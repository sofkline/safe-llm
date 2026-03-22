# LiteLLM User Management: What It Tracks and What We Need to Add

> Research for behavioral monitoring system integration.
> Date: 2026-03-12

## Table of Contents

1. [Overview](#1-overview)
2. [LiteLLM's Built-in User Management](#2-litellms-built-in-user-management)
3. [How Requests Are Associated with Users](#3-how-requests-are-associated-with-users)
4. [What LiteLLM Stores Per User (Database Tables)](#4-what-litellm-stores-per-user-database-tables)
5. [What LiteLLM Does NOT Track](#5-what-litellm-does-not-track)
6. [Integration Points for Custom Logic](#6-integration-points-for-custom-logic)
7. [Recommendation: Reuse vs Build](#7-recommendation-reuse-vs-build)

---

## 1. Overview

LiteLLM Proxy is an OpenAI-compatible gateway that sits between users and LLM providers. It has a built-in user management system focused on **cost control** and **rate limiting** -- it knows *who* is making requests and *how much they spend*, but it has no concept of *behavioral patterns* or *risk assessment*.

This document maps out exactly what LiteLLM provides and where our behavioral monitoring system needs its own data.

---

## 2. LiteLLM's Built-in User Management

### Creating a User

Users are created via the `/user/new` API endpoint. You need the master key (admin key) to do this.

```bash
curl --location 'http://localhost:4000/user/new' \
  --header 'Authorization: Bearer <master-key>' \
  --header 'Content-Type: application/json' \
  --data '{
    "user_id": "student-001",
    "max_budget": 10,
    "budget_duration": "30d",
    "tpm_limit": 10000,
    "rpm_limit": 60
  }'
```

### Fields on a User Object

The `LiteLLM_UserTable` has the following fields:

| Field | Type | Purpose |
|-------|------|---------|
| `user_id` | String (PK) | Unique identifier, you choose it |
| `user_alias` | String | Human-readable name |
| `user_email` | String | Email address |
| `user_role` | String | Role: `"internal_user"`, `"proxy_admin"`, etc. |
| `password` | String | For UI login |
| `sso_user_id` | String | SSO integration identifier |
| `team_id` | String | Default team |
| `teams` | String[] | All teams the user belongs to |
| `organization_id` | String (FK) | Organization reference |
| `max_budget` | Float | Max spend in USD |
| `spend` | Float | Current accumulated spend (USD) |
| `model_spend` | JSON | Spend broken down per model |
| `model_max_budget` | JSON | Per-model budget limits |
| `budget_duration` | String | Reset period: `"30s"`, `"30m"`, `"30h"`, `"30d"` |
| `budget_reset_at` | DateTime | Next budget reset time |
| `models` | String[] | Allowed model names |
| `max_parallel_requests` | Integer | Concurrency limit |
| `tpm_limit` | BigInteger | Tokens per minute limit |
| `rpm_limit` | BigInteger | Requests per minute limit |
| `metadata` | JSON | Arbitrary custom metadata (important for us!) |
| `policies` | String[] | Applied policies |
| `allowed_cache_controls` | String[] | Cache control settings |
| `created_at` | DateTime | When the user was created |
| `updated_at` | DateTime | Last update time |

### Other User Management Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/user/new` | POST | Create a user |
| `/user/update` | POST | Update user settings |
| `/user/info?user_id=X` | GET | Get user info + spend |
| `/user/delete` | POST | Delete a user |

---

## 3. How Requests Are Associated with Users

There are **two different "user" concepts** in LiteLLM. This is important to understand:

### 3.1. Internal Users (proxy users)

These are users who have API keys. The association flow:

```
User created (/user/new)
    -> Key generated for user (/key/generate with user_id)
        -> User sends request with key in Authorization header
            -> LiteLLM looks up key -> finds user_id -> tracks spend
```

**Request example:**
```bash
curl http://localhost:4000/chat/completions \
  -H "Authorization: Bearer sk-user-key-here" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
```

The key `sk-user-key-here` is looked up in `LiteLLM_VerificationToken`, which has a `user_id` field linking it to the user.

### 3.2. End Users (the actual humans using your app)

If you build an app where your backend calls LiteLLM on behalf of end users, you can pass the `user` parameter:

```bash
curl http://localhost:4000/chat/completions \
  -H "Authorization: Bearer sk-your-backend-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "user": "end-user-123",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

End users are tracked in a separate table: `LiteLLM_EndUserTable`. This table is very minimal:

| Field | Type | Purpose |
|-------|------|---------|
| `user_id` | String (PK) | End user identifier |
| `alias` | String | Display name |
| `spend` | Float | Accumulated spend |
| `allowed_model_region` | String | Region restriction |
| `default_model` | String | Default model |
| `budget_id` | String (FK) | Budget reference |
| `blocked` | Boolean | Whether user is blocked |

### Which One Matters for Behavioral Monitoring?

For our purposes, **end users** are the ones whose behavior we want to monitor. The `user` parameter in chat completions is how we identify them. Internal users are more like service accounts or developers.

---

## 4. What LiteLLM Stores Per User (Database Tables)

### 4.1. Core Tables in Mikhail's Models

Mikhail's codebase (`src/database/models.py`) already mirrors the full LiteLLM schema. Here are the tables relevant to user tracking:

#### `LiteLLM_SpendLogs` -- Per-Request Log (the most valuable table for us)

Every API request creates a row here:

| Field | Type | What It Contains |
|-------|------|-----------------|
| `request_id` | String (PK) | Unique request ID |
| `call_type` | String | `"completion"`, `"embedding"`, etc. |
| `api_key` | String | Which key was used (hashed) |
| `user` | String | Internal user ID (from key) |
| `end_user` | String | End user ID (from `user` param) |
| `team_id` | String | Team of the key |
| `model` | String | Model used |
| `spend` | Float | Cost in USD |
| `prompt_tokens` | Integer | Input tokens |
| `completion_tokens` | Integer | Output tokens |
| `total_tokens` | Integer | Total tokens |
| `startTime` | DateTime | Request start |
| `endTime` | DateTime | Request end |
| `completionStartTime` | DateTime | When first token arrived |
| `messages` | JSON | The actual messages sent |
| `response` | JSON | The actual response |
| `metadata` | JSON | Custom metadata from request |
| `request_tags` | JSON | Tags attached to request |
| `session_id` | String | Session identifier |
| `status` | String | Success/failure |
| `requester_ip_address` | String | IP address |
| `cache_hit` | String | Whether cache was used |

This is very rich data. Note that `messages` and `response` contain the actual conversation content (unless message redaction is enabled).

#### `LiteLLM_DailyUserSpend` -- Aggregated Daily Metrics

Pre-aggregated daily spend per user:

| Field | Type |
|-------|------|
| `user_id` | String |
| `date` | String |
| `api_key` | String |
| `model` | String |
| `prompt_tokens` | BigInteger |
| `completion_tokens` | BigInteger |
| `spend` | Float |
| `api_requests` | BigInteger |
| `successful_requests` | BigInteger |
| `failed_requests` | BigInteger |

#### `LiteLLM_ErrorLogs` -- Failed Requests

| Field | Type |
|-------|------|
| `request_id` | String (PK) |
| `exception_type` | String |
| `exception_string` | String |
| `model_group` | String |
| `startTime` / `endTime` | DateTime |

#### `LiteLLM_AuditLog` -- Admin Actions

Tracks who changed what (user creation, key generation, settings changes):

| Field | Type |
|-------|------|
| `changed_by` | String |
| `action` | String |
| `table_name` | String |
| `object_id` | String |
| `before_value` / `updated_values` | JSON |

---

## 5. What LiteLLM Does NOT Track

LiteLLM is a cost management and routing proxy. Here is what it has **no concept of** that we need for behavioral monitoring:

| Behavioral Metric | Why We Need It | LiteLLM Status |
|-------------------|---------------|----------------|
| **Session frequency** | How often does a user start new sessions? Increasing frequency may indicate growing dependency | Not tracked. `session_id` exists in SpendLogs but there's no session management |
| **Message patterns over time** | Escalation in tone, complexity, emotional content | Messages are logged raw, but no analysis is performed |
| **Dependency indicators** | Signs that a user is becoming over-reliant on LLM | No concept exists |
| **Risk scores** | Computed assessment of user risk level | No concept exists |
| **Intervention state** | Has the user been warned? Are they in a cooldown? | No concept exists |
| **Conversation topic classification** | What categories of questions are being asked | No concept exists |
| **Time-of-day patterns** | Late-night usage, changes in schedule | Timestamps exist in SpendLogs but no analysis |
| **Response satisfaction** | Did the user accept the response or re-ask? | Not tracked |
| **Escalation patterns** | Does the user rephrase angrily when they get safety refusals? | Not tracked |
| **User profile/demographics** | Age, context, vulnerability factors | Only `metadata` JSON exists (freeform) |
| **Behavioral baselines** | What is "normal" for this user? | No concept exists |

### Summary

LiteLLM knows: **who spent how much on which model.**
LiteLLM does not know: **how the user behaves, whether they're at risk, or what to do about it.**

---

## 6. Integration Points for Custom Logic

### 6.1. Custom Callbacks (Best Integration Point)

LiteLLM supports custom callback classes that fire on every request. This is where behavioral monitoring logic should hook in.

```python
from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy.proxy_server import UserAPIKeyAuth

class BehavioralMonitor(CustomLogger):

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,  # Contains user_id, metadata
        cache,
        data: dict,           # The request: model, messages, etc.
        call_type: str,       # "completion", "embedding", etc.
    ) -> dict:
        """
        Runs BEFORE the request goes to the LLM.
        Can modify or reject the request.
        """
        user_id = user_api_key_dict.user_id
        messages = data.get("messages", [])

        # Example: check risk score, inject warnings, block if needed
        # Return data dict to proceed, return a string to reject
        return data

    async def async_log_success_event(
        self,
        kwargs,           # Contains model, messages, user
        response_obj,     # The LLM response
        start_time,
        end_time,
    ):
        """
        Runs AFTER a successful response.
        Use this to update behavioral metrics.
        """
        user = kwargs.get("user")
        messages = kwargs.get("messages")
        metadata = kwargs.get("litellm_params", {}).get("metadata", {})
        # Update behavioral database here

    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: UserAPIKeyAuth,
        response,
    ):
        """
        Can modify the response before it's sent to the user.
        Example: append a wellness check message if risk is elevated.
        """
        pass
```

**Configuration** in `config.yaml`:
```yaml
litellm_settings:
  callbacks: my_module.behavioral_monitor_instance
```

### 6.2. User Metadata Field

The `metadata` JSON field on `LiteLLM_UserTable` can store arbitrary data. We could store a lightweight risk summary here:

```json
{
  "risk_level": "medium",
  "last_assessment": "2026-03-12T10:00:00",
  "flags": ["increasing_frequency", "late_night_usage"]
}
```

Update it via:
```bash
curl -X POST http://localhost:4000/user/update \
  -H "Authorization: Bearer <master-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "student-001",
    "metadata": {"risk_level": "medium", "last_assessment": "2026-03-12"}
  }'
```

However, this is **not a substitute for a proper behavioral database**. It's useful for quick lookups during request processing (e.g., "should I inject a warning for this user?").

### 6.3. Request Tags and Metadata

Every request can carry custom metadata and tags:

```python
response = client.chat.completions.create(
    model="gpt-4",
    messages=[...],
    extra_body={
        "metadata": {
            "session_type": "academic",
            "trace_id": "session-abc-123",
        },
        "tags": ["monitored", "high-risk-user"]
    }
)
```

These get stored in `LiteLLM_SpendLogs.metadata` and `request_tags`. Our monitoring system can use tags to mark requests that triggered behavioral flags.

### 6.4. Data Available in Callbacks

Inside callback hooks, `UserAPIKeyAuth` provides:

- `user_id` -- the internal user
- `team_id` -- team membership
- `metadata` -- custom metadata from the key
- `key_alias` -- human-readable key name
- `max_budget`, `spend` -- budget info

And `kwargs` provides:
- `model` -- which model
- `messages` -- the full conversation
- `user` -- end user ID
- All standard LLM parameters (temperature, etc.)

---

## 7. Recommendation: Reuse vs Build

### Reuse from LiteLLM (do not rebuild)

| Capability | LiteLLM Table | Notes |
|-----------|---------------|-------|
| User identity and authentication | `LiteLLM_UserTable` + `LiteLLM_VerificationToken` | Use LiteLLM's user_id as the foreign key in our tables |
| End user identity | `LiteLLM_EndUserTable` | For tracking the actual humans |
| Per-request logging | `LiteLLM_SpendLogs` | Rich data: messages, response, tokens, timing, session_id |
| Spend tracking | `LiteLLM_UserTable.spend` + `LiteLLM_DailyUserSpend` | Cost monitoring is already done |
| Rate limiting | `tpm_limit`, `rpm_limit` on User/Key | Already enforced |
| Request blocking | `LiteLLM_EndUserTable.blocked` | Can block users |
| Admin audit trail | `LiteLLM_AuditLog` | Tracks config changes |

### Build Custom (new tables needed)

| What | Why | Suggested Table |
|------|-----|-----------------|
| **User behavioral profile** | Store computed risk scores, behavioral baselines, vulnerability flags | `behavioral_user_profiles` |
| **Behavioral events** | Individual detected events: "late night spike", "emotional escalation", "dependency signal" | `behavioral_events` |
| **Risk assessments** | Historical risk scores with reasoning, computed periodically | `risk_assessments` |
| **Interventions** | Records of actions taken: warning injected, session limited, human notified | `interventions` |
| **Session analysis** | Per-session aggregates: message count, topic drift, sentiment trajectory | `session_analyses` |
| **Monitoring rules** | Configurable thresholds and detection rules | `monitoring_rules` |

### Suggested Schema Sketch for Custom Tables

```sql
-- Links to LiteLLM's user_id (either UserTable or EndUserTable)
CREATE TABLE behavioral_user_profiles (
    user_id         TEXT PRIMARY KEY REFERENCES "LiteLLM_EndUserTable"(user_id),
    risk_level      TEXT DEFAULT 'low',        -- low / medium / high / critical
    risk_score      FLOAT DEFAULT 0.0,         -- 0.0 to 1.0
    baseline_rpm    FLOAT,                     -- normal requests per minute
    baseline_daily  INTEGER,                   -- normal daily request count
    flags           JSONB DEFAULT '[]',        -- active behavioral flags
    last_assessed   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE behavioral_events (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT REFERENCES behavioral_user_profiles(user_id),
    event_type      TEXT NOT NULL,             -- 'frequency_spike', 'emotional_escalation', etc.
    severity        TEXT NOT NULL,             -- 'info', 'warning', 'alert'
    details         JSONB,                    -- event-specific data
    request_id      TEXT,                     -- FK to LiteLLM_SpendLogs if applicable
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE interventions (
    id              SERIAL PRIMARY KEY,
    user_id         TEXT REFERENCES behavioral_user_profiles(user_id),
    intervention_type TEXT NOT NULL,           -- 'warning_injected', 'rate_reduced', 'human_notified'
    trigger_event_id INTEGER REFERENCES behavioral_events(id),
    status          TEXT DEFAULT 'active',     -- 'active', 'acknowledged', 'expired'
    details         JSONB,
    created_at      TIMESTAMP DEFAULT NOW(),
    resolved_at     TIMESTAMP
);
```

### Architecture Diagram

```
User Request
    |
    v
LiteLLM Proxy
    |
    +-- [async_pre_call_hook] --> Check behavioral_user_profiles
    |                             If risk is high -> inject warning / block
    |
    +-- Forward to LLM Provider
    |
    +-- [async_log_success_event] --> Write to behavioral_events
    |                                  Update behavioral_user_profiles
    |
    +-- LiteLLM_SpendLogs (automatic)
    |
    v
Response to User (possibly modified with safety messages)
```

### Key Design Decisions

1. **Reference LiteLLM's user_id, don't copy user data.** Our tables use `user_id` as a foreign key to LiteLLM's tables. We don't duplicate name, email, etc.

2. **Read from SpendLogs, don't re-log requests.** LiteLLM already stores messages, tokens, timing. Our behavioral analysis reads from SpendLogs rather than capturing its own copy.

3. **Use callbacks for real-time, batch jobs for deep analysis.** The `async_pre_call_hook` does quick risk checks. A separate background job runs periodically to compute risk scores from SpendLogs history.

4. **Store risk state in our tables, cache a summary in LiteLLM metadata.** The full behavioral profile lives in our tables. A lightweight `{"risk_level": "high"}` gets synced to LiteLLM's user metadata for fast access in callbacks.

---

## Sources

- LiteLLM docs: [Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
- LiteLLM docs: [Users / Budgets](https://docs.litellm.ai/docs/proxy/users)
- LiteLLM docs: [Logging & Callbacks](https://docs.litellm.ai/docs/proxy/logging)
- LiteLLM docs: [Call Hooks](https://docs.litellm.ai/docs/proxy/call_hooks)
- Mikhail's database models: `src/database/models.py` in this repository
