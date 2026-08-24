#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MIGRATION_FILE=${1:-"$PROJECT_DIR/backend/db/migrations/20260723_001_create_accelerator_metric_sample.sql"}
MYSQL_CONTAINER=${MYSQL_CONTAINER:-jushi-mysql}

if [ ! -f "$MIGRATION_FILE" ]; then
  echo "Migration file not found: $MIGRATION_FILE" >&2
  exit 1
fi

if ! docker inspect "$MYSQL_CONTAINER" >/dev/null 2>&1; then
  echo "MySQL container not found: $MYSQL_CONTAINER" >&2
  exit 1
fi

echo "Applying migration: $MIGRATION_FILE"
docker exec -i "$MYSQL_CONTAINER" sh -c '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE"
' < "$MIGRATION_FILE"

docker exec "$MYSQL_CONTAINER" sh -c '
  export MYSQL_PWD="$MYSQL_PASSWORD"
  exec mysql -u"$MYSQL_USER" "$MYSQL_DATABASE" \
    -e "SHOW TABLES LIKE '\''accelerator_metric_sample'\'';"
'

echo "Accelerator history migration completed."

