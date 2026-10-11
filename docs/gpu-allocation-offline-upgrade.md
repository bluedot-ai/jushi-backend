# GPU/NPU 历史回看与自然月对比：内网增量升级

## 1. 范围与数据口径

开发目录为 `/opt/software/jushi` 和 `/opt/software/jushiapi-ui-test`。本次先交付原部署记录中的 x86-64 测试环境（`linux/amd64`）；后续华为 ARM64 生产环境需单独构建 `linux/arm64` 镜像，不能直接使用 x86 镜像。

新增 `gpu_allocation_snapshot` 集群级快照表，不替换已有 `resource_snapshot` 或 `accelerator_metric_sample`，不新增容器。默认每 300 秒采样，保留当前月及前六个完整自然月；例如 2026-10-10 的清理边界为 2026-04-01 00:00:00（北京时间）。

支持 NVIDIA GPU、华为 Ascend NPU 以及两者混合集群。前端可选择“全部 / NVIDIA / 华为”，当前指标、趋势和月份对比均使用同一个范围。全部范围按物理加速卡数量合并，不表示不同型号设备算力相等，也不换算 TFLOPS 或旧“算力单位”。总容量与可分配数量分开展示；分配率仅统计同一批 Ready、可调度节点上的已分配数量 / 可分配数量。NotReady、维护节点不进入分配率分母。

NVIDIA 默认资源为 `nvidia.com/gpu`，华为默认资源为 `huawei.com/Ascend310P`。现场若使用其他整卡资源名，需要明确配置和核验，不能静默漏算。共享、切分、虚拟资源或多芯片设备与物理卡映射有歧义时不输出估算结果；`vdie_id` 是身份标签，不能仅凭名称认定为虚拟卡。原设备详情和短期单卡历史保留，不改变其旧接口。

当前前端展示总容量、资源分配率、显存使用率三项；显卡计算利用率及对应历史对比行和趋势选项已隐藏，后端仍采集、保存并通过接口返回这些指标。显存监控不满足完整窗口要求时，可明确标注为“最近观测”，说明覆盖范围、原始时间和延迟；这些展示值不进入正式历史统计。

利用率采用过去 5 分钟的真实监控平均值，显存使用率来自真实设备显存，而非 Pod 申请显存。查询窗口以实际采集时间结束；`sample_slot` 只负责周期去重。NVIDIA 接入 DCGM，华为接入 NPU Exporter。全部范围的利用率按物理卡数加权，显存使用率按显存容量加权；混合集群任何在用厂商的监控不完整时，全部范围对应指标为空，不能只用有数据的厂商冒充全量。

缺失或不完整数据返回空值，不显示为 0。两个厂商可分别配置抓取周期、原始指标选择器和显存单位，模板见 `docs/gpu-allocation.env.example`。默认 NVIDIA 显存单位 MiB、Ascend 显存单位 MB，必须与现场 exporter 一致。采集检查每张卡的样本数量、首尾跨度、最新样本年龄及内部缺口；新卡少量监控点不能立即标为完整。当前月只统计已过去时间；上线前没有保存的分配数量不能反向补齐。

每个集群每 5 分钟保存 `all / nvidia / ascend` 三条记录，表共 20 个字段，仅在原 19 字段设计上增加 `vendor`。旧 NVIDIA 记录保留为 `nvidia`、原计算版本不变，不冒充全部历史；同一月混用计算版本或两个月口径不同，不输出变化百分比，页面提示不可直接比较。

## 2. 离线包内容

- 对应架构的前后端新镜像、版本标识和校验和；
- 旧单卡历史建表、审计统计索引、新集群快照建表及 `vendor` 升级，共四份迁移 SQL；
- `scripts/apply-gpu-history-upgrade.sh` 及其调用的迁移脚本；
- 本文及 `docs/gpu-allocation.env.example`。

在能取得基础镜像和依赖的打包环境执行；客户内网仅导入镜像，不在线下载依赖。例如：

```bash
cd /opt/software/jushi
sh scripts/package-gpu-history-offline.sh amd64 gpu-history-v2

# 后续 ARM64 交付：必须先准备支持 arm64 的 builder 或 ARM 原生构建机。
# 名称叫 arm64-builder 并不表示它实际支持 arm64，先检查 Platforms。
docker buildx inspect --bootstrap
sh scripts/package-gpu-history-offline.sh arm64 gpu-history-v2
```

脚本按架构构建、核验并导出镜像，附带 SQL、脚本、非敏感配置模板和 `SHA256SUMS`；不打包真实 env 或 MySQL 镜像。传输后先运行 `sha256sum -c SHA256SUMS`，再按已有 `docker load` 流程导入压缩镜像。不要覆盖现场环境文件、Nginx 配置或业务端口。打包脚本不擅自安装特权模拟器；ARM 镜像构建和现场华为监控须另行验收。

## 3. 升级前检查与迁移

备份数据库、现场配置及正在运行的前后端镜像版本，记录业务 Pod、Service 和 NodePort。备份命令见原离线升级说明；使用客户批准的数据库账号，不在命令或交付包中写入真实密码。

确认采集账号可以只读列出集群节点及所有命名空间的 Pod：

```bash
kubectl auth can-i list nodes --as=system:serviceaccount:algorithm:jushi-deploy-api
kubectl auth can-i list pods --all-namespaces --as=system:serviceaccount:algorithm:jushi-deploy-api
```

若无权限，由现场管理员审核授予必要只读权限。不能只采集 `algorithm` 命名空间就宣称是整个集群的分配率。继续使用已经验证过的现场 Prometheus 地址，不照抄其他环境的地址或端口。

已有 MySQL 数据目录时，更新镜像不会自动执行 `init.sql`。备份后先显式运行幂等增量迁移：

```bash
cd /opt/software/jushi
sh scripts/apply-gpu-history-upgrade.sh
```

该脚本创建缺失的单卡历史表，补审计统计索引，创建新快照表，并为已存在的旧快照表增加 `vendor`、升级唯一索引。不删除历史记录，可重复执行。审计索引属于既有业务表的增量索引；大表首次建索引仍需现场确认锁等待和执行窗口。若应用账号无 DDL 权限，由数据库管理员执行 SQL，不长期扩大应用账号权限。若旧单卡表和审计索引已确认完整，也可只运行 `sh scripts/apply-gpu-allocation-migration.sh`（包含新快照 001、002 两份迁移）。

## 4. 分两阶段发布

第一阶段：导入后端新镜像，在现场 `docker-compose.backend.offline.yml` 中将 `jushi-api.image` 设置为已核验的新版本，并保留原有配置。确认实际读取的环境文件，按 `docs/gpu-allocation.env.example` 添加开关，**不要覆盖整个环境文件**。

```bash
cd /opt/software/jushi
docker compose -f docker-compose.backend.offline.yml up -d --no-build --no-deps jushi-api
```

本命令使用本地离线镜像，不带 `--build`；执行前检查服务配置，确保 MySQL 的镜像、配置和挂载未改变。不得执行整套 `down`。现场若不是原生 Docker Compose、缺少这些参数，先按原部署运行时核验等价的单服务更新命令，不能盲目照抄。

第二阶段：验证后端连续入库至少两个采样周期，再导入前端镜像，在 `docker-compose.frontend.offline.yml` 中更新前端镜像，保留现场 Nginx、网络及端口。使用原部署记录中实际生效的环境文件执行：

```bash
cd /opt/software/jushiapi-ui-test
BACKEND_NETWORK=jushi_default FRONTEND_PORT=18000 \
docker compose --env-file .env.example -f docker-compose.frontend.offline.yml up -d --no-build --no-deps jushi-frontend
```

如现场使用 `.env`，则改用实际文件，不能为了匹配示例替换现有配置。算法 Pod、Deployment、Service 和固定业务端口均不改动；管理页面/API 在单实例切换时可能短暂不可用，业务算法不会因管理镜像切换被主动停止。

## 5. 验证和回退

- 关闭浏览器，连续两个采样周期仍有新快照入库；同一集群、厂商范围、时间桶没有重复记录；
- 当前与历史的厂商选择同步；纯华为环境能显示 NPU 容量、分配率和显存使用率，页面不再展示显卡计算利用率；
- 混合集群后端按卡数、显存容量分别正确加权；页面历史支持两个自然月、日趋势、卡时及分配/显存数据完整率，后端仍保留三类完整率；
- 无有效显存监控时显示“暂无数据”，部分或延迟的最近观测必须明确标注；历史缺口不补零、不跨缺口累计卡时；
- NotReady/维护节点不混入可分配数量；共享资源不能冒充物理卡；
- 新接口未登录返回 401，手动采集只允许管理员；
- 现有登录、实例、单卡趋势和业务端口正常。

```sql
SELECT cluster_name, vendor, calculation_version, COUNT(*) AS sample_count,
       MIN(sampled_at) AS first_sample, MAX(sampled_at) AS latest_sample
FROM gpu_allocation_snapshot GROUP BY cluster_name, vendor, calculation_version;

SELECT cluster_name, vendor, sample_slot, COUNT(*) AS duplicate_count
FROM gpu_allocation_snapshot
GROUP BY cluster_name, vendor, sample_slot HAVING COUNT(*) > 1;
```

异常时将 `GPU_ALLOCATION_HISTORY_ENABLED=false`，恢复旧前后端镜像和现场配置。新表保留，不删除历史记录；不重启 MySQL，不操作客户算法资源。测试环境验收完成后再按客户批准流程发布，不将开发验证视为现场验收。
