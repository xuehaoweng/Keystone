#!/usr/bin/env python3
"""Create an admin JWT token for LLM Gateway management operations."""

from __future__ import annotations

import argparse
import os
import time

from dotenv import load_dotenv
from jose import jwt
import yaml


def load_config_secret(default_secret: str) -> str:
    env_secret = os.getenv("GATEWAY_JWT_SECRET", "").strip()
    if env_secret:
        return env_secret

    config_path = os.getenv("CONFIG_DIR", "config")
    yaml_path = os.path.join(config_path, "gateway.yaml")
    try:
        with open(yaml_path, "r", encoding="utf-8") as fp:
            cfg = yaml.safe_load(fp) or {}
    except FileNotFoundError:
        return default_secret
    except Exception:
        return default_secret

    auth_cfg = cfg.get("auth", {}) if isinstance(cfg, dict) else {}
    return str(auth_cfg.get("jwt_secret") or default_secret)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate admin JWT token for LLM Gateway.")
    parser.add_argument(
        "--user-id",
        default="admin-user",
        help="JWT sub claim (default: admin-user)",
    )
    parser.add_argument(
        "--role",
        default="admin",
        choices=["admin", "user"],
        help="JWT role claim (default: admin)",
    )
    parser.add_argument(
        "--expire-hours",
        type=float,
        default=24 * 365,
        help="Token TTL in hours (default: 8760)",
    )
    parser.add_argument(
        "--secret",
        default="",
        help="Optional custom JWT secret; defaults to GATEWAY_JWT_SECRET/env config.",
    )
    parser.add_argument(
        "--algorithm",
        default="HS256",
        help="JWT algorithm (default: HS256)",
    )
    args = parser.parse_args()

    load_dotenv()

    secret = args.secret or load_config_secret("change-me-in-production")
    if not secret:
        raise RuntimeError("GATEWAY_JWT_SECRET is empty, cannot generate JWT.")
    now = int(time.time())
    expire = now + int(args.expire_hours * 3600)

    payload = {
        "sub": args.user_id,
        "role": args.role,
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(payload, secret, algorithm=args.algorithm)

    print(token)
    print(f"\nPayload: {payload}")
    print(f"Expire: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expire))}")


if __name__ == "__main__":
    main()
