SET @operation_log_statistics_index_exists = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'operation_log'
    AND index_name = 'idx_operation_log_time_type_success'
);

SET @operation_log_statistics_index_sql = IF(
  @operation_log_statistics_index_exists = 0,
  'ALTER TABLE operation_log ADD INDEX idx_operation_log_time_type_success (created_at, operation_type, is_success)',
  'SELECT ''idx_operation_log_time_type_success already exists'''
);

PREPARE operation_log_statistics_index_statement
  FROM @operation_log_statistics_index_sql;
EXECUTE operation_log_statistics_index_statement;
DEALLOCATE PREPARE operation_log_statistics_index_statement;

