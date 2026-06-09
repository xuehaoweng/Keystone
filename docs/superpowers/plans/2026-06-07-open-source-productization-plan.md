# LLM Gateway 开源产品化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 LLM Gateway 升级为开源友好的产品化项目，重点补齐前端管理后台、路由可观测性、错误归一化、按 key 用量查询和开源文档。

**架构：** 保持 FastAPI 单端口托管 React build 的 MVP 架构。后端新增结构化 route metadata、provider error normalization、usage 查询和健康检查接口；前端重构为基础设施控制台，展示 key、模型、规则、用量和测试请求生命周期。

**技术栈：** Python 3.12、FastAPI、SQLite、Redis、pytest、React 18、Vite、TypeScript、lucide-react。

---

## 文件结构

### 后端

- 修改：`app/models/response.py`
  - 新增 `RouteInfo`、`GatewayError` 等响应模型。
- 新增：`app/services/provider_errors.py`
  - 将 httpx/provider 异常归一化为结构化错误码。
- 修改：`app/services/router.py`
  - 返回路由来源、规则名、resolved tier 等元信息。
- 修改：`app/services/rule_engine.py`
  - 保留 rule name，供 route metadata 使用。
- 修改：`app/api/runs.py`
  - 返回 route metadata。
  - 记录 attempted models。
  - 使用 provider error normalization。
- 修改：`app/services/metrics.py`
  - 新增分页 usage 查询。
- 修改：`app/api/admin.py`
  - 新增 `/api/usage`、`/ready`、`/api/providers/health`。
- 测试：`tests/test_api_runs.py`
  - 覆盖 route metadata、attempted models、provider error code。
- 测试：`tests/test_api_auth.py`
  - 覆盖 usage API、ready/config/provider health。
- 测试：`tests/test_provider_errors.py`
  - 覆盖 402/403/429/timeout/bad request 映射。

### 前端

- 修改：`frontend/src/App.tsx`
  - 拆分页面前的过渡版本，保留单文件但改成侧边栏布局。
- 新增：`frontend/src/types.ts`
  - 前端共享类型。
- 新增：`frontend/src/components/StatusBanner.tsx`
  - 展示 loading/success/error。
- 新增：`frontend/src/components/DataTable.tsx`
  - 简单表格组件。
- 新增：`frontend/src/pages/OverviewPage.tsx`
- 新增：`frontend/src/pages/ModelsPage.tsx`
- 新增：`frontend/src/pages/ApiKeysPage.tsx`
- 新增：`frontend/src/pages/UsagePage.tsx`
- 新增：`frontend/src/pages/RoutingRulesPage.tsx`
- 新增：`frontend/src/pages/TestConsolePage.tsx`
- 新增：`frontend/src/pages/SettingsPage.tsx`
- 修改：`frontend/src/styles.css`
  - 侧边栏、页面状态、表格、错误说明和响应式样式。

### 文档

- 新增：`LICENSE`
- 新增：`CONTRIBUTING.md`
- 新增：`SECURITY.md`
- 新增：`CHANGELOG.md`
- 新增：`CODE_OF_CONDUCT.md`
- 新增：`docs/quickstart.md`
- 新增：`docs/deployment.md`
- 新增：`docs/configuration.md`
- 新增：`docs/provider-setup.md`
- 新增：`docs/troubleshooting.md`
- 修改：`README.md`
  - 重写为开源首页结构。

---

## 任务 1：Provider 错误归一化

**文件：**
- 创建：`app/services/provider_errors.py`
- 修改：`app/models/response.py`
- 测试：`tests/test_provider_errors.py`

- [ ] **步骤 1：编写失败测试**

```python
import httpx

from app.services.provider_errors import normalize_provider_error


def _http_error(status_code: int, url: str = "https://api.deepseek.com/v1/chat/completions"):
    request = httpx.Request("POST", url)
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_402_maps_to_payment_required():
    error = normalize_provider_error(_http_error(402), provider="deepseek", model="deepseek-chat")
    assert error.code == "provider_payment_required"
    assert error.status_code == 402
    assert error.provider == "deepseek"


def test_429_maps_to_rate_limited():
    error = normalize_provider_error(_http_error(429), provider="deepseek", model="deepseek-chat")
    assert error.code == "provider_rate_limited"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_provider_errors.py -v`

预期：FAIL，提示 `ModuleNotFoundError: No module named 'app.services.provider_errors'`。

- [ ] **步骤 3：实现最少代码**

```python
from dataclasses import dataclass

import httpx


@dataclass
class ProviderError:
    code: str
    message: str
    provider: str
    model: str
    status_code: int | None = None
    details: str | None = None


def normalize_provider_error(exc: Exception, provider: str, model: str) -> ProviderError:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 402:
            return ProviderError("provider_payment_required", "Provider payment required", provider, model, status_code, str(exc))
        if status_code == 403:
            return ProviderError("provider_forbidden", "Provider forbidden", provider, model, status_code, str(exc))
        if status_code == 429:
            return ProviderError("provider_rate_limited", "Provider rate limited", provider, model, status_code, str(exc))
        if status_code == 400:
            return ProviderError("provider_bad_request", "Provider bad request", provider, model, status_code, str(exc))
        return ProviderError("provider_error", "Provider error", provider, model, status_code, str(exc))
    if isinstance(exc, TimeoutError):
        return ProviderError("provider_timeout", "Provider timeout", provider, model, None, str(exc))
    return ProviderError("provider_error", "Provider error", provider, model, None, str(exc))
```

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_provider_errors.py -v`

预期：PASS。

---

## 任务 2：Runs 返回 route metadata 和 attempted models

**文件：**
- 修改：`app/models/response.py`
- 修改：`app/services/router.py`
- 修改：`app/api/runs.py`
- 测试：`tests/test_api_runs.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_api_runs.py` 添加：

```python
def test_create_run_response_includes_route_metadata(monkeypatch):
    # 使用现有 mock lb 和 adapter 模式。
    # 期望响应 JSON 包含 route.resolved_tier、route.attempted_models、route.cache_hit。
    ...
```

测试断言：

```python
assert data["route"]["resolved_tier"] == "cheap"
assert data["route"]["attempted_models"] == ["cheap-a"]
assert data["route"]["cache_hit"] is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_api_runs.py::test_create_run_response_includes_route_metadata -v`

预期：FAIL，响应中没有 `route`。

- [ ] **步骤 3：实现响应模型**

在 `app/models/response.py` 添加：

```python
class RouteInfo(BaseModel):
    source: str = "unknown"
    rule_name: str | None = None
    requested_tier: str = "auto"
    resolved_tier: str
    attempted_models: list[str] = []
    fallback_used: bool = False
    cache_hit: bool = False


class ChatResponse(BaseModel):
    ...
    route: RouteInfo | None = None
```

- [ ] **步骤 4：实现 API route metadata**

在 `app/api/runs.py` 中：

- `_dispatch_non_stream_with_retry` 返回 `(current, result, attempted_models)`。
- cache hit 时返回 `route.cache_hit = True`。
- 非 cache 成功时返回 `route.cache_hit = False`。
- `fallback_used = len(attempted_models) > 1`。

- [ ] **步骤 5：运行测试验证通过**

运行：`uv run pytest tests/test_api_runs.py -v`

预期：PASS。

---

## 任务 3：Usage API 按 key/model/provider/tier 查询

**文件：**
- 修改：`app/services/metrics.py`
- 修改：`app/api/admin.py`
- 测试：`tests/test_api_auth.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_api_auth.py` 添加：

```python
def test_usage_endpoint_returns_db_summary(client):
    resp = client.get("/api/usage")
    assert resp.status_code == 200
    assert "items" in resp.json()
    assert "summary" in resp.json()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_api_auth.py::test_usage_endpoint_returns_db_summary -v`

预期：FAIL，404。

- [ ] **步骤 3：实现 metrics 查询**

在 `app/services/metrics.py` 添加：

```python
async def query_usage(...):
    ...
    return {"items": items, "summary": summary, "limit": limit, "offset": offset}
```

支持参数：

- `from_ts`
- `to_ts`
- `key_id`
- `model`
- `provider`
- `tier`
- `limit`
- `offset`

首版 provider 可通过 model config 映射补充到 item。

- [ ] **步骤 4：实现 API**

在 `app/api/admin.py` 添加：

```python
@router.get("/usage")
async def usage(...):
    await authenticate(request)
    return await query_usage(...)
```

- [ ] **步骤 5：运行测试验证通过**

运行：`uv run pytest tests/test_api_auth.py -v`

预期：PASS。

---

## 任务 4：Ready 和 Provider Health

**文件：**
- 修改：`app/api/admin.py`
- 测试：`tests/test_api_auth.py`

- [ ] **步骤 1：编写失败测试**

```python
def test_ready_endpoint(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"ready", "degraded"}


def test_provider_health_endpoint(client):
    resp = client.get("/api/providers/health")
    assert resp.status_code == 200
    assert "providers" in resp.json()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`uv run pytest tests/test_api_auth.py::test_ready_endpoint tests/test_api_auth.py::test_provider_health_endpoint -v`

预期：FAIL，404。

- [ ] **步骤 3：实现接口**

- `/ready` 检查 SQLite `SELECT 1`，Redis 可连接则 ready，不可连接则 degraded。
- `/api/providers/health` 根据 models config 返回 provider、base_url、configured_key_count、models。

- [ ] **步骤 4：运行测试验证通过**

运行：`uv run pytest tests/test_api_auth.py -v`

预期：PASS。

---

## 任务 5：React 前端信息架构重构

**文件：**
- 创建：`frontend/src/types.ts`
- 创建：`frontend/src/components/StatusBanner.tsx`
- 创建：`frontend/src/components/DataTable.tsx`
- 创建：`frontend/src/pages/OverviewPage.tsx`
- 创建：`frontend/src/pages/ModelsPage.tsx`
- 创建：`frontend/src/pages/ApiKeysPage.tsx`
- 创建：`frontend/src/pages/UsagePage.tsx`
- 创建：`frontend/src/pages/RoutingRulesPage.tsx`
- 创建：`frontend/src/pages/TestConsolePage.tsx`
- 创建：`frontend/src/pages/SettingsPage.tsx`
- 修改：`frontend/src/App.tsx`
- 修改：`frontend/src/api.ts`
- 修改：`frontend/src/styles.css`

- [ ] **步骤 1：拆类型**

把 `frontend/src/api.ts` 中类型移到 `frontend/src/types.ts`，保留 `ApiClient`。

- [ ] **步骤 2：创建通用组件**

`StatusBanner` props：

```ts
type StatusBannerProps = {
  kind: "idle" | "loading" | "success" | "error";
  children: React.ReactNode;
};
```

`DataTable` props：

```ts
type DataTableProps = {
  columns: string[];
  rows: React.ReactNode[][];
};
```

- [ ] **步骤 3：拆页面**

每个页面接收 `client`、`runAction`、`state` 所需 props，避免全局状态库。

- [ ] **步骤 4：改 App 为侧边栏布局**

导航项：

```ts
Overview, Models, API Keys, Usage, Routing Rules, Test Console, Settings
```

- [ ] **步骤 5：构建验证**

运行：`npm run build`

预期：PASS。

---

## 任务 6：Test Console 展示 route 和 provider error

**文件：**
- 修改：`frontend/src/pages/TestConsolePage.tsx`
- 修改：`frontend/src/types.ts`
- 修改：`frontend/src/api.ts`

- [ ] **步骤 1：更新 RunResponse 类型**

添加：

```ts
route?: {
  source: string;
  rule_name?: string | null;
  requested_tier: string;
  resolved_tier: string;
  attempted_models: string[];
  fallback_used: boolean;
  cache_hit: boolean;
};
```

- [ ] **步骤 2：展示请求生命周期**

成功时展示：

- model。
- tier。
- route source。
- attempted models。
- fallback used。
- cache hit。
- token usage。

失败时展示归一化错误 code、provider、model、status code。

- [ ] **步骤 3：构建验证**

运行：`npm run build`

预期：PASS。

---

## 任务 7：开源文档补齐

**文件：**
- 创建：`LICENSE`
- 创建：`CONTRIBUTING.md`
- 创建：`SECURITY.md`
- 创建：`CHANGELOG.md`
- 创建：`CODE_OF_CONDUCT.md`
- 创建：`docs/quickstart.md`
- 创建：`docs/deployment.md`
- 创建：`docs/configuration.md`
- 创建：`docs/provider-setup.md`
- 创建：`docs/troubleshooting.md`
- 修改：`README.md`

- [ ] **步骤 1：README 重写**

结构：

1. What is LLM Gateway。
2. Problems it solves。
3. Architecture。
4. Quick start。
5. Admin UI。
6. Provider setup。
7. Roadmap。
8. License。

- [ ] **步骤 2：补 quickstart**

必须包含：

```bash
uv sync
npm install --prefix frontend
npm run build --prefix frontend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- [ ] **步骤 3：补 provider setup**

明确区分：

- Gateway API Key：填在前端右上角，用于调用网关。
- Provider API Key：服务端环境变量，用于调用 DeepSeek/Kimi/OpenAI 等。

- [ ] **步骤 4：补 troubleshooting**

包含：

- DeepSeek 402。
- Provider 403。
- Provider 429。
- Missing authorization header。
- `/` 访问跳转。
- `/llm_gateway_admin` 静态资源问题。

- [ ] **步骤 5：文档检查**

运行：`rg "TODO|待定|TBD" README.md docs CONTRIBUTING.md SECURITY.md CHANGELOG.md CODE_OF_CONDUCT.md LICENSE`

预期：无未完成占位符。

---

## 最终验证

- [ ] `uv run pytest`
- [ ] `uv run ruff check app tests`
- [ ] `npm run build` in `frontend/`
- [ ] `curl http://127.0.0.1:8000/health`
- [ ] `curl -I http://127.0.0.1:8000/llm_gateway_admin`

## 规格覆盖自检

- 前端页面结构：已覆盖任务 5 和 6。
- route metadata：已覆盖任务 2。
- provider error normalization：已覆盖任务 1 和 6。
- usage by key/model/provider/tier：已覆盖任务 3。
- ready/provider health：已覆盖任务 4。
- 开源文档：已覆盖任务 7。

