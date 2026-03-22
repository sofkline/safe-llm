# LiteLLM Upgrade Runbook

Steps to take after upgrading the `litellm` package.

## When to use this

After running `uv add litellm@<new-version>` or `uv sync` following a version bump in `pyproject.toml`.

---

## Step 1: Regenerate the Prisma client

The Prisma client is tied to the installed package version and must be regenerated after every upgrade. The tricky part on Windows is that `prisma-client-py` must be on PATH when `prisma generate` runs — the venv Scripts directory is not on PATH by default.

Open **PowerShell** in `d:\PSU\safeLLM\project\ai-safety` and run:

```powershell
$env:PATH = "$PWD\.venv\Scripts;" + $env:PATH
.\.venv\Scripts\prisma.exe generate --schema .\.venv\Lib\site-packages\litellm\proxy\schema.prisma
```

Expected output ends with:
```
✔ Generated Prisma Client Python (v0.x.x) to .\.venv\Lib\site-packages\prisma in ...ms
```

> **Non-ASCII username (e.g. Cyrillic):** The Prisma Rust binary can mangle Unicode characters in the path (e.g. `Соня` → `����`), causing a `PermissionError` when it tries to create the output directory. Fix: set `PYTHONUTF8=1` before running generate:
> ```powershell
> $env:PYTHONUTF8 = "1"
> $env:PATH = "$PWD\.venv\Scripts;" + $env:PATH
> .\.venv\Scripts\prisma.exe generate --schema .\.venv\Lib\site-packages\litellm\proxy\schema.prisma
> ```
> If it still fails, redirect the generator output to an ASCII-only path:
> ```powershell
> $env:PYTHONUTF8 = "1"
> $env:PATH = "$PWD\.venv\Scripts;" + $env:PATH
> $env:PRISMA_PY_GENERATOR_OUTPUT = "C:\Temp\prisma-gen"
> .\.venv\Scripts\prisma.exe generate --schema .\.venv\Lib\site-packages\litellm\proxy\schema.prisma
> Copy-Item -Recurse -Force "C:\Temp\prisma-gen\*" ".\.venv\Lib\site-packages\prisma\"
> ```

> **Stale venv scripts** (error: "uv trampoline failed to canonicalize script path"): can happen after renaming the project folder. Fix: reinstall prisma via pip first.
> ```powershell
> .venv\Scripts\python.exe -m ensurepip
> .venv\Scripts\python.exe -m pip install --force-reinstall prisma
> ```
> Then re-run the generate command above.

---

## Step 2: Patch the DailyTagSpend view SQL

LiteLLM's `create_views.py` uses `jsonb_array_elements_text(request_tags)` but the `request_tags` column in `LiteLLM_SpendLogs` is `json` type (not `jsonb`). PostgreSQL rejects this without an explicit cast.

File to patch:
```
.venv\Lib\site-packages\litellm\proxy\db\create_views.py
```

Find this line (inside the `DailyTagSpend` view SQL):
```python
jsonb_array_elements_text(request_tags) AS individual_request_tag,
```

Change it to:
```python
jsonb_array_elements_text(request_tags::jsonb) AS individual_request_tag,
```

To do it in one command from the project root (run in bash/Git Bash — this is a single command, the `\` is a line continuation):

```bash
sed -i 's/jsonb_array_elements_text(request_tags)/jsonb_array_elements_text(request_tags::jsonb)/g' \
  .venv/Lib/site-packages/litellm/proxy/db/create_views.py
```

> **Why this happens:** Prisma maps `Json` fields to PostgreSQL `json` (not `jsonb`). The `jsonb_array_elements_text` function only accepts `jsonb`, so the explicit `::jsonb` cast is required. This is an upstream LiteLLM bug — check if it has been fixed before applying the patch after each upgrade.

---

## Step 3: Verify startup

```bash
uv run python src/main.py
```

Look for these lines confirming the DB views were set up:
```
LiteLLM_VerificationTokenView Created!  (or Exists!)
MonthlyGlobalSpend Created!             (or Exists!)
DailyTagSpend Created!                  (or Exists!)
...
Application startup complete.
```

If you see `RawQueryError: function jsonb_array_elements_text(json) does not exist`, the patch in Step 2 was not applied (or was overwritten).

---

## Summary

| Step | Command | Notes |
|------|---------|-------|
| Regenerate Prisma client | `prisma generate --schema ...` via PowerShell | Must have venv Scripts in PATH |
| Patch view SQL | `sed -i 's/...'` or manual edit | Cast `::jsonb` on `request_tags` |
| Verify | `uv run python src/main.py` | Check for startup complete |
