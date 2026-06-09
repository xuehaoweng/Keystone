"""Anthropic-compatible API endpoints.

Supports POST /v1/messages so that Claude Code and other Anthropic-native
clients can use LLM Gateway as a drop-in base_url replacement.
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

router = APIRouter(tags=["anthropic-compatible"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AnthropicMessage(BaseModel):
    role: str
    content: str | list[dict]


class AnthropicMessageRequest(BaseModel):
    model: str | None = None
    messages: list[AnthropicMessage]
    max_tokens: int = Field(default=4096, gt=0, le=128000)
    system: str | None = None
    stream: bool = False
    temperature: float = Field(default=1.0, ge=0, le=1)
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] | None = None
    metadata: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text_content(content: str | list[dict]) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return ""


def _to_internal_request(body: AnthropicMessageRequest) -> ChatRequest:
    """Convert an Anthropic-style request into the gateway's internal ChatRequest."""
    messages: list[Message] = []
    if body.system:
        messages.append(Message(role="system", content=body.system))
    for m in body.messages:
        # Anthropic only uses 'user' and 'assistant' in messages list;
        # system is a separate field already handled above.
        role = m.role
        if role not in ("user", "assistant", "system"):
            role = "user"
        messages.append(Message(role=role, content=_extract_text_content(m.content)))
    return ChatRequest(
        messages=messages,
        stream=body.stream,
        model=body.model,
        model_tier="auto",
        temperature=body.temperature,
        max_tokens=body.max_tokens,
    )


def _build_anthropic_response(
    result,
    model_name: str,
    request_id: str,
) -> dict:
    """Build an Anthropic-compatible message response."""
    return {
        "id": f"msg_{request_id}",
        "type": "message",
        "role": "assistant",
        "model": model_name,
        "content": [
            {"type": "text", "text": result.content},
        ],
        "stop_reason": result.finish_reason or "end_turn",
        "usage": {
            "input_tokens": result.prompt_tokens,
            "output_tokens": result.completion_tokens,
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
    """Dispatch a non-streaming request with fallback retry logic."""
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


async def _anthropic_stream_generator(
    body: ChatRequest,
    instance,
    user_id: str,
    api_key_id: str | None,
    lb,
    metrics,
    request_id: str,
):
    """Yield Anthropic-compatible SSE events."""
    msg_id = f"msg_{request_id}"
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

        # message_start
        start_event = {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": instance.name,
                "content": [],
                "stop_reason": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        yield f"event: message_start\ndata: {json.dumps(start_event)}\n\n"

        # content_block_start
        block_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n"

        async for chunk in stream:
            total_completion += chunk.completion_tokens
            if chunk.content:
                delta_event = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": chunk.content},
                }
                yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
            if chunk.finish_reason:
                total_prompt = chunk.prompt_tokens
                # content_block_stop
                block_stop = {"type": "content_block_stop", "index": 0}
                yield f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n"

                # message_delta
                msg_delta = {
                    "type": "message_delta",
                    "delta": {"stop_reason": chunk.finish_reason},
                    "usage": {"output_tokens": total_completion},
                }
                yield f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n"

                # message_stop
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

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
    except Exception:
        await lb.report_error(instance.name)
        lb.release(instance.name)
        raise


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/v1/anthropic")
async def create_message(request: Request, body: AnthropicMessageRequest):
    """Anthropic-compatible messages endpoint.

    Clients can set ``base_url`` to the gateway root and use their Gateway
    API Key as the ``x-api-key``:

    .. code-block:: bash

        export ANTHROPIC_API_KEY="lgw_xxx"
        claude --api-provider anthropic --api-url http://localhost:8000

    When ``model`` is omitted the gateway's rule engine + intent classifier
    pick the best model, exactly like ``POST /api/runs``.
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
            _anthropic_stream_generator(
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
    return _build_anthropic_response(result, final_instance.name, request_id)
