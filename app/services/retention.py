import asyncio
import os
from datetime import datetime, timedelta, timezone

from app.db.sqlite import get_db, init_db

_RETENTION_DAYS = int(os.getenv("GATEWAY_RETENTION_DAYS", "30"))
_CLEANUP_INTERVAL = 86400.0  # 24 hours


async def _cleanup_table(db, table: str, column: str, cutoff: str) -> int:
    cursor = await db.execute(
        f"DELETE FROM {table} WHERE {column} < ?",
        (cutoff,),
    )
    await db.commit()
    return cursor.rowcount


async def run_retention_cleanup() -> dict:
    """Delete rows older than RETENTION_DAYS from usage_logs, request_traces and audit_logs."""
    await init_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    async with get_db() as db:
        deleted = {
            "usage_logs": await _cleanup_table(db, "usage_logs", "timestamp", cutoff),
            "request_traces": await _cleanup_table(db, "request_traces", "created_at", cutoff),
            "audit_logs": await _cleanup_table(db, "audit_logs", "created_at", cutoff),
        }
    return deleted


async def retention_loop():
    """Background task that runs retention cleanup every 24 hours."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL)
        try:
            await run_retention_cleanup()
        except Exception:
            # Log and continue; we don't want the background task to die
            pass


_cleanup_task: asyncio.Task | None = None


def start_retention_cleanup():
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(retention_loop())


async def stop_retention_cleanup():
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
