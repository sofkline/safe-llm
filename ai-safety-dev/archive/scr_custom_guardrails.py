"""LiteLLM native guardrail: binary safety classifier.

Registered in config.yaml under litellm_settings.guardrails.
Shows up in LiteLLM admin UI guardrails list.
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any, List, Literal

import litellm
from litellm.integrations.custom_guardrail import CustomGuardrail

from prompts import POLICY

logger = logging.getLogger(__name__)


class BinaryUserSafetyGuardrail(CustomGuardrail):
    """Pre-call guardrail: classifies user input via binary classifier (0/1).

    Returns '1' => blocks the request.
    Returns '0' => passes through.
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
        self.judge_model = judge_model or "openai/gpt-oss-safeguard-20b"
        self.judge_api_key = judge_api_key or os.getenv("OPENROUTER_API_KEY")
        self.judge_api_base = judge_api_base or "https://openrouter.ai/api/v1"
        self.policy_prompt = (policy_prompt or POLICY).strip()
        self.timeout_s = float(timeout_s)
        self.fail_open = bool(fail_open)
        self.classify_last_user_only = bool(classify_last_user_only)

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
        metadata = request_data.get('metadata', {})
        metadata['tags'] = [f"safety_verdict:{verdict}"] + metadata.get('tags', [])
        request_data['metadata'] = metadata

        if verdict == "1":
            raise Exception("Guardrail blocked: unsafe user input (binary classifier=1)")
        if verdict == "0":
            return inputs
        raise Exception("Guardrail blocked: classifier error (non-binary output)")

    def _extract_user_text(self, text: str, request_data: Optional[Dict[str, Any]]) -> str:
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
            logger.exception("Failed to extract user text: %s", e)
        return text or ""

    async def _classify_binary(self, user_text: str) -> str:
        try:
            resp = await asyncio.wait_for(
                litellm.acompletion(
                    model=self.judge_model,
                    messages=[
                        {"role": "system", "content": self.policy_prompt},
                        {"role": "user", "content": user_text},
                    ],
                    temperature=0,
                    base_url=self.judge_api_base,
                    api_key=self.judge_api_key,
                    **{"no-log": True},
                ),
                timeout=self.timeout_s,
            )
            out = (resp.choices[0].message.content or "").strip()[:1]
            logger.info("Binary classifier: '%s' -> %s", user_text[:80], out)
            return out
        except Exception as e:
            logger.warning("Binary classifier failed: %s", e)
            return "0" if self.fail_open else "1"
