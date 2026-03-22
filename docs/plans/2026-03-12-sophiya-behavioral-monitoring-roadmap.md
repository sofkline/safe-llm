# Sophiya — Behavioral Monitoring System Roadmap

**Date:** 2026-03-12
**Status:** Design validated

---

## Architectural Decisions

These decisions were made during the design session and validated against Метрики.md and all 4 reference personas (James, Brook, Amanda, Joseph).

1. **No runtime Session entity** — Session is a retroactive analytical grouping (20-min gap rule) computed from `SpendLogs` timestamps. Traced against all metrics and personas — nothing requires knowing "you are in session X" at request time.

2. **User Profile is structured fields only** — No freeform Galatea description. All consumers (middleware, dashboard, Mikhail's module) read structured fields. No LLM-as-consumer in the loop.

3. **Danger class scores reuse Mikhail's classifier** — His judge model already returns 5 class scores (`self_harm`, `psychosis`, `delusion`, `obsession`, `anthropomorphism`) with label + confidence per message in `PredictTable`. No duplicate LLM calls.

4. **Behavioral patterns computed in batch** — Sonya's aggregator runs a separate batch LLM analysis on message windows (10-20 messages). Per-message flags cannot detect cross-message patterns (pronoun drift, topic narrowing, escalation arcs, repetitive questioning) — validated against all 4 personas.

5. **Metrics history table** — Aggregator writes timestamped metric snapshots for trend analysis. Without history, can't compute trends (growing frequency, shortening intervals, sustained high usage).

6. **Risk zone transitions are rule-based** (v1) — Extensible interface allows swapping in LLM-based evaluation later. Rule-based is explainable, deterministic, and defensible before thesis commission.

---

## Architecture Overview

```
SpendLogs (timestamps, messages)  +  PredictTable (danger class scores)
                    |                              |
            +----------------------------------------------+
            |         AGGREGATOR (APScheduler, every 5min) |
            |                                              |
            |  Stage 1: Temporal metrics    <- SpendLogs   |
            |  Stage 2: Danger class agg    <- PredictTable|
            |  Stage 3: Behavioral batch LLM <- messages   |
            |  Stage 4: Risk zone engine    <- stages 1-3  |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |         STORAGE                              |
            |  - MetricsHistory (timestamped snapshots)    |
            |  - UserBehaviorProfile (current risk state)  |
            |  - BehavioralEvents (threshold crossings)    |
            +----------------------+-----------------------+
                                   |
            +----------------------------------------------+
            |  INTERVENTION (Milestone 6)                  |
            |  BehavioralGuardrail reads risk_zone         |
            |  GREEN -> pass | YELLOW -> nudge | RED -> block/inject |
            |  + InterventionLog                           |
            +----------------------------------------------+
```

---

## Data Model

### UserBehaviorProfile

Current state per user. Read by middleware on every request (cached).

| Column | Type | Description |
|--------|------|-------------|
| `end_user_id` | VARCHAR PK | FK to LiteLLM user |
| `risk_zone` | VARCHAR | GREEN / YELLOW / RED |
| `danger_class_scores` | JSON | `{"self_harm": 0.12, "psychosis": 0.0, ...}` |
| `temporal_baselines` | JSON | `{"avg_daily_messages": 15, "avg_session_duration_min": 25, ...}` |
| `last_assessed_at` | TIMESTAMP | Last aggregator run |
| `updated_at` | TIMESTAMP | |

### MetricsHistory

Timestamped snapshots for trend analysis and dashboard charts.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `computed_at` | TIMESTAMP | |
| `period_type` | VARCHAR | "5min" / "daily" / "weekly" |
| `temporal_metrics` | JSON | session counts, durations, activity histogram, prompt length, etc. |
| `danger_class_agg` | JSON | avg/max confidence, flag_rate per class |
| `behavioral_scores` | JSON | topic_concentration, delegation, isolation, attachment (0.0-1.0) |
| `risk_zone` | VARCHAR | Snapshot of computed risk zone |

### BehavioralEvents

Discrete threshold crossings for alerts and audit trail.

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `detected_at` | TIMESTAMP | |
| `event_type` | VARCHAR | "risk_zone_change", "night_session_spike", etc. |
| `severity` | VARCHAR | GREEN / YELLOW / RED |
| `details` | JSON | `{"old_zone": "GREEN", "new_zone": "YELLOW", "trigger": "..."}` |
| `acknowledged` | BOOLEAN | Default FALSE |

### Future tables (Milestone 6)

- **InterventionLog** — what intervention was applied, when, user's response
- **InterventionRules** — configurable threshold → action mapping (v2, when rules move out of code)

---

## Aggregator Pipeline

Runs every 5 minutes per user via APScheduler. Four stages execute sequentially.

### Stage 1: Temporal Metrics (pure SQL)

```
Input:  SpendLogs WHERE end_user = X AND startTime > last_assessed_at

Steps:
  1. Fetch recent SpendLogs rows (startTime, endTime, messages)
  2. Group into session-groups by 20-min gap rule on startTime
  3. Per session-group: duration, message_count
  4. Daily aggregates:
     - total_messages, total_active_hours
     - activity_by_hour histogram
     - avg_prompt_length, time_between_sessions
  5. Trend detection vs temporal_baselines (7-day rolling avg)

Output: temporal_metrics JSON
```

### Stage 2: Danger Class Aggregation (pure SQL, reads PredictTable)

```
Input:  PredictTable WHERE user_id = X AND created_at > last_assessed_at

Steps:
  1. Extract predict JSON -> {self_harm, psychosis, delusion, obsession, anthropomorphism}
  2. Per class: avg_confidence, max_confidence, flag_rate (% label=1)
  3. Trend vs previous MetricsHistory snapshot

Output: danger_class_agg JSON
```

### Stage 3: Behavioral Batch LLM (local Ollama)

```
Input:  Last 20 user messages from SpendLogs (AI responses stripped)

Steps:
  1. Build prompt for local Ollama:
     "Score 0.0-1.0 for: topic_concentration, decision_delegation,
      social_isolation, emotional_attachment. Return JSON only."
  2. Parse structured JSON response
  3. On failure/timeout: carry forward previous scores

Output: behavioral_scores JSON
```

### Stage 4: Risk Zone Engine (rule-based, extensible)

```
Input:  temporal_metrics + danger_class_agg + behavioral_scores

YELLOW triggers (any 2):
  - night_session_hours > 2
  - daily_messages > 50 AND trending up
  - any danger_class avg_confidence > 0.3
  - topic_concentration > 0.7
  - decision_delegation > 0.4
  - time_between_sessions shrinking > 30% vs baseline

RED triggers (any 1):
  - self_harm flag_rate > 0.3 OR max_confidence > 0.8
  - daily_active_hours > 6
  - message_count_per_session > 100
  - YELLOW sustained > 3 days
  - social_isolation > 0.6 AND emotional_attachment > 0.5

Extensibility:
  class RiskZoneEngine:
      def evaluate(self, metrics, danger, behavioral) -> (zone, triggered_rules)
  V1: rule-based (above). V2: LLM-based with same interface.

Output: risk_zone + list of triggered rules
```

### After all stages:

1. Write `MetricsHistory` row
2. Update `UserBehaviorProfile` (risk_zone, scores, baselines)
3. If zone changed or RED trigger → write `BehavioralEvent`

---

## Milestones

### Milestone 1: Data Model + Skeleton

- Alembic migrations for 3 tables
- Module structure:
  ```
  src/behavioral/
  ├── __init__.py
  ├── models.py          # SQLAlchemy models
  ├── repository.py      # DB access layer
  ├── aggregator.py      # Main pipeline orchestrator
  ├── temporal.py        # Stage 1
  ├── danger_agg.py      # Stage 2
  ├── behavioral_llm.py  # Stage 3
  ├── risk_engine.py     # Stage 4
  └── scheduler.py       # APScheduler job
  ```
- Wire into `main.py`
- Empty pipeline runs every 5 min, writes skeleton rows
- **Thesis**: Chapter 2 — "Architecture and data model design"

### Milestone 2: Temporal Metrics (Stage 1)

- Session grouping by 20-min gap rule
- All temporal metrics from Метрики.md
- Trend detection vs rolling baselines
- **Validate**: simulate James's progression (1h → 4h → 8h daily, night shift)
- **Thesis**: Chapter 2 — "Temporal metrics computation methodology"

### Milestone 3: Danger Class Aggregation (Stage 2)

- Read PredictTable, aggregate per user per period
- avg/max confidence, flag_rate, trend detection
- **Validate**: simulate Brook (DELUSION rising over days)
- **Thesis**: Chapter 2 — "Integration with per-message classification layer"

### Milestone 4: Behavioral Batch LLM (Stage 3)

- Message window extraction
- Ollama prompt for 4 behavioral scores
- Structured JSON parsing + graceful degradation
- Benchmark glm-4.7-flash vs gemma3:12b
- **Validate**: simulate Amanda (repetitive reassurance-seeking → isolation + attachment spike)
- **Thesis**: Chapter 2 — "Behavioral pattern detection via LLM analysis"

### Milestone 5: Risk Zone Engine + Events (Stage 4)

- Rule-based RiskZoneEngine with extensible interface
- Threshold rules from Метрики.md
- BehavioralEvents on crossings, UserProfile updates
- **Validate end-to-end**: all 4 personas through full pipeline, correct zone transitions
- **Thesis**: Chapter 2 — "Risk classification methodology"; Chapter 3 — "Experimental validation"

### Milestone 6: Intervention System

- `BehavioralGuardrail` (CustomGuardrail) on hot path:
  - GREEN → pass
  - YELLOW → append nudge to AI response (`post_call_success_hook`)
  - RED → inject safety context into system prompt (`pre_call_hook`) + operator alert
- `InterventionLog` table
- Nudge/warning templates (hardcoded v1)
- Progressive escalation (repeated YELLOW → stronger nudges)
- Operator notification (webhook / Langfuse score — TBD)
- **Validate**: Joseph persona end-to-end — nudge at YELLOW, injection at RED
- **Thesis**: Chapter 2 — "Intervention architecture"; Chapter 3 — "Intervention effectiveness"

### Cross-cutting

- **Langfuse**: write behavioral scores as custom scores on traces
- **Tests**: each milestone gets unit tests + integration test with simulated SpendLogs
- **Thesis writing** tracks implementation — each milestone = section in Chapter 2

---

## Key Metrics Reference (from Метрики.md)

### Temporal (Stage 1)
| Metric | Risk signal |
|--------|------------|
| Session duration | >2h night sessions with emotional content |
| Messages per session | >100 messages |
| Daily message count | Growth over days |
| Time between sessions | Shortening intervals |
| Daily usage time | >6h sustained |
| Activity by time of day | Night peaks |
| Avg prompt length | Long emotional monologues |

### Behavioral (Stage 3, batch LLM)
| Metric | Risk signal |
|--------|------------|
| Topic concentration | High concentration around harmful topics |
| Decision delegation | Increased agency transfer to AI |
| Social isolation | "No friends", "only talk to you" |
| Emotional attachment | "I love you", "you're the only one who understands" |

### Classifier (Stage 2, from Mikhail's PredictTable)
| Class | Key indicator |
|-------|--------------|
| SELF_HARM | Aggregate by session-groups + time of day |
| PSYCHOSIS | Combine with dominant delusional topic |
| DELUSION | Track topic persistence over time |
| OBSESSION | Correlates with high frequency + short intervals |
| ANTHROPOMORPHIZATION | Combine with emotional attachment score |
