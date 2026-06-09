const tokenInput = document.querySelector("#token");
const panels = document.querySelectorAll(".panel");
const tabs = document.querySelectorAll(".tab");

tokenInput.value = localStorage.getItem("llm_gateway_token") || "";
tokenInput.addEventListener("input", () => {
  localStorage.setItem("llm_gateway_token", tokenInput.value);
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((item) => item.classList.remove("active"));
    panels.forEach((panel) => panel.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`#${tab.dataset.panel}`).classList.add("active");
  });
});

function headers() {
  return {
    Authorization: `Bearer ${tokenInput.value}`,
    "Content-Type": "application/json",
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...headers(),
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = text;
  }
  if (!response.ok) {
    throw new Error(JSON.stringify(data, null, 2));
  }
  return data;
}

function write(id, value) {
  document.querySelector(id).textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

async function refreshOverview() {
  const metrics = await api("/api/metrics");
  document.querySelector("#stat-requests").textContent = metrics.total_requests ?? 0;
  document.querySelector("#stat-tokens").textContent = metrics.total_tokens ?? 0;
  document.querySelector("#stat-cost").textContent = Number(metrics.total_cost_estimate ?? 0).toFixed(4);
  document.querySelector("#stat-latency").textContent = `${Number(metrics.avg_latency_ms ?? 0).toFixed(1)}ms`;
  write("#overview-output", metrics);
}

async function refreshKeys() {
  const keys = await api("/api/auth/keys");
  const body = document.querySelector("#keys-body");
  body.innerHTML = "";
  keys.forEach((key) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${key.id}</td>
      <td>${key.name}</td>
      <td>${key.quota_monthly}</td>
      <td>${key.rate_limit_rps}</td>
      <td><span class="pill">${key.allowed_tiers}</span></td>
      <td>${key.created_at}</td>
      <td><button data-delete="${key.id}">删除</button></td>
    `;
    body.appendChild(row);
  });
  body.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/api/auth/keys/${button.dataset.delete}`, { method: "DELETE" });
      await refreshKeys();
    });
  });
  write("#keys-output", keys);
}

async function refreshModels() {
  const models = await api("/api/models");
  const config = await api("/api/config");
  const body = document.querySelector("#models-body");
  body.innerHTML = "";
  Object.entries(models).forEach(([name, info]) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${name}</td>
      <td><span class="pill">${info.tier}</span></td>
      <td class="${info.healthy ? "ok" : "bad"}">${info.healthy}</td>
      <td>${info.connections}</td>
      <td>${info.errors}</td>
      <td>${info.circuit_open_until || 0}</td>
    `;
    body.appendChild(row);
  });
  write("#config-output", config);
}

document.querySelector("#refresh-overview").addEventListener("click", () => refreshOverview().catch((err) => write("#overview-output", err.message)));
document.querySelector("#refresh-keys").addEventListener("click", () => refreshKeys().catch((err) => write("#keys-output", err.message)));
document.querySelector("#refresh-models").addEventListener("click", () => refreshModels().catch((err) => write("#config-output", err.message)));

document.querySelector("#key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const params = new URLSearchParams(form);
  try {
    const created = await api(`/api/auth/keys?${params.toString()}`, { method: "POST" });
    write("#keys-output", created);
    await refreshKeys();
  } catch (err) {
    write("#keys-output", err.message);
  }
});

document.querySelector("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const model = form.get("model").trim();
  const payload = {
    messages: [{ role: "user", content: form.get("message") }],
    model_tier: form.get("model_tier"),
    temperature: Number(form.get("temperature")),
    max_tokens: Number(form.get("max_tokens")),
    stream: false,
  };
  if (model) {
    payload.model = model;
  }
  try {
    const result = await api("/api/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    write("#run-output", result);
    await refreshOverview();
  } catch (err) {
    write("#run-output", err.message);
  }
});
