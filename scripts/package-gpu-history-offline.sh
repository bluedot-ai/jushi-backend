#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SOFTWARE_DIR=$(CDPATH= cd -- "$PROJECT_DIR/.." && pwd)
FRONTEND_DIR=${GPU_HISTORY_FRONTEND_DIR:-"$SOFTWARE_DIR/jushiapi-ui-test"}
ARCH=${1:-amd64}
RELEASE_TAG=${2:-gpu-history-v2}
case "$ARCH" in amd64|arm64) ;; *) echo "Architecture must be amd64 or arm64" >&2; exit 1 ;; esac
case "$RELEASE_TAG" in ''|*[!a-zA-Z0-9_.-]*) echo "Invalid release tag" >&2; exit 1 ;; esac
OUTPUT_DIR=${3:-"$SOFTWARE_DIR/offline-images/$RELEASE_TAG-$ARCH"}
ARCHIVE_NAME="jushi-$RELEASE_TAG-$ARCH.tar"
if [ -e "$OUTPUT_DIR/$ARCHIVE_NAME" ] || [ -e "$OUTPUT_DIR/$ARCHIVE_NAME.gz" ]; then
  echo "Release archive already exists; choose a new release tag or output directory." >&2
  exit 1
fi
if [ ! -f "$FRONTEND_DIR/Dockerfile" ]; then
  echo "Vue frontend Dockerfile not found" >&2
  exit 1
fi

# No privileged binfmt registration: prepare an ARM-capable builder separately.
if [ -n "${GPU_HISTORY_BUILDER:-}" ]; then
  docker buildx inspect "$GPU_HISTORY_BUILDER" >/dev/null
  set -- --builder "$GPU_HISTORY_BUILDER"
else
  set --
fi
BACKEND_IMAGE="jushi-jushi-api:$RELEASE_TAG-$ARCH"
FRONTEND_IMAGE="jushiapi-ui-test-jushi-frontend:$RELEASE_TAG-$ARCH"
docker buildx build "$@" --platform "linux/$ARCH" --provenance=false \
  --load -t "$BACKEND_IMAGE" -f "$PROJECT_DIR/backend/Dockerfile" "$PROJECT_DIR/backend"
docker buildx build "$@" --platform "linux/$ARCH" --provenance=false \
  --build-arg VITE_API_BASE_URL= --build-arg VITE_ENABLE_MOCK=false \
  --load -t "$FRONTEND_IMAGE" "$FRONTEND_DIR"
for image in "$BACKEND_IMAGE" "$FRONTEND_IMAGE"; do
  actual_arch=$(docker image inspect "$image" --format '{{.Architecture}}')
  if [ "$actual_arch" != "$ARCH" ]; then
    echo "Wrong image architecture for $image: $actual_arch" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT_DIR/migrations" "$OUTPUT_DIR/scripts"
docker save -o "$OUTPUT_DIR/$ARCHIVE_NAME" "$BACKEND_IMAGE" "$FRONTEND_IMAGE"
gzip -c "$OUTPUT_DIR/$ARCHIVE_NAME" > "$OUTPUT_DIR/$ARCHIVE_NAME.gz"
cp "$PROJECT_DIR/backend/db/migrations/20260723_001_create_accelerator_metric_sample.sql" "$OUTPUT_DIR/migrations/"
cp "$PROJECT_DIR/backend/db/migrations/20260723_002_add_operation_log_statistics_index.sql" "$OUTPUT_DIR/migrations/"
cp "$PROJECT_DIR/backend/db/migrations/20261010_001_create_gpu_allocation_snapshot.sql" "$OUTPUT_DIR/migrations/"
cp "$PROJECT_DIR/backend/db/migrations/20261010_002_add_gpu_allocation_vendor.sql" "$OUTPUT_DIR/migrations/"
cp "$SCRIPT_DIR/apply-accelerator-history-migration.sh" "$SCRIPT_DIR/apply-gpu-allocation-migration.sh" "$SCRIPT_DIR/apply-gpu-history-upgrade.sh" "$OUTPUT_DIR/scripts/"
cp "$PROJECT_DIR/docs/gpu-allocation.env.example" "$PROJECT_DIR/docs/gpu-allocation-offline-upgrade.md" "$OUTPUT_DIR/"
# Scripts expect the repository layout, also when shipped without source code.
mkdir -p "$OUTPUT_DIR/backend/db/migrations"
cp "$OUTPUT_DIR/migrations/"*.sql "$OUTPUT_DIR/backend/db/migrations/"
(cd "$OUTPUT_DIR" && sha256sum "$ARCHIVE_NAME.gz" migrations/*.sql backend/db/migrations/*.sql scripts/*.sh gpu-allocation.env.example gpu-allocation-offline-upgrade.md > SHA256SUMS)
echo "Offline release prepared: $OUTPUT_DIR"
echo "Images: $BACKEND_IMAGE $FRONTEND_IMAGE"
echo "No MySQL image, live credentials or deployment configuration were copied."
