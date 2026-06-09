# API Reference

所有接口除 `/health` 和 `/admin` 页面资源外，均需要：

```http
Authorization: Bearer <api_key_or_jwt>
```

## Runs

### `POST /api/runs`

发送一次对话请求。

关键字段：

| 字段 | 说明 |
|------|------|
| `messages` | 对话消息列表 |
| `stream` | 是否启用 SSE 流式返回 |
| `model` | 直接指定模型，最高优先级 |
| `preferred_model` | 优先使用模型，不可用时继续路由 |
| `model_tier` | `auto`、`cheap`、`expensive` |
| `temperature` | 生成温度 |
| `max_tokens` | 最大输出 token |
| `tools` | 工具列表，用于规则匹配 |

非流式响应：

```json
{
  "id": "run-deepseek-chat",
  "model": "deepseek-chat",
  "tier": "cheap",
  "content": "response",
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  },
  "finish_reason": "stop"
}
```

## Auth

### `POST /api/auth/keys`

创建 API Key。

Query 参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `name` | `default` | Key 名称 |
| `quota` | `0` | 月度 token 配额，0 表示无限制 |
| `rate_limit` | `10` | QPS 限制 |
| `allowed_tiers` | `cheap,expensive` | 允许使用的模型层级 |

### `GET /api/auth/keys`

列出当前用户的 API Keys。

### `GET /api/auth/keys/{key_id}/usage`

从数据库聚合单个 key 的用量。

### `DELETE /api/auth/keys/{key_id}`

软删除 API Key。

## Admin

### `GET /api/models`

返回模型状态，包括 tier、健康状态、连接数、错误数和熔断冷却时间。

### `GET /api/models/{model_name}/health`

返回单个模型健康状态。

### `GET /api/metrics`

返回数据库聚合的全局请求数、token、成本和平均延迟。

### `GET /api/traces`

查询最近调用 Trace。用于追踪 request_id、provider、model、fallback、cache 和错误。

### `GET /api/providers/sla`

按 provider 聚合 SLA 指标，包括成功率、错误数、P50/P95 延迟、fallback 和缓存命中。

### `GET /api/audit`

查询管理审计日志。

### `GET /api/policies`

返回当前策略快照和最近策略草案。

### `POST /api/policies/drafts`

保存策略草案并写入审计日志。草案不会直接覆盖 YAML。

### `POST /api/policies/drafts/{draft_id}/apply`

把草案状态标记为 `applied` 并写入审计日志。开源版默认不做线上 YAML 热更新。

### `GET /api/config`

返回脱敏后的网关配置和模型配置。Provider `api_keys` 始终返回空数组。

## Admin UI

### `GET /admin`

返回内置管理后台页面。页面通过上述 API 获取数据。

## Health

### `GET /health`

无需鉴权。

```json
{"status": "ok"}
```
