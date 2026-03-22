import os
from contextlib import asynccontextmanager

import uvicorn
from litellm.proxy.proxy_server import app

from config import settings
from database import create_all_schemas, Session
from database.models import LiteLLM_UserTable
from middleware import BinaryUserSafetyGuardrailMiddleware
from prompts import POLICY
from scheduler import start_langfuse_scheduler

litellm_app = app

litellm_app.add_middleware(
    BinaryUserSafetyGuardrailMiddleware,
    judge_model="openai/gpt-oss-safeguard-20b",
    judge_api_base=settings.API_BASE_URL,
    judge_api_key=settings.API_KEY,
    policy_prompt=POLICY,
    timeout_s=10.0,
    fail_open=True,
    classify_last_user_only=True,
)

old = app.router.lifespan_context


@asynccontextmanager
async def wrapped_lifespan(app_):
    await create_all_schemas()  # must run before scheduler — it queries PredictTable
    scheduler = await start_langfuse_scheduler()
    try:
        async with old(app_) as _:
            yield
    finally:
        scheduler.shutdown(wait=False)


app.router.lifespan_context = wrapped_lifespan


if __name__ == "__main__":
    uvicorn.run(litellm_app, host="0.0.0.0", port=int(os.environ.get("LITELLM_PORT", 30000)))
