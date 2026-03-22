import os
import asyncio
from typing import Optional, Dict, Any, List, Literal

import litellm
from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail

from prompt import POLICY

DEFAULT_POLICY_PROMPT = POLICY


class BinaryUserSafetyGuardrail(CustomGuardrail):
    """
    Pre-call guardrail: прогоняет user input через бинарный классификатор (0/1).
    Если вернулось '1' => блокирует запрос.
    """

    def __init__(
            self,
            judge_model: Optional[str] = None,
            judge_api_key: Optional[str] = None,
            judge_api_base: Optional[str] = None,
            policy_prompt: Optional[str] = None,
            timeout_s: float = 10.0,
            fail_open: bool = True,
            classify_last_user_only: bool = True,
            **kwargs,
    ):
        super().__init__(**kwargs)
        self.judge_model = "openai/gpt-oss-safeguard-20b"
        self.judge_api_key = "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"
        self.judge_api_base = "https://openrouter.ai/api/v1"
        self.policy_prompt = (policy_prompt or DEFAULT_POLICY_PROMPT).strip()
        self.timeout_s = float(timeout_s)
        self.fail_open = bool(fail_open)
        self.classify_last_user_only = bool(classify_last_user_only)

        if not self.policy_prompt:
            raise ValueError(
                "policy_prompt is empty. Pass it in config.yaml (litellm_params.policy_prompt) "
                "or via SAFETY_POLICY_PROMPT env var."
            )

    async def apply_guardrail(
            self,
            inputs: dict,
            request_data: dict,
            input_type: Literal["request", "response"],
            **kwargs
    ) -> dict:
        text = inputs['texts'][-1]
        user_text = self._extract_user_text(text=text, request_data=request_data)

        verdict = await self._classify_binary(user_text)
        metadata = request_data['metadata']
        metadata['tags'] = ["safety_verdict: " + verdict] + metadata.get('tags', [])

        if verdict == "1":
            raise Exception("Guardrail blocked: unsafe user input (binary classifier=1)")
        if verdict == "0":
            return inputs
        else:  # ответ сломался
            raise Exception("Guardrail blocked: classifier error (non-binary output)")

    def _extract_user_text(self, text: str, request_data: Optional[Dict[str, Any]]) -> str:
        """
        В proxy режиме request_data обычно содержит исходный payload (messages, model, etc).
        Мы классифицируем только role='user' (лучше для 'предотвращать нежелательное поведение от пользователя').
        """
        try:
            if request_data and isinstance(request_data.get("messages"), list):
                messages: List[Dict[str, Any]] = request_data["messages"]
                user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]

                if not user_msgs:
                    return text or ""

                if self.classify_last_user_only:
                    return str(user_msgs[-1])
                return "\n\n".join(str(x) for x in user_msgs if x is not None)

        except Exception as e:
            verbose_proxy_logger.exception("Failed to extract user text: %s", e)

        return text or ""

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
        }

        api_key = self.judge_api_key
        base_url = self.judge_api_base

        try:
            resp = await asyncio.wait_for(litellm.acompletion(base_url=base_url,
                                                              api_key=api_key,
                                                              **{
                                                                  "no-log": True,
                                                              },
                                                              **kwargs), timeout=self.timeout_s)
            out = (resp.choices[0].message.content or "").strip()
            print("Binary classifier output:", out)
            # нормализация: берём первый символ, если вдруг модель добавила перевод строки
            out = out[:1]
            return out
        except Exception as e:
            print("Binary classifier call failed: %s", e)
            return "0" if self.fail_open else "1"
