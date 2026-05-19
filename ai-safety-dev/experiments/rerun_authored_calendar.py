#!/usr/bin/env python3
"""E9-followup -- rerun a persona's Stage 3 with a hand-authored calendar.

E9 found the live in-prompt calendar near-null. The calendar-review task
diagnosed *why*: the live _format_calendar emits thematic prose with no score
trajectory, a non-diffable tone paragraph, repeated marker blocks, and feeds
back the system's own (mis)predicted zones as history.

This driver replaces the live calendar with a frozen hand-authored one
(<persona>_calendar_authored.json) that fixes those defects: a trend header,
the full score vector per day, an ordinal tone, NEW-only deltas, plateau
compression, and est.zone marked as an estimate.

Mechanism: monkeypatch evaluate_corpus._format_calendar. The live calendar
list still flows through the pipeline; we ignore its content and render our
own from the authored JSON, keyed by len(calendar)+1 == the day being scored
(every prior viktor day is 'notable', so list length == D-1).

Everything else -- model, generator, thresholds, Stage 1/2 -- is identical to
the E8/E9 working corpus, so the calendar text is the only changed variable.
Incremental: each day appends to results/<persona>_authored_rerun.jsonl.
"""
import argparse
import asyncio
import json
import os

import evaluate_corpus as ec

BACKENDS = {
    "routerai": dict(model="openai/deepseek/deepseek-v3.2",
                     api_base="https://routerai.ru/api/v1",
                     key_env="ROUTERAI_API_KEY"),
    "openrouter": dict(model="openrouter/openai/gpt-oss-120b",
                       api_base="", key_env="OPENROUTER_API_KEY"),
}


def load_authored(persona: str) -> dict:
    path = ec.HERE / f"{persona}_calendar_authored.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_renderer(authored: dict):
    """Return render(D) -> calendar text fed when scoring day D (history 1..D-1)."""
    days = {d["day"]: d for d in authored["days"]}
    ab = authored["dim_abbrev"]
    theme = authored["persistent_theme"]

    def render(D: int) -> str:
        hist = [days[i] for i in range(1, D) if i in days]
        if not hist:
            return ""
        zones = [h["est_zone"] for h in hist]
        tn = [h["tone_n"] for h in hist]
        trend = "rising" if tn[-1] > tn[0] else (
            "falling" if tn[-1] < tn[0] else "flat")
        out = [f"=== {len(hist)}-DAY HISTORY (oldest->newest; today = Day 0) ===",
               "Trajectory: " + " ".join(z[0] for z in zones)
               + f"  (tone {tn[0]}->{tn[-1]}, {trend})",
               "Persistent theme: " + theme,
               "est.zone is a SYSTEM ESTIMATE of the prior day's zone, not "
               "ground truth -- weigh the score trend over any single est.zone.",
               ""]
        i = 0
        while i < len(hist):
            h = hist[i]
            rel = D - h["day"]
            run = i
            while (run + 1 < len(hist)
                   and hist[run + 1]["tone_n"] == h["tone_n"]
                   and hist[run + 1]["new"].startswith("-")
                   and h["new"].startswith("-")):
                run += 1
            vec = " ".join(f"{ab[k]} {h['scores'][k]:.2f}" for k in range(len(ab)))
            if run > i:
                r2 = D - hist[run]["day"]
                out.append(f"Day -{rel}..-{r2} | {h['tone']} | "
                           f"{run - i + 1}-day stable plateau, no new markers")
                i = run + 1
            else:
                out.append(f"Day -{rel} | tone: {h['tone']}({h['tone_n']}/5) | "
                           f"{vec} | NEW: {h['new']} | est.zone {h['est_zone']}*")
                i += 1
        return "\n".join(out)

    return render


def build_cfg(backend: str) -> ec.RunConfig:
    b = BACKENDS[backend]
    key = os.environ.get(b["key_env"])
    if not key:
        raise SystemExit(f"{b['key_env']} not set in environment / .env")
    return ec.RunConfig(
        corpus_dir=ec.HERE / "results" / "pilot",
        generator="qwen36",
        classifier_model=b["model"], classifier_api_base=b["api_base"],
        classifier_api_key=key,
        stage3_model=b["model"], stage3_api_base=b["api_base"],
        stage3_api_key=key,
        temperature=0.0, limit_days=None, use_calendar=True,
    )


async def run(persona: str, backend: str) -> None:
    cfg = build_cfg(backend)
    render = make_renderer(load_authored(persona))

    # The calendar is the only changed variable. Stage 3 is called once per
    # day in chronological order; an explicit counter keys the renderer (more
    # robust than inferring D from the live calendar list, whose length
    # depends on per-day _is_notable outcomes).
    state = {"day": 0}
    ec._format_calendar = lambda _calendar: render(state["day"])

    jsonl = ec.HERE / "results" / f"{persona}_authored_rerun.jsonl"
    jsonl.write_text("")
    orig = ec.stage3_behavioral
    captured: list[dict] = []

    async def wrapped(today, sessions, calendar, cfg_):
        state["day"] += 1
        result = await orig(today, sessions, calendar, cfg_)
        entry = {"date": today.isoformat(), "day": state["day"],
                 "calendar_text_fed": render(state["day"]),
                 "scores": result.get("scores", {})}
        captured.append(entry)
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result

    ec.stage3_behavioral = wrapped
    res = await ec.evaluate_persona(persona, cfg)
    rows = res["rows"]
    n = len(rows)
    match = sum(r["match"] for r in rows)
    out = ec.HERE / "results" / f"{persona}_authored_rerun.json"
    out.write_text(json.dumps({
        "persona": persona, "backend": backend,
        "calendar": "hand-authored (E9-followup)",
        "config": {"model": cfg.stage3_model, "generator": cfg.generator},
        "zone_match": match / n,
        "trajectory_exact_match": res["trajectory_exact_match"],
        "rows": [{"day": r["day"], "expected": r["expected_zone"],
                  "predicted": r["predicted_zone"], "match": r["match"],
                  "triggered_rules": r["triggered_rules"]} for r in rows],
    }, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")
    print(f"zone_match = {match}/{n} = {match / n:.3f}")
    for r in rows:
        mark = "ok" if r["match"] else "MISS"
        print(f"  day {r['day']:2d}: {r['expected_zone']:6s} -> "
              f"{r['predicted_zone']:6s} {mark}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--persona", default="viktor")
    ap.add_argument("--backend", choices=list(BACKENDS), default="routerai")
    args = ap.parse_args()
    asyncio.run(run(args.persona, args.backend))


if __name__ == "__main__":
    main()
