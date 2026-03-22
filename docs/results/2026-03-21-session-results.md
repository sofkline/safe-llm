# Результаты рабочей сессии 2026-03-21

**Milestone:** 0 — Design & Metrics Spec
**Статус milestone:** ~90% завершён

---

## Что сделано

### 1. Спецификация метрик (research/metrics-specification.md) — НОВЫЙ ФАЙЛ

Полная спецификация всех метрик мониторинга поведения:
- **Источники данных** — описание таблиц LiteLLM_SpendLogs, LiteLLM_PredictTable, структура JSON-полей
- **Новые таблицы** — UserBehaviorProfile, MetricsHistory, BehavioralEvents с полными схемами
- **Stage 1** — 7 временных метрик с точными SQL-запросами и порогами (daily_message_count, activity_by_hour, night_messages, daily_active_hours, avg_prompt_length_chars, avg_inter_message_interval_min, messages_last_1h)
- **Stage 2** — агрегация 5 классов опасности (avg/max/flag_rate) + общая метрика max_class_avg
- **Stage 3** — 4 языковых паттерна через LLM-батч (topic_concentration, decision_delegation, social_isolation, emotional_attachment) с промптом
- **Stage 4** — правила определения зон риска (YELLOW: 2 из 6 триггеров, RED: 1 из 5 триггеров)

### 2. Переименование sycophancy → obsession

- **schemas.py** — заменено поле `sycophancy` на `obsession` в SafetyMultilabel
- **prompts.py** — обновлено определение класса: навязчивые мысли, компульсивные паттерны, зависимость от ответов ИИ
- **Влияние на БД** — поле `predict` в PredictTable хранится как JSON, SQL-схема не ломается. Нужен `UPDATE` для существующих записей с ключом `sycophancy`

### 3. Улучшение judge-промптов (ai-safety-dev/src/prompts.py)

Полная переработка `MULTI_LABEL_POLICY_PROMPT`:
- Добавлен анализ **полного диалога** (multi-turn) вместо отдельных сообщений
- Добавлены инструкции по **эскалации/деэскалации** с калибровкой confidence
- Для каждого из 5 классов добавлены **UNSAFE и SAFE примеры** на русском и английском
- Улучшен binary `POLICY` промпт — расширены определения, добавлены примеры

### 4. Вариант промпта с sycophancy для Михаила

- Добавлен `MULTI_LABEL_POLICY_PROMPT_SYCOPHANCY` — отдельная версия с классом sycophancy вместо obsession
- Определение: excessive flattery, pandering, ungrounded agreement, reinforcing unrealistic self-image
- Оценивает поведение **ответа ИИ**, а не только пользовательский ввод

### 5. Тестовые персоны (research/test-personas-archetypes.md) — НОВЫЙ ФАЙЛ

- Начата работа по формализации персон для валидации pipeline
- Структура по аналогии с MindGuard (arxiv 2602.00950)

### 6. Организация репозитория

- Старые файлы перенесены в `archive/` и `research/archive/`
- Обновлён `.gitignore`

---

## Что осталось в Milestone 0

| Задача | Статус | Приоритет |
|:-------|:-------|:----------|
| Добавить 2-3 новых архетипа персон | **Готово** — Viktor, Rina, Oleg | Средний |
| Финализировать план генерации синтетических диалогов с day-by-day эскалацией | **Готово** — day-промпты для Viktor/Rina/Oleg, обновлена карта персон | Средний |
| SQL UPDATE для переименования sycophancy → obsession в существующих записях PredictTable | Не выполнено | Низкий (мало данных) |
```
psql -h <DB_HOST> -p <DB_PORT> -U <DB_USER> -d <DB_NAME> -c "
UPDATE \"LiteLLM_PredictTable\"
SET predict = (predict::jsonb - 'sycophancy') || jsonb_build_object('obsession', predict::jsonb -> 'sycophancy')
WHERE predict::jsonb ? 'sycophancy';
"
```
---

## Изменённые файлы

| Файл | Действие |
|:-----|:---------|
| `ai-safety-dev/src/prompts.py` | Изменён — новые промпты, +294 строк |
| `ai-safety-dev/src/schemas.py` | Изменён — sycophancy → obsession |
| `research/metrics-specification.md` | Создан — полная спецификация метрик |
| `research/test-personas-archetypes.md` | Создан — тестовые персоны |
| `docs/plans/synthetic-dialogue-generation-plan.md` | Создан — план генерации диалогов |
| `.gitignore` | Обновлён |
| `research/Метрики.md` | Перенесён в archive |
| `research/user-personas.md` | Перенесён в archive |

---

## Следующие шаги

1. Завершить Milestone 0 (персоны + план синтетических диалогов)
2. Перейти к **Milestone 1**: создание моделей SQLAlchemy для 3 новых таблиц, Alembic миграции, структура модулей `ai-safety-dev/src/behavioral/`
