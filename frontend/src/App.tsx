import {
  Activity,
  AlertTriangle,
  BookOpen,
  Boxes,
  Braces,
  CheckCircle2,
  CircleDot,
  FileSliders,
  Github,
  KeyRound,
  LogOut,
  ListTree,
  PackageOpen,
  Play,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Split,
  TimerReset,
  WalletCards
} from "lucide-react";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import {
  ApiClient,
  ApiKeyInfo,
  AuthIdentity,
  MetricsSummary,
  ModelInfo,
  AuditResponse,
  PoliciesResponse,
  ProviderHealthResponse,
  ProviderSlaResponse,
  RunResponse,
  TraceResponse,
  UsageResponse
} from "./api";

type Tab = "overview" | "models" | "keys" | "usage" | "routing" | "console" | "providers" | "traces" | "sla" | "policies" | "audit";
type OutputKind = "idle" | "loading" | "success" | "error";
const demoGatewayKey = "lgw_test_key_2026";

const tabGroups = ["观测", "治理", "开发"] as const;

const tabs: Array<{ id: Tab; label: string; icon: ReactNode; group: (typeof tabGroups)[number] }> = [
  { id: "overview", label: "概览", icon: <Activity size={16} />, group: "观测" },
  { id: "models", label: "模型池", icon: <Boxes size={16} />, group: "观测" },
  { id: "usage", label: "用量账单", icon: <WalletCards size={16} />, group: "观测" },
  { id: "traces", label: "调用追踪", icon: <ListTree size={16} />, group: "观测" },
  { id: "sla", label: "SLA 看板", icon: <TimerReset size={16} />, group: "观测" },
  { id: "keys", label: "访问密钥", icon: <KeyRound size={16} />, group: "治理" },
  { id: "routing", label: "路由规则", icon: <Split size={16} />, group: "治理" },
  { id: "policies", label: "策略中心", icon: <SlidersHorizontal size={16} />, group: "治理" },
  { id: "audit", label: "审计日志", icon: <ScrollText size={16} />, group: "治理" },
  { id: "console", label: "测试控制台", icon: <Play size={16} />, group: "开发" },
  { id: "providers", label: "供应商配置", icon: <FileSliders size={16} />, group: "开发" }
];

function formatNumber(value: number | undefined): string {
  return new Intl.NumberFormat("zh-CN").format(value ?? 0);
}

export function App() {
  const currentPath = window.location.pathname;
  const [token, setToken] = useState(() => localStorage.getItem("llm_gateway_token") || "");
  const [credentialInput, setCredentialInput] = useState(() => localStorage.getItem("llm_gateway_token") || "");
  const [authLoading, setAuthLoading] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [authMessageKind, setAuthMessageKind] = useState<OutputKind>("idle");
  const [active, setActive] = useState<Tab>("overview");
  const [metrics, setMetrics] = useState<MetricsSummary>({});
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [models, setModels] = useState<Record<string, ModelInfo>>({});
  const [config, setConfig] = useState<unknown>(null);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [providers, setProviders] = useState<ProviderHealthResponse | null>(null);
  const [traces, setTraces] = useState<TraceResponse | null>(null);
  const [sla, setSla] = useState<ProviderSlaResponse | null>(null);
  const [audit, setAudit] = useState<AuditResponse | null>(null);
  const [policies, setPolicies] = useState<PoliciesResponse | null>(null);
  const [ready, setReady] = useState<{ status?: string; checks?: Record<string, boolean> }>({});
  const [output, setOutput] = useState("");
  const [outputKind, setOutputKind] = useState<OutputKind>("idle");
  const [identity, setIdentity] = useState<AuthIdentity | null>(null);
  const [consoleTierFilter, setConsoleTierFilter] = useState("all");
  const [consoleHealthFilter, setConsoleHealthFilter] = useState("healthy");
  const [consoleSearch, setConsoleSearch] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [createMode, setCreateMode] = useState<"self" | "admin">("self");
  const [busy, setBusy] = useState(false);
  const client = useMemo(() => new ApiClient(token), [token]);
  const isAdmin = identity?.role === "admin";
  const isLoggedIn = Boolean(identity && token.trim());
  const consoleModels = useMemo(
    () => filterConsoleModels(models, consoleTierFilter, consoleHealthFilter, consoleSearch),
    [models, consoleTierFilter, consoleHealthFilter, consoleSearch],
  );

  function applyToken(nextToken: string) {
    const normalized = nextToken.trim();
    setToken(normalized);
    setCredentialInput(normalized);
    localStorage.setItem("llm_gateway_token", normalized);
  }

  async function runAction(action: () => Promise<unknown>) {
    setBusy(true);
    setOutputKind("loading");
    setOutput("请求中...");
    try {
      const result = await action();
      setOutputKind("success");
      setOutput(JSON.stringify(result, null, 2));
    } catch (error) {
      setOutputKind("error");
      setOutput(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  async function runSilent(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      setOutputKind("error");
      setOutput(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  async function refreshIdentity(candidateToken = token) {
    try {
      const me = await new ApiClient(candidateToken).request<AuthIdentity>("/api/auth/me");
      setIdentity(me);
      return me;
    } catch (error) {
      setIdentity(null);
      if (candidateToken === token) {
        setAuthMessageKind("error");
        setAuthMessage(formatAuthError(error));
      }
      return null;
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = credentialInput.trim();
    if (!candidate) {
      setAuthMessageKind("error");
      setAuthMessage("请输入 Gateway API Key 或 JWT。");
      return;
    }
    setAuthLoading(true);
    setAuthMessageKind("loading");
    setAuthMessage("正在校验凭证...");
    try {
      const me = await new ApiClient(candidate).request<AuthIdentity>("/api/auth/me");
      applyToken(candidate);
      setAuthMessageKind("success");
      setAuthMessage(`登录成功：${me.auth_type === "jwt" ? "JWT" : "API Key"}，用户 ${me.user_id}，角色 ${me.role === "admin" ? "管理员" : "普通用户"}。`);
      setActive("overview");
      setIdentity(me);
      window.history.replaceState({}, "", "/llm_gateway_admin");
    } catch (error) {
      setAuthMessageKind("error");
      setAuthMessage(formatAuthError(error));
    }
    setAuthLoading(false);
  }

  function useDemoToken() {
    setCredentialInput(demoGatewayKey);
    setAuthMessageKind("loading");
    setAuthMessage("已填入演示 Key，请点击“登录”。");
  }

  function logout() {
    setToken("");
    setIdentity(null);
    setCredentialInput("");
    localStorage.removeItem("llm_gateway_token");
    setAuthMessage("");
    setAuthMessageKind("idle");
    setOutput("");
    setOutputKind("idle");
    setActive("overview");
    window.history.replaceState({}, "", "/login");
  }

  async function refreshOverview() {
    const readyData = await client.request<{ status: string; checks: Record<string, boolean> }>("/ready");
    setReady(readyData);
    const data = await client.request<MetricsSummary>("/api/metrics");
    setMetrics(data);
    return { metrics: data, ready: readyData };
  }

  async function refreshKeys() {
    const data = await client.request<ApiKeyInfo[]>("/api/auth/keys");
    setKeys(data);
    return data;
  }

  async function refreshModels() {
    const modelData = await client.request<Record<string, ModelInfo>>("/api/models");
    const configData = await client.request<unknown>("/api/config");
    setModels(modelData);
    setConfig(configData);
    return { models: modelData, config: configData };
  }

  async function refreshUsage() {
    const data = await client.request<UsageResponse>("/api/usage?limit=25");
    setUsage(data);
    return data;
  }

  async function refreshProviders() {
    const providerData = await client.request<ProviderHealthResponse>("/api/providers/health");
    const configData = await client.request<unknown>("/api/config");
    setProviders(providerData);
    setConfig(configData);
    return { providers: providerData, config: configData };
  }

  async function refreshTraces() {
    const data = await client.request<TraceResponse>("/api/traces?limit=50");
    setTraces(data);
    return data;
  }

  async function refreshSla() {
    const data = await client.request<ProviderSlaResponse>("/api/providers/sla");
    setSla(data);
    return data;
  }

  async function refreshAudit() {
    const data = await client.request<AuditResponse>("/api/audit?limit=50");
    setAudit(data);
    return data;
  }

  async function refreshPolicies() {
    const data = await client.request<PoliciesResponse>("/api/policies");
    setPolicies(data);
    return data;
  }

  async function loadTab(tab: Tab) {
    setOutput("");
    setOutputKind("idle");
    if (tab === "overview") {
      await runSilent(refreshOverview);
      return;
    }
    if (tab === "models" || tab === "routing") {
      await runSilent(refreshModels);
    } else if (tab === "keys") {
      await runSilent(refreshKeys);
    } else if (tab === "usage") {
      await runSilent(refreshUsage);
    } else if (tab === "providers") {
      await runSilent(refreshProviders);
    } else if (tab === "traces") {
      await runSilent(refreshTraces);
    } else if (tab === "sla") {
      await runSilent(refreshSla);
    } else if (tab === "audit") {
      await runSilent(refreshAudit);
    } else if (tab === "policies") {
      await runSilent(refreshPolicies);
    }
  }

  useEffect(() => {
    if (!token.trim()) {
      setIdentity(null);
      setAuthLoading(false);
      setAuthMessageKind("idle");
      setAuthMessage("");
      return;
    }
    if (isLoggedIn) {
      if (active === "console" && Object.keys(models).length === 0) {
        void runSilent(refreshModels);
      } else {
        void loadTab(active);
      }
      setAuthLoading(false);
      return;
    }
    setAuthLoading(true);
    setAuthMessageKind("loading");
    setAuthMessage("正在校验凭证...");
    const verifyToken = token.trim();
    refreshIdentity(verifyToken)
      .catch(() => {
        return null;
      })
      .finally(() => {
        setAuthLoading(false);
      });
  }, [active, isLoggedIn, token]);

  useEffect(() => {
    if (!isAdmin && createMode === "admin") {
      setCreateMode("self");
    }
  }, [isAdmin, createMode]);

  useEffect(() => {
    if (isLoggedIn) {
      if (currentPath === "/login" || currentPath === "/login/" || currentPath === "/") {
        window.history.replaceState({}, "", "/llm_gateway_admin");
      }
      return;
    }
    if (currentPath !== "/login" && currentPath !== "/login/") {
      window.history.replaceState({}, "", "/login");
    }
  }, [currentPath, isLoggedIn]);

  async function createKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (createMode === "admin" && !isAdmin) {
      setOutputKind("error");
      setOutput("当前凭证角色不是管理员，不能使用管理员代建。请先使用管理员 JWT 或留空切到普通创建。");
      return;
    }
    const formData = new FormData(event.currentTarget);
    const ownerUserId = String(formData.get("owner_user_id") || "").trim();
    if (createMode === "admin" && !ownerUserId) {
      setOutputKind("error");
      setOutput("管理员代建需要填写“归属用户ID”。如果要给当前登录用户创建 Key，请选择“普通创建”。");
      return;
    }
    for (const [key, value] of formData.entries()) {
      const trimmed = String(value).trim();
      if (trimmed) {
        params.set(key, trimmed);
      }
    }
    await runAction(async () => {
      const created = await client.request(`/api/auth/keys?${params.toString()}`, { method: "POST" });
      await refreshKeys();
      return created;
    });
  }

  async function deleteKey(id: string) {
    await runAction(async () => {
      const deleted = await client.request(`/api/auth/keys/${id}`, { method: "DELETE" });
      await refreshKeys();
      return deleted;
    });
  }

  async function copyIntegrationPackage(key: ApiKeyInfo) {
    if (!key.key) {
      setOutputKind("error");
      setOutput("这个 Key 是旧数据，数据库里没有可解密的密文。请重新创建一个 Key 后复制接入包。");
      return;
    }
    const baseUrl = window.location.origin;
    const packageText = buildIntegrationPackage(baseUrl, key);
    await copyText(packageText);
    setOutputKind("success");
    setOutput(`已复制 ${key.name} 的接入包。`);
  }

  async function sendRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const model = selectedModel.trim();
    const payload: Record<string, unknown> = {
      messages: [{ role: "user", content: String(form.get("message") || "") }],
      model_tier: String(form.get("model_tier") || "auto"),
      temperature: Number(form.get("temperature") || 0),
      max_tokens: Number(form.get("max_tokens") || 512),
      stream: false
    };
    if (model) {
      payload.model = model;
    }
    await runAction(async () => {
      const result = await client.request<RunResponse>("/api/runs", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      await refreshOverview();
      return result;
    });
  }

  async function createPolicyDraft() {
    const content = policies?.current || {};
    await runAction(async () => {
      const draft = await client.request("/api/policies/drafts", {
        method: "POST",
        body: JSON.stringify({
          name: `策略草案-${new Date().toISOString().slice(0, 10)}`,
          content,
        }),
      });
      await refreshPolicies();
      await refreshAudit();
      return draft;
    });
  }

  if (!isLoggedIn) {
    return (
      <div className="app-shell auth-shell">
        <section className="auth-card">
          <div>
            <div className="eyebrow"><ShieldCheck size={15} /> 开源 LLM Gateway</div>
            <h1>LLM Gateway 管理后台登录</h1>
            <p>请先使用网关凭证（Gateway API Key 或 JWT）登录后，再访问管理入口。</p>
          </div>
          <div className="onboarding-grid">
            <article className="onboarding-step">
              <h2>新用户首次进入</h2>
              <p>这是 Gateway 统一管理后台。未登录时默认跳转到这里，登录后自动进入控制台主页。</p>
            </article>
            <article className="onboarding-step">
              <h2>如何先拿 Key</h2>
              <p>1) 首次体验：先点“演示 Key”然后登录；2) 正式接入：联系管理员发放 Key；3) 管理员可在“访问密钥”里创建并分发给业务方。</p>
            </article>
            <article className="onboarding-step">
              <h2>如何切换 admin</h2>
              <p>登录页用管理员身份凭证（管理员 JWT / 管理员 Key）登录后，顶部“当前凭证”会显示角色是“管理员”。普通用户没有管理员代建权限。</p>
            </article>
          </div>
          <div className="auth-notice">
            <p>
              <strong>管理员注意：</strong>若你本地是空库，可先执行
              <code>docker compose exec gateway python scripts/setup_test_key.py</code>
              生成演示密钥 <code>{demoGatewayKey}</code>，用于本地自测。
            </p>
          </div>
          <form className="auth-form" onSubmit={handleLogin}>
            <label>
              凭证
              <input
                value={credentialInput}
                onChange={(event) => setCredentialInput(event.target.value)}
                type="password"
                placeholder="lgw_... 或 JWT"
              />
            </label>
            <div className="auth-actions">
              <button className="primary-action" type="submit" disabled={authLoading || !credentialInput.trim()}>
                {authLoading ? "登录中..." : "登 录"}
              </button>
              <button type="button" onClick={useDemoToken}>演示 Key</button>
            </div>
          </form>
          {authMessage && (
            <div className={`status-banner ${authMessageKind}`}>{authMessage}</div>
          )}
          <div className="quick-links">
            <a href="/docs"><BookOpen size={14} /> 接口文档</a>
            <a href="/api/config"><Braces size={14} /> 配置接口</a>
            <a href="https://github.com/"><Github size={14} /> GitHub</a>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="eyebrow"><ShieldCheck size={15} /> 开源 LLM Gateway</div>
          <h1>LLM Gateway 管理后台</h1>
          <p>统一入口、模型治理、成本观测、路由解释和调用验证。</p>
          <div className="quick-links">
            <a href="/docs"><BookOpen size={14} /> 接口文档</a>
            <a href="https://github.com/"><Github size={14} /> GitHub</a>
            <a href="/api/config"><Braces size={14} /> 配置接口</a>
          </div>
        </div>
        <div className="token-field">
          <span>当前凭证</span>
          <strong>{identity?.auth_type === "jwt" ? "JWT" : "Gateway API Key"}</strong>
          <div className={`auth-indicator ok`}>{`用户：${identity?.user_id || "-"} / 角色：${identity?.role === "admin" ? "管理员" : "普通用户"}`}</div>
          <button type="button" onClick={logout}><LogOut size={15} />退出登录</button>
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <div className="project-card">
            <div className="project-mark">LG</div>
            <div>
              <strong>LLM Gateway</strong>
              <span>v0.1.0 开源版</span>
            </div>
          </div>
          {tabGroups.map((group) => (
            <div key={group}>
              <div className="nav-section">{group}</div>
              <nav aria-label={`${group}导航`}>
                {tabs.filter((tab) => tab.group === group).map((tab) => (
                  <button key={tab.id} className={active === tab.id ? "active" : ""} onClick={() => setActive(tab.id)}>
                    {tab.icon}
                    {tab.label}
                  </button>
                ))}
              </nav>
            </div>
          ))}
          <div className="sidebar-footer">
            <span className={`status-dot ${ready.status === "ready" ? "ok-bg" : "warn-bg"}`} />
            <span>{statusText(ready.status)}</span>
          </div>
        </aside>

        <section className="content">
          {active === "overview" && (
            <section className="panel">
              <PanelHead title="运行概览" desc="网关运行状态、用量和依赖健康。" action={() => runAction(refreshOverview)} />
              <div className="health-strip">
                <StatusPill label="网关" ok />
                <StatusPill label="数据库" ok={ready.checks?.db} />
                <StatusPill label="Redis" ok={ready.checks?.redis} />
                <StatusPill label="访问凭证" ok={Boolean(token)} />
              </div>
              <div className="stats">
                <div><span>请求数</span><strong>{formatNumber(metrics.total_requests)}</strong></div>
                <div><span>Token 用量</span><strong>{formatNumber(metrics.total_tokens)}</strong></div>
                <div><span>预估成本</span><strong>{Number(metrics.total_cost_estimate ?? 0).toFixed(4)}</strong></div>
                <div><span>平均延迟</span><strong>{Number(metrics.avg_latency_ms ?? 0).toFixed(1)}ms</strong></div>
              </div>
              <div className="guide-grid">
                <InfoTile title="访问凭证" value={token.trim() ? "已填写" : "待填写"} desc="概览页可无鉴权查看依赖健康；模型、密钥、用量和供应商接口需要 Gateway API Key。" tone={token.trim() ? "ok" : "warn"} />
                <InfoTile title="控制面入口" value="/llm_gateway_admin" desc="前后端同端口部署，根路径会自动跳转到管理后台。" />
                <InfoTile title="数据面入口" value="/api/runs" desc="业务系统通过统一接口调用模型，路由结果会记录用量和成本。" />
              </div>
            </section>
          )}

          {active === "models" && (
            <section className="panel">
              <PanelHead title="模型与路由" desc="模型池、tier、连接数、错误数和熔断状态。" action={() => runAction(refreshModels)} />
              <div className="table-wrap">
                <table>
                  <thead><tr><th>模型</th><th>分层</th><th>健康状态</th><th>连接数</th><th>错误数</th><th>熔断到期</th></tr></thead>
                  <tbody>
                    {Object.entries(models).map(([name, info]) => (
                      <tr key={name}>
                        <td><code>{name}</code></td>
                        <td><span className={`pill ${info.tier}`}>{info.tier}</span></td>
                        <td><span className={`pill ${info.healthy ? "healthy" : "down"}`}>{info.healthy ? "健康" : "异常"}</span></td>
                        <td>{info.connections}</td>
                        <td>{info.errors}</td>
                        <td>{info.circuit_open_until || 0}</td>
                      </tr>
                    ))}
                    {Object.keys(models).length === 0 && (
                      <tr>
                        <td colSpan={6} className="empty-cell">
                          {modelEmptyText(token, outputKind, output)}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {active === "keys" && (
            <section className="panel">
              <PanelHead title="访问密钥" desc="Gateway 访问凭证。这里不是供应商 API Key。" action={() => runAction(refreshKeys)} />
              <form className="grid-form" onSubmit={createKey}>
                <label>
                  创建类型
                  <select value={createMode} onChange={(event) => setCreateMode(event.target.value as "self" | "admin")}>
                    <option value="self">普通创建（当前登录用户）</option>
                    <option value="admin" disabled={!isAdmin}>管理员代建</option>
                  </select>
                </label>
                <label className="notice-note">
                  {createMode === "self"
                    ? "说明：仅创建归属当前登录用户的 Key，不需要填写 归属用户ID。"
                    : "说明：管理员模式会把该 Key 归属到你填写的用户ID；如果当前凭证非管理员角色，将返回无权限。"}
                </label>
                <label>名称<input name="name" defaultValue="default" /></label>
                <label>月度 Quota<input name="quota" type="number" min="0" defaultValue="0" /></label>
                <label>QPS<input name="rate_limit" type="number" min="1" defaultValue="10" /></label>
                <label>允许分层<input name="allowed_tiers" defaultValue="cheap,expensive" /></label>
                {createMode === "admin" && (
                  <label>
                    归属用户ID（管理员代建）
                    <input name="owner_user_id" placeholder="目标用户ID（例如 user-id-xxx）" />
                  </label>
                )}
                <label>外部用户唯一ID<input name="external_user_id" placeholder="可留空或填业务系统用户/工号" /></label>
                <button type="submit"><KeyRound size={15} />创建</button>
              </form>
              {output && (output.startsWith("已复制") || output.includes("旧数据")) && (
                <div className={`status-banner ${outputKind}`}>{output}</div>
              )}
              <div className="table-wrap">
                <table>
                  <thead><tr><th>ID</th><th>名称</th><th>归属用户ID</th><th>外部用户ID</th><th>API Key</th><th>月度 Quota</th><th>QPS</th><th>允许分层</th><th>创建时间</th><th>接入包</th><th></th></tr></thead>
                  <tbody>
                    {keys.map((key) => (
                      <tr key={key.id}>
                        <td><code>{key.id}</code></td>
                        <td>{key.name}</td>
                        <td>{key.owner_user_id || "-"}</td>
                        <td>{key.external_user_id || "-"}</td>
                        <td><code>{key.key || "仅新 Key 可见"}</code></td>
                        <td>{key.quota_monthly}</td>
                        <td>{key.rate_limit_rps}</td>
                        <td><span className="pill neutral">{key.allowed_tiers}</span></td>
                        <td>{key.created_at}</td>
                        <td><button onClick={() => copyIntegrationPackage(key)}>复制</button></td>
                        <td><button onClick={() => deleteKey(key.id)}>删除</button></td>
                      </tr>
                    ))}
                    {keys.length === 0 && (
                      <tr>
                        <td colSpan={11} className="empty-cell">
                          暂无访问密钥。填写名称、Quota、QPS 和允许分层后点击“创建”。
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {active === "usage" && (
            <section className="panel">
              <PanelHead title="用量账单" desc="用量按 API Key、用户、模型和 tier 落库，可追踪测试与生产消耗。" action={() => runAction(refreshUsage)} />
              <div className="stats">
                <div><span>请求数</span><strong>{formatNumber(usage?.summary.total_requests)}</strong></div>
                <div><span>Token 用量</span><strong>{formatNumber(usage?.summary.total_tokens)}</strong></div>
                <div><span>预估成本</span><strong>{Number(usage?.summary.total_cost_estimate ?? 0).toFixed(4)}</strong></div>
                <div><span>平均延迟</span><strong>{Number(usage?.summary.avg_latency_ms ?? 0).toFixed(1)}ms</strong></div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>时间</th><th>密钥</th><th>用户</th><th>模型</th><th>分层</th><th>Token</th><th>成本</th><th>延迟</th></tr></thead>
                  <tbody>
                    {(usage?.items || []).map((item) => (
                      <tr key={item.id}>
                        <td>{item.timestamp}</td>
                        <td><code>{item.api_key_id || "-"}</code></td>
                        <td>{item.user_id}</td>
                        <td><code>{item.model_name}</code></td>
                        <td><span className={`pill ${item.tier}`}>{item.tier}</span></td>
                        <td>{item.total_tokens}</td>
                        <td>{Number(item.cost_estimate || 0).toFixed(4)}</td>
                        <td>{Number(item.latency_ms || 0).toFixed(1)}ms</td>
                      </tr>
                    ))}
                    {(usage?.items || []).length === 0 && (
                      <tr>
                        <td colSpan={8} className="empty-cell">
                          暂无用量记录。通过“测试控制台”或业务 API 发送请求后，这里会按 Key、模型和 tier 展示消耗。
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {active === "traces" && (
            <section className="panel">
              <PanelHead title="调用追踪" desc="按 request_id 串联接入层、路由层和执行层，查看 fallback、缓存和错误。" action={() => runAction(refreshTraces)} />
              <div className="table-wrap">
                <table>
                  <thead><tr><th>时间</th><th>Request ID</th><th>状态</th><th>Provider</th><th>模型</th><th>路由</th><th>Token</th><th>延迟</th><th>路径</th></tr></thead>
                  <tbody>
                    {(traces?.items || []).map((trace) => (
                      <tr key={trace.id}>
                        <td>{trace.created_at}</td>
                        <td><code>{trace.request_id}</code></td>
                        <td><span className={`pill ${trace.status === "success" ? "healthy" : "down"}`}>{trace.status === "success" ? "成功" : "失败"}</span></td>
                        <td>{trace.provider || "-"}</td>
                        <td><code>{trace.model_name || "-"}</code></td>
                        <td>{trace.route_source || "-"}{trace.fallback_used ? " · fallback" : ""}{trace.cache_hit ? " · cache" : ""}</td>
                        <td>{trace.total_tokens}</td>
                        <td>{Number(trace.latency_ms || 0).toFixed(1)}ms</td>
                        <td>{trace.attempted_models.join(" -> ") || "-"}</td>
                      </tr>
                    ))}
                    {(traces?.items || []).length === 0 && (
                      <tr><td colSpan={9} className="empty-cell">暂无调用 Trace。通过测试控制台或业务 API 发起请求后，这里会展示完整路由路径。</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {active === "sla" && (
            <section className="panel">
              <PanelHead title="供应商 SLA 看板" desc="按 Provider 聚合成功率、错误数、延迟分位、fallback 和缓存命中。" action={() => runAction(refreshSla)} />
              <div className="sla-grid">
                {(sla?.providers || []).map((provider) => (
                  <article className="sla-card" key={provider.provider}>
                    <div className="sla-head">
                      <strong>{provider.provider}</strong>
                      <span className={`pill ${provider.success_rate >= 0.95 ? "healthy" : provider.success_rate >= 0.8 ? "neutral" : "down"}`}>{(provider.success_rate * 100).toFixed(1)}%</span>
                    </div>
                    <div className="sla-metrics">
                      <div><span>请求</span><strong>{provider.total_requests}</strong></div>
                      <div><span>错误</span><strong>{provider.error_count}</strong></div>
                      <div><span>P95</span><strong>{provider.p95_latency_ms.toFixed(1)}ms</strong></div>
                      <div><span>Fallback</span><strong>{provider.fallback_count}</strong></div>
                    </div>
                    <div className="sla-bar"><span style={{ width: `${Math.min(100, provider.success_rate * 100)}%` }} /></div>
                    <p>平均 {provider.avg_latency_ms.toFixed(1)}ms，P50 {provider.p50_latency_ms.toFixed(1)}ms，缓存命中 {provider.cache_hit_count} 次。</p>
                  </article>
                ))}
                {(sla?.providers || []).length === 0 && <div className="empty-box">暂无 SLA 数据。产生调用 Trace 后自动聚合。</div>}
              </div>
            </section>
          )}

          {active === "routing" && (
            <section className="panel">
              <PanelHead title="路由规则" desc="当前规则只读展示。配置编辑需要审计、校验和回滚。" action={() => runAction(refreshModels)} />
              <pre className="output">{config ? JSON.stringify((config as { gateway?: { rules?: unknown } }).gateway?.rules || [], null, 2) : "点击加载配置查看规则。"}</pre>
            </section>
          )}

          {active === "policies" && (
            <section className="panel">
              <div className="panel-head">
                <div><h2>策略中心</h2><p>查看当前策略快照，生成可审计草案。草案不会直接改线上 YAML。</p></div>
                <div className="panel-actions">
                  <button onClick={() => runAction(refreshPolicies)}><RefreshCw size={15} />刷新</button>
                  <button onClick={createPolicyDraft}><SlidersHorizontal size={15} />生成草案</button>
                </div>
              </div>
              <div className="policy-layout">
                <div>
                  <h3>Provider 运行配置</h3>
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Provider</th><th>模型数</th><th>模型 / 并发 / 权重</th></tr></thead>
                      <tbody>
                        {Object.entries(policies?.current.providers || {}).map(([name, provider]) => (
                          <tr key={name}>
                            <td><strong>{name}</strong></td>
                            <td>{provider.models.length}</td>
                            <td>{provider.models.map((model) => `${model.name} · ${model.max_concurrent ?? "-"} 并发 · weight ${model.weight}`).join(" / ") || "暂无绑定模型"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                <div>
                  <h3>策略草案</h3>
                  <div className="draft-list">
                    {(policies?.drafts || []).map((draft) => (
                      <article className="draft-item" key={draft.id}>
                        <div><strong>{draft.name}</strong><span>{draft.created_at}</span></div>
                        <span className={`pill ${draft.status === "applied" ? "healthy" : "neutral"}`}>{draft.status}</span>
                      </article>
                    ))}
                    {(policies?.drafts || []).length === 0 && <div className="empty-box">暂无草案。点击“生成草案”会把当前策略快照保存到数据库并写入审计日志。</div>}
                  </div>
                </div>
              </div>
              <details className="config-details">
                <summary>当前策略快照 JSON</summary>
                <pre className="output">{policies ? JSON.stringify(policies.current, null, 2) : "点击刷新加载策略。"}</pre>
              </details>
            </section>
          )}

          {active === "audit" && (
            <section className="panel">
              <PanelHead title="审计日志" desc="记录密钥、策略等管理操作，便于追责和变更回溯。" action={() => runAction(refreshAudit)} />
              <div className="table-wrap">
                <table>
                  <thead><tr><th>时间</th><th>动作</th><th>操作者</th><th>目标</th><th>IP</th><th>详情</th></tr></thead>
                  <tbody>
                    {(audit?.items || []).map((item) => (
                      <tr key={item.id}>
                        <td>{item.created_at}</td>
                        <td><code>{item.action}</code></td>
                        <td>{item.actor_user_id || "-"}</td>
                        <td>{item.target_type || "-"} / <code>{item.target_id || "-"}</code></td>
                        <td>{item.ip_address || "-"}</td>
                        <td><code>{JSON.stringify(item.detail)}</code></td>
                      </tr>
                    ))}
                    {(audit?.items || []).length === 0 && <tr><td colSpan={6} className="empty-cell">暂无审计记录。创建 Key 或生成策略草案后会自动记录。</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {active === "console" && (
            <section className="panel">
              <div className="panel-head">
                <div><h2>测试控制台</h2><p>像 API playground 一样验证路由、模型响应和错误归因。</p></div>
              </div>
              <div className={`status-banner ${outputKind}`}>
                {busy ? "正在调用网关并等待模型响应..." : consoleStatus(outputKind, output)}
              </div>
              <div className="playground">
                <form className="console-form" onSubmit={sendRun}>
                  <label>消息<textarea name="message" rows={8} defaultValue="什么是 LLM Gateway？" /></label>
                  <div className="console-picker">
                    <div className="console-picker-head">
                      <div>
                        <strong>模型选择</strong>
                        <span>{selectedModel ? `已选择 ${selectedModel}` : "未指定模型时由路由层自动选择"}</span>
                      </div>
                      <button type="button" onClick={() => runAction(refreshModels)}><RefreshCw size={15} />刷新模型</button>
                    </div>
                    <div className="model-filters">
                      <label>筛选分层<select value={consoleTierFilter} onChange={(event) => setConsoleTierFilter(event.target.value)}><option value="all">全部</option><option value="cheap">cheap</option><option value="expensive">expensive</option></select></label>
                      <label>健康状态<select value={consoleHealthFilter} onChange={(event) => setConsoleHealthFilter(event.target.value)}><option value="healthy">仅健康</option><option value="all">全部</option><option value="down">仅异常</option></select></label>
                      <label>搜索模型<input value={consoleSearch} onChange={(event) => setConsoleSearch(event.target.value)} placeholder="模型名 / provider" /></label>
                    </div>
                    <div className="model-choice-list">
                      <button type="button" className={!selectedModel ? "selected" : ""} onClick={() => setSelectedModel("")}>
                        <strong>自动路由</strong>
                        <span>按规则、tier、健康状态选择模型</span>
                      </button>
                      {consoleModels.map(([name, info]) => (
                        <button type="button" key={name} className={selectedModel === name ? "selected" : ""} onClick={() => setSelectedModel(name)}>
                          <strong>{name}</strong>
                          <span>{info.provider} · {info.tier} · {info.healthy ? "健康" : "异常"}</span>
                        </button>
                      ))}
                      {consoleModels.length === 0 && <div className="empty-box">没有符合筛选条件的模型。请调整筛选条件或刷新模型池。</div>}
                    </div>
                  </div>
                  <div className="grid-form compact">
                    <label>请求分层<select name="model_tier" defaultValue="auto"><option>auto</option><option>cheap</option><option>expensive</option></select></label>
                    <label>温度<input name="temperature" type="number" min="0" max="2" step="0.1" defaultValue="0" /></label>
                    <label>最大 Token<input name="max_tokens" type="number" min="1" defaultValue="512" /></label>
                  </div>
                  <button className="primary-action" type="submit" disabled={busy}><Play size={15} />{busy ? "请求中..." : "发送测试请求"}</button>
                </form>
                <div className="timeline">
                  <div className={busy ? "active" : ""}><CircleDot size={14} /> 鉴权</div>
                  <div className={busy ? "active" : ""}><CircleDot size={14} /> 路由</div>
                  <div className={busy ? "active" : ""}><CircleDot size={14} /> 供应商</div>
                  <div className={outputKind === "success" ? "done" : outputKind === "error" ? "failed" : ""}><CircleDot size={14} /> 响应</div>
                </div>
              </div>
              {output && <pre className={`output ${outputKind}`}>{output}</pre>}
            </section>
          )}

          {active === "providers" && (
            <section className="panel">
              <PanelHead title="供应商配置" desc="Provider API Key 只应存在服务端；这里展示脱敏后的接入状态。" action={() => runAction(refreshProviders)} />
              <div className="provider-hero">
                <div>
                  <span className="section-kicker">Provider Registry</span>
                  <h2>供应商接入状态</h2>
                  <p>按服务端配置、环境变量和模型绑定关系展示。这里不会显示 Provider API Key 明文。</p>
                </div>
                <div className="provider-summary">
                  <SummaryMetric label="可用" value={providerCount(providers, "ready")} tone="ok" />
                  <SummaryMetric label="缺 Key" value={providerCount(providers, "missing_key")} tone="bad" />
                  <SummaryMetric label="未使用" value={providerCount(providers, "unused")} tone="neutral" />
                </div>
              </div>
              <div className="setup-callout">
                <FileSliders size={18} />
                <div>
                  <strong>服务端配置方式</strong>
                  <p>在 `.env` 中填写 `DEEPSEEK_API_KEY`、`KIMI_API_KEY`、`KIMI_CODE_API_KEY`、`LINGYA_API_KEY` 等变量，然后重启网关。Kimi Code 会员 Key 使用 `KIMI_CODE_API_KEY` 和 `kimi-for-coding`。</p>
                </div>
              </div>
              <div className="provider-list">
                {Object.entries(providers?.providers || {}).map(([name, provider]) => (
                  <article className="provider-card" key={name}>
                    <div className={`provider-rail ${providerStatusClass(provider.status)}`} />
                    <div className="provider-main">
                      <div className="provider-card-head">
                        <div className="provider-title">
                          <div className="provider-avatar">{providerInitials(name)}</div>
                          <div>
                            <strong>{name}</strong>
                            <span>{provider.base_url || "未配置 base_url"}</span>
                          </div>
                        </div>
                        <span className={`provider-status ${providerStatusClass(provider.status)}`}>
                          {providerStatusIcon(provider.status)}
                          {providerStatusText(provider.status)}
                        </span>
                      </div>
                      <dl>
                        <div><dt>环境变量</dt><dd><code>{providerEnvName(name)}</code></dd></div>
                        <div><dt>Key 来源</dt><dd>{provider.env_key_configured ? "环境变量" : provider.config_key_count > 0 ? "YAML" : "未配置"}</dd></div>
                        <div><dt>Key 数量</dt><dd>{provider.configured_key_count}</dd></div>
                        <div><dt>绑定模型</dt><dd>{provider.models.length}</dd></div>
                      </dl>
                      <div className="provider-models">
                        {provider.models.length ? provider.models.map((model) => <code key={model}>{model}</code>) : <span>暂无模型使用该供应商</span>}
                      </div>
                      <div className={`provider-next ${providerStatusClass(provider.status)}`}>
                        {providerNextStep(name, provider.status)}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
              {!providers && <div className="empty-box">点击刷新或填写 Gateway API Key 后查看供应商接入状态。</div>}
              <details className="config-details">
                <summary>查看脱敏原始配置</summary>
                <pre className="output">{config ? JSON.stringify(config, null, 2) : "暂无配置数据。"}</pre>
              </details>
            </section>
          )}

          {active !== "console" && outputKind === "error" && output && <pre className={`output ${outputKind}`}>{output}</pre>}
        </section>
      </main>
    </div>
  );
}

function InfoTile({ title, value, desc, tone = "neutral" }: { title: string; value: string; desc: string; tone?: "ok" | "warn" | "neutral" }) {
  return (
    <article className={`info-tile ${tone}`}>
      <span>{title}</span>
      <strong>{value}</strong>
      <p>{desc}</p>
    </article>
  );
}

function SummaryMetric({ label, value, tone }: { label: string; value: number; tone: "ok" | "bad" | "neutral" }) {
  return (
    <div className={`summary-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PanelHead({ title, desc, action }: { title: string; desc: string; action: () => void }) {
  return (
    <div className="panel-head">
      <div><h2>{title}</h2><p>{desc}</p></div>
      <button onClick={action}><RefreshCw size={15} />刷新</button>
    </div>
  );
}

function StatusPill({ label, ok }: { label: string; ok?: boolean }) {
  return <span className={`health-pill ${ok ? "ok" : "warn"}`}>{label}: {ok ? "正常" : "降级"}</span>;
}

function statusText(status?: string): string {
  if (status === "ready") {
    return "服务正常";
  }
  if (status === "degraded") {
    return "服务降级";
  }
  return "状态未知";
}

function providerStatusClass(status: string): string {
  if (status === "ready") {
    return "healthy";
  }
  if (status === "unused") {
    return "neutral";
  }
  return "down";
}

function providerStatusText(status: string): string {
  if (status === "ready") {
    return "已配置";
  }
  if (status === "unused") {
    return "未使用";
  }
  return "缺少 Key";
}

function providerStatusIcon(status: string) {
  if (status === "ready") {
    return <CheckCircle2 size={15} />;
  }
  if (status === "unused") {
    return <PackageOpen size={15} />;
  }
  return <AlertTriangle size={15} />;
}

function providerCount(providers: ProviderHealthResponse | null, status: string): number {
  return Object.values(providers?.providers || {}).filter((provider) => provider.status === status).length;
}

function providerEnvName(name: string): string {
  return `${name.toUpperCase()}_API_KEY`;
}

function providerInitials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

function providerNextStep(name: string, status: string): string {
  if (status === "ready") {
    return "已绑定模型且检测到服务端 Key，请到测试控制台验证实际调用。";
  }
  if (status === "unused") {
    return "当前没有模型绑定到该供应商；如需启用，请在 config/models.yaml 中添加模型。";
  }
  return `缺少服务端 Key：请在 .env 中设置 ${providerEnvName(name)} 后重启网关。`;
}

function buildIntegrationPackage(baseUrl: string, key: ApiKeyInfo): string {
  const apiKey = key.key || "";
  return [
    `LLM Gateway 接入信息 - ${key.name}`,
    "",
    `Base URL: ${baseUrl}`,
    `Chat API: ${baseUrl}/api/runs`,
    `Gateway API Key: ${apiKey}`,
    `Key ID: ${key.id}`,
    `归属用户ID: ${key.owner_user_id || "-"}`,
    `外部用户ID: ${key.external_user_id || "-"}`,
    `允许分层: ${key.allowed_tiers}`,
    `QPS: ${key.rate_limit_rps}`,
    `月度 Quota: ${key.quota_monthly || "无限制"}`,
    "",
    "curl 示例:",
    `curl -X POST ${baseUrl}/api/runs \\`,
    `  -H "Authorization: Bearer ${apiKey}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"messages":[{"role":"user","content":"你好，测试一下 LLM Gateway"}],"model_tier":"auto","stream":false}'`,
  ].join("\n");
}

function filterConsoleModels(
  models: Record<string, ModelInfo>,
  tier: string,
  health: string,
  search: string,
): Array<[string, ModelInfo]> {
  const q = search.trim().toLowerCase();
  return Object.entries(models).filter(([name, info]) => {
    if (tier !== "all" && info.tier !== tier) {
      return false;
    }
    if (health === "healthy" && !info.healthy) {
      return false;
    }
    if (health === "down" && info.healthy) {
      return false;
    }
    if (q && !`${name} ${info.provider} ${info.tier}`.toLowerCase().includes(q)) {
      return false;
    }
    return true;
  });
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function formatError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  if (raw.includes("402 Payment Required") && raw.includes("deepseek")) {
    return "DeepSeek 返回 402 Payment Required：下游 DeepSeek 账户余额、额度或计费状态不可用。请检查 DEEPSEEK_API_KEY 对应账户的余额/充值/计费权限。\\n\\n原始错误：\\n" + raw;
  }
  if (raw.includes("provider_unauthorized") || raw.includes("401 Unauthorized") || raw.includes("Invalid Authentication")) {
    return "下游模型供应商认证失败：当前供应商 API Key 无效、过期、填错平台，或复制时包含多余空格。Kimi 请在服务器 `.env` 中检查 `KIMI_API_KEY` 是否为 Moonshot API 平台创建的有效 Key，保存后重启 docker compose。\\n\\n原始错误：\\n" + raw;
  }
  if (raw.includes("403 Forbidden")) {
    return "下游模型供应商返回 403 Forbidden：API Key 没有调用该模型或该供应商接口的权限。\\n\\n原始错误：\\n" + raw;
  }
  if (raw.includes("429 Too Many Requests")) {
    return "下游模型供应商返回 429 Too Many Requests：供应商侧限流或额度过载。稍后重试，或切换模型。\\n\\n原始错误：\\n" + raw;
  }
  if (raw.includes("Invalid credentials")) {
    return `Gateway API Key 无效：当前浏览器可能保存了旧 Key，或该凭证不在当前 Compose 数据库内。请重新登录有效凭证，或在登录页点“演示 Key”试用。\\n\\n原始错误：\\n${raw}`;
  }
  return raw;
}

function formatAuthError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  if (raw.includes("Missing authorization header")) {
    return "请先输入 Gateway API Key 或 JWT。";
  }
  if (raw.includes("Invalid credentials")) {
    return `凭证校验失败：该凭证无效或已失效。你可以在登录页使用演示 Key (${demoGatewayKey}) 先体验，或联系管理员重新发放。\\n\\n原始错误：\\n${raw}`;
  }
  return raw;
}

function consoleStatus(kind: OutputKind, output: string): string {
  if (kind === "success") {
    return "请求完成，结果见下方输出。";
  }
  if (kind === "error") {
    return output.split("\\n")[0] || "请求失败，详情见下方输出。";
  }
  return "登录并选择模型后，发送测试请求。";
}

function modelEmptyText(token: string, outputKind: OutputKind, output: string): string {
  if (!token.trim()) {
    return "请先填写 Gateway API Key / JWT，模型池接口需要鉴权。";
  }
  if (outputKind === "error" && output.includes("Gateway API Key 无效")) {
    return `当前 Gateway API Key 无效。请登录页点“演示 Key”使用 ${demoGatewayKey}，或重新创建访问密钥。`;
  }
  return "正在加载或暂无模型。点击刷新按钮可重新获取。";
}
