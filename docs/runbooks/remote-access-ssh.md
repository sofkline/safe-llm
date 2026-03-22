# Remote Access via SSH

How to control the dev environment and access service UIs from a laptop over SSH.

## What you need

- SSH client on the laptop (already installed)
- SSH server running on the PC (already set up)
- PC's local IP address (see Step 1)

---

## Step 1: Find the PC's IP address

Run on the **PC** (PowerShell):

```powershell
ipconfig
```

Look for the `IPv4 Address` line under your active network adapter (Ethernet or Wi-Fi), e.g. `192.168.1.42`. Use this as `<pc-ip>` below.

---

## Step 2: Open two SSH sessions from the laptop

You need two terminal windows on the laptop — one to keep `main.py` running, one for other commands.

**Terminal 1 — infrastructure and proxy:**
```bash
ssh sofkline@192.168.87.41
```

Once connected (you'll get a Windows shell), start services:

```powershell
cd C:\Users\Соня\safeLLM\ai-safety
docker compose up -d
uv run python src/main.py
```

`uv run python src/main.py` blocks — keep this terminal open while working.

**Terminal 2 — for running other commands while proxy is up:**
```bash
ssh sofkline@192.168.87.41
```

Use this session for `git`, `docker compose ps`, log checks, etc.

---

## Step 3: Forward service ports to the laptop

In a **third terminal on the laptop**, open the SSH tunnel (keep it open):

```bash
ssh -N \
  -L 30000:localhost:30000 \
  -L 30080:localhost:30080 \
  -L 33000:localhost:33000 \
  -L 30432:localhost:30432 \
  -L 30433:localhost:30433 \
  sofkline@192.168.87.41
```

No output means it's working. Ctrl+C closes all tunnels.

---

## Step 4: Open the UIs in your laptop's browser

| Service | URL | Notes |
|---------|-----|-------|
| LiteLLM proxy | http://localhost:30000 | API endpoint |
| LiteLLM admin UI | http://localhost:30000/ui | Requires `UI_USERNAME` / `UI_PASSWORD` in `.env` |
| Open WebUI | http://localhost:30080 | Chat interface |
| Langfuse | http://localhost:33000 | Traces and sessions |

---

## Step 5: Connect to the database

Forward ports are already set up above (30432 = app DB, 30433 = Langfuse DB).

Use any PostgreSQL client (pgAdmin, DBeaver, DataGrip, TablePlus):

| Field | App DB | Langfuse DB |
|-------|--------|-------------|
| Host | `localhost` | `localhost` |
| Port | `30432` | `30433` |
| Credentials | see `.env` | see `.env` |

---

## Recommended workflow: VS Code Remote SSH

For day-to-day development this is better than the manual SSH + git round-trip. Files live on the PC; you edit them from the laptop as if they were local. No push/pull cycle just to test a change.

**Setup (once):**

1. Install the **Remote - SSH** extension (`ms-vscode-remote.remote-ssh`) on your laptop's VS Code
2. `Ctrl+Shift+P` → **Remote-SSH: Connect to Host** → `sofkline@192.168.87.41`
3. Open folder `C:\Users\Соня\safeLLM\ai-safety`
4. Open the **Ports** panel (bottom bar) → **Forward a Port** → add each port:
   `30000`, `30080`, `33000`, `30432`, `30433`

Port forwarding and file editing now work automatically — no separate tunnel terminal needed.

**Daily loop:**

```
1. Connect via Remote-SSH
2. Open integrated terminal → docker compose up -d
3. Open second terminal  → uv run python src/main.py   (keep open)
4. Edit files in VS Code on the laptop — they save directly to the PC
5. Ctrl+C in terminal 2, re-run main.py to pick up changes
6. Test in laptop browser via forwarded ports
7. When done: git commit & push (see Git workflow section below)
```

**When to use git push → pull instead:**
- Sharing changes with teammates
- Applying changes from a completely different network (outside home/office)
- A teammate's PC needs to pick up your commits

---

## Git workflow over SSH

Run git commands in Terminal 2 (the non-blocking SSH session).

### Check what changed

```powershell
git status                   # overview of changed files
git diff                     # full unstaged diff
git diff --staged            # what's already staged for commit
git log --oneline -10        # recent commit history
```

### Pull latest from remote

```powershell
git pull
```

If the proxy is running, restart it after pulling to pick up code changes (Ctrl+C in Terminal 1, then `uv run python src/main.py` again).

### Stage and commit

```powershell
git add src\main.py          # stage a specific file
git add src\                 # stage a whole directory
git add -p                   # interactive — review each chunk before staging

git commit -m "your message"
```

### Push

```powershell
git push
```

### Review a specific file's history

```powershell
git log --oneline -- src\main.py
git diff HEAD~1 -- src\main.py    # what changed in that file in the last commit
```

---

## Troubleshooting

### SSH connection refused
Check that OpenSSH Server service is running on the PC:
```powershell
Get-Service sshd
# If stopped:
Start-Service sshd
```

### Port forwarding — "channel 3: open failed"
The service on that port isn't running on the PC yet. Make sure `docker compose up -d` completed and `uv run python src/main.py` is running.

### Proxy dies when SSH session disconnects
`main.py` is tied to the SSH session. Either keep Terminal 1 open, or run the proxy on the PC directly (not via SSH) and connect only for port forwarding.

### LiteLLM `/ui` returns 404
The admin UI requires `UI_USERNAME` and `UI_PASSWORD` to be set in `.env`. Check those are present, then restart the proxy.
