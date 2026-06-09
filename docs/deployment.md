# Deployment

## Docker Compose

The recommended open-source quick deployment is Docker Compose:

```bash
cp .env.example .env
# Fill provider keys in .env
docker compose up -d --build
```

It starts:

- `ingress`: Nginx ingress on `${GATEWAY_PORT:-8000}`.
- `gateway`: FastAPI + bundled React admin UI, private to the Compose network.
- `redis`: cache and rate-limit state, private to the Compose network.
- `gateway_db`: persistent SQLite database volume at `/app/data/gateway.db`.
- `redis_data`: persistent Redis AOF data.

```text
browser / client
  ↓
nginx ingress:${GATEWAY_PORT:-8000}
  ↓
gateway:8000 private network
  ├─ /llm_gateway_admin
  ├─ /api/*
  └─ /health /ready
  ↓
redis:6379 private network
```

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Create a demo Gateway API Key inside the Compose database:

```bash
docker compose exec gateway python scripts/setup_test_key.py
```

If port `8000` is already used:

```bash
GATEWAY_PORT=18080 docker compose up -d --build
```

## MVP Single-Port Deployment

The default open-source deployment uses one FastAPI process:

```text
FastAPI :8000
  ├─ /llm_gateway_admin
  ├─ /api/*
  └─ /health
```

Start:

```bash
uv sync
npm install --prefix frontend
npm run build --prefix frontend
REDIS_URL=redis://127.0.0.1:6379/0 uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Production Reverse Proxy

The default Compose stack already puts Nginx in front of FastAPI:

```text
Nginx ingress
  ↓
FastAPI Gateway
  ↓
Redis + PostgreSQL
  ↓
Model Providers
```

Nginx currently handles the unified HTTP entrypoint, reverse proxy headers, request size limits, long model-response timeouts, streaming-friendly buffering settings, and coarse IP-based rate limiting. For enterprise plugin ecosystems, replace the `ingress` service with Kong, APISIX, or Envoy while keeping the internal Gateway contract unchanged.

Nginx writes JSON access logs and forwards `X-Request-ID` to the Gateway. The Gateway stores request-level traces in SQLite so operators can correlate ingress logs with model routing decisions.
