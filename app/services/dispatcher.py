import asyncio
import inspect
import json
import time
import uuid

from app.adapters.base import ChatResult, ModelAdapter
from app.models.request import ChatRequest, Message
from app.services.metrics import MetricsCollector, RequestMetric


def _messages_to_dict(messages: list[Message]) -> list[dict]:
    return [m.model_dump() for m in messages]


async def dispatch_non_stream(
    adapter: ModelAdapter,
    request: ChatRequest,
    model_name: str,
    tier: str,
    route_path: str,
    user_id: str,
    lb,
    metrics: MetricsCollector,
    api_key_id: str | None = None,
) -> ChatResult:
    start = time.time()
    messages = _messages_to_dict(request.messages)
    try:
        result = await adapter.chat(
            messages=messages,
            stream=False,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        lb.report_success(model_name)
        lb.release(model_name)
        latency = (time.time() - start) * 1000
        await metrics.record(RequestMetric(
            user_id=user_id,
            model_name=model_name,
            tier=tier,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=latency,
            is_stream=False,
            route_path=route_path,
            api_key_id=api_key_id,
        ))
        return result
    except Exception:
        lb.report_error(model_name)
        lb.release(model_name)
        raise


async def dispatch_stream(
    adapter: ModelAdapter,
    request: ChatRequest,
    model_name: str,
    tier: str,
    route_path: str,
    user_id: str,
    lb,
    metrics: MetricsCollector,
    api_key_id: str | None = None,
):
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    messages = _messages_to_dict(request.messages)
    total_prompt = 0
    total_completion = 0
    start = time.time()
    try:
        stream_result = adapter.chat(
            messages=messages,
            stream=True,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        stream = await stream_result if inspect.isawaitable(stream_result) else stream_result
        async for chunk in stream:
            total_completion += chunk.completion_tokens
            if chunk.content:
                yield f'event: chunk\ndata: {{"id": "{run_id}", "model": "{model_name}", "content": {json.dumps(chunk.content)}, "finish_reason": {json.dumps(chunk.finish_reason)}}}\n\n'
            if chunk.finish_reason:
                total_prompt = chunk.prompt_tokens
                yield f'event: done\ndata: {{"id": "{run_id}", "model": "{model_name}", "finish_reason": {json.dumps(chunk.finish_reason)}}}\n\n'
        lb.report_success(model_name)
        lb.release(model_name)
        latency = (time.time() - start) * 1000
        await metrics.record(RequestMetric(
            user_id=user_id,
            model_name=model_name,
            tier=tier,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            total_tokens=total_prompt + total_completion,
            latency_ms=latency,
            is_stream=True,
            route_path=route_path,
            api_key_id=api_key_id,
        ))
    except asyncio.CancelledError:
        lb.release(model_name)
        raise
    except Exception:
        lb.report_error(model_name)
        lb.release(model_name)
        raise
