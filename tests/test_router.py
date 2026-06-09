import asyncio

import pytest

from app.models.request import ChatRequest, Message
from app.services.load_balancer import LoadBalancer, ModelInstance
from app.services.router import resolve_route


@pytest.fixture
def lb(monkeypatch):
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "gpt-4o-mini": ModelInstance(name="gpt-4o-mini", provider="openai", tier="cheap", weight=3),
        "claude-opus": ModelInstance(name="claude-opus", provider="anthropic", tier="expensive", weight=1),
    }
    lb._lock = asyncio.Lock()
    monkeypatch.setattr("app.services.router.get_load_balancer", lambda: lb)
    return lb


@pytest.mark.asyncio
async def test_resolve_with_explicit_tier(lb):
    req = ChatRequest(
        messages=[Message(role="user", content="Hello")],
        model_tier="cheap",
    )
    result = await resolve_route(req)
    assert result.tier == "cheap"


@pytest.mark.asyncio
async def test_resolve_preferred_model(lb):
    req = ChatRequest(
        messages=[Message(role="user", content="Hello")],
        preferred_model="claude-opus",
    )
    result = await resolve_route(req)
    assert result.name == "claude-opus"


@pytest.mark.asyncio
async def test_resolve_no_instances_raises(lb):
    import time
    for inst in lb._instances.values():
        inst.healthy = False
        inst.circuit_open_until = time.time() + 3600
    with pytest.raises(RuntimeError, match="No available model instances"):
        await resolve_route(
            ChatRequest(messages=[Message(role="user", content="Hello")], model_tier="cheap")
        )
