"""Resource domain constants shared by collection and presentation code."""

GPU_RESOURCE_META = {
    "nvidia.com/gpu": {
        "display_name": "NVIDIA GPU",
        "vendor": "NVIDIA",
        "kind": "physical_gpu",
        "unit": "GPU",
    },
    "nvidia.com/vgpu": {
        "display_name": "NVIDIA vGPU",
        "vendor": "NVIDIA",
        "kind": "vgpu",
        "unit": "vGPU",
    },
    "nvidia.com/gpucores": {
        "display_name": "GPU Compute",
        "vendor": "NVIDIA",
        "kind": "gpu_core",
        "unit": "core",
    },
    "nvidia.com/gpumem": {
        "display_name": "GPU Memory",
        "vendor": "NVIDIA",
        "kind": "gpu_memory",
        "unit": "MiB",
    },
    "huawei.com/Ascend310P": {
        "display_name": "Huawei Ascend310P",
        "vendor": "Huawei",
        "kind": "npu",
        "unit": "NPU",
    },
}

# 物理加速卡：用于资源中心“显卡”数量。
PHYSICAL_GPU_KEYS = ["nvidia.com/gpu", "huawei.com/Ascend310P"]

# 虚拟加速卡：用于资源中心“vGPU”数量。
VGPU_KEYS = ["nvidia.com/vgpu"]

# 兼容旧字段名，后续代码中 gpu_total 只表示物理卡。
GPU_COUNT_KEYS = PHYSICAL_GPU_KEYS

GPU_MEMORY_KEYS = ["nvidia.com/gpumem"]
GPU_CORE_KEYS = ["nvidia.com/gpucores"]

UNKNOWN_GPU_MODEL = "Unknown"
METRIC_SOURCE = "paas_cluster_resourceSummary + k8s_node_label + cluster_pod_resource_fallback"
PROMETHEUS_METRIC_SOURCE = "prometheus_gpu_memory_usage"


