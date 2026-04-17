"""Standalone RouterAI pilot. No DB, no LiteLLM. Just transcripts.

Writes JSONL to experiments/results/pilot/<persona>/<timestamp>.jsonl
and prints human-readable transcripts to stdout.

Usage:
    cd ai-safety-dev
    python3 experiments/synthetic/pilot_routerai.py --persona nastya --days 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

PLM_TEMPERATURE = 0.85
PLM_MAX_TOKENS = 2500
CLM_TEMPERATURE = 0.7
CLM_MAX_TOKENS = 2000


def git_sha(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic.personas import ALL_PERSONAS
from synthetic.personas.base import DayScript, PersonaConfig, SessionPlan
from synthetic.prompts import (
    CLM_SYSTEM_PROMPT,
    PROMPT_VERSION,
    build_plm_prompt,
    build_turn_reminder,
)


def load_env(env_path: Path) -> dict:
    out = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


async def chat(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    kind: str = "openai",
    temperature: float = 0.8,
    max_tokens: int = 500,
    timeout: float = 300.0,
) -> tuple[str, dict]:
    last_exc = None
    for attempt in range(5):
        try:
            return await _chat_once(
                client, api_key, model, messages,
                kind=kind, temperature=temperature,
                max_tokens=max_tokens, timeout=timeout,
            )
        except httpx.HTTPStatusError as e:
            # Retry on 429 / 5xx (RouterAI had 502 outages on 2026-04-17)
            if e.response.status_code < 500 and e.response.status_code != 429:
                raise
            last_exc = e
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_exc = e
        wait = 2 ** attempt * 5  # 5s, 10s, 20s, 40s, 80s
        print(f"    [retry {attempt+1}/5] {type(last_exc).__name__}: backing off {wait}s")
        await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


async def _chat_once(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    messages: list[dict],
    *,
    kind: str,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> tuple[str, dict]:
    if kind == "ollama":
        # Native Ollama /api/chat — OpenAI-compat strands qwen3 thinking
        # into `reasoning` and leaves `content` empty. Native endpoint with
        # think=false forces direct content generation.
        resp = await client.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("message", {}).get("content") or "").strip()
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
        }
        return content, usage

    resp = await client.post(
        "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage", {})
    return content, usage


async def run_session(
    plm_backend: tuple[httpx.AsyncClient, str, str, str],
    clm_backend: tuple[httpx.AsyncClient, str, str, str],
    persona: PersonaConfig,
    ds: DayScript,
    session: SessionPlan,
) -> list[dict]:
    plm_client, plm_key, plm_model, plm_kind = plm_backend
    clm_client, clm_key, clm_model, clm_kind = clm_backend

    plm_prompt = build_plm_prompt(persona, ds, session)
    plm_history = [{"role": "system", "content": plm_prompt}]
    clm_history = [{"role": "system", "content": CLM_SYSTEM_PROMPT}]
    exchanges = []

    for turn in range(1, session.max_turns + 1):
        reminder = build_turn_reminder(persona, ds, turn, session.max_turns)
        plm_messages = plm_history + (
            [{"role": "system", "content": reminder}] if reminder else []
        )

        user_msg, user_usage = await chat(
            plm_client, plm_key, plm_model,
            plm_messages,
            kind=plm_kind,
            temperature=PLM_TEMPERATURE, max_tokens=PLM_MAX_TOKENS,
        )
        plm_history.append({"role": "assistant", "content": user_msg})
        clm_history.append({"role": "user", "content": user_msg})

        asst_msg, asst_usage = await chat(
            clm_client, clm_key, clm_model,
            clm_history,
            kind=clm_kind,
            temperature=CLM_TEMPERATURE, max_tokens=CLM_MAX_TOKENS,
        )
        clm_history.append({"role": "assistant", "content": asst_msg})
        plm_history.append({"role": "user", "content": asst_msg})

        exchanges.append({
            "turn": turn,
            "user": user_msg,
            "assistant": asst_msg,
            "user_usage": user_usage,
            "asst_usage": asst_usage,
        })

        print(f"    T{turn}  USR: {user_msg[:180]}")
        print(f"         AST: {asst_msg[:180]}")

    return exchanges


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", default="nastya")
    parser.add_argument("--days", type=int, default=3, help="Limit to first N days")
    parser.add_argument("--only-day", type=int, default=None,
                        help="Run only this single day number (1-indexed)")
    parser.add_argument("--sessions-per-day", type=int, default=None,
                        help="Cap sessions per day (default: all)")
    parser.add_argument("--generator-backend", choices=["routerai", "ollama"],
                        default="routerai",
                        help="Which backend drives the PLM (persona)")
    parser.add_argument("--generator-model", default=None,
                        help="Override generator model (else env default)")
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama base URL (no /v1 suffix — uses native /api/chat)")
    parser.add_argument("--tag", default=None,
                        help="Extra tag added to output filename")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    env = load_env(repo_root / ".env")
    router_key = env["ROUTERAI_API_KEY"]
    router_url = env["ROUTERAI_BASE_URL"]
    target = env.get("TARGET_AI_MODEL", "openai/gpt-5.4-nano")

    if args.generator_backend == "ollama":
        plm_url = args.ollama_url
        plm_key = "ollama"
        plm_model = args.generator_model or "glm-4.7-flash:latest"
        plm_kind = "ollama"
    else:
        plm_url = router_url
        plm_key = router_key
        plm_model = args.generator_model or env.get(
            "GENERATOR_MODEL", "deepseek/deepseek-v3.2"
        )
        plm_kind = "openai"

    persona = ALL_PERSONAS[args.persona.lower()]
    if args.only_day is not None:
        days = [d for d in persona.days if d.day == args.only_day]
        if not days:
            print(f"No day={args.only_day} found for persona {persona.name}")
            return
    else:
        days = persona.days[:args.days]

    out_dir = repo_root / "experiments" / "results" / "pilot" / persona.name.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    tag_suffix = f"_{args.tag}" if args.tag else f"_{args.generator_backend}"
    run_id = f"{datetime.now():%Y%m%d_%H%M%S}{tag_suffix}"
    out_path = out_dir / f"{run_id}.jsonl"

    print(f"Persona: {persona.name} ({persona.name_ru})")
    print(f"PLM: backend={args.generator_backend}  url={plm_url}  model={plm_model}")
    print(f"CLM: backend=routerai  model={target}")
    print(f"Days: {len(days)}  •  Output: {out_path}")
    print("=" * 80)

    total_in = 0
    total_out = 0
    t0 = time.time()

    fout = out_path.open("w")
    async with httpx.AsyncClient(base_url=plm_url, timeout=300) as plm_client, \
               httpx.AsyncClient(base_url=router_url, timeout=300) as clm_client:
        plm_backend = (plm_client, plm_key, plm_model, plm_kind)
        clm_backend = (clm_client, router_key, target, "openai")
        for ds in days:
            sessions = ds.sessions
            if args.sessions_per_day:
                sessions = sessions[:args.sessions_per_day]

            print(f"\n=== Day {ds.day} [{ds.phase}]  primary={ds.primary_topic}  tone={ds.emotional_tone}")
            if ds.required_phrases:
                print(f"    required: {ds.required_phrases}")

            for si, sp in enumerate(sessions):
                print(f"  -- Session {si+1}/{len(sessions)}  hour={sp.hour}  turns={sp.max_turns}")
                exchanges = await run_session(
                    plm_backend, clm_backend, persona, ds, sp,
                )
                for ex in exchanges:
                    total_in += (ex["user_usage"].get("prompt_tokens", 0)
                                 + ex["asst_usage"].get("prompt_tokens", 0))
                    total_out += (ex["user_usage"].get("completion_tokens", 0)
                                  + ex["asst_usage"].get("completion_tokens", 0))
                fout.write(json.dumps({
                    "run_id": run_id,
                    "plm_backend": args.generator_backend,
                    "plm_model": plm_model,
                    "clm_backend": "routerai",
                    "clm_model": target,
                    "prompt_version": PROMPT_VERSION,
                    "persona": persona.name,
                    "day": ds.day,
                    "phase": ds.phase,
                    "session_hour": sp.hour,
                    "required_phrases": ds.required_phrases,
                    "exchanges": exchanges,
                }, ensure_ascii=False) + "\n")
                fout.flush()
    fout.close()

    dt = time.time() - t0

    meta_path = out_path.with_suffix(".meta.json")
    meta = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "persona": persona.name,
        "persona_ru": persona.name_ru,
        "days_arg": {
            "only_day": args.only_day,
            "days_limit": args.days,
            "sessions_per_day": args.sessions_per_day,
        },
        "days_run": [d.day for d in days],
        "plm": {
            "backend": args.generator_backend,
            "base_url": plm_url,
            "model": plm_model,
            "temperature": PLM_TEMPERATURE,
            "max_tokens": PLM_MAX_TOKENS,
        },
        "clm": {
            "backend": "routerai",
            "base_url": router_url,
            "model": target,
            "temperature": CLM_TEMPERATURE,
            "max_tokens": CLM_MAX_TOKENS,
        },
        "prompt_version": PROMPT_VERSION,
        "script": {
            "path": str(Path(__file__).relative_to(repo_root)),
            "git_sha": git_sha(repo_root),
        },
        "totals": {
            "duration_sec": round(dt, 2),
            "tokens_in": total_in,
            "tokens_out": total_out,
        },
        "output_jsonl": out_path.name,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print(f"Done in {dt:.1f}s  •  tokens in={total_in} out={total_out}")
    print(f"  data: {out_path}")
    print(f"  meta: {meta_path}")


if __name__ == "__main__":
    asyncio.run(main())
