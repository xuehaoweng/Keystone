# Contributing

Thanks for considering a contribution to LLM Gateway.

## Development Setup

```bash
uv sync
npm install --prefix frontend
npm run build --prefix frontend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run checks before sending changes:

```bash
uv run pytest
uv run ruff check app tests
npm run build --prefix frontend
```

## Contribution Guidelines

- Keep backend changes covered by pytest.
- Keep frontend changes buildable with `npm run build --prefix frontend`.
- Do not commit real provider API keys.
- Do not expose provider API keys in API responses or UI.
- Prefer small, focused changes.

## Project Boundaries

LLM Gateway focuses on model routing, access governance, usage visibility, provider adapters, fallback, circuit breaking, and admin operations.

It is not a prompt management platform, workflow engine, fine-tuning system, or full billing product.
