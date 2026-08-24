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

