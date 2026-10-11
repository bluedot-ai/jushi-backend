#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MYSQL_CONTAINER=${MYSQL_CONTAINER:-jushi-mysql}
export MYSQL_CONTAINER

# Validate every input before the first DDL; take a database backup separately.
for migration in \
  20260723_001_create_accelerator_metric_sample.sql \
  20260723_002_add_operation_log_statistics_index.sql \
  20261010_001_create_gpu_allocation_snapshot.sql \
  20261010_002_add_gpu_allocation_vendor.sql
do
  if [ ! -f "$PROJECT_DIR/backend/db/migrations/$migration" ]; then
    echo "Missing migration: $migration" >&2
    exit 1
  fi
done

sh "$SCRIPT_DIR/apply-accelerator-history-migration.sh"
echo "Checking operation log statistics index."
docker exec -i "$MYSQL_CONTAINER" sh -c '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"
' < "$PROJECT_DIR/backend/db/migrations/20260723_002_add_operation_log_statistics_index.sql"
sh "$SCRIPT_DIR/apply-gpu-allocation-migration.sh"
echo "GPU/NPU history schema upgrade completed. No historical rows were deleted."
