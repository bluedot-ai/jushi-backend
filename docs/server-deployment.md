# 服务器部署说明

本文档记录聚时项目部署到服务器的推荐方式、端口规划、构建步骤、验证命令和常见问题处理。

## 1. 部署方式

推荐使用 Docker Compose 部署整套服务：

- `jushi-frontend`：前端 nginx，负责静态页面和 `/api/` 反向代理。
- `jushi-api`：后端 Flask 主服务，包含端口避让接口 `/api/port-list/*`。
- `jushi-mysql`：本项目独立 MySQL。

不建议复用服务器上已有的 `yolo-anything-mysql`。原因是两个项目的数据、账号、初始化脚本和生命周期不同，复用同一个 MySQL 容器会增加误删数据和配置冲突风险。

## 2. 端口规划

推荐只对外开放前端端口：

| 服务 | 容器内端口 | 宿主机端口 | 访问范围 |
| --- | --- | --- | --- |
| `jushi-frontend` | `80` | `18000` | 对外开放 |
| `jushi-api` | `8080` | 不映射 | Docker 内网 |
| `jushi-mysql` | `3306` | 不映射 | Docker 内网 |

服务器安全组或防火墙只需要放行：

```bash
18000/tcp
```

MySQL 不需要对外放行。Compose 内部服务访问 MySQL 时使用服务名和容器端口：

```text
jushi-mysql:3306
```

这里的 `3306` 是 Docker 内部网络端口，不等于占用宿主机 `3306`。只有写了 `ports: "3306:3306"` 才会映射到宿主机。

## 3. 环境变量

服务器环境变量文件可以命名为 `.env.example` 或 `.env.server`，但 `docker-compose.yml` 中的 `env_file` 必须和实际文件名一致。

示例：

```env
APP_ENV=production
SECRET_KEY=BlueDot@123

MYSQL_HOST=jushi-mysql
MYSQL_PORT=3306
MYSQL_DATABASE=jushi
MYSQL_USER=jushi
MYSQL_PASSWORD=jushi_pass

DCE_API_BASE=https://10.11.20.71:31123/apis/kpanda.io/v1alpha1
DCE_CLUSTER=kpanda-global-cluster
DCE_NAMESPACE=algorithm
DCE_TOKEN="替换为实际 token"
```

注意：

- `MYSQL_HOST` 在 Compose 内部必须是 `jushi-mysql`。
- 端口避让接口由 `jushi-api` 内部直接提供，不再需要独立 `PORT_LIST_API_BASE`。
- `DCE_TOKEN`、`SECRET_KEY` 不要提交到公开仓库；如果已经暴露，需要及时更换。

## 4. 推荐 docker-compose 配置

服务器上推荐使用如下结构。核心点是只映射前端 `18000:80`，其他服务不映射到宿主机。

```yaml
services:
  jushi-frontend:
    build:
      context: ./ui
    ports:
      - "18000:80"
    depends_on:
      - jushi-api
    restart: unless-stopped

  jushi-api:
    build:
      context: ./backend
    env_file:
      - .env.example
    depends_on:
      jushi-mysql:
        condition: service_healthy
    restart: unless-stopped

  jushi-mysql:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: root_pass
      MYSQL_DATABASE: jushi
      MYSQL_USER: jushi
      MYSQL_PASSWORD: jushi_pass
    volumes:
      - ./mysql/data:/var/lib/mysql
      - ./backend/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    restart: unless-stopped
```

如果服务器拉取 Docker Hub 镜像超时，可以把 Dockerfile 的基础镜像改成国内镜像源。

后端 `backend/Dockerfile`：

```dockerfile
FROM docker.m.daocloud.io/python:3.11-slim
```

前端 `ui/Dockerfile`：

```dockerfile
FROM docker.m.daocloud.io/node:20-alpine AS build
...
FROM docker.m.daocloud.io/nginx:1.27-alpine
```

## 5. 构建前清理

如果本地或服务器目录里存在 `ui/node_modules`，建议先删除，避免把宿主机上的依赖复制进镜像导致权限问题，例如 `sh: vite: Permission denied`。

```bash
rm -rf ui/node_modules
```

建议增加 `ui/.dockerignore`：

```dockerignore
node_modules
dist
.git
.gitignore
.DS_Store
npm-debug.log
```

## 6. 启动部署

在服务器项目根目录执行：

```bash
cd /home/qhadmin/jushi
docker compose up -d --build --remove-orphans
```

如果服务器上已经部署过旧版 4 容器架构，`--remove-orphans` 会移除不再出现在当前 `docker-compose.yml` 中的 `jushi-port-list` 容器。

也可以按服务分步部署：

```bash
docker compose up -d jushi-mysql
docker compose up -d --build --no-deps jushi-api
docker compose up -d --build --no-deps jushi-frontend
```

其中 `jushi-api` 已配置依赖 `jushi-mysql` 健康检查；第一次完整部署仍推荐使用上面的完整部署命令。

查看服务状态：

```bash
docker compose ps
docker ps -a | grep jushi
```

正常情况下应该看到：

- `jushi-frontend` running
- `jushi-api` running
- `jushi-mysql` running

`docker images` 看到只有一个 `mysql:8.0` 是正常的。`docker images` 显示的是镜像，不是容器；多个 MySQL 容器可以共用同一个 `mysql:8.0` 镜像。

## 7. 访问地址

Swagger 地址：

```text
http://服务器IP:18000/api/docs
```

OpenAPI JSON：

```text
http://服务器IP:18000/api/docs/openapi.json
```

健康检查：

```text
http://服务器IP:18000/api/health
```

前端页面：

```text
http://服务器IP:18000/
```

## 8. 内网验证命令

在服务器上执行：

```bash
curl -I http://127.0.0.1:18000/
curl -i http://127.0.0.1:18000/api/health
curl -I http://127.0.0.1:18000/api/docs
curl -i http://127.0.0.1:18000/api/docs/openapi.json
```

验证登录接口：

```bash
curl -s -X POST http://127.0.0.1:18000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"bluedot@123"}'
```

验证登录拦截器：

```bash
curl -i http://127.0.0.1:18000/api/users/list
```

未带 token 时，除登录、健康检查和 Swagger 文档外，业务接口应返回 `401`。

拿到 token 后再访问：

```bash
curl -i http://127.0.0.1:18000/api/users/list \
  -H "Authorization: Bearer 替换为登录返回的token"
```

## 9. 数据库验证

进入 MySQL 容器：

```bash
docker exec -it jushi-mysql mysql -ujushi -pjushi_pass jushi
```

查看表和初始化用户：

```sql
SHOW TABLES;
SELECT id, username, role, status FROM sys_user;
```

部署相关表建议额外确认：

```sql
SELECT deployment_name, instance_name, creator, status, created_at
FROM deploy_instance
ORDER BY created_at DESC
LIMIT 5;

SHOW COLUMNS FROM alert_event;
```

注意：

- `backend/db/init.sql` 只会在 MySQL 数据目录首次初始化时执行；单纯重建 `jushi-api` 或 `jushi-mysql` 容器不会重复执行初始化 SQL。
- 已有离线环境增加节点单卡历史表时，必须显式执行 `backend/db/migrations/20260723_001_create_accelerator_metric_sample.sql`。完整步骤见 [节点单卡历史离线升级说明](accelerator-history-offline-upgrade.md)。
- 已有环境启用审计调用统计前，应显式执行幂等迁移 `backend/db/migrations/20260723_002_add_operation_log_statistics_index.sql`，为时间范围聚合补充查询索引；该迁移不修改或删除已有日志数据。
- 当前释放部署为软删除：`deploy_instance.status` 会更新为 `released`，列表接口会过滤 released 记录。
- 告警表的兼容字段由后端 `ensure_alert_schema()` 在访问告警接口时补齐，首次调用 `/api/alerts/list` 时会检查并补充 `instance_name`、`deployment_name`、`fingerprint` 等列。

## 10. 常见问题

### 10.1 Docker Hub 拉取超时

现象：

```text
failed to resolve source metadata for docker.io/library/python:3.11-slim
i/o timeout
```

处理：

- 把 `python:3.11-slim` 改为 `docker.m.daocloud.io/python:3.11-slim`。
- 把 `node:20-alpine` 改为 `docker.m.daocloud.io/node:20-alpine`。
- 把 `nginx:1.27-alpine` 改为 `docker.m.daocloud.io/nginx:1.27-alpine`。

### 10.2 前端构建 vite 权限错误

现象：

```text
sh: vite: Permission denied
```

原因：

宿主机的 `ui/node_modules` 被复制进镜像，其中 `node_modules/.bin/vite` 没有执行权限。

处理：

```bash
rm -rf ui/node_modules
docker compose up -d --build
```

并增加 `ui/.dockerignore`，避免再次复制 `node_modules`。

### 10.3 后端容器报 No module named backend

现象：

```text
ModuleNotFoundError: No module named 'backend'
```

原因：

后端镜像的构建上下文是 `./backend`，容器内代码位于 `/app`，不存在 `/app/backend` 这个父包。

处理方式是在需要兼容本地和容器启动的地方使用 fallback import，例如：

```python
try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config
```

### 10.4 前端访问 API 返回 502

现象：

```text
502 Bad Gateway
```

一种常见原因是 `jushi-api` 容器重建后 IP 变化，但前端 nginx 进程仍缓存了旧的 `jushi-api` 地址。

处理：

```bash
docker compose restart jushi-frontend
```

如果 API 也刚重建过，可以一起重启：

```bash
docker compose restart jushi-api jushi-frontend
```

### 10.5 docker restart 报 task not found

如果当前服务器的 `docker compose` 底层使用 `nerdctl`，直接 `docker restart 容器名` 可能出现 task 不一致问题。

优先使用：

```bash
docker compose restart jushi-api
docker compose restart jushi-frontend
docker compose ps
```

或者直接强制重建：

```bash
docker compose up -d --force-recreate jushi-api jushi-frontend
```

## 11. 日志排查

查看 API 日志：

```bash
docker logs --tail=200 jushi-api
```

查看前端 nginx 日志：

```bash
docker logs --tail=200 jushi-frontend
```

查看 MySQL 日志：

```bash
docker logs --tail=200 jushi-mysql
```

## 12. 部署完成标准

满足以下条件后，可认为服务器部署基本完成：

- `docker compose ps` 中 3 个服务都是 `running`。
- `http://服务器IP:18000/` 可以打开前端。
- `http://服务器IP:18000/api/docs` 可以打开 Swagger。
- `http://服务器IP:18000/api/health` 返回成功。
- 未登录访问业务接口返回 `401`。
- 登录成功后，带 token 可以访问 `/api/users/list`。
- `jushi-mysql` 中存在 `sys_user` 等初始化表。

