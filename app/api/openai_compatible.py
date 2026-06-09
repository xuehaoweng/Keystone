"""OpenAI-compatible API endpoints.

Supports POST /v1/chat/completions and GET /v1/models so that clients
using the OpenAI SDK (or tools like Claude Code, Continue, Cursor, etc.)
can use LLM Gateway as a drop-in base_url replacement.
"""

import inspect
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.adapters.base import get_adapter
from app.api.runs import _enforce_quota, _tier_allowed
from app.middleware.auth import authenticate
from app.middleware.rate_limit import check_rate_limit
from app.models.request import ChatRequest, Message
from app.services.dispatcher import dispatch_non_stream
from app.services.load_balancer import get_load_balancer
from app.services.metrics import RequestMetric, get_metrics, get_monthly_usage
from app.services.provider_errors import ProviderError, normalize_provider_error
from app.services.router import resolve_route

router = APIRouter(tags=["openai-compatible"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OpenAIMessage(BaseModel):
    role: str
    content: str | list[dict] | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class OpenAIChatRequest(BaseModel):
    model: str | None = None
    messages: list[OpenAIMessage]
    stream: bool = False
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0, le=128000)
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | list[str] | None = None
    user: str | None = None
    n: int | None = Field(default=1, ge=1, le=1)


class OpenAIModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text_content(content: str | list[dict] | None) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def _to_internal_request(body: OpenAIChatRequest) -> ChatRequest:
    """Convert an OpenAI-style request into the gateway's internal ChatRequest."""
    return ChatRequest(
        messages=[
            Message(
                role=m.role,
                content=_extract_text_content(m.content),
                name=m.name,
            )
            for m in body.messages
        ],
        stream=body.stream,
        model=body.model,
        model_tier="auto",
        temperature=body.temperature,
        max_tokens=body.max_tokens or 4096,
    )


def _openai_id(request_id: str) -> str:
    return f"chatcmpl-{request_id}"


def _build_openai_response(
    result,
    model_name: str,
    request_id: str,
) -> dict:
    """Build an OpenAI-compatible chat.completion response."""
    return {
        "id": _openai_id(request_id),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": result.content,
                },
                "finish_reason": result.finish_reason or "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
    }


async def _dispatch_non_stream_with_retry(
    body: ChatRequest,
    instance,
    user_id: str,
    api_key_id: str | None,
    lb,
    metrics,
):
    """Dispatch a non-streaming request with fallback retry logic.

    Mirrors the logic in app/api/runs.py so both endpoints behave identically.
    """
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
            last_provider_error = normalize_provider_error(
                e, provider=current.provider, model=current.name
            )
            if body.model:
                break

        next_instance = await lb.select(current.tier, exclude_names=attempted)
        if not next_instance and current.tier == "expensive":
            next_instance = await lb.select("cheap", exclude_names=attempted)
        if not next_instance:
            break
        current = next_instance

    if last_provider_error:
        raise HTTPException(status_code=502, detail={
            "code": last_provider_error.code,
            "message": last_provider_error.message,
            "provider": last_provider_error.provider,
            "model": last_provider_error.model,
            "status_code": last_provider_error.status_code,
        })
    raise HTTPException(status_code=502, detail={"code": "model_error", "message": str(last_error)})


async def _openai_stream_generator(
    body: ChatRequest,
    instance,
    user_id: str,
    api_key_id: str | None,
    lb,
    metrics,
    request_id: str,
):
    """Yield OpenAI-compatible SSE chunks."""
    run_id = _openai_id(request_id)
    messages = [m.model_dump() for m in body.messages]
    total_prompt = 0
    total_completion = 0
    start = time.time()

    try:
        adapter = get_adapter(instance.name)
        stream_result = adapter.chat(
            messages=messages,
            stream=True,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        stream = await stream_result if inspect.isawaitable(stream_result) else stream_result

        # First chunk: role
        first_chunk = {
            "id": run_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": instance.name,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(first_chunk)}\n\n"

        async for chunk in stream:
            total_completion += chunk.completion_tokens
            if chunk.content:
                data = {
                    "id": run_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": instance.name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk.content},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(data)}\n\n"
            if chunk.finish_reason:
                total_prompt = chunk.prompt_tokens
                data = {
                    "id": run_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": instance.name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": chunk.finish_reason,
                        }
                    ],
                }
                yield f"data: {json.dumps(data)}\n\n"

        await lb.report_success(instance.name)
        lb.release(instance.name)
        latency = (time.time() - start) * 1000
        await metrics.record(
            RequestMetric(
                user_id=user_id,
                model_name=instance.name,
                tier=instance.tier,
                prompt_tokens=total_prompt,
                completion_tokens=total_completion,
                total_tokens=total_prompt + total_completion,
                latency_ms=latency,
                is_stream=True,
                route_path=f"model:{instance.name}",
                api_key_id=api_key_id,
            )
        )
        yield "data: [DONE]\n\n"
    except Exception:
        await lb.report_error(instance.name)
        lb.release(instance.name)
        raise


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/models")
async def list_models(request: Request):
    """List available models in OpenAI-compatible format."""
    await authenticate(request)
    from app.config import get_models_config

    cfg = get_models_config()
    models = cfg.get("models", [])
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": m["name"],
                "object": "model",
                "created": now,
                "owned_by": m.get("provider", "unknown"),
            }
            for m in models
        ],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, body: OpenAIChatRequest):
    """OpenAI-compatible chat completions endpoint.

    Clients can set ``base_url`` to the gateway root and use their Gateway
    API Key as the ``api_key``:

    .. code-block:: python

        import openai
        client = openai.OpenAI(
            api_key="lgw_xxx",
            base_url="http://localhost:8000/v1",
        )
        client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hello"}],
        )

    When ``model`` is omitted (or set to a gateway-internal alias such as
    ``auto``), the gateway's rule engine + intent classifier pick the best
    model, exactly like ``POST /api/runs``.
    """
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

    internal_body = _to_internal_request(body)

    lb = get_load_balancer()
    metrics = get_metrics()

    try:
        instance = await resolve_route(internal_body)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not _tier_allowed(user, instance.tier):
        lb.release(instance.name)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"API key is not allowed to use tier: {instance.tier}",
        )

    if internal_body.stream:
        return StreamingResponse(
            _openai_stream_generator(
                body=internal_body,
                instance=instance,
                user_id=user_id,
                api_key_id=api_key_id,
                lb=lb,
                metrics=metrics,
                request_id=request_id,
            ),
            media_type="text/event-stream",
        )

    final_instance, result, attempted_models = await _dispatch_non_stream_with_retry(
        body=internal_body,
        instance=instance,
        user_id=user_id,
        api_key_id=api_key_id,
        lb=lb,
        metrics=metrics,
    )
    return _build_openai_response(result, final_instance.name, request_id)
