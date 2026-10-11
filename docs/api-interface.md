# 聚时 AI 推理资源管理平台一期接口文档

## 1. 文档说明

本文档基于当前前端 `ui/src/api.ts`、后端 `backend/modules/*` 以及一期开发方案整理，用于前后端联调和后端补齐接口。

约定：

- 后端基础地址：`http://localhost:8080`
- Swagger UI：`/api/docs`
- OpenAPI JSON：`/api/docs/openapi.json`
- 端口管理统一使用 `/api/port-list/*`，不再使用 `/api/ports/allowlist/*`
- 前端如果通过 Vite 开发服务访问后端，需要设置 `VITE_API_BASE_URL=http://localhost:8080`

当前后端多数核心接口已接入 MySQL、PaaS 或 Kubernetes。本文档以“一期应交付接口契约”为准，并在每个接口标注当前状态。

## 2. 通用约定

### 2.1 接口风格划分

产品化后不强制所有接口使用同一种请求体。按接口类型分为两类：

| 类型 | 适用接口 | 请求格式 | 说明 |
| --- | --- | --- | --- |
| 产品化 REST 接口 | 认证、用户、端口、资源、Pod、告警、日志等 | 直接 JSON、query 参数或 path 参数 | 面向页面管理能力，字段应贴近业务对象 |
| 兼容部署 envelope 接口 | 集群、部署、审计等 POST 接口 | `msg_id` / `serial` / `context` / `content` | 兼容原服务器部署服务和当前前端适配层 |

部署类接口本期继续使用 envelope，方便从原 `app_x86_195.py` / `app_arm_195.py` 迁移，并保持前端 `ui/src/api.ts` 的 `ApiEnvelope<T>` 可用。

### 2.2 鉴权约定

除以下接口外，所有 `/api/*` 业务接口都需要携带登录 token：

```text
GET  /api/health
POST /api/auth/login
GET  /api/docs
GET  /api/docs/openapi.json
```

请求头：

```http
Authorization: Bearer <login_token>
```

说明：

- 登录 token 来自 `/api/auth/login`，用于访问本系统后端。
- `DCE_TOKEN` 是后端内部调用 PaaS/DCE 使用的 token，只配置在服务端环境变量中，前端、Swagger、curl 都不应该传入。
- 旧版前端中的 `X-User` 只能作为创建人兜底信息，不能作为登录鉴权凭证。

### 2.3 部署 envelope 请求包

集群与部署类 POST 接口使用以下结构：

```json
{
  "msg_id": "create-001",
  "serial": "create-serial-001",
  "context": "create inference instance",
  "content": {}
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `msg_id` | string | 是 | 请求 ID |
| `serial` | string | 是 | 请求序列 |
| `context` | string | 是 | 请求上下文 |
| `content` | object | 是 | 业务参数 |
| `gpu_resource_name` | string | 否 | Huawei 场景使用，如 `huawei.com/Ascend310P` |

兼容规则：

- `/api/cluster` 可以接受没有 `content` 的旧请求；新请求建议统一传 `content: {}`。
- `content.creator` 作为创建人优先来源；没有时后端可退回当前登录用户，再退回 `X-User` / `X-Forwarded-User`。
- 部署类接口的响应建议继续回传 `msg_id`、`serial`、`context`，便于和历史服务及前端调试保持一致。
- 部署类接口会按动作校验 `msg_id`、`serial` 和 `context`；前端必须传对应动作的前缀和上下文，否则返回 `400`。

部署类动作约束：

| 接口 | `msg_id` / `serial` 前缀 | `context` |
| --- | --- | --- |
| `POST /api/deploy/check-available` | `check-` | `check deploy available` |
| `POST /api/deploy/create-default` | `create-` | `create inference instance` |
| `POST /api/deploy/retrieve` | `retrieve-` | `retrieve deploy` |
| `POST /api/deploy/list` | `list-` | `list deploy` |
| `POST /api/deploy/release` | `release-` | `release deploy` |
| `POST /api/deploy/reset` | `reset-` | `restart deploy` |
| `POST /api/deploy/stop` | `stop-` | `stop deploy` |
| `POST /api/deploy/logs` | `logs-` | `deploy logs` |

### 2.4 响应包

产品化 REST 接口可以返回简化结构：

```json
{
  "is_success": true,
  "msg": "OK",
  "http_status_code": 200,
  "content": {}
}
```

部署类接口必须返回兼容原始部署服务的 envelope：

```json
{
  "msg_id": "create-001_Resp",
  "head_id": 0,
  "context": "create inference instance",
  "serial": "create-serial-001",
  "version": "1.0.0.1",
  "status": 0,
  "content": {},
  "token": "",
  "time": "2026-05-21 15:30:00",
  "timestamp": 1780000000000,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true
}
```

所有接口正式联调时必须保证：

- HTTP 状态码成功时为 2xx
- 响应体包含 `is_success`
- 失败时响应体包含 `msg`
- 失败时 HTTP 状态码和 `http_status_code` 保持一致

部署类接口额外约定：

| 字段 | 说明 |
| --- | --- |
| `status` | 语义状态，`0` 成功，`-1` 失败 |
| `http_status_code` | HTTP 状态码镜像 |
| `content` | 业务返回体或下游错误快照 |
| `msg` | 给页面或 Swagger 展示的简短原因 |

### 2.5 部署开发顺序约定

后续部署类开发按以下顺序推进：

```text
1. POST /api/cluster
2. POST /api/deploy/check-available
3. POST /api/deploy/create-default
4. POST /api/deploy/retrieve
5. POST /api/deploy/list
6. POST /api/deploy/release
7. POST /api/deploy/reset
8. POST /api/deploy/stop
9. POST /api/deploy/logs
```

一期暂不优先开发：

```text
POST /api/deploy/queue
```

`queue` 只在资源不足排队能力重新纳入一期范围时实现。`stop` 已用于缩容停止，`logs` 入口当前用于返回 Pod describe 风格排障文本。

## 3. 用户认证接口

### 3.1 用户登录

```http
POST /api/auth/login
```

当前状态：后端已补齐。登录成功后返回本系统登录 token。

请求：

```json
{
  "username": "admin",
  "password": "admin123"
}
```

响应：

```json
{
  "is_success": true,
  "token": "dev-token",
  "user": {
    "username": "admin",
    "real_name": "系统管理员",
    "role": "admin"
  }
}
```

### 3.2 用户登出

```http
POST /api/auth/logout
```

当前状态：后端已补齐。当前为轻量登出，后端校验 token，前端删除本地 token。

响应：

```json
{
  "is_success": true
}
```

### 3.3 当前用户

```http
GET /api/auth/me
```

当前状态：后端已补齐。通过 Bearer token 恢复当前用户。

响应：

```json
{
  "username": "admin",
  "real_name": "系统管理员",
  "role": "admin"
}
```

## 4. 用户管理接口

### 4.1 用户列表

```http
GET /api/users/list
```

当前状态：后端已补齐。已接入 `sys_user` 表并支持基础筛选和分页。

响应：

```json
{
  "items": [
    {
      "id": 1,
      "username": "admin",
      "real_name": "系统管理员",
      "role": "admin",
      "status": "active",
      "created_at": "2026-05-21 15:30:00"
    }
  ]
}
```

### 4.2 创建用户

```http
POST /api/users/create
```

当前状态：后端已补齐。已接入 `sys_user` 表。

请求：

```json
{
  "username": "alice",
  "password": "Init@123",
  "real_name": "Alice",
  "role": "operator",
  "status": "active"
}
```

响应：

```json
{
  "is_success": true,
  "id": 2
}
```

### 4.3 更新用户

```http
POST /api/users/update
```

当前状态：后端已补齐。已接入 `sys_user` 表。

请求：

```json
{
  "id": 2,
  "real_name": "Alice Zhang",
  "role": "operator",
  "status": "active"
}
```

响应：

```json
{
  "is_success": true
}
```

### 4.4 删除用户

```http
POST /api/users/delete
```

当前状态：后端已补齐。当前实现为物理删除；如产品要求保留审计轨迹，建议后续改为逻辑禁用。

请求：

```json
{
  "id": 2
}
```

响应：

```json
{
  "is_success": true
}
```

### 4.5 重置密码

```http
POST /api/users/reset-password
```

当前状态：后端已补齐。当前阶段密码仍按 `init.sql` 约定明文保存，正式上线前应改为哈希。

请求：

```json
{
  "id": 2,
  "password": "New@123"
}
```

响应：

```json
{
  "is_success": true
}
```

## 5. 集群与部署接口

本节是后续部署类开发的主契约。除特别说明外，请求必须携带：

```http
Authorization: Bearer <login_token>
Content-Type: application/json
```

后端调用 PaaS/DCE 时统一通过 `backend/services/paas_client.py`，不要在业务模块中重复拼装 HTTP 客户端。部署类接口统一读取 `DCE_API_BASE`、`DCE_CLUSTER`、`DCE_NAMESPACE`、`DCE_TOKEN`。

### 5.0 部署公共字段

#### 5.0.1 GPU 请求字段

前端和接口请求继续使用产品字段：

```json
{
  "devices": {
    "NVIDIA/GPU": 1
  },
  "deployType": "NvidiaInfer",
  "creator": "admin",
  "instance_name": "qwen2.5-72b-prod"
}
```

后端内部统一映射：

| 请求设备字段 | PaaS/K8s 资源名 | deployType | GPU 厂商 | 算法包 |
| --- | --- | --- | --- | --- |
| `NVIDIA/GPU` | `nvidia.com/gpu` | `NvidiaInfer` | `NVIDIA` | `mtworkflow_x86.zip` |
| `Huawei/Ascend310P` | `huawei.com/Ascend310P` | `HuaweiInfer` | `Huawei` | `mtworkflow_arm.zip` |

Huawei 请求建议同时传顶层 `gpu_resource_name`：

```json
{
  "gpu_resource_name": "huawei.com/Ascend310P",
  "content": {
    "devices": {
      "Huawei/Ascend310P": 1
    },
    "deployType": "HuaweiInfer",
    "creator": "admin",
    "instance_name": "ascend-test"
  }
}
```

#### 5.0.2 创建人字段

创建人取值优先级：

```text
content.creator -> 当前登录用户 username -> X-User / X-Forwarded-User -> unknown
```

创建 Deployment / PodTemplate / Service 时建议写入：

```text
metadata.labels.instance_name
metadata.annotations.createdAt
metadata.annotations.creatorIp
metadata.annotations.deployType
```

`creator` 不再写入 Kubernetes label；创建人保存在本地 `deploy_instance.creator`，查询详情和审计按数据库记录读取。

#### 5.0.3 名称字段

查询、释放、重启、停止、日志接口统一从以下位置读取实例名：

```json
{
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

如果缺少 `content.name`，返回 `400`。

### 5.1 集群查询

```http
POST /api/cluster
```

当前状态：后端已补齐。新版实现通过 `DCE_API_BASE` 和 `DCE_TOKEN` 调用 PaaS 集群列表接口。

请求：

```json
{
  "msg_id": "cluster-001",
  "serial": "serial-001",
  "context": "query cluster",
  "content": {}
}
```

兼容旧请求：

```json
{
  "msg_id": "q1",
  "serial": "s-001",
  "context": "optional"
}
```

响应：

```json
{
  "msg_id": "cluster-001",
  "serial": "serial-001",
  "context": "query cluster",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "items": []
  }
}
```

实现要求：

- 只做实时查询，不写 MySQL，不缓存。
- PaaS 路径为 `{DCE_API_BASE}/clusters`。
- PaaS token 过期或缺失时返回清晰错误 envelope，不暴露 Flask traceback。

### 5.2 资源预检

```http
POST /api/deploy/check-available
```

当前状态：后端已实现。已接入 PaaS 集群资源、Deployment、Service 和端口避让检查。

目标：在创建部署前判断资源是否满足，后续 `create-default` 必须先复用同一套预检逻辑。

NVIDIA 请求：

```json
{
  "msg_id": "check-001",
  "serial": "check-serial-001",
  "context": "check deploy available",
  "content": {
    "devices": {
      "NVIDIA/GPU": 1
    },
    "deployType": "NvidiaInfer",
    "creator": "admin",
    "instance_name": "qwen2.5-72b-prod"
  }
}
```

Huawei 请求：

```json
{
  "msg_id": "check-002",
  "serial": "check-serial-002",
  "context": "check deploy available",
  "gpu_resource_name": "huawei.com/Ascend310P",
  "content": {
    "devices": {
      "Huawei/Ascend310P": 1
    },
    "deployType": "HuaweiInfer",
    "creator": "admin",
    "instance_name": "ascend-test"
  }
}
```

响应：

```json
{
  "msg_id": "check-001_Resp",
  "serial": "check-serial-001",
  "context": "check deploy available",
  "status": 0,
  "http_status_code": 200,
  "msg": "资源预检通过",
  "is_success": true,
  "content": {
    "can_create": true,
    "reason": "资源预检通过",
    "checks": [
      {
        "key": "gpu_available",
        "label": "GPU 可用余量",
        "status": "passed",
        "display": "可用 3 / 8 张"
      },
      {
        "key": "cpu_memory",
        "label": "CPU / 内存余量",
        "status": "passed",
        "display": "通过"
      },
      {
        "key": "nodeport",
        "label": "NodePort 自动避让",
        "status": "passed",
        "display": "通过"
      },
      {
        "key": "deploy_lock",
        "label": "部署锁与并发校验",
        "status": "passed",
        "display": "通过"
      }
    ],
    "cpu_available_m": 64000,
    "mem_available_bytes": 137438953472,
    "gpu_details": {
      "nvidia.com/gpu": {
        "requested": 1,
        "available": 3,
        "total": 8,
        "used": 5
      }
    },
    "total_deployments": 5,
    "devices": {
      "NVIDIA/GPU": 1
    }
  }
}
```

资源不足响应：

```json
{
  "msg_id": "check-001_Resp",
  "serial": "check-serial-001",
  "context": "check deploy available",
  "status": -1,
  "http_status_code": 400,
  "msg": "GPU 卡数量不足",
  "is_success": false,
  "content": {
    "can_create": false,
    "reason": "GPU 卡数量不足",
    "cpu_available_m": 64000,
    "mem_available_bytes": 137438953472,
    "gpu_details": {
      "nvidia.com/gpu": {
        "requested": 2,
        "available": 1,
        "total": 4,
        "used": 3
      }
    },
    "total_deployments": 3,
    "devices": {
      "NVIDIA/GPU": 2
    }
  }
}
```

实现要求：

- NVIDIA 逻辑参考旧 `app_x86_195.py`：查询 `clusters/{cluster}` 的 `resourceSummary.allocatable/allocated`，并查询 `clusters/{cluster}/namespaces/{namespace}/deployments` 估算占卡数量。
- Huawei 逻辑参考旧 `app_arm_195.py`：一期可先按 deployment 数量估算 Ascend310P 使用量；如果后续 PaaS 返回稳定 Ascend 资源字段，再切换到资源汇总判断。
- 默认资源下限：CPU `2000m`，内存 `4GiB`。
- `gpu_details` 的 key 使用 K8s 资源名，如 `nvidia.com/gpu`、`huawei.com/Ascend310P`。
- 不在预检阶段创建 Deployment、Service 或写入 `deploy_instance`。
- PaaS 查询失败返回 `502`；超时返回 `504`；参数错误返回 `400`。

### 5.3 创建推理部署

```http
POST /api/deploy/create-default
```

当前状态：后端已实现 NVIDIA 最小闭环。创建成功后会创建 PaaS Deployment / Service，并写入 `deploy_instance` 表。Swagger 中保留 Huawei 创建请求示例，但当前 `create-default` 会返回 `400`：`当前集群暂不支持 Huawei/Ascend310P`。

NVIDIA 请求：

```json
{
  "msg_id": "create-001",
  "serial": "create-serial-001",
  "context": "create inference instance",
  "content": {
    "devices": {
      "NVIDIA/GPU": 1
    },
    "deployType": "NvidiaInfer",
    "creator": "admin",
    "instance_name": "qwen2.5-72b-prod"
  }
}
```

行为要求：

- 创建前必须调用资源预检；预检失败时直接返回 `400`，不得创建任何 PaaS 资源。
- 当前创建接口只允许 NVIDIA；Huawei 请求会在创建阶段返回 `400`。资源预检仍保留 Huawei 参数校验能力。
- 创建 Deployment 后，普通模式创建同名 NodePort Service；车间固定端口模式如继续沿用旧方案，可不创建 Service，但响应仍需返回固定端口。
- 随机端口必须避开三类端口：
  - `port_block_rule` 中的封闭端口，可直接调用 `backend/modules/ports/repository.py` 的 `resolve_blocked_ports()`。
  - PaaS/Kubernetes 已存在 Service 的 `nodePort`。
  - 宿主机已绑定端口。
- 创建成功后写入 `deploy_instance` 表，至少保存 `instance_name`、`deployment_name`、GPU 字段、`deploy_type`、`creator`、`status`、`node_ports`。`log_path` 字段保留但当前创建响应返回 `null`，日志/排障改走 Kubernetes API。
- PaaS 工作负载别名写入 `kpanda.io/alias-name = instance_name/client_ip`，方便在 PaaS 平台和本系统列表中对应展示。

响应：

```json
{
  "msg_id": "create-001_Resp",
  "serial": "create-serial-001",
  "context": "create inference instance",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "deployment_name": "nvidia-cuda-xxxxxx",
    "node_ports": [
      {
        "name": "tcp-8018",
        "port": 30001
      },
      {
        "name": "tcp-8019",
        "port": 35001
      }
    ],
    "devices": {
      "NVIDIA/GPU": 1
    },
    "gpu_type": "NVIDIA/GPU",
    "deployType": "NvidiaInfer",
    "log_path": null,
    "log_source": "paas",
    "workshop_mode": false,
    "client_ip": "10.11.20.71"
  }
}
```

预检失败响应同 `5.2` 的资源不足响应。PaaS 创建失败时返回：

```json
{
  "status": -1,
  "http_status_code": 502,
  "msg": "创建部署失败",
  "is_success": false,
  "content": {
    "error": "Deployment 创建失败",
    "response": {}
  }
}
```

### 5.4 查询单个部署

```http
POST /api/deploy/retrieve
```

当前状态：后端已实现。返回前端实例详情展示字段，不透传完整 PaaS 原始对象，不写数据库。

请求：

```json
{
  "msg_id": "retrieve-001",
  "serial": "retrieve-serial-001",
  "context": "retrieve deploy",
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

响应：

```json
{
  "msg_id": "retrieve-001_Resp",
  "serial": "retrieve-serial-001",
  "context": "retrieve deploy",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "deployment_name": "nvidia-cuda-xxxxxx",
    "instance_name": "qwen2.5-72b-prod",
    "status": "Running",
    "creator": "admin",
    "created_at": "2026-05-26 11:08:28",
    "deploy_area": "qhvgpu1",
    "replica_count": "1/1 个",
    "service_endpoint": "10.11.20.71",
    "open_ports": [30001],
    "resource_mode": "物理 GPU",
    "bound_resource": "qhvgpu1 / nvidia.com/gpu x1"
  }
}
```

实现要求：

- 查询 PaaS Deployment：`clusters/{cluster}/namespaces/{namespace}/deployments/{name}`。
- 查询 Pod 时按 Deployment 标签或 owner 关联，优先复用历史脚本中的 labelSelector 方式。
- 查询同名 Service，提取 `spec.ports[].nodePort` 作为 `open_ports`。
- `creator` 优先从本地 `deploy_instance.creator` 读取；Kubernetes YAML 中不再写 `labels.creator`。
- `service_endpoint` 当前返回创建接口写入 Deployment annotation 的 `creatorIp`。
- `deploy_area` 返回关联 Pod 所在节点名；`replica_count` 返回 `ready_pods / replicas`。
- `resource_mode` 当前统一返回 `物理 GPU`；`bound_resource` 由节点名和 GPU resource limit 拼装。
- Deployment 不存在返回 `404`，响应体仍保持 envelope。

### 5.5 释放部署

```http
POST /api/deploy/release
```

当前状态：后端已实现。会删除同名 Service、Deployment，并把本地 `deploy_instance` 记录软删除为 `released` 状态。

请求：

```json
{
  "msg_id": "release-001",
  "serial": "release-serial-001",
  "context": "release deploy",
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

响应：

```json
{
  "msg_id": "release-001_Resp",
  "serial": "release-serial-001",
  "context": "release deploy",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "deployment_name": "nvidia-cuda-xxxxxx",
    "status": "released",
    "deployment_delete": {},
    "service_delete": {},
    "db_update": {
      "deployment_name": "nvidia-cuda-xxxxxx",
      "status": "released",
      "affected_rows": 1
    }
  }
}
```

实现要求：

- 删除同名 Deployment 和 Service。
- Service 不存在可视为释放成功，保持幂等。
- 成功后不物理删除 `deploy_instance`，只把状态更新为 `released`；部署列表默认过滤 released 记录。
- 日志不保存到数据库；释放后若 Deployment/Pod 已删除，日志接口不再能通过集群实时读取该实例日志。

### 5.6 重启部署

```http
POST /api/deploy/reset
```

当前状态：后端已实现运行中实例重启。按 Deployment 查询关联 Pod，删除旧 Pod 后由 Deployment 控制器自动拉起新 Pod；不改动 Service 和端口。

已停止实例说明：

- `stop` 会把 Deployment `spec.replicas` 缩为 `0`，此时集群内没有可删除的 Pod。
- `reset` 保持原有语义，只处理运行中实例重启，不负责恢复已停止实例。
- 已停止实例再次调用 reset 时，如果没有 Pod 可删除，返回“暂无可重启的 Pod”属于预期行为。
- PaaS 报 `can not start a workload which has no historical replicas` 也符合当前平台语义：已停止工作负载没有可用于恢复的历史副本数。

请求：

```json
{
  "msg_id": "reset-001",
  "serial": "reset-serial-001",
  "context": "restart deploy",
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

响应：

```json
{
  "msg_id": "reset-001_Resp",
  "serial": "reset-serial-001",
  "context": "restart deploy",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "deployment_name": "nvidia-cuda-xxxxxx",
    "status": "running",
    "pod_deletes": [
      {
        "pod_name": "nvidia-cuda-xxxxxx-abcde",
        "http_status_code": 200,
        "is_success": true
      }
    ]
  }
}
```

实现要求：

- 不调用 Deployment rollout restart，避免 GPU 单副本场景先创建新 Pod 导致 `Insufficient nvidia.com/gpu`。
- 按 `app=<deployment_name>` 查询 Pod，优先删除 Running Pod；如果没有 Running Pod，则删除查询到的 Pod。
- 删除 Pod 后由 Deployment/ReplicaSet 自动重建 Pod。
- 如果 Deployment 当前 `spec.replicas = 0`，表示已停止，reset 不做恢复启动。

### 5.7 部署列表

```http
POST /api/deploy/list
```

当前状态：后端已实现，返回实例列表页需要的精简字段。

请求：

```json
{
  "msg_id": "list-001",
  "serial": "list-serial-001",
  "context": "list deploy",
  "content": {}
}
```

响应：

```json
{
  "msg_id": "list-001_Resp",
  "serial": "list-serial-001",
  "context": "list deploy",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "items": [
      {
        "instance_name": "qwen2.5-72b-prod",
        "deployment_name": "nvidia-cuda-xxxxxx",
        "status": "已部署",
        "created_at": "2026-05-25 14:31:00"
      }
    ]
  }
}
```

实现要求：

- `instance_name`：实例展示名称，优先取本地 `deploy_instance.instance_name`；没有本地记录时回退为 `deployment_name`。
- `deployment_name`：真实 Kubernetes Deployment 名称，也就是工作负载 ID。
- `status`：由 PaaS Deployment 和 Pod 实时状态转换，副本正常可用显示为 `已部署`，Pod Pending 或副本还在启动中显示为 `等待`，副本数为 0 或本地状态为 stopped 显示为 `已停止`，启动失败/镜像拉取失败等明确失败状态显示为 `异常`。
- `created_at`：优先取 PaaS Deployment 注解或元数据创建时间，必要时回退本地记录创建时间。

### 5.8 停止部署

```http
POST /api/deploy/stop
```

当前状态：后端已实现。直接调用 Kubernetes API 把 Deployment 副本数缩为 `0`，并更新本地实例状态为 `stopped`。

请求：

```json
{
  "msg_id": "stop-001",
  "serial": "stop-serial-001",
  "context": "stop deploy",
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

响应：

```json
{
  "msg_id": "stop-001_Resp",
  "serial": "stop-serial-001",
  "context": "stop deploy",
  "status": 0,
  "http_status_code": 200,
  "msg": "OK",
  "is_success": true,
  "content": {
    "deployment_name": "nvidia-cuda-xxxxxx",
    "status": "stopped",
    "response": {}
  }
}
```

说明：停止不会删除 Deployment / Service，只通过 Kubernetes 原生 PATCH 把 Deployment 副本数缩为 `0`。列表接口会把这类实例展示为 `已停止`。

### 5.9 资源不足排队

```http
POST /api/deploy/queue
```

当前状态：一期暂缓。前端适配层已预留该接口，但一期核心交付不依赖该接口。

请求：

```json
{
  "msg_id": "queue-001",
  "serial": "queue-serial-001",
  "context": "queue deploy",
  "content": {
    "name": "nvidia-cuda-auto-001",
    "priority": "high",
    "reason": "current resource is full"
  }
}
```

响应：

```json
{
  "is_success": true,
  "content": {
    "queue_id": "queue-001",
    "rank": 1,
    "priority": "high",
    "status": "queued"
  }
}
```

说明：只有在重新纳入“一期资源不足排队”范围后再实现。当前资源不足应由 `check-available` 返回 `400` 和明确 reason。若后续启用该接口，建议沿用 `queue-` 作为 `msg_id` / `serial` 前缀。

### 5.10 部署 Pod 描述

```http
POST /api/deploy/logs
```

当前状态：后端已实现。前端只需要传 Deployment 名称，后端会通过 `app=<deployment_name>` 查询真实 Pod，并返回接近 `kubectl describe pod` 的纯文本描述。

请求：

```json
{
  "msg_id": "logs-001",
  "serial": "logs-serial-001",
  "context": "deploy logs",
  "content": {
    "name": "nvidia-cuda-xxxxxx"
  }
}
```

成功响应：

```http
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
```

```text
Name:             nvidia-cuda-xxxxxx-abcde
Namespace:        algorithm
Status:           Running
Containers:
  nvidia-cuda-xxxxxx:
    Image:         nvidia/cuda:11.6.2-cudnn8-devel-ubuntu20.04_v1
    State:         Running
Events:
  Type     Reason            Age   From               Message
```

实现说明：

- 该接口名称沿用 `/api/deploy/logs`，但当前语义是“Pod 描述/排障文本”，不是容器 stdout 日志。
- 成功响应为 `text/plain`，Swagger 和前端可直接保留换行；前端应使用 `response.text()` 或 `<pre>` / `white-space: pre-wrap` 展示。
- 失败响应仍返回原 envelope JSON，便于复用部署类错误处理。
- 后端按 `app=<deployment_name>` 通过 Kubernetes API 查询 Deployment 对应 Pod，优先选择 Running Pod。
- 后端会读取 Pod 对象并拼出 describe 文本；Events 区域需要当前 K8s token 具备 `events` 的 `get/list/watch` 权限，否则无法完整显示事件。

## 6. 封闭端口 / 端口避让接口

端口接口统一使用 `/api/port-list/*`。

不再提供：

```text
/api/ports/allowlist/list
/api/ports/allowlist/create
/api/ports/allowlist/delete
```

前端 `ui/src/api.ts` 后续需要把端口接口改为本节路径。

### 6.1 查询封闭端口

```http
GET /api/port-list/list
```

当前状态：后端已补齐。已接入 MySQL `port_block_rule` 表。

响应：

```json
{
  "items": [
    {
      "id": "1",
      "port": 50055,
      "remark": "reserved port",
      "created_at": "2026-05-21 15:30:00",
      "updated_at": "2026-05-21 15:30:00"
    }
  ]
}
```

### 6.2 新增封闭端口

```http
POST /api/port-list/add
```

当前状态：后端已补齐。已接入 MySQL `port_block_rule` 表。

请求：

```json
{
  "port": 50055,
  "remark": "reserved port"
}
```

响应：

```json
{
  "is_success": true,
  "id": "1",
  "port": 50055,
  "remark": "reserved port"
}
```

### 6.3 更新封闭端口

```http
PUT /api/port-list/update/{item_id}
```

当前状态：后端已补齐。已接入 MySQL `port_block_rule` 表。

请求：

```json
{
  "port": 50056,
  "remark": "updated reserved port"
}
```

响应：

```json
{
  "is_success": true,
  "id": "1",
  "port": 50056,
  "remark": "updated reserved port"
}
```

### 6.4 删除封闭端口

```http
DELETE /api/port-list/delete/{item_id}
```

当前状态：后端已补齐。已接入 MySQL `port_block_rule` 表。

响应：

```json
{
  "is_success": true,
  "id": "1"
}
```

### 6.5 端口避让快照

```http
GET /api/port-list/resolve
```

当前状态：后端已补齐。已接入 MySQL `port_block_rule` 表。

响应：

```json
{
  "blocked_ports": [50055, 55055],
  "blocked_singles": [50055, 55055]
}
```

## 7. 集群资源接口

### 7.1 资源总览

```http
GET /api/resources/summary
```

当前状态：后端已实现。会读取 PaaS 集群资源汇总，并结合 Kubernetes 节点、Pod 资源和本地 `resource_snapshot` 生成资源总览；同类快照默认按 `RESOURCE_SNAPSHOT_MIN_INTERVAL_SECONDS` 做写入节流。

响应：

```json
{
  "gpu_total": 8,
  "gpu_used": 5,
  "gpu_available": 3,
  "cpu_total_m": 128000,
  "cpu_used_m": 32000,
  "memory_total_bytes": 274877906944,
  "memory_used_bytes": 85899345920,
  "running_instances": 5,
  "pending_instances": 1
}
```

### 7.2 节点列表

```http
GET /api/resources/nodes
```

当前状态：后端已实现。优先读取 PaaS 节点接口，并结合 Kubernetes Node 信息补充节点标签、状态和资源字段。

响应：

```json
{
  "items": [
    {
      "node_name": "node-gpu-01",
      "status": "Ready",
      "gpu_total": 4,
      "gpu_used": 3,
      "cpu_allocatable": "64",
      "memory_allocatable": "128Gi"
    }
  ]
}
```

### 7.3 GPU 统计

```http
GET /api/resources/gpus
```

当前状态：后端已实现。按 NVIDIA GPU、NVIDIA vGPU、显存、算力以及 Huawei Ascend310P 等资源名汇总可用量、已用量和展示字段。

`category_items` 的型号数量按 Prometheus 单卡设备标签聚合，不再将一个节点的型号复制给该节点的全部显卡。NVIDIA 使用 UUID、`gpu`、`modelName`，华为使用 `vdie_id`（或 PCI 地址）、`id`、`model_name`。监控未覆盖的资源数量保留为 `Unknown` 型号，不凭节点标签猜测；前端显示“未识别型号”。`diagnostics.card_inventory` 提供查询失败、身份缺失、元数据冲突及节点数量不一致诊断。该设备视图不作为历史分配率的校验替代，也不绕过虚拟资源检查。

响应：

```json
{
  "items": [
    {
      "vendor": "NVIDIA",
      "resource_name": "nvidia.com/gpu",
      "total": 4,
      "used": 3,
      "available": 1
    },
    {
      "vendor": "Huawei",
      "resource_name": "huawei.com/Ascend310P",
      "total": 12,
      "used": 5,
      "available": 7
    }
  ]
}
```

### 7.4 资源配额

```http
GET /api/resources/quotas
```

当前状态：后端已实现。查询 Kubernetes ResourceQuota；如果当前 token 无权限或集群未配置配额，会返回空列表并保留错误快照，不阻塞页面展示。

响应：

```json
{
  "items": []
}
```

### 7.5 显卡 / vGPU 卡片列表

```http
GET /api/resources/cards
```

当前状态：后端已实现。用于资源中心卡片或表格展示，数据来自 PaaS/Kubernetes 资源汇总和节点信息。

逐卡身份和型号读取 Prometheus（NVIDIA DCGM / 华为 NPU Exporter），保持原字段结构并新增 `vendor`、`device_index`（原始零基序号）、`device_name`、`model_source`。`card_id` 优先为 NVIDIA UUID 或华为 `vdie_id`，华为无 UUID 时使用 PCI 地址；按节点、厂商及稳定设备标识去重，不按返回顺序套用型号。缺失监控保留 `节点-unidentified-序号` 占位、`gpu_model=Unknown`、`device_index=null`、`is_real_physical_card=false`，不能将占位当成真实显卡 UUID。

“已识别”只表示已获取显卡身份，不代表“运行中”或“已分配”。无法从节点申请总量确定哪一个 UUID 被分配时，逐卡分配值及已用显存返回 `null`；节点推导的容量仍保留估算标记，不宣称真实单卡用量。查询不写入数据库，也不需要新增表、环境变量或依赖。仅更新前端不能修复型号来源，离线发布时需要同时更新后端镜像。

### 7.6 资源趋势

```http
GET /api/resources/trend
```

当前状态：后端已实现。当前从 `resource_snapshot` 历史快照读取趋势；如果历史不足，会基于当前资源快照返回兜底趋势数据。

### 7.7 资源推荐策略

```http
GET /api/resources/recommendation
```

当前状态：后端已实现。根据当前 GPU、vGPU、显存、算力和节点压力返回资源使用建议。

### 7.8 物理 GPU / 华为 NPU 历史回看与自然月对比

新增独立的 `gpu_allocation_snapshot` 表，默认每 5 分钟分别保存 `all`（全部）、`nvidia`（NVIDIA GPU）、`ascend`（华为 Ascend NPU）的集群级历史快照，保存**当前月及前六个完整自然月**。旧的 `resource_snapshot` 和 `accelerator_metric_sample` 保持原有用途；不得用单卡显存历史反推历史分配数量。统一接口保留 `gpu_*` 字段名称兼容已有前端，华为范围对应 NPU 设备指标；全部范围为设备数量统计，不代表异构设备等效算力。

```http
GET  /api/resources/gpu-allocation/current
GET  /api/resources/gpu-allocation/trend
GET  /api/resources/gpu-allocation/compare
POST /api/internal/gpu-allocation/collect
```

前三个接口需要登录。`current` 仅查询，不写入数据库；`collect` 需要管理员角色，客户端不能上传指标或任意采样时间。后台任务直接调用采集函数，不依赖登录或浏览器。

统一响应包含 `is_success`、`msg` 和 `data`。参数错误返回 HTTP 400；未登录返回 401；非管理员手动采集返回 403；数据库或迁移未就绪返回 503。

三个查询接口均支持 `vendor=all|nvidia|ascend`，默认 `all`。`current.data` 包括 `vendor`、`vendors`（各厂商快照）、`gpu_capacity`（所选范围的纳管物理设备总数）、`gpu_allocatable`（Ready 且可调度节点上的可分配数量）、`gpu_allocated`（同一批节点的已分配数量）、`allocation_rate`、`gpu_utilization_avg`、`gpu_memory_utilization`、`sampled_at` 及 `diagnostics`。资源分配率不是计算利用率；真实监控缺失或不完整时返回 `null`，不能以分配比例估算。NVIDIA 采集 DCGM 指标，华为采集 NPU Exporter 指标；全部利用率按物理设备数加权，显存按统一字节单位的真实容量加权。任一实际存在厂商的某项监控不完整，全部范围对应指标为空，不能用另一厂商代替全体。

监控以原始五分钟窗口的真实抓取时间校验。同一物理设备、同一 `instance/job` 且其他设备和采集源标签一致时，仅 `exported_pod/exported_namespace/exported_container` 变化的片段可合并；重叠同值点去重，冲突值、多源不同时间、内部长缺口或缺失采集源身份仍拒绝，不能靠合并多采集源伪造完整率。`diagnostics.monitor_coverage.memory_total.physical_inventory_valid` 表示总显存指标中的新鲜整卡身份是否覆盖全部纳管设备。该核验独立于五分钟窗口完整性，可用于 NVIDIA 陈旧 `gpu.count` 标签与整卡 Capacity 的数量核验；窗口不足时利用率仍为空。华为切分资源项在 Capacity/Allocatable 两侧均为零或未声明时不视为已启用切分；任一侧非零、数值非法或共享标签启用仍拒绝整卡统计。NotReady 节点仍计入纳管容量，但不计入可分配/已分配数量；其监控缺失仍会影响所选范围的全量利用率。

`trend` 参数：`start=YYYY-MM-DD`（包含）、`end=YYYY-MM-DD`（不包含）、`granularity=day|hour`、`timezone=Asia/Shanghai`。查询范围必须在保留范围内；当前月只统计已经过去的时间，返回 `data.items` 的时间桶，缺失指标为 `null`。

当前展示与历史统计隔离：`current` 新增 `observed_monitor`（`mode=latest_observation`，`lookback_seconds=300`），复用上述原始窗口中的每卡最后一个有效点，不增加 Prometheus 查询，不安装或修改客户时间服务。原 `gpu_utilization_avg` / `gpu_memory_utilization` 继续表示严格五分钟统计；只有这些正式字段进入 `gpu_allocation_snapshot`，最近观测不入库、不参与历史趋势或月份对比。`sampled_at` 为查询时间，不能拿它替代原始指标时间。节点单卡趋势继续使用已有采集表，缺失点断线显示，不以最近观测补造历史。

`observed_monitor.utilization` 与 `.memory` 分别提供 `value`、`expected_cards`、`observed_cards`、`fresh_cards`、`delayed_cards`、`missing_cards`、`status`、`oldest_sample_at`、`latest_sample_at`、`maximum_age_seconds`、`nodes` 和 `issues`。状态为 `complete`、`partial`、`delayed`、`partial_delayed`、`unavailable` 或 `no_devices`；`complete` 仅表示最近观测覆盖完整，不表示五分钟历史有效。超过两倍对应厂商抓取间隔的样本标记延迟，窗口外或未来样本拒绝；保留原始时间，不补偿节点时钟。未确认的整卡身份、虚拟卡、超出节点物理数量、多源冲突、非法数值仍拒绝。显存只统计身份及采集源匹配、采样时间差不超过两倍抓取间隔的 used/total 对；利用率按参与观测的卡数平均，显存按统一字节单位加权。纳管数量未知时 `expected_cards` / `missing_cards` 为 `null`，不能视为零。

前端优先展示正式五分钟值；该项为空但最近观测有值时，标题改为“最近观测”，注明覆盖数量、原始时间范围、最大延迟及缺失/不可用节点，不宣称代表全部纳管显卡。无可展示样本时显示具体原因，不填零。全部范围可以展示明确标注的已观测子集，但绝不能将它写进全部范围的正式统计。此变更无新增表、数据库字段、依赖或必填环境变量。

`compare` 参数：`base_month=YYYY-MM`、`compare_month=YYYY-MM`、`timezone=Asia/Shanghai`。返回 `data.base`、`data.comparison` 和 `data.changes`。月度字段：

| 字段 | 含义 |
| --- | --- |
| `gpu_capacity_avg` / `gpu_allocatable_avg` / `gpu_allocated_avg` | 按有效时间加权的平均容量、可分配及已分配卡数 |
| `allocation_rate_avg` | 已分配卡时 / 可分配卡时 × 100%，不是直接平均百分比 |
| `allocation_rate_max` | 有效采样峰值分配率 |
| `gpu_card_hours` | 已分配 GPU 卡时，单位 GPU·h，不跨长时间缺口推算 |
| `gpu_utilization_avg` / `gpu_memory_utilization` | 真实监控窗口值的时间加权平均 |
| `allocation_completeness` / `utilization_completeness` / `memory_completeness` | 三类数据分别计算完整率 |
| `partial_month` | 是否为尚未结束的当前月 |
| `status` | `ok`、`no_data`、`mixed_version` 或 `unsupported_version` |

`changes` 的 `absolute` 在百分比指标中表示百分点（pp），`percentage` 表示相对变化百分比，基准为 0 时相对变化为空。`comparison_compatible=false` 时不输出变化，前端也不得自行补算。新口径为 `physical-accelerator-v2`；旧 `physical-gpu-v1` 快照保留为 `vendor=nvidia`，不混入新的 `all` 范围，跨新旧版本不能直接比较。混合或未知计算口径不输出可误导的数值对比。首次上线不能凭空生成之前月份的分配历史。

部署与增量 SQL 见 [GPU x86 离线升级说明](gpu-allocation-offline-upgrade.md)。

## 8. Pod 运维接口

### 8.1 Pod 列表

```http
GET /api/pods/list
```

当前状态：后端已实现。通过 Kubernetes API 查询 Pod 列表，默认命名空间为 `DCE_NAMESPACE`，支持按部署名、Pod phase 和节点名筛选。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `namespace` | string | 否 | 命名空间 |
| `deployment_name` | string | 否 | 部署名 |
| `phase` | string | 否 | Pod 状态 |
| `node_name` | string | 否 | 节点名 |

响应：

```json
{
  "items": [
    {
      "pod_name": "nvidia-cuda-xxxxxx-abcde",
      "namespace": "algorithm",
      "phase": "Running",
      "node_name": "node-1",
      "pod_ip": "10.244.x.x",
      "restart_count": 0,
      "ready": true,
      "created_at": "2026-05-21 15:30:00"
    }
  ]
}
```

### 8.2 Pod 详情

```http
GET /api/pods/detail
```

当前状态：后端已实现。通过 Kubernetes API 读取 Pod 对象，并补充容器状态、重启次数和关联 Events。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `namespace` | string | 是 | 命名空间 |
| `pod_name` | string | 是 | Pod 名称 |

响应：

```json
{
  "pod_name": "nvidia-cuda-xxxxxx-abcde",
  "namespace": "algorithm",
  "containers": [],
  "events": []
}
```

### 8.3 Pod 日志

```http
GET /api/pods/logs
```

当前状态：后端已实现。通过 Kubernetes logs API 读取最近日志行，默认 `tail_lines = 200`。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `namespace` | string | 是 | 命名空间 |
| `pod_name` | string | 是 | Pod 名称 |
| `tail_lines` | number | 否 | 最近日志行数，默认 200 |

响应：

```json
{
  "lines": [
    "[2026-05-21 15:30:00] service started"
  ]
}
```

### 8.4 删除 Pod

```http
POST /api/pods/delete
```

当前状态：后端已实现。通过 Kubernetes API 删除指定 Pod；通常用于让控制器自动重建 Pod。

请求：

```json
{
  "namespace": "algorithm",
  "pod_name": "nvidia-cuda-xxxxxx-abcde"
}
```

响应：

```json
{
  "is_success": true
}
```

### 8.5 重启 Pod

```http
POST /api/pods/restart
```

当前状态：后端已实现。当前实现复用删除 Pod 语义，删除后由 Deployment/控制器自动拉起新 Pod。

请求：

```json
{
  "namespace": "algorithm",
  "pod_name": "nvidia-cuda-xxxxxx-abcde"
}
```

响应：

```json
{
  "is_success": true
}
```

## 9. 告警接口

### 9.1 告警列表

```http
POST /api/alerts/list
```

当前状态：后端已实现。列表接口默认扫描整个 Kubernetes 集群的 Pods、Events、Nodes，写入/更新 `alert_event` 后再返回未解决、未忽略的集群级告警；也可通过 `scope = namespace` 限定单个命名空间。

请求体可为空。空对象 `{}` 或不传 JSON body 时，默认等价于 `scope = cluster`、`namespace = all`、`status = open`、`page = 1`、`page_size = 20`。

请求：

```json
{}
```

响应：

```json
{
  "is_success": true,
  "scan_error": null,
  "scan_scope": {
    "scope": "cluster",
    "namespace": "all",
    "cluster_name": "kpanda-global-cluster",
    "pod_count": 28,
    "event_count": 16,
    "node_count": 3,
    "sources": ["k8s_pods", "k8s_events", "k8s_nodes"]
  },
  "detected": 2,
  "written": 2,
  "items": [
    {
      "id": "1",
      "alert_type": "pod_pending",
      "alert_level": "high",
      "level": "high",
      "title": "GPU 资源不足",
      "message": "0/2 nodes are available: 2 Insufficient nvidia.com/gpu.",
      "description": "0/2 nodes are available: 2 Insufficient nvidia.com/gpu.",
      "source": "k8s",
      "target_name": "nvidia-cuda-xxxxxx-abcde",
      "target": "nvidia-cuda-xxxxxx-abcde",
      "cluster_name": "kpanda-global-cluster",
      "namespace": "algorithm",
      "instance_name": "qwen2.5-72b-prod",
      "deployment_name": "nvidia-cuda-xxxxxx",
      "display_status": "异常",
      "status": "open",
      "created_at": "2026-05-28 19:41:02",
      "last_seen_at": "2026-05-28 20:10:00",
      "resolved_at": null,
      "resolver": null,
      "occurrence_count": 3,
      "evidence": {}
    }
  ],
  "summary": {
    "open_total": 4,
    "high": 2,
    "medium": 1,
    "low": 1,
    "avg_handle_minutes": 7,
    "health_score": 86
  },
  "total": 4,
  "page": 1,
  "page_size": 20
}
```

实现说明：

- 默认 `scope = cluster`，扫描整个集群的 Pods、Events、Nodes；传 `scope = namespace` 和 `namespace` 时只扫描指定命名空间的 Pods/Events，同时仍读取 Nodes。
- 如果 `scope = cluster` 因 RBAC 返回 403，后端会自动降级到 `DCE_NAMESPACE` 命名空间扫描，并在 `scan_scope.requested_scope` 和 `scan_scope.fallback_reason` 中说明实际扫描范围。
- 告警来源当前为 Pod phase、容器 waiting/terminated reason、Warning Events、Node Ready/Pressure 条件。
- 集群级扫描依赖 K8s token 对 `pods`、`events`、`nodes` 具备 `list` 权限；无权限时 `scan_error` 会说明原因，列表仍返回数据库中已有告警。
- 当前 ServiceAccount 为 `system:serviceaccount:algorithm:jushi-deploy-api` 时，可应用 `docs/jushi-alert-cluster-read-rbac.yaml` 授权全集群只读告警扫描。
- `instance_name` 优先来自 `deploy_instance.instance_name`，`deployment_name` 来自 Pod 的 `app` label。
- `resolved` 和 `ignored` 状态不会被自动扫描重新打开；如需恢复为未处理，调用 `/api/alerts/reopen`。

### 9.2 告警历史记录

```http
POST /api/alerts/history
```

当前状态：后端已实现。只从数据库查询 `resolved` 和 `ignored` 告警，不触发 Kubernetes 集群扫描，用于历史记录列表展示和后续恢复操作。

请求体可为空。空对象 `{}` 或不传 JSON body 时，默认查询全部已解决和已忽略告警；也可传 `status = resolved` 或 `status = ignored` 单独筛选。

请求：

```json
{
  "status": "resolved",
  "page": 1,
  "page_size": 20
}
```

响应：

```json
{
  "is_success": true,
  "items": [
    {
      "id": "1",
      "alert_type": "pod_pending",
      "alert_level": "high",
      "title": "GPU 资源不足",
      "target_name": "nvidia-cuda-xxxxxx-abcde",
      "cluster_name": "kpanda-global-cluster",
      "namespace": "algorithm",
      "deployment_name": "nvidia-cuda-xxxxxx",
      "status": "resolved",
      "created_at": "2026-05-28 19:41:02",
      "last_seen_at": "2026-05-28 20:10:00",
      "handled_at": "2026-05-28 20:15:00",
      "resolved_at": "2026-05-28 20:15:00",
      "resolver": "admin",
      "occurrence_count": 3
    }
  ],
  "summary": {
    "resolved": 1,
    "ignored": 0
  },
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

历史记录下的“恢复/重新打开”操作调用 `/api/alerts/reopen`。

### 9.3 创建告警

```http
POST /api/alerts/create
```

当前状态：后端已实现。主要供后端流程或调试手工写入告警；自动告警优先通过 `/api/alerts/list` 扫描生成。

请求：

```json
{
  "alert_type": "resource_insufficient",
  "alert_level": "high",
  "title": "GPU 资源不足",
  "message": "当前 GPU 可用数量不足",
  "source": "deploy",
  "target_name": "NVIDIA/GPU"
}
```

响应：

```json
{
  "is_success": true
}
```

### 9.4 解决告警

```http
POST /api/alerts/resolve
```

当前状态：后端已实现。把告警状态更新为 `resolved`，记录处理人和解决时间。后续自动扫描不会重新打开该指纹告警，除非显式调用重新打开接口。

请求：

```json
{
  "id": "alert-001",
  "resolver": "admin"
}
```

响应：

```json
{
  "is_success": true,
  "status": "resolved"
}
```

### 9.5 忽略告警

```http
POST /api/alerts/ignore
```

当前状态：后端已实现。把告警状态更新为 `ignored`，用于前端“静默处理”，后续自动扫描不会重新打开该指纹告警。

请求：

```json
{
  "id": "alert-001",
  "resolver": "admin"
}
```

响应：

```json
{
  "is_success": true,
  "status": "ignored"
}
```

### 9.6 重新打开告警

```http
POST /api/alerts/reopen
```

当前状态：后端已实现。把 `resolved` 或 `ignored` 的告警恢复为 `open`，并清空处理人和解决时间。

请求：

```json
{
  "id": "alert-001",
  "resolver": "admin"
}
```

响应：

```json
{
  "is_success": true,
  "status": "open"
}
```

## 10. 日志与审计接口

### 10.1 操作日志

```http
GET /api/logs/operations
```

当前状态：后端已实现。查询 `operation_log` 表，部署类接口会通过 Flask `after_request` 中间件自动写入操作日志。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `operator` | string | 否 | 操作人 |
| `operation_type` | string | 否 | 操作类型 |
| `keyword` | string | 否 | 关键词 |
| `page` | number | 否 | 页码 |
| `page_size` | number | 否 | 每页数量 |

响应：

```json
{
  "items": [
    {
      "operator": "admin",
      "operation_type": "create",
      "target_type": "deploy",
      "target_name": "nvidia-cuda-xxxxxx",
      "is_success": true,
      "created_at": "2026-05-21 15:30:00"
    }
  ]
}
```

### 10.2 实例日志

```http
GET /api/logs/instance
```

当前状态：后端已实现。通过 `app=<deployment_name>` 查找实例 Pod，优先读取 Running Pod 的 Kubernetes logs。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `deployment_name` | string | 是 | 部署名称 |
| `tail_lines` | number | 否 | 最近日志行数 |

响应：

```json
{
  "lines": [
    "[2026-05-21 15:30:00] instance started"
  ]
}
```

### 10.3 Pod 日志

```http
GET /api/logs/pod
```

当前状态：后端已实现。复用 Pod 运维模块的 Kubernetes logs 能力。

查询参数同 `/api/pods/logs`。

响应：

```json
{
  "lines": [
    "[2026-05-21 15:30:00] pod started"
  ]
}
```

### 10.4 审计列表

```http
POST /api/audits/list
```

当前状态：后端已实现。查询 `operation_log` 并按审计 envelope 返回，支持 `operator`、`operation_type`、`keyword`、分页等筛选。

请求：

```json
{
  "msg_id": "audits-list-001",
  "serial": "serial-001",
  "context": "list audits",
  "content": {
    "result": "all",
    "operator": "admin",
    "time_range": "7d",
    "keyword": "vGPU",
    "page": 1,
    "page_size": 20
  }
}
```

响应：

```json
{
  "is_success": true,
  "content": {
    "list": [
      {
        "operator": "admin",
        "action": "创建实例",
        "target": "nvidia-cuda-xxxxxx",
        "result": "success",
        "created_at": "2026-05-21 15:30:00"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

### 10.5 导入审计日志

```http
POST /api/audits/import
Content-Type: multipart/form-data
```

当前状态：一期需补齐。前端适配层已预留该接口；当前后端未注册 `/api/audits/import` 路由。

表单字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | Excel 或 PDF 文件 |

响应：

```json
{
  "is_success": true,
  "imported": 10
}
```

### 10.6 导出审计日志

```http
POST /api/audits/export
```

当前状态：后端已实现。按筛选条件导出 `operation_log`，`content.format = json` 时返回 JSON 文件，`content.format = excel` 时返回 Excel xlsx 文件。

请求：

```json
{
  "msg_id": "audits-export-001",
  "serial": "serial-001",
  "context": "export audits",
  "content": {
    "format": "excel",
    "operator": "admin",
    "operation_type": "create",
    "keyword": "nvidia"
  }
}
```

响应：

返回文件流。`format = json` 时响应 `Content-Type: application/json`，文件名 `audit_logs.json`；`format = excel` 时响应 `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，文件名 `audit_logs.xlsx`。

## 11. 前后端字段对齐说明

### 11.1 GPU 字段

产品化页面可以使用更直观的字段：

```json
{
  "gpu_vendor": "NVIDIA",
  "gpu_type": "NVIDIA/GPU",
  "gpu_count": 1
}
```

但部署类接口一期必须继续支持当前前端 `ui/src/api.ts` 和旧服务器接口使用的 `devices` 格式：

```json
{
  "devices": {
    "NVIDIA/GPU": 1
  },
  "deployType": "NvidiaInfer"
}
```

后端内部统一映射：

| 前端字段 | 内部资源名 | deployType | GPU 厂商 | 算法包 |
| --- | --- | --- | --- | --- |
| `NVIDIA/GPU` | `nvidia.com/gpu` | `NvidiaInfer` | `NVIDIA` | `mtworkflow_x86.zip` |
| `Huawei/Ascend310P` | `huawei.com/Ascend310P` | `HuaweiInfer` | `Huawei` | `mtworkflow_arm.zip` |

实现要求：

- 校验 `devices` 中只能出现当前支持的 GPU 字段。
- `deployType` 必须和 GPU 字段匹配。
- Huawei 场景如果传入顶层 `gpu_resource_name`，必须和映射表一致。
- 响应中的 `gpu_details` 使用 K8s 资源名作为 key，实例列表可同时返回产品字段 `gpu_type`。

### 11.2 部署 envelope 与产品字段

当前前端部署接口使用 `ApiEnvelope<T>`，后端部署模块应直接兼容：

```ts
type ApiEnvelope<T> = {
  msg_id: string;
  serial: string;
  context: string;
  content: T;
  gpu_resource_name?: string;
}
```

部署开发时不要把 envelope 字段写入 Deployment 业务 spec；只把 `content` 中的部署字段、当前登录用户和运行环境配置用于创建资源。

| 字段 | 来源 | 用途 |
| --- | --- | --- |
| `msg_id` / `serial` / `context` | 请求 envelope | 响应回传和链路追踪 |
| `content.devices` | 前端选择 | 资源预检和容器 requests/limits |
| `content.deployType` | 前端选择 | 区分 NVIDIA/Huawei 模板 |
| `content.creator` | 前端或当前用户 | 写入本地表，作为创建人审计字段 |
| `gpu_resource_name` | Huawei 兼容字段 | 指定底层 K8s 资源名 |

部署类接口当前会校验 `msg_id` / `serial` 前缀和 `context`，例如查询单个部署必须使用 `retrieve-` 前缀和 `retrieve deploy` 上下文；创建部署必须使用 `create-` 前缀和 `create inference instance` 上下文。前端不要复用其他动作的 envelope。

### 11.3 端口字段

端口接口统一使用：

```text
/api/port-list/*
```

前端旧的 `PortAllowlistItem` 可临时映射：

| 前端字段 | 后端字段 | 说明 |
| --- | --- | --- |
| `port` | `port` | 端口号 |
| `remark` | `remark` | 备注 |
| `name` | 可忽略或写入 remark | 端口名称 |
| `creator` | 可写入操作日志 | 创建人 |

创建部署随机端口时不通过 HTTP 调用 `/api/port-list/resolve`，而是在后端内部直接复用端口模块的 repository/service，避免 `jushi-api` 自己请求自己。

### 11.4 告警字段

前端展示字段：

```text
id, level, category, title, target, description, action, created_at, status
```

后端表字段建议：

```text
id, alert_type, alert_level, title, message, source, target_name, status, created_at, resolved_at, resolver
```

接口返回时由后端适配：

| 后端字段 | 前端字段 |
| --- | --- |
| `alert_level` | `level` |
| `message` | `description` |
| `target_name` | `target` |
| `source` | `category` |

## 12. 一期后端补齐清单

当前后端已建路由：

```text
GET  /api/health
GET  /api/docs
GET  /api/docs/openapi.json
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/users/list
POST /api/users/create
POST /api/users/update
POST /api/users/delete
POST /api/users/reset-password
POST /api/cluster
POST /api/deploy/check-available
POST /api/deploy/create-default
POST /api/deploy/retrieve
POST /api/deploy/release
POST /api/deploy/reset
POST /api/deploy/stop
POST /api/deploy/list
POST /api/deploy/logs
GET  /api/port-list/list
POST /api/port-list/add
PUT  /api/port-list/update/{item_id}
DELETE /api/port-list/delete/{item_id}
GET  /api/port-list/resolve
GET  /api/resources/summary
GET  /api/resources/nodes
GET  /api/resources/gpus
GET  /api/resources/quotas
GET  /api/resources/cards
GET  /api/resources/trend
GET  /api/resources/recommendation
GET  /api/pods/list
GET  /api/pods/detail
GET  /api/pods/logs
POST /api/pods/delete
POST /api/pods/restart
POST /api/alerts/list
POST /api/alerts/history
POST /api/alerts/create
POST /api/alerts/resolve
POST /api/alerts/ignore
POST /api/alerts/reopen
GET  /api/logs/operations
GET  /api/logs/instance
GET  /api/logs/pod
POST /api/audits/list
POST /api/audits/export
```

其中已接入真实 MySQL 或 PaaS 能力的接口：

```text
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
GET  /api/users/list
POST /api/users/create
POST /api/users/update
POST /api/users/delete
POST /api/users/reset-password
POST /api/cluster
POST /api/deploy/check-available
POST /api/deploy/create-default
POST /api/deploy/retrieve
POST /api/deploy/release
POST /api/deploy/reset
POST /api/deploy/stop
POST /api/deploy/list
POST /api/deploy/logs
POST /api/alerts/list
POST /api/alerts/history
POST /api/alerts/create
POST /api/alerts/resolve
POST /api/alerts/ignore
POST /api/alerts/reopen
GET  /api/port-list/list
POST /api/port-list/add
PUT  /api/port-list/update/{item_id}
DELETE /api/port-list/delete/{item_id}
GET  /api/port-list/resolve
GET  /api/resources/summary
GET  /api/resources/nodes
GET  /api/resources/gpus
GET  /api/resources/quotas
GET  /api/resources/cards
GET  /api/resources/trend
GET  /api/resources/recommendation
GET  /api/pods/list
GET  /api/pods/detail
GET  /api/pods/logs
POST /api/pods/delete
POST /api/pods/restart
GET  /api/logs/operations
GET  /api/logs/instance
GET  /api/logs/pod
POST /api/audits/list
POST /api/audits/export
```

后续业务增强或暂缓接口：

```text
POST /api/deploy/queue
POST /api/audits/import
```

前端需要调整：

```text
把 /api/ports/allowlist/* 改为 /api/port-list/*
请求头补充 Authorization: Bearer <login_token>
```
