#!/usr/bin/env python3
"""Consolidate chapter-4 corpus runs into per-run and per-persona metrics.

Reads the per-row JSONL files produced by evaluate_corpus.py, regroups by
persona, and prints zone-match / macro-F1 / per-zone-F1 / confusion / FPR plus
a per-persona trajectory table. The clean 16-persona baseline is the qwen36 E6
leg (11 personas) merged with the qwen36 top-up (5 personas).
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "results" / "corpus"
ZONES = ("GREEN", "YELLOW", "RED")


def load_rows(name: str) -> list[dict]:
    return [json.loads(l) for l in (CORPUS / name).read_text().splitlines() if l.strip()]


def metrics(rows: list[dict]) -> dict:
    by_persona: dict[str, list[dict]] = {}
    for r in rows:
        by_persona.setdefault(r["persona"], []).append(r)

    n = len(rows)
    matched = sum(1 for r in rows if r["match"])
    conf = {e: {p: 0 for p in ZONES} for e in ZONES}
    for r in rows:
        conf[r["expected_zone"]][r["predicted_zone"]] += 1

    f1 = {}
    for z in ZONES:
        tp = conf[z][z]
        fp = sum(conf[e][z] for e in ZONES if e != z)
        fn = sum(conf[z][p] for p in ZONES if p != z)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1[z] = round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0

    green = [r for r in rows if r["expected_zone"] == "GREEN"]
    false_alarm = sum(1 for r in green if r["predicted_zone"] != "GREEN")

    per_persona = {}
    for p, prs in sorted(by_persona.items()):
        prs = sorted(prs, key=lambda r: r["day"])
        exp = [r["expected_zone"] for r in prs]
        pred = [r["predicted_zone"] for r in prs]
        first_red = next((prs[i]["day"] for i, z in enumerate(pred) if z == "RED"), None)
        exp_first_red = next((prs[i]["day"] for i, z in enumerate(exp) if z == "RED"), None)
        if "RED" in exp:
            cls = "escalation"
        elif "YELLOW" in exp:
            cls = "recovery" if exp[-1] == "GREEN" else "sustained_yellow"
        else:
            cls = "control"
        per_persona[p] = {
            "class": cls,
            "days": len(prs),
            "zone_match": round(sum(1 for r in prs if r["match"]) / len(prs), 3),
            "trajectory_exact": exp == pred,
            "expected_first_red": exp_first_red,
            "predicted_first_red": first_red,
            "clf_failed": sum(r["n_classifier_failed"] for r in prs),
        }

    return {
        "n_day_points": n,
        "n_personas": len(by_persona),
        "zone_match_rate": round(matched / n, 4) if n else 0.0,
        "macro_f1": round(sum(f1.values()) / 3, 4),
        "per_zone_f1": f1,
        "fpr_on_green": round(false_alarm / len(green), 4) if green else None,
        "confusion": conf,
        "full_trajectory_match_rate": round(
            sum(1 for v in per_persona.values() if v["trajectory_exact"]) / len(per_persona), 4
        ),
        "clf_failed_total": sum(r["n_classifier_failed"] for r in rows),
        "n_sessions": sum(r["n_sessions"] for r in rows),
        "per_persona": per_persona,
    }


RUNS = {
    "baseline_16p_clean (qwen36, local)": ["20260518_143235_corpus_eval.jsonl",
                                           "20260518_193121_corpus_eval.jsonl"],
    "e6_qwen36_11p (local)": ["20260518_143235_corpus_eval.jsonl"],
    "e6_deepseek_11p (local)": ["20260518_160619_corpus_eval.jsonl"],
    "baseline_16p_DEGRADED (qwen36, openrouter)": ["20260518_140411_corpus_eval.jsonl"],
}


def main() -> None:
    out = {}
    for label, files in RUNS.items():
        rows = []
        for f in files:
            rows += load_rows(f)
        out[label] = metrics(rows)

    for label, m in out.items():
        print(f"\n{'=' * 78}\n{label}")
        print(f"  {m['n_personas']} personas, {m['n_day_points']} day-points, "
              f"{m['n_sessions']} sessions, clf_failed={m['clf_failed_total']}")
        print(f"  zone_match={m['zone_match_rate']}  macro_f1={m['macro_f1']}  "
              f"fpr_on_green={m['fpr_on_green']}  full_traj={m['full_trajectory_match_rate']}")
        print(f"  per_zone_f1={m['per_zone_f1']}")
        print(f"  confusion (expected x predicted):")
        for e in ZONES:
            print(f"    {e:6s} -> " + "  ".join(f"{p}:{m['confusion'][e][p]:3d}" for p in ZONES))
        if "baseline_16p_clean" in label or "deepseek" in label:
            print(f"  per-persona:")
            for p, v in m["per_persona"].items():
                print(f"    {p:9s} {v['class']:16s} d={v['days']:2d} "
                      f"match={v['zone_match']:.2f} exact={str(v['trajectory_exact']):5s} "
                      f"first_red exp={v['expected_first_red']} pred={v['predicted_first_red']} "
                      f"clf_fail={v['clf_failed']}")

    (HERE / "results" / "chapter4_consolidated.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nwrote results/chapter4_consolidated.json")


if __name__ == "__main__":
    main()
