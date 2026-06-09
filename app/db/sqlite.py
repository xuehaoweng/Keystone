import asyncio
import os
from contextlib import asynccontextmanager

import aiosqlite

_db_path: str = os.getenv("GATEWAY_DB_PATH", "gateway.db")
_db_conn: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()


def set_db_path(path: str):
    global _db_path
    _db_path = path


async def _ensure_connection() -> aiosqlite.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = await aiosqlite.connect(_db_path)
        _db_conn.row_factory = aiosqlite.Row
        # WAL mode allows readers to proceed while a writer is active
        await _db_conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL sync is safe with WAL and much faster than FULL
        await _db_conn.execute("PRAGMA synchronous=NORMAL")
        # 64 MB page cache
        await _db_conn.execute("PRAGMA cache_size=-64000")
        # Auto-checkpoint every 1000 pages (roughly 4 MB) to keep WAL small
        await _db_conn.execute("PRAGMA wal_autocheckpoint=1000")
        await _db_conn.commit()
    return _db_conn


@asynccontextmanager
async def get_db():
    db = await _ensure_connection()
    yield db


async def close_db():
    global _db_conn
    if _db_conn is not None:
        await _db_conn.close()
        _db_conn = None


async def init_db():
    db = await _ensure_connection()
    async with _write_lock:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT UNIQUE NOT NULL,
                key_encrypted TEXT,
                user_id TEXT NOT NULL,
                external_user_id TEXT,
                name TEXT,
                quota_monthly INTEGER DEFAULT 0,
                rate_limit_rps INTEGER DEFAULT 10,
                allowed_tiers TEXT DEFAULT 'cheap,expensive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                api_key_id TEXT,
                user_id TEXT,
                model_name TEXT,
                tier TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms REAL,
                route_path TEXT,
                cost_estimate REAL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS request_traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT UNIQUE NOT NULL,
                api_key_id TEXT,
                user_id TEXT,
                provider TEXT,
                model_name TEXT,
                tier TEXT,
                status TEXT NOT NULL,
                route_source TEXT,
                requested_tier TEXT,
                resolved_tier TEXT,
                attempted_models TEXT DEFAULT '[]',
                fallback_used INTEGER DEFAULT 0,
                cache_hit INTEGER DEFAULT 0,
                latency_ms REAL DEFAULT 0,
                error_type TEXT,
                error_detail TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id TEXT,
                api_key_id TEXT,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                detail_json TEXT DEFAULT '{}',
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS policy_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                content_json TEXT NOT NULL,
                status TEXT DEFAULT 'draft',
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Migration: add columns that may not exist in older dbs
        for col_def in [
            ("ALTER TABLE usage_logs ADD COLUMN cost_estimate REAL DEFAULT 0",),
            ("ALTER TABLE api_keys ADD COLUMN key_encrypted TEXT",),
            ("ALTER TABLE api_keys ADD COLUMN external_user_id TEXT",),
        ]:
            try:
                await db.execute(col_def[0])
            except aiosqlite.OperationalError:
                pass
        await db.commit()
