-- 聚时 AI 推理资源管理平台数据库
CREATE DATABASE IF NOT EXISTS jushi DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE jushi;

CREATE TABLE IF NOT EXISTS sys_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '用户主键 ID',
  username VARCHAR(64) NOT NULL UNIQUE COMMENT '登录用户名，系统内唯一',
  password VARCHAR(128) NOT NULL COMMENT '登录密码，前期开发阶段暂存明文，后续上线前改为哈希',
  real_name VARCHAR(64) DEFAULT NULL COMMENT '用户真实姓名或展示名称',
  role VARCHAR(32) NOT NULL DEFAULT 'user' COMMENT '用户角色：admin 管理员，operator 运维人员，user 普通用户',
  status VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '用户状态：active 启用，disabled 禁用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT='系统用户表，保存登录账号、角色和状态';

CREATE TABLE IF NOT EXISTS deploy_instance (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '实例记录主键 ID',
  instance_name VARCHAR(128) NOT NULL COMMENT '实例展示名称，用户给工作负载起的别名',
  deployment_name VARCHAR(128) NOT NULL UNIQUE COMMENT 'Kubernetes Deployment 名称，真实工作负载 ID',
  gpu_vendor VARCHAR(32) NOT NULL COMMENT 'GPU 厂商，如 NVIDIA、Huawei',
  gpu_type VARCHAR(64) NOT NULL COMMENT '前端展示或请求使用的 GPU 类型，如 NVIDIA/GPU、Huawei/Ascend310P',
  gpu_count INT NOT NULL DEFAULT 1 COMMENT '申请的 GPU 数量',
  deploy_type VARCHAR(64) NOT NULL COMMENT '部署类型，如 NvidiaInfer、HuaweiInfer',
  creator VARCHAR(64) NOT NULL COMMENT '创建人用户名',
  status VARCHAR(32) NOT NULL DEFAULT 'created' COMMENT '实例状态，如 created、running、stopped、released、failed',
  node_ports JSON DEFAULT NULL COMMENT '实例暴露端口信息，保存 Service NodePort 或车间固定端口',
  log_path VARCHAR(255) DEFAULT NULL COMMENT '实例日志目录路径',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT='推理部署实例表，保存实例生命周期和资源关键信息';

CREATE TABLE IF NOT EXISTS port_block_rule (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '封闭端口规则主键 ID',
  port INT NOT NULL UNIQUE COMMENT '需要避让的端口号',
  remark VARCHAR(255) DEFAULT NULL COMMENT '端口用途或封闭原因说明',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT='封闭端口规则表，创建实例随机端口时需要避开这些端口';

CREATE TABLE IF NOT EXISTS operation_log (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '操作日志主键 ID',
  operation_type VARCHAR(64) NOT NULL COMMENT '操作类型，如 login、create、release、reset、port_add',
  operator VARCHAR(64) DEFAULT NULL COMMENT '操作人用户名',
  operator_ip VARCHAR(64) DEFAULT NULL COMMENT '操作人 IP 地址',
  target_type VARCHAR(64) DEFAULT NULL COMMENT '操作对象类型，如 deploy、pod、port、alert',
  target_name VARCHAR(128) DEFAULT NULL COMMENT '操作对象名称，如实例名、Pod 名或端口号',
  request_payload JSON DEFAULT NULL COMMENT '请求参数快照',
  response_payload JSON DEFAULT NULL COMMENT '响应结果快照',
  http_status_code INT DEFAULT NULL COMMENT 'HTTP 响应状态码',
  is_success TINYINT(1) NOT NULL DEFAULT 0 COMMENT '操作是否成功：1 成功，0 失败',
  error_message TEXT DEFAULT NULL COMMENT '失败原因或异常信息',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  KEY idx_operation_log_time_type_success (created_at, operation_type, is_success)
) COMMENT='操作日志表，用于审计用户关键操作';

CREATE TABLE IF NOT EXISTS alert_event (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '告警事件主键 ID',
  alert_type VARCHAR(64) DEFAULT NULL COMMENT '告警类型，如 image_pull_failed、pod_failed、pending_timeout',
  alert_level VARCHAR(32) NOT NULL COMMENT '告警级别，如 high、medium、low',
  title VARCHAR(128) NOT NULL COMMENT '告警标题',
  message TEXT DEFAULT NULL COMMENT '告警详细描述',
  source VARCHAR(64) DEFAULT NULL COMMENT '告警来源模块，如 deploy、pod、resource、port',
  target_name VARCHAR(128) DEFAULT NULL COMMENT '告警对象名称，如实例名、Pod 名、节点名或资源名',
  cluster_name VARCHAR(128) DEFAULT NULL COMMENT 'Kubernetes cluster name',
  namespace VARCHAR(128) DEFAULT NULL COMMENT 'Kubernetes namespace',
  instance_name VARCHAR(128) DEFAULT NULL COMMENT '实例展示名称',
  deployment_name VARCHAR(128) DEFAULT NULL COMMENT 'Kubernetes Deployment 名称',
  fingerprint VARCHAR(255) DEFAULT NULL COMMENT '告警去重指纹',
  last_seen_at DATETIME DEFAULT NULL COMMENT '最近一次检测到该告警的时间',
  evidence JSON DEFAULT NULL COMMENT '告警证据快照，如 Pod 状态、事件和日志关键字',
  occurrence_count INT NOT NULL DEFAULT 1 COMMENT '同一告警累计检测次数',
  status VARCHAR(32) NOT NULL DEFAULT 'open' COMMENT '告警状态：open 未处理，resolved 已解决，ignored 已忽略',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  resolved_at DATETIME DEFAULT NULL COMMENT '解决时间',
  handled_at DATETIME DEFAULT NULL COMMENT '处理时间，用于已解决和已忽略告警历史排序',
  resolver VARCHAR(64) DEFAULT NULL COMMENT '处理人用户名',
  KEY idx_alert_cluster_namespace (cluster_name, namespace),
  UNIQUE KEY uk_alert_fingerprint (fingerprint)
) COMMENT='告警事件表，保存资源、实例、Pod 和端口相关告警';

CREATE TABLE IF NOT EXISTS resource_snapshot (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '资源快照主键 ID',
  snapshot_type VARCHAR(64) NOT NULL COMMENT '快照类型，如 summary、nodes、gpus、quotas',
  payload JSON NOT NULL COMMENT '资源快照内容 JSON',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  KEY idx_resource_snapshot_type_time (snapshot_type, created_at),
  KEY idx_resource_snapshot_created_at (created_at)
) COMMENT='资源快照表，用于保存集群资源统计结果';

CREATE TABLE IF NOT EXISTS accelerator_metric_sample (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '采样记录主键',
  sampled_at DATETIME NOT NULL COMMENT '指标采样时间，按采集周期对齐',
  cluster_name VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '集群标识',
  node_name VARCHAR(253) NOT NULL COMMENT 'Kubernetes 节点名称',
  vendor VARCHAR(16) NOT NULL COMMENT '内部厂商标识：nvidia 或 ascend',
  card_id VARCHAR(128) NOT NULL COMMENT '稳定卡标识：NVIDIA UUID 或 Ascend vdie_id',
  device_index INT DEFAULT NULL COMMENT 'exporter 提供的原始卡序号',
  device_name VARCHAR(128) DEFAULT NULL COMMENT '设备名称或 PCIe 地址',
  model_name VARCHAR(255) DEFAULT NULL COMMENT '物理卡型号',
  memory_used_mib DECIMAL(20, 3) DEFAULT NULL COMMENT '显存已使用量，单位 MiB',
  memory_total_mib DECIMAL(20, 3) DEFAULT NULL COMMENT '显存总量，单位 MiB',
  memory_utilization_percent DECIMAL(7, 3) DEFAULT NULL COMMENT '显存利用率百分比',
  metric_source VARCHAR(32) NOT NULL DEFAULT 'prometheus' COMMENT '数据来源',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录入库时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_accelerator_sample (
    cluster_name,
    node_name,
    vendor,
    card_id,
    sampled_at
  ),
  KEY idx_accelerator_node_time (
    cluster_name,
    node_name,
    sampled_at
  ),
  KEY idx_accelerator_card_time (
    cluster_name,
    node_name,
    card_id,
    sampled_at
  ),
  KEY idx_accelerator_sampled_at (sampled_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='节点物理加速卡历史指标采样表';


CREATE TABLE IF NOT EXISTS sys_config (
  config_key VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '配置键名',
  config_value TEXT NOT NULL COMMENT '配置值',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) COMMENT='系统配置表，存储全局配置项如 logo 路径等';

INSERT IGNORE INTO sys_user (
  username,
  password,
  real_name,
  role,
  status
) VALUES (
  'admin',
  'bluedot@123',
  '系统管理员',
  'admin',
  'active'
);

ALTER TABLE alert_event
  MODIFY alert_type VARCHAR(64) NULL,
  MODIFY source VARCHAR(64) NULL,
  MODIFY target_name VARCHAR(128) NULL;

