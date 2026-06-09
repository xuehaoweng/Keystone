from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
import traceback
import time
import uuid

from app.adapters.base import get_adapter
from app.middleware.auth import authenticate
from app.middleware.rate_limit import check_rate_limit
from app.models.request import ChatRequest
from app.models.response import ChatResponse, RouteInfo, UsageInfo
from app.services.dispatcher import dispatch_non_stream, dispatch_stream
from app.services.governance import RequestTrace, record_request_trace
from app.services.load_balancer import get_load_balancer
from app.services.metrics import get_metrics, get_monthly_usage
from app.services.provider_errors import ProviderError, normalize_provider_error
from app.services.result_cache import (
    build_cache_key,
    get_or_compute,
    should_cache_request,
)
from app.services.router import resolve_route

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _tier_allowed(user: dict, tier: str) -> bool:
    allowed = user.get("allowed_tiers")
    return not allowed or tier in allowed


async def _enforce_quota(user: dict) -> None:
    quota = int(user.get("quota_monthly") or 0)
    if quota <= 0:
        return
    used = await get_monthly_usage(user["user_id"], user.get("key_id"))
    if used >= quota:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly quota exceeded ({used}/{quota} tokens)",
        )


async def _dispatch_non_stream_with_retry(
    body: ChatRequest,
    instance,
    user_id: str,
    api_key_id: str | None,
    lb,
    metrics,
):
    attempted: set[str] = set()
    last_error: Exception | None = None
    last_provider_error: ProviderError | None = None
    current = instance

    for _ in range(3):
        attempted.add(current.name)
        try:
            adapter = get_adapter(current.name)
        except (ValueError, KeyError) as e:
            lb.release(current.name)
            raise HTTPException(status_code=500, detail=f"Adapter error: {e}")

        try:
            result = await dispatch_non_stream(
                adapter=adapter,
                request=body,
                model_name=current.name,
                tier=current.tier,
                route_path=f"model:{current.name}",
                user_id=user_id,
                lb=lb,
                metrics=metrics,
                api_key_id=api_key_id,
            )
            return current, result, list(attempted)
        except Exception as e:
            last_error = e
            last_provider_error = normalize_provider_error(e, provider=current.provider, model=current.name)
            if body.model:
                break

        next_instance = await lb.select(current.tier, exclude_names=attempted)
        if not next_instance and current.tier == "expensive":
            next_instance = await lb.select("cheap", exclude_names=attempted)
        if not next_instance:
            break
        current = next_instance

    if last_provider_error:
        raise HTTPException(status_code=502, detail=last_provider_error.__dict__)
    raise HTTPException(status_code=502, detail=f"Model error: {last_error}")


@router.post("", status_code=status.HTTP_200_OK)
async def create_run(request: Request, body: ChatRequest):
    start = time.time()
    request_id = getattr(
        request.state,
        "request_id",
        request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}",
    )
    await authenticate(request)
    await check_rate_limit(request)
    user = request.state.user
    user_id = user["user_id"]
    api_key_id = user.get("key_id")

    await _enforce_quota(user)

    lb = get_load_balancer()
    metrics = get_metrics()

    try:
        instance = await resolve_route(body)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not _tier_allowed(user, instance.tier):
        lb.release(instance.name)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is not allowed to use tier: {instance.tier}",
        )

    try:
        adapter = get_adapter(instance.name)
    except (ValueError, KeyError) as e:
        lb.release(instance.name)
        raise HTTPException(status_code=500, detail=f"Adapter error: {e}")

    route_path = f"model:{instance.name}"

    if body.stream:
        return StreamingResponse(
            dispatch_stream(
                adapter=adapter,
                request=body,
                model_name=instance.name,
                tier=instance.tier,
                route_path=route_path,
                user_id=user_id,
                lb=lb,
                metrics=metrics,
                api_key_id=api_key_id,
            ),
            media_type="text/event-stream",
        )
    else:
        try:
            cache_key = build_cache_key(body, instance.tier) if should_cache_request(body) else None
            if cache_key:
                async def _on_cache_hit(cached: ChatResponse):
                    cached.route = RouteInfo(
                        source="cache",
                        requested_tier=body.model_tier,
                        resolved_tier=instance.tier,
                        attempted_models=[instance.name],
                        fallback_used=False,
                        cache_hit=True,
                    )
                    await record_request_trace(RequestTrace(
                        request_id=request_id,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        provider=instance.provider,
                        model_name=instance.name,
                        tier=instance.tier,
                        status="success",
                        route_source="cache",
                        requested_tier=body.model_tier,
                        resolved_tier=instance.tier,
                        attempted_models=[instance.name],
                        cache_hit=True,
                        latency_ms=(time.time() - start) * 1000,
                        prompt_tokens=cached.usage.prompt_tokens,
                        completion_tokens=cached.usage.completion_tokens,
                        total_tokens=cached.usage.total_tokens,
                    ))

                async def _compute() -> ChatResponse:
                    inner_start = time.time()
                    final_instance, result, attempted_models = await _dispatch_non_stream_with_retry(
                        body=body,
                        instance=instance,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        lb=lb,
                        metrics=metrics,
                    )
                    response = ChatResponse(
                        id=f"run-{final_instance.name}",
                        model=final_instance.name,
                        tier=final_instance.tier,
                        content=result.content,
                        usage=UsageInfo(
                            prompt_tokens=result.prompt_tokens,
                            completion_tokens=result.completion_tokens,
                            total_tokens=result.total_tokens,
                        ),
                        finish_reason=result.finish_reason,
                        route=RouteInfo(
                            source="direct_model" if body.model else ("explicit_tier" if body.model_tier != "auto" else "auto"),
                            requested_tier=body.model_tier,
                            resolved_tier=final_instance.tier,
                            attempted_models=attempted_models,
                            fallback_used=len(attempted_models) > 1,
                            cache_hit=False,
                        ),
                    )
                    await record_request_trace(RequestTrace(
                        request_id=request_id,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        provider=final_instance.provider,
                        model_name=final_instance.name,
                        tier=final_instance.tier,
                        status="success",
                        route_source=response.route.source if response.route else None,
                        requested_tier=body.model_tier,
                        resolved_tier=final_instance.tier,
                        attempted_models=attempted_models,
                        fallback_used=len(attempted_models) > 1,
                        cache_hit=False,
                        latency_ms=(time.time() - inner_start) * 1000,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        total_tokens=result.total_tokens,
                    ))
                    return response

                return await get_or_compute(cache_key, _compute, _on_cache_hit)

            final_instance, result, attempted_models = await _dispatch_non_stream_with_retry(
                body=body,
                instance=instance,
                user_id=user_id,
                api_key_id=api_key_id,
                lb=lb,
                metrics=metrics,
            )
            response = ChatResponse(
                id=f"run-{final_instance.name}",
                model=final_instance.name,
                tier=final_instance.tier,
                content=result.content,
                usage=UsageInfo(
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                ),
                finish_reason=result.finish_reason,
                route=RouteInfo(
                    source="direct_model" if body.model else ("explicit_tier" if body.model_tier != "auto" else "auto"),
                    requested_tier=body.model_tier,
                    resolved_tier=final_instance.tier,
                    attempted_models=attempted_models,
                    fallback_used=len(attempted_models) > 1,
                    cache_hit=False,
                ),
            )
            await record_request_trace(RequestTrace(
                request_id=request_id,
                user_id=user_id,
                api_key_id=api_key_id,
                provider=final_instance.provider,
                model_name=final_instance.name,
                tier=final_instance.tier,
                status="success",
                route_source=response.route.source if response.route else None,
                requested_tier=body.model_tier,
                resolved_tier=final_instance.tier,
                attempted_models=attempted_models,
                fallback_used=len(attempted_models) > 1,
                cache_hit=False,
                latency_ms=(time.time() - start) * 1000,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
            ))
            return response
        except Exception as e:
            await record_request_trace(RequestTrace(
                request_id=request_id,
                user_id=user_id,
                api_key_id=api_key_id,
                provider=instance.provider,
                model_name=instance.name,
                tier=instance.tier,
                status="error",
                requested_tier=body.model_tier,
                resolved_tier=instance.tier,
                attempted_models=[instance.name],
                latency_ms=(time.time() - start) * 1000,
                error_type=type(e).__name__,
                error_detail=str(e),
            ))
            tb = traceback.format_exc()
            print("=== DISPATCH ERROR ===")
            print(f"Model: {instance.name}, Provider: {instance.tier}")
            print(f"Exception: {e}")
            print(tb)
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=502, detail=f"Model error: {e}")
