import aiosqlite
from contextlib import asynccontextmanager
import os

_db_path: str = os.getenv("GATEWAY_DB_PATH", "gateway.db")


def set_db_path(path: str):
    global _db_path
    _db_path = path


@asynccontextmanager
async def get_db():
    db = await aiosqlite.connect(_db_path)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with aiosqlite.connect(_db_path) as db:
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
        try:
            await db.execute("ALTER TABLE usage_logs ADD COLUMN cost_estimate REAL DEFAULT 0")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE api_keys ADD COLUMN key_encrypted TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE api_keys ADD COLUMN external_user_id TEXT")
        except aiosqlite.OperationalError:
            pass
        await db.commit()
