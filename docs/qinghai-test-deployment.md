# 聚时仓库同步与青海测试环境部署

本文档记录截至 2026-08-25 已验证的仓库关系、青海测试环境部署方式、环境变量策略和 Prometheus 接入结论。文档中的地址均使用占位符；真实密码、Token 和客户地址只保存在受控环境配置中。

## 1. 仓库与分支基线

| 工程 | 源仓库与开发分支 | 私有交付仓库与交付分支 |
| --- | --- | --- |
| 后端 | `boshilin123/jushi:main` | `bluedot-ai/barm-backend:main` |
| Vue 3 前端 | `DoisLONG/jushiapi-ui-test:dige/logo` | `bluedot-ai/barm-ui:main`、`dige/logo` |

前端源仓库的 `main` 与 `dige/logo` 是两套没有共同祖先的 Git 历史，不能把 GitHub 的 ahead/behind 数字理解为代码新旧。当前实际开发、构建和部署均以 `dige/logo` 为准。

青海测试环境已做过产物级验证：运行容器中的 `index.html`、JS、CSS 哈希与 `dige/logo@7402bc4` 的构建产物完全一致。私有交付仓库的 `main` 已覆盖为同一条 `dige/logo` 交付历史。

## 2. 本地 Remote 约定

后端：

```text
origin          源仓库 boshilin123/jushi
barm-backend    私有交付仓库 bluedot-ai/barm-backend
```

前端：

```text
origin          源仓库 DoisLONG/jushiapi-ui-test
barm-ui         私有交付仓库 bluedot-ai/barm-ui
```

不要用原后端仓库的 Deploy Key 访问 BARM 仓库。Deploy Key 通常只对绑定的单个仓库生效；BARM 仓库使用具备相应组织权限的账户密钥或单独配置的仓库密钥。

## 3. 环境文件策略

当前环境文件：

- 后端：`.env.example`
- 前端：`.env`

规则：

1. 源仓库开发分支继续通过 `.gitignore` 忽略真实环境文件。
2. 按交付要求，真实环境文件只在 BARM 私有交付分支中保留一份受跟踪版本。
3. `.gitignore` 只对未跟踪文件生效。文件一旦进入私有仓库历史，后续修改仍可能被 Git 识别并提交。
4. 测试服务器只需要 Pull 权限；服务器仓库应禁用 Push URL，避免误推送。
5. 从 BARM 私有仓库直接克隆到服务器时，可以在每个服务器克隆中执行一次：

```bash
git update-index --skip-worktree .env.example  # 后端
git update-index --skip-worktree .env          # 前端
```

恢复跟踪：

```bash
git update-index --no-skip-worktree .env.example
git update-index --no-skip-worktree .env
```

`skip-worktree` 只作用于当前克隆，不能代替权限控制或密钥管理。远端若再次修改同一环境文件，Pull 仍可能需要人工处理。

## 4. 青海测试服务器目录与拉取

实际目录：

```text
/home/qhadmin/jushi
/home/qhadmin/jushiapi-ui-test
```

由 `root` 执行 Git 和容器命令，因此不需要为了拉取把仓库改成 `qhadmin` 所有。

后端：

```bash
cd /home/qhadmin/jushi
git fetch --prune origin
git pull --ff-only origin main
```

前端：

```bash
cd /home/qhadmin/jushiapi-ui-test
git fetch --prune origin
git pull --ff-only origin dige/logo
```

青海环境的 `docker-compose.frontend.yml` 和 `nginx.conf` 包含服务器专用的 `extra_hosts`、`/tts` 代理、上传大小及超时设置。拉取前必须备份，拉取后再合并或恢复；不要直接用 `git restore` 丢弃而不留备份。

推荐把服务器备份放在仓库外，例如：

```text
/root/jushi-deploy-config/backend/
/root/jushi-deploy-config/frontend/
```

## 5. 容器运行时兼容性

青海测试服务器的 `/usr/local/bin/docker` 实际调用 nerdctl。执行 Compose 时已观察到以下警告：

```text
Ignoring: service jushi-mysql: [HealthCheck]
Ignoring: service jushi-api: [EnvFiles]
Ignoring: service jushi-api: depends_on ... condition service_healthy
```

这意味着：

- 不能只依赖服务级 `env_file` 注入后端环境变量。
- 不能只依赖 `depends_on.condition: service_healthy` 保证 MySQL 就绪。
- 部署后必须进入容器验证关键环境变量。

在该环境中，关键变量应通过 Compose 的 `environment` 显式映射，并使用 CLI `--env-file` 为插值提供值。例如：

```yaml
services:
  jushi-api:
    environment:
      PROMETHEUS_BASE_URL: ${PROMETHEUS_BASE_URL}
      PROMETHEUS_TOKEN: ${PROMETHEUS_TOKEN:-}
      PROMETHEUS_TIMEOUT_SECONDS: ${PROMETHEUS_TIMEOUT_SECONDS:-5}
      PROMETHEUS_GPU_USAGE_ENABLED: ${PROMETHEUS_GPU_USAGE_ENABLED:-true}
```

数据库、PaaS、Kubernetes 等后端必需变量也应采用相同方式显式映射，不能假定 nerdctl 已加载服务级 `env_file`。

## 6. 后端部署

以下命令以 `docker-compose.backend.yml` 已按上一节显式映射后端必需环境变量为前提。如果仍出现 `[EnvFiles]` ignored 警告，应先补齐映射并通过容器内环境检查，不要直接发布。

代码或依赖发生变化时：

```bash
cd /home/qhadmin/jushi
docker compose -f docker-compose.backend.yml --env-file .env.example up -d --build
docker compose -f docker-compose.backend.yml --env-file .env.example ps
```

仅修改环境变量时不需要构建镜像：

```bash
cd /home/qhadmin/jushi
docker compose -f docker-compose.backend.yml --env-file .env.example \
  up -d --force-recreate jushi-api
```

验证关键环境变量时只输出非敏感字段：

```bash
nerdctl exec jushi-api python -c \
  'import os; print(os.getenv("PROMETHEUS_BASE_URL"))'
```

禁止在终端记录、文档或工单中输出 Token、密码和完整环境文件。

## 7. 前端部署

```bash
cd /home/qhadmin/jushiapi-ui-test
docker compose -f docker-compose.frontend.yml --env-file .env up -d --build
docker compose -f docker-compose.frontend.yml --env-file .env ps
```

当前前端部署配置还包含青海环境专用项：

- Compose：`host.docker.internal` 的 `extra_hosts` 映射。
- Nginx：`/tts`、长连接代理、上传大小和超时设置。

构建完成后至少验证：

```bash
curl -I http://127.0.0.1:18000/
curl -i http://127.0.0.1:18000/api/system/health
nerdctl exec jushi-frontend nginx -t
```

## 8. Prometheus 接入结论

后端通过以下接口查询 Prometheus：

```text
/api/v1/query
/api/v1/query_range
```

青海环境实测应使用 Kubernetes 中 Prometheus Service 的 `9090` 对应 NodePort `32582`：

```env
PROMETHEUS_BASE_URL=http://<青海控制节点内网IP>:32582
PROMETHEUS_TOKEN=
PROMETHEUS_TIMEOUT_SECONDS=5
PROMETHEUS_GPU_USAGE_ENABLED=true
```

选择该端口的依据：

- 查询 API 返回 `200` 和 `status=success`。
- 后端容器可以访问。
- `DCGM_FI_DEV_FB_TOTAL`、`DCGM_FI_DEV_FB_USED`、`DCGM_FI_DEV_GPU_UTIL` 均能返回数据。
- `job="nvidia-dcgm-exporter"` 与代码选择器一致。
- 指标包含代码所需的 `node`、`UUID`、`gpu`、`device`、`modelName` 等标签。

其他候选端口的实测结论：

- `30909`：缺少 `DCGM_FI_DEV_FB_TOTAL`，无法构造完整物理 GPU 卡片。
- `31891`：不是 Prometheus Query API，返回 `404`。
- `31439`：代理返回 `403`，当前空 Token 配置不能使用。
- HAMI monitor 端口：Exporter 端点，不是 Prometheus Query API。

## 9. 镜像构建性能

若构建长时间停在：

```text
FROM docker.m.daocloud.io/python:3.11-slim
```

瓶颈是基础镜像下载，不是项目构建上下文。环境变量变更不要使用 `--build`。真正需要构建时，优先使用青海内网镜像仓库或从联网环境执行 `nerdctl save/load` 离线导入。

Python 依赖安装尚未开始前，不要把基础镜像下载慢误判为 `pip install` 慢。

## 10. BARM 私有仓库同步

后端代码更新后：

```bash
cd /opt/software/jushi
git switch sync/barm-backend-main
git merge main
git push barm-backend
git switch main
```

前端代码更新后：

```bash
cd /opt/software/jushiapi-ui-test
git switch sync/barm-ui-dige-logo
git merge dige/logo
git push barm-ui
git switch dige/logo
```

`barm-ui/main` 与 `barm-ui/dige/logo` 当前指向同一交付提交。默认的 `git push barm-ui` 映射为：

```text
sync/barm-ui-dige-logo -> main
```

环境文件已经存在于 BARM 专用同步分支。以后合并源分支代码时不需要重新复制或提交环境文件，除非负责人明确要求更新私有仓库中的环境基线。

## 11. 完成检查

后端：

```bash
git status --short --branch
docker compose -f docker-compose.backend.yml --env-file .env.example config --quiet
docker compose -f docker-compose.backend.yml --env-file .env.example ps
```

前端：

```bash
git status --short --branch
docker compose -f docker-compose.frontend.yml --env-file .env config --quiet
docker compose -f docker-compose.frontend.yml --env-file .env ps
```

最终确认：

```bash
nerdctl ps
```

预期至少包含 `jushi-api`、`jushi-mysql` 和 `jushi-frontend`，且前端页面、健康检查、Swagger、Prometheus GPU 查询均可用。
