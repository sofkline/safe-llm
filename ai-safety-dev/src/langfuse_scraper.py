# Скрапер: читает трейсы из Langfuse, классифицирует (5 классов), записывает в PredictTable
# Запускается планировщиком каждый час (или каждые 5с в dev mode)
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from classificators import daily_classification
from config import settings
from database.models import LiteLLM_PredictTable
from database.repository import PredictRepository

logger = logging.getLogger("langfuse.scraper")


def _get_langfuse_client():
    """Create a Langfuse client using project settings."""
    from langfuse import Langfuse
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_API_HOST,
    )


def _last_hour_window(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=settings.SCRAPE_HOURS_WINDOW)
    return start, end


def _extract_session_id(trace) -> Optional[str]:
    """Extract session_id from a Langfuse trace object."""
    # SDK trace objects have .session_id attribute
    if hasattr(trace, "session_id") and trace.session_id:
        return trace.session_id
    # Fallback for dict-like access
    if isinstance(trace, dict):
        for key in ("sessionId", "session_id", "sessionID"):
            value = trace.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _extract_user_id(trace) -> Optional[str]:
    """Extract user_id from trace metadata.

    LiteLLM stores user info in metadata.attributes.metadata as JSON string.
    """
    metadata = getattr(trace, "metadata", None) or {}
    if isinstance(metadata, dict):
        meta_str = metadata.get("attributes", {}).get("metadata")
        if meta_str:
            try:
                meta = json.loads(meta_str)
                return meta.get("user_api_key_user_id")
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def _extract_messages(trace) -> list[dict]:
    """Extract conversation messages from a trace."""
    trace_input = getattr(trace, "input", None) or []
    trace_output = getattr(trace, "output", None)
    if isinstance(trace_input, list):
        messages = trace_input[:]
    else:
        messages = []
    if trace_output:
        messages.append(trace_output)
    return [m for m in messages if isinstance(m, dict)]


async def scrape_sessions_for_previous_hour() -> None:
    """Основная функция скрапера: Langfuse -> classify -> PredictTable."""
    start, end = _last_hour_window()
    predict_repository = PredictRepository()
    langfuse = _get_langfuse_client()

    # Шаг 1: забираем все трейсы за последний час из Langfuse
    try:
        traces_response = langfuse.fetch_traces(
            from_timestamp=start,
            to_timestamp=end,
        )
        traces = traces_response.data if traces_response.data else []
    except Exception:
        logger.exception("Failed to fetch traces from Langfuse")
        return

    # Шаг 2: группируем трейсы по session_id
    session_traces: dict[str, list] = {}
    for trace in traces:
        session_id = _extract_session_id(trace)
        if session_id:
            session_traces.setdefault(session_id, []).append(trace)

    logger.info("Langfuse scraper: found %d sessions from %d traces", len(session_traces), len(traces))

    # Шаг 3: для каждой сессии — классифицируем и сохраняем в PredictTable
    for session_id, session_trace_list in session_traces.items():
        try:
            sorted_traces = sorted(
                session_trace_list,
                key=lambda t: getattr(t, "timestamp", datetime.min.replace(tzinfo=timezone.utc)),
            )
            last_trace = sorted_traces[-1]

            user_id = _extract_user_id(last_trace)
            if not user_id:
                logger.warning("Session %s: no user_api_key_user_id, skipping", session_id)
                continue

            messages = _extract_messages(last_trace)
            if not messages:
                logger.warning("Session %s: no messages in last trace, skipping", session_id)
                continue

            trace_id = getattr(last_trace, "id", None) or ""

            # Пропускаем, если эту сессию уже классифицировали
            cur_predict = await predict_repository.get_by_session_id(session_id)
            if cur_predict is None or cur_predict.last_trace_id != trace_id:
                conversation = "\n\n".join(
                    f"{msg['role']}: {msg['content']}"
                    for msg in messages
                    if isinstance(msg, dict) and "role" in msg and "content" in msg
                )
                # 5-классовая классификация через LLM
                llm_classify_model = await daily_classification(conversation=conversation)

                predict = LiteLLM_PredictTable(
                    last_trace_id=trace_id,
                    session_id=session_id,
                    user_id=user_id,
                    predict={"predict": llm_classify_model.model_dump()},
                )
                await predict_repository.add(predict)

        except Exception:
            logger.exception("Failed to process session %s", session_id)

    langfuse.flush()
