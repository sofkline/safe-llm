# LiteLLM Proxy Docker Deployment Research

Date: 2026-03-12

## 1. Official docker-compose.yml (from BerriAI/litellm main branch)

```yaml
services:
  litellm:
    build:
      context: .
      args:
        target: runtime
    image: docker.litellm.ai/berriai/litellm:main-stable
    #########################################
    ## Uncomment these lines to start proxy with a config.yaml file ##
    # volumes:
    #  - ./config.yaml:/app/config.yaml
    # command:
    #  - "--config=/app/config.yaml"
    ##############################################
    ports:
      - "4000:4000"
    environment:
      DATABASE_URL: "postgresql://llmproxy:dbpassword9090@db:5432/litellm"
      STORE_MODEL_IN_DB: "True"  # allows adding models to proxy via UI
    env_file:
      - .env
    depends_on:
      - db
    healthcheck:
      test:
        - CMD-SHELL
        - python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:4000/health/liveliness')"
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  db:
    image: postgres:16
    restart: always
    container_name: litellm_db
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: llmproxy
      POSTGRES_PASSWORD: dbpassword9090
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -d litellm -U llmproxy"]
      interval: 1s
      timeout: 5s
      retries: 10

  prometheus:
    image: prom/prometheus
    volumes:
      - prometheus_data:/prometheus
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=15d"
    restart: always

volumes:
  prometheus_data:
    driver: local
  postgres_data:
    name: litellm_postgres_data
```

## 2. How config.yaml is mounted

Uncomment the volumes/command in the litellm service:

```yaml
volumes:
  - ./config.yaml:/app/config.yaml
command:
  - "--config=/app/config.yaml"
```

The container expects the config at `/app/config.yaml`. The `--config` flag tells the proxy where to find it.

## 3. Required environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LITELLM_MASTER_KEY` | Yes (production) | Admin API key for the proxy. Set in `.env` file. |
| `LITELLM_SALT_KEY` | Yes (production) | Encryption key for stored API credentials. **Cannot be changed after initial setup.** |
| `DATABASE_URL` | Yes (with DB) | PostgreSQL connection string, e.g. `postgresql://llmproxy:dbpassword9090@db:5432/litellm` |
| `STORE_MODEL_IN_DB` | Optional | Set `"True"` to allow adding models via the admin UI instead of config.yaml only |

Provider-specific keys go in `.env` or in `config.yaml` via `os.environ/VAR_NAME` syntax:

```yaml
model_list:
  - model_name: gpt-4o
    litellm_params:
      model: azure/gpt-4o
      api_base: os.environ/AZURE_API_BASE
      api_key: os.environ/AZURE_API_KEY
```

## 4. Quick start commands

```bash
curl -O https://raw.githubusercontent.com/BerriAI/litellm/main/docker-compose.yml
curl -O https://raw.githubusercontent.com/BerriAI/litellm/main/prometheus.yml

echo 'LITELLM_MASTER_KEY="sk-1234"' > .env
echo 'LITELLM_SALT_KEY="sk-1234"' >> .env

docker compose up -d
```

Proxy runs at `http://localhost:4000`.

## 5. Custom middleware / callbacks in Docker

LiteLLM supports two approaches for custom code:

### Approach A: CustomGuardrail class (native LiteLLM hook system)

Mount your Python file into the container and reference it in `config.yaml`:

```yaml
# config.yaml
litellm_settings:
  callbacks: custom_guardrails.proxy_handler_instance
```

```yaml
# docker-compose.yaml volumes
volumes:
  - ./config.yaml:/app/config.yaml
  - ./custom_guardrails.py:/app/custom_guardrails.py:ro
  - ./prompt.py:/app/prompt.py:ro    # if your guardrail imports it
```

The Python file must expose an instantiated handler:

```python
from litellm.integrations.custom_logger import CustomLogger

class MyCustomHandler(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        # modify data, raise HTTPException to block
        return data

proxy_handler_instance = MyCustomHandler()
```

Available hooks:
- `async_pre_call_hook` -- modify request before LLM call
- `async_moderation_hook` -- runs in parallel with LLM call
- `async_post_call_success_hook` -- modify non-streaming response
- `async_post_call_streaming_hook` -- modify streaming response
- `async_post_call_failure_hook` -- transform error responses
- `async_post_call_response_headers_hook` -- inject custom HTTP headers

### Approach B: Starlette middleware wrapping proxy app (current `src/main.py` approach)

This is what Mikhail currently does -- importing `litellm.proxy.proxy_server.app` and adding Starlette middleware. This **cannot run in the official Docker image** because it requires a custom entrypoint (`python main.py` via uvicorn instead of `litellm --config`).

To dockerize this approach, you need a custom Dockerfile:

```dockerfile
FROM docker.litellm.ai/berriai/litellm:main-stable
COPY src/ /app/custom/
WORKDIR /app/custom
CMD ["python", "main.py"]
```

## 6. Comparison: current approach vs Docker-native

| Aspect | Current (`python main.py`) | Docker with CustomGuardrail | Docker with custom Dockerfile |
|--------|---------------------------|----------------------------|-------------------------------|
| Starlette middleware | Yes (full control) | No (use hook system instead) | Yes |
| Custom lifespan (scheduler) | Yes | No (would need separate service) | Yes |
| Database schema creation | Yes (custom SQLAlchemy) | No | Yes |
| Official image updates | Manual pip upgrade | Just pull new image | Rebuild on top of new image |
| Complexity | Low (one process) | Low (mount files) | Medium (maintain Dockerfile) |
| Production-readiness | Needs systemd/supervisor | Built-in healthcheck, restart | Built-in healthcheck, restart |

## 7. Recommendation for Mikhail's project

The current `src/main.py` does three things the native hook system cannot easily replace:

1. **Starlette middleware** that reads raw request body, classifies it, and injects `metadata.tags` + `session_id` from `x-openwebui-chat-id` header -- the native `async_pre_call_hook` can do most of this but header access and metadata injection work differently.

2. **Custom lifespan** with Langfuse scraper scheduler -- no equivalent in LiteLLM's hook system.

3. **Custom database schema creation** -- separate from LiteLLM's own DB.

**Two viable paths:**

**Path 1 (minimal change):** Keep `python main.py`, but containerize it with a custom Dockerfile. Mount `config.yaml` as before. This preserves all existing middleware logic.

**Path 2 (refactor to native hooks):** Rewrite `BinaryUserSafetyGuardrailMiddleware` as a `CustomGuardrail` (already done in `experiments/litellm/custom_guardrails.py`), run the Langfuse scheduler as a separate sidecar container, and use the official Docker image with mounted Python files. This is cleaner long-term but requires splitting the monolith.

The experiment in `experiments/litellm/` already has a working docker-compose.yaml with custom guardrails mounted -- that is essentially Path 2 in progress.
