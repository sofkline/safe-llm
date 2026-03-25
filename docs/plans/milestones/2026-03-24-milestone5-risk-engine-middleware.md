# Milestone 5: Risk Zone Engine + Soft Middleware — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the rule-based risk zone engine (Stage 4) with YELLOW/RED threshold rules, and extend the existing middleware to inject safety prompts based on the user's risk zone.

**Architecture:** `risk_engine.py` evaluates rules from 3 inputs (temporal + danger + behavioral) plus MetricsHistory for sustained-YELLOW check. The middleware extends `BinaryUserSafetyGuardrailMiddleware.dispatch()` to look up `risk_zone` from `UserBehaviorProfile` and prepend a fixed system message for YELLOW/RED users. Also fix the aggregator to emit events on RED triggers (not just zone changes).

**Tech Stack:** SQLAlchemy 2.0 (async), Starlette middleware

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` — Stage 4 (lines 342-368), Soft Middleware (lines 379-420), Risk Zone Thresholds (lines 553-575)

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── risk_engine.py           # Replace stub with full rule-based engine

ai-safety-dev/src/
├── middleware.py             # Extend dispatch() with risk_zone lookup + prompt injection

ai-safety-dev/src/behavioral/
├── aggregator.py            # Fix: emit events on RED triggers, not just zone changes

ai-safety-dev/tests/
├── test_risk_engine.py      # Threshold rule tests
├── test_middleware_behavioral.py  # Soft middleware injection tests
```

---

### Task 1: Implement risk zone engine

**Files:**
- Replace: `ai-safety-dev/src/behavioral/risk_engine.py`
- Create: `ai-safety-dev/tests/test_risk_engine.py`

- [ ] **Step 1: Create test file**

Create `ai-safety-dev/tests/test_risk_engine.py`:

```python
"""Tests for Stage 4: Risk zone engine."""

import pytest
from unittest.mock import AsyncMock, patch

from behavioral.risk_engine import evaluate_risk_zone


# --- Helper: default metrics dicts (all safe/GREEN) ---

def _green_temporal():
    return {
        "daily_message_count": 10,
        "night_messages": 0,
        "daily_active_hours": 1,
        "avg_inter_message_interval_min": 5.0,
    }

def _green_danger():
    return {
        "self_harm_avg": 0.0,
        "self_harm_max": 0.0,
        "self_harm_flag_rate": 0.0,
        "max_class_avg": 0.0,
    }

def _green_behavioral():
    return {
        "topic_concentration": 0.0,
        "decision_delegation": 0.0,
        "social_isolation": 0.0,
        "emotional_attachment": 0.0,
    }

def _green_baselines():
    return {
        "avg_daily_messages": 10,
        "avg_inter_message_interval": 5.0,
    }


class TestGreenZone:
    @pytest.mark.asyncio
    async def test_all_safe_returns_green(self):
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"
        assert rules == []


class TestYellowZone:
    """YELLOW requires any 2 triggers."""

    @pytest.mark.asyncio
    async def test_single_trigger_stays_green(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 30  # 1 trigger
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"

    @pytest.mark.asyncio
    async def test_two_triggers_yellow(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 30  # trigger 1
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8  # trigger 2
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
        assert "night_messages > 24" in rules
        assert "topic_concentration > 0.7" in rules

    @pytest.mark.asyncio
    async def test_night_messages_trigger(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 25
        behavioral = _green_behavioral()
        behavioral["decision_delegation"] = 0.5
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
        assert "night_messages > 24" in rules
        assert "decision_delegation > 0.4" in rules

    @pytest.mark.asyncio
    async def test_high_frequency_trending_up(self):
        temporal = _green_temporal()
        temporal["daily_message_count"] = 60
        danger = _green_danger()
        danger["max_class_avg"] = 0.35
        zone, rules = await evaluate_risk_zone(
            temporal, danger, _green_behavioral(),
            baselines={"avg_daily_messages": 20, "avg_inter_message_interval": 5.0},
        )
        assert zone == "YELLOW"
        assert "daily_message_count > 50 AND trending up" in rules
        assert "max_class_avg > 0.3" in rules

    @pytest.mark.asyncio
    async def test_interval_shrinking(self):
        temporal = _green_temporal()
        temporal["avg_inter_message_interval_min"] = 3.0
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines={"avg_daily_messages": 10, "avg_inter_message_interval": 5.0},
        )
        assert zone == "YELLOW"
        assert "interval_shrinking > 30%" in rules


class TestRedZone:
    """RED requires any 1 trigger. RED overrides YELLOW."""

    @pytest.mark.asyncio
    async def test_self_harm_flag_rate(self):
        danger = _green_danger()
        danger["self_harm_flag_rate"] = 0.4
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "self_harm_flag_rate > 0.3" in rules

    @pytest.mark.asyncio
    async def test_self_harm_max(self):
        danger = _green_danger()
        danger["self_harm_max"] = 0.85
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "self_harm_max > 0.8" in rules

    @pytest.mark.asyncio
    async def test_daily_active_hours(self):
        temporal = _green_temporal()
        temporal["daily_active_hours"] = 7
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "daily_active_hours > 6" in rules

    @pytest.mark.asyncio
    async def test_volume_spike(self):
        temporal = _green_temporal()
        temporal["daily_message_count"] = 250
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "daily_message_count > 200" in rules

    @pytest.mark.asyncio
    async def test_isolation_plus_attachment(self):
        behavioral = _green_behavioral()
        behavioral["social_isolation"] = 0.7
        behavioral["emotional_attachment"] = 0.6
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "social_isolation > 0.6 AND emotional_attachment > 0.5" in rules

    @pytest.mark.asyncio
    async def test_sustained_yellow(self):
        """YELLOW for >=3 consecutive days triggers RED."""
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW"})(),
            type("H", (), {"risk_zone": "YELLOW"})(),
            type("H", (), {"risk_zone": "YELLOW"})(),
        ]
        # Need 2 YELLOW triggers to be in YELLOW first
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "RED"
        assert "sustained_yellow >= 3 days" in rules

    @pytest.mark.asyncio
    async def test_red_overrides_yellow(self):
        """If both YELLOW and RED triggers fire, result is RED."""
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        temporal["daily_active_hours"] = 7  # RED trigger
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "RED"
```

- [ ] **Step 2: Replace risk_engine.py**

Replace `ai-safety-dev/src/behavioral/risk_engine.py`:

```python
"""Stage 4: Rule-based risk zone engine."""

import logging

logger = logging.getLogger(__name__)


async def evaluate_risk_zone(
    temporal_metrics: dict,
    danger_class_agg: dict,
    behavioral_scores: dict,
    baselines: dict | None = None,
    recent_history: list | None = None,
) -> tuple[str, list[str]]:
    """Evaluate risk zone from all stage outputs.

    Args:
        temporal_metrics: Stage 1 output
        danger_class_agg: Stage 2 output
        behavioral_scores: Stage 3 scores
        baselines: 7-day rolling averages for trend detection
        recent_history: last N MetricsHistory rows for sustained-YELLOW check

    Returns:
        (zone, triggered_rules) where zone is GREEN/YELLOW/RED
    """
    if baselines is None:
        baselines = {}
    if recent_history is None:
        recent_history = []

    yellow_triggers = _check_yellow_triggers(temporal_metrics, danger_class_agg, behavioral_scores, baselines)
    red_triggers = _check_red_triggers(temporal_metrics, danger_class_agg, behavioral_scores)

    # Sustained YELLOW check: YELLOW for >=3 consecutive days
    if len(recent_history) >= 3:
        last_3_zones = [h.risk_zone for h in recent_history[:3]]
        if all(z == "YELLOW" for z in last_3_zones):
            red_triggers.append("sustained_yellow >= 3 days")

    # Determine zone: RED (any 1) > YELLOW (any 2) > GREEN
    all_triggers = []
    if red_triggers:
        all_triggers = red_triggers + yellow_triggers
        zone = "RED"
    elif len(yellow_triggers) >= 2:
        all_triggers = yellow_triggers
        zone = "YELLOW"
    else:
        zone = "GREEN"

    if all_triggers:
        logger.info("Risk zone %s for triggers: %s", zone, all_triggers)

    return zone, all_triggers


def _check_yellow_triggers(
    temporal: dict, danger: dict, behavioral: dict, baselines: dict
) -> list[str]:
    """Check all YELLOW trigger rules. Returns list of triggered rule names."""
    triggers = []

    # Night activity: night_messages > 24
    if temporal.get("night_messages", 0) > 24:
        triggers.append("night_messages > 24")

    # High frequency + growing: daily_message_count > 50 AND trending up
    daily_msgs = temporal.get("daily_message_count", 0)
    baseline_msgs = baselines.get("avg_daily_messages", 0)
    if daily_msgs > 50 and baseline_msgs > 0 and daily_msgs > baseline_msgs * 1.5:
        triggers.append("daily_message_count > 50 AND trending up")

    # Classifier signal: max_class_avg > 0.3
    if danger.get("max_class_avg", 0) > 0.3:
        triggers.append("max_class_avg > 0.3")

    # Topic concentration > 0.7
    if behavioral.get("topic_concentration", 0) > 0.7:
        triggers.append("topic_concentration > 0.7")

    # Decision delegation > 0.4
    if behavioral.get("decision_delegation", 0) > 0.4:
        triggers.append("decision_delegation > 0.4")

    # Compulsive return: interval shrinking >30% vs baseline
    baseline_interval = baselines.get("avg_inter_message_interval", 0)
    current_interval = temporal.get("avg_inter_message_interval_min", 0)
    if baseline_interval > 0 and current_interval > 0:
        decrease = (baseline_interval - current_interval) / baseline_interval
        if decrease > 0.3:
            triggers.append("interval_shrinking > 30%")

    return triggers


def _check_red_triggers(
    temporal: dict, danger: dict, behavioral: dict
) -> list[str]:
    """Check all RED trigger rules. Returns list of triggered rule names."""
    triggers = []

    # Self-harm spike: flag_rate > 0.3 OR max > 0.8
    if danger.get("self_harm_flag_rate", 0) > 0.3:
        triggers.append("self_harm_flag_rate > 0.3")
    if danger.get("self_harm_max", 0) > 0.8:
        triggers.append("self_harm_max > 0.8")

    # Sustained usage: daily_active_hours > 6
    if temporal.get("daily_active_hours", 0) > 6:
        triggers.append("daily_active_hours > 6")

    # Volume spike: daily_message_count > 200
    if temporal.get("daily_message_count", 0) > 200:
        triggers.append("daily_message_count > 200")

    # Isolation + attachment: social_isolation > 0.6 AND emotional_attachment > 0.5
    if behavioral.get("social_isolation", 0) > 0.6 and behavioral.get("emotional_attachment", 0) > 0.5:
        triggers.append("social_isolation > 0.6 AND emotional_attachment > 0.5")

    return triggers
```

- [ ] **Step 3: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_risk_engine.py -v
```

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/src/behavioral/risk_engine.py ai-safety-dev/tests/test_risk_engine.py
git commit -m "feat(risk_engine): implement rule-based risk zone engine (Stage 4)

YELLOW: any 2 of 6 triggers (night, frequency, classifier, topic, delegation, interval).
RED: any 1 of 5 triggers (self-harm, hours, volume, sustained YELLOW, isolation+attachment).
RED overrides YELLOW. Extensible interface for future LLM-based evaluation."
```

---

### Task 2: Wire risk engine into aggregator with baselines + history

**Files:**
- Modify: `ai-safety-dev/src/behavioral/aggregator.py`
- Modify: `ai-safety-dev/tests/test_aggregator_skeleton.py`

The risk engine now needs `baselines` and `recent_history` parameters. Also fix: emit BehavioralEvent on RED triggers, not just zone changes (spec line 375).

- [ ] **Step 1: Update aggregator**

In `ai-safety-dev/src/behavioral/aggregator.py`, update the Stage 4 call (currently around line 55):

FROM:
```python
    risk_zone, triggered_rules = await evaluate_risk_zone(
        temporal_metrics, danger_class_agg, behavioral_scores
    )
```

TO:
```python
    risk_zone, triggered_rules = await evaluate_risk_zone(
        temporal_metrics, danger_class_agg, behavioral_scores,
        baselines=baselines,
        recent_history=recent_history,
    )
```

Also update the BehavioralEvent condition (currently around line 112):

FROM:
```python
    if risk_zone != old_zone:
```

TO:
```python
    if risk_zone != old_zone or risk_zone == "RED":
```

- [ ] **Step 2: Update aggregator tests**

In `test_aggregator_skeleton.py`, update the mock for `evaluate_risk_zone` — it now accepts `baselines` and `recent_history` kwargs. The existing `assert_awaited_once()` calls should still work since mock accepts any args. But the zone-unchanged test needs updating since RED now always emits events.

In `test_pipeline_no_event_when_zone_unchanged`, change:
- mock risk_zone returns "GREEN" (unchanged from GREEN) → `add_event` should NOT be called (this stays the same)

Add a new test:
```python
    @pytest.mark.asyncio
    async def test_pipeline_emits_event_on_repeated_red(self):
        """RED zone always emits event even when zone unchanged."""
        mock_repo = AsyncMock()
        mock_profile = AsyncMock()
        mock_profile.risk_zone = "RED"  # already RED
        mock_repo.get_profile.return_value = mock_profile
        mock_repo.get_recent_metrics.return_value = []

        with (
            patch("behavioral.aggregator.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.aggregator.compute_temporal_metrics", return_value={}),
            patch("behavioral.aggregator.compute_danger_class_agg", return_value={}),
            patch("behavioral.aggregator.compute_behavioral_scores_and_summary", return_value={
                "scores": {},
                "summary": {
                    "key_topics": [], "life_events": [], "emotional_tone": "neutral",
                    "ai_relationship_markers": [], "notable_quotes": [], "operator_note": None,
                },
            }),
            patch("behavioral.aggregator.evaluate_risk_zone", return_value=("RED", ["self_harm_flag_rate > 0.3"])),
        ):
            await run_aggregator_for_user("test_user")
            mock_repo.add_event.assert_awaited_once()  # event emitted even though zone stayed RED
```

- [ ] **Step 3: Run all tests**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/src/behavioral/aggregator.py ai-safety-dev/tests/test_aggregator_skeleton.py
git commit -m "feat(aggregator): pass baselines + history to risk engine, emit RED events

Risk engine now receives baselines for trend detection and recent history
for sustained-YELLOW check. BehavioralEvents emitted on zone change OR RED."
```

---

### Task 3: Implement soft middleware

**Files:**
- Modify: `ai-safety-dev/src/middleware.py`
- Create: `ai-safety-dev/tests/test_middleware_behavioral.py`

- [ ] **Step 1: Create test file**

Create `ai-safety-dev/tests/test_middleware_behavioral.py`:

```python
"""Tests for soft middleware — risk zone prompt injection."""

import pytest
import json
from unittest.mock import patch, AsyncMock, MagicMock
from starlette.testclient import TestClient


# Test the injection logic in isolation (not full middleware stack)
from behavioral.repository import BehavioralRepository

YELLOW_TEMPLATE = """This user may be developing an unhealthy interaction pattern with AI.
Encourage taking breaks. Suggest offline activities and real-world social
connections. Do not reinforce emotional dependency. If the user asks you
to make personal decisions, redirect them to think independently."""

RED_TEMPLATE = """This user shows signs of significant emotional distress or unhealthy AI
dependency. Keep responses brief and grounding. Do not role-play as a
companion, friend, or loved one. If the user expresses self-harm or
crisis, provide professional help resources. Suggest contacting a trusted
person or mental health professional. Do not engage in extended emotional
conversations."""


class TestRiskZonePromptInjection:
    def test_green_no_injection(self):
        """GREEN zone should not modify the messages."""
        from middleware import _inject_risk_zone_prompt
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "GREEN")
        assert result == messages  # unchanged
        assert len(result) == 1

    def test_yellow_prepends_system_message(self):
        from middleware import _inject_risk_zone_prompt
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "YELLOW")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "unhealthy interaction pattern" in result[0]["content"]
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_red_prepends_system_message(self):
        from middleware import _inject_risk_zone_prompt
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "RED")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "emotional distress" in result[0]["content"]

    def test_none_zone_no_injection(self):
        """No profile (new user) should not modify messages."""
        from middleware import _inject_risk_zone_prompt
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, None)
        assert result == messages

    def test_preserves_existing_system_message(self):
        """Injection should prepend BEFORE existing system messages."""
        from middleware import _inject_risk_zone_prompt
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = _inject_risk_zone_prompt(messages, "RED")
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "emotional distress" in result[0]["content"]
        assert result[1] == {"role": "system", "content": "You are a helpful assistant"}
```

- [ ] **Step 2: Add injection function to middleware.py**

Add at the bottom of `ai-safety-dev/src/middleware.py`:

```python
# --- Soft Middleware: Risk Zone Prompt Injection ---

_YELLOW_PROMPT = """This user may be developing an unhealthy interaction pattern with AI.
Encourage taking breaks. Suggest offline activities and real-world social
connections. Do not reinforce emotional dependency. If the user asks you
to make personal decisions, redirect them to think independently."""

_RED_PROMPT = """This user shows signs of significant emotional distress or unhealthy AI
dependency. Keep responses brief and grounding. Do not role-play as a
companion, friend, or loved one. If the user expresses self-harm or
crisis, provide professional help resources. Suggest contacting a trusted
person or mental health professional. Do not engage in extended emotional
conversations."""

_ZONE_PROMPTS = {
    "YELLOW": _YELLOW_PROMPT,
    "RED": _RED_PROMPT,
}


def _inject_risk_zone_prompt(messages: list, risk_zone: str | None) -> list:
    """Prepend a safety system message based on risk zone.

    GREEN or None → no modification.
    YELLOW/RED → prepend fixed template at position 0.
    """
    if not risk_zone or risk_zone == "GREEN":
        return messages
    template = _ZONE_PROMPTS.get(risk_zone)
    if not template:
        return messages
    return [{"role": "system", "content": template}] + messages
```

- [ ] **Step 3: Integrate into dispatch method**

In the `dispatch` method of `BinaryUserSafetyGuardrailMiddleware`, add the risk zone lookup and injection AFTER the binary classification and BEFORE forwarding. Add import at top:

```python
from behavioral.repository import BehavioralRepository
```

In `dispatch`, after `payload['metadata'] = metadata` (around line 89) and before the `receive()` function, add:

```python
        # Soft middleware: inject risk zone prompt
        end_user = payload.get("user") or request.headers.get("x-openwebui-user-id")
        if end_user:
            try:
                repo = BehavioralRepository()
                risk_zone = await repo.get_risk_zone(end_user)
                if risk_zone and risk_zone != "GREEN":
                    payload["messages"] = _inject_risk_zone_prompt(
                        payload.get("messages", []), risk_zone
                    )
            except Exception:
                pass  # fail open — don't block requests on DB errors
```

- [ ] **Step 4: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_middleware_behavioral.py -v
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/middleware.py ai-safety-dev/tests/test_middleware_behavioral.py
git commit -m "feat(middleware): add soft risk zone prompt injection

Extends BinaryUserSafetyGuardrailMiddleware to look up risk_zone from
UserBehaviorProfile and prepend fixed YELLOW/RED safety system messages.
GREEN/new users pass through unmodified. Fail-open on DB errors."
```
