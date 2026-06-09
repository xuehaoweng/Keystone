import asyncio
import time
from dataclasses import dataclass

from app.config import get_models_config
from app.db.redis import get_redis

CIRCUIT_PREFIX = "gateway:circuit:"


@dataclass
class ModelInstance:
    name: str
    provider: str
    tier: str
    weight: int = 1
    max_concurrent: int = 100
    rate_limit: int = 1000
    current_connections: int = 0
    error_count: int = 0
    last_error_time: float = 0
    healthy: bool = True
    circuit_open_until: float = 0
    circuit_state: str = "closed"


class LoadBalancer:
    def __init__(self):
        self._instances: dict[str, ModelInstance] = {}
        self._lock = asyncio.Lock()
        self._reload()

    def _reload(self):
        models = get_models_config().get("models", [])
        for m in models:
            if m["name"] in self._instances:
                inst = self._instances[m["name"]]
                inst.weight = m.get("weight", 1)
                inst.max_concurrent = m.get("max_concurrent", 100)
                inst.rate_limit = m.get("rate_limit", 1000)
            else:
                self._instances[m["name"]] = ModelInstance(
                    name=m["name"],
                    provider=m["provider"],
                    tier=m["tier"],
                    weight=m.get("weight", 1),
                    max_concurrent=m.get("max_concurrent", 100),
                    rate_limit=m.get("rate_limit", 1000),
                )

    async def _read_state(self, model_name: str) -> dict:
        """Read circuit state from Redis; fall back to in-memory on failure."""
        try:
            redis = await get_redis()
            key = f"{CIRCUIT_PREFIX}{model_name}"
            data = await redis.hgetall(key)
            if data:
                return {
                    "error_count": int(data.get("error_count", 0)),
                    "last_error_time": float(data.get("last_error_time", 0)),
                    "healthy": data.get("healthy", "1") == "1",
                    "circuit_open_until": float(data.get("circuit_open_until", 0)),
                    "circuit_state": data.get("circuit_state", "closed"),
                }
        except Exception:
            pass
        inst = self._instances.get(model_name)
        if inst:
            return {
                "error_count": inst.error_count,
                "last_error_time": inst.last_error_time,
                "healthy": inst.healthy,
                "circuit_open_until": inst.circuit_open_until,
                "circuit_state": inst.circuit_state,
            }
        return {}

    async def _write_state(self, model_name: str, **fields) -> None:
        """Write circuit state to Redis; silently fail on connection errors."""
        try:
            redis = await get_redis()
            key = f"{CIRCUIT_PREFIX}{model_name}"
            await redis.hset(key, mapping={k: str(v) for k, v in fields.items()})
        except Exception:
            pass
        # Always keep in-memory cache warm
        inst = self._instances.get(model_name)
        if inst:
            for k, v in fields.items():
                if hasattr(inst, k):
                    if k == "healthy":
                        v = v == "1" or v is True
                    setattr(inst, k, v)

    async def get_by_tier(self, tier: str) -> list[ModelInstance]:
        now = time.time()
        candidates = []
        for inst in self._instances.values():
            if inst.tier != tier:
                continue
            state = await self._read_state(inst.name)
            # Auto-recover from open to half-open when timeout expires
            if not state.get("healthy", True) and state.get("circuit_open_until", 0) <= now:
                await self._write_state(
                    inst.name,
                    healthy="1",
                    error_count=0,
                    circuit_open_until=0,
                    circuit_state="half-open",
                )
                state = {
                    "healthy": True,
                    "error_count": 0,
                    "circuit_open_until": 0,
                    "circuit_state": "half-open",
                }
            # Sync in-memory cache
            inst.error_count = state.get("error_count", inst.error_count)
            inst.healthy = state.get("healthy", inst.healthy)
            inst.circuit_open_until = state.get("circuit_open_until", inst.circuit_open_until)
            inst.circuit_state = state.get("circuit_state", inst.circuit_state)
            if state.get("healthy", True):
                candidates.append(inst)
        return candidates

    async def select(
        self,
        tier: str,
        exclude_names: set[str] | None = None,
    ) -> ModelInstance | None:
        async with self._lock:
            candidates = await self.get_by_tier(tier)
            if exclude_names:
                candidates = [i for i in candidates if i.name not in exclude_names]
            if not candidates:
                return None
            available = [i for i in candidates if i.current_connections < i.max_concurrent]
            if not available:
                available = candidates
            available.sort(key=lambda i: (i.current_connections / max(i.weight, 1), i.current_connections))
            selected = available[0]
            selected.current_connections += 1
            return selected

    def release(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.current_connections = max(0, inst.current_connections - 1)

    async def report_error(self, model_name: str):
        state = await self._read_state(model_name)
        error_count = state.get("error_count", 0) + 1
        last_error_time = time.time()
        fields = {
            "error_count": error_count,
            "last_error_time": last_error_time,
        }
        if error_count >= 5:
            fields.update({
                "healthy": "0",
                "circuit_open_until": last_error_time + 30,
                "circuit_state": "open",
            })
        await self._write_state(model_name, **fields)

    async def report_success(self, model_name: str):
        await self._write_state(
            model_name,
            error_count=0,
            healthy="1",
            circuit_open_until=0,
            circuit_state="closed",
        )

    async def get_all(self) -> dict:
        result = {}
        for name, inst in self._instances.items():
            state = await self._read_state(name)
            result[name] = {
                "provider": inst.provider,
                "tier": inst.tier,
                "healthy": state.get("healthy", inst.healthy),
                "connections": inst.current_connections,
                "errors": state.get("error_count", inst.error_count),
                "circuit_open_until": state.get("circuit_open_until", inst.circuit_open_until),
                "circuit_state": state.get("circuit_state", inst.circuit_state),
            }
        return result


_lb: LoadBalancer | None = None


def get_load_balancer() -> LoadBalancer:
    global _lb
    if _lb is None:
        _lb = LoadBalancer()
    return _lb
