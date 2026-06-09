# 运维指南

## 配额和限流

API Key 有两个主要限制：

- `rate_limit_rps`：每秒请求数。
- `quota_monthly`：月度 token 配额，0 表示无限制。

请求进入 `/api/runs` 后，会先鉴权和限流，再检查月度 quota。超过 quota 返回 `429`。

## Tier 权限

`allowed_tiers` 用于控制 key 能使用的模型层级。

典型策略：

- 实习生或测试环境：`cheap`
- 常规业务：`cheap,expensive`
- 财务敏感业务：结合 quota 和审计单独管控

## 熔断

模型连续失败 5 次后会被标记为不健康，并进入 30 秒冷却期。

冷却期间该模型不会被负载均衡选中。冷却结束后，模型会自动恢复为候选状态。下一次成功调用会清空错误计数。

## 降级

非流式请求失败时：

1. 先尝试同 tier 的其他健康模型。
2. 如果没有可用模型，再尝试另一个 tier。
3. 如果仍失败，返回 `502`。

流式请求已经开始输出后无法无感切换模型，因此不做流中重试。

## 结果缓存

结果缓存适合确定性请求。当前默认只缓存：

- 非流式请求。
- `temperature == 0`。

缓存存储在 Redis。Redis 不可用时，请求继续走模型调用，不影响主流程。

不建议缓存：

- 个性化请求。
- 实时数据请求。
- 高隐私请求。
- 高温度创造性生成。

## 成本估算

模型配置可支持以下字段：

```yaml
input_cost_per_1k: 0.10
output_cost_per_1k: 0.20
```

或统一价格：

```yaml
cost_per_1k: 0.15
```

未配置价格时，成本估算为 0。

## 故障排查

常见状态码：

| 状态码 | 原因 |
|--------|------|
| `401` | 鉴权失败 |
| `403` | API Key 不允许使用目标 tier |
| `429` | QPS 或月度 quota 超限 |
| `502` | 下游模型调用失败 |
| `503` | 没有可用模型 |

排查顺序：

1. 查看 `/health`。
2. 查看 `/api/models`。
3. 查看 `/api/metrics`。
4. 查看指定 key 的 `/api/auth/keys/{key_id}/usage`。
5. 检查 Redis 和 provider API Key。

## 调用 Trace

每个非流式调用会写入 `request_traces`：

- `request_id`：来自 Nginx `X-Request-ID`，没有则由 Gateway 生成。
- `provider` / `model_name` / `tier`：实际执行模型。
- `route_source`：自动路由、显式 tier、指定模型或缓存。
- `attempted_models`：fallback 路径。
- `cache_hit` / `fallback_used`：缓存和降级行为。
- `latency_ms` / `error_type` / `error_detail`：排障字段。

## 管理审计

API Key 创建/删除、策略草案创建/应用会写入 `audit_logs`。审计记录包含操作者、Key ID、目标对象、IP 和详情 JSON。

## Provider SLA

`/api/providers/sla` 基于 `request_traces` 聚合 Provider 级别指标，包括成功率、P50/P95 延迟、错误数、fallback 次数和缓存命中次数。

## 策略草案

`/api/policies` 返回当前策略快照和最近草案。草案用于开源版的可视化治理闭环：可以保存、审计和标记应用状态，但不会直接覆盖线上 YAML。生产环境应结合审批和重启/热加载流程。
