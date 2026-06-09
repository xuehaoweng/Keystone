# LLM Gateway 设计文档

> 日期：2026-04-09
> 状态：Draft

## Context

需要一个统一的大模型调度网关，实现：
- 按需路由到不同大模型（便宜/贵）
- 负载均衡
- 统一鉴权（API Key + JWT）
- 支持流式和非流式响应

技术栈：Python + FastAPI（asyncio 原生异步）+ Redis
部署策略：从轻量开始，支持渐进扩展

## 架构总览

```
Client
  │
  ▼
┌─────────────────────────────────────────────────┐
│  FastAPI Gateway (asyncio)                       │
│                                                   │
│  ┌───────────┐  ┌─────────────┐  ┌────────────┐ │
│  │   Auth    │→ │  Request    │→ │   Router   │ │
│  │ Middleware│  │  Analyzer   │  │            │ │
│  └───────────┘  └─────────────┘  └─────┬──────┘ │
│                                         │        │
│  ┌──────────────────────────────────────┴──────┐ │
│  │         Model Dispatcher (asyncio)           │ │
│  │  ┌────────────┐  ┌──────────┐  ┌─────────┐ │ │
│  │  │   Model    │→ │ Response │→ │ Stream  │ │ │
│  │  │  Adapter   │  │ Handler  │  │ (SSE)   │ │ │
│  │  └────────────┘  └──────────┘  └─────────┘ │ │
│  │                                             │ │
│  │  BackgroundTasks: 日志写入 / 用量统计        │ │
│  └──────────────────────────────────────────────┘ │
│                                                    │
│  Config: YAML  │  Logs: SQLite/PostgreSQL          │
└────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│     Redis         │
│  - 限流计数器     │
│  - 负载均衡状态   │
│  - 意图分类缓存   │
│  - API Key 存储   │
└──────────────────┘
         │
         ▼
┌──────────────────┐
│  Model Providers  │
│  OpenAI / Anthropic│
│  Qwen / Others    │
└──────────────────┘
```

## 核心组件设计

### 1. 统一鉴权层

**API Key 认证**
- 网关自颁 API Key，存储在 Redis/DB
- Key 绑定：user_id、quota（月度额度）、rate_limit（QPS）、allowed_tiers（可用模型等级）
- 请求头：`Authorization: Bearer <api_key>`

**JWT 认证**
- 支持外部 JWT（企业 SSO/OIDC）
- 验证签名后提取 user_id、role
- 请求头：`Authorization: Bearer <jwt_token>`

**限流**
- Redis 滑动窗口限流，按 user_id 维度
- 超出配额返回 `429 Too Many Requests`

### 2. 请求分析器 + 混合路由

**路由决策流程（POST /api/runs 入口）**：

```
Request → 规则匹配 → 命中？ → YES → 直接路由到对应 tier
                      ↓ NO
              查 Redis 意图分类缓存（相似请求 5 分钟内）
                      ↓ 命中
              使用缓存结果
                      ↓ 未命中
              意图分类模型（haiku/qwen-turbo）
              超时: 2 秒 → 超时则降级到 cheap tier
                      ↓
              输出: {tier, task_type, fallback_model}
              写入 Redis 缓存（TTL 5 分钟）
                      ↓
              从同 tier 可用模型中选择一个
```

**意图分类缓存**：
- Key: `intent:{content_hash}` （内容前 200 字符的 MD5）
- Value: `{"tier": "cheap", "task_type": "query", "ts": ...}`
- TTL: 5 分钟
- 缓存命中率目标: > 30%（减少重复分类调用）
- 超时降级: 意图分类请求 2 秒未返回 → 默认 cheap tier，不阻塞主流程

**规则引擎**（优先匹配，零成本）：
```yaml
rules:
  - name: "db_query"
    match:
      tools: ["execute_sql", "query_database"]
    tier: cheap
    
  - name: "mcp_call"
    match:
      tools: ["mcp_*"]
    tier: cheap
    
  - name: "skill_invoke"
    match:
      tools: ["skill_*"]
    tier: cheap
    
  - name: "knowledge_search"
    match:
      keywords: ["查询", "搜索", "查找"]
      max_content_tokens: 500    # 请求内容 token 数上限
    tier: cheap
    
  - name: "alert_analysis"
    match:
      keywords: ["告警", "报警", "incident"]
      min_content_tokens: 1000   # 请求内容 token 数下限
    tier: expensive
    
  - name: "code_collaboration"
    match:
      keywords: ["代码审查", "code review", "重构"]
      min_content_tokens: 2000
    tier: expensive
    
  - name: "general_query"
    match:
      max_content_tokens: 200
    tier: cheap
```

**意图分类 Prompt**（兜底）：
```
你是一个请求分类器。请将用户请求分类为以下等级：
- cheap: 简单查询、数据检索、MCP调用、Skill调用、常识问答
- expensive: 深度分析、告警诊断、知识库综合解答、代码协作、复杂推理

输出 JSON: {"tier": "cheap|expensive", "task_type": "...", "fallback_model": "..."}
```

### 3. 负载均衡

**策略**：加权轮询 + 最少连接数

- 每个模型实例维护：当前请求数、QPS、错误率、健康状态
- 选择算法：
  1. 过滤不健康实例（错误率 > 阈值 或 健康检查失败）
  2. 同 tier 内按权重轮询
  3. 权重相同时选当前连接数最少的实例

**健康检查**：
- 轻量探测：调用各 provider 的 models list API（非 chat），费用极低或免费
- 连续 N 次失败 → 摘除实例
- 恢复后自动重新加入
- 检查间隔：30 秒（可配置）

**配置示例**：
```yaml
models:
  - name: "gpt-4o-mini"
    tier: cheap
    weight: 3
    provider: openai
    max_concurrent: 100
    rate_limit: 1000  # rpm
    
  - name: "claude-haiku"
    tier: cheap
    weight: 2
    provider: anthropic
    max_concurrent: 80
    rate_limit: 800
    
  - name: "claude-opus"
    tier: expensive
    weight: 1
    provider: anthropic
    max_concurrent: 20
    rate_limit: 200
    
  - name: "qwen-plus"
    tier: cheap
    weight: 2
    provider: qwen
    max_concurrent: 150
    rate_limit: 1500
```

### 4. 模型适配器

**统一接口**：
```python
class ModelAdapter(ABC):
    async def chat(
        self,
        messages: list[Message],
        stream: bool = False,
        **kwargs
    ) -> ChatResponse | AsyncIterator[ChatChunk]:
        ...
```

**各提供商实现**：
- `OpenAIAdapter` — 适配 OpenAI/GPT 系列
- `AnthropicAdapter` — 适配 Claude 系列
- `QwenAdapter` — 适配通义千问
- `GenericAdapter` — 适配兼容 OpenAI 格式的其他模型

**容错机制**：
- 重试：指数退避，最多 3 次
- 超时：请求级超时（可配置）
- 熔断：连续失败 N 次 → 熔断 30 秒
- Fallback：模型不可用 → 使用 fallback_model → 返回错误

### 4.1 下游 Provider 鉴权

- 各模型的 API Key 通过环境变量注入：`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `QWEN_API_KEY`
- 支持多账号轮询：同一 provider 可配置多个 API Key，按轮询分配
- Key 轮换：热加载环境变量变更，无需重启
- 安全：API Key 不写入日志，不暴露在 API 响应中

### 5. 流式/非流式响应

**流式（SSE）— 单次请求直接返回**：
- 客户端发 `POST /api/runs` with `stream: true`
- FastAPI 端直接 `async for` 调用模型适配器
- 使用 `StreamingResponse` + `text/event-stream` 实时推送 chunks
- 客户端断开 → `asyncio.CancelledError` → 取消模型调用，释放资源
- 后台通过 `BackgroundTasks` 异步写入日志和用量统计

**非流式**：
- 客户端发 `POST /api/runs` with `stream: false`（默认）
- asyncio 同步等待模型完整响应后返回
- 设置请求级超时，超时返回 504

### 5.1 用量统计与计费

每次请求完成后（流式结束或非流式返回），通过 `BackgroundTasks` 异步记录：
- user_id、model_name、tier、prompt_tokens、completion_tokens、total_tokens
- 请求延迟、是否命中缓存、路由决策路径
- 按 user_id 聚合日/月 token 用量和估算费用
- 接口：`GET /api/metrics` 返回网关级别统计，`GET /api/auth/keys/{id}/usage` 返回单 Key 用量

### 6. API 设计

```
POST /api/runs              # 创建对话请求（核心接口，流式/非流式由 body.stream 控制）
GET  /api/runs/{run_id}     # 查询历史请求状态
DELETE /api/runs/{run_id}   # 取消进行中的请求

POST /api/auth/keys         # 创建 API Key
GET  /api/auth/keys         # 列出 API Keys
GET  /api/auth/keys/{id}/usage  # 查询单 Key 用量
DELETE /api/auth/keys/{id}  # 删除 API Key

GET  /api/models            # 列出可用模型
GET  /api/models/{name}/health  # 模型健康状态
GET  /api/metrics           # 网关指标（QPS、延迟、错误率、token 用量）
```

**/api/runs 请求体**：
```json
{
    "messages": [
        {"role": "user", "content": "帮我分析这个告警..."}
    ],
    "stream": true,
    "model_tier": "auto",        // auto | cheap | expensive
    "preferred_model": null,     // 可选，指定偏好模型
    "fallback_model": null,      // 可选，指定降级模型
    "temperature": 0.7,
    "max_tokens": 4096,
    "tools": []                  // 可选，MCP/Skill 工具列表（用于规则匹配）
}
```

### 7. 项目结构

```
llm_gateway/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置加载
│   ├── api/
│   │   ├── __init__.py
│   │   ├── runs.py             # /api/runs 端点
│   │   ├── auth.py             # 鉴权端点
│   │   └── admin.py            # 管理端点
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py             # 鉴权中间件
│   │   └── rate_limit.py       # 限流中间件
│   ├── services/
│   │   ├── __init__.py
│   │   ├── router.py           # 路由决策
│   │   ├── load_balancer.py    # 负载均衡
│   │   ├── rule_engine.py      # 规则匹配
│   │   ├── intent_classifier.py # 意图分类
│   │   ├── dispatcher.py       # 异步调度器 (asyncio)
│   │   └── metrics.py          # 用量统计
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py             # 抽象基类
│   │   ├── openai_adapter.py
│   │   ├── anthropic_adapter.py
│   │   └── qwen_adapter.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── request.py          # 请求模型
│   │   └── response.py         # 响应模型
│   └── db/
│       ├── __init__.py
│       ├── redis.py            # Redis 连接
│       └── sqlite.py           # SQLite 存储
├── config/
│   ├── gateway.yaml            # 网关配置
│   └── models.yaml             # 模型配置
├── tests/
├── docker-compose.yml          # 开发环境
├── Dockerfile
├── pyproject.toml
└── README.md
```

## 错误处理

| 场景 | 处理 |
|------|------|
| 鉴权失败 | 401 Unauthorized |
| 配额/限流 | 429 Too Many Requests |
| 无可用模型 | 503 Service Unavailable |
| 模型超时 | 重试 → fallback → 返回错误 |
| 客户端断开 | `asyncio.CancelledError` 捕获，取消模型调用 |
| 配置错误 | 启动时校验，阻止启动 |

## 扩展路径

1. **水平扩展**：多 worker uvicorn + Redis 共享状态 → 增加进程实例
2. **数据库升级**：SQLite → PostgreSQL（配置切换）
3. **拆分服务**：Router/Adapter 可独立为微服务
4. **可观测性**：添加 OpenTelemetry 追踪、Prometheus 指标
5. **语义缓存**：相似请求结果缓存（embedding similarity），跳过模型调用直接返回
