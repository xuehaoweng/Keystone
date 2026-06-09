# Configuration

## Gateway Config

`config/gateway.yaml` controls server defaults, auth, timeouts, intent classifier, and routing rules.

## Models Config

`config/models.yaml` defines model instances:

```yaml
models:
  - name: deepseek-chat
    tier: cheap
    provider: deepseek
    weight: 2
    max_concurrent: 150
    rate_limit: 1500
```

Provider definitions include base URLs. Provider API keys should usually come from environment variables.

## Cost Fields

Optional cost fields:

```yaml
input_cost_per_1k: 0.10
output_cost_per_1k: 0.20
```

or:

```yaml
cost_per_1k: 0.15
```
