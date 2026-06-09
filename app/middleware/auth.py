import hashlib
import base64
import os
import uuid

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

from app.config import get_gateway_config
from app.db.sqlite import get_db


def _key_encryption_secret() -> str:
    secret = os.getenv("GATEWAY_KEY_ENCRYPTION_SECRET", "")
    if secret:
        return secret
    cfg = get_gateway_config()
    auth_cfg = cfg.get("auth", {})
    fallback = auth_cfg.get("jwt_secret") or os.getenv("GATEWAY_JWT_SECRET", "")
    if fallback:
        return fallback
    raise RuntimeError(
        "GATEWAY_KEY_ENCRYPTION_SECRET is not set. "
        "Please configure it in your .env file or environment variables."
    )


def _fernet() -> Fernet:
    digest = hashlib.sha256(_key_encryption_secret().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_api_key(key: str) -> str:
    return _fernet().encrypt(key.encode()).decode()


def decrypt_api_key(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


async def verify_api_key(key_hash: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, user_id, name, quota_monthly, rate_limit_rps, allowed_tiers, external_user_id
            FROM api_keys
            WHERE key_hash = ? AND active = 1
            """,
            (key_hash,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "key_id": row[0],
                "user_id": row[1],
                "role": "user",
                "name": row[2],
                "quota_monthly": row[3],
                "rate_limit_rps": row[4],
                "allowed_tiers": row[5].split(","),
                "external_user_id": row[6],
            }
    return None


def verify_jwt(token: str) -> dict | None:
    cfg = get_gateway_config()
    auth_cfg = cfg.get("auth", {})
    secret = auth_cfg.get("jwt_secret", "")
    if not secret:
        import os
        secret = os.getenv("GATEWAY_JWT_SECRET", "")
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[auth_cfg.get("jwt_algorithm", "HS256")])
        return {"user_id": payload.get("sub"), "role": payload.get("role", "user")}
    except JWTError:
        return None


async def authenticate(request: Request) -> dict:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    token = auth_header[7:]

    key_hash = hashlib.sha256(token.encode()).hexdigest()
    user_info = await verify_api_key(key_hash)
    if user_info:
        request.state.user = user_info
        request.state.auth_type = "api_key"
        return user_info

    user_info = verify_jwt(token)
    if user_info:
        request.state.user = user_info
        request.state.auth_type = "jwt"
        return user_info

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


async def create_api_key(
    name: str,
    user_id: str,
    quota: int = 0,
    rate_limit: int = 10,
    allowed_tiers: list[str] | None = None,
    external_user_id: str | None = None,
) -> dict:
    key = f"lgw_{uuid.uuid4().hex}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    key_encrypted = encrypt_api_key(key)
    tier_value = ",".join(allowed_tiers or ["cheap", "expensive"])
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO api_keys (
                id, key_hash, key_encrypted, user_id, external_user_id,
                name, quota_monthly, rate_limit_rps, allowed_tiers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (key_hash[:16], key_hash, key_encrypted, user_id, external_user_id, name, quota, rate_limit, tier_value),
        )
        await db.commit()
    return {"key": key, "id": key_hash[:16], "name": name, "external_user_id": external_user_id}
