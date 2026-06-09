import os

from fastapi import APIRouter, Body, HTTPException, Query, Request

from app.config import get_gateway_config, get_models_config
from app.middleware.auth import authenticate
from app.services.load_balancer import get_load_balancer
from app.services.governance import (
    apply_policy_draft,
    create_policy_draft,
    current_policy_bundle,
    provider_sla,
    query_audit_logs,
    query_request_traces,
    list_policy_drafts,
    record_audit,
)
from app.services.metrics import get_usage_summary, query_usage

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/models")
async def list_models(request: Request):
    await authenticate(request)
    lb = get_load_balancer()
    return await lb.get_all()


@router.get("/models/{model_name}/health")
async def model_health(model_name: str, request: Request):
    await authenticate(request)
    lb = get_load_balancer()
    all_status = await lb.get_all()
    if model_name not in all_status:
        return {"name": model_name, "status": "unknown"}
    info = all_status[model_name]
    return {"name": model_name, **info, "status": "healthy" if info["healthy"] else "unhealthy"}


@router.get("/providers/health")
async def provider_health(request: Request):
    await authenticate(request)
    models_config = get_models_config()
    models = models_config.get("models", [])
    providers = {}
    for name, provider in models_config.get("providers", {}).items():
        provider_models = [m["name"] for m in models if m.get("provider") == name]
        env_keys = [
            key.strip()
            for key in os.getenv(f"{name.upper()}_API_KEY", "").split(",")
            if key.strip()
        ]
        config_keys = provider.get("api_keys", [])
        if not provider_models:
            provider_status = "unused"
        elif env_keys or config_keys:
            provider_status = "ready"
        else:
            provider_status = "missing_key"
        providers[name] = {
            "base_url": provider.get("base_url"),
            "configured_key_count": len(env_keys) + len(config_keys),
            "env_key_configured": bool(env_keys),
            "config_key_count": len(config_keys),
            "models": provider_models,
            "status": provider_status,
        }
    return {"providers": providers}


@router.get("/metrics")
async def metrics_summary(request: Request):
    await authenticate(request)
    return await get_usage_summary()


@router.get("/usage")
async def usage_summary(
    request: Request,
    from_ts: str | None = None,
    to_ts: str | None = None,
    key_id: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    await authenticate(request)
    return await query_usage(
        from_ts=from_ts,
        to_ts=to_ts,
        key_id=key_id,
        model=model,
        tier=tier,
        limit=limit,
        offset=offset,
    )


@router.get("/traces")
async def traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    await authenticate(request)
    return await query_request_traces(limit=limit, offset=offset)


@router.get("/providers/sla")
async def providers_sla(request: Request):
    await authenticate(request)
    return await provider_sla()


@router.get("/audit")
async def audit_logs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    await authenticate(request)
    return await query_audit_logs(limit=limit, offset=offset)


@router.get("/policies")
async def policies(request: Request):
    await authenticate(request)
    return {
        "current": current_policy_bundle(),
        "drafts": await list_policy_drafts(),
    }


@router.post("/policies/drafts")
async def create_policy(
    request: Request,
    payload: dict = Body(...),
):
    await authenticate(request)
    name = str(payload.get("name") or "policy-draft")
    content = payload.get("content")
    if not isinstance(content, dict):
        raise HTTPException(status_code=422, detail="content must be an object")
    user = request.state.user
    draft = await create_policy_draft(name=name, content=content, created_by=user.get("user_id"))
    await record_audit(
        actor_user_id=user.get("user_id"),
        api_key_id=user.get("key_id"),
        action="policy.draft.create",
        target_type="policy_draft",
        target_id=str(draft["id"]),
        detail={"name": name},
        ip_address=request.client.host if request.client else None,
    )
    return draft


@router.post("/policies/drafts/{draft_id}/apply")
async def apply_policy(
    draft_id: int,
    request: Request,
):
    await authenticate(request)
    draft = await apply_policy_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Policy draft not found")
    user = request.state.user
    await record_audit(
        actor_user_id=user.get("user_id"),
        api_key_id=user.get("key_id"),
        action="policy.draft.apply",
        target_type="policy_draft",
        target_id=str(draft_id),
        detail={"name": draft["name"], "status": "applied"},
        ip_address=request.client.host if request.client else None,
    )
    return draft


@router.get("/config")
async def config_summary(request: Request):
    await authenticate(request)
    models_config = get_models_config()
    safe_models_config = {
        **models_config,
        "providers": {
            name: {**provider, "api_keys": []}
            for name, provider in models_config.get("providers", {}).items()
        },
    }
    return {
        "gateway": get_gateway_config(),
        "models": safe_models_config,
    }
