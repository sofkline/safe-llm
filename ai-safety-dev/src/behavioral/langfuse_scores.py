"""Write behavioral scores to Langfuse as custom scores on user traces."""

import logging
from datetime import datetime, timedelta, UTC

from config import settings

logger = logging.getLogger(__name__)


async def write_behavioral_scores_to_langfuse(
    end_user_id: str,
    risk_zone: str,
    behavioral_scores: dict,
    danger_class_agg: dict,
) -> None:
    """Write behavioral monitoring scores to Langfuse for dashboard visibility.

    Finds the user's most recent trace and attaches scores to it.
    Best-effort: logs warning on failure, never raises.
    """
    try:
        from langfuse import Langfuse
        langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_API_HOST,
        )

        now = datetime.now(UTC)
        since = now - timedelta(hours=24)

        traces = langfuse.fetch_traces(
            user_id=end_user_id,
            from_timestamp=since,
            limit=1,
        )

        if not traces.data:
            logger.debug("No recent Langfuse traces for %s, skipping scores", end_user_id)
            return

        trace_id = traces.data[0].id

        zone_value = {"GREEN": 0.0, "YELLOW": 0.5, "RED": 1.0}
        langfuse.score(
            trace_id=trace_id,
            name="risk_zone",
            value=zone_value.get(risk_zone, 0.0),
            comment=risk_zone,
        )

        for key, value in behavioral_scores.items():
            langfuse.score(
                trace_id=trace_id,
                name=f"behavioral_{key}",
                value=value,
            )

        if danger_class_agg.get("max_class_avg"):
            langfuse.score(
                trace_id=trace_id,
                name="max_danger_class_avg",
                value=danger_class_agg["max_class_avg"],
            )

        langfuse.flush()
        logger.info("Langfuse scores written for %s (zone: %s)", end_user_id, risk_zone)

    except Exception as e:
        logger.warning("Failed to write Langfuse scores for %s: %s", end_user_id, e)
