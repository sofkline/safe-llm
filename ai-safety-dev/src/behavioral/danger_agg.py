"""Stage 2: Danger class aggregation from PredictTable. Implemented in Milestone 3."""

import logging

logger = logging.getLogger(__name__)


async def compute_danger_class_agg(end_user_id: str) -> dict:
    """Aggregate 24h danger class scores for a user. Returns danger_class_agg JSON.

    Stub: returns empty scores. Full implementation in Milestone 3.
    """
    logger.info("Stage 2 (danger_agg): stub for user %s", end_user_id)
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
