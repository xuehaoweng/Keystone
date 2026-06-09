from fastapi import HTTPException, Request, status

from app.db.redis import get_redis


async def check_rate_limit(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if not user:
        return
    user_id = user["user_id"]
    rps = user.get("rate_limit_rps", 10)
    try:
        r = await get_redis()
    except Exception:
        # Redis unavailable — allow request to proceed
        return
    key = f"ratelimit:{user_id}"
    try:
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, 1)
        if current > rps:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({rps} rps)",
            )
    except HTTPException:
        raise
    except Exception:
        # Redis error — allow request to proceed
        return
