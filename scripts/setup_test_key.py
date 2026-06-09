#!/usr/bin/env python3
"""一键创建测试 API Key，无需 JWT 认证"""
import asyncio
import hashlib
from dotenv import load_dotenv

load_dotenv()

async def main():
    from app.db.sqlite import init_db, get_db
    from app.middleware.auth import encrypt_api_key

    await init_db()
    key_value = "lgw_test_key_2026"
    key_hash = hashlib.sha256(key_value.encode()).hexdigest()
    key_id = key_hash[:16]
    key_encrypted = encrypt_api_key(key_value)

    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO api_keys (id, key_hash, key_encrypted, user_id, name, quota_monthly, rate_limit_rps, active) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (key_id, key_hash, key_encrypted, "test-user", "auto-test", 100000, 1000),
        )
        await db.commit()

    print(f"API Key 创建成功: {key_value}")
    print(f"Key ID: {key_id}")

if __name__ == "__main__":
    asyncio.run(main())
