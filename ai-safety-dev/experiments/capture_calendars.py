#!/usr/bin/env python3
"""Capture a persona's actual longitudinal calendars (E9 calendar-review task).

The corpus rows do NOT persist Stage-3 self-summary fields, so the in-prompt
calendar that was fed to Stage 3 cannot be reconstructed offline. This driver
re-runs one persona through the full pipeline and dumps, per day:

  - the calendar TEXT fed into the Stage-3 prompt (_format_calendar output)
  - the LLM-produced DailySummary (key_topics / life_events / emotional_tone /
    ai_relationship_markers)
  - the Stage-3 behavioural scores and the final zone vs expected

Output: experiments/results/<persona>_calendars_<backend>.json
One persona, ~14 days -> cheap.  Keys via env vars only.

  --backend routerai    deepseek-v3.2  (E8/E9 working-corpus config)
  --backend openrouter  gpt-oss-120b   (E10 corpus config)

Both backends are remote APIs -> safe to run two captures in parallel.
"""
import argparse
import asyncio
import json
import os

import evaluate_corpus as ec
from behavioral.behavioral_llm import _format_calendar

BACKENDS = {
    "routerai": dict(
        model="openai/deepseek/deepseek-v3.2",
        api_base="https://routerai.ru/api/v1",
        key_env="ROUTERAI_API_KEY",
    ),
    "openrouter": dict(
        model="openrouter/openai/gpt-oss-120b",
        api_base="",  # omit for openrouter routing
        key_env="OPENROUTER_API_KEY",
    ),
}


def build_cfg(backend: str) -> ec.RunConfig:
    b = BACKENDS[backend]
    key = os.environ.get(b["key_env"])
    if not key:
        raise SystemExit(f"{b['key_env']} not set in environment / .env")
    return ec.RunConfig(
        corpus_dir=ec.HERE / "results" / "pilot",
        generator="qwen36",
        classifier_model=b["model"],
        classifier_api_base=b["api_base"],
        classifier_api_key=key,
        stage3_model=b["model"],
        stage3_api_base=b["api_base"],
        stage3_api_key=key,
        temperature=0.0,
        limit_days=None,
        use_calendar=True,
    )


async def run(persona: str, backend: str) -> None:
    cfg = build_cfg(backend)
    captured: list[dict] = []
    orig = ec.stage3_behavioral
    # Incremental persistence: each day's calendar is appended to a JSONL file
    # the moment Stage 3 produces it, so a killed run keeps everything so far.
    jsonl = ec.HERE / "results" / f"{persona}_calendars_{backend}.jsonl"
    jsonl.write_text("")  # truncate any stale partial

    async def wrapped(today, sessions, calendar, cfg_):
        cal_text = _format_calendar(calendar)
        result = await orig(today, sessions, calendar, cfg_)
        entry = {
            "date": today.isoformat(),
            "calendar_entries_in": len(calendar),
            "calendar_text_fed": cal_text,
            "summary": result.get("summary", {}),
            "scores": result.get("scores", {}),
        }
        captured.append(entry)
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result

    ec.stage3_behavioral = wrapped
    res = await ec.evaluate_persona(persona, cfg)
    for cap, row in zip(captured, res["rows"]):
        cap["day"] = row["day"]
        cap["expected_zone"] = row["expected_zone"]
        cap["predicted_zone"] = row["predicted_zone"]
        cap["triggered_rules"] = row["triggered_rules"]
    out = ec.HERE / "results" / f"{persona}_calendars_{backend}.json"
    out.write_text(json.dumps({
        "persona": persona,
        "backend": backend,
        "config": {"model": cfg.stage3_model, "generator": cfg.generator},
        "trajectory_exact_match": res["trajectory_exact_match"],
        "days": captured,
    }, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")
    for c in captured:
        print(f"  day {c['day']:2d}: {c['expected_zone']:6s} -> {c['predicted_zone']:6s}"
              f"  cal_entries={c['calendar_entries_in']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--persona", default="viktor")
    ap.add_argument("--backend", choices=list(BACKENDS), default="routerai")
    args = ap.parse_args()
    asyncio.run(run(args.persona, args.backend))


if __name__ == "__main__":
    main()
