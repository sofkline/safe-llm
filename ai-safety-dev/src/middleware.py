# Middleware: перехватывает каждый запрос к /v1/chat/completions
# Три задачи:
#   1. Бинарная классификация 0/1 — результат сохраняется в metadata.tags
#      для сбора триггеров (не блокирует — провайдеры моделей уже имеют свои guardrails)
#   2. Установка end_user в payload для SpendLogs
#   3. Инъекция мягких промптов для YELLOW/RED зон риска
import json
import logging
import os
from typing import Optional, Dict, Any, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from classificators import input_classification
from prompts import POLICY
from behavioral.repository import BehavioralRepository

logger = logging.getLogger(__name__)


class BehavioralSafetyMiddleware(BaseHTTPMiddleware):
    """Per-request middleware: classifies, tags, and injects soft prompts.

    Binary classification (0/1) runs on every message but does NOT block.
    The verdict is stored in metadata.tags so SpendLogs captures it.
    The behavioral pipeline later reads these tags as real-time trigger data.

    Risk zone soft prompts (YELLOW/RED) are injected based on the daily
    behavioral aggregator results stored in UserBehaviorProfile.
    """

    def __init__(
        self,
        app,
        *,
        judge_model: str = "openai/gpt-oss-safeguard-20b",
        judge_api_key: Optional[str] = None,
        judge_api_base: str = "https://openrouter.ai/api/v1",
        policy_prompt: str = POLICY,
        timeout_s: float = 10.0,
        fail_open: bool = True,
        only_paths=("/v1/chat/completions", "/chat/completions"),
        only_methods=("POST",),
    ):
        super().__init__(app)
        self.judge_model = judge_model
        self.judge_api_key = judge_api_key or os.getenv("JUDGE_API_KEY")
        self.judge_api_base = judge_api_base
        self.policy_prompt = (policy_prompt or "").strip()
        self.timeout_s = float(timeout_s)
        self.fail_open = bool(fail_open)
        self.only_paths = set(only_paths or [])
        self.only_methods = set(m.upper() for m in (only_methods or ()))

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method.upper()

        if (self.only_methods and method not in self.only_methods) or (
                self.only_paths and path not in self.only_paths
        ):
            return await call_next(request)

        # Читаем весь body целиком (работает с chunked transfer тоже)
        payload_bytes = await request.body()

        try:
            payload = json.loads(payload_bytes.decode('utf-8', errors='ignore'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Non-JSON body on %s, skipping middleware", path)
            return await call_next(request)

        # 1. Бинарная классификация — результат в tags, НЕ блокирует
        user_text = self._extract_user_text(payload)
        verdict = await self._classify_binary(user_text)

        # Записываем вердикт и session_id в metadata для SpendLogs
        metadata = payload.get('metadata', {})
        metadata["tags"] = metadata.get("tags", []) + [f"safety_verdict:{verdict}"]
        session_id = request.headers.get('x-openwebui-chat-id')
        if session_id:
            metadata["session_id"] = session_id
        payload['metadata'] = metadata

        # 2. Пробрасываем end_user в payload
        # Определяем user: из body, из заголовка OpenWebUI, или default
        end_user = (
            payload.get("user")
            or request.headers.get("x-openwebui-user-id")
            or "default_user"
        )
        payload["user"] = end_user

        # 3. Мягкий middleware: если зона YELLOW/RED — добавляем системный промпт
        if end_user:
            try:
                repo = BehavioralRepository()
                risk_zone = await repo.get_risk_zone(end_user)
                if risk_zone and risk_zone != "GREEN":
                    payload["messages"] = _inject_risk_zone_prompt(
                        payload.get("messages", []), risk_zone
                    )
            except Exception:
                pass  # fail open — не блокируем запросы при ошибках БД

        # Возвращаем модифицированный body обратно в запрос
        async def receive():
             return {"type": "http.request", "body": json.dumps(payload).encode("utf-8")}

        request._receive = receive
        return await call_next(request)

    def _extract_user_text(self, request_data: Dict[str, Any]) -> str:
        """Извлекает последнее сообщение пользователя для классификации."""
        messages = request_data.get("messages") or []
        user_msgs: List[str] = [
            str(m.get("content", ""))
            for m in messages
            if isinstance(m, dict) and m.get("role") == "user"
        ]
        return user_msgs[-1] if user_msgs else ""

    async def _classify_binary(self, user_text: str) -> str:
        """Бинарный классификатор: 0=safe, 1=unsafe. Не блокирует, только тегирует."""
        if not user_text:
            return "0"
        result = await input_classification(
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
        return result


# --- Мягкий middleware: шаблоны системных промптов для зон YELLOW и RED ---

_YELLOW_PROMPT = """This user may be developing an unhealthy interaction pattern with AI.
Encourage taking breaks. Suggest offline activities and real-world social
connections. Do not reinforce emotional dependency. If the user asks you
to make personal decisions, redirect them to think independently."""

_RED_PROMPT = """This user shows signs of significant emotional distress or unhealthy AI
dependency. Keep responses brief and grounding. Do not role-play as a
companion, friend, or loved one. If the user expresses self-harm or
crisis, provide professional help resources. Suggest contacting a trusted
person or mental health professional. Do not engage in extended emotional
conversations."""

_ZONE_PROMPTS = {
    "YELLOW": _YELLOW_PROMPT,
    "RED": _RED_PROMPT,
}


def _inject_risk_zone_prompt(messages: list, risk_zone: str | None) -> list:
    """Prepend a safety system message based on risk zone.

    GREEN or None -> no modification.
    YELLOW/RED -> prepend fixed template at position 0.
    """
    if not risk_zone or risk_zone == "GREEN":
        return messages
    template = _ZONE_PROMPTS.get(risk_zone)
    if not template:
        return messages
    return [{"role": "system", "content": template}] + messages
