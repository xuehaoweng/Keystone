import asyncio
import time
from dataclasses import dataclass

from app.config import get_models_config


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

    def get_by_tier(self, tier: str) -> list[ModelInstance]:
        now = time.time()
        for inst in self._instances.values():
            if not inst.healthy and inst.circuit_open_until and inst.circuit_open_until <= now:
                inst.healthy = True
                inst.error_count = 0
                inst.circuit_open_until = 0
        return [i for i in self._instances.values() if i.tier == tier and i.healthy]

    async def select(
        self,
        tier: str,
        exclude_names: set[str] | None = None,
    ) -> ModelInstance | None:
        async with self._lock:
            candidates = self.get_by_tier(tier)
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

    def report_error(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.error_count += 1
            inst.last_error_time = time.time()
            if inst.error_count >= 5:
                inst.healthy = False
                inst.circuit_open_until = inst.last_error_time + 30

    def report_success(self, model_name: str):
        if model_name in self._instances:
            inst = self._instances[model_name]
            inst.error_count = 0
            inst.healthy = True
            inst.circuit_open_until = 0

    def get_all(self) -> dict:
        return {
            name: {
                "provider": i.provider,
                "tier": i.tier,
                "healthy": i.healthy,
                "connections": i.current_connections,
                "errors": i.error_count,
                "circuit_open_until": i.circuit_open_until,
            }
            for name, i in self._instances.items()
        }


_lb: LoadBalancer | None = None


def get_load_balancer() -> LoadBalancer:
    global _lb
    if _lb is None:
        _lb = LoadBalancer()
    return _lb
