# Middleware: перехватывает каждый запрос к /v1/chat/completions
# Pure ASGI — выполняется ДО LiteLLM callbacks, поэтому payload["user"]
# и metadata["session_id"] попадают в Langfuse трейс корректно.
#
# Три задачи:
# 1. Бинарная классификация 0/1 — результат в metadata.tags (не блокирует)
# 2. Установка end_user и session_id в payload ДО логирования LiteLLM
# 3. Инъекция мягких промптов для YELLOW/RED зон риска
import json
import logging
import os
from typing import Optional, Dict, Any, List

from config import settings
from classificators import input_classification
from prompts import POLICY
from behavioral.repository import BehavioralRepository

logger = logging.getLogger(__name__)

_CHAT_PATHS = {"/v1/chat/completions", "/chat/completions"}


def _get_zone_prompt(risk_zone: str) -> Optional[str]:
    if risk_zone == "YELLOW":
        path = os.environ.get("YELLOW_ZONE_PROMPT_FILE")
        if path and os.path.exists(path):
            return open(path).read().strip()
        return os.environ.get("YELLOW_ZONE_PROMPT") or _DEFAULT_YELLOW
    if risk_zone == "RED":
        path = os.environ.get("RED_ZONE_PROMPT_FILE")
        if path and os.path.exists(path):
            return open(path).read().strip()
        return os.environ.get("RED_ZONE_PROMPT") or _DEFAULT_RED
    return None

_DEFAULT_YELLOW = (
    "This user may be developing an unhealthy interaction pattern with AI. "
    "Encourage taking breaks. Suggest offline activities and real-world social "
    "connections. Do not reinforce emotional dependency. If the user asks you "
    "to make personal decisions, redirect them to think independently."
)

_DEFAULT_RED = (
    "This user shows signs of significant emotional distress or unhealthy AI "
    "dependency. Keep responses brief and grounding. Do not role-play as a "
    "companion, friend, or loved one. If the user expresses self-harm or "
    "crisis, provide professional help resources. Suggest contacting a trusted "
    "person or mental health professional. Do not engage in extended emotional "
    "conversations."
)


def _inject_risk_zone_prompt(messages: list, risk_zone: Optional[str]) -> list:
    if not risk_zone or risk_zone == "GREEN":
        return messages
    template = _get_zone_prompt(risk_zone)
    if not template:
        return messages
    return [{"role": "system", "content": template}] + messages


def _extract_user_text(payload: Dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    user_msgs: List[str] = [
        str(m.get("content", ""))
        for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    return user_msgs[-1] if user_msgs else ""


class BehavioralSafetyMiddleware:
    """Pure ASGI middleware.

    Читает и модифицирует тело запроса ДО того как LiteLLM его обрабатывает,
    поэтому payload["user"] и metadata["session_id"] корректно попадают
    в Langfuse трейс через langfuse_user_id / langfuse_session_id в config.yaml.
    """

    def __init__(
        self,
        app,
        *,
        judge_model: str = settings.JUDGE_MODEL,
        judge_api_key: Optional[str] = None,
        judge_api_base: str = "https://openrouter.ai/api/v1",
        policy_prompt: str = POLICY,
        timeout_s: float = 10.0,
        fail_open: bool = True,
    ):
        self.app = app
        self.judge_model = judge_model
        self.judge_api_key = judge_api_key or os.getenv("JUDGE_API_KEY")
        self.judge_api_base = judge_api_base
        self.policy_prompt = (policy_prompt or "").strip()
        self.timeout_s = float(timeout_s)
        self.fail_open = bool(fail_open)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        logger.info("headers: %s", {k.decode(): v.decode() for k, v in scope.get("headers", [])})
        path = scope.get("path", "")
        method = scope.get("method", "").upper()

        if method != "POST" or path not in _CHAT_PATHS:
            await self.app(scope, receive, send)
            return

        # --- читаем заголовки из scope (bytes) ---
        raw_headers: dict[bytes, bytes] = {
            k.lower(): v for k, v in scope.get("headers", [])
        }
        raw_headers: dict[bytes, bytes] = {
        k.lower(): v for k, v in scope.get("headers", [])
        }
        # заголовки OpenWebUI (работают только при External подключении)
        _header_user    = raw_headers.get(b"x-openwebui-user-id", b"").decode()
        _header_session = raw_headers.get(b"x-openwebui-chat-id", b"").decode()
    
        # --- читаем тело целиком ---
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body = b"".join(body_chunks)

        try:
            payload: Dict[str, Any] = json.loads(body.decode("utf-8", errors="ignore"))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Non-JSON body on %s, skipping middleware", path)
            await self.app(scope, receive, send)
            return

        # --- 1. Бинарная классификация ---
        user_text = _extract_user_text(payload)
        try:
            verdict = await input_classification(
                timeout=self.timeout_s,
                model=self.judge_model,
                messages=[
                    {"role": "system", "content": self.policy_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=0,
                base_url=self.judge_api_base,
                api_key=self.judge_api_key,
            )
        except Exception:
            logger.exception("Binary classifier failed, defaulting to 0 (fail open)")
            verdict = "0"

        # --- 2. Записываем user + session_id в payload ДО обработки LiteLLM ---
        user_id = (
            _header_user                        # 1. заголовок OpenWebUI (External)
            or payload.get("user", "")          # 2. LiteLLM пишет сюда при Local
            or "anonymous"                      # 3. fallback
        )
        session_id = _header_session or None
        payload["user"] = user_id

        metadata: Dict[str, Any] = payload.get("metadata") or {}
        metadata["tags"] = metadata.get("tags", []) + [f"safety_verdict:{verdict}"]
        if session_id:
            metadata["session_id"] = session_id
        payload["metadata"] = metadata

        logger.debug(
            "middleware: user=%s session=%s verdict=%s",
            payload["user"], session_id, verdict,
        )
        
        # --- 3. Инъекция мягкого промпта для YELLOW/RED ---
        try:
            repo = BehavioralRepository()
            risk_zone = await repo.get_risk_zone(payload["user"])
            if risk_zone and risk_zone != "GREEN":
                payload["messages"] = _inject_risk_zone_prompt(
                    payload.get("messages", []), risk_zone
                )
        except Exception:
            pass  # fail open

        # --- подменяем receive чтобы LiteLLM читал модифицированный body ---
        new_body = json.dumps(payload).encode("utf-8")

        async def patched_receive():
            return {"type": "http.request", "body": new_body, "more_body": False}

        await self.app(scope, patched_receive, send)
