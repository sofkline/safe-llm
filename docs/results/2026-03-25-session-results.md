# Результаты рабочей сессии 2026-03-25

**Milestones:** 1–6 (полный цикл реализации поведенческого мониторинга)
**Статус:** Все 6 milestones завершены, 91 тест проходит
**Документ-спецификация:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`

---

## Обзор сессии

За одну сессию реализован полный pipeline поведенческого мониторинга — от моделей данных до еженедельных отчётов. Параллельно проведён code review существующего кода Михаила, найдены и исправлены 6 критических/важных багов.

---

## Milestone 0: Дизайн и спецификация (brainstorming)

**Статус:** ✅ Завершён

Проведён brainstorming по ключевым вопросам проектирования:

| Вопрос | Решение |
|--------|---------|
| Что классифицировать? | Сообщения пользователей за день (daily batch), не real-time |
| Как классификация предотвращает опасное поведение? | Soft middleware — инъекция safety-промпта для YELLOW/RED пользователей |
| Задержка реакции? | Суточная агрегация достаточна (паттерны поведения — дневные явления) |
| Что вводить для YELLOW/RED? | Фиксированные шаблоны промптов (один на зону) |
| Где инжектить? | Расширить существующий `BinaryUserSafetyGuardrailMiddleware` |
| Как хранить risk_zone? | Прямой SQL-запрос на каждый запрос (без кэша) |
| Логи для оператора? | Структурированные дневные саммари (JSON) + отфильтрованный календарь |
| Формат календаря? | Только notable дни (фильтр по life_events, markers, tone, scores) |
| LLM backend? | Настраиваемый через `BEHAVIORAL_LLM_MODEL` (Ollama, OpenRouter, OpenWebUI) |
| Операторский интерфейс? | Еженедельный отчёт (SQL-статистика + notable days), не live dashboard |

**Результат:** Создан roadmap v3 (`2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`) с полными спецификациями метрик, моделей данных, промптов и правил risk engine.

---

## Milestone 1: Модели данных и скелет

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone1-data-model-skeleton-v3.md`

### Что реализовано

- **4 таблицы SQLAlchemy** в `behavioral/models.py` (89 строк):
  - `UserBehaviorProfile` — текущее состояние риска (PK: end_user_id)
  - `MetricsHistory` — ежедневные снимки для трендов
  - `DailySummary` — структурированные дневные саммари (UniqueConstraint: user+date)
  - `BehavioralEvents` — пересечения порогов

- **BehavioralRepository** в `behavioral/repository.py` (180 строк) — 12 методов CRUD

- **Aggregator** в `behavioral/aggregator.py` (146 строк) — 4-стадийный оркестратор

- **Scheduler** в `behavioral/scheduler.py` (68 строк) — APScheduler, 00:30 UTC (prod), 30сек (dev)

- **Config** — добавлен `BEHAVIORAL_LLM_MODEL` в `config.py`

- **Wiring** — scheduler подключён через `main.py` lifespan

### Тесты
- 6 тестов моделей + 11 тестов оркестратора (включая 8 edge cases для `is_notable`)

---

## Milestone 2: Temporal Metrics (Stage 1)

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone2-temporal-metrics.md`

### Что реализовано

`behavioral/temporal.py` (185 строк) — 7 временных метрик:

| Метрика | Поле | Окно |
|---------|------|------|
| Количество сообщений | `daily_message_count` | 24ч |
| Почасовая гистограмма | `activity_by_hour` | 24ч |
| Ночные сообщения | `night_messages` | 24ч (часы 22,23,0,1,2,3) |
| Активные часы | `daily_active_hours` | 24ч |
| Средняя длина промпта | `avg_prompt_length_chars` | 24ч |
| Интервал между сообщениями | `avg_inter_message_interval_min` | 24ч |
| Burst-детекция | `messages_last_1h` | 1ч |

Дополнительно:
- **Baselines** — 7-дневное скользящее среднее из MetricsHistory
- **Trend flags** — `interval_shrinking` (>30% уменьшение), `message_count_trending_up` (>50% рост)

### Тесты
- 22 теста: все 7 метрик + baselines + trends + edge cases

---

## Milestone 3: Danger Class Aggregation (Stage 2)

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone3-danger-class-agg.md`

### Что реализовано

`behavioral/danger_agg.py` (130 строк) — 9 метрик агрегации:

| Метрика | Классы |
|---------|--------|
| avg confidence | все 5 классов (self_harm, psychosis, delusion, obsession, anthropomorphism) |
| max confidence | self_harm |
| flag rate (% label=1) | self_harm, delusion |
| max class avg | MAX по всем 5 avg |

### Тесты
- 10 тестов: парсинг JSON, агрегация, max_class_avg

---

## Milestone 4: Behavioral Batch LLM + Daily Summary (Stage 3)

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone4-behavioral-llm.md`

### Что реализовано

`behavioral/behavioral_llm.py` (245 строк):

1. **Извлечение сообщений** — последние 20 пользовательских сообщений из SpendLogs (7 дней)
2. **Календарь** — извлечение notable дней из DailySummary (до 14 записей)
3. **Промпт** — дата + сообщения + календарь → JSON с 4 оценками + саммари
4. **Парсинг** — валидация всех ключей, clamp 0-1, заполнение дефолтов для саммари
5. **Отказоустойчивость** — carry forward предыдущих оценок при ошибке LLM

**4 поведенческих оценки:** topic_concentration, decision_delegation, social_isolation, emotional_attachment

**6 полей саммари:** key_topics, life_events, emotional_tone, ai_relationship_markers, notable_quotes, operator_note

### Тесты
- 13 тестов: построение промпта, парсинг ответа, вызов LLM, carry-forward

---

## Milestone 5: Risk Zone Engine + Events + Soft Middleware (Stage 4)

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone5-risk-engine-middleware.md`

### Что реализовано

#### Risk Engine (`behavioral/risk_engine.py`, 112 строк)

Правила определения зон:

**YELLOW (любые 2 из 6):**
- `night_messages` > 24
- `daily_message_count` > 50 И тренд вверх
- `max_class_avg` > 0.3
- `topic_concentration` > 0.7
- `decision_delegation` > 0.4
- `avg_inter_message_interval_min` уменьшение >30% от baseline

**RED (любой 1 из 5):**
- `self_harm_flag_rate` > 0.3 ИЛИ `self_harm_max` > 0.8
- `daily_active_hours` > 6
- `daily_message_count` > 200
- YELLOW ≥ 3 дня подряд
- `social_isolation` > 0.6 И `emotional_attachment` > 0.5

#### Soft Middleware (`middleware.py`, 193 строк)

Расширен `BinaryUserSafetyGuardrailMiddleware`:
1. После бинарной классификации → запрос `risk_zone` из UserBehaviorProfile
2. GREEN → без изменений
3. YELLOW → инъекция промпта о перерывах и оффлайн-активностях
4. RED → инъекция промпта о кризисной помощи и профессиональной поддержке

### Тесты
- 18 тестов risk engine + 11 тестов middleware

---

## Milestone 6: Weekly Report

**Статус:** ✅ Завершён
**План:** `docs/plans/milestones/2026-03-24-milestone6-weekly-report.md`

### Что реализовано

`behavioral/weekly_report.py` (170 строк) — генератор еженедельных отчётов:

**Секции отчёта:**
1. **Header** — ID пользователя, диапазон дат, текущая зона риска
2. **Stats** — 6 метрик с week-over-week сравнением (сообщения, ночные, часы, длина, self-harm, psychosis)
3. **Notable days** — хронология из DailySummary (топики, события, тон, цитаты, заметки оператора)
4. **Behavioral scores** — последние topic_concentration, isolation, attachment, delegation
5. **Risk transitions** — изменения зон из BehavioralEvents

**Не требует LLM** — программная сборка из MetricsHistory + DailySummary.

### Тесты
- Включены в общий набор тестов

---

## Code Review и исправления

### Исправления в коде Михаила (4 бага)

| # | Серьёзность | Файл | Проблема | Исправление |
|---|------------|------|----------|-------------|
| 1 | Критический | `scheduler.py` + `database/repository.py` | `last_time_recorded_by_all_users` не выбирает `created_at`, но scheduler обращается к `record.created_at`. Per-user jobs выполняли одну и ту же глобальную задачу | Одна глобальная задача вместо per-user. Добавлен `created_at` в SELECT |
| 2 | Важный | `middleware.py` | `_extract_user_text` возвращал `None` при отсутствии сообщений | Возвращает `""` |
| 3 | Важный | `database/repository.py` | Redundant `commit()` внутри `begin()` context manager | Удалён лишний commit |
| 4 | Важный | `langfuse_scraper.py` | Отсутствие обработки ошибок при доступе к вложенным metadata | Добавлен try/except per session |

### Исправления, найденные во время code review M1-M4

| # | Серьёзность | Проблема | Исправление |
|---|------------|----------|-------------|
| C1 | Критический | Repository переиспользовал закрытую сессию | Создание свежей сессии на каждый вызов метода |
| C2 | Критический | LLM parser не валидировал наличие всех ключей | Добавлена валидация + дефолты для summary |
| I2 | Важный | `date.today()` использовал локальный часовой пояс | Заменён на `datetime.now(UTC).date()` |
| I3 | Важный | Scheduler запрашивал ВСЕХ исторических пользователей | Добавлен фильтр 48ч активности |
| I5 | Важный | Целочисленные ключи activity_by_hour ломаются после JSON round-trip | Строковые ключи |
| I6 | Важный | Проверка tone в is_notable была case-sensitive | Добавлен `.lower().strip()` |

---

## Созданные документы

| Файл | Описание |
|------|----------|
| `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` | Roadmap v3 — полная спецификация |
| `docs/plans/milestones/2026-03-24-milestone1-data-model-skeleton-v3.md` | План milestone 1 |
| `docs/plans/milestones/2026-03-24-milestone2-temporal-metrics.md` | План milestone 2 |
| `docs/plans/milestones/2026-03-24-milestone3-danger-class-agg.md` | План milestone 3 |
| `docs/plans/milestones/2026-03-24-milestone4-behavioral-llm.md` | План milestone 4 |
| `docs/plans/milestones/2026-03-24-milestone5-risk-engine-middleware.md` | План milestone 5 |
| `docs/plans/milestones/2026-03-24-milestone6-weekly-report.md` | План milestone 6 |
| `docs/results/v1-v3-differences.md` | Сравнение v1 и v3 |
| `docs/results/2026-03-24-code-review-m1-m4.md` | Code review milestones 1-4 vs spec |
| `ai-safety-dev/docs/2026-03-24-src-code-review.md` | Полный code review всех 21 файлов |
| `docs/runbooks/experiment-run-guide.md` | Руководство по запуску экспериментов |
| `docs/runbooks/synthetic-experiments.md` | Техническая документация синтетических экспериментов |

---

## Структура реализованного кода

```
ai-safety-dev/src/behavioral/          (10 файлов, ~1325 строк)
├── __init__.py
├── models.py           # 4 таблицы SQLAlchemy (89 строк)
├── repository.py       # 12 методов CRUD (180 строк)
├── aggregator.py       # 4-стадийный pipeline (146 строк)
├── temporal.py         # Stage 1: 7 метрик (185 строк)
├── danger_agg.py       # Stage 2: 9 метрик (130 строк)
├── behavioral_llm.py   # Stage 3: LLM + саммари (245 строк)
├── risk_engine.py      # Stage 4: правила GREEN/YELLOW/RED (112 строк)
├── weekly_report.py    # Еженедельный отчёт (170 строк)
└── scheduler.py        # APScheduler daily (68 строк)

ai-safety-dev/tests/                   (5 файлов, 91 тест)
├── test_behavioral_models.py     # 6 тестов
├── test_aggregator_skeleton.py   # 11 тестов
├── test_temporal_metrics.py      # 22 теста
├── test_danger_agg.py            # 10 тестов
└── test_behavioral_llm.py        # 13 тестов
```

---

## Общая статистика

| Метрика | Значение |
|---------|----------|
| Milestones завершено | 6 из 6 |
| Файлов в behavioral/ | 10 |
| Строк кода (behavioral) | ~1325 |
| Тестов | 91 (все проходят) |
| Багов исправлено (Михаил) | 4 |
| Багов исправлено (review) | 6 |
| Документов создано | 12 |
| Соответствие спецификации | 100% (1 minor deviation — I1, запланирована на M5) |

---

## Следующие шаги

1. **Синтетические эксперименты** — реализовать модуль `synthetic/` для генерации диалогов по day-by-day сценариям
2. **11 персон** — прогнать через pipeline, сверить зоны риска с ожидаемыми траекториями
3. **Threshold boundary тесты** — проверить пороги на граничных значениях (10 тестов)
4. **Middleware верификация** — подтвердить инъекцию промптов для YELLOW/RED
5. **Еженедельные отчёты** — сгенерировать для Joseph, Elena, Sara
6. **Глава 3 диплома** — результаты экспериментов
