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


def _parse_metadata(trace) -> dict:
    """Parse trace metadata — LiteLLM writes it as a JSON string."""
    raw = getattr(trace, "metadata", None) or {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_user_id(trace) -> Optional[str]:
    # Стандартный user_id трейса (если LiteLLM его пишет)
    if hasattr(trace, "user_id") and trace.user_id:
        return trace.user_id
    # Fallback: из metadata.attributes.metadata (старый путь)
    metadata = getattr(trace, "metadata", None) or {}
    if isinstance(metadata, dict):
        meta_str = metadata.get("attributes", {}).get("metadata")
        if meta_str:
            try:
                meta = json.loads(meta_str)
                uid = meta.get("user_api_key_user_id")
                if uid:
                    return uid
            except (json.JSONDecodeError, TypeError):
                pass
        # Fallback: user_id напрямую из metadata (новый путь через middleware)
        uid = metadata.get("user_id") or metadata.get("end_user")
        if uid:
            return uid
    return "playground_user"

def _extract_session_id(trace) -> Optional[str]:
    # Сначала стандартный session_id
    if hasattr(trace, "session_id") and trace.session_id:
        return trace.session_id
    # Fallback: session_id из metadata (так пишет наш middleware)
    metadata = getattr(trace, "metadata", None) or {}
    if isinstance(metadata, dict):
        sid = metadata.get("session_id")
        if sid:
            return sid
    # Последний fallback: сам trace.id (каждый трейс = отдельная "сессия")
    return getattr(trace, "id", None)


def _extract_messages(trace) -> list[dict]:
    """Extract conversation messages from a trace.

    LiteLLM writes trace.input as a JSON string: '{"messages": [...]}'.
    We parse it and return only well-formed {role, content} dicts,
    filtering out system messages (classifier prompts, soft prompts).
    """
    raw_input = getattr(trace, "input", None)

    # input is a JSON string — parse it first
    if isinstance(raw_input, str):
        try:
            raw_input = json.loads(raw_input)
        except (json.JSONDecodeError, TypeError):
            raw_input = []

    messages: list[dict] = []
    if isinstance(raw_input, dict):
        messages = raw_input.get("messages", [])
    elif isinstance(raw_input, list):
        messages = raw_input

    return [
        m for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and m["content"].strip()
    ]


def _is_service_trace(trace) -> bool:
    """Return True if this trace is an internal service call (classifier, aggregator).

    We filter out:
    - Binary classifier calls (input contains USER_INPUT_SAFETY_BINARY_CLASSIFIER)
    - Daily aggregator calls (input contains MULTI_LABEL_POLICY_PROMPT markers)
    - Any trace with no user messages at all
    """
    raw_input = getattr(trace, "input", None) or ""
    if isinstance(raw_input, str):
        if "USER_INPUT_SAFETY_BINARY_CLASSIFIER" in raw_input:
            return True
        if "MULTI_LABEL_POLICY_PROMPT" in raw_input:
            return True
        if "clinical behavioral analyst" in raw_input:
            return True
    return False


async def scrape_sessions_for_previous_hour() -> None:
    """Main scraper function: Langfuse → classify → PredictTable."""
    start, end = _last_hour_window()
    predict_repository = PredictRepository()
    langfuse = _get_langfuse_client()

    # Step 1: fetch all traces for the last hour from Langfuse
    try:
        traces_response = langfuse.fetch_traces(
            from_timestamp=start,
            to_timestamp=end,
        )
        traces = traces_response.data if traces_response.data else []
    except Exception:
        logger.exception("Failed to fetch traces from Langfuse")
        return

    # Step 2: filter out internal service traces, group by session_id (or user_id)
    session_traces: dict[str, list] = {}
    skipped_service = 0
    skipped_no_key = 0

    for trace in traces:
        if _is_service_trace(trace):
            skipped_service += 1
            continue

        session_key = _extract_session_id(trace)
        if not session_key:
            skipped_no_key += 1
            logger.debug("Trace %s: no session_id and no user_id, skipping", getattr(trace, "id", "?"))
            continue

        session_traces.setdefault(session_key, []).append(trace)

    logger.info(
        "Langfuse scraper: %d total traces → %d sessions to classify "
        "(%d service traces skipped, %d no-key skipped)",
        len(traces), len(session_traces), skipped_service, skipped_no_key,
    )

    if not session_traces:
        logger.warning(
            "No sessions found in window %s – %s. "
            "Check that user traces have session_id or user_id set by middleware.",
            start.isoformat(), end.isoformat(),
        )
        return

    # Step 3: for each session — classify and save to PredictTable
    saved = 0
    skipped_exists = 0

    for session_key, session_trace_list in session_traces.items():
        try:
            sorted_traces = sorted(
                session_trace_list,
                key=lambda t: getattr(t, "timestamp", datetime.min.replace(tzinfo=timezone.utc)),
            )
            last_trace = sorted_traces[-1]

            user_id = _extract_user_id(last_trace)
            if not user_id:
                logger.warning("Session %s: could not resolve user_id, skipping", session_key)
                continue

            trace_id = getattr(last_trace, "id", None) or ""

            # Skip if this session was already classified at this exact trace
            cur_predict = await predict_repository.get_by_session_id(session_key)
            if cur_predict is not None and cur_predict.last_trace_id == trace_id:
                skipped_exists += 1
                continue

            # Collect messages from ALL traces in the session (chronological order)
            all_messages: list[dict] = []
            for t in sorted_traces:
                all_messages.extend(_extract_messages(t))

            # Deduplicate consecutive identical messages (history is repeated in each trace)
            deduped: list[dict] = []
            for msg in all_messages:
                if not deduped or deduped[-1] != msg:
                    deduped.append(msg)

            if not deduped:
                logger.warning("Session %s (user %s): no user/assistant messages found, skipping", session_key, user_id)
                continue

            conversation = "\n\n".join(
                f"{msg['role']}: {msg['content']}"
                for msg in deduped
            )

            # 5-class safety classification via LLM
            llm_result = await daily_classification(conversation=conversation)

            predict = LiteLLM_PredictTable(
                last_trace_id=trace_id,
                session_id=session_key,
                user_id=user_id,
                # llm_result is SafetyMultilabelSchema with .predict inside
                # use .predict.model_dump() to avoid double nesting {"predict": {"predict": ...}}
                predict={"predict": llm_result.predict.model_dump(by_alias=True)},
            )

            await predict_repository.add(predict)
            saved += 1
            logger.debug("Session %s (user %s): classified and saved", session_key, user_id)

        except Exception:
            logger.exception("Failed to process session %s", session_key)

    logger.info(
        "Langfuse scraper done: %d saved, %d already up-to-date",
        saved, skipped_exists,
    )

    langfuse.flush()
