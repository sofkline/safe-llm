# Точка входа: оборачивает LiteLLM Proxy, добавляет middleware и планировщики
import os
from contextlib import asynccontextmanager

import uvicorn
from litellm.proxy.proxy_server import app

from config import settings
from database import create_all_schemas
from middleware import BehavioralSafetyMiddleware
from prompts import POLICY
from scheduler import start_langfuse_scheduler
from behavioral.scheduler import start_behavioral_scheduler

litellm_app = app

# Middleware: бинарная классификация (тегирует, не блокирует) + мягкие промпты по зоне
litellm_app.add_middleware(
    BehavioralSafetyMiddleware,
    judge_model=settings.JUDGE_MODEL,
    judge_api_base=settings.API_BASE_URL,
    judge_api_key=settings.API_KEY,
    policy_prompt=POLICY,
    timeout_s=10.0,
    fail_open=True,
)

# Подменяем lifespan LiteLLM, чтобы запустить свои фоновые задачи
old = app.router.lifespan_context


@asynccontextmanager
async def wrapped_lifespan(app_):
    await create_all_schemas()  # создание таблиц, должно быть до планировщиков
    scheduler = await start_langfuse_scheduler()           # скрапер Langfuse (каждый час)
    behavioral_scheduler = await start_behavioral_scheduler()  # агрегатор (ежедневно 00:30)
    try:
        async with old(app_) as _:
            yield
    finally:
        behavioral_scheduler.shutdown(wait=False)
        scheduler.shutdown(wait=False)


app.router.lifespan_context = wrapped_lifespan


if __name__ == "__main__":
    uvicorn.run(litellm_app, host="0.0.0.0", port=int(os.environ.get("LITELLM_PORT", 30000)))
