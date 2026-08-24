import os


class Config:
    APP_ENV = os.getenv("APP_ENV", "production")
    SECRET_KEY = os.getenv("SECRET_KEY", "BlueDot@123")

    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "jushi")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "504803")

    DCE_API_BASE = os.getenv("DCE_API_BASE", "")
    DCE_CLUSTER = os.getenv("DCE_CLUSTER", "default")
    DCE_NAMESPACE = os.getenv("DCE_NAMESPACE", "default")
    DCE_TOKEN = (os.getenv("DCE_TOKEN") or "").strip('"')

    K8S_API_BASE = os.getenv("K8S_API_BASE", "")
    K8S_TOKEN = (os.getenv("K8S_TOKEN") or "").strip('"')

    ALGORITHM_ARCH = (os.getenv("ALGORITHM_ARCH") or "auto").strip().lower()
    ALGORITHM_VERSION_BASE_DIR = os.getenv(
        "ALGORITHM_VERSION_BASE_DIR",
        "/mnt/jushi-algorithm",
    )

    PROMETHEUS_BASE_URL = os.getenv("PROMETHEUS_BASE_URL", "")
    PROMETHEUS_TOKEN = (os.getenv("PROMETHEUS_TOKEN") or "").strip('"')
    PROMETHEUS_TIMEOUT_SECONDS = int(os.getenv("PROMETHEUS_TIMEOUT_SECONDS", "5"))

    # 老版本部署脚本通过内部接口上报六类部署操作。密钥为空时接口保持关闭。
    AUDIT_INGEST_KEY = (os.getenv("AUDIT_INGEST_KEY") or "").strip()
    AUDIT_INGEST_MAX_BYTES = int(os.getenv("AUDIT_INGEST_MAX_BYTES", "262144"))

