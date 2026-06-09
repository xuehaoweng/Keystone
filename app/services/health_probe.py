import asyncio
import time

import httpx

from app.config import get_models_config
from app.services.load_balancer import get_load_balancer

_PROBE_INTERVAL = 30.0
_PROBE_TIMEOUT = 10.0


async def _probe_model(model_name: str) -> bool:
    """Send a minimal health-check request to a provider."""
    models = get_models_config().get("models", [])
    model_cfg = next((m for m in models if m["name"] == model_name), None)
    if not model_cfg:
        return False
    provider = model_cfg.get("provider", "")
    provider_cfg = get_models_config().get("providers", {}).get(provider, {})
    base_url = provider_cfg.get("base_url", "")
    if not base_url:
        return False

    env_key = f"{provider.upper()}_API_KEY"
    api_key = (
        provider_cfg.get("api_keys", [None])[0]
        or __import__("os").getenv(env_key, "").split(",")[0].strip()
    )
    if not api_key:
        return False

    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=body, timeout=_PROBE_TIMEOUT)
            return resp.status_code < 500
    except Exception:
        return False


async def health_probe_loop():
    """Background task that probes unhealthy or half-open instances."""
    lb = get_load_balancer()
    while True:
        await asyncio.sleep(_PROBE_INTERVAL)
        instances = list(lb._instances.values())
        for inst in instances:
            # Probe anything that is not known-healthy (closed)
            if inst.circuit_state == "closed" and inst.healthy:
                continue
            ok = await _probe_model(inst.name)
            if ok:
                await lb.report_success(inst.name)
            else:
                await lb.report_error(inst.name)


_probe_task: asyncio.Task | None = None


def start_health_probe():
    global _probe_task
    if _probe_task is None or _probe_task.done():
        _probe_task = asyncio.create_task(health_probe_loop())


async def stop_health_probe():
    global _probe_task
    if _probe_task and not _probe_task.done():
        _probe_task.cancel()
        try:
            await _probe_task
        except asyncio.CancelledError:
            pass
