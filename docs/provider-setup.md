# Provider Setup

LLM Gateway separates client authentication from provider authentication.

## Gateway API Key

Gateway API Keys authenticate callers to LLM Gateway.

Use them in:

- Admin UI right-top token field.
- `Authorization: Bearer <gateway_key>` headers.

Example:

```text
lgw_test_key_2026
```

## Provider API Key

Provider API Keys authenticate LLM Gateway to downstream model vendors.

Examples:

```bash
export DEEPSEEK_API_KEY="..."
export KIMI_API_KEY="..."
export KIMI_CODE_API_KEY="..."
export GLM_API_KEY="..."
export OPENAI_API_KEY="..."
```

Provider keys are server-side secrets. They are not accepted in the admin UI.

Kimi has two different API families:

- `KIMI_API_KEY`: Moonshot/Kimi open platform, model examples such as `kimi-k2.5`, base URL `https://api.moonshot.ai/v1`.
- `KIMI_CODE_API_KEY`: Kimi Code membership entitlement, fixed model ID `kimi-for-coding`, base URL `https://api.kimi.com/coding/v1`.

## Common Provider Errors

| Error | Meaning |
|------|---------|
| DeepSeek 402 | Account balance, quota, or billing status problem |
| Provider 403 | API key lacks permission for that provider/model |
| Provider 429 | Provider-side rate limit or quota pressure |
| Provider 400 | Provider rejected request format or parameters |
