import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_models_config
from app.db.sqlite import get_db, init_db

@dataclass
class RequestMetric:
    user_id: str
    model_name: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    is_stream: bool
    route_path: str
    api_key_id: str | None = None
    cost_estimate: float = 0.0
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    def __init__(self):
        self._metrics: list[RequestMetric] = []
        self._user_usage: dict[str, dict] = defaultdict(lambda: {
            "total_tokens": 0,
            "total_requests": 0,
            "total_cost_estimate": 0.0,
        })

    async def record(self, metric: RequestMetric):
        metric.cost_estimate = calculate_cost(
            metric.model_name,
            metric.prompt_tokens,
            metric.completion_tokens,
        )
        self._metrics.append(metric)
        usage = self._user_usage[metric.user_id]
        usage["total_tokens"] += metric.total_tokens
        usage["total_requests"] += 1
        usage["total_cost_estimate"] += metric.cost_estimate
        await persist_usage(metric)

    def get_user_usage(self, user_id: str) -> dict:
        return self._user_usage.get(user_id, {})

    def get_summary(self) -> dict:
        total = len(self._metrics)
        if total == 0:
            return {"total_requests": 0}
        return {
            "total_requests": total,
            "avg_latency_ms": sum(m.latency_ms for m in self._metrics) / total,
            "total_tokens": sum(m.total_tokens for m in self._metrics),
            "total_cost_estimate": sum(m.cost_estimate for m in self._metrics),
        }


def calculate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    models = get_models_config().get("models", [])
    model_cfg = next((m for m in models if m.get("name") == model_name), {})
    input_price = model_cfg.get("input_cost_per_1k", model_cfg.get("cost_per_1k", 0))
    output_price = model_cfg.get("output_cost_per_1k", model_cfg.get("cost_per_1k", 0))
    return (prompt_tokens / 1000 * input_price) + (completion_tokens / 1000 * output_price)


async def persist_usage(metric: RequestMetric) -> None:
    await init_db()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO usage_logs (
                api_key_id, user_id, model_name, tier, prompt_tokens,
                completion_tokens, total_tokens, latency_ms, route_path, cost_estimate
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metric.api_key_id,
                metric.user_id,
                metric.model_name,
                metric.tier,
                metric.prompt_tokens,
                metric.completion_tokens,
                metric.total_tokens,
                metric.latency_ms,
                metric.route_path,
                metric.cost_estimate,
            ),
        )
        await db.commit()


async def get_monthly_usage(user_id: str, api_key_id: str | None = None) -> int:
    month_start = datetime.now(timezone.utc).replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ).strftime("%Y-%m-%d %H:%M:%S")
    if api_key_id:
        where = "api_key_id = ?"
        params = (api_key_id, month_start)
    else:
        where = "user_id = ?"
        params = (user_id, month_start)

    async with get_db() as db:
        cursor = await db.execute(
            f"SELECT COALESCE(SUM(total_tokens), 0) FROM usage_logs WHERE {where} AND timestamp >= ?",
            params,
        )
        row = await cursor.fetchone()
    return int(row[0] or 0)


async def get_usage_summary(
    user_id: str | None = None,
    api_key_id: str | None = None,
) -> dict:
    clauses = []
    params = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if api_key_id:
        clauses.append("api_key_id = ?")
        params.append(api_key_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    async with get_db() as db:
        cursor = await db.execute(
            f"""
            SELECT
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COUNT(*) AS total_requests,
                COALESCE(SUM(cost_estimate), 0) AS total_cost_estimate,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM usage_logs
            {where}
            """,
            tuple(params),
        )
        row = await cursor.fetchone()

    return {
        "total_tokens": int(row["total_tokens"] or 0),
        "total_requests": int(row["total_requests"] or 0),
        "total_cost_estimate": float(row["total_cost_estimate"] or 0),
        "avg_latency_ms": float(row["avg_latency_ms"] or 0),
    }


async def query_usage(
    from_ts: str | None = None,
    to_ts: str | None = None,
    key_id: str | None = None,
    model: str | None = None,
    tier: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    clauses = []
    params: list[str | int] = []
    if from_ts:
        clauses.append("timestamp >= ?")
        params.append(from_ts)
    if to_ts:
        clauses.append("timestamp <= ?")
        params.append(to_ts)
    if key_id:
        clauses.append("api_key_id = ?")
        params.append(key_id)
    if model:
        clauses.append("model_name = ?")
        params.append(model)
    if tier:
        clauses.append("tier = ?")
        params.append(tier)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    async with get_db() as db:
        summary_cursor = await db.execute(
            f"""
            SELECT
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COUNT(*) AS total_requests,
                COALESCE(SUM(cost_estimate), 0) AS total_cost_estimate,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM usage_logs
            {where}
            """,
            tuple(params),
        )
        summary_row = await summary_cursor.fetchone()

        item_cursor = await db.execute(
            f"""
            SELECT
                id, api_key_id, user_id, model_name, tier, prompt_tokens,
                completion_tokens, total_tokens, latency_ms, route_path,
                cost_estimate, timestamp
            FROM usage_logs
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        rows = await item_cursor.fetchall()

    return {
        "items": [
            {
                "id": row["id"],
                "api_key_id": row["api_key_id"],
                "user_id": row["user_id"],
                "model_name": row["model_name"],
                "tier": row["tier"],
                "prompt_tokens": row["prompt_tokens"],
                "completion_tokens": row["completion_tokens"],
                "total_tokens": row["total_tokens"],
                "latency_ms": row["latency_ms"],
                "route_path": row["route_path"],
                "cost_estimate": row["cost_estimate"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ],
        "summary": {
            "total_tokens": int(summary_row["total_tokens"] or 0),
            "total_requests": int(summary_row["total_requests"] or 0),
            "total_cost_estimate": float(summary_row["total_cost_estimate"] or 0),
            "avg_latency_ms": float(summary_row["avg_latency_ms"] or 0),
        },
        "limit": limit,
        "offset": offset,
    }


_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics
