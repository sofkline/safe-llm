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
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synthetic.personas import ALL_PERSONAS
from synthetic.personas.base import DayScript, PersonaConfig, SessionPlan
from synthetic.prompts import CLM_SYSTEM_PROMPT, build_plm_prompt, build_turn_reminder


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
    temperature: float = 0.8,
    max_tokens: int = 500,
    timeout: float = 60.0,
) -> tuple[str, dict]:
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
    client: httpx.AsyncClient,
    api_key: str,
    persona: PersonaConfig,
    ds: DayScript,
    session: SessionPlan,
    generator_model: str,
    target_model: str,
) -> list[dict]:
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
            client, api_key, generator_model,
            plm_messages,
            temperature=0.85, max_tokens=500,
        )
        plm_history.append({"role": "assistant", "content": user_msg})
        clm_history.append({"role": "user", "content": user_msg})

        asst_msg, asst_usage = await chat(
            client, api_key, target_model,
            clm_history,
            temperature=0.7, max_tokens=400,
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
    parser.add_argument("--sessions-per-day", type=int, default=None,
                        help="Cap sessions per day (default: all)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    env = load_env(repo_root / ".env")
    api_key = env["ROUTERAI_API_KEY"]
    base_url = env["ROUTERAI_BASE_URL"]
    generator = env.get("GENERATOR_MODEL", "deepseek/deepseek-v3.2")
    target = env.get("TARGET_AI_MODEL", "openai/gpt-5.4-nano")

    persona = ALL_PERSONAS[args.persona.lower()]
    days = persona.days[:args.days]

    out_dir = repo_root / "experiments" / "results" / "pilot" / persona.name.lower()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    print(f"Persona: {persona.name} ({persona.name_ru})  •  generator={generator}  target={target}")
    print(f"Days: {len(days)}  •  Output: {out_path}")
    print("=" * 80)

    total_in = 0
    total_out = 0
    t0 = time.time()

    fout = out_path.open("w")
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
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
                    client, api_key, persona, ds, sp, generator, target,
                )
                for ex in exchanges:
                    total_in += (ex["user_usage"].get("prompt_tokens", 0)
                                 + ex["asst_usage"].get("prompt_tokens", 0))
                    total_out += (ex["user_usage"].get("completion_tokens", 0)
                                  + ex["asst_usage"].get("completion_tokens", 0))
                fout.write(json.dumps({
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
    print("\n" + "=" * 80)
    print(f"Done in {dt:.1f}s  •  tokens in={total_in} out={total_out}  •  file={out_path}")


if __name__ == "__main__":
    asyncio.run(main())
