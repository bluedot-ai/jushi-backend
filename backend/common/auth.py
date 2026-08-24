from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

try:
    from backend.config import Config
except ModuleNotFoundError:
    from config import Config


TOKEN_SALT = "jushi-auth-token"
TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60


def _serializer():
    # 使用 Flask SECRET_KEY 做签名密钥，保证 token 不能被客户端随意篡改。
    return URLSafeTimedSerializer(Config.SECRET_KEY)


def create_token(user: dict) -> str:
    # 登录成功后签发 token。token 内只放身份识别字段，不放密码等敏感信息。
    payload = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }
    return _serializer().dumps(payload, salt=TOKEN_SALT)


def parse_token(token: str) -> tuple[dict | None, str | None]:
    # 解析并校验 token：签名不对或超过有效期都会返回错误信息。
    try:
        payload = _serializer().loads(
            token,
            salt=TOKEN_SALT,
            max_age=TOKEN_MAX_AGE_SECONDS,
        )
        return payload, None
    except SignatureExpired:
        return None, "登录已过期"
    except BadSignature:
        return None, "无效 token"
