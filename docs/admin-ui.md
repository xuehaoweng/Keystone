# 管理后台说明

## 目标用户

管理后台面向平台管理员、运维和业务 owner，用于查看模型状态、管理 API Key、观察用量成本，并手动发起测试请求。

## 页面结构

### 运行概览

展示：

- 总请求数。
- 总 token。
- 总成本估算。
- 平均延迟。
- 数据库、Redis、访问凭证状态。
- 控制面入口和数据面入口。

概览页会自动加载 `/ready`。未填写 Gateway API Key 时，只展示依赖健康状态；填写后再展示用量指标。

### 访问密钥

展示：

- Key 名称。
- 月度 quota。
- QPS。
- allowed tiers。
- 创建时间。

支持：

- 创建 key。
- 删除 key。
- 查询 key 用量。

空状态会提示如何创建第一个 Key。

### 模型与路由

展示：

- 模型名称。
- tier。
- 健康状态。
- 当前连接数。
- 错误数。
- 熔断冷却时间。

### 用量账单

展示最近用量记录：

- 时间。
- Gateway API Key ID。
- 用户。
- 模型。
- tier。
- token。
- 成本估算。
- 延迟。

空状态会提示通过测试控制台或业务 API 产生第一条记录。

### 调用追踪

展示 `request_traces` 中的最新调用记录。每条记录包含 request_id、Gateway API Key ID、provider、model、tier、路由来源、fallback、cache hit、token、延迟和错误类型。

该页面用于把 Nginx 接入层、FastAPI 路由层和供应商执行层串联起来排查。

### SLA 看板

按 provider 聚合成功率、错误数、平均延迟、P50/P95 延迟、fallback 次数和缓存命中次数。

### 路由规则

只读展示当前 `config/gateway.yaml` 中的规则配置。配置编辑暂不在首版开放。

### 策略中心

展示当前策略快照，并支持生成数据库中的策略草案。草案会写入审计日志，但不会直接覆盖 YAML 或热更新生产配置。

### 审计日志

展示 `audit_logs` 中的管理操作，包括 API Key 创建/删除、策略草案创建/应用等。

### 供应商配置

结构化展示：

- Provider 名称。
- Base URL。
- 服务端 Key 数量。
- 是否通过环境变量配置 Key。
- 关联模型。
- 接入状态。

Provider API Key 不在前端展示，也不允许粘贴到管理后台。

### 测试控制台

支持：

- 输入 Authorization token。
- 输入用户消息。
- 选择 `model_tier`。
- 可选指定 `model`。
- 设置 temperature 和 max_tokens。
- 发起测试请求。
- 展示实际命中的模型、tier、token 和响应内容。

## 当前边界

首版后台只通过 API 管理数据，不直接编辑 `config/gateway.yaml` 和 `config/models.yaml`。

配置编辑需要补齐：

- 权限分级。
- 审计日志。
- 配置 diff。
- 回滚能力。
- 生效前验证。
