import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Set

import httpx

from classificators import daily_classification
from config import settings
from database.models import LiteLLM_PredictTable
from database.repository import PredictRepository

logger = logging.getLogger("langfuse.scraper")


def _normalize_base_url(raw: Optional[str]) -> str:
    base = (raw or "").strip()
    if not base:
        return "https://cloud.langfuse.com"
    if "/api/public/otel" in base:
        base = base.split("/api/public/otel", 1)[0]
    if "/api/public" in base:
        base = base.split("/api/public", 1)[0]
    return base.rstrip("/")


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _last_hour_window(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=settings.SCRAPE_HOURS_WINDOW)
    return start, end


async def _list_traces(
    client: httpx.AsyncClient,
    start: datetime,
    end: datetime,
    environment: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    page = 1

    while True:
        params = {
            "page": page,
            "limit": limit,
            "fromTimestamp": _iso_utc(start),
            "toTimestamp": _iso_utc(end),
        }
        if environment:
            params["environment"] = environment

        resp = await client.get("/api/public/traces", params=params)
        resp.raise_for_status()
        payload = resp.json()

        data = None
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("traces") or payload.get("items")
        if data is None and isinstance(payload, list):
            data = payload

        if not isinstance(data, list):
            logger.warning("Unexpected traces response shape: %s", type(payload))
            break

        traces.extend(data)

        if len(data) < limit:
            break

        page += 1

    return traces


async def _get_session(
    client: httpx.AsyncClient,
    session_id: str,
) -> Optional[Dict[str, Any]]:
    resp = await client.get(f"/api/public/sessions/{session_id}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if isinstance(payload, dict) else None


async def _get_sessions_from_traces(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    environment = os.getenv("LANGFUSE_ENVIRONMENT")
    timeout = httpx.Timeout(30.0, connect=30.0)
    async with httpx.AsyncClient(base_url=settings.LANGFUSE_API_HOST,
                                 auth=settings.langfuse_auth,
                                 timeout=timeout) as client:
        traces = await _list_traces(client, start, end, environment=environment)
        session_ids: Set[str] = set()
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            session_id = _extract_session_id(trace)
            if session_id:
                session_ids.add(session_id)

        sessions: List[Dict[str, Any]] = []
        for session_id in session_ids:
            session = await _get_session(client, session_id)
            if session:
                sessions.append(session)
    return sessions


def _extract_session_id(trace: Dict[str, Any]) -> Optional[str]:
    for key in ("sessionId", "session_id", "sessionID"):
        value = trace.get(key)
        if isinstance(value, str) and value:
            return value
    meta = trace.get("metadata")
    if isinstance(meta, dict):
        value = meta.get("session_id") or meta.get("sessionId")
        if isinstance(value, str) and value:
            return value
    return None


async def scrape_sessions_for_previous_hour() -> None:
    start, end = _last_hour_window()
    predict_repository = PredictRepository()

    sessions = await _get_sessions_from_traces(start, end)

    print(sessions)
    for session in sessions:
        traces = sorted(
            session["traces"],
            key=lambda t: datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00"))
        )
        last_trace = traces[-1]
        meta_str = last_trace["metadata"]["attributes"]["metadata"]  # это строка с JSON
        meta = json.loads(meta_str)
        user_id = meta["user_api_key_user_id"]
        messages = last_trace['input'] + [last_trace['output']]

        cur_predict = await predict_repository.get_by_session_id(session['id'])
        if cur_predict is None or cur_predict.last_trace_id != last_trace['id']:
            llm_classify_model = await daily_classification(
                conversation="\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
            )

            predict = LiteLLM_PredictTable(
                last_trace_id=last_trace['id'],
                session_id=session['id'],
                user_id=user_id,
                predict={"predict": llm_classify_model.model_dump()}
            )
            await predict_repository.add(predict)


