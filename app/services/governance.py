import json
import math
from dataclasses import dataclass, field
from time import time
from typing import Any

from app.config import get_gateway_config, get_models_config
from app.db.sqlite import get_db, init_db


@dataclass
class RequestTrace:
    request_id: str
    user_id: str | None
    api_key_id: str | None
    provider: str | None
    model_name: str | None
    tier: str | None
    status: str
    route_source: str | None = None
    requested_tier: str | None = None
    resolved_tier: str | None = None
    attempted_models: list[str] = field(default_factory=list)
    fallback_used: bool = False
    cache_hit: bool = False
    latency_ms: float = 0
    error_type: str | None = None
    error_detail: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


async def record_request_trace(trace: RequestTrace) -> None:
    await init_db()
    async with get_db() as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO request_traces (
                request_id, api_key_id, user_id, provider, model_name, tier,
                status, route_source, requested_tier, resolved_tier,
                attempted_models, fallback_used, cache_hit, latency_ms,
                error_type, error_detail, prompt_tokens, completion_tokens, total_tokens
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace.request_id,
                trace.api_key_id,
                trace.user_id,
                trace.provider,
                trace.model_name,
                trace.tier,
                trace.status,
                trace.route_source,
                trace.requested_tier,
                trace.resolved_tier,
                json.dumps(trace.attempted_models, ensure_ascii=False),
                1 if trace.fallback_used else 0,
                1 if trace.cache_hit else 0,
                trace.latency_ms,
                trace.error_type,
                trace.error_detail,
                trace.prompt_tokens,
                trace.completion_tokens,
                trace.total_tokens,
            ),
        )
        await db.commit()


async def query_request_traces(limit: int = 50, offset: int = 0) -> dict:
    await init_db()
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM request_traces
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
    return {
        "items": [_trace_row_to_dict(row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


def _trace_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "api_key_id": row["api_key_id"],
        "user_id": row["user_id"],
        "provider": row["provider"],
        "model_name": row["model_name"],
        "tier": row["tier"],
        "status": row["status"],
        "route_source": row["route_source"],
        "requested_tier": row["requested_tier"],
        "resolved_tier": row["resolved_tier"],
        "attempted_models": json.loads(row["attempted_models"] or "[]"),
        "fallback_used": bool(row["fallback_used"]),
        "cache_hit": bool(row["cache_hit"]),
        "latency_ms": row["latency_ms"],
        "error_type": row["error_type"],
        "error_detail": row["error_detail"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "created_at": row["created_at"],
    }


async def provider_sla() -> dict:
    await init_db()
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT provider, status, latency_ms, fallback_used, cache_hit, total_tokens
            FROM request_traces
            WHERE provider IS NOT NULL
            """
        )
        rows = await cursor.fetchall()

    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["provider"], []).append(row)

    providers = []
    for provider, provider_rows in sorted(grouped.items()):
        total = len(provider_rows)
        successes = sum(1 for row in provider_rows if row["status"] == "success")
        errors = total - successes
        latencies = sorted(float(row["latency_ms"] or 0) for row in provider_rows)
        providers.append({
            "provider": provider,
            "total_requests": total,
            "success_count": successes,
            "error_count": errors,
            "success_rate": round(successes / total, 4) if total else 0,
            "avg_latency_ms": round(sum(latencies) / total, 2) if total else 0,
            "p50_latency_ms": percentile(latencies, 0.5),
            "p95_latency_ms": percentile(latencies, 0.95),
            "fallback_count": sum(1 for row in provider_rows if row["fallback_used"]),
            "cache_hit_count": sum(1 for row in provider_rows if row["cache_hit"]),
            "total_tokens": sum(int(row["total_tokens"] or 0) for row in provider_rows),
        })
    return {"providers": providers}


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0
    index = max(0, math.ceil(len(values) * p) - 1)
    return values[index]


async def record_audit(
    actor_user_id: str | None,
    api_key_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    await init_db()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO audit_logs
            (actor_user_id, api_key_id, action, target_type, target_id, detail_json, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_user_id,
                api_key_id,
                action,
                target_type,
                target_id,
                json.dumps(detail or {}, ensure_ascii=False),
                ip_address,
            ),
        )
        await db.commit()


async def query_audit_logs(limit: int = 50, offset: int = 0) -> dict:
    await init_db()
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT * FROM audit_logs
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "actor_user_id": row["actor_user_id"],
                "api_key_id": row["api_key_id"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "detail": json.loads(row["detail_json"] or "{}"),
                "ip_address": row["ip_address"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
        "limit": limit,
        "offset": offset,
    }


def current_policy_bundle() -> dict:
    models_config = get_models_config()
    return {
        "generated_at": int(time()),
        "gateway": {
            "rules": get_gateway_config().get("rules", []),
            "timeouts": get_gateway_config().get("timeouts", {}),
            "rate_limit": get_gateway_config().get("rate_limit", {}),
        },
        "providers": {
            name: {
                "base_url": provider.get("base_url"),
                "models": [
                    {
                        "name": model.get("name"),
                        "tier": model.get("tier"),
                        "weight": model.get("weight", 1),
                        "max_concurrent": model.get("max_concurrent"),
                        "rate_limit": model.get("rate_limit"),
                    }
                    for model in models_config.get("models", [])
                    if model.get("provider") == name
                ],
            }
            for name, provider in models_config.get("providers", {}).items()
        },
    }


async def create_policy_draft(name: str, content: dict, created_by: str | None) -> dict:
    await init_db()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO policy_drafts (name, content_json, status, created_by)
            VALUES (?, ?, 'draft', ?)
            RETURNING id, name, content_json, status, created_by, created_at, updated_at
            """,
            (name, json.dumps(content, ensure_ascii=False), created_by),
        )
        row = await cursor.fetchone()
        await db.commit()
    return _policy_row_to_dict(row)


async def list_policy_drafts() -> list[dict]:
    await init_db()
    async with get_db() as db:
        cursor = await db.execute(
            """
            SELECT id, name, content_json, status, created_by, created_at, updated_at
            FROM policy_drafts
            ORDER BY id DESC
            LIMIT 20
            """
        )
        rows = await cursor.fetchall()
    return [_policy_row_to_dict(row) for row in rows]


async def apply_policy_draft(draft_id: int) -> dict | None:
    await init_db()
    async with get_db() as db:
        await db.execute(
            """
            UPDATE policy_drafts
            SET status = 'applied', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (draft_id,),
        )
        cursor = await db.execute(
            """
            SELECT id, name, content_json, status, created_by, created_at, updated_at
            FROM policy_drafts
            WHERE id = ?
            """,
            (draft_id,),
        )
        row = await cursor.fetchone()
        await db.commit()
    return _policy_row_to_dict(row) if row else None


def _policy_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "content": json.loads(row["content_json"]),
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
