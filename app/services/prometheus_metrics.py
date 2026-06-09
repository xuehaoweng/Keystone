"""Lightweight Prometheus-compatible metrics without extra dependencies."""

import time
from collections import defaultdict

# Counters
_request_count: dict[str, int] = defaultdict(int)
_request_errors: dict[str, int] = defaultdict(int)

# Latency histogram buckets (ms): 50, 100, 200, 500, 1000, 2000, 5000, 10000, +Inf
_latency_buckets = [50, 100, 200, 500, 1000, 2000, 5000, 10000]
_latency_counts: dict[str, list[int]] = defaultdict(lambda: [0] * (len(_latency_buckets) + 1))
_latency_sums: dict[str, float] = defaultdict(float)

# Gauge: circuit breaker state per model
_circuit_state: dict[str, int] = {}


def record_request(model_name: str, latency_ms: float, is_error: bool = False):
    _request_count[model_name] += 1
    _latency_sums[model_name] += latency_ms
    if is_error:
        _request_errors[model_name] += 1
    # Histogram bucketing
    counts = _latency_counts[model_name]
    placed = False
    for i, bucket in enumerate(_latency_buckets):
        if latency_ms <= bucket:
            counts[i] += 1
            placed = True
            break
    if not placed:
        counts[-1] += 1


def set_circuit_state(model_name: str, state: str):
    mapping = {"closed": 0, "half-open": 1, "open": 2}
    _circuit_state[model_name] = mapping.get(state, 0)


def generate_metrics() -> str:
    lines = []
    lines.append("# HELP gateway_requests_total Total requests by model")
    lines.append("# TYPE gateway_requests_total counter")
    for model, count in _request_count.items():
        lines.append(f'gateway_requests_total{{model="{model}"}} {count}')

    lines.append("# HELP gateway_request_errors_total Total errors by model")
    lines.append("# TYPE gateway_request_errors_total counter")
    for model, count in _request_errors.items():
        lines.append(f'gateway_request_errors_total{{model="{model}"}} {count}')

    lines.append("# HELP gateway_request_latency_ms_sum Sum of request latencies")
    lines.append("# TYPE gateway_request_latency_ms histogram")
    for model, counts in _latency_counts.items():
        total = _request_count.get(model, 0)
        for i, bucket in enumerate(_latency_buckets):
            lines.append(
                f'gateway_request_latency_ms_bucket{{model="{model}",le="{bucket}"}} {counts[i]}'
            )
        lines.append(
            f'gateway_request_latency_ms_bucket{{model="{model}",le="+Inf"}} {counts[-1]}'
        )
        lines.append(f'gateway_request_latency_ms_sum{{model="{model}"}} {_latency_sums[model]}')
        lines.append(f'gateway_request_latency_ms_count{{model="{model}"}} {total}')

    lines.append("# HELP gateway_circuit_state Circuit breaker state (0=closed,1=half-open,2=open)")
    lines.append("# TYPE gateway_circuit_state gauge")
    for model, state in _circuit_state.items():
        lines.append(f'gateway_circuit_state{{model="{model}"}} {state}')

    return "\n".join(lines) + "\n"
