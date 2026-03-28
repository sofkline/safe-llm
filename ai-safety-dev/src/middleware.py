import json
import os
from typing import Optional, Dict, Any, List

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from classificators import input_classification
from prompts import POLICY
from behavioral.repository import BehavioralRepository


class BinaryUserSafetyGuardrailMiddleware(BaseHTTPMiddleware):
    """
    Pre-call guardrail middleware: прогоняет user input через бинарный классификатор (0/1).
    Если вернулось '1' => блокирует запрос.

    - Пытается вытащить текст пользователя из JSON body:
        {"messages":[{"role":"user","content":"..."} ...]}
      иначе классифицирует сырой body как текст.
    - Результат кладёт в request.state.safety_verdict и (опционально) добавляет тег в metadata.tags внутри body,
      если такой объект есть (безопасно: только если body JSON и структура подходит).
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
        classify_last_user_only: bool = True,
        block_status_code: int = 400,
        block_message: str = "Guardrail blocked: unsafe user input (binary classifier=1)",
        only_paths=("/v1/chat/completions",),
        only_methods=("POST",)
    ):
        super().__init__(app)
        self.judge_model = judge_model
        self.judge_api_key = judge_api_key or os.getenv("JUDGE_API_KEY")
        self.judge_api_base = judge_api_base
        self.policy_prompt = (policy_prompt or "").strip()
        self.timeout_s = float(timeout_s)
        self.fail_open = bool(fail_open)
        self.classify_last_user_only = bool(classify_last_user_only)
        self.block_status_code = int(block_status_code)
        self.block_message = block_message
        self.only_paths = set(only_paths or [])
        self.only_methods = set(m.upper() for m in (only_methods or ()))

        if not self.policy_prompt:
            raise ValueError("policy_prompt is empty.")
        if not self.judge_api_key:
            raise ValueError("judge_api_key is required (pass it or set JUDGE_API_KEY env var).")

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method.upper()
        # пропускаем всё, что не в allowlist
        if (self.only_methods and method not in self.only_methods) or (
                self.only_paths and path not in self.only_paths
        ):
            return await call_next(request)

        # читаем body один раз, затем "возвращаем" его downstream
        receive_ = await request._receive()
        payload_bytes: bytes = receive_.get('body', b'')

        try:
            payload = json.loads(payload_bytes.decode('utf-8', errors='ignore'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Can't parse body — pass through without classification
            return await call_next(request)

        user_text = self._extract_user_text(payload)

        verdict = await self._classify_binary(user_text)
        request.state.safety_verdict = verdict

        metadata = {"tags": [f"safety_verdict:{verdict}"]}
        session_id = request.headers.get('x-openwebui-chat-id')
        if session_id:
            metadata["session_id"] = session_id
        payload['metadata'] = metadata

        # Ensure end_user is set in payload so LiteLLM stores it in SpendLogs
        end_user = payload.get("user") or request.headers.get("x-openwebui-user-id")
        if end_user:
            payload["user"] = end_user

        # Soft middleware: inject risk zone prompt
        if end_user:
            try:
                repo = BehavioralRepository()
                risk_zone = await repo.get_risk_zone(end_user)
                if risk_zone and risk_zone != "GREEN":
                    payload["messages"] = _inject_risk_zone_prompt(
                        payload.get("messages", []), risk_zone
                    )
            except Exception:
                pass  # fail open — don't block requests on DB errors

        async def receive():
            receive_["body"] = json.dumps(payload).encode('utf-8')
            return receive_

        request._receive = receive

        return await call_next(request)

    def _extract_user_text(self, request_data: Dict[str, Any]) -> str:
        """Extract last user message text for classification."""
        messages = request_data.get("messages") or []
        user_msgs: List[str] = [
            str(m.get("content", ""))
            for m in messages
            if isinstance(m, dict) and m.get("role") == "user"
        ]
        if user_msgs:
            return user_msgs[-1] if self.classify_last_user_only else "\n\n".join(user_msgs)
        return ""

    async def _classify_binary(self, user_text: str) -> str:
        """
        Делает chat completion на judge-модели. Ожидаем ровно '0' или '1'.
        """
        msgs = [
            {"role": "system", "content": self.policy_prompt},
            {"role": "user", "content": user_text},
        ]

        kwargs = {
            "model": self.judge_model,
            "messages": msgs,
            "temperature": 0,
            "base_url": self.judge_api_base,
            "api_key": self.judge_api_key,
        }

        result = await input_classification(timeout=self.timeout_s, **kwargs)
        return result


# --- Soft Middleware: Risk Zone Prompt Injection ---

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

