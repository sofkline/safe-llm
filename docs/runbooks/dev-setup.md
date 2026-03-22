# Dev Setup Runbook

## Prerequisites

- Docker & Docker Compose
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Ollama running locally (`ollama serve`)
- OpenRouter API key (for cloud models and judge)

## 1. Clone and configure

```bash
cd ai-safety-mikhail
cp .env.example .env
# Edit .env — fill in your OpenRouter key and Langfuse keys (after step 3)
```

## 2. Start infrastructure

```bash
docker compose up -d
```

This starts 9 containers (Langfuse v3 needs ClickHouse, Redis, MinIO). First run pulls ~3GB of images.

| Service | URL | What it does |
|---------|-----|-------------|
| PostgreSQL | `localhost:30432` | App database (LiteLLM + predictions) |
| Langfuse Web | `http://localhost:33000` | Trace viewer & analytics |
| Langfuse Worker | (internal) | Async processing |
| Langfuse DB | `localhost:30433` | Langfuse's PostgreSQL |
| ClickHouse | (internal) | Langfuse analytics storage |
| Redis | (internal) | Langfuse queue |
| MinIO | (internal) | Langfuse blob storage |
| Open WebUI | `http://localhost:30080` | Chat interface |

**Important**: There may be another Langfuse on `localhost:3000` — that's the host instance, not ours. Always use **port 33000**.

Langfuse takes ~30-60s to fully start (migrations + healthchecks). Check with:
```bash
docker compose logs langfuse-web --tail 5
```

## 3. Set up Langfuse

1. Open `http://localhost:33000`
2. Create an account (first user becomes admin)
3. Create a project
4. Go to Settings → API Keys → Create
5. Copy the public and secret keys into your `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
   LANGFUSE_SECRET_KEY=sk-lf-xxxxx
   ```

## 4. Install Python dependencies

```bash
uv sync
```

That's it — uv creates the venv and installs everything from the lock file.

## 5. Run the proxy

```bash
uv run python src/main.py
```

The LiteLLM proxy starts on `http://localhost:30000`.

## 6. Verify it works

```bash
# Check proxy is up (use your LITELLM_MASTER_KEY from .env, default: sk-1234)
curl http://localhost:30000/health -H "Authorization: Bearer sk-1234"

# List available models
curl http://localhost:30000/models -H "Authorization: Bearer sk-1234"

# Test a local model (Ollama must be running)
curl http://localhost:30000/chat/completions \
  -H "Authorization: Bearer sk-1234" \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma3", "messages": [{"role": "user", "content": "Hello!"}]}'
```

Or open `http://localhost:30080` (Open WebUI) and chat directly.

## 7. Shut down

```bash
docker compose down        # stop containers (keep data)
docker compose down -v     # stop and DELETE all data
```

## Available Models

| Name | Backend | Notes |
|------|---------|-------|
| `gemma3` | Local Ollama | gemma3:12b |
| `glm-4.7-flash` | Local Ollama | |
| `gpt-oss` | Local Ollama | |
| `gemma3-vpn1` | 192.168.87.25 | VPN required |
| `glm-4.7-flash-vpn1` | 192.168.87.25 | VPN required |
| `gemma3-vpn2` | 192.168.87.54 | VPN required |
| `glm-4.7-flash-vpn2` | 192.168.87.54 | VPN required |
| `gpt-5-nano` | OpenRouter | Needs API key |
| `gpt-oss-safeguard` | OpenRouter | Judge model for safety |

## Port Map

| Port | Service |
|------|---------|
| 30000 | LiteLLM proxy (on host) |
| 30080 | Open WebUI |
| 30432 | PostgreSQL (app) |
| 30433 | PostgreSQL (Langfuse) |
| 33000 | Langfuse |
