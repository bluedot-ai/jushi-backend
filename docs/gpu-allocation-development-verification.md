# GPU/NPU 历史分析：开发验证记录

## 2026-10-11 当前源码更新

- 当前查询增加明确标注的“最近观测”显存展示，保留覆盖数量、原始采样时间、延迟及缺失节点说明；部分或延迟观测不写入正式历史统计，不修改现场时钟或 Prometheus 配置。
- 资源中心顶部保留总容量、资源分配率、显存使用率三项；移除前端显卡计算利用率、对应月度对比及完整率行、趋势切换项。后端利用率采集、存储、计算和接口字段继续保留。
- 显卡列表按真实 UUID、原始卡序号和逐卡型号展示；去掉逐行显存“估算”字样，但仍注明节点容量折算来源及未识别卡容量待确认。未知逐卡使用量仍显示“-”，不补零。
- 全量 192 项后端测试、22 项前端测试、Vue 生产构建通过；本机浏览器模拟验证通过三项指标、厂商切换、历史展示及桌面/移动端布局，无页面脚本错误。
- 上述为源码验证，不代表新镜像已发布或客户现场验收；不增加依赖、必填环境变量、SQL 或数据库字段。下文为前一版的开发记录。

## 2026-10-10 更新范围

已按方案 B 实现：保留当前月及前六个完整自然月。后端新增 `gpu_allocation_snapshot` 表和定时采集、当前指标、趋势、月份对比及管理员手动采集接口；前端增加当前四项指标、自然月对比和同步厂商筛选。

新统计支持 NVIDIA GPU、华为 Ascend NPU，覆盖混合集群和纯华为场景。`all / nvidia / ascend` 分别保存和查询；全部范围为物理设备数量口径，不代表等效算力。保留原设备详情、单卡趋势及其接口，不把虚拟共享数量或旧算力单位混入新分配率。现场须确认整卡资源名与 exporter 身份、单位和抓取周期。

## 本机验证与限制

### 采集误判修复与开发镜像切换

- 同一 NVIDIA 整卡 UUID、同一采集目标的业务归属标签变化会产生多条原始序列。现仅合并三个明确的业务标签变更片段，保留真实抓取时间和完整性检查；不同目标、冲突值、缺口和缺失采集源身份均不放行。
- 华为插件发布的零数量切分资源名称不再误判为实际切分；正数、非法数量或启用共享标签仍拒绝。
- NVIDIA 陈旧数量标签通过新鲜整卡总显存身份独立核验，分配数量恢复不再依赖利用率窗口完整。离线节点缺失监控时，全部厂商利用率仍为空，不用部分结果代替全体。
- 当前源码在现有 Python 3.11 镜像中断网、只读挂载执行全量 **175 项后端单元测试通过**。新增回归覆盖七段业务标签、15 秒真实抓取、冲突来源/值、重复片段、零数量华为切分项以及混合厂商和离线节点。
- 本次不新增依赖、环境变量、SQL 或数据表字段；现有抓取周期配置必须匹配现场实际值（15 秒抓取时 NVIDIA 配置设为 15）。不修改真实环境文件、Kubernetes 资源或历史缺失记录。以下前一版真实容器记录不代表测试环境发布。
- 2026-10-10 21:44 开发容器已切换到用户构建的最新 `amd64` 镜像：后端 `f188820868a0`，前端 `d883e742e0c5`；各自的 `latest` 与 `amd64` 相同。最新后端镜像中的采集、分配统计和逐卡型号模块哈希与当前源码一致。新增 `docker-compose.backend.dev-image.yml` 和相邻前端仓库的 `docker-compose.frontend.dev-image.yml`，仅覆盖管理服务的镜像，固定使用 x86 标签，避免 ARM 打包改动 `latest` 后误更新开发容器。
- 页面、健康接口、Swagger 均为 HTTP 200；未登录访问历史当前指标接口返回 401。端口和挂载保持不变；MySQL 启动时间未改变，不操作其他项目服务。
- 已备份后删除前后端各三组旧开发镜像（`before-gpu-history-20261010`、`gpu-allocation-dev-20261010`、`gpu-history-dual-dev-20261010`），删除前确认没有容器引用。备份保存在 `/opt/software/offline-images/dev-image-rollback-20261010.Mlv0g3/jushi-old-development-images.tar`，权限 600，可通过 `docker load -i` 恢复；不要将回退备份作为客户交付包。
- 实测 `arm64-builder` 最小 ARM 构建成功，容器内执行 `uname -m` 返回 `aarch64`。BuildKit 自带 `buildkit-qemu-aarch64`，即使 `Platforms` 未列 ARM，仍能完成该最小构建；不能据此列表否定 ARM 构建能力。宿主机直接运行 ARM 容器仍报 `exec format error`，与 BuildKit 内置模拟构建是两回事。本次未安装宿主机模拟器，也未构建或导出完整 ARM 前后端交付镜像，尚未进行生产 ARM 实卡验收。
- 本次未部署至测试/生产服务器，未 Git 提交或推送。

### 前一版功能验证记录

- 后端语法编译、全量 **159 项单元测试**通过，并在新镜像实际 Python 3.11 依赖环境中断网、只读挂载仓库复测通过；包含混合厂商、纯 Ascend、华为缺失不能冒充全量、显存 MB/MiB 换算、虚拟设备拒绝、厂商筛选、旧版本兼容、数据完整率及新路由鉴权。测试发现阶段关闭后台线程，执行缓存行为测试时恢复默认开关，避免人为关闭缓存造成误报。
- Vue 生产构建、**10 项指标计算测试**通过；浏览器模拟验证覆盖厂商切换竞态、月份选择、缺失/零值、统计版本不兼容、趋势断线、接口异常和移动端。
- 真实开发容器中，三个厂商范围的趋势和月份对比均返回 200；未登录返回 401，非法厂商返回 400；华为当前接口返回明确的数据源不可用诊断，而非异常栈。
- 健康检查、Swagger 页面和 OpenAPI JSON 均返回 200；四个新接口存在，三个读取接口的 `vendor` 枚举均为 `all / nvidia / ascend`。
- 真实浏览器加载新镜像，确认四张指标卡、七个月选项、11 行对比项；切换历史范围到 Ascend 后，当前范围同步，三个读取接口均携带 `vendor=ascend`，无 JavaScript 运行异常，未注入模拟数据。
- 已备份开发数据库，实际执行完整升级脚本两次。旧快照表从 19 列升至 **20 列**，迁移后原 21 条记录全部保留为 `nvidia / physical-gpu-v1`；唯一索引改为 `(cluster_name, vendor, sample_slot)`。重复迁移无错误、无重复索引。完整升级也检查旧单卡表和审计统计索引；MySQL 未重启，启动时间保持不变。
- 新后台任务无需打开页面、无需手动采集，已观察到 **17:14:57、17:19:57 两个自动周期**，每个周期保存 `all / nvidia / ascend` 三条 `physical-accelerator-v2` 快照，无重复时间桶。唯一索引下同一厂商当前时间桶再次采样会更新原记录，包括发布时尚未结束的旧版本时间桶；更早的旧记录不改写。开发 Kubernetes 节点查询仍返回超时（504），因此新快照资源和监控字段为 `NULL`，`allocation_valid=false`，只记录缺口，不计入有效月度统计。恢复连接后还需现场验证真实 NVIDIA/Ascend 数据及至少两个连续有效周期，不能把模拟测试作为实卡验收。
- 新代码没有 NVIDIA/Ascend 本地 SDK 或架构相关扩展依赖；未新增软件依赖。当前开发构建器仅支持 amd64/386，即使名称含 arm64 也不代表支持 ARM；ARM64 标准镜像构建、真实华为设备采样尚未验证。
- 独立只读代码审查未发现明确 P0/P1 阻断项；另外复测 52 项采集/NPU 模拟测试及三份脚本语法通过。该审查不替代实卡、ARM 和客户发布验收。
- 没有连接或发布到 x86 测试服务器，没有 Git 提交或推送。测试及客户验收不能以本机测试代替。

## 当前开发更新命令

后端：

```bash
cd /opt/software/jushi
docker compose -p jushi -f docker-compose.backend.yml \
  -f docker-compose.backend.dev-image.yml \
  up -d --no-build --no-deps jushi-api
```

前端（沿用本机实际 `.env`）：

```bash
cd /opt/software/jushiapi-ui-test
docker compose -p jushiapi-ui-test --env-file .env \
  -f docker-compose.frontend.yml -f docker-compose.frontend.dev-image.yml \
  up -d --no-build --no-deps jushi-frontend
```

以上只适用于已核验的开发 Docker Compose；客户运行时需按现场部署文件和参数支持情况独立验证。离线包使用明确的 `amd64` 或 `arm64` 标签，不需要在源开发机临时将 ARM 重打成 `latest`。

## 前一版开发镜像与回退记录

前一版开发验证使用的两个镜像为（现已清理，保留在回退备份中）：

```text
jushi-jushi-api:gpu-history-dual-dev-20261010
jushiapi-ui-test-jushi-frontend:gpu-history-dual-dev-20261010
```

两者已核验为 `linux/amd64`。开发验证镜像复用原镜像的依赖环境并加入新后端代码或前端构建产物；仓库标准 Dockerfile 未改动。临时开发 Compose override 位于 `/tmp/jushi-dual-vendor.GHCJok/`，仅指定新镜像，未修改真实 env、Nginx、网络或端口。数据库备份和真实浏览器截图也在此私有临时目录，数据库备份权限为 600，不能打入客户交付包。后续常规更新可按原命令重新构建；不要把临时 override 当作客户部署文件。

需要回退旧版本时，先从上述镜像备份导入，再选择备份中的明确版本标签；不要把当前 `latest` 当成旧版本。使用原 Compose 文件、原环境文件，以 `--no-build --no-deps` 仅恢复 `jushi-api` 和 `jushi-frontend`。开发主机支持 Docker Compose 原生参数；不要照抄到不支持这些参数的测试运行时。新表保留，不删除数据，不操作算法 Pod、Deployment 或 Service。

客户 x86 离线发布按 [增量升级说明](gpu-allocation-offline-upgrade.md) 独立构建、校验和验收。配置模板已包含旧资源趋势缓存、旧单卡历史以及新 GPU/NPU 历史开关；必须增量补入现场实际读取的环境文件。`scripts/package-gpu-history-offline.sh` 提供 amd64/arm64 标准打包流程，本次未导出正式离线交付包。

## 主要代码位置

- `backend/modules/resources/gpu_allocation_collector.py`：独立定时采集及方案 B 清理边界。
- `backend/modules/resources/gpu_allocation_providers.py`：NVIDIA/Ascend 物理身份、监控覆盖、单位与独立配置。
- `backend/modules/resources/gpu_allocation_repository.py`：幂等保存与限量查询、清理。
- `backend/modules/resources/gpu_allocation_stats.py`：时间加权趋势、月份对比及独立完整率。
- `backend/modules/resources/gpu_allocation_routes.py`：三个只读接口及管理员手动采集。
- `backend/db/migrations/20261010_001_create_gpu_allocation_snapshot.sql`：新增表迁移；同步到 `backend/db/init.sql`。
- `backend/db/migrations/20261010_002_add_gpu_allocation_vendor.sql`：兼容旧表的厂商范围升级。
- `scripts/apply-gpu-history-upgrade.sh`：旧单卡表、审计索引与新集群历史统一增量迁移。
- `/opt/software/jushiapi-ui-test/src/views/resources/GpuAllocationHistory.vue`：月度对比及日趋势。
- `/opt/software/jushiapi-ui-test/src/views/resources/Resources.vue`：当前四项 GPU 指标与旧设备视图。
