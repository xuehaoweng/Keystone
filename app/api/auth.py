from fastapi import APIRouter, HTTPException, Request

from app.middleware.auth import authenticate, create_api_key, decrypt_api_key
from app.db.sqlite import get_db
from app.services.governance import record_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def me(request: Request):
    await authenticate(request)
    user = request.state.user
    return {
        "user_id": user["user_id"],
        "role": user.get("role", "user"),
        "auth_type": request.state.auth_type,
    }


@router.post("/keys")
async def create_key(
    request: Request,
    name: str = "default",
    quota: int = 0,
    rate_limit: int = 10,
    allowed_tiers: str = "cheap,expensive",
    owner_user_id: str | None = None,
    external_user_id: str | None = None,
):
    await authenticate(request)
    user = request.state.user
    tiers = [tier.strip() for tier in allowed_tiers.split(",") if tier.strip()]
    is_admin = user.get("role") == "admin"
    normalized_owner = owner_user_id.strip() if owner_user_id else None
    target_user_id = normalized_owner or user["user_id"]
    if normalized_owner and (not is_admin and normalized_owner != user["user_id"]):
        raise HTTPException(
            status_code=403,
            detail="仅管理员可为他人创建 API Key。",
        )
    result = await create_api_key(
        name=name,
        user_id=target_user_id,
        external_user_id=external_user_id.strip() if external_user_id else None,
        quota=quota,
        rate_limit=rate_limit,
        allowed_tiers=tiers,
    )
    await record_audit(
        actor_user_id=user.get("user_id"),
        api_key_id=user.get("key_id"),
        action="api_key.create",
        target_type="api_key",
        target_id=result["id"],
        detail={
            "name": name,
            "owner_user_id": target_user_id,
            "external_user_id": external_user_id.strip() if external_user_id else None,
            "quota": quota,
            "rate_limit": rate_limit,
            "allowed_tiers": tiers,
        },
        ip_address=request.client.host if request.client else None,
    )
    return result


@router.get("/keys")
async def list_keys(request: Request, owner_user_id: str | None = None):
    await authenticate(request)
    user = request.state.user
    is_admin = user.get("role") == "admin"
    normalized_owner = owner_user_id.strip() if owner_user_id else None
    target_user_id = normalized_owner or user["user_id"]
    if normalized_owner and (not is_admin and normalized_owner != user["user_id"]):
        raise HTTPException(
            status_code=403,
            detail="仅管理员可查询他人 API Key。",
        )
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, key_encrypted, user_id, external_user_id, name, quota_monthly, rate_limit_rps, allowed_tiers, created_at
            FROM api_keys
            WHERE user_id = ? AND active = 1
            """,
            (target_user_id,),
        )
        rows = await cursor.fetchall()
    return [
        {
            "id": r[0],
            "key": decrypt_api_key(r[1]),
            "owner_user_id": r[2],
            "external_user_id": r[3],
            "name": r[4],
            "quota_monthly": r[5],
            "rate_limit_rps": r[6],
            "allowed_tiers": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


@router.get("/keys/{key_id}/usage")
async def get_key_usage(key_id: str, request: Request):
    await authenticate(request)
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id FROM api_keys WHERE id = ? AND active = 1",
            (key_id,),
        )
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    user_id = row[0]
    from app.services.metrics import get_usage_summary

    return await get_usage_summary(user_id=user_id, api_key_id=key_id)


@router.delete("/keys/{key_id}")
async def delete_key(key_id: str, request: Request):
    await authenticate(request)
    async with get_db() as db:
        await db.execute("UPDATE api_keys SET active = 0 WHERE id = ?", (key_id,))
        await db.commit()
    user = request.state.user
    await record_audit(
        actor_user_id=user.get("user_id"),
        api_key_id=user.get("key_id"),
        action="api_key.delete",
        target_type="api_key",
        target_id=key_id,
        ip_address=request.client.host if request.client else None,
    )
    return {"deleted": True}
