# Behavioral Monitoring System — Code Review

**Project:** Safe LLM — Psychological Safety of Conversational AI
**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`
**Last updated:** 2026-04-04
**Tests:** 95 passing (8 test files)
**Code:** ~1735 lines in `ai-safety-dev/src/behavioral/` + middleware

---

## Milestone Completion

| Milestone | Status | Files | Tests |
|-----------|--------|-------|-------|
| M0: Design & Spec | Done | roadmap-v3.md | — |
| M1: Data Model + Skeleton | Done | models.py, repository.py, aggregator.py, scheduler.py, config.py, main.py | 17 |
| M2: Temporal Metrics | Done | temporal.py | 22 |
| M3: Danger Class Aggregation | Done | danger_agg.py | 10 |
| M4: Behavioral LLM + Summary | Done | behavioral_llm.py | 13 |
| M5: Risk Engine + Middleware | Done | risk_engine.py, middleware.py | 29 (18 engine + 11 middleware) |
| M6: Weekly Report | Done | weekly_report.py, langfuse_scores.py | 4 |

---

## Spec Compliance (Roadmap v3)

| Spec Section | Status | Notes |
|-------------|--------|-------|
| UserBehaviorProfile (8 columns) | Matches | FK removed for dev flexibility |
| MetricsHistory (8 columns) | Matches | |
| DailySummary (11 columns + UniqueConstraint) | Matches | UPSERT logic fixed (was INSERT only) |
| BehavioralEvents (7 columns) | Matches | |
| Stage 1: 6 temporal metrics | Matches | `messages_last_1h` removed (unused by any rule) |
| Stage 1: 7-day baselines | Matches | |
| Stage 1: Trend detection | Matches | 50% threshold for trending_up |
| Stage 2: 9 danger metrics | Matches | |
| Stage 3: Prompt template | Matches | |
| Stage 3: Calendar format + filtering | Matches | All 5 filtering rules implemented |
| Stage 3: 4 behavioral scores | Matches | |
| Stage 3: Daily summary (6 fields) | Matches | |
| Stage 3: Configurable LLM backend | Matches | BEHAVIORAL_LLM_MODEL via litellm.acompletion |
| Stage 3: Failure handling (carry-forward) | Matches | |
| Stage 4: YELLOW triggers (6 rules) | Matches | +1 added: delusion_flag_rate sustained |
| Stage 4: RED triggers (5 rules) | Matches | |
| Soft middleware (YELLOW/RED prompts) | Matches | |
| Weekly report (5 sections) | Matches | Human-readable trigger explanations added |
| Langfuse score integration | Matches | risk_zone + 4 behavioral scores on traces |
| Aggregator pipeline (4 stages sequential) | Matches | |
| Scheduler (daily batch) | Matches | CronTrigger 00:30 UTC / 60s dev |

**Known deviation:** BehavioralEvent write only on zone change (spec says "or RED trigger"). Acceptable — re-triggering same RED rule doesn't add value without new information.

---

## Design Choices (intentional, not issues)

| Choice | Spec says | Code does | Rationale |
|--------|-----------|-----------|-----------|
| activity_by_hour keys | `{0: N, ...}` (int) | `{"0": N, ...}` (string) | JSON round-trip converts int->string in PostgreSQL |
| Message fetch window | "last 20 user messages" | Last 20 within 7-day window | Performance safeguard for sparse users |
| Trend threshold | "trending up" | >50% above baseline | Spec didn't define percentage |
| Emotional tone matching | Not specified | `.lower().strip()` | LLM may capitalize |
| FK constraints | FK to LiteLLM_UserTable | No FK | Dev testing users don't exist in LiteLLM_UserTable |
| Night hours | Not precisely defined | Hours 1-5 UTC | User's definition |

---

## Bugs Fixed

### Critical & Important (implementation)

| # | Date | Severity | File | Problem | Fix |
|---|------|----------|------|---------|-----|
| C1 | 03-24 | Critical | repository.py | Reused closed SQLAlchemy session across calls | Session factory, fresh session per call |
| C2 | 03-24 | Critical | behavioral_llm.py | LLM parser didn't validate all score keys | Added validation + summary defaults |
| I2 | 03-24 | Important | aggregator.py | `date.today()` used local TZ instead of UTC | `datetime.now(UTC).date()` |
| I3 | 03-24 | Important | scheduler.py | Queried ALL historical users | Added 48h activity filter |
| I5 | 03-24 | Important | temporal.py | Integer activity_by_hour keys break after JSON | String keys from start |
| I6 | 03-24 | Important | aggregator.py | is_notable tone check was case-sensitive | `.lower().strip()` |

### Bugs in Mikhail's code (fixed during review)

| # | Date | Severity | File | Problem | Fix |
|---|------|----------|------|---------|-----|
| M1 | 03-25 | Critical | scheduler.py + repository.py | `last_time_recorded_by_all_users` missing `created_at`; per-user jobs ran same global task | Single global task, added `created_at` to SELECT |
| M2 | 03-25 | Important | middleware.py | `_extract_user_text` returned `None` | Returns `""` |
| M3 | 03-25 | Important | repository.py | Redundant `commit()` inside `begin()` context manager | Removed |
| M4 | 03-25 | Important | langfuse_scraper.py | No error handling for nested metadata access | Added try/except per session |

### Server deployment bugs (end-to-end debugging)

| # | Date | Error | Root cause | Fix | Commit |
|---|------|-------|-----------|-----|--------|
| S1 | 03-29 | `offset-naive and offset-aware datetimes` | SpendLogs uses TIMESTAMP WITHOUT TZ, code used `datetime.now(UTC)` | Naive datetimes | `7b0a2fe` |
| S2 | 03-29 | SpendLogs.messages always `{}` | LiteLLM v1.81.8 doesn't write messages by default | Config + proxy_server_request fallback | `0fc0b31`, `8ff6d99` |
| S3 | 03-29 | end_user always empty | Playground doesn't send `user` field | Fallback chain: payload -> header -> "default_user" | `b3617d7` |
| S4 | 03-29 | Messages still empty after config fix | proxy_server_request not always populated | Langfuse traces as primary fallback | `b2ec6af` |
| S5 | 03-29 | `ForeignKeyViolationError` on MetricsHistory | end_user_id not in LiteLLM_UserTable | Removed FK constraints | `5d284aa` |
| S6 | 03-29 | `AuthenticationError` in Stage 3 | behavioral_llm.py didn't pass api_key | Added api_key + base_url | `8b593bc` |
| S7 | 03-29 | `BadRequestError: LLM Provider NOT provided` | Used alias instead of full model name | Switched to nemotron-3-super | `9bedcd2` |
| S8 | 03-29 | `UniqueViolationError` on DailySummary | `merge()` didn't find existing by PK | Full upsert: SELECT then UPDATE/INSERT | `9bedcd2` |
| S9 | 03-29 | Playground not intercepted | Middleware only matched `/v1/chat/completions` | Added `/chat/completions` path | `2d521b6` |

---

## Improvements (post-review)

| # | Date | Improvement | Rationale |
|---|------|-------------|-----------|
| 1 | 03-29 | Soft prompt effectiveness test script | Proves YELLOW/RED prompts change LLM behavior |
| 2 | 03-29 | Langfuse score integration | risk_zone + 4 scores visible in Langfuse dashboard |
| 3 | 03-29 | Human-readable trigger explanations | 13 rules with actual values instead of raw thresholds |
| 4 | 03-29 | Removed `messages_last_1h` metric | Computed but unused by any risk rule |
| 5 | 03-29 | Added `delusion_flag_rate` YELLOW rule | Sustained >0.2 for 3+ days. 3 new tests |
| 6 | 03-29 | Silent days preserve risk zone | Aggregator skips users with 0 messages |
| 7 | 03-29 | Guardrails refactored | Binary classifier tags only, no blocking. Middleware handles both |
| 8 | 03-29 | Langfuse SDK unified | Replaced httpx with SDK in scraper |
| 9 | 03-29 | Dead code removed | SYCOPHANCY prompt (120 lines), unused imports |

---

## Refactoring

| Date | What | Before | After |
|------|------|--------|-------|
| 03-29 | Middleware name | `BinaryUserSafetyGuardrailMiddleware` | `BehavioralSafetyMiddleware` |
| 03-29 | Langfuse scraper | httpx + manual pagination | `from langfuse import Langfuse` SDK |
| 03-29 | Guardrail architecture | `custom_guardrails.py` (native LiteLLM) | Middleware-only (archived) |
| 03-29 | Middleware paths | `/v1/chat/completions` only | Both `/v1/chat/completions` and `/chat/completions` |

---

## Test Coverage

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| test_behavioral_models.py | 6 | Model instantiation for all 4 tables |
| test_aggregator_skeleton.py | 11 | Pipeline orchestration + is_notable logic (8 edge cases) |
| test_temporal_metrics.py | 22 | All 6 metrics + baselines + trends + edge cases |
| test_danger_agg.py | 10 | JSON parsing + aggregation + max_class_avg |
| test_behavioral_llm.py | 13 | Prompt building + response parsing + LLM call + carry-forward |
| test_risk_engine.py | 18 | All YELLOW/RED rules incl. delusion_flag_rate sustained |
| test_middleware_behavioral.py | 11 | Soft prompt injection for GREEN/YELLOW/RED |
| test_weekly_report.py | 4 | Report generation + trigger explanations |
| **Total** | **95** | |

### Untested areas (known, acceptable)

- Database round-trip operations (repository methods always mocked)
- Scheduler user discovery (relies on SpendLogs queries)
- `_fetch_spendlogs_rows` and `_fetch_predict_rows` (always mocked)
- Langfuse fallback path (tested manually on server)
- End-to-end with real data (tested manually, documented in server bugs above)

---

## End-to-End Verification (03-29)

Full pipeline confirmed working on server after all fixes:

```
Playground message "умоляю работай"
  -> middleware: safety_verdict:0, end_user=default_user
  -> SpendLogs: row created
  -> Aggregator (60s later):
     Stage 1: Langfuse fallback -> 1 msg, 1 active hour
     Stage 2: all zeros (no PredictTable data)
     Stage 3: Nemotron -> topic=0.9, delegation=0.8, isolation=0.6, attachment=0.85
     Stage 4: YELLOW (topic_concentration>0.7 + decision_delegation>0.4)
  -> DailySummary written, UserBehaviorProfile=YELLOW
  -> Langfuse scores written
  -> Next request: YELLOW prompt injected
```

Verified in Langfuse:
- `userId: "default_user"` — middleware works
- `tags: ["safety_verdict:0"]` — binary classifier works
- Input contains YELLOW system prompt — soft middleware works
- Scores on trace: `risk_zone=YELLOW`, all 4 behavioral scores — Langfuse integration works
- Calendar in Stage 3 prompt — cross-day references work

---

## Open Items / Backlog

| Item | Priority | Notes |
|------|----------|-------|
| BehavioralEvent on repeated RED triggers | Low | Currently only on zone change |
| Silent user detection ("user_gone_silent") | Medium | RED user silent 2+ days = isolation signal |
| PredictTable sometimes empty | Low | Depends on Mikhail's scraper having data |
| Synthetic experiment validation | High | Next step: run all 11 personas, verify zone trajectories |
| eRisk correlation analysis | Medium | 909 real users for external validation |

---

## Changelog

| Date | Review activity |
|------|----------------|
| 2026-03-24 | Code review M1-M4 vs spec. 62 tests passing. Found 6 bugs (C1, C2, I2, I3, I5, I6) |
| 2026-03-25 | M5-M6 review. All 6 milestones complete. 91 tests. Found 4 bugs in Mikhail's code |
| 2026-03-25 | Gap analysis: 5 improvements identified and implemented |
| 2026-03-29 | Guardrails refactoring review. Architecture simplified |
| 2026-03-29 | Server deployment: 9 bugs found and fixed during end-to-end testing |
| 2026-03-29 | End-to-end pipeline verified working on server |
| 2026-04-04 | Consolidated all reviews into single document. 95 tests |
