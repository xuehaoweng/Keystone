# Quickstart

## One-Command Start (推荐)

```bash
./scripts/quickstart.sh
```

该脚本会检查环境、构建镜像、启动服务、创建演示 Key，并打印访问链接。全程无需手动编辑 `.env`。

> 如果 `bash` 不可用，请继续往下看「手动部署」步骤。

## 手动部署

```bash
cp .env.example .env
# 编辑 .env，至少填写一个供应商 API Key
docker compose up -d --build
```

打开：

```text
http://localhost:8000/
```

根路径会跳转到 `/llm_gateway_admin`。Docker 镜像会在构建阶段打包 React 管理后台，并把 SQLite 数据库持久化到 `gateway_db` volume。

默认 Compose 栈包含：

| 服务 | 作用 |
|------|------|
| `ingress` | Nginx 接入层，对外暴露 `${GATEWAY_PORT:-8000}` |
| `gateway` | 后端 Gateway + 已打包的 React 管理后台，只在 Compose 内网暴露 |
| `redis` | 缓存、限流和运行时状态 |
| `gateway_db` | SQLite 持久化 volume |
| `redis_data` | Redis 持久化 volume |

Gateway 和 Redis 只在 Compose 内网暴露，不会直接映射到宿主机公网端口。外部请求先进入 Nginx，再转发到 Gateway。

初始化演示用 Gateway API Key：

```bash
docker compose exec gateway python scripts/setup_test_key.py
```

然后在管理后台右上角填写：

```text
lgw_test_key_2026
```

## Local Install

```bash
uv sync
npm install --prefix frontend
npm run build --prefix frontend
```

## Configure Provider Keys

Provider keys are configured on the server:

```bash
export DEEPSEEK_API_KEY="..."
export KIMI_API_KEY="..."
export GLM_API_KEY="..."
```

Do not paste provider keys into the admin UI.

## Start

```bash
REDIS_URL=redis://127.0.0.1:6379/0 uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000/
```

The root path redirects to `/llm_gateway_admin`.

## Test Gateway Key

For local testing, this repository includes a helper key script:

```bash
uv run python scripts/setup_test_key.py
```

Use the printed Gateway API Key in the admin UI.
