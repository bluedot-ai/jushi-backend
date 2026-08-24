import json
from contextlib import contextmanager
from datetime import datetime

try:
    from backend.db.mysql import get_connection
except ModuleNotFoundError:
    from db.mysql import get_connection


class DeployCreateLockError(RuntimeError):
    pass


@contextmanager
def deploy_create_lock(timeout_seconds: int = 10):
    # 使用 MySQL 连接级 GET_LOCK，保证多 API 副本下创建链路仍然串行。
    conn = get_connection()
    lock_name = "jushi_deploy_create"
    acquired = False
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s) AS acquired", (lock_name, timeout_seconds))
            row = cursor.fetchone() or {}
            acquired = row.get("acquired") == 1
        if not acquired:
            raise DeployCreateLockError("当前有部署正在创建，请稍后重试")
        yield
    finally:
        if acquired:
            with conn.cursor() as cursor:
                cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
        conn.close()


def save_deploy_instance(record: dict):
    # 保存部署实例记录，创建成功后写入 deploy_instance 表。
    node_ports = record.get("node_ports")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM deploy_instance LIKE 'instance_name'")
            has_instance_name = cursor.fetchone() is not None

    instance_columns = "instance_name,\n            " if has_instance_name else ""
    instance_values = "%s, " if has_instance_name else ""
    sql = """
        INSERT INTO deploy_instance (
            {instance_columns}
            deployment_name,
            gpu_vendor,
            gpu_type,
            gpu_count,
            deploy_type,
            creator,
            status,
            node_ports,
            log_path
        )
        VALUES ({instance_values}%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """.format(instance_columns=instance_columns, instance_values=instance_values)
    params = []
    if has_instance_name:
        params.append(record.get("instance_name"))
    params.extend(
        [
            record["deployment_name"],
            record["gpu_vendor"],
            record["gpu_type"],
            record["gpu_count"],
            record["deploy_type"],
            record["creator"],
            record.get("status", "running"),
            json.dumps(node_ports, ensure_ascii=False) if node_ports is not None else None,
            record.get("log_path"),
        ]
    )
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            record["id"] = cursor.lastrowid
    return record


def _format_datetime(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def list_deploy_instances():
    # 查询本系统创建记录，只提供业务侧别名；已释放实例默认不再出现在实例列表。
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM deploy_instance LIKE 'instance_name'")
            has_instance_name = cursor.fetchone() is not None
            instance_expr = "instance_name" if has_instance_name else "deployment_name AS instance_name"
            cursor.execute(
                f"""
                SELECT
                    {instance_expr},
                    deployment_name,
                    creator,
                    status,
                    created_at
                FROM deploy_instance
                WHERE status <> 'released'
                ORDER BY created_at DESC
                """
            )
            rows = cursor.fetchall() or []

    for row in rows:
        row["created_at"] = _format_datetime(row.get("created_at"))
    return rows


def get_deploy_instance(name: str) -> dict | None:
    if not name:
        return None
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SHOW COLUMNS FROM deploy_instance LIKE 'instance_name'")
            has_instance_name = cursor.fetchone() is not None
            instance_expr = "instance_name" if has_instance_name else "deployment_name AS instance_name"
            cursor.execute(
                f"""
                SELECT
                    {instance_expr},
                    deployment_name,
                    creator,
                    status,
                    created_at
                FROM deploy_instance
                WHERE deployment_name = %s
                LIMIT 1
                """,
                (name,),
            )
            row = cursor.fetchone()
    if row:
        row["created_at"] = _format_datetime(row.get("created_at"))
    return row


def update_deploy_status(name: str, status: str):
    # 更新部署实例状态，如 created、running、released、failed。
    if not name:
        return {"deployment_name": name, "status": status, "affected_rows": 0}
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE deploy_instance
                SET status = %s
                WHERE deployment_name = %s
                """,
                (status, name),
            )
            affected_rows = cursor.rowcount
    return {"deployment_name": name, "status": status, "affected_rows": affected_rows}


def delete_deploy_instance(name: str) -> dict:
    # 释放实例后软删除本地记录，保留审计线索；列表查询会过滤 released 状态。
    if not name:
        return {"deployment_name": name, "affected_rows": 0}
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE deploy_instance
                SET status = 'released'
                WHERE deployment_name = %s
                """,
                (name,),
            )
            affected_rows = cursor.rowcount
    return {"deployment_name": name, "affected_rows": affected_rows}
