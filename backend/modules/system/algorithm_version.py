import platform
import re
from pathlib import Path

try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config


ARCH_DIRECTORY_MAP = {
    "arm": "mtworkflow_arm",
    "x86": "mtworkflow_x86",
}

MACHINE_ARCH_MAP = {
    "aarch64": "arm",
    "arm64": "arm",
    "amd64": "x86",
    "x86_64": "x86",
}

VERSION_FILE_PATTERN = re.compile(
    r"^version_([0-9A-Za-z]+(?:[._-][0-9A-Za-z]+)*)$"
)


def _resolve_arch(configured_arch: str, machine: str) -> str | None:
    configured = str(configured_arch or "auto").strip().lower()
    if configured in ARCH_DIRECTORY_MAP:
        return configured
    if configured != "auto":
        return None
    return MACHINE_ARCH_MAP.get(str(machine or "").strip().lower())


def _result(status: str, *, version: str | None = None, arch: str | None = None) -> dict:
    messages = {
        "ok": "算法版本读取成功",
        "not_found": "算法目录中没有版本标识文件",
        "conflict": "算法目录中存在多个版本标识文件",
        "unavailable": "算法版本目录不可用",
        "unsupported_arch": "无法识别当前服务器架构",
    }
    return {
        "is_success": True,
        "status": status,
        "version": version,
        "arch": arch,
        "msg": messages[status],
    }


def get_algorithm_version(
    *,
    base_dir: str | None = None,
    configured_arch: str | None = None,
    machine: str | None = None,
) -> dict:
    """读取宿主机只读挂载目录中的 version_<版本号> 文件名。"""
    arch = _resolve_arch(
        Config.ALGORITHM_ARCH if configured_arch is None else configured_arch,
        platform.machine() if machine is None else machine,
    )
    if not arch:
        return _result("unsupported_arch")

    root = Path(
        Config.ALGORITHM_VERSION_BASE_DIR if base_dir is None else base_dir
    )
    algorithm_dir = root / ARCH_DIRECTORY_MAP[arch]

    try:
        if not algorithm_dir.is_dir():
            return _result("unavailable", arch=arch)

        matches = []
        for entry in algorithm_dir.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            matched = VERSION_FILE_PATTERN.fullmatch(entry.name)
            if matched:
                matches.append(matched.group(1))
    except OSError:
        return _result("unavailable", arch=arch)

    matches.sort()
    if not matches:
        return _result("not_found", arch=arch)
    if len(matches) > 1:
        return _result("conflict", arch=arch)
    return _result("ok", version=matches[0], arch=arch)

