# Changelog

## [0.2.0] — 2026-06-09

### Added
- **OpenAI-compatible API** (`POST /v1/chat/completions`, `GET /v1/models`) — drop-in replacement for OpenAI SDK clients (Cursor, Continue, Copilot, etc.).
- **Anthropic-compatible API** (`POST /v1/anthropic`) — native Messages API format for Claude Code and Anthropic SDK.
- **Multi-protocol support** — single gateway serves Native (`/api/runs`), OpenAI (`/v1/chat/completions`), and Anthropic (`/v1/anthropic`) endpoints simultaneously.
- **One-command quick start** — `scripts/quickstart.sh` gets you from clone to first request in under 5 minutes.
- **GitHub Actions CI** — automated test and lint pipeline on every push/PR.
- **Bilingual documentation** — English README (`README.md`) and Chinese README (`README.zh-CN.md`) with cross-links.

### Changed
- Rewrote README with English-first structure, CI badges, and "Why not LiteLLM?" comparison.
- Fixed frontend GitHub placeholder links to point to the actual repository.

## [0.1.0] — 2026-06-08

### Added
- React admin console served by FastAPI.
- API Key quota and allowed tier enforcement.
- Usage persistence and DB-backed usage summary.
- Model fallback, circuit breaking, result cache, and provider status views.
- Route metadata in non-stream responses.
- `/api/usage`, `/ready`, and `/api/providers/health` endpoints.
- Provider error normalization helpers.
- Intent classification with Redis caching.
- Static rule engine (tool, keyword, content-length matching).
- Load balancer with health-aware weighted selection.
- Docker Compose stack with Nginx ingress, Redis, and SQLite persistence.
