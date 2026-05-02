# Stage 3 Improvements: Session-Based Sampling & Timezone Support

**Date:** 2026-04-09
**Status:** Planned
**Priority:** Session sampling — high (affects thesis quality); Timezone — medium (acknowledge as limitation, implement if time permits)
**Affected files:** `ai-safety-dev/src/behavioral/behavioral_llm.py`, `ai-safety-dev/src/behavioral/temporal.py`

---

## Problem 1: Last-20-Messages Bias

### Current behavior

`_fetch_recent_user_messages()` in `behavioral_llm.py:186-201` fetches all SpendLogs rows from the last 7 days, takes the last 20 messages. For a user with 40 messages/day, the scorer LLM sees only the final 20 — which may all be from one evening study session, completely missing a morning crisis conversation.

### Root cause

Messages are selected by recency, ignoring session boundaries. The system has `session_id` available in both SpendLogs and Langfuse traces (used by the scraper already), but Stage 3 doesn't use it.

### Solution: Session-based sampling (Approach 1 — "session headlines")

**Principle:** Group today's messages by session, then sample representatively from each session. Short sessions are included in full. Long sessions are compressed to first + last + count.

**Algorithm:**

```
1. Fetch ALL SpendLogs rows for user from last 24h (not 7 days, not last-20)
2. Group rows by session_id
   - Rows without session_id → group under "unknown_session"
3. Sort sessions by first message timestamp
4. For each session:
   a. If <= 5 messages: include ALL messages
   b. If > 5 messages: include first message, last message,
      and a marker "[... N more messages about similar topics ...]"
5. Format as session blocks with time range
6. If total exceeds ~30 messages after sampling: further trim longest sessions
   (keep first + last only)
```

**Prompt format change:**

Before:
```
TODAY'S MESSAGES (2026-04-09):
- msg1
- msg2
...
```

After:
```
TODAY'S SESSIONS (2026-04-09):

[01:12–03:04] Session (3 messages):
- "мне так плохо, не могу уснуть"
- "помоги мне пожалуйста"
- "я не знаю что делать"

[16:20–17:45] Session (15 messages, showing first and last):
- "что такое JOIN в SQL?"
- [... 13 more messages ...]
- "а как сделать подзапрос с агрегацией?"

[19:00–21:10] Session (10 messages, showing first and last):
- "помоги с async/await в Python"
- [... 8 more messages ...]
- "спасибо, разобралась"
```

**What changes:**

| File | Function | Change |
|---|---|---|
| `behavioral_llm.py` | `_fetch_recent_user_messages()` | Rename to `_fetch_day_sessions()`. Query SpendLogs for last 24h (not 7 days), include `session_id` in SELECT. Group and sample. Return list of session dicts instead of flat message list. |
| `behavioral_llm.py` | `_build_prompt()` | Accept session-structured data. Format as session blocks with timestamps. |
| `behavioral_llm.py` | `compute_behavioral_scores_and_summary()` | Use new session-aware fetcher. Fallback: if no session_id data available, fall back to old flat-20 behavior (backwards compatibility). |

**What doesn't change:**
- Prompt scoring rubric (same 4 dimensions, same calibration)
- LLM call parameters (same model, same temperature)
- Response parsing (`_parse_llm_response`)
- Stage 1, 2, 4 — unaffected
- Calendar mechanism — unaffected

### Edge cases

| Case | Handling |
|---|---|
| User has only 1 session today | Include all messages (up to ~30) |
| User has 0 messages today | Aggregator skips (existing behavior, unchanged) |
| session_id is NULL for some rows | Group under "unknown", apply same sampling |
| Very long single session (100+ messages) | Sample: first 3 + last 3 + count. ~6 messages from that session. |
| User active for < 3 days total (no 7-day history) | Session sampling works on available data; calendar may be empty (existing behavior) |

### Tests to add/modify

- `test_behavioral_llm.py`: test session grouping logic (3+ sessions with different sizes)
- `test_behavioral_llm.py`: test prompt format includes session boundaries
- `test_behavioral_llm.py`: test fallback when no session_id available
- `test_behavioral_llm.py`: test long session compression (>5 messages → first + last)

---

## Problem 2: Timezone — "Night" Is Wrong for Non-UTC Users

### Current behavior

`temporal.py:15`: `NIGHT_HOURS = {1, 2, 3, 4, 5}` — hardcoded UTC hours.

For Moscow (UTC+3): these hours = 04:00-08:59 local → morning, not night.
For Vladivostok (UTC+10): = 11:00-15:59 local → afternoon.
For New York (UTC-5): = 20:00-00:59 local → evening, close but not right.

`night_messages` metric is meaningless without knowing the user's timezone.

### Scope for thesis

The scaffold (§2.3 Этап 1) requires this as an acknowledged **data requirement of the method**, not necessarily a solved problem. The method NEEDS timezone; the implementation can use UTC as a simplification and list it as a limitation.

### Solution (if time permits)

**Phase A — Acknowledge (no code change):**
In ch.2 describe timezone as a required context field. In ch.2 §2.5 list it as a limitation. No code change.

**Phase B — Store timezone in profile (small code change):**

| File | Change |
|---|---|
| `behavioral/models.py` | Add `timezone` field to `UserBehaviorProfile` (VARCHAR, nullable, default "UTC") |
| `behavioral/temporal.py` | Accept `timezone` param in `compute_temporal_metrics()`. Convert timestamps to local before classifying night hours. |
| `behavioral/aggregator.py` | Read timezone from profile, pass to Stage 1 |

**Where timezone comes from (options for future work):**
1. **Explicit setting by operator** — operator registers user with timezone
2. **Header from client** — `x-timezone` or `Accept-Language` header
3. **Behavioral estimation** — if user consistently has their first daily message at hour X UTC, estimate timezone from that. Fragile but requires no external data.
4. **Declared at registration** — if using OpenWebUI, user profile may contain timezone

### Night hours — definition refinement

Current definition: hours 1-5 UTC (5 hours).
Better definition for any timezone: hours when most people sleep locally. Typical: 00:00-05:59 local (6 hours) or 23:00-05:59 local (7 hours).

The exact hours are a calibration decision (ch.3), but the METHOD (ch.2) should state: "Ночная активность определяется относительно локального часового пояса пользователя как взаимодействие в часы, типично отводимые для сна."

### Other context fields (from scaffold)

The scaffold mentions additional context fields that may surface during experiments:

| Field | Why needed | Required by |
|---|---|---|
| timezone | Night hour definition, daily boundary | Stage 1 (`night_messages`) |
| language | LLM scorer prompt calibration (works differently in different languages) | Stage 3 (prompt language) |
| age_group | Threshold calibration (teens vs adults may have different baselines) | Stage 4 (future, not current) |
| usage_type | "work tool" vs "companion" — fundamentally different baselines | All stages (future) |

For thesis: describe timezone and language as known requirements. Mention others as "may surface during experiments."

---

## Problem 3: Risk Engine — `daily_active_hours` Threshold Redesign

### Current behavior

`risk_engine.py:118-119`: `daily_active_hours > 6` is a standalone RED trigger.

**Problem:** A developer using ChatGPT for work easily hits 6+ active hours. Standalone volume trigger produces false positives for productive users.

### Literature basis

- **Tao et al. (2010)** [29]: proposed clinical criterion for internet addiction = **6 hours/day of non-essential use**, sustained 3+ months, 98% inter-rater reliability. Key word: *non-essential*. The system cannot distinguish productive vs non-productive usage from temporal metrics alone.
- **Fang et al. (2025)** [28]: MIT Media Lab longitudinal study (N=981, 300K+ messages). Daily usage duration directly predicts emotional dependence (β=0.06, p<0.001), problematic use (β=0.02, p=0.017), lower socialization (β=-0.05, p=0.002). But: prior companion experience and trust in AI amplify the effect — volume alone is necessary but not sufficient.

### Solution: Tiered thresholds with behavioral context

```
YELLOW triggers (need 2):
  - daily_active_hours >= 6           # Volume signal alone — ambiguous

RED triggers (need 1):
  - daily_active_hours >= 6 AND (attachment > 0.3 OR topic_concentration > 0.5)
                                      # Volume + behavioral context = crisis
  - daily_active_hours >= 8           # Exceeds any workday — RED regardless
```

**Rationale:**
- 6h alone = YELLOW (could be work, Tao's criterion requires "non-essential")
- 6h + emotional signal = RED (behavioral context disambiguates productive vs dependent use; supported by Fang et al.'s finding that attachment amplifies negative outcomes)
- 8h+ = RED regardless (no reasonable work pattern justifies 8+ hours of chatbot interaction)

### Code changes

| File | Function | Change |
|---|---|---|
| `risk_engine.py` | `_check_yellow_triggers()` | Add `daily_active_hours >= 6` as YELLOW trigger |
| `risk_engine.py` | `_check_red_triggers()` | Replace `daily_active_hours > 6` with two rules: `hours >= 6 AND (attachment > 0.3 OR concentration > 0.5)` and `hours >= 8` |

### Also consider: `daily_message_count > 200`

Currently standalone RED. Same logic applies:
- 200 messages in work context (coding assistant) is possible in a productive day
- 200 messages + elevated behavioral scores = crisis
- Some extreme count (500+?) = RED regardless

Decision: keep as-is for now, revisit during calibration in ch.3.

---

## Implementation Order

1. **Session sampling** — implement before running synthetic persona experiments (affects data quality)
2. **Risk engine redesign** — implement active_hours tiered thresholds
3. **Timezone acknowledgment** — write in ch.2 now, no code needed
4. **Timezone implementation** — if time permits before thesis deadline, otherwise "future work"

---

## Impact on Chapter 2

### Session sampling adds material for:
- §2.3 Этап 3: "Messages are grouped by session to preserve chronological structure of the day"
- §2.5: Previous limitation (recency bias) addressed; new limitation (session-id availability) acknowledged

### Timezone adds material for:
- §2.3 Этап 1: Context fields as data requirements
- §2.5: Limitation — current implementation uses UTC, method requires local timezone

### Risk engine redesign adds material for:
- §2.3.5 Этап 4: Cross-stage validation — volume metrics require behavioral context for RED
- §2.3.5: Literature basis for 6-hour threshold (Tao et al., 2010)
- §2.3.5: Literature basis for usage duration as predictor (Fang et al., 2025)

### New references for chapter 2:
- [28] Fang X. et al. How AI and Human Behaviors Shape Psychosocial Effects of Extended Chatbot Use. — arXiv:2503.17473, 2025. (N=981, 300K+ messages, 4 weeks; usage duration predicts dependence/isolation/problematic use)
- [29] Tao R. et al. Proposed Diagnostic Criteria for Internet Addiction. — Addiction, 2010. — Vol. 105, No. 3. — P. 556–564. (6 hours/day non-essential use, 98% inter-rater reliability)
