"""Insert generated dialogues into SpendLogs + PredictTable."""

import sys
import uuid
import logging
from datetime import datetime, timedelta, timezone, date

from .personas.base import DayScript, PersonaConfig, SessionPlan
from .generator import GeneratedExchange

logger = logging.getLogger(__name__)

# Ensure src is importable
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent / "src"))


def build_spendlogs_rows(
    persona: PersonaConfig,
    day_script: DayScript,
    session: SessionPlan,
    exchanges: list[GeneratedExchange],
    start_date: date,
) -> list[dict]:
    """Convert exchanges into SpendLogs-compatible row dicts.

    Each exchange becomes one row. The messages field is CUMULATIVE
    (full conversation history up to that point).
    """
    rows = []
    cumulative_messages = []

    day_date = start_date + timedelta(days=day_script.day - 1)
    # Naive datetime: SpendLogs.startTime is TIMESTAMP WITHOUT TIME ZONE
    base_time = datetime(
        day_date.year, day_date.month, day_date.day,
        session.hour, 0, 0,
    )

    for i, exchange in enumerate(exchanges):
        timestamp = base_time + timedelta(minutes=i * session.inter_msg_gap_min)

        cumulative_messages.append({"role": "user", "content": exchange.user_message})
        cumulative_messages.append({"role": "assistant", "content": exchange.assistant_message})

        rows.append({
            "request_id": f"synth_{uuid.uuid4()}",
            "call_type": "acompletion",
            "api_key": "synthetic",
            "spend": 0.0,
            "total_tokens": len(exchange.user_message.split()) + len(exchange.assistant_message.split()),
            "prompt_tokens": len(exchange.user_message.split()),
            "completion_tokens": len(exchange.assistant_message.split()),
            "startTime": timestamp,
            "endTime": timestamp + timedelta(seconds=5),
            "model": "synthetic",
            "user": "",
            "end_user": persona.persona_id,
            "messages": list(cumulative_messages),  # copy!
            "response": {
                "choices": [{"message": {"content": exchange.assistant_message}}],
            },
            "metadata_json": {
                "source": "synthetic",
                "persona": persona.name,
                "day": day_script.day,
                "phase": day_script.phase,
                "session_hour": session.hour,
                "turn": exchange.turn,
            },
            "session_id": f"synth_{persona.persona_id}_d{day_script.day}_h{session.hour}",
        })

    return rows


def build_predict_row(
    persona: PersonaConfig,
    day_script: DayScript,
    session_id: str,
) -> dict | None:
    """Build a deterministic PredictTable row (Option B) if predict_overrides are set."""
    if not day_script.predict_overrides:
        return None

    return {
        "user_id": persona.persona_id,
        "session_id": session_id,
        "last_trace_id": f"synth_{uuid.uuid4()}",
        "predict": {"predict": day_script.predict_overrides},
    }


async def insert_spendlogs_rows(rows: list[dict]) -> int:
    """Insert SpendLogs rows into the database."""
    from database import Session
    from database.models import LiteLLM_SpendLogs

    inserted = 0
    async with Session() as session:
        async with session.begin():
            for row_data in rows:
                row = LiteLLM_SpendLogs(**row_data)
                session.add(row)
                inserted += 1
    return inserted


async def insert_predict_row(predict_data: dict) -> None:
    """Insert a PredictTable row."""
    from database import Session
    from database.models import LiteLLM_PredictTable

    async with Session() as session:
        async with session.begin():
            row = LiteLLM_PredictTable(**predict_data)
            session.add(row)
