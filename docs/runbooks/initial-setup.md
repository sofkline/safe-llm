# Initial Setup — for new contributors

This guide gets you from zero to a working dev environment on your PC.

## What you'll have when done

- LiteLLM proxy (AI gateway) running on your machine
- Langfuse (trace viewer) to see what's happening
- Open WebUI (chat interface) to talk to models
- Access to local and remote LLMs

## Step 0: Install prerequisites

### Git
```bash
# Ubuntu/Debian
sudo apt install git

# Check
git --version
```

### Docker & Docker Compose
```bash
# Install Docker (official method)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in for group to take effect

# Check
docker --version
docker compose version
```

### Python 3.11+
```bash
# Ubuntu/Debian
sudo apt install python3 python3-venv python3-pip

# Check
python3 --version   # Should be 3.11 or higher
```

### uv (Python package manager)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

# Check
uv --version
```

### Ollama (local LLMs)
```bash
curl -fsSL https://ollama.com/install.sh | sh

# Check
ollama --version
```

## Step 1: Clone the repo

```bash
git clone https://github.com/PixelPantz/ai-safety.git
cd ai-safety
git checkout dev/behavioral-monitoring
```

## Step 2: Pull Ollama models

This downloads the models we use. Takes a while on first run (~20-30GB total).

```bash
ollama pull gemma3:12b
ollama pull glm-4.7-flash:latest
```

Make sure Ollama is running:
```bash
ollama serve
# If it says "address already in use" — it's already running, that's fine
```

## Step 3: Configure environment

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in:

1. **OpenRouter API key** — get one at https://openrouter.ai/keys
   ```
   OPENROUTER_API_KEY=sk-or-v1-xxxxx
   API_KEY=sk-or-v1-xxxxx           # same key
   ```

2. Leave everything else as-is for now. Langfuse keys are set up in Step 5.

## Step 4: Start infrastructure

```bash
docker compose up -d
```

Wait for it to finish. First time it downloads ~3GB of images (Langfuse v3 has several components).

Check everything is running:
```bash
docker compose ps
```

You should see 8 services — all "Up" or "Up (healthy)". Langfuse takes ~30-60 seconds to fully start.

If `langfuse-web` shows "Restarting", wait a minute — it needs ClickHouse and Redis to be ready first.

## Step 5: Set up Langfuse

1. Open http://localhost:33000 in your browser
2. Create an account (email + password — this is local, only on your machine)
3. Create a new project (call it anything, e.g. "ai-safety")
4. Go to **Settings** → **API Keys** → **Create API Key**
5. Copy the keys into your `.env`:
   ```
   LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
   LANGFUSE_SECRET_KEY=sk-lf-xxxxx
   ```

## Step 6: Install Python dependencies

```bash
uv sync
```

That's it. `uv` creates a virtual environment and installs all packages from the lock file. Takes a few seconds.

## Step 7: Run the proxy

```bash
uv run python src/main.py
```

You should see output like:
```
INFO:     Uvicorn running on http://localhost:30000
```

## Step 8: Verify

### Option A: Command line
```bash
curl http://localhost:30000/health
```
Should return `{"status":"healthy"}` or similar.

### Option B: Open WebUI (easier)
1. Open http://localhost:30080
2. Create an account (local only)
3. Pick a model (e.g. `gemma3`)
4. Send a message — you should get a response

### Option C: Check Langfuse
After sending a message, open http://localhost:33000 → **Traces** — you should see your conversation appear.

## Daily workflow

```bash
# Start infra (if not already running)
docker compose up -d

# Run proxy
uv run python src/main.py

# When done
Ctrl+C to stop proxy
docker compose down   # optional — stop infra
```

## Troubleshooting

### "Port already in use"
Something else is using that port. Check what:
```bash
ss -tlnp | grep 30000
```
Kill it or change the port in `.env` (`LITELLM_PORT=30001`).

### Ollama models not responding
Make sure Ollama is running:
```bash
ollama serve
```
Test directly:
```bash
curl http://localhost:11434/api/tags
```

### VPN models not working
Models on 192.168.87.25 and 192.168.87.54 only work when VPN is connected. Use local models if VPN is off.

### Docker containers won't start
```bash
docker compose logs langfuse    # check specific service
docker compose down && docker compose up -d   # restart everything
```

### "Module not found" errors
Re-sync dependencies:
```bash
uv sync
```

## Port reference

| Port | Service | URL |
|------|---------|-----|
| 30000 | LiteLLM proxy | http://localhost:30000 |
| 30080 | Open WebUI | http://localhost:30080 |
| 30432 | PostgreSQL (app) | — |
| 30433 | PostgreSQL (Langfuse) | — |
| 33000 | Langfuse | http://localhost:33000 |
