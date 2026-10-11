"""Physical GPU allocation history contract (not vGPU or theoretical FLOPS)."""


def _query(name, description, pattern=None, default=None, enum=None):
    schema = {"type": "string"}
    if pattern:
        schema["pattern"] = pattern
    if default:
        schema["default"] = default
    if enum:
        schema["enum"] = enum
    return {"name": name, "in": "query", "description": description,
            "required": name in {"start", "end", "base_month", "compare_month"}, "schema": schema}


_COMMON = [
    _query("cluster_name", "已配置的集群名称；不能通过此参数切换 Kubernetes 连接"),
    _query("vendor", "物理加速卡厂商范围；全部为设备数量口径，不代表等效算力", default="all", enum=["all", "nvidia", "ascend"]),
    _query("timezone", "自然月和采集时间统一采用北京时间", default="Asia/Shanghai", enum=["Asia/Shanghai"]),
]
_RESPONSES = {
    "200": {"description": "is_success=true，data 内返回指标、数据完整率和计算口径；缺失指标为 null，不补 0"},
    "400": {"description": "参数错误、月份超出当前月及前六个完整自然月范围"},
    "401": {"description": "未登录或登录已过期"},
    "503": {"description": "数据库不可用或尚未执行新表迁移"},
}

GPU_ALLOCATION_PATHS = {
    "/api/resources/gpu-allocation/current": {
        "get": {
            "tags": ["Resources"],
            "summary": "NVIDIA GPU / 华为 Ascend 当前分配和真实利用情况",
            "description": "只读查询，不触发入库。支持 all、nvidia、ascend；全部范围不能用单一厂商的部分监控代替。总容量和可分配数量分开展示；分配率分子、分母来自同一批 Ready 且可调度节点。同一物理设备、同一采集源的业务标签分段可按真实采样时间合并，采集源冲突或缺失仍拒绝。华为切分资源仅在 capacity 与 allocatable 均为零或未声明时忽略；实际切分或共享仍拒绝。NVIDIA 陈旧数量标签可经新鲜整卡身份独立核验，不要求利用率窗口完整。原 gpu_utilization_avg/gpu_memory_utilization 仍为严格过去 5 分钟统计，不完整时为 null。新增 observed_monitor 是独立的最近观测展示：复用原始窗口内每卡最后一个有效点，保留原始采样时间，分别提供覆盖、延迟、缺失节点及诊断；不超过 300 秒的部分或延迟样本可展示，但不得作为完整 5 分钟平均或写入正式历史统计。不增加监控请求，不修改客户时间或 Prometheus 配置。sampled_at 是本次查询时间，不是最近观测的原始采样时间。",
            "parameters": [_COMMON[1]],
            "responses": {
                "200": {"description": "data 含 vendor、vendors（各厂商快照）、gpu_capacity、gpu_allocatable、gpu_allocated、allocation_rate、gpu_utilization_avg、gpu_memory_utilization、sampled_at、allocation_valid、monitor_valid、diagnostics 和 observed_monitor；observed_monitor.utilization/memory 各含 value、expected_cards、observed_cards、fresh_cards、delayed_cards、missing_cards、status、oldest_sample_at、latest_sample_at、maximum_age_seconds、nodes、issues；原始时间为带 +08:00 的 ISO 时间。字段前缀 gpu 为兼容命名，ascend 表示 NPU 设备指标"},
                "400": _RESPONSES["400"],
                "401": _RESPONSES["401"],
                "503": _RESPONSES["503"],
            },
        }
    },
    "/api/resources/gpu-allocation/trend": {
        "get": {
            "tags": ["Resources"],
            "summary": "GPU 历史分配与利用趋势",
            "description": "从独立 gpu_allocation_snapshot 表读取集群级历史，按小时或日加权统计；数据缺口不跨越累计卡时。起始日期包含，结束日期不包含。上线前未保存的分配数据不做反推。",
            "parameters": _COMMON + [
                _query("start", "起始日期，例如 2026-10-01", r"^\d{4}-\d{2}-\d{2}$"),
                _query("end", "不包含的结束日期，例如 2026-11-01", r"^\d{4}-\d{2}-\d{2}$"),
                _query("granularity", "趋势粒度", default="day", enum=["day", "hour"]),
            ],
            "responses": _RESPONSES,
        }
    },
    "/api/resources/gpu-allocation/compare": {
        "get": {
            "tags": ["Resources"],
            "summary": "GPU 资源自然月对比",
            "description": "返回 data.base、data.comparison、data.changes、vendor 和 comparison_compatible。按厂商或全部范围查询，全部只读取专用 all 快照，不把旧 NVIDIA 单厂商历史当成全体。月平均分配率=已分配卡时/可分配卡时×100%；卡时为资源占用时间，不代表等效算力。分配、利用率、显存完整率分别计算，当前月仅统计已过去时间；跨 physical-gpu-v1 与 physical-accelerator-v2 的月份不直接计算变化。",
            "parameters": _COMMON + [
                _query("base_month", "基准自然月，例如 2026-09", r"^\d{4}-\d{2}$"),
                _query("compare_month", "对比自然月，例如 2026-10", r"^\d{4}-\d{2}$"),
            ],
            "responses": _RESPONSES,
        }
    },
    "/api/internal/gpu-allocation/collect": {
        "post": {
            "tags": ["Resources"],
            "summary": "管理员手动触发 GPU 历史采集",
            "description": "需要有效管理员 Bearer 登录令牌，不是免鉴权接口。不接受客户端上传指标、时间或集群连接配置；同一集群和采样时间桶幂等写入。后台定时任务直接调用采集函数，不依赖登录或页面。",
            "responses": {
                **_RESPONSES,
                "403": {"description": "非管理员，不执行采集或数据库写入"},
            },
        }
    },
}
