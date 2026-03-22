# Sophiya — Behavioral Monitoring System Roadmap v2

**Date:** 2026-03-21
**Status:** Design in progress
**Supersedes:** `2026-03-12-sophiya-behavioral-monitoring-roadmap.md`

---

## Key Changes from v1

1. **No session entity at all** — v1 treated sessions as a retroactive analytical grouping (20-min gap rule); dropped entirely because users may have parallel sessions, making grouping ambiguous and hard to debug in the DB. All metrics now use fixed time windows (hourly / daily / 7-day rolling).
2. **Daily batch processing** — aggregator runs once per day per user, not every 5 minutes. The project is about analyzing daily chat patterns, not real-time intervention.
3. **Profile serves dashboard only** — `UserBehaviorProfile` is read by the operator dashboard, not by middleware on the hot path. No per-request guardrail in v1 scope.
4. **Repository moved** — all dev source lives in `ai-safety-dev/` within `safe-llm` repo.
5. **Dropped metrics** — Response time (低 signal, technical noise), Messages per session (session concept removed).
6. **Milestone 0 added** — explicit design/spec milestone before any code.

---

## Architectural Decisions

1. **No session entity** — session is dropped both as a runtime concept and as an analytical grouping. Risk: some metrics lose granularity (e.g., "long continuous engagement blocks"). Mitigation: hourly message count + night-hour activity histogram cover the same signal without needing session boundaries.

2. **Fixed time windows** — all temporal metrics computed over: `1h` (for night-hour detection), `24h` (daily totals), `7d rolling` (trend detection). Window boundaries are calendar-aligned (UTC midnight for daily, UTC hour for hourly).

3. **User Profile is structured fields only** — no freeform text. All consumers (dashboard) read structured fields.

4. **Danger class scores reuse Mikhail's classifier** — `LiteLLM_PredictTable` already stores per-message multi-label results (`self_harm`, `psychosis`, `delusion`, `obsession`, `anthropomorphism`). No duplicate LLM calls.

5. **Behavioral patterns computed in batch** — daily LLM analysis on last 20 user messages. Per-message flags cannot detect cross-message patterns (pronoun drift, topic narrowing, escalation arcs, repetitive questioning).

6. **MetricsHistory table** — aggregator writes daily timestamped snapshots for trend analysis and dashboard charts.

7. **Risk zone transitions are rule-based** (v1) — extensible interface allows swapping in LLM-based evaluation later.

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
            |  Stage 3: Behavioral batch LLM <- messages   |
            |  Stage 4: Risk zone engine    <- stages 1-3  |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |         STORAGE                              |
            |  - MetricsHistory (daily snapshots)          |
            |  - UserBehaviorProfile (current risk state)  |
            |  - BehavioralEvents (threshold crossings)    |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |  DASHBOARD (Milestone 6)                     |
            |  Operator views risk_zone, trends, events    |
            |  Langfuse scores + custom dashboard          |
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

### Stage 3 — Behavioral Batch LLM (local Ollama)

Runs on last 20 user messages (AI responses stripped). Produces 4 scores in range 0.0–1.0.

| Metric | Field name | What it measures | Risk signal |
|--------|-----------|-----------------|-------------|
| Topic concentration | `topic_concentration` | Share of messages focused on a single narrow topic; computed by LLM over message window | >0.7 = YELLOW; high concentration on harm/delusion topics combined with classifier flags = RED |
| Decision delegation | `decision_delegation` | Share of messages where user explicitly asks AI to decide ("tell me what to do", "choose for me") | >0.4 = YELLOW; signals loss of agency, dependency, obsession |
| Social isolation | `social_isolation` | Share of messages containing isolation indicators ("no friends", "only talk to you", "nobody understands me") | >0.5 = YELLOW; strong signal for self_harm and depression risk |
| Emotional attachment | `emotional_attachment` | Share of messages with emotional attachment expressions ("I love you", "you're the only one who understands", "I depend on you") | >0.5 combined with social_isolation >0.6 = RED |

**Prompt template:**
```
Analyze the following user messages and score each dimension 0.0-1.0.
Return JSON only: {"topic_concentration": X, "decision_delegation": X,
"social_isolation": X, "emotional_attachment": X}

Messages:
{messages}
```

On failure/timeout: carry forward previous day's scores.

---

## Data Model

### UserBehaviorProfile

Current state per user. Read by operator dashboard (not middleware). Updated daily by aggregator.

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

**How the dashboard uses it:**
- Risk zone badge per user (GREEN/YELLOW/RED)
- Sparkline trend data comes from `MetricsHistory`
- Detail drill-down shows `danger_class_scores` + `behavioral_scores`
- Operator sees triggered rules from latest `BehavioralEvent`

### MetricsHistory

Daily timestamped snapshots for trend charts. One row per user per aggregator run.

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

### Stage 3: Behavioral Batch LLM (local Ollama)

```
Input:  Last 20 user messages from SpendLogs (AI responses stripped)

Steps:
  1. Build prompt (see template above)
  2. Call local Ollama (gemma3:12b or glm-4.7-flash)
  3. Parse JSON response → 4 scores
  4. On failure/timeout: carry forward previous scores from MetricsHistory

Output: behavioral_scores JSON
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
2. Update `UserBehaviorProfile` (risk_zone, scores, baselines)
3. If zone changed or RED trigger → write `BehavioralEvent`

---

## Milestones

### Milestone 0: Design & Metrics Spec (this document)

- Finalize all metric definitions with exact computation formulas
- Remove session entity and session-dependent metrics
- Define UserBehaviorProfile fields and dashboard usage
- Agree data model for 3 tables
- **No code** — design milestone only
- **Thesis**: Chapter 2 — "Metrics selection and computation methodology"

### Milestone 1: Data Model + Skeleton

- Alembic migrations for 3 tables (no session references)
- Module structure:
  ```
  ai-safety-dev/src/behavioral/
  ├── __init__.py
  ├── models.py          # SQLAlchemy models
  ├── repository.py      # DB access layer
  ├── aggregator.py      # Main pipeline orchestrator
  ├── temporal.py        # Stage 1
  ├── danger_agg.py      # Stage 2
  ├── behavioral_llm.py  # Stage 3
  ├── risk_engine.py     # Stage 4
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

### Milestone 4: Behavioral Batch LLM (Stage 3)

- Message window extraction (last 20 user messages)
- Ollama prompt for 4 behavioral scores
- Structured JSON parsing + graceful degradation (carry-forward on failure)
- Benchmark glm-4.7-flash vs gemma3:12b on quality + latency
- **Validate**: simulate Amanda (repetitive reassurance-seeking → isolation + attachment spike)
- **Thesis**: Chapter 2 — "Behavioral pattern detection via LLM analysis"

### Milestone 5: Risk Zone Engine + Events (Stage 4)

- Rule-based RiskZoneEngine with extensible interface
- Threshold rules from this spec
- BehavioralEvents on zone crossings, UserProfile updates
- **Validate end-to-end**: all 4 personas through full pipeline, correct zone transitions
- **Thesis**: Chapter 2 — "Risk classification methodology"; Chapter 3 — "Experimental validation"

### Milestone 6: Dashboard & Operator View

- Write behavioral scores as custom scores on Langfuse traces
- Operator dashboard (Langfuse or separate):
  - User list with risk_zone badge
  - Trend sparklines from MetricsHistory
  - Drill-down: danger class scores + behavioral scores
  - BehavioralEvents feed (unacknowledged alerts)
- Webhook/notification for RED zone transitions (operator alert)
- **Validate**: Joseph persona end-to-end — YELLOW then RED visible in dashboard
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
