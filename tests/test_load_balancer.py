import asyncio

import pytest

from app.services.load_balancer import LoadBalancer, ModelInstance


@pytest.fixture
def lb():
    lb = LoadBalancer.__new__(LoadBalancer)
    lb._instances = {
        "m1": ModelInstance(name="m1", provider="openai", tier="cheap", weight=1),
        "m2": ModelInstance(name="m2", provider="openai", tier="cheap", weight=2),
        "m3": ModelInstance(name="m3", provider="openai", tier="expensive", weight=1),
    }
    lb._lock = asyncio.Lock()
    return lb


@pytest.mark.asyncio
async def test_select_from_tier(lb):
    result = await lb.select("cheap")
    assert result is not None
    assert result.tier == "cheap"


@pytest.mark.asyncio
async def test_select_returns_none_for_empty_tier(lb):
    result = await lb.select("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_select_respects_capacity(lb):
    lb._instances["m1"].max_concurrent = 1
    lb._instances["m1"].current_connections = 1
    result = await lb.select("cheap")
    assert result.name == "m2"


@pytest.mark.asyncio
async def test_release_decreases_connections(lb):
    selected = await lb.select("cheap")
    assert selected.current_connections == 1
    lb.release(selected.name)
    assert lb._instances[selected.name].current_connections == 0


@pytest.mark.asyncio
async def test_report_error_marks_unhealthy(lb):
    for _ in range(5):
        await lb.report_error("m1")
    assert lb._instances["m1"].healthy is False


@pytest.mark.asyncio
async def test_report_success_resets(lb):
    for _ in range(5):
        await lb.report_error("m1")
    await lb.report_success("m1")
    assert lb._instances["m1"].healthy is True
    assert lb._instances["m1"].error_count == 0


@pytest.mark.asyncio
async def test_report_error_opens_circuit(lb, monkeypatch):
    monkeypatch.setattr("app.services.load_balancer.time.time", lambda: 100.0)
    for _ in range(5):
        await lb.report_error("m1")

    assert lb._instances["m1"].healthy is False
    assert lb._instances["m1"].circuit_open_until == 130.0


@pytest.mark.asyncio
async def test_get_by_tier_recovers_after_circuit_cooldown(lb, monkeypatch):
    monkeypatch.setattr("app.services.load_balancer.time.time", lambda: 100.0)
    for _ in range(5):
        await lb.report_error("m1")

    monkeypatch.setattr("app.services.load_balancer.time.time", lambda: 131.0)
    candidates = await lb.get_by_tier("cheap")

    assert lb._instances["m1"] in candidates
    assert lb._instances["m1"].healthy is True
    assert lb._instances["m1"].error_count == 0


@pytest.mark.asyncio
async def test_get_all(lb):
    result = await lb.get_all()
    assert "m1" in result
    assert result["m1"]["tier"] == "cheap"
