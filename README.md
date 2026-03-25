# Safe LLM — Psychological Safety of Conversational AI

Комплексный поведенческий мониторинг и обеспечение безопасного взаимодействия в системах диалогового ИИ

#### Source code repo

- https://github.com/PixelPantz/ai-safety

## Архитектура

```
LiteLLM Proxy + Middleware (binary classification + soft safety prompts)
        ↓                          ↑ risk_zone lookup
   SpendLogs / PredictTable → Behavioral Pipeline (daily)
                                ├── Stage 1: Temporal Metrics (7 metrics from SpendLogs)
                                ├── Stage 2: Danger Class Aggregation (5 classes from PredictTable)
                                ├── Stage 3: Behavioral LLM (4 scores + daily summary)
                                └── Stage 4: Risk Zone Engine (GREEN / YELLOW / RED)
                                        ↓
                              Weekly Report (SQL stats + notable days timeline)
```

## Как это работает

1. **LiteLLM Proxy** проксирует запросы к LLM, сохраняя логи в PostgreSQL
2. **Langfuse Scraper** (ежечасно) классифицирует сообщения по 5 классам опасности: self_harm, psychosis, delusion, obsession, anthropomorphism
3. **Behavioral Pipeline** (ежедневно, 00:30 UTC) анализирует паттерны каждого пользователя за 24ч и присваивает зону риска
4. **Soft Middleware** инжектит safety-промпт в запросы YELLOW/RED пользователей (без блокировки)
5. **Weekly Report** генерирует еженедельный отчёт: SQL-статистика + хронология notable days + переходы зон риска

## Зоны риска

- **GREEN** — нормальное использование, без вмешательства
- **YELLOW** — ранние предупреждающие сигналы (ночная активность, фиксация на теме, делегирование решений ИИ). Инжектится промпт с рекомендациями перерывов
- **RED** — критические сигналы (self-harm, >6ч активности, изоляция + привязанность). Инжектится промпт с контактами кризисной помощи

## Структура проекта

```
ai-safety-dev/
├── src/
│   ├── main.py                 # Entrypoint: LiteLLM proxy + middleware + schedulers
│   ├── middleware.py            # Binary classification + risk zone injection
│   ├── classificators.py       # Binary + multi-label LLM classifiers
│   ├── langfuse_scraper.py     # Langfuse trace fetcher + classifier
│   ├── scheduler.py            # Hourly Langfuse scraper scheduler
│   ├── config.py               # Settings (pydantic-settings)
│   ├── prompts.py              # LLM policy prompts
│   ├── schemas.py              # Pydantic response models
│   ├── database/
│   │   ├── __init__.py         # Engine + Session factory
│   │   ├── models.py           # LiteLLM schema + PredictTable
│   │   └── repository.py       # PredictRepository
│   └── behavioral/
│       ├── models.py           # 4 tables (Profile, History, Summary, Events)
│       ├── repository.py       # BehavioralRepository (12 methods)
│       ├── aggregator.py       # 4-stage daily pipeline
│       ├── temporal.py         # Stage 1: 7 temporal metrics
│       ├── danger_agg.py       # Stage 2: 5 danger class aggregation
│       ├── behavioral_llm.py   # Stage 3: LLM scores + daily summary
│       ├── risk_engine.py      # Stage 4: GREEN/YELLOW/RED rules
│       ├── weekly_report.py    # Weekly report generator
│       └── scheduler.py        # Daily behavioral scheduler
├── tests/                      # 91 tests
└── docs/                       # Code review
```

## Tech Stack

- **LiteLLM** — proxy server + unified LLM API
- **PostgreSQL** + **SQLAlchemy** (async) — storage
- **APScheduler** — cron jobs (hourly scraper + daily pipeline)
- **Langfuse** — tracing + observability
- **Pydantic** — settings + response models


