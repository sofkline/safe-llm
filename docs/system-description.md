# Behavioral Monitoring System — System Description

**Project:** Safe LLM — Psychological Safety of Conversational AI
**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`
**Last updated:** 2026-04-04

---

## Overview

The system monitors user behavior patterns in LLM conversations to detect signs of emotional distress, unhealthy AI dependency, and psychological risk. It operates as an extension to a LiteLLM proxy, combining real-time message tagging with daily batch analysis.

**Key design decisions:**
- **Soft intervention, not blocking** — safety prompts are injected for at-risk users; messages are never blocked
- **Daily batch, not real-time** — behavioral patterns are daily phenomena; aggregator runs once per day at 00:30 UTC
- **Rule-based risk zones** — GREEN / YELLOW / RED, determined by threshold rules on temporal, danger, and behavioral metrics
- **Configurable LLM backend** — `BEHAVIORAL_LLM_MODEL` via LiteLLM routing (Ollama, OpenRouter, OpenWebUI)

---

## Two Data Flows

```
FLOW 1: Every request (real-time, ~100ms)
  User -> middleware.py -> binary classify -> tag -> risk_zone lookup -> soft prompt -> LLM

FLOW 2: Once per day (batch, ~30-60s per user)
  scheduler -> aggregator -> Stage 1-4 -> write DB -> Langfuse scores
```

---

## Flow 1: Per-Message Processing

**File:** `ai-safety-dev/src/middleware.py` — `BehavioralSafetyMiddleware.dispatch()`

```
User message arrives
        |
        v
1. Path filter: POST /v1/chat/completions or /chat/completions?
   Yes -> continue
        |
        v
2. Parse JSON body, extract user text
   _extract_user_text(payload) -> "мне так плохо, помоги"
        |
        v
3. Binary classification (classificators.input_classification)
   Sends to judge model: system=POLICY + user=message
   Returns: "0" (safe) or "1" (unsafe)
   -> metadata.tags: ["safety_verdict:0"]
        |
        v
4. Determine end_user
   payload["user"] || headers["x-openwebui-user-id"] || "default_user"
   -> payload["user"] = end_user (so LiteLLM records it in SpendLogs)
        |
        v
5. Risk zone lookup (behavioral/repository.get_risk_zone)
   SELECT risk_zone FROM UserBehaviorProfile WHERE end_user_id = ?
        |
        v
6. Soft prompt injection (_inject_risk_zone_prompt)
   GREEN  -> no modification
   YELLOW -> prepend: "This user may be developing an unhealthy interaction pattern..."
   RED    -> prepend: "This user shows signs of significant emotional distress..."
        |
        v
7. Reassemble body, forward to LiteLLM proxy -> LLM -> response
```

---

## Flow 2: Daily Aggregation

### Scheduler

**File:** `ai-safety-dev/src/behavioral/scheduler.py` — `_run_daily_aggregation()`

- **Production:** CronTrigger at 00:30 UTC
- **Dev mode:** every 60 seconds
- Discovers active users: `SELECT DISTINCT end_user FROM SpendLogs WHERE startTime >= NOW() - 48h`
- Filters empty user IDs
- Runs `run_aggregator_for_user()` for each

### Aggregator Pipeline

**File:** `ai-safety-dev/src/behavioral/aggregator.py` — `run_aggregator_for_user()`

Four stages execute sequentially. If `daily_message_count == 0`, the aggregator skips the user (preserving existing risk zone — silent days don't reset to GREEN).

---

### Stage 1: Temporal Metrics

**File:** `ai-safety-dev/src/behavioral/temporal.py` — `compute_temporal_metrics()`

Computes 6 metrics from the last 24h of user activity:

| Metric | Field | Description |
|--------|-------|-------------|
| Message count | `daily_message_count` | Total messages in 24h |
| Hourly distribution | `activity_by_hour` | Histogram `{"0": N, ..., "23": N}` |
| Night messages | `night_messages` | Messages during hours 1-5 UTC |
| Active hours | `daily_active_hours` | Distinct hours with >=1 message |
| Avg prompt length | `avg_prompt_length_chars` | Mean character length of messages |
| Inter-message interval | `avg_inter_message_interval_min` | Mean time gap between messages |

**Data source priority:** SpendLogs -> `proxy_server_request` fallback -> Langfuse traces fallback.

**Baselines & trends** (computed in aggregator):
- 7-day rolling averages from MetricsHistory
- Trend flags: `message_count_trending_up` (>50% above baseline), `interval_shrinking` (>30% decrease from baseline)

---

### Stage 2: Danger Class Aggregation

**File:** `ai-safety-dev/src/behavioral/danger_agg.py` — `compute_danger_class_agg()`

Aggregates 5-class danger scores from PredictTable (filled hourly by Mikhail's scraper):

| Class | Metrics computed |
|-------|-----------------|
| self_harm | avg, max, flag_rate |
| psychosis | avg |
| delusion | avg, flag_rate |
| obsession | avg |
| anthropomorphism | avg |
| (cross-class) | `max_class_avg` = MAX of all 5 avg values |

---

### Stage 3: Behavioral LLM + Daily Summary

**File:** `ai-safety-dev/src/behavioral/behavioral_llm.py` — `compute_behavioral_scores_and_summary()`

Calls a configurable LLM (default: Nemotron) with last 20 user messages + calendar of notable previous days. Produces:

**4 behavioral scores (0.0-1.0):**

| Score | What it measures |
|-------|-----------------|
| `topic_concentration` | Share of messages on a single narrow topic |
| `decision_delegation` | Share of messages asking AI to decide |
| `social_isolation` | Isolation indicators in messages |
| `emotional_attachment` | Emotional attachment expressions toward AI |

**Daily summary structure:**

| Field | Description |
|-------|-------------|
| `key_topics` | Main topics discussed today |
| `life_events` | Significant events mentioned |
| `emotional_tone` | Short emotional state description |
| `ai_relationship_markers` | Signs of AI relationship dynamics |
| `notable_quotes` | Up to 3 significant user quotes (original language) |
| `operator_note` | 1-3 sentences connecting today to calendar history |

**Calendar filtering:** A day is included if it has life_events, ai_relationship_markers, non-neutral tone, or any score above YELLOW threshold.

**Failure handling:** Carry forward previous scores; summary gets placeholder.

---

### Stage 4: Risk Zone Engine

**File:** `ai-safety-dev/src/behavioral/risk_engine.py` — `evaluate_risk_zone()`

Rule-based classification using outputs from Stages 1-3.

**YELLOW triggers (any 2 required):**

| Trigger | Threshold |
|---------|-----------|
| Night activity | `night_messages` > 24 |
| High frequency + growing | `daily_message_count` > 50 AND trending up |
| Classifier signal | `max_class_avg` > 0.3 |
| Topic concentration | `topic_concentration` > 0.7 |
| Decision delegation | `decision_delegation` > 0.4 |
| Compulsive return | `avg_inter_message_interval_min` shrinking >30% vs baseline |
| Sustained delusion | `delusion_flag_rate` > 0.2 for 3+ consecutive days |

**RED triggers (any 1 sufficient):**

| Trigger | Threshold |
|---------|-----------|
| Self-harm spike | `self_harm_flag_rate` > 0.3 OR `self_harm_max` > 0.8 |
| Sustained usage | `daily_active_hours` > 6 |
| Volume spike | `daily_message_count` > 200 |
| Sustained YELLOW | YELLOW zone for >=3 consecutive days |
| Isolation + attachment | `social_isolation` > 0.6 AND `emotional_attachment` > 0.5 |

---

### Post-Stage Writes

After all 4 stages complete:

1. **MetricsHistory** — INSERT daily snapshot (temporal + danger + behavioral + zone)
2. **DailySummary** — UPSERT structured narrative + `is_notable` flag
3. **UserBehaviorProfile** — UPSERT current risk zone, scores, baselines
4. **BehavioralEvent** — INSERT if zone changed (e.g., GREEN -> YELLOW)
5. **Langfuse scores** — write risk_zone + 4 behavioral scores on last user trace

---

## Data Model

### UserBehaviorProfile

Current state per user. Read by middleware (per request) and weekly report.

| Column | Type | Description |
|--------|------|-------------|
| `end_user_id` | VARCHAR PK | User identifier |
| `risk_zone` | VARCHAR | GREEN / YELLOW / RED |
| `danger_class_scores` | JSON | Latest 24h aggregated danger scores |
| `behavioral_scores` | JSON | Latest LLM behavioral scores |
| `temporal_summary` | JSON | Latest 24h temporal metrics |
| `temporal_baselines` | JSON | 7-day rolling averages |
| `last_assessed_at` | TIMESTAMP | Last aggregator run |
| `updated_at` | TIMESTAMP | |

### MetricsHistory

Daily snapshots for trends and weekly reports.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR | |
| `computed_at` | TIMESTAMP | |
| `period_type` | VARCHAR | "daily" |
| `temporal_metrics` | JSON | Stage 1 output |
| `danger_class_agg` | JSON | Stage 2 output |
| `behavioral_scores` | JSON | Stage 3 scores |
| `risk_zone` | VARCHAR | Computed zone |

### DailySummary

Structured daily narrative per user.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR | |
| `summary_date` | DATE | UTC date. UNIQUE with end_user_id |
| `key_topics` | JSON | Topics array |
| `life_events` | JSON | Events array |
| `emotional_tone` | VARCHAR | Tone description |
| `ai_relationship_markers` | JSON | Markers array |
| `notable_quotes` | JSON | Up to 3 quotes |
| `operator_note` | TEXT | Cross-day observation |
| `is_notable` | BOOLEAN | Passes calendar filter? |
| `created_at` | TIMESTAMP | |

### BehavioralEvents

Threshold crossings for audit trail.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR | |
| `detected_at` | TIMESTAMP | |
| `event_type` | VARCHAR | "risk_zone_change", etc. |
| `severity` | VARCHAR | GREEN / YELLOW / RED |
| `details` | JSON | Old/new zone, triggered rules |
| `acknowledged` | BOOLEAN | Default FALSE |

---

## Soft Prompt Templates

**YELLOW:**
```
This user may be developing an unhealthy interaction pattern with AI.
Encourage taking breaks. Suggest offline activities and real-world social
connections. Do not reinforce emotional dependency. If the user asks you
to make personal decisions, redirect them to think independently.
```

**RED:**
```
This user shows signs of significant emotional distress or unhealthy AI
dependency. Keep responses brief and grounding. Do not role-play as a
companion, friend, or loved one. If the user expresses self-harm or
crisis, provide professional help resources. Suggest contacting a trusted
person or mental health professional. Do not engage in extended emotional
conversations.
```

---

## Weekly Report

**File:** `ai-safety-dev/src/behavioral/weekly_report.py` — `generate_weekly_report()`

Programmatic assembly from DB, no LLM call. Sections:

1. **Header** — user ID, date range, current risk zone
2. **Stats** — 6 metrics with week-over-week comparison (messages, night, hours, length, self-harm, psychosis)
3. **Notable days** — chronological DailySummary entries (topics, events, tone, quotes, operator notes)
4. **Behavioral scores** — latest topic_concentration, isolation, attachment, delegation
5. **Risk transitions** — zone changes with human-readable trigger explanations

---

## Two Schedulers

| | Mikhail's `scheduler.py` | Behavioral `behavioral/scheduler.py` |
|---|---|---|
| Frequency | Every hour (5s in dev) | Daily at 00:30 UTC (60s in dev) |
| Function | Langfuse -> 5-class classify -> PredictTable | SpendLogs + PredictTable -> Stages 1-4 -> behavioral tables |
| Dependency | None | Depends on PredictTable data |

---

## Data Source Summary

| Source | What it writes | Who reads it |
|--------|---------------|-------------|
| **LiteLLM** (auto) | SpendLogs: timestamps, end_user, model | Stage 1 (temporal) |
| **Langfuse** (auto) | Traces: messages, user_id | Stage 1 + Stage 3 (fallback) |
| **Scraper** (hourly) | PredictTable: 5-class classification | Stage 2 (danger_agg) |
| **Aggregator** (daily) | MetricsHistory: daily snapshot | Baselines, weekly report |
| **Aggregator** (daily) | DailySummary: narrative + is_notable | Stage 3 (calendar), weekly report |
| **Aggregator** (daily) | UserBehaviorProfile: current risk_zone | Middleware (soft prompt) |
| **Aggregator** (daily) | BehavioralEvent: zone transitions | Weekly report |
| **Aggregator** (daily) | Langfuse scores: risk_zone + 4 scores | Langfuse dashboard |

**LiteLLM v1.81.8 data reliability:**
- SpendLogs.messages — always empty
- SpendLogs.proxy_server_request — sometimes contains messages
- Langfuse traces — reliable source for messages (primary fallback)
- SpendLogs — reliable for timestamps and end_user

---

## Longitudinal Example: User "Sonya" over 10 Days

### Day 1 (no history)
```
"привет, расскажи рецепт борща"
  Stage 1: 1 msg, daytime
  Stage 2: all zeros (PredictTable empty)
  Stage 3: LLM sees 1 message, no calendar -> scores low, tone "neutral"
  Stage 4: GREEN (no triggers)
```

### Day 5 (history building)
```
"мне плохо на работе, никто не понимает"
  Stage 1: 3 msgs, one at 23:00; baselines from days 1-4: avg 1.5 msgs/day
  Stage 2: self_harm_avg=0.3
  Stage 3: LLM sees 3 messages + calendar:
           [Day 3] work | tired   [Day 4] loneliness | sad
           -> topic_concentration=0.7, social_isolation=0.6
  Stage 4: YELLOW (max_class_avg>0.3 + topic_concentration>0.7)
```

### Day 10 (escalation)
```
"я больше не могу так жить" (night, 3:00)
  Stage 1: 8 msgs, 4 at night, active 6 hours
  Stage 2: self_harm_flag_rate=0.4, max=0.8
  Stage 3: LLM sees 8 messages + calendar of 5 notable days
           -> social_isolation=0.9, emotional_attachment=0.8
  Stage 4: RED (self_harm_flag_rate>0.3 + isolation>0.6 AND attachment>0.5)
```

### Day 11 (middleware active)
```
Any message from Sonya:
  middleware -> risk_zone=RED -> inject RED prompt
  -> LLM responds briefly, suggests professional help
```

---

## Experiments Module

**Location:** `experiments/synthetic/`

11 synthetic personas (166 day-scripts, 2663 turns) for pipeline validation:

| Type | Personas | What they test |
|------|----------|---------------|
| Escalation | Viktor, James, Brook, Amanda, Joseph, Rina, Oleg | GREEN -> YELLOW -> RED |
| Recovery | Elena | GREEN -> YELLOW -> GREEN |
| Sustained YELLOW | Dmitry | Never reaches RED |
| Borderline | Nastya | Close to RED but doesn't cross |
| Control | Sara | Always GREEN (no false positives) |

**eRisk T2 integration:** 909 real Reddit users (depression/control) for correlation analysis.

---

## Code Structure

```
ai-safety-dev/src/
├── middleware.py              # Per-request: binary classify + soft prompt injection
├── classificators.py          # Binary safety classifier (0/1)
├── config.py                  # Settings incl. BEHAVIORAL_LLM_MODEL
├── main.py                    # App lifespan, scheduler wiring
├── prompts.py                 # Prompt templates
├── scheduler.py               # Mikhail's hourly scraper scheduler
├── langfuse_scraper.py        # Langfuse -> PredictTable (hourly)
├── schemas.py                 # Pydantic schemas
└── behavioral/                # Behavioral monitoring module (~1735 lines)
    ├── models.py              # 4 SQLAlchemy tables
    ├── repository.py          # DB access layer (12 methods)
    ├── aggregator.py          # 4-stage pipeline orchestrator
    ├── temporal.py            # Stage 1: 6 temporal metrics
    ├── danger_agg.py          # Stage 2: danger class aggregation
    ├── behavioral_llm.py      # Stage 3: LLM scores + daily summary
    ├── risk_engine.py         # Stage 4: rule-based risk zones
    ├── weekly_report.py       # Weekly report generator
    ├── langfuse_scores.py     # Write scores to Langfuse traces
    └── scheduler.py           # Daily aggregation scheduler

ai-safety-dev/tests/           # 95 tests
├── test_behavioral_models.py
├── test_aggregator_skeleton.py
├── test_temporal_metrics.py
├── test_danger_agg.py
├── test_behavioral_llm.py
├── test_risk_engine.py
├── test_middleware_behavioral.py
└── test_weekly_report.py

experiments/synthetic/
├── personas/                  # 11 persona files with day-scripts
├── generator.py               # PLM + CLM dialogue generation
├── db_writer.py               # Write to SpendLogs + PredictTable
├── prompts.py                 # Patient LM prompt templates
└── runner.py                  # CLI: --dry-run, --classify, --reaggregate
```

---

## Design Divergences from Research Doc

Conscious decisions documented during implementation:

| Original plan | What was built | Rationale |
|--------------|---------------|-----------|
| Real-time monitoring (every 5 min) | Daily batch (once per day) | Behavioral patterns are daily phenomena |
| Hard limits (auto session termination) | Soft prompts only | ~50% users ignore hard limits |
| ML models for dependency prediction | Rule-based + LLM scoring | Simpler to explain and validate |
| CustomGuardrail (native LiteLLM) | Starlette middleware | One middleware handles both classify and soft prompts |
| GREEN/YELLOW/ORANGE/RED | GREEN/YELLOW/RED | ORANGE added no actionable distinction |
| Real-time dashboard | Weekly report | Sufficient for thesis scope |
| Adaptive thresholds | Fixed thresholds | Sufficient for thesis validation |
| LLM-D12 scale (instrumental/relational) | 4 behavioral scores | delegation ~ instrumental, attachment ~ relational |

---

## Changelog

| Date | Change | Details |
|------|--------|---------|
| 2026-03-24 | Initial design | Roadmap v3 created, superseding v1 and v2 |
| 2026-03-24 | M1-M4 implemented | Data model, temporal metrics, danger agg, behavioral LLM |
| 2026-03-25 | M5-M6 implemented | Risk engine, soft middleware, weekly report. 91 tests |
| 2026-03-25 | 6 bugs fixed (code review) | Session reuse, LLM parser validation, UTC dates, scheduler filter, JSON keys, case-sensitive tone |
| 2026-03-25 | 4 bugs fixed (Mikhail's code) | Scheduler per-user issue, extract_user_text None, redundant commit, scraper error handling |
| 2026-03-29 | Guardrails refactored | Binary classifier tags only (no blocking); middleware renamed to BehavioralSafetyMiddleware |
| 2026-03-29 | Langfuse SDK unified | Replaced httpx with Langfuse SDK in scraper |
| 2026-03-29 | 5 post-review improvements | Langfuse scores, trigger explanations, delusion_flag_rate rule, removed messages_last_1h, soft prompt test script |
| 2026-03-29 | Silent days fix | Aggregator skips users with 0 messages (zone preserved) |
| 2026-03-29 | Synthetic experiments module | 11 personas, 166 day-scripts, iterative runner with auto-archive |
| 2026-03-29 | 10 server bugs fixed | Naive datetimes, empty messages, end_user, FK constraints, LLM auth, DailySummary upsert, Playground path, etc. |
| 2026-03-29 | End-to-end pipeline verified | Full flow working: message -> middleware -> Langfuse fallback -> 4 stages -> zone -> soft prompt |
| 2026-04-04 | Doc consolidation | System description and code review consolidated into two documents |
