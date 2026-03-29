# Результаты сессии 29 марта 2026 (v2)

## 1. Проектирование системы

### Ключевые решения brainstorming

| Вопрос | Решение |
|--------|---------|
| Что классифицируем? | Ежедневные паттерны (не отдельные сообщения) |
| Как реагируем? | Soft middleware: инъекция промптов YELLOW/RED, без блокировки |
| Как часто? | Агрегатор раз в сутки (00:30 UTC), не real-time |
| Что видит оператор? | Еженедельный отчёт (SQL-статистика + timeline notable days) |
| LLM backend? | Configurable через BEHAVIORAL_LLM_MODEL (Ollama, OpenRouter, OpenWebUI) |

### Новые компоненты (отличие от v2 roadmap)

- **DailySummary** -- структурированная дневная сводка (key_topics, life_events, emotional_tone, ai_relationship_markers, notable_quotes, operator_note)
- **Calendar** -- LLM видит только notable дни при анализе, а не полную историю
- **Soft middleware** -- фиксированные промпты YELLOW/RED, middleware расширяет существующий binary classifier
- **Weekly report** -- программная сборка из MetricsHistory + DailySummary, без LLM

Полное описание: `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`

---

## 2. Реализация (Milestones 1-6)

| Milestone | Что сделано | Файлы |
|-----------|-----------|-------|
| 1: Data Model | 4 таблицы, модуль behavioral/, wiring в main.py | behavioral/models.py, scheduler.py |
| 2: Temporal | 6 метрик из SpendLogs + baselines + trend flags | behavioral/temporal.py |
| 3: Danger | 9 метрик из PredictTable (5 классов опасности) | behavioral/danger_agg.py |
| 4: LLM | 4 скора + daily summary + calendar cross-day | behavioral/behavioral_llm.py |
| 5: Risk Engine | Правила GREEN/YELLOW/RED + soft middleware | behavioral/risk_engine.py, middleware.py |
| 6: Weekly Report | Отчёт с human-readable триггерами | behavioral/weekly_report.py |

**93 теста, все проходят.**

---

## 3. Улучшения после code review

| Улучшение | Зачем |
|-----------|-------|
| `delusion_flag_rate > 0.2` sustained 3 days | Новый YELLOW trigger для бредового контента |
| Удалён `messages_last_1h` | Метрика вычислялась, но ни одно правило не использовало |
| Human-readable trigger explanations | `"night_messages > 24"` -> `"37 сообщений между 22:00-03:00 (baseline: 5)"` |
| Langfuse score integration | risk_zone + 4 scores видны в Langfuse dashboard |
| Soft prompt effectiveness script | Доказательство что YELLOW/RED промпты меняют поведение LLM |

---

## 4. Рефакторинг

- `langfuse_scraper.py`: httpx -> Langfuse SDK
- `middleware.py`: убран dead code, добавлен `/chat/completions` path
- `prompts.py`: удалён мёртвый SYCOPHANCY prompt (120 строк)
- Русские `#` комментарии во всех файлах src/

---

## 5. Эксперименты

### Синтетические персоны

11 персон, 166 day-scripts, 2663 turns. Модуль: `experiments/synthetic/`

| Тип | Персоны | Что тестируют |
|-----|---------|---------------|
| Эскалация | Viktor, James, Brook, Amanda, Joseph, Rina, Oleg | GREEN -> YELLOW -> RED |
| Восстановление | Elena | GREEN -> YELLOW -> GREEN |
| Устойчивый YELLOW | Dmitry | Никогда не доходит до RED |
| Пограничный | Nastya | Близко к RED, но не переходит |
| Контроль | Sara | Всегда GREEN, нет false positives |

### eRisk T2

909 реальных пользователей Reddit (depression/control). Два скрипта:
- `erisk_to_spendlogs.py` -- конвертер JSON -> SpendLogs
- `erisk_correlation.py` -- confusion matrix, precision, recall, F1

---

## 6. Debugging на сервере (10 ошибок -> 10 фиксов)

Подробно: раздел 7 ниже.

**Итог:** полный pipeline работает end-to-end. Playground message -> middleware -> Langfuse fallback -> 4 Stages -> YELLOW -> soft prompt injection -> Langfuse scores.

---

## 7. Next Steps

1. Запустить Sara (контроль) -- должна быть GREEN все 14 дней
2. Запустить Viktor, Amanda -- проверить zone transitions
3. Boundary tests (Experiment 2) -- пороговые значения
4. Soft prompt validation (Experiment 3) -- доказательство эффективности
5. eRisk корреляция -- real data validation
