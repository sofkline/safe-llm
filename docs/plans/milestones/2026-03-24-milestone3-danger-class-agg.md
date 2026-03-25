# Milestone 3: Danger Class Aggregation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 2 of the aggregator pipeline — aggregate per-message danger class scores from `LiteLLM_PredictTable` over the last 24h window per user, producing avg/max confidence and flag rates for all 5 classes.

**Architecture:** `danger_agg.py` queries `LiteLLM_PredictTable`, parses the `predict` JSON field (5 classes × {label, confidence}), and computes aggregate statistics. Pure Python aggregation — no extra LLM calls.

**Tech Stack:** SQLAlchemy 2.0 (async), JSON parsing

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` — Stage 2 metrics (lines 115-130) and pipeline (lines 308-320)

---

## Domain Knowledge

### PredictTable `predict` JSON structure

Each row stores the output of Mikhail's judge model:

```json
{
    "predict": {
        "obsession": {"label": 1, "confidence": 0.80},
        "self_harm": {"label": 0, "confidence": 0.10},
        "psychosis": {"label": 0, "confidence": 0.15},
        "delusion": {"label": 1, "confidence": 0.65},
        "anthropomorphism": {"label": 1, "confidence": 0.92}
    }
}
```

- `label`: 0 or 1 (binary flag)
- `confidence`: 0.0–1.0 (model confidence)
- 5 classes: `self_harm`, `psychosis`, `delusion`, `obsession`, `anthropomorphism`

### PredictTable key columns

- `user_id` (String, FK to LiteLLM_UserTable, NOT NULL)
- `predict` (JSON, NOT NULL) — the multi-label classification result
- `created_at` (DateTime, NOT NULL, server_default=CURRENT_TIMESTAMP)

### Output: 9 metrics

| Field | Computation |
|-------|-------------|
| `self_harm_avg` | AVG(confidence) for self_harm class |
| `self_harm_max` | MAX(confidence) for self_harm class |
| `self_harm_flag_rate` | COUNT(label=1) / COUNT(*) |
| `psychosis_avg` | AVG(confidence) |
| `delusion_avg` | AVG(confidence) |
| `delusion_flag_rate` | COUNT(label=1) / COUNT(*) |
| `obsession_avg` | AVG(confidence) |
| `anthropomorphism_avg` | AVG(confidence) |
| `max_class_avg` | MAX across all 5 class avg confidences |

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── danger_agg.py            # Replace stub with full Stage 2 implementation

ai-safety-dev/tests/
├── test_danger_agg.py       # Unit tests for aggregation logic
```

---

### Task 1: Implement danger class aggregation

**Files:**
- Modify: `ai-safety-dev/src/behavioral/danger_agg.py` (replace stub)
- Create: `ai-safety-dev/tests/test_danger_agg.py`

- [ ] **Step 1: Create test file**

Create `ai-safety-dev/tests/test_danger_agg.py`:

```python
"""Tests for Stage 2: Danger class aggregation."""

import pytest
from datetime import datetime, UTC
from unittest.mock import patch

from behavioral.danger_agg import (
    compute_danger_class_agg,
    _aggregate_predictions,
    _parse_predict_json,
)

CLASSES = ["self_harm", "psychosis", "delusion", "obsession", "anthropomorphism"]


class TestParsePredictJson:
    def test_parses_valid_predict(self):
        predict_json = {
            "predict": {
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.2},
                "delusion": {"label": 1, "confidence": 0.7},
                "obsession": {"label": 1, "confidence": 0.8},
                "anthropomorphism": {"label": 0, "confidence": 0.3},
            }
        }
        result = _parse_predict_json(predict_json)
        assert result["self_harm"] == {"label": 0, "confidence": 0.1}
        assert result["delusion"] == {"label": 1, "confidence": 0.7}

    def test_returns_none_for_invalid_json(self):
        assert _parse_predict_json(None) is None
        assert _parse_predict_json({}) is None
        assert _parse_predict_json({"predict": "not a dict"}) is None

    def test_missing_class_returns_none(self):
        predict_json = {"predict": {"self_harm": {"label": 0, "confidence": 0.1}}}
        # Still parses what's available
        result = _parse_predict_json(predict_json)
        assert result is not None
        assert "self_harm" in result


class TestAggregatePredictions:
    def test_single_prediction(self):
        predictions = [
            {
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.2},
                "delusion": {"label": 1, "confidence": 0.7},
                "obsession": {"label": 0, "confidence": 0.3},
                "anthropomorphism": {"label": 0, "confidence": 0.4},
            }
        ]
        result = _aggregate_predictions(predictions)
        assert result["self_harm_avg"] == 0.1
        assert result["self_harm_max"] == 0.1
        assert result["self_harm_flag_rate"] == 0.0
        assert result["delusion_avg"] == 0.7
        assert result["delusion_flag_rate"] == 1.0

    def test_multiple_predictions(self):
        predictions = [
            {
                "self_harm": {"label": 1, "confidence": 0.9},
                "psychosis": {"label": 0, "confidence": 0.1},
                "delusion": {"label": 0, "confidence": 0.2},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.1},
            },
            {
                "self_harm": {"label": 0, "confidence": 0.3},
                "psychosis": {"label": 0, "confidence": 0.3},
                "delusion": {"label": 1, "confidence": 0.8},
                "obsession": {"label": 0, "confidence": 0.2},
                "anthropomorphism": {"label": 0, "confidence": 0.2},
            },
        ]
        result = _aggregate_predictions(predictions)
        assert result["self_harm_avg"] == pytest.approx(0.6, abs=0.01)
        assert result["self_harm_max"] == 0.9
        assert result["self_harm_flag_rate"] == 0.5  # 1 out of 2
        assert result["delusion_flag_rate"] == 0.5
        assert result["max_class_avg"] == pytest.approx(0.6, abs=0.01)  # self_harm_avg

    def test_empty_predictions(self):
        result = _aggregate_predictions([])
        assert result["self_harm_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    def test_max_class_avg(self):
        """max_class_avg should be the highest avg across all 5 classes."""
        predictions = [
            {
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.1},
                "delusion": {"label": 0, "confidence": 0.1},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.9},
            },
        ]
        result = _aggregate_predictions(predictions)
        assert result["max_class_avg"] == 0.9  # anthropomorphism is highest


class TestComputeDangerClassAgg:
    @pytest.mark.asyncio
    async def test_no_predictions_returns_zeros(self):
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=[]):
            result = await compute_danger_class_agg("user1")
        assert result["self_harm_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    @pytest.mark.asyncio
    async def test_aggregates_from_db_rows(self):
        rows = [
            {
                "predict": {
                    "self_harm": {"label": 1, "confidence": 0.8},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "delusion": {"label": 0, "confidence": 0.2},
                    "obsession": {"label": 0, "confidence": 0.3},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
            {
                "predict": {
                    "self_harm": {"label": 0, "confidence": 0.2},
                    "psychosis": {"label": 0, "confidence": 0.3},
                    "delusion": {"label": 1, "confidence": 0.6},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.2},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        assert result["self_harm_avg"] == pytest.approx(0.5, abs=0.01)
        assert result["self_harm_max"] == 0.8
        assert result["self_harm_flag_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_skips_invalid_predict_json(self):
        rows = [
            None,  # invalid
            {"predict": "not_a_dict"},  # invalid
            {
                "predict": {
                    "self_harm": {"label": 0, "confidence": 0.5},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "delusion": {"label": 0, "confidence": 0.1},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        # Only 1 valid row
        assert result["self_harm_avg"] == 0.5
```

- [ ] **Step 2: Replace danger_agg.py stub**

Replace the entire `ai-safety-dev/src/behavioral/danger_agg.py`:

```python
"""Stage 2: Danger class aggregation from PredictTable."""

import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, and_

from database import Session
from database.models import LiteLLM_PredictTable

logger = logging.getLogger(__name__)

DANGER_CLASSES = ["self_harm", "psychosis", "delusion", "obsession", "anthropomorphism"]


def _parse_predict_json(predict_json) -> dict | None:
    """Parse the predict JSON from a PredictTable row.

    Returns a dict of {class_name: {"label": int, "confidence": float}} or None if invalid.
    """
    if not predict_json or not isinstance(predict_json, dict):
        return None
    predict = predict_json.get("predict")
    if not predict or not isinstance(predict, dict):
        return None
    return predict


async def _fetch_predict_rows(end_user_id: str, since: datetime) -> list[dict]:
    """Fetch predict JSON values from PredictTable for a user since cutoff."""
    async with Session() as session:
        query = (
            select(LiteLLM_PredictTable.predict)
            .where(
                and_(
                    LiteLLM_PredictTable.user_id == end_user_id,
                    LiteLLM_PredictTable.created_at >= since,
                )
            )
            .order_by(LiteLLM_PredictTable.created_at.asc())
        )
        result = await session.execute(query)
        return [row[0] for row in result.all()]


def _aggregate_predictions(predictions: list[dict]) -> dict:
    """Aggregate parsed prediction dicts into Stage 2 output metrics.

    Args:
        predictions: list of parsed predict dicts (output of _parse_predict_json)
    """
    if not predictions:
        return _empty_danger_agg()

    # Collect per-class values
    class_confidences: dict[str, list[float]] = {c: [] for c in DANGER_CLASSES}
    class_flags: dict[str, list[int]] = {c: [] for c in DANGER_CLASSES}

    for pred in predictions:
        for cls in DANGER_CLASSES:
            entry = pred.get(cls)
            if entry and isinstance(entry, dict):
                conf = entry.get("confidence", 0.0)
                label = entry.get("label", 0)
                class_confidences[cls].append(conf)
                class_flags[cls].append(label)

    # Compute per-class aggregates
    avgs = {}
    for cls in DANGER_CLASSES:
        confs = class_confidences[cls]
        avgs[cls] = sum(confs) / len(confs) if confs else 0.0

    result = {
        # Self-harm: avg, max, flag_rate
        "self_harm_avg": round(avgs["self_harm"], 4),
        "self_harm_max": round(max(class_confidences["self_harm"], default=0.0), 4),
        "self_harm_flag_rate": round(
            sum(class_flags["self_harm"]) / len(class_flags["self_harm"])
            if class_flags["self_harm"] else 0.0, 4
        ),
        # Psychosis: avg
        "psychosis_avg": round(avgs["psychosis"], 4),
        # Delusion: avg, flag_rate
        "delusion_avg": round(avgs["delusion"], 4),
        "delusion_flag_rate": round(
            sum(class_flags["delusion"]) / len(class_flags["delusion"])
            if class_flags["delusion"] else 0.0, 4
        ),
        # Obsession: avg
        "obsession_avg": round(avgs["obsession"], 4),
        # Anthropomorphism: avg
        "anthropomorphism_avg": round(avgs["anthropomorphism"], 4),
        # Max across all class avgs
        "max_class_avg": round(max(avgs.values()), 4),
    }
    return result


async def compute_danger_class_agg(end_user_id: str) -> dict:
    """Aggregate 24h danger class scores for a user from PredictTable.

    Returns danger_class_agg JSON with all Stage 2 metrics.
    """
    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)

    raw_rows = await _fetch_predict_rows(end_user_id, since_24h)

    # Parse and filter valid predictions
    predictions = []
    for row in raw_rows:
        parsed = _parse_predict_json(row)
        if parsed is not None:
            predictions.append(parsed)

    if not predictions:
        logger.info("Stage 2: no predictions for user %s in last 24h", end_user_id)
        return _empty_danger_agg()

    result = _aggregate_predictions(predictions)
    logger.info("Stage 2 complete for %s: %d predictions aggregated", end_user_id, len(predictions))
    return result


def _empty_danger_agg() -> dict:
    """Return zeroed-out danger class aggregation."""
    return {
        "self_harm_avg": 0.0,
        "self_harm_max": 0.0,
        "self_harm_flag_rate": 0.0,
        "psychosis_avg": 0.0,
        "delusion_avg": 0.0,
        "delusion_flag_rate": 0.0,
        "obsession_avg": 0.0,
        "anthropomorphism_avg": 0.0,
        "max_class_avg": 0.0,
    }
```

- [ ] **Step 3: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_danger_agg.py -v
```

- [ ] **Step 4: Run full suite**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/danger_agg.py ai-safety-dev/tests/test_danger_agg.py
git commit -m "feat(danger_agg): implement Stage 2 danger class aggregation from PredictTable

Aggregates 5 danger classes (self_harm, psychosis, delusion, obsession,
anthropomorphism) over 24h: avg/max confidence, flag rates, max_class_avg.
Replaces stub with real PredictTable queries."
```
