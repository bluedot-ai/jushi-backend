import os
import time

try:
    from backend.db.mysql import get_connection
    from backend.modules.system.schema import (
        LOGO_CONFIG_KEY,
        LOGO_ENABLED_KEY,
        LOGO_UPLOAD_DIR,
    )
    from backend.common.response import success, fail
except ModuleNotFoundError:
    from db.mysql import get_connection
    from modules.system.schema import (
        LOGO_CONFIG_KEY,
        LOGO_ENABLED_KEY,
        LOGO_UPLOAD_DIR,
    )
    from common.response import success, fail


def _get_config_value(key: str) -> str:
    """读取 sys_config 中指定 key 的值，不存在返回空字符串。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT config_value FROM sys_config WHERE config_key = %s",
                (key,),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    return row["config_value"] if row else ""


def _set_config_value(key: str, value: str) -> None:
    """写入或更新 sys_config 中的键值对。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO sys_config (config_key, config_value)
                   VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)""",
                (key, value),
            )
    finally:
        conn.close()


def get_logo() -> dict:
    """读取当前 logo 状态，返回前端可用的 URL 和启用标记。"""
    enabled = _get_config_value(LOGO_ENABLED_KEY)
    if enabled != "1":
        return {"logo_url": "", "logo_enabled": False}

    logo_path = _get_config_value(LOGO_CONFIG_KEY)
    if not logo_path or not os.path.isfile(logo_path):
        return {"logo_url": "", "logo_enabled": False}

    return {"logo_url": "/api/system/logo/file", "logo_enabled": True}


def get_logo_file_path() -> str | None:
    """返回当前启用的 logo 磁盘绝对路径，不存在或未启用时返回 None。"""
    enabled = _get_config_value(LOGO_ENABLED_KEY)
    if enabled != "1":
        return None

    path = _get_config_value(LOGO_CONFIG_KEY)
    if path and os.path.isfile(path):
        return path
    return None


def set_logo_enabled(enable: bool) -> dict:
    """开关 logo，true=启用自定义，false=恢复默认。"""
    value = "1" if enable else "0"
    _set_config_value(LOGO_ENABLED_KEY, value)
    if enable:
        path = _get_config_value(LOGO_CONFIG_KEY)
        if not path or not os.path.isfile(path):
            return {"logo_url": "", "logo_enabled": False}
        return {"logo_url": "/api/system/logo/file", "logo_enabled": True}
    return {"logo_url": "", "logo_enabled": False}


def upload_logo(file_storage) -> tuple:
    """保存上传的 logo，启用自定义 logo（不删除旧文件，所有上传记录均保留）。"""
    # 1. 保存文件（不删除旧文件）
    os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
    _, ext = os.path.splitext(file_storage.filename)
    timestamp = int(time.time() * 1000)
    new_filename = f"logo_{timestamp}{ext.lower()}"
    new_path = os.path.join(LOGO_UPLOAD_DIR, new_filename)

    try:
        file_storage.save(new_path)
    except Exception as exc:
        return fail(f"保存文件失败：{exc}", 500)

    # 2. 写入配置：路径 + 启用标记
    _set_config_value(LOGO_CONFIG_KEY, new_path)
    _set_config_value(LOGO_ENABLED_KEY, "1")

    return success({"logo_url": "/api/system/logo/file", "logo_enabled": True})
