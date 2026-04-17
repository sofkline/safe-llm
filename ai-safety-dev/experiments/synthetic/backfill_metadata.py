"""Backfill run_id/plm_model/clm_model/prompt_version into existing JSONL files.

Rules:
- If a sidecar `<stem>.meta.json` exists, use it as source of truth.
- Else infer from filename tag: `_deepseek*` → deepseek-v3.2 p1, `_qwen36*` → qwen3.6 p2,
  `_glm47*` → glm-4.7-flash p1, `_smoke` → qwen3.6 p1. Nastya untagged files = p0 or p1.
- Writes a new file `<stem>.backfilled.jsonl` then replaces original (unless --dry-run).
- Idempotent: if rows already have `run_id`, file is skipped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "results" / "pilot"

# (filename tag → (plm_backend, plm_model, prompt_version))
TAG_RULES = {
    "deepseek_p2_resume": ("routerai", "deepseek/deepseek-v3.2", "p2"),
    "deepseek_p2": ("routerai", "deepseek/deepseek-v3.2", "p2"),
    "deepseek": ("routerai", "deepseek/deepseek-v3.2", "p1"),
    "qwen36_p2_resume": ("ollama", "qwen3.6:35b-a3b", "p2"),
    "qwen36_3090_p2": ("ollama", "qwen3.6:35b-a3b", "p2"),
    "qwen36_p2": ("ollama", "qwen3.6:35b-a3b", "p2"),
    "qwen36_smoke": ("ollama", "qwen3.6:35b-a3b", "p1"),
    "qwen36": ("ollama", "qwen3.6:35b-a3b", "p1"),
    "glm47": ("ollama", "glm-4.7-flash:latest", "p1"),
}
DEFAULT_CLM = ("routerai", "openai/gpt-5.4-nano")


def infer_from_tag(stem: str) -> tuple[str, str, str]:
    """Return (plm_backend, plm_model, prompt_version) by longest-match on filename."""
    # Try longer tags first
    for tag, triple in sorted(TAG_RULES.items(), key=lambda kv: -len(kv[0])):
        if stem.endswith(tag):
            return triple
    # Nastya untagged files (20260417_075424.jsonl, 20260417_075920.jsonl, etc.)
    # First two runs were p0 prompt-leak era; rest were p1. Use modification-order heuristic:
    # stems without any known tag → assume deepseek p0 (Nastya aborted/pilot runs pre-refactor).
    return ("routerai", "deepseek/deepseek-v3.2", "p0")


def load_meta(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None


def fields_from_meta(meta: dict, stem: str) -> dict:
    plm = meta.get("plm", {})
    clm = meta.get("clm", {})
    return {
        "run_id": stem,
        "plm_backend": plm.get("backend", "routerai"),
        "plm_model": plm.get("model", "unknown"),
        "clm_backend": clm.get("backend", "routerai"),
        "clm_model": clm.get("model", DEFAULT_CLM[1]),
        "prompt_version": meta.get("prompt_version", "unknown"),
    }


def fields_from_tag(stem: str) -> dict:
    plm_backend, plm_model, pv = infer_from_tag(stem)
    return {
        "run_id": stem,
        "plm_backend": plm_backend,
        "plm_model": plm_model,
        "clm_backend": DEFAULT_CLM[0],
        "clm_model": DEFAULT_CLM[1],
        "prompt_version": pv,
    }


def process_file(jsonl_path: Path, dry_run: bool) -> str:
    stem = jsonl_path.stem
    meta = load_meta(jsonl_path.with_suffix(".meta.json"))
    fields = fields_from_meta(meta, stem) if meta else fields_from_tag(stem)

    lines = jsonl_path.read_text().splitlines()
    if not lines:
        return f"skip (empty): {jsonl_path.name}"

    first = json.loads(lines[0])
    if "run_id" in first:
        return f"skip (already backfilled): {jsonl_path.name}"

    out_lines = []
    for ln in lines:
        if not ln.strip():
            continue
        row = json.loads(ln)
        # Preserve existing keys; overlay metadata fields at the front
        new_row = {**fields, **row}
        out_lines.append(json.dumps(new_row, ensure_ascii=False))

    src = "meta" if meta else "tag"
    if dry_run:
        return (
            f"would backfill ({src}): {jsonl_path.name}  "
            f"plm={fields['plm_model']} pv={fields['prompt_version']} n={len(out_lines)}"
        )

    tmp = jsonl_path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(out_lines) + "\n")
    tmp.replace(jsonl_path)
    return (
        f"backfilled ({src}): {jsonl_path.name}  "
        f"plm={fields['plm_model']} pv={fields['prompt_version']} n={len(out_lines)}"
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args()

    files = sorted(args.root.glob("*/*.jsonl"))
    for f in files:
        try:
            print(process_file(f, args.dry_run))
        except Exception as e:
            print(f"ERROR {f.name}: {e}")


if __name__ == "__main__":
    main()
