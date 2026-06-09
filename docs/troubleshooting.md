# Troubleshooting

## `Missing authorization header`

The request did not include a Gateway API Key.

In the admin UI, fill the right-top token field with a Gateway API Key, not a provider key.

## DeepSeek `402 Payment Required`

The backend reached DeepSeek, but DeepSeek rejected the request because billing or quota is unavailable.

Check the account behind `DEEPSEEK_API_KEY`.

## Provider `403 Forbidden`

The provider API key does not have permission to call the target model or endpoint.

Check provider-side model permissions and endpoint access.

## Provider `429 Too Many Requests`

The provider is rate limiting the request or the provider quota is exhausted.

Try later, reduce concurrency, or use another configured model in the same tier.

## `/` Returns Redirect

This is expected. `/` redirects to `/llm_gateway_admin`.

## Static Assets 404

Rebuild the frontend:

```bash
npm run build --prefix frontend
```

Restart FastAPI after rebuilding.

## Docker Compose Port Conflict

If `docker compose up` reports that port `8000` is already allocated, either stop the process using that port or use another Nginx ingress host port:

```bash
GATEWAY_PORT=18080 docker compose up -d --build
```

Then open:

```text
http://localhost:18080/
```

## Redis Shows Degraded

In Docker Compose mode, `gateway` connects to `redis://redis:6379/0` inside the private Compose network. Check:

```bash
docker compose ps
docker compose logs redis
curl http://localhost:8000/ready
```

In local development mode, start Redis separately and set:

```bash
REDIS_URL=redis://127.0.0.1:6379/0
```

## Nginx Ingress

Docker Compose exposes Nginx, not FastAPI, to the host:

```text
host:${GATEWAY_PORT:-8000} -> ingress:80 -> gateway:8000
```

Check the ingress:

```bash
docker compose ps
docker compose logs ingress
curl -i http://localhost:8000/health
```
