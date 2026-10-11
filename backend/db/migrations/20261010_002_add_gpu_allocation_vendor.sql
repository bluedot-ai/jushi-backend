-- Run 001 first. Upgrade an existing NVIDIA-only (19-column) table without
-- deleting or relabeling its calculation_version. Repeat execution is safe.
-- The new column DEFAULT nvidia backfills all legacy rows and protects an old
-- collector still running during the additive schema upgrade.
SET @gpu_allocation_vendor_exists = (
  SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'gpu_allocation_snapshot' AND column_name = 'vendor'
);
SET @gpu_allocation_vendor_sql = IF(
  @gpu_allocation_vendor_exists = 0,
  'ALTER TABLE gpu_allocation_snapshot ADD COLUMN vendor VARCHAR(16) NOT NULL DEFAULT ''nvidia'' COMMENT ''all/nvidia/ascend; legacy rows are nvidia'' AFTER cluster_name',
  'SELECT ''gpu_allocation_snapshot.vendor already exists'''
);
PREPARE gpu_allocation_vendor_statement FROM @gpu_allocation_vendor_sql;
EXECUTE gpu_allocation_vendor_statement;
DEALLOCATE PREPARE gpu_allocation_vendor_statement;

SET @gpu_allocation_old_slot_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'gpu_allocation_snapshot'
    AND index_name = 'uk_gpu_allocation_cluster_slot'
);
SET @gpu_allocation_new_slot_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'gpu_allocation_snapshot'
    AND index_name = 'uk_gpu_allocation_cluster_vendor_slot'
);
SET @gpu_allocation_new_time_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'gpu_allocation_snapshot'
    AND index_name = 'idx_gpu_allocation_cluster_vendor_time'
);
SET @gpu_allocation_old_time_exists = (
  SELECT COUNT(*) FROM information_schema.statistics
  WHERE table_schema = DATABASE() AND table_name = 'gpu_allocation_snapshot'
    AND index_name = 'idx_gpu_allocation_cluster_time'
);
-- Keep uniqueness throughout the index switch: one ALTER, not DROP followed by
-- ADD in separate statements. All DDL is confined to the new history table.
SET @gpu_allocation_vendor_alter = CONCAT_WS(', ',
  IF(@gpu_allocation_old_slot_exists > 0, 'DROP INDEX uk_gpu_allocation_cluster_slot', NULL),
  IF(@gpu_allocation_new_slot_exists = 0, 'ADD UNIQUE KEY uk_gpu_allocation_cluster_vendor_slot (cluster_name, vendor, sample_slot)', NULL),
  IF(@gpu_allocation_new_time_exists = 0, 'ADD KEY idx_gpu_allocation_cluster_vendor_time (cluster_name, vendor, sampled_at)', NULL),
  IF(@gpu_allocation_old_time_exists > 0, 'DROP INDEX idx_gpu_allocation_cluster_time', NULL)
);
SET @gpu_allocation_vendor_sql = IF(
  LENGTH(@gpu_allocation_vendor_alter) > 0,
  CONCAT('ALTER TABLE gpu_allocation_snapshot ', @gpu_allocation_vendor_alter),
  'SELECT ''gpu_allocation_snapshot vendor indexes already exist'''
);
PREPARE gpu_allocation_vendor_statement FROM @gpu_allocation_vendor_sql;
EXECUTE gpu_allocation_vendor_statement;
DEALLOCATE PREPARE gpu_allocation_vendor_statement;
