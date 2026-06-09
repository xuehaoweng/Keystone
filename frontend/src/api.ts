export type MetricsSummary = {
  total_requests?: number;
  total_tokens?: number;
  total_cost_estimate?: number;
  avg_latency_ms?: number;
};

export type AuthIdentity = {
  user_id: string;
  role: string;
  auth_type: "api_key" | "jwt";
};

export type ApiKeyInfo = {
  id: string;
  key?: string | null;
  owner_user_id?: string;
  external_user_id?: string | null;
  name: string;
  quota_monthly: number;
  rate_limit_rps: number;
  allowed_tiers: string;
  created_at: string;
};

export type ModelInfo = {
  provider: string;
  tier: string;
  healthy: boolean;
  connections: number;
  errors: number;
  circuit_open_until?: number;
};

export type RunResponse = {
  id: string;
  model: string;
  tier: string;
  content: string;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  finish_reason: string;
  route?: {
    source: string;
    rule_name?: string | null;
    requested_tier: string;
    resolved_tier: string;
    attempted_models: string[];
    fallback_used: boolean;
    cache_hit: boolean;
  } | null;
};

export type UsageResponse = {
  items: Array<{
    id: number;
    api_key_id: string | null;
    user_id: string;
    model_name: string;
    tier: string;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    latency_ms: number;
    route_path: string;
    cost_estimate: number;
    timestamp: string;
  }>;
  summary: MetricsSummary;
  limit: number;
  offset: number;
};

export type ProviderHealthResponse = {
  providers: Record<string, {
    base_url?: string;
    configured_key_count: number;
    env_key_configured: boolean;
    config_key_count: number;
    models: string[];
    status: string;
  }>;
};

export type TraceResponse = {
  items: Array<{
    id: number;
    request_id: string;
    api_key_id: string | null;
    user_id: string | null;
    provider: string | null;
    model_name: string | null;
    tier: string | null;
    status: string;
    route_source: string | null;
    requested_tier: string | null;
    resolved_tier: string | null;
    attempted_models: string[];
    fallback_used: boolean;
    cache_hit: boolean;
    latency_ms: number;
    error_type: string | null;
    error_detail: string | null;
    total_tokens: number;
    created_at: string;
  }>;
};

export type ProviderSlaResponse = {
  providers: Array<{
    provider: string;
    total_requests: number;
    success_count: number;
    error_count: number;
    success_rate: number;
    avg_latency_ms: number;
    p50_latency_ms: number;
    p95_latency_ms: number;
    fallback_count: number;
    cache_hit_count: number;
    total_tokens: number;
  }>;
};

export type AuditResponse = {
  items: Array<{
    id: number;
    actor_user_id: string | null;
    api_key_id: string | null;
    action: string;
    target_type: string | null;
    target_id: string | null;
    detail: Record<string, unknown>;
    ip_address: string | null;
    created_at: string;
  }>;
};

export type PoliciesResponse = {
  current: {
    gateway: Record<string, unknown>;
    providers: Record<string, {
      base_url?: string;
      models: Array<{
        name: string;
        tier: string;
        weight: number;
        max_concurrent?: number;
        rate_limit?: number;
      }>;
    }>;
  };
  drafts: Array<{
    id: number;
    name: string;
    content: Record<string, unknown>;
    status: string;
    created_by: string | null;
    created_at: string;
    updated_at: string;
  }>;
};

export class ApiClient {
  constructor(private readonly token: string) {}

  private headers(): HeadersInit {
    return {
      Authorization: `Bearer ${this.token}`,
      "Content-Type": "application/json"
    };
  }

  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(path, {
      ...init,
      headers: {
        ...this.headers(),
        ...(init.headers || {})
      }
    });
    const text = await response.text();
    const contentType = response.headers.get("content-type") || "";
    const normalizedBody = text ? text.trim() : "";
    let data: any = {};

    if (!normalizedBody) {
      data = {};
    } else if (contentType.includes("application/json") || contentType.includes("application/problem+json")) {
      try {
        data = JSON.parse(normalizedBody);
      } catch (_err) {
        data = { detail: `网关返回了无效 JSON：${normalizedBody.slice(0, 200)}...` };
      }
    } else if (normalizedBody.startsWith("<!doctype") || normalizedBody.startsWith("<!DOCTYPE")) {
      data = {
        detail: "网关返回了 HTML（通常是前端页面）。请确认你访问的是网关入口（含 /api 代理），不要直接访问前端静态端口。",
      };
    } else {
      data = { detail: normalizedBody.slice(0, 300) };
    }

    if (!response.ok) {
      const parsed = JSON.stringify(data, null, 2);
      if (response.status === 403 && parsed.includes("Invalid credentials")) {
        data = {
          detail: "凭证无效或所属实例不一致：当前 token 可能在其他容器/数据库中创建，或签名密钥不匹配。",
        };
      }
      throw new Error(JSON.stringify(data, null, 2));
    }
    return data as T;
  }
}
