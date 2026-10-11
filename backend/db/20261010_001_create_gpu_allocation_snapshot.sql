-- Incremental, idempotent migration; never modifies existing business tables.
-- Apply to the existing jushi database. All timestamps use Asia/Shanghai.
CREATE TABLE IF NOT EXISTS gpu_allocation_snapshot (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '历史快照主键',
  sampled_at DATETIME NOT NULL COMMENT '实际采集时间及监控窗口结束时间，Asia/Shanghai',
  sample_slot DATETIME NOT NULL COMMENT '采集周期对齐槽，用于幂等写入',
  cluster_name VARCHAR(128) NOT NULL DEFAULT 'default' COMMENT '集群标识',
  vendor VARCHAR(16) NOT NULL DEFAULT 'nvidia' COMMENT '范围：all 合并，nvidia 英伟达，ascend 华为；旧行默认为英伟达',
  gpu_capacity INT UNSIGNED DEFAULT NULL COMMENT '纳管物理 GPU/NPU 总容量，张',
  gpu_allocatable INT UNSIGNED DEFAULT NULL COMMENT '当前可分配物理 GPU/NPU 数量，张',
  gpu_allocated INT UNSIGNED DEFAULT NULL COMMENT '已分配物理 GPU/NPU 数量，张',
  allocation_rate DECIMAL(12, 4) DEFAULT NULL COMMENT '资源分配率百分比；分母为零时为空',
  gpu_utilization_avg DECIMAL(7, 4) DEFAULT NULL COMMENT '过去采样窗口 GPU 平均利用率百分比',
  gpu_utilization_max DECIMAL(7, 4) DEFAULT NULL COMMENT '过去采样窗口 GPU 峰值利用率百分比',
  gpu_memory_utilization DECIMAL(7, 4) DEFAULT NULL COMMENT '真实监控的容量加权显存使用率百分比',
  gpu_active_count INT UNSIGNED DEFAULT NULL COMMENT '有效活跃物理 GPU 数量',
  allocation_source VARCHAR(64) NOT NULL COMMENT '分配数据来源',
  monitor_source VARCHAR(64) DEFAULT NULL COMMENT '真实 GPU 监控来源',
  allocation_valid BOOLEAN NOT NULL DEFAULT FALSE COMMENT '分配数据是否有效',
  monitor_valid BOOLEAN NOT NULL DEFAULT FALSE COMMENT '监控数据是否完整有效；单项仍可独立有效',
  calculation_version VARCHAR(64) NOT NULL COMMENT '计算口径版本',
  sample_interval_seconds INT UNSIGNED NOT NULL DEFAULT 300 COMMENT '采样窗口秒数，历史复算使用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '写入时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gpu_allocation_cluster_vendor_slot (cluster_name, vendor, sample_slot),
  KEY idx_gpu_allocation_cluster_vendor_time (cluster_name, vendor, sampled_at),
  KEY idx_gpu_allocation_sampled_at (sampled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='物理 GPU/NPU 资源分配历史；保留当前月及前六个完整自然月';
