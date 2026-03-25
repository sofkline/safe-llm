# Code Review: Milestones 1-4 vs Roadmap v3 Spec

**Date:** 2026-03-24
**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`
**Scope:** All implemented code in `ai-safety-dev/src/behavioral/` + related files
**Tests:** 62 tests passing

---

## Spec Compliance Summary

| Section | Status | Details |
|---------|--------|---------|
| Data Model — UserBehaviorProfile | ✅ Matches | All 8 columns, types, defaults correct |
| Data Model — MetricsHistory | ✅ Matches | All 8 columns correct |
| Data Model — DailySummary | ✅ Matches | All 11 columns + UniqueConstraint correct |
| Data Model — BehavioralEvents | ✅ Matches | All 7 columns correct |
| Stage 1 — Temporal Metrics (7 metrics) | ✅ Matches | All field names, windows, computations correct |
| Stage 1 — 7-day baselines | ✅ Matches | Rolling avg from MetricsHistory |
| Stage 1 — Trend detection | ✅ Matches | interval_shrinking, message_count_trending_up |
| Stage 2 — Danger Class Aggregation (9 metrics) | ✅ Matches | All avg/max/flag_rate + max_class_avg correct |
| Stage 3 — Prompt template | ✅ Matches | Date, messages, calendar, JSON schema all correct |
| Stage 3 — Calendar format | ✅ Matches | Compact single-line-per-day, omitted when empty |
| Stage 3 — Calendar filtering rules | ✅ Matches | All 5 rules implemented |
| Stage 3 — 4 behavioral scores | ✅ Matches | topic_concentration, decision_delegation, social_isolation, emotional_attachment |
| Stage 3 — Daily summary structure | ✅ Matches | All 6 fields correct |
| Stage 3 — Configurable LLM backend | ✅ Matches | BEHAVIORAL_LLM_MODEL in config, used via litellm.acompletion |
| Stage 3 — Failure handling | ✅ Matches | Carry forward previous scores, placeholder summary |
| Stage 3 — Last 20 messages | ✅ Matches | AI responses stripped via _extract_last_user_message |
| Stage 4 — Risk engine stub | ✅ Matches | Returns GREEN, correct interface for Milestone 5 |
| Weekly report stub | ✅ Matches | Placeholder for Milestone 6 |
| Aggregator pipeline — 4 stages sequential | ✅ Matches | Correct order, awaited sequentially |
| Aggregator — post-stage writes | ⚠️ Minor deviation | Zone change events only (see I1 below) |
| Module structure | ✅ Matches | All 10 files present per spec |
| Scheduler — daily batch | ✅ Matches | CronTrigger 00:30 UTC (prod), 30s (dev) |
| main.py wiring | ✅ Matches | Lifespan hooks correct |
| Config — BEHAVIORAL_LLM_MODEL | ✅ Matches | Present with default |

---

## Issues Found

### Important (1)

**I1. BehavioralEvent write condition incomplete**
- **Spec (line 375):** "If zone changed or RED trigger → write BehavioralEvent"
- **Code (`aggregator.py:112`):** Only checks `risk_zone != old_zone`
- **Impact:** If user stays RED but triggers a new RED rule, no event is recorded
- **Fix:** Add `or risk_zone == "RED"` check, or log specific trigger combination even when zone unchanged
- **When to fix:** Milestone 5 (Risk Zone Engine), when triggers are fully implemented

---

## Design Choices (documented, not issues)

| Choice | Spec says | Code does | Rationale |
|--------|-----------|-----------|-----------|
| activity_by_hour keys | `{0: N, ...}` (integer) | `{"0": N, ...}` (string) | JSON round-trip converts int→string in PostgreSQL; using strings from start avoids KeyError |
| Message fetch window | "last 20 user messages" | Last 20 within 7-day window | Performance safeguard for sparse users; prevents scanning entire history |
| Trend flag threshold | "trending up vs 7d baseline" | >50% above baseline | Spec doesn't define "trending up" percentage; 50% is reasonable default |
| trend_flags persistence | Not specified | Logged only, not stored | Will be needed by risk engine in Milestone 5; can be added then |
| Emotional tone matching | Not specified | Case-insensitive `.lower().strip()` | LLM may capitalize; prevents false notable flags |

---

## Milestone Completion Status

| Milestone | Status | Evidence |
|-----------|--------|----------|
| M0: Design & Spec | ✅ Complete | `2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` |
| M1: Data Model + Skeleton | ✅ Complete | 4 tables, 10 module files, scheduler wired, config added |
| M2: Temporal Metrics | ✅ Complete | 7 metrics + baselines + trends, 22 tests |
| M3: Danger Class Aggregation | ✅ Complete | 9 metrics from PredictTable, 10 tests |
| M4: Behavioral Batch LLM | ✅ Complete | LLM call + parse + carry-forward + calendar, 13 tests |
| M5: Risk Zone Engine + Middleware | ⏳ Not started | Stub returns GREEN |
| M6: Weekly Report | ⏳ Not started | Stub returns placeholder |

---

## Bugs Fixed During Review

Prior to this review, a separate code quality review identified and fixed 6 issues:

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| C1 | Critical | Repository reused closed session across method calls | Store session factory, create fresh session per call |
| C2 | Critical | LLM response parser didn't validate all score keys present | Added validation + summary key defaults |
| I2 | Important | `date.today()` used local timezone instead of UTC | Changed to `datetime.now(UTC).date()` |
| I3 | Important | Scheduler queried ALL historical users | Added 48h activity filter |
| I5 | Important | activity_by_hour integer keys break after JSON round-trip | Changed to string keys |
| I6 | Important | is_notable tone check was case-sensitive | Added `.lower().strip()` |

---

## Test Coverage

| Test file | Tests | Coverage |
|-----------|-------|----------|
| test_behavioral_models.py | 6 | Model instantiation for all 4 tables |
| test_aggregator_skeleton.py | 11 | Pipeline orchestration + is_notable logic (8 edge cases) |
| test_temporal_metrics.py | 22 | All 7 metrics + baselines + trends + edge cases |
| test_danger_agg.py | 10 | JSON parsing + aggregation + max_class_avg |
| test_behavioral_llm.py | 13 | Prompt building + response parsing + LLM call + carry-forward |
| **Total** | **62** | |

### Untested areas (acceptable for current milestone):
- Database round-trip operations (repository methods always mocked)
- Scheduler user discovery
- `_fetch_spendlogs_rows` and `_fetch_predict_rows` (always mocked)
- End-to-end pipeline with real data
