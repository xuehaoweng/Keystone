from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.base import ChatChunk, ChatResult
from app.db.sqlite import close_db, get_db, init_db, set_db_path
from app.models.request import ChatRequest, Message
from app.services.metrics import MetricsCollector


@pytest.fixture
def mock_adapter():
    adapter = MagicMock()
    adapter.chat = AsyncMock()
    return adapter


@pytest.fixture
def mock_lb():
    lb = MagicMock()
    lb.report_success = AsyncMock()
    lb.report_error = AsyncMock()
    lb.release = MagicMock()
    return lb


@pytest.fixture
def mock_metrics():
    return MetricsCollector()


@pytest.fixture(autouse=True)
async def isolated_sqlite(tmp_path):
    await close_db()
    set_db_path(str(tmp_path / "gateway-test.db"))
    await init_db()
    yield
    await close_db()
    set_db_path("gateway.db")


@pytest.mark.asyncio
async def test_dispatch_non_stream_success(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_non_stream
    mock_adapter.chat.return_value = ChatResult(
        content="Hello",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        model="gpt-4o-mini",
    )
    request = ChatRequest(messages=[Message(role="user", content="Hi")])
    result = await dispatch_non_stream(
        adapter=mock_adapter,
        request=request,
        model_name="gpt-4o-mini",
        tier="cheap",
        route_path="rule:general_query",
        user_id="user-1",
        lb=mock_lb,
        metrics=mock_metrics,
    )
    assert result.content == "Hello"
    mock_lb.report_success.assert_called_once_with("gpt-4o-mini")
    assert mock_metrics.get_summary()["total_requests"] == 1


@pytest.mark.asyncio
async def test_dispatch_non_stream_error(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_non_stream
    mock_adapter.chat.side_effect = RuntimeError("API error")
    request = ChatRequest(messages=[Message(role="user", content="Hi")])
    with pytest.raises(RuntimeError, match="API error"):
        await dispatch_non_stream(
            adapter=mock_adapter,
            request=request,
            model_name="gpt-4o-mini",
            tier="cheap",
            route_path="rule:general_query",
            user_id="user-1",
            lb=mock_lb,
            metrics=mock_metrics,
        )
    mock_lb.report_error.assert_called_once_with("gpt-4o-mini")


@pytest.mark.asyncio
async def test_dispatch_stream_yields_chunks(mock_adapter, mock_lb, mock_metrics):
    from app.services.dispatcher import dispatch_stream
    async def mock_stream(**kwargs):
        yield ChatChunk(content="Hel")
        yield ChatChunk(content="lo")
        yield ChatChunk(content="", finish_reason="stop")
    mock_adapter.chat = mock_stream
    request = ChatRequest(messages=[Message(role="user", content="Hi")], stream=True)
    chunks = []
    async for chunk in dispatch_stream(
        adapter=mock_adapter,
        request=request,
        model_name="gpt-4o-mini",
        tier="cheap",
        route_path="rule:general_query",
        user_id="user-1",
        lb=mock_lb,
        metrics=mock_metrics,
    ):
        chunks.append(chunk)
    assert len(chunks) == 3
    assert "event: chunk" in chunks[0]
    assert "event: done" in chunks[-1]
    mock_lb.report_success.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_non_stream_persists_usage_and_cost(
    monkeypatch,
    mock_adapter,
    mock_lb,
):
    from app.services.dispatcher import dispatch_non_stream

    monkeypatch.setattr("app.services.metrics.get_models_config", lambda: {
        "models": [
            {
                "name": "priced-model",
                "tier": "cheap",
                "provider": "openai",
                "input_cost_per_1k": 0.10,
                "output_cost_per_1k": 0.20,
            }
        ]
    })
    metrics = MetricsCollector()
    mock_adapter.chat.return_value = ChatResult(
        content="Hello",
        prompt_tokens=1000,
        completion_tokens=500,
        total_tokens=1500,
        model="priced-model",
    )

    await dispatch_non_stream(
        adapter=mock_adapter,
        request=ChatRequest(messages=[Message(role="user", content="Hi")]),
        model_name="priced-model",
        tier="cheap",
        route_path="model:priced-model",
        user_id="user-1",
        lb=mock_lb,
        metrics=metrics,
        api_key_id="key-1",
    )

    usage = metrics.get_user_usage("user-1")
    assert usage["total_tokens"] == 1500
    assert usage["total_cost_estimate"] == pytest.approx(0.20)

    await metrics.force_flush()

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT api_key_id, user_id, model_name, total_tokens, cost_estimate FROM usage_logs"
        )
        row = await cursor.fetchone()

    assert row["api_key_id"] == "key-1"
    assert row["user_id"] == "user-1"
    assert row["model_name"] == "priced-model"
    assert row["total_tokens"] == 1500
    assert row["cost_estimate"] == pytest.approx(0.20)


@pytest.mark.asyncio
async def test_usage_summary_reads_from_database(mock_adapter, mock_lb):
    from app.services.dispatcher import dispatch_non_stream
    from app.services.metrics import MetricsCollector, get_usage_summary

    mock_adapter.chat.return_value = ChatResult(
        content="Hello",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        model="gpt-4o-mini",
    )

    metrics = MetricsCollector()
    await dispatch_non_stream(
        adapter=mock_adapter,
        request=ChatRequest(messages=[Message(role="user", content="Hi")]),
        model_name="gpt-4o-mini",
        tier="cheap",
        route_path="model:gpt-4o-mini",
        user_id="user-db",
        lb=mock_lb,
        metrics=metrics,
        api_key_id="key-db",
    )

    await metrics.force_flush()

    summary = await get_usage_summary(api_key_id="key-db")

    assert summary["total_tokens"] == 150
    assert summary["total_requests"] == 1
