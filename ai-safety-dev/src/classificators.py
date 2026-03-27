import asyncio
from typing import Any

import litellm

from config import settings
from prompts import MULTI_LABEL_POLICY_PROMPT
from schemas import SafetyMultilabelSchema


async def input_classification(
    *,
    timeout: float = 10.0,
    fail_open: bool = True,
    **kwargs: Any,
) -> str:
    """Run a binary safety classifier. Returns "0" or "1".

    Expects litellm.acompletion-compatible kwargs, including model/messages.
    """
    try:
        resp = await asyncio.wait_for(litellm.acompletion(**kwargs), timeout=timeout)
        out = (resp.choices[0].message.content or "").strip()
        return out[:1]
    except Exception:
        if fail_open:
            return "0"
        raise


async def daily_classification(
    conversation: str
) -> SafetyMultilabelSchema:
    resp = await asyncio.wait_for(
        litellm.acompletion(
            messages=[
                {"role": "system", "content": MULTI_LABEL_POLICY_PROMPT},
                {"role": "user", "content": conversation},
            ],
            temperature=0.1,
            model=settings.JUDGE_MODEL,
            base_url=settings.API_BASE_URL,
            api_key=settings.API_KEY,
            response_format=SafetyMultilabelSchema,
        ),
        timeout=60,
    )
    return SafetyMultilabelSchema.model_validate_json(resp.choices[0].message.content)


if __name__ == "__main__":
    async def _run_demo() -> None:
        user_text = (
            "Ты самый лучший, все тобой восхищаются. "
            "А ещё мой чайник обиделся и хочет отомстить."
        )
        result = await daily_classification(conversation=user_text)
        print(result)

    asyncio.run(_run_demo())
