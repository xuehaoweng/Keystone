# LLM Gateway 开源产品化设计规格

> 日期：2026-06-07
> 状态：Draft

## 目标

把当前 LLM Gateway 从一个可运行的内部网关原型，升级为适合开源发布的产品化项目。重点不是堆功能，而是让外部用户能够理解它、快速跑起来、观察行为、定位错误，并愿意二次开发。

## 目标用户

- 平台工程师：需要统一管理多个 LLM provider。
- AI 应用开发者：希望业务只接一个模型网关。
- 运维/FinOps：需要查看 token、成本、限流和模型健康。
- 开源贡献者：需要清晰架构、文档、测试和扩展点。

## 非目标

当前阶段不做：

- 完整商业计费系统。
- Prompt 管理平台。
- 工作流编排平台。
- 模型训练或微调。
- 强制依赖 Nginx、Kong、APISIX 或 Kubernetes。

这些可以作为生产部署或企业增强方向，而不是开源 MVP 的前置条件。

## 总体架构

### 开源 MVP 架构

```text
Browser / Business App
  ↓
FastAPI + Uvicorn :8000
  ├─ /llm_gateway_admin  React Admin
  ├─ /api/*              Gateway API
  └─ /health
  ↓
SQLite + Redis
  ↓
Model Providers
```

该阶段继续保持单端口部署，避免用户启动时必须理解 Nginx 或多容器代理。

### 生产推荐架构

```text
Nginx / Kong / APISIX / Envoy
  ↓
FastAPI Gateway
  ↓
Redis + PostgreSQL
  ↓
Model Providers
```

反向代理负责 TLS、IP 白名单、基础访问日志、粗粒度限流。FastAPI 专注模型治理、路由、成本、熔断和审计。

### 企业增强架构

```text
Admin UI
Gateway API
Worker / Metrics Aggregator
PostgreSQL
Redis
Observability Stack
```

当数据量、审计和报表压力变大时，再拆分后台任务、指标聚合和监控系统。

## 前端产品设计

### 设计方向

前端是基础设施控制台，不是营销网站。视觉风格应接近 Cloudflare、Grafana、Linear 管理后台：信息密度高、层级清晰、状态明确、少装饰。

签名交互：Test Console 展示请求生命周期，从“鉴权、路由、模型调用、fallback、完成/失败”逐步呈现，让用户理解一次请求为什么命中某个模型。

### 页面结构

```text
Overview
Models
API Keys
Usage
Routing Rules
Test Console
Settings
```

### Overview

展示网关整体状态：

- 总请求数。
- 总 token。
- 总成本估算。
- 平均延迟。
- 模型健康数量。
- Redis/DB/config 状态。
- 最近错误摘要。

### Models

展示每个模型实例：

- model name。
- provider。
- tier。
- weight。
- max concurrent。
- current connections。
- healthy。
- error count。
- circuit open until。
- 最近错误类型。

首版为只读。启用/禁用模型可以作为后续能力。

### API Keys

功能：

- 创建 key。
- 删除 key。
- 查看 key。
- 查看 key usage。
- 设置 quota、QPS、allowed tiers。

交互要求：

- 创建后的 secret 只展示一次。
- `allowed_tiers` 使用多选控件，而不是自由文本。
- 删除 key 前需要确认。
- app key 不应拥有创建/删除 key 的权限；首版后端需要区分 admin key 和 app key。

### Usage

展示用量和成本：

- 按日期。
- 按 API Key。
- 按 model。
- 按 provider。
- 按 tier。

需要支持筛选、分页和导出基础 JSON。

### Routing Rules

展示当前规则：

- rule name。
- match 条件。
- target tier。
- 命中说明。

首版只读，不直接编辑 YAML。配置编辑需要审计、校验和回滚。

### Test Console

功能：

- 输入 Gateway API Key / JWT。
- 输入 messages。
- 选择 model tier。
- 可选指定 model。
- 设置 temperature、max tokens。
- 发送非流式测试请求。

必须展示：

- 请求中状态。
- 最终模型。
- tier。
- route source。
- rule name。
- attempted models。
- fallback used。
- token usage。
- provider error type。

错误必须分类展示：

- Gateway 鉴权错误。
- Gateway quota/rate limit 错误。
- Provider payment required。
- Provider forbidden。
- Provider rate limited。
- Provider timeout。
- Provider bad request。
- Configuration error。

### Settings

展示脱敏配置：

- gateway config。
- models config。
- provider base URL。
- provider key 是否配置，但不显示 key 内容。

首版只读。配置编辑作为后续版本。

## 后端能力补齐

### 路由元信息

`POST /api/runs` 应在响应中包含路由元信息：

```json
{
  "route": {
    "source": "rule",
    "rule_name": "general_query",
    "requested_tier": "auto",
    "resolved_tier": "cheap",
    "attempted_models": ["deepseek-chat", "kimi-k2.5"],
    "fallback_used": true,
    "cache_hit": false
  }
}
```

流式响应可在最终 done event 中包含 route。

### 错误归一化

下游 provider 错误不能只透传 HTTPX 文本，应归一化为结构化错误：

```json
{
  "error": "Provider payment required",
  "code": "provider_payment_required",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "status_code": 402,
  "details": "DeepSeek account balance or billing status is unavailable"
}
```

错误码：

| code | 含义 |
|------|------|
| `provider_payment_required` | 下游账户余额或计费问题 |
| `provider_forbidden` | 下游 key 无权限 |
| `provider_rate_limited` | 下游限流 |
| `provider_timeout` | 下游超时 |
| `provider_bad_request` | 下游请求格式或模型参数错误 |
| `gateway_quota_exceeded` | 网关月度 quota 超限 |
| `gateway_tier_forbidden` | key 不允许使用目标 tier |
| `gateway_no_available_model` | 没有可用模型 |
| `gateway_config_error` | 配置缺失或非法 |

### Usage API

新增：

```text
GET /api/usage?from=&to=&key_id=&model=&provider=&tier=&limit=&offset=
```

返回分页数据和聚合摘要。

### API Key 权限

需要区分：

- admin key：可管理 key、看全局配置、看全局 usage。
- app key：只能调用 `/api/runs` 和查看自身 usage。

当前测试 key 可作为 admin seed key，但文档必须明确生产环境如何创建 admin key。

### 健康检查

拆分：

```text
GET /health   活性检查
GET /ready    DB、Redis、配置可用性检查
GET /api/providers/health  provider 可用性概览
```

### 配置校验

启动时校验：

- 每个 model 的 provider 存在。
- tier 属于允许值。
- weight、max_concurrent、rate_limit 是正数。
- provider base_url 存在。
- provider key 是否配置，不强制必须配置，但要在 Settings 中提示。

## 开源文档

需要补充：

```text
LICENSE
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md
CODE_OF_CONDUCT.md
.env.example
docker-compose.example.yml
docs/quickstart.md
docs/deployment.md
docs/configuration.md
docs/provider-setup.md
docs/troubleshooting.md
docs/architecture.md
docs/api-reference.md
```

### README 结构

README 应重写为开源首页：

1. 项目是什么。
2. 解决什么问题。
3. 架构图。
4. 快速开始。
5. 第一次创建 Gateway API Key。
6. 第一次调用模型。
7. 管理后台截图或说明。
8. 支持的 provider。
9. 配置示例。
10. Roadmap。
11. License。

## 实施顺序

### Phase 1：前端产品化

- 重构 React 组件结构。
- 增加侧边栏和页面路由状态。
- 增加 Usage、Routing Rules、Settings 页面。
- 增强 Test Console 请求状态和错误展示。

### Phase 2：后端可观测性

- 增加 route metadata。
- 增加 provider error normalization。
- 增加 usage 查询 API。
- 增加 ready/provider health API。

### Phase 3：权限和安全

- 区分 admin key 和 app key。
- 控制管理接口权限。
- 增加审计日志。

### Phase 4：开源文档和发布准备

- 补齐开源文档。
- 补 Docker example。
- 补 provider setup guide。
- 补 troubleshooting。
- 更新 README。

## 成功标准

- 新用户能在 10 分钟内启动项目并打开后台。
- 用户能明确知道右上角填的是 Gateway API Key，不是 provider key。
- Test Console 能解释一次请求为什么命中某个模型。
- Provider 402/403/429 等错误能被结构化展示。
- README 能独立说明项目价值和快速开始。
- 全量后端测试、前端构建和静态检查通过。

