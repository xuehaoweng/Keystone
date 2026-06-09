# Security Policy

## Reporting a Vulnerability

Please do not open public issues for vulnerabilities. Report privately to the project maintainers.

Include:

- Affected version or commit.
- Reproduction steps.
- Impact.
- Suggested mitigation, if known.

## Secrets

There are two kinds of keys:

- Gateway API Key: used by clients and the admin UI to authenticate with LLM Gateway.
- Provider API Key: used by the backend to call OpenAI, DeepSeek, Kimi, Qwen, GLM, Lingya, or other providers.

Provider API keys must remain server-side. They must not be pasted into the admin UI, returned by `/api/config`, or committed to the repository.
