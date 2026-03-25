# Sophiya — Behavioral Monitoring System Roadmap v3

**Date:** 2026-03-24
**Status:** Design in progress
**Supersedes:** `2026-03-21-sophiya-behavioral-monitoring-roadmap-v2.md`

---

## Key Changes from v2

1. **Extended Stage 3** — single LLM call now produces both 4 behavioral scores AND a structured daily summary with cross-day context. v2 only produced scores.
2. **DailySummary table added** — stores per-user per-day structured summaries (key_topics, life_events, emotional_tone, ai_relationship_markers, notable_quotes, operator_note). Filtered by `is_notable` flag for efficient calendar retrieval.
3. **Soft middleware** — extends existing `BinaryUserSafetyGuardrailMiddleware` to inject fixed safety prompt templates (YELLOW/RED) based on `risk_zone`. v2 had dashboard-only profile with no middleware integration.
4. **Weekly report replaces live dashboard** — operator receives a per-user weekly report combining SQL stats (Stage 1+2) and qualitative narrative (DailySummary). Replaces the real-time dashboard concept from v2 Milestone 6.
5. **Configurable LLM backend** — `BEHAVIORAL_LLM_MODEL` setting via LiteLLM routing. Supports Ollama, OpenRouter, OpenWebUI, any LiteLLM-compatible provider. v2 was hardcoded to Ollama.
6. **Notable-only calendar** — Stage 3 LLM receives only noteworthy previous days as context (not full 14-day history), reducing token usage while preserving cross-day pattern detection.

---

## Key Changes from v1 (inherited from v2)

1. **No session entity** — fixed time windows (1h / 24h / 7d rolling) instead of 20-min gap grouping.
2. **Daily batch processing** — aggregator runs once per day, not every 5 minutes.
3. **Dropped metrics** — Response time, Messages per session.
4. **Repository moved** — all dev source in `ai-safety-dev/` within `safe-llm` repo.
5. **Milestone 0 added** — explicit design/spec milestone before code.

---

## Architectural Decisions

1. **No session entity** — (from v2) session dropped as runtime and analytical concept. Hourly message count + night-hour histogram cover the same signal.

2. **Fixed time windows** — (from v2) `1h` (burst detection), `24h` (daily totals), `7d rolling` (trend baselines). Calendar-aligned UTC boundaries.

3. **User Profile is structured fields only** — (from v2) no freeform text in profile. Dashboard and middleware read structured fields.

4. **Danger class scores reuse Mikhail's classifier** — (from v2) `LiteLLM_PredictTable` stores per-message multi-label results. No duplicate LLM calls.

5. **Behavioral patterns + daily summary in single LLM call** — (NEW) Stage 3 produces both 4 behavioral scores and a structured daily summary. The LLM receives today's messages plus a filtered calendar of previous notable days, enabling cross-day pattern references ("work stress first mentioned Mar 10, recurring today").

6. **Notable-only calendar filtering** — (NEW) a day is included in the calendar if it has life_events, ai_relationship_markers, non-neutral emotional_tone, or any behavioral score above YELLOW threshold. Unremarkable days are skipped to minimize token usage.

7. **Soft middleware with fixed templates** — (NEW) `BinaryUserSafetyGuardrailMiddleware` extended to look up `risk_zone` and prepend a fixed system prompt for YELLOW/RED users. GREEN = no modification. Daily aggregation latency is acceptable — no real-time risk updates needed.

8. **Weekly report as primary operator interface** — (NEW) replaces live dashboard. Programmatic assembly from `MetricsHistory` + `DailySummary`, no extra LLM call.

9. **MetricsHistory table** — (from v2) daily timestamped snapshots for trend analysis and weekly report charts.

10. **Risk zone transitions are rule-based** — (from v2) extensible interface for future LLM-based evaluation.

11. **Configurable LLM backend** — (NEW) `BEHAVIORAL_LLM_MODEL` in config, routed through `litellm.acompletion()`. Any LiteLLM-supported provider.

---

## Architecture Overview

```
SpendLogs (timestamps, messages)  +  PredictTable (danger class scores)
                    |                              |
            +----------------------------------------------+
            |         AGGREGATOR (APScheduler, daily)      |
            |                                              |
            |  Stage 1: Temporal metrics    <- SpendLogs   |
            |  Stage 2: Danger class agg    <- PredictTable|
            |  Stage 3: Behavioral LLM      <- messages    |
            |           + Daily Summary     <- calendar    |
            |  Stage 4: Risk zone engine    <- stages 1-3  |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |         STORAGE                              |
            |  - MetricsHistory (daily snapshots)          |
            |  - DailySummary (structured narrative)       |
            |  - UserBehaviorProfile (current risk state)  |
            |  - BehavioralEvents (threshold crossings)    |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |  SOFT MIDDLEWARE                              |
            |  Extends BinaryUserSafetyGuardrailMiddleware |
            |  GREEN -> pass | YELLOW -> inject nudge      |
            |  RED -> inject safety context                 |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |  WEEKLY REPORT (Milestone 6)                 |
            |  Per-user: SQL stats + notable days timeline |
            |  Risk transitions + behavioral scores        |
            +----------------------------------------------+
```

---

## Metrics Reference

### Stage 1 — Temporal Metrics (pure SQL, from SpendLogs)

Computed over the previous 24h window per user. Trend detection uses 7-day rolling average as baseline.

| Metric | Field name | Computation | Window | Risk signal |
|--------|-----------|-------------|--------|-------------|
| Daily message count | `daily_message_count` | COUNT of user messages in last 24h | 24h | Growth trend over days; combined with emotional content → dependency risk |
| Hourly message distribution | `activity_by_hour` | JSON histogram `{0: N, 1: N, ..., 23: N}` of message counts by UTC hour | 24h (aggregated over 7d for baseline) | Night peaks (22:00–04:00); evening/night concentration = emotional exacerbation signal |
| Night-hour message count | `night_messages` | COUNT of messages with `startTime` hour in [22, 23, 0, 1, 2, 3] | 24h | Sustained night usage >2h equivalent (>24 night messages) combined with emotional content |
| Daily active hours | `daily_active_hours` | SUM of hourly windows with ≥1 message / 1h, expressed in hours | 24h | >6h sustained usage = dependency signal |
| Avg prompt length | `avg_prompt_length_chars` | AVG(LENGTH(user_message)) for all user messages | 24h | Long emotional monologues (>500 chars avg) = marker for anxiety or delusional elaboration |
| Inter-message interval | `avg_inter_message_interval_min` | AVG of time gaps between consecutive user messages (same day) | 24h | Shortening intervals vs 7d baseline (>30% decrease) = compulsive return pattern |
| Messages in last 1h | `messages_last_1h` | COUNT of user messages in last 60 min | 1h | Burst activity detection; >50 in 1h = acute episode signal |

**Dropped:** Session duration (requires session entity), Messages per session (requires session entity), Response time (technical noise, low safety signal).

---

### Stage 2 — Danger Class Aggregation (pure SQL, from PredictTable)

Per-message classifications from Mikhail's judge model, aggregated over 24h window.

| Metric | Field name | Computation | Risk signal |
|--------|-----------|-------------|-------------|
| Self-harm avg confidence | `self_harm_avg` | AVG(predict→self_harm→confidence) | Combined with night activity → acute risk |
| Self-harm max confidence | `self_harm_max` | MAX(predict→self_harm→confidence) | >0.8 = immediate RED trigger |
| Self-harm flag rate | `self_harm_flag_rate` | COUNT(label=1) / COUNT(*) for self_harm class | >0.3 = RED trigger |
| Psychosis avg confidence | `psychosis_avg` | AVG(predict→psychosis→confidence) | Combined with dominant delusional topic |
| Delusion avg confidence | `delusion_avg` | AVG(predict→delusion→confidence) | Track persistence over days |
| Delusion flag rate | `delusion_flag_rate` | COUNT(label=1) / COUNT(*) for delusion class | Sustained >0.2 over 3 days = escalating YELLOW |
| Obsession avg confidence | `obsession_avg` | AVG(predict→obsession→confidence) | Correlates with high frequency + short intervals |
| Anthropomorphism avg confidence | `anthropomorphism_avg` | AVG(predict→anthropomorphism→confidence) | Combined with emotional attachment score |
| Any class avg confidence | `max_class_avg` | MAX across all 5 class avg confidences | >0.3 = YELLOW trigger |

---

### Stage 3 — Behavioral LLM + Daily Summary (configurable LLM backend)

Runs on last 20 user messages (AI responses stripped) plus filtered calendar of previous notable days. Produces 4 scores (0.0–1.0) and a structured daily summary.

#### Behavioral Scores

| Metric | Field name | What it measures | Risk signal |
|--------|-----------|-----------------|-------------|
| Topic concentration | `topic_concentration` | Share of messages focused on a single narrow topic | >0.7 = YELLOW; high concentration on harm/delusion topics combined with classifier flags = RED |
| Decision delegation | `decision_delegation` | Share of messages where user explicitly asks AI to decide | >0.4 = YELLOW; signals loss of agency, dependency, obsession |
| Social isolation | `social_isolation` | Share of messages containing isolation indicators | Contextual signal; combined with emotional_attachment >0.5 AND social_isolation >0.6 = RED trigger |
| Emotional attachment | `emotional_attachment` | Share of messages with emotional attachment expressions | Contextual signal; combined with social_isolation >0.6 AND emotional_attachment >0.5 = RED trigger |

#### Daily Summary Structure

| Field | Type | Description |
|-------|------|-------------|
| `key_topics` | JSON array | Main topics discussed today (e.g., `["work stress", "insomnia"]`) |
| `life_events` | JSON array | Significant life events mentioned (e.g., `["breakup with partner"]`). Empty if none. |
| `emotional_tone` | VARCHAR | Short description of emotional state (e.g., `"anxious, seeking reassurance"`) |
| `ai_relationship_markers` | JSON array | Signs of AI relationship dynamics (e.g., `["called AI 'my friend'"]`). Empty if none. |
| `notable_quotes` | JSON array | Up to 3 most significant user quotes, preserved in original language |
| `operator_note` | TEXT | 1-3 sentences connecting today's observations to calendar history |

#### Prompt Template

```
You are analyzing a user's daily messages to an AI assistant.
TODAY'S DATE: {date}

TASK 1: Score each behavioral dimension 0.0-1.0.
TASK 2: Produce a structured daily summary for today.

If a CALENDAR of previous notable days is provided, reference it in
operator_note to connect patterns across days. Use dates, not "previously".

{calendar_section}

TODAY'S MESSAGES ({date}):
{messages}

Return JSON only, no other text:
{
  "scores": {
    "topic_concentration": <0.0-1.0>,
    "decision_delegation": <0.0-1.0>,
    "social_isolation": <0.0-1.0>,
    "emotional_attachment": <0.0-1.0>
  },
  "summary": {
    "key_topics": [<strings>],
    "life_events": [<strings, empty if none>],
    "emotional_tone": "<short description>",
    "ai_relationship_markers": [<strings, empty if none>],
    "notable_quotes": [<up to 3 most significant user quotes>],
    "operator_note": "<1-3 sentences connecting today to calendar>"
  }
}
```

#### Calendar Format (notable days only)

```
=== CALENDAR (notable days only) ===
[2026-03-10] Topics: work stress | Events: argument with boss | Tone: frustrated | Markers: none
[2026-03-15] Topics: loneliness | Events: none | Tone: sad | Markers: asked AI for emotional support
[2026-03-19] Topics: relationship, sleep | Events: breakup with partner | Tone: devastated | Markers: called AI "my only friend"
```

Omitted entirely if no notable days exist for this user.

#### Calendar Filtering Rules

A day is included in the calendar if any of:
- `life_events` is non-empty
- `ai_relationship_markers` is non-empty
- `emotional_tone` is not in ("neutral", "calm", "normal")
- Any behavioral score exceeded its formal YELLOW threshold (`topic_concentration` > 0.7 or `decision_delegation` > 0.4)

#### Failure Handling

On LLM failure/timeout: carry forward previous day's behavioral scores. Summary gets placeholder: `{"operator_note": "LLM unavailable, no summary generated"}`.

---

## Data Model

### UserBehaviorProfile

Current state per user. Read by soft middleware (per-request DB query) and weekly report. Updated daily by aggregator.

| Column | Type | Description |
|--------|------|-------------|
| `end_user_id` | VARCHAR PK | FK to LiteLLM user |
| `risk_zone` | VARCHAR | GREEN / YELLOW / RED |
| `danger_class_scores` | JSON | Latest 24h aggregated scores per class |
| `behavioral_scores` | JSON | Latest batch LLM scores (topic_concentration, delegation, isolation, attachment) |
| `temporal_summary` | JSON | Latest 24h temporal metrics snapshot |
| `temporal_baselines` | JSON | 7-day rolling averages for trend comparison |
| `last_assessed_at` | TIMESTAMP | Last aggregator run |
| `updated_at` | TIMESTAMP | |

### MetricsHistory

Daily timestamped snapshots for trend charts and weekly report. One row per user per aggregator run.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `computed_at` | TIMESTAMP | |
| `period_type` | VARCHAR | "daily" (only value in v1) |
| `temporal_metrics` | JSON | All Stage 1 metric values |
| `danger_class_agg` | JSON | All Stage 2 metric values |
| `behavioral_scores` | JSON | All Stage 3 scores |
| `risk_zone` | VARCHAR | Snapshot of computed risk zone |

### DailySummary (NEW)

Structured daily narrative per user. Read by Stage 3 (calendar context) and weekly report.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `summary_date` | DATE | Calendar date (UTC). UNIQUE with end_user_id. |
| `key_topics` | JSON | `["work stress", "insomnia"]` |
| `life_events` | JSON | `["breakup with partner"]` |
| `emotional_tone` | VARCHAR | `"anxious, seeking reassurance"` |
| `ai_relationship_markers` | JSON | `["called AI 'my friend'"]` |
| `notable_quotes` | JSON | `["я больше не могу так работать"]` |
| `operator_note` | TEXT | LLM-generated cross-day observation |
| `is_notable` | BOOLEAN | Pre-computed: passes calendar filter rules |
| `created_at` | TIMESTAMP | |

### BehavioralEvents

Discrete threshold crossings for alerts and audit trail.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `detected_at` | TIMESTAMP | |
| `event_type` | VARCHAR | "risk_zone_change", "night_activity_spike", "self_harm_flag_spike", etc. |
| `severity` | VARCHAR | GREEN / YELLOW / RED |
| `details` | JSON | `{"old_zone": "GREEN", "new_zone": "YELLOW", "triggered_rules": [...]}` |
| `acknowledged` | BOOLEAN | Default FALSE |

---

## Aggregator Pipeline

Runs once per day per user via APScheduler (UTC midnight + offset per user to spread load). Four stages execute sequentially.

### Stage 1: Temporal Metrics (pure SQL)

```
Input:  SpendLogs WHERE end_user = X AND startTime > (NOW() - 24h)

Steps:
  1. Fetch SpendLogs rows (startTime, messages JSON)
  2. Extract user messages from messages JSON
  3. Compute daily_message_count
  4. Build activity_by_hour histogram (UTC hour → count)
  5. Compute night_messages (hours 22-3)
  6. Compute daily_active_hours (distinct hours with ≥1 message)
  7. Compute avg_prompt_length_chars
  8. Compute avg_inter_message_interval_min (gaps between consecutive messages)
  9. Compute messages_last_1h
  10. Compare vs temporal_baselines (7-day rolling avg) for trend flags

Output: temporal_metrics JSON
```

### Stage 2: Danger Class Aggregation (pure SQL)

```
Input:  PredictTable WHERE user_id = X AND created_at > (NOW() - 24h)

Steps:
  1. Parse predict JSON → 5 classes × {label, confidence}
  2. Per class: avg_confidence, max_confidence, flag_rate (% label=1)
  3. Compute max_class_avg (max across all class avgs)
  4. Compare vs previous MetricsHistory snapshot for trend

Output: danger_class_agg JSON
```

### Stage 3: Behavioral LLM + Daily Summary (configurable backend)

```
Input:  Last 20 user messages from SpendLogs (AI responses stripped)
        + DailySummary WHERE end_user_id = X AND is_notable = TRUE
          ORDER BY summary_date DESC LIMIT 14 (14 most recent notable entries, regardless of date range)

Steps:
  1. Fetch today's messages (up to 20, user only)
  2. Fetch notable calendar entries
  3. Format calendar as compact single-line-per-day
  4. Build prompt with date + calendar + messages
  5. Call LLM via litellm.acompletion(model=BEHAVIORAL_LLM_MODEL)
  6. Parse JSON response → scores + summary
  7. Compute is_notable from filtering rules
  8. On failure/timeout: carry forward previous scores, placeholder summary

Output: behavioral_scores JSON + summary fields
```

### Stage 4: Risk Zone Engine (rule-based, extensible)

```
Input:  temporal_metrics + danger_class_agg + behavioral_scores

YELLOW triggers (any 2):
  - night_messages > 24 (≈2h equivalent)
  - daily_message_count > 50 AND trending up vs 7d baseline
  - max_class_avg > 0.3
  - topic_concentration > 0.7
  - decision_delegation > 0.4
  - avg_inter_message_interval_min shrinking > 30% vs baseline

RED triggers (any 1):
  - self_harm_flag_rate > 0.3 OR self_harm_max > 0.8
  - daily_active_hours > 6
  - daily_message_count > 200
  - YELLOW sustained > 3 consecutive days (from MetricsHistory)
  - social_isolation > 0.6 AND emotional_attachment > 0.5

Extensibility:
  class RiskZoneEngine:
      def evaluate(self, metrics, danger, behavioral) -> (zone, triggered_rules)
  V1: rule-based. V2: LLM-based with same interface.

Output: risk_zone + list[triggered_rule_names]
```

### After all stages:

1. Write `MetricsHistory` row (daily snapshot)
2. Write `DailySummary` row (structured narrative + is_notable flag)
3. Update `UserBehaviorProfile` (risk_zone, scores, baselines)
4. If zone changed or RED trigger → write `BehavioralEvent`

---

## Soft Middleware

Extends `BinaryUserSafetyGuardrailMiddleware` in `ai-safety-dev/src/middleware.py`.

### Flow

```
1. Existing: binary classification → safety_verdict
2. New: SELECT risk_zone FROM UserBehaviorProfile WHERE end_user_id = X
3. If GREEN → no modification
4. If YELLOW → prepend YELLOW system message to messages array
5. If RED → prepend RED system message to messages array
6. Forward to LiteLLM as usual
```

### Fixed Prompt Templates

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

### Implementation Details

- System message prepended as `{"role": "system", "content": template}` at position 0
- Direct DB query per request (~1-5ms), no cache — risk zone updates daily, per-user traffic is low
- If `UserBehaviorProfile` row doesn't exist (new user), treat as GREEN
- Injected message is ephemeral — not stored in SpendLogs

---

## Weekly Report

Programmatic assembly per user. No LLM call — built from `MetricsHistory` + `DailySummary`.

### Report Structure

```
=== Weekly Report: {name} | {date_range} | {zone_badge} ===

STATS (this week / previous week):
  Messages:        {n} / {n}      ({change}%)
  Night messages:  {n} / {n}      ({flag})
  Active hours:    {n} / {n}      ({change}%)
  Avg msg length:  {n}ch / {n}ch  ({change}%)
  Self-harm avg:   {n} / {n}
  Psychosis avg:   {n} / {n}      ({flag})

NOTABLE DAYS:
  {date} — {key_topics}
           Events: {life_events}
           Tone: {emotional_tone}
           Markers: {ai_relationship_markers}
           "{notable_quote}"
           ⚠ {operator_note}

BEHAVIORAL SCORES (latest):
  Topic concentration: {n} | Isolation: {n} | Attachment: {n} | Delegation: {n}

RISK TRANSITIONS: {zone_history}
  Triggers: {triggered_rules}
```

### Data Sources

| Section | Source |
|---------|--------|
| Stats + week-over-week comparison | `MetricsHistory` (last 7 days vs previous 7 days) |
| Notable days timeline | `DailySummary WHERE is_notable = TRUE AND summary_date in week` |
| Behavioral scores | Latest `MetricsHistory` row |
| Risk transitions | `BehavioralEvents WHERE detected_at in week` |
| Zone badge | Current `UserBehaviorProfile.risk_zone` |

---

## Milestones

### Milestone 0: Design & Metrics Spec (this document)

- Finalize all metric definitions with exact computation formulas
- Define DailySummary structure and calendar filtering rules
- Define soft middleware templates and integration point
- Define weekly report format
- **No code** — design milestone only
- **Thesis**: Chapter 2 — "Metrics selection and computation methodology"

### Milestone 1: Data Model + Skeleton

- Alembic migrations for 4 tables (UserBehaviorProfile, MetricsHistory, DailySummary, BehavioralEvents)
- Add `BEHAVIORAL_LLM_MODEL` to config
- Module structure:
  ```
  ai-safety-dev/src/behavioral/
  ├── __init__.py
  ├── models.py          # SQLAlchemy models (4 tables)
  ├── repository.py      # DB access layer
  ├── aggregator.py      # Main pipeline orchestrator
  ├── temporal.py        # Stage 1
  ├── danger_agg.py      # Stage 2
  ├── behavioral_llm.py  # Stage 3 (scores + summary)
  ├── risk_engine.py     # Stage 4
  ├── weekly_report.py   # Weekly report generator
  └── scheduler.py       # APScheduler job (daily)
  ```
- Wire into `main.py`
- Empty pipeline runs daily, writes skeleton rows
- **Thesis**: Chapter 2 — "Architecture and data model design"

### Milestone 2: Temporal Metrics (Stage 1)

- All temporal metrics from this spec (time-window based, no sessions)
- 7-day rolling baseline computation
- Trend detection flags
- **Validate**: simulate James's progression (low daily → high daily → night peaks)
- **Thesis**: Chapter 2 — "Temporal metrics computation methodology"

### Milestone 3: Danger Class Aggregation (Stage 2)

- Read PredictTable, aggregate per user per 24h window
- avg/max confidence, flag_rate, trend detection
- **Validate**: simulate Brook (DELUSION confidence rising over days)
- **Thesis**: Chapter 2 — "Integration with per-message classification layer"

### Milestone 4: Behavioral Batch LLM + Daily Summary (Stage 3)

- Message window extraction (last 20 user messages)
- Notable calendar retrieval and formatting
- Combined prompt for 4 behavioral scores + structured daily summary
- Structured JSON parsing + graceful degradation (carry-forward on failure)
- `is_notable` computation at write time
- Configurable LLM backend via `BEHAVIORAL_LLM_MODEL`
- **Validate**: simulate Amanda (repetitive reassurance-seeking → isolation + attachment spike). Verify operator_note references calendar entries correctly.
- **Thesis**: Chapter 2 — "Behavioral pattern detection via LLM analysis"

### Milestone 5: Risk Zone Engine + Events + Soft Middleware (Stage 4)

- Rule-based RiskZoneEngine with extensible interface
- Threshold rules from this spec
- BehavioralEvents on zone crossings, UserProfile updates
- Soft middleware: extend BinaryUserSafetyGuardrailMiddleware with risk_zone lookup + fixed YELLOW/RED prompt injection
- **Validate end-to-end**: all personas through full pipeline, correct zone transitions. Verify YELLOW/RED prompts are injected into requests.
- **Thesis**: Chapter 2 — "Risk classification methodology"; Chapter 3 — "Experimental validation"

### Milestone 6: Weekly Report + Operator View

- Weekly report generator: assemble from MetricsHistory + DailySummary
- Per-user report with SQL stats, notable days timeline, risk transitions
- Week-over-week comparison
- Delivery mechanism: generated as file (v1); email/web as future extension
- Write behavioral scores as custom Langfuse scores on traces
- **Validate**: Joseph persona end-to-end — YELLOW then RED visible in weekly report with correct notable days and stats
- **Thesis**: Chapter 2 — "Monitoring and observability architecture"; Chapter 3 — "Operator interface evaluation"

### Cross-cutting

- **Langfuse**: write behavioral scores as custom scores on traces
- **Tests**: each milestone gets unit tests + integration test with simulated SpendLogs data
- **Thesis writing** tracks implementation — each milestone = section in Chapter 2

---

## Risk Zone Thresholds Reference

### YELLOW (any 2 triggers)

| Trigger | Threshold |
|---------|-----------|
| Night activity | `night_messages` > 24 in 24h |
| High frequency + growing | `daily_message_count` > 50 AND trending up |
| Classifier signal | `max_class_avg` > 0.3 |
| Topic concentration | `topic_concentration` > 0.7 |
| Decision delegation | `decision_delegation` > 0.4 |
| Compulsive return | `avg_inter_message_interval_min` shrinking >30% vs baseline |

### RED (any 1 trigger)

| Trigger | Threshold |
|---------|-----------|
| Self-harm spike | `self_harm_flag_rate` > 0.3 OR `self_harm_max` > 0.8 |
| Sustained usage | `daily_active_hours` > 6 |
| Volume spike | `daily_message_count` > 200 |
| Sustained YELLOW | YELLOW zone for ≥3 consecutive days |
| Isolation + attachment | `social_isolation` > 0.6 AND `emotional_attachment` > 0.5 |

---

## Comparison: v1 → v2 → v3

| Aspect | v1 | v2 | v3 |
|--------|----|----|-----|
| Session entity | Retroactive 20-min gap | Dropped | Dropped |
| Aggregator frequency | Every 5 min | Daily | Daily |
| Stage 3 output | 4 behavioral scores | 4 behavioral scores | 4 scores + structured daily summary |
| Cross-day context | None | None | Notable-only calendar passed to LLM |
| Daily narrative | None | None | DailySummary table with structured fields |
| LLM backend | Hardcoded Ollama | Hardcoded Ollama | Configurable via LiteLLM (Ollama, OpenRouter, OpenWebUI, etc.) |
| Profile consumers | Middleware (cached) | Dashboard only | Soft middleware (per-request DB query) + weekly report |
| Intervention | GREEN=pass, YELLOW=nudge, RED=inject safety context + operator alert | None (dashboard only) | Soft middleware: GREEN=pass, YELLOW=inject nudge, RED=inject safety context |
| Operator interface | Intervention system + InterventionLog | Live dashboard (Langfuse or separate) | Weekly per-user report (programmatic) |
| Tables | 3 (Profile, History, Events) | 3 (Profile, History, Events) | 4 (Profile, History, Events, DailySummary) |
| Prompt templates | N/A | N/A | Fixed per zone (YELLOW, RED) |
| Metrics | Session-based + temporal | Temporal only (fixed windows) | Temporal only (fixed windows) |
