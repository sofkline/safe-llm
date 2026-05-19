#!/usr/bin/env python3
"""Stage-4 YELLOW threshold optimisation (chapter-4, the YELLOW lower edge).

The 2026-05-18 audit found 40 of 72 YELLOW-designed day-points produce *zero*
Stage-4 triggers: Stage 3 detects moderate distress but every YELLOW threshold
sits above the moderate band. This script recalibrates the YELLOW behavioural
thresholds so that band registers, without worsening the GREEN false-positive
rate.

It is pure offline post-processing — no GPU, no model calls. Stage-1/2/3 outputs
are already in the corpus JSONL; only the deterministic Stage-4 rule engine
(`evaluate_risk_zone`) is replayed with candidate thresholds.

Method:
  1. Split the 16 personas into a calibration set and a random 4-persona
     holdout (stratified by class, fixed seed) — the holdout is the genuine
     evaluation, never seen by the search (calibration-vs-evaluation rule).
  2. Univariate init: per behavioural score, pick the threshold separating
     YELLOW- from GREEN-designed day-points best (Youden's J), on calibration.
  3. Coordinate descent over the 5 primary thresholds + the YELLOW gate,
     maximising macro-F1 on calibration, constrained so fpr_on_green is not
     worse than the default-threshold engine on the same set.
  4. Report before/after on both splits; write threshold_optimization.json.
"""
import json
import os
import random
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))

# behavioral.* transitively builds config.Settings(); satisfy it without a DB.
for _k, _v in {
    "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x", "DB_HOST": "x",
    "DB_PORT": "5432", "LANGFUSE_PUBLIC_KEY": "x", "LANGFUSE_SECRET_KEY": "x",
    "LANGFUSE_API_HOST": "http://x", "API_BASE_URL": "http://x", "API_KEY": "x",
}.items():
    os.environ.setdefault(_k, _v)

from behavioral.risk_engine import evaluate_risk_zone, DEFAULT_YELLOW_TH  # noqa: E402
from behavioral.temporal import compute_baselines  # noqa: E402

CORPUS = HERE / "results" / "corpus"
BASELINE_FILES = ["20260518_234328_corpus_eval.jsonl"]  # deepseek-v3.2 full 16-persona
# corpus — chapter-4 E8/E9 working corpus; thematic calendar; raw predicts persisted.
# (prior gpt-oss-20b BASELINE_FILES preserved in git history / *.gptoss20b.json backups)
ZONES = ("GREEN", "YELLOW", "RED")
SCORES = ["topic_concentration", "emotional_attachment", "emotional_isolation",
          "social_isolation", "decision_delegation"]
PAIR_OFFSET = 0.1   # original tc/ei/ea single-vs-pair gap; kept uniform
GRID = [round(0.20 + 0.05 * i, 2) for i in range(12)]   # 0.20 .. 0.75
GREEN_FP_SLACK = 0.0   # optimised fpr_on_green must not exceed default + slack
SEED = 42


# ── coroutine driver (evaluate_risk_zone is async but never awaits) ──────────
def _run(coro):
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("evaluate_risk_zone unexpectedly awaited")


# ── data ─────────────────────────────────────────────────────────────────────
def load_rows() -> dict[str, list[dict]]:
    # dedup by (persona, day); later files win, so a re-run of a persona
    # supersedes its earlier partial rows (dmitry/rina completed corpus).
    by_key: dict[tuple[str, int], dict] = {}
    for f in BASELINE_FILES:
        for l in (CORPUS / f).read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                by_key[(r["persona"], r["day"])] = r
    by_persona: dict[str, list[dict]] = {}
    for r in by_key.values():
        by_persona.setdefault(r["persona"], []).append(r)
    for p in by_persona:
        by_persona[p].sort(key=lambda r: r["day"])
    return by_persona


def persona_class(rows: list[dict]) -> str:
    exp = [r["expected_zone"] for r in rows]
    if "RED" in exp:
        return "escalation"
    if "YELLOW" in exp:
        return "recovery" if exp[-1] == "GREEN" else "sustained_yellow"
    return "control"


def split_personas(by_persona: dict) -> tuple[list[str], list[str]]:
    """Random 4-persona holdout, stratified by class, fixed seed."""
    rng = random.Random(SEED)
    by_class: dict[str, list[str]] = {}
    for p, rows in by_persona.items():
        by_class.setdefault(persona_class(rows), []).append(p)
    for c in by_class:
        rng.shuffle(by_class[c])
    holdout: list[str] = []
    classes = sorted(by_class)
    i = 0
    while len(holdout) < 4:
        c = classes[i % len(classes)]
        if by_class[c]:
            holdout.append(by_class[c].pop())
        i += 1
    calib = sorted(p for p in by_persona if p not in holdout)
    return calib, sorted(holdout)


# ── replay & metrics ─────────────────────────────────────────────────────────
def expand(primaries: dict) -> dict:
    """Turn the 5 tuned primaries into the full DEFAULT_YELLOW_TH override."""
    th = dict(DEFAULT_YELLOW_TH)
    th["topic_concentration"] = primaries["topic_concentration"]
    th["emotional_attachment"] = primaries["emotional_attachment"]
    th["emotional_isolation"] = primaries["emotional_isolation"]
    th["social_isolation"] = primaries["social_isolation"]
    th["decision_delegation"] = primaries["decision_delegation"]
    th["tc_depr_pair"] = round(max(0.05, primaries["topic_concentration"] - PAIR_OFFSET), 2)
    th["ei_depr_pair"] = round(max(0.05, primaries["emotional_isolation"] - PAIR_OFFSET), 2)
    th["ea_iso_pair"] = round(max(0.05, primaries["emotional_attachment"] - PAIR_OFFSET), 2)
    return th


def replay(rows: list[dict], th: dict, gate: int) -> list[tuple[str, str]]:
    history: list[SimpleNamespace] = []
    pairs: list[tuple[str, str]] = []
    for r in rows:
        recent = list(reversed(history))[:7]
        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])
        zone, _ = _run(evaluate_risk_zone(
            r["temporal_metrics"], r["danger_class_agg"], r["behavioral_scores"],
            baselines=baselines, recent_history=recent, thresholds=th, yellow_gate=gate))
        pairs.append((r["expected_zone"], zone))
        history.append(SimpleNamespace(
            risk_zone=zone, danger_class_agg=r["danger_class_agg"],
            behavioral_scores=r["behavioral_scores"], temporal_metrics=r["temporal_metrics"]))
    return pairs


def metrics(pairs: list[tuple[str, str]]) -> dict:
    n = len(pairs)
    conf = {e: {p: 0 for p in ZONES} for e in ZONES}
    for e, p in pairs:
        conf[e][p] += 1
    f1 = {}
    for z in ZONES:
        tp = conf[z][z]
        fp = sum(conf[e][z] for e in ZONES if e != z)
        fn = sum(conf[z][p] for p in ZONES if p != z)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1[z] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    green = sum(conf["GREEN"].values())
    green_fp = green - conf["GREEN"]["GREEN"]
    return {
        "zone_match": round(sum(1 for e, p in pairs if e == p) / n, 4) if n else 0.0,
        "macro_f1": round(sum(f1.values()) / 3, 4),
        "per_zone_f1": {z: round(f1[z], 4) for z in ZONES},
        "fpr_on_green": round(green_fp / green, 4) if green else 0.0,
        "confusion": conf,
    }


def evaluate(personas: list[str], by_persona: dict, th: dict, gate: int) -> dict:
    pairs: list[tuple[str, str]] = []
    for p in personas:
        pairs += replay(by_persona[p], th, gate)
    return metrics(pairs)


# ── univariate init (Youden's J per score) ───────────────────────────────────
def youden_init(calib: list[str], by_persona: dict) -> dict:
    init = {}
    for score in SCORES:
        pos, neg = [], []   # YELLOW-designed vs GREEN-designed day-point values
        for p in calib:
            for r in by_persona[p]:
                v = r["behavioral_scores"].get(score, 0) or 0
                if r["expected_zone"] == "YELLOW":
                    pos.append(v)
                elif r["expected_zone"] == "GREEN":
                    neg.append(v)
        best_t, best_j = 0.5, -1.0
        cands = sorted({round(x, 2) for x in pos + neg})
        for t in cands:
            tpr = sum(1 for v in pos if v > t) / len(pos) if pos else 0.0
            fpr = sum(1 for v in neg if v > t) / len(neg) if neg else 0.0
            j = tpr - fpr
            if j > best_j:
                best_j, best_t = j, t
        init[score] = min(0.70, max(0.25, best_t))
    return init


# ── coordinate descent ───────────────────────────────────────────────────────
def optimise(calib: list[str], by_persona: dict, init: dict, fpr_cap: float) -> tuple[dict, int]:
    primaries = dict(init)
    gate = 2

    def score_of(prim, g):
        m = evaluate(calib, by_persona, expand(prim), g)
        # reject candidates that worsen GREEN false positives
        penalty = 0.0 if m["fpr_on_green"] <= fpr_cap else (m["fpr_on_green"] - fpr_cap) * 10
        return m["macro_f1"] - penalty, m

    best_obj, _ = score_of(primaries, gate)
    for _ in range(5):                       # passes until stable
        changed = False
        for key in SCORES + ["__gate__"]:
            if key == "__gate__":
                for g in (1, 2):
                    obj, _ = score_of(primaries, g)
                    if obj > best_obj + 1e-9:
                        best_obj, gate, changed = obj, g, True
            else:
                for v in GRID:
                    trial = dict(primaries)
                    trial[key] = v
                    obj, _ = score_of(trial, gate)
                    if obj > best_obj + 1e-9:
                        best_obj, primaries, changed = obj, trial, True
        if not changed:
            break
    return primaries, gate


# ── main ─────────────────────────────────────────────────────────────────────
def _fmt(m: dict) -> str:
    z = m["per_zone_f1"]
    return (f"zone_match={m['zone_match']:.3f}  macro_f1={m['macro_f1']:.3f}  "
            f"F1[G/Y/R]={z['GREEN']:.2f}/{z['YELLOW']:.2f}/{z['RED']:.2f}  "
            f"fpr_green={m['fpr_on_green']:.3f}")


def main() -> None:
    by_persona = load_rows()
    calib, holdout = split_personas(by_persona)
    print(f"calibration ({len(calib)}): {calib}")
    print(f"holdout     ({len(holdout)}): {holdout}\n")

    default_prim = {s: DEFAULT_YELLOW_TH[s] for s in SCORES}
    base_calib = evaluate(calib, by_persona, DEFAULT_YELLOW_TH, 2)
    base_hold = evaluate(holdout, by_persona, DEFAULT_YELLOW_TH, 2)
    print("DEFAULT thresholds")
    print(f"  calibration : {_fmt(base_calib)}")
    print(f"  holdout     : {_fmt(base_hold)}\n")

    fpr_cap = base_calib["fpr_on_green"] + GREEN_FP_SLACK
    init = youden_init(calib, by_persona)
    print(f"Youden init: {init}\n")

    primaries, gate = optimise(calib, by_persona, init, fpr_cap)
    th = expand(primaries)
    opt_calib = evaluate(calib, by_persona, th, gate)
    opt_hold = evaluate(holdout, by_persona, th, gate)
    print(f"OPTIMISED thresholds (gate={gate})")
    for k in SCORES:
        print(f"  {k:22s} {DEFAULT_YELLOW_TH[k]} -> {primaries[k]}")
    print(f"  calibration : {_fmt(opt_calib)}")
    print(f"  holdout     : {_fmt(opt_hold)}")
    overfit = opt_calib["macro_f1"] - opt_hold["macro_f1"]
    print(f"\n  calibration-minus-holdout macro_f1 gap: {overfit:+.3f}"
          f"  ({'watch for overfit' if overfit > 0.10 else 'ok'})")

    out = {
        "method": "youden-init + coordinate-descent, calibration-vs-holdout split",
        "seed": SEED, "calibration_personas": calib, "holdout_personas": holdout,
        "fpr_on_green_cap": fpr_cap, "yellow_gate": gate,
        "default_primaries": default_prim, "optimised_primaries": primaries,
        "optimised_thresholds_full": th,
        "metrics": {
            "default": {"calibration": base_calib, "holdout": base_hold},
            "optimised": {"calibration": opt_calib, "holdout": opt_hold},
        },
    }
    (HERE / "results" / "threshold_optimization.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print("\nwrote results/threshold_optimization.json")


if __name__ == "__main__":
    main()
