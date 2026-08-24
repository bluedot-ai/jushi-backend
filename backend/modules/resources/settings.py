"""Environment-backed settings used only by the resources module."""

import os


def _snapshot_enabled():
    return os.getenv("RESOURCE_SNAPSHOT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _snapshot_interval_seconds():
    try:
        return max(int(os.getenv("RESOURCE_SNAPSHOT_MIN_INTERVAL_SECONDS", "10")), 10)
    except ValueError:
        return 10


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _snapshot_retention_days():
    """
    资源快照保留天数。
    默认保留 7 天；设置为 0 或负数表示不清理。
    """
    return _env_int("RESOURCE_SNAPSHOT_RETENTION_DAYS", 7)


def _auto_snapshot_enabled():
    return _env_bool("RESOURCE_AUTO_SNAPSHOT_ENABLED", True)


def _auto_snapshot_interval_seconds():
    return max(_env_int("RESOURCE_AUTO_SNAPSHOT_INTERVAL_SECONDS", _snapshot_interval_seconds()), 10)


def _trend_cache_enabled():
    return _env_bool("RESOURCE_TREND_CACHE_ENABLED", True)


def _trend_cache_24h_refresh_seconds():
    return max(_env_int("RESOURCE_TREND_CACHE_24H_REFRESH_SECONDS", 15 * 60), 60)


def _trend_cache_7d_refresh_seconds():
    return max(_env_int("RESOURCE_TREND_CACHE_7D_REFRESH_SECONDS", 60 * 60), 60)


def _trend_cache_warmup_delay_seconds():
    return max(_env_int("RESOURCE_TREND_CACHE_WARMUP_DELAY_SECONDS", 2), 0)


def _prometheus_gpu_usage_enabled():
    return _env_bool("PROMETHEUS_GPU_USAGE_ENABLED", True)


def _accelerator_history_enabled():
    return _env_bool("ACCELERATOR_HISTORY_ENABLED", True)


def _accelerator_history_interval_seconds():
    return max(_env_int("ACCELERATOR_HISTORY_INTERVAL_SECONDS", 60), 30)


def _accelerator_history_retention_days():
    return max(_env_int("ACCELERATOR_HISTORY_RETENTION_DAYS", 14), 1)


def _accelerator_history_backfill_seconds():
    return max(_env_int("ACCELERATOR_HISTORY_BACKFILL_SECONDS", 90 * 60), 0)


def _accelerator_history_cluster_name():
    return (os.getenv("ACCELERATOR_HISTORY_CLUSTER_NAME") or "default").strip() or "default"


def _capacity_estimation_enabled():
    """
    当集群没有暴露 nvidia.com/gpumem / nvidia.com/gpucores 时，
    是否按物理卡数量估算显存容量和算力容量。
    """
    return _env_bool("RESOURCE_CAPACITY_ESTIMATION_ENABLED", True)


def _gpu_card_memory_gib():
    """
    单张物理卡估算显存容量，默认按 A10 24GiB。
    如果现场不是 A10，可以通过环境变量覆盖。
    """
    return _env_float("GPU_CARD_MEMORY_GIB", 24)


def _gpu_card_compute_units():
    """
    单张物理卡估算算力单位。
    这里不是 TFLOPS 真实值，只是资源中心展示用的标准化容量单位。
    """
    return _env_float("GPU_CARD_COMPUTE_UNITS", 100)


def _vgpu_per_gpu():
    """
    当无法拿到物理卡数量、只能拿到 vGPU 数量时，用这个比例反推物理卡数量。
    当前环境 4 张物理卡暴露 40 个 vGPU，所以默认 10。
    """
    return max(_env_int("VGPU_PER_GPU", 10), 1)

