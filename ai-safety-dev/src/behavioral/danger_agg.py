"""Этап 2: Агрегация классов опасности из PredictTable (чистый SQL, без LLM)."""

import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, and_

from database import Session
from database.models import LiteLLM_PredictTable

logger = logging.getLogger(__name__)

# 5 классов опасности из мультиклассового классификатора
DANGER_CLASSES = ["suicide", "psychosis", "depression", "obsession", "anthropomorphism"]


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


async def _fetch_predict_rows(
    end_user_id: str, since: datetime, until: datetime | None = None,
) -> list[dict]:
    """Fetch predict JSON values from PredictTable for a user since cutoff.

    Args:
        since: lower bound (inclusive)
        until: upper bound (exclusive). Defaults to utcnow().
    """
    if until is None:
        until = datetime.utcnow()

    async with Session() as session:
        query = (
            select(LiteLLM_PredictTable.predict)
            .where(
                and_(
                    LiteLLM_PredictTable.user_id == end_user_id,
                    LiteLLM_PredictTable.created_at >= since,
                    LiteLLM_PredictTable.created_at < until,
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

    avgs = {}
    for cls in DANGER_CLASSES:
        confs = class_confidences[cls]
        avgs[cls] = sum(confs) / len(confs) if confs else 0.0

    result = {
        "suicide_avg": round(avgs["suicide"], 4),
        "suicide_max": round(max(class_confidences["suicide"], default=0.0), 4),
        "suicide_flag_rate": round(
            sum(class_flags["suicide"]) / len(class_flags["suicide"])
            if class_flags["suicide"] else 0.0, 4
        ),
        "psychosis_avg": round(avgs["psychosis"], 4),
        "psychosis_max": round(max(class_confidences["psychosis"], default=0.0), 4),
        "psychosis_flag_rate": round(
            sum(class_flags["psychosis"]) / len(class_flags["psychosis"])
            if class_flags["psychosis"] else 0.0, 4
        ),
        "depression_avg": round(avgs["depression"], 4),
        "depression_flag_rate": round(
            sum(class_flags["depression"]) / len(class_flags["depression"])
            if class_flags["depression"] else 0.0, 4
        ),
        "obsession_avg": round(avgs["obsession"], 4),
        "anthropomorphism_avg": round(avgs["anthropomorphism"], 4),
        "max_class_avg": round(max(avgs.values()), 4),
    }
    return result


async def compute_danger_class_agg(end_user_id: str) -> dict:
    """Aggregate 24h danger class scores for a user from PredictTable.

    Returns danger_class_agg JSON with all Stage 2 metrics.
    """
    # naive datetime: PredictTable.created_at is TIMESTAMP WITHOUT TIME ZONE
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    raw_rows = await _fetch_predict_rows(end_user_id, since_24h, until=now)

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
        "suicide_avg": 0.0,
        "suicide_max": 0.0,
        "suicide_flag_rate": 0.0,
        "psychosis_avg": 0.0,
        "psychosis_max": 0.0,
        "psychosis_flag_rate": 0.0,
        "depression_avg": 0.0,
        "depression_flag_rate": 0.0,
        "obsession_avg": 0.0,
        "anthropomorphism_avg": 0.0,
        "max_class_avg": 0.0,
    }
