"""Stage 3: Behavioral LLM scores + daily summary. Implemented in Milestone 4."""

import logging
from datetime import date

logger = logging.getLogger(__name__)


async def compute_behavioral_scores_and_summary(
    end_user_id: str,
    today: date | None = None,
) -> dict:
    """Run LLM analysis on recent messages + calendar. Returns scores + summary.

    Stub: returns default scores and empty summary. Full implementation in Milestone 4.
    """
    logger.info("Stage 3 (behavioral_llm): stub for user %s", end_user_id)
    return {
        "scores": {
            "topic_concentration": 0.0,
            "decision_delegation": 0.0,
            "social_isolation": 0.0,
            "emotional_attachment": 0.0,
        },
        "summary": {
            "key_topics": [],
            "life_events": [],
            "emotional_tone": "neutral",
            "ai_relationship_markers": [],
            "notable_quotes": [],
            "operator_note": None,
        },
    }
