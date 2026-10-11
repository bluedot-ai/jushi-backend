#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MIGRATION_FILE=${1:-"$PROJECT_DIR/backend/db/migrations/20261010_001_create_gpu_allocation_snapshot.sql"}
VENDOR_MIGRATION_FILE="$PROJECT_DIR/backend/db/migrations/20261010_002_add_gpu_allocation_vendor.sql"
MYSQL_CONTAINER=${MYSQL_CONTAINER:-jushi-mysql}

if [ ! -f "$MIGRATION_FILE" ]; then
  echo "Migration file not found: $MIGRATION_FILE" >&2
  exit 1
fi
if [ "$#" -eq 0 ] && [ ! -f "$VENDOR_MIGRATION_FILE" ]; then
  echo "Migration file not found: $VENDOR_MIGRATION_FILE" >&2
  exit 1
fi
if ! docker inspect "$MYSQL_CONTAINER" >/dev/null 2>&1; then
  echo "MySQL container not found: $MYSQL_CONTAINER" >&2
  exit 1
fi

echo "Applying additive GPU allocation migration: $MIGRATION_FILE"
docker exec -i "$MYSQL_CONTAINER" sh -c '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"
' < "$MIGRATION_FILE"
if [ "$#" -eq 0 ]; then
  echo "Upgrading GPU history vendor scope without deleting existing samples."
  docker exec -i "$MYSQL_CONTAINER" sh -c '
    export MYSQL_PWD="$MYSQL_PASSWORD"
    exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"
  ' < "$VENDOR_MIGRATION_FILE"
fi
docker exec "$MYSQL_CONTAINER" sh -c '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" \
    -e "SHOW TABLES LIKE '\''gpu_allocation_snapshot'\'';"
'
echo "GPU allocation migration completed. Existing business tables were not modified."
