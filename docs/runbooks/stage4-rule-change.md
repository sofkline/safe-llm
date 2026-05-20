# Stage-4 rule change protocol

A small ritual to keep changes to `risk_engine.py` (or to the corpus they consume)
from quietly regressing other personas while we fix one. Apply to:

- any edit to `_check_red_triggers` or `_check_yellow_triggers`
- any threshold change in `DEFAULT_YELLOW_TH`
- any change to the zone-combination logic in `evaluate_risk_zone`
- any edit to a persona's `.edited.jsonl` corpus (because that shifts the inputs
  the rules see — same blast radius as a rule change)

Two non-negotiables baked in:

- **Never change a Stage-4 threshold or rule based on a single (persona, day).**
  The baseline diff in `Before` is required before committing.
- **The regression test in `Change` must be derived from the actual decision-log
  entry of the failing day, not handwritten.** Handwritten fixtures encode the
  fix you wanted, not the input that broke.

## Before

**Name the failure case.** One sentence: persona + day(s) + observed zone +
expected zone + smallest reproducer. The reproducer is a path into a decision
log (see `risk_engine._maybe_log_decision`):

```
$ RISK_DECISION_LOG=results/decisions/viktor_baseline.jsonl \
    python3 experiments/rerun_authored_calendar.py --persona viktor
$ jq 'select(.day==4)' results/decisions/viktor_baseline.jsonl
```

**Snapshot the baseline.** Re-run the authored-calendar rerun for every persona
that has an authored calendar (today: viktor, nastya). Save a flat trajectory
CSV keyed by `git rev-parse --short HEAD`:

```
$ for p in viktor nastya; do
    RISK_DECISION_LOG=results/decisions/${p}_$(git rev-parse --short HEAD).jsonl \
      python3 experiments/rerun_authored_calendar.py --persona $p
  done
$ python3 experiments/dump_trajectories.py \
    > results/rule_baseline_$(git rev-parse --short HEAD).csv
```

(`dump_trajectories.py` reads the per-persona `*_authored_rerun.json` files and
emits one row per `(persona, day)` with columns `expected, predicted, match,
triggered_rules`. If it doesn't exist yet, write it as the first step.)

**Predict the diff.** Open the baseline CSV. For every `(persona, day)` you
expect to change, add two columns: `expected_after`, `reason`. For every
`(persona, day)` you expect to *not* change, leave them blank. Commit the
prediction alongside the baseline so the audit step (`After`) has something
falsifiable to check against.

## Change

**Regression test first.** Pull the failing day's decision-log entry verbatim
into `tests/test_risk_engine.py` as a fixture. Assert the expected zone after
the fix. The test stays in the suite forever — it is the contract that this
particular (persona, day) does not regress again. Example:

```python
# Captured from results/decisions/viktor_baseline.jsonl, day 4, before fix.
VIKTOR_DAY4_INPUTS = {
    "behavioral": {"topic_concentration": 0.7, "emotional_isolation": 0.7, ...},
    "danger":     {"max_class_avg": 0.0, ...},
    "temporal":   {...},
}

async def test_viktor_day4_grief_disclosure_stays_yellow():
    z, _ = await evaluate_risk_zone(
        VIKTOR_DAY4_INPUTS["temporal"],
        VIKTOR_DAY4_INPUTS["danger"],
        VIKTOR_DAY4_INPUTS["behavioral"],
        recent_history=[],
    )
    assert z == "YELLOW"
```

**Edit the rule.** One rule per commit. Commit message follows the form:

```
stage4: <rule-or-threshold-name> — <one-line intent>

Failure case: viktor day 4 (grief disclosure) over-escalated to RED.
Baseline: results/rule_baseline_<sha>.csv
Predicted diff: results/rule_diff_<sha>.csv
```

## After

**Re-run, diff trajectories.** Same script as `Before`, new CSV. Compute the
diff against the baseline (any `(persona, day)` where `predicted` changed).

**Audit every changed cell.** Walk down the diff. For each row:

- *Was this in the predicted-diff list?* If yes ✓.
- *Did it match the prediction's `expected_after`?* If yes ✓.
- Otherwise: investigate. **A non-predicted regression on any (persona, day)
  that was previously correct is a stop-the-world condition** — back out the
  change, refine the hypothesis, repeat from `Before`.

**Account for rerun noise.** The deepseek classifier is not perfectly
deterministic at temperature=0.0 — captured shift of ±0.05 on a single Stage-3
score is normal. A zone change on a day *not* in the predicted-diff list, with
no obvious mechanism, should be re-run once to confirm before being treated as
a regression. Conversely: a baseline day passing "correctly" can be passing by
chance — the predicted-diff document should call out which baseline successes
are robust vs. marginal.

**Net zone-match delta per persona.** Compute `Δ zone_match = new − baseline`
for each persona. Must be ≥ 0 for personas you were not targeting. A decrease
on a non-target persona means the rule generalized worse than intended.

**Update the writeup.** If the change is large enough to mention in the thesis
chapter, note it in the appendix experiment-artifacts table with the baseline
SHA and the new SHA.

## Why this ceremony for a thesis pipeline

Two reasons. First, every rule we tune by hand on Viktor implicitly trades off
behaviour on Nastya, Sara, Igor, etc. — we don't see that cost unless we make
the baseline visible. Second, when the chapter says "the rule engine over-fires
on grief-disclosure days", we want to be able to point at a specific decision
record (`viktor`, day 4, `2026-03-13`, `behavioral={...}`, fired rule X) rather
than gesture vaguely. The decision log is what makes the chapter's claims
falsifiable.
