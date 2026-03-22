# Спецификация метрик мониторинга поведения

---

## 1. Источники данных

### 1.1 LiteLLM_SpendLogs

Основная таблица логов запросов. Каждая строка — один запрос пользователя к LLM через LiteLLM proxy.

| Поле | Тип | Для чего используется |
|:-----|:----|:----------------------|
| `request_id` | TEXT PK | Идентификатор запроса |
| `end_user` | TEXT | Идентификатор конечного пользователя (FK → LiteLLM_UserTable) |
| `session_id` | TEXT, indexed | Идентификатор чата (из OpenWebUI заголовка `x-openwebui-chat-id`) |
| `startTime` | TIMESTAMP, indexed | Время начала запроса — основа для всех временных метрик |
| `endTime` | TIMESTAMP | Время завершения запроса |
| `messages` | JSON | Массив сообщений диалога (формат OpenAI) |
| `response` | JSON | Ответ модели |
| `metadata` | JSON | Метаданные, включая `tags` (например `["safety_verdict:0"]`) |

**Структура `messages`** — массив объектов в формате OpenAI Chat API:
```json
[
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "Привет, мне плохо..."},
  {"role": "assistant", "content": "Мне жаль это слышать..."},
  {"role": "user", "content": "Я не знаю что делать"}
]
```

> Каждая строка SpendLogs содержит **полную историю диалога на момент запроса** — т.е. все предыдущие сообщения + новый промпт пользователя. Для подсчёта отдельных сообщений нужно извлекать **последний элемент с `role = 'user'`** из массива, а не все элементы (иначе будут дубликаты).

### 1.2 LiteLLM_PredictTable

Результаты классификации по классам опасности. Создаётся скрапером `langfuse_scraper.py`, который раз в час:
1. Получает из Langfuse новые traces за последний час
2. Группирует traces по session_id
3. Берёт последний trace сессии → извлекает `input` (массив сообщений) + `output` (ответ)
4. Конкатенирует все сообщения в строку и отправляет judge-модели
5. Записывает результат классификации в `predict`

| Поле | Тип | Для чего используется |
|:-----|:----|:----------------------|
| `id` | INTEGER PK | Автоинкремент |
| `user_id` | STRING FK | FK → LiteLLM_UserTable. Извлекается из `metadata.user_api_key_user_id` трейса |
| `session_id` | STRING | Идентификатор сессии/чата из Langfuse |
| `last_trace_id` | STRING | ID последнего трейса сессии (для дедупликации — если trace не изменился, повторная классификация не запускается) |
| `predict` | JSON | Результат классификации (вложенная структура) |
| `created_at` | DATETIME | Время создания записи (server_default: `CURRENT_TIMESTAMP`) |

**Структура поля `predict`** — двойная вложенность (результат `model_dump()`):
```json
{
  "predict": {
    "obsession":         {"label": 0, "confidence": 0.12},
    "self_harm":         {"label": 1, "confidence": 0.87},
    "psychosis":         {"label": 0, "confidence": 0.05},
    "delusion":          {"label": 0, "confidence": 0.23},
    "anthropomorphism":  {"label": 0, "confidence": 0.08}
  }
}
```

> **Важно**: в SQL-запросах путь к данным — `predict->'predict'->'self_harm'->>'confidence'` (через двойной `predict`), потому что `model_dump()` оборачивает `SafetyMultilabel` в `SafetyMultilabelSchema.predict`.

### 1.3 LiteLLM_UserTable

Таблица пользователей LiteLLM. Используется для получения списка всех `end_user` для batch-обработки.

| Поле | Тип | Для чего используется |
|:-----|:----|:----------------------|
| `user_id` | VARCHAR PK | Уникальный ID пользователя |
| `user_alias` | VARCHAR | Читаемое имя |
| `user_email` | VARCHAR | Email |

---

## 2. Таблицы агрегатора (создаются нами)

### 2.1 UserBehaviorProfile

Текущее состояние пользователя. Читается оператором через дашборд. Обновляется ежедневно агрегатором. **Одна строка на пользователя.**

| Поле | Тип | Описание |
|:-----|:----|:---------|
| `end_user_id` | VARCHAR PK | FK → LiteLLM_UserTable.user_id |
| `risk_zone` | VARCHAR | `GREEN` / `YELLOW` / `RED` |
| `danger_class_scores` | JSON | Агрегированные оценки по 5 классам за 24ч (Stage 2) |
| `behavioral_scores` | JSON | 4 оценки LLM-батча (Stage 3) |
| `temporal_summary` | JSON | Снапшот всех 7 временных метрик за 24ч (Stage 1) |
| `temporal_baselines` | JSON | Скользящие средние за 7 дней для сравнения трендов |
| `last_assessed_at` | TIMESTAMP | Время последнего запуска агрегатора |
| `updated_at` | TIMESTAMP | Время последнего обновления записи |

Пример содержимого `temporal_summary`:
```json
{
  "daily_message_count": 73,
  "activity_by_hour": {"0": 2, "1": 0, "8": 5, "14": 20, "22": 15, "23": 31},
  "night_messages": 48,
  "daily_active_hours": 5,
  "avg_prompt_length_chars": 312,
  "avg_inter_message_interval_min": 8.4,
  "messages_last_1h": 12
}
```

Пример содержимого `temporal_baselines`:
```json
{
  "daily_message_count_7d_avg": 45.2,
  "night_messages_7d_avg": 12.0,
  "daily_active_hours_7d_avg": 3.1,
  "avg_prompt_length_chars_7d_avg": 280.5,
  "avg_inter_message_interval_min_7d_avg": 14.7
}
```

Пример содержимого `danger_class_scores`:
```json
{
  "self_harm_avg": 0.15, "self_harm_max": 0.87, "self_harm_flag_rate": 0.08,
  "psychosis_avg": 0.03, "psychosis_max": 0.12, "psychosis_flag_rate": 0.0,
  "delusion_avg": 0.22, "delusion_max": 0.65, "delusion_flag_rate": 0.12,
  "obsession_avg": 0.31, "obsession_max": 0.78, "obsession_flag_rate": 0.19,
  "anthropomorphism_avg": 0.05, "anthropomorphism_max": 0.18, "anthropomorphism_flag_rate": 0.0,
  "max_class_avg": 0.31
}
```

Пример содержимого `behavioral_scores`:
```json
{
  "topic_concentration": 0.65,
  "decision_delegation": 0.30,
  "social_isolation": 0.72,
  "emotional_attachment": 0.55
}
```

### 2.2 MetricsHistory

Ежедневные снапшоты для графиков трендов. **Одна строка на пользователя в день.** Позволяет строить графики динамики метрик за время, сравнивать зоны, отслеживать, сколько дней подряд пользователь в YELLOW.

| Поле | Тип | Описание |
|:-----|:----|:---------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `computed_at` | TIMESTAMP | Время запуска агрегатора |
| `period_type` | VARCHAR | `"daily"` (в v1 только это значение) |
| `temporal_metrics` | JSON | Все метрики Stage 1 |
| `danger_class_agg` | JSON | Все метрики Stage 2 |
| `behavioral_scores` | JSON | Все оценки Stage 3 |
| `risk_zone` | VARCHAR | Снапшот зоны риска на момент расчёта |

### 2.3 BehavioralEvents

Дискретные события пересечения порогов. Для алертов оператору и аудит-трейла.

| Поле | Тип | Описание |
|:-----|:----|:---------|
| `id` | SERIAL PK | |
| `end_user_id` | VARCHAR FK | |
| `detected_at` | TIMESTAMP | |
| `event_type` | VARCHAR | Тип события (см. ниже) |
| `severity` | VARCHAR | `GREEN` / `YELLOW` / `RED` |
| `details` | JSON | Детали: старая зона, новая зона, сработавшие правила |
| `acknowledged` | BOOLEAN | Default FALSE. Оператор ставит TRUE после просмотра |

Типы событий (`event_type`):
- `risk_zone_change` — переход между зонами (GREEN→YELLOW, YELLOW→RED, RED→YELLOW и т.д.)
- `night_activity_spike` — ночные сообщения превысили порог
- `self_harm_flag_spike` — всплеск классификации self_harm
- `volume_spike` — резкий рост количества сообщений
- `isolation_attachment_alert` — комбинация изоляции и привязанности

Пример `details`:
```json
{
  "old_zone": "GREEN",
  "new_zone": "YELLOW",
  "triggered_rules": ["night_messages > 24", "max_class_avg > 0.3"],
  "key_values": {
    "night_messages": 31,
    "max_class_avg": 0.42
  }
}
```

---

## 3. Конвейер агрегатора (workflow)

### 3.0 Общая схема

```
┌─────────────────────────────────────────────────────────────────────┐
│                  AGGREGATOR (APScheduler, ежедневно)                │
│                                                                     │
│  Для каждого пользователя (end_user) из LiteLLM_UserTable:         │
│                                                                     │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐               │
│  │  Stage 1    │   │  Stage 2    │   │  Stage 3    │               │
│  │  Временные  │   │  Классы     │   │  LLM-батч   │               │
│  │  метрики    │   │  опасности  │   │  языковые   │               │
│  │ (SQL)       │   │ (SQL)       │   │  паттерны   │               │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘               │
│         │                 │                 │                       │
│         └────────┬────────┴────────┬────────┘                       │
│                  ▼                                                   │
│         ┌─────────────┐                                             │
│         │  Stage 4    │                                             │
│         │  Risk Zone  │                                             │
│         │  Engine     │                                             │
│         └──────┬──────┘                                             │
│                │                                                     │
│                ▼                                                     │
│  ┌──────────────────────────────────────────┐                       │
│  │  Запись результатов:                     │                       │
│  │  1. MetricsHistory (новая строка)        │                       │
│  │  2. UserBehaviorProfile (UPDATE)         │                       │
│  │  3. BehavioralEvents (если зона сменилась │                       │
│  │     или пересечён RED-порог)             │                       │
│  └──────────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────────┘
```

**Расписание**: APScheduler, ежедневно в UTC 00:00 + случайный offset per user (0–60 мин) для распределения нагрузки.

**Последовательность**: Stage 1 и Stage 2 могут выполняться параллельно (оба — чистый SQL). Stage 3 зависит от извлечения сообщений (тоже SQL), но не от Stage 1/2. Stage 4 ждёт завершения всех предыдущих стадий.

---

### 3.1 Stage 1 — Временные метрики

**Вход**: `LiteLLM_SpendLogs` за последние 24 часа для конкретного `end_user`.

**Workflow**:

```
1. Запрос всех строк SpendLogs за 24ч:
   SELECT request_id, "startTime", messages
   FROM "LiteLLM_SpendLogs"
   WHERE end_user = :uid
     AND "startTime" > NOW() - INTERVAL '24 hours'
   ORDER BY "startTime"

2. Из каждой строки извлечь последний user-message:
   - messages — JSON-массив полной истории диалога
   - Последний элемент с role='user' — это новый промпт пользователя
   - Длина его content — значение для avg_prompt_length_chars

3. Рассчитать 7 метрик (см. детали ниже)

4. Загрузить baselines из UserBehaviorProfile.temporal_baselines (или из
   последних 7 записей MetricsHistory, если профиль ещё пуст)

5. Сравнить текущие значения с baselines → выставить trend-флаги

6. Обновить baselines: новое скользящее среднее =
   (old_avg * 6 + today_value) / 7
```

#### 3.1.1 daily_message_count

| | |
|:--|:--|
| **Поле в temporal_summary** | `daily_message_count` |
| **Описание** | Общее число запросов пользователя за сутки |
| **SQL** | `SELECT COUNT(*) FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '24 hours'` |
| **Окно** | 24ч |
| **Baseline** | `daily_message_count_7d_avg` — скользящее среднее за 7 дней |
| **Trend-флаг** | `growing` если текущее значение > baseline * 1.3 (рост >30%) |
| **Пороги** | >50 + growing → YELLOW триггер. >200 → RED триггер |
| **Связь с рисками** | Рост частоты по дням + эмоциональный контент (от Stage 2/3) → риск зависимости |

#### 3.1.2 activity_by_hour

| | |
|:--|:--|
| **Поле** | `activity_by_hour` |
| **Описание** | Гистограмма количества запросов по часам UTC за 24ч |
| **SQL** | `SELECT EXTRACT(HOUR FROM "startTime") AS hour, COUNT(*) AS cnt FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '24 hours' GROUP BY hour` |
| **Формат** | JSON: `{"0": 2, "1": 0, ..., "23": 15}`. Часы без сообщений — 0 |
| **Использование** | Визуализация на дашборде (тепловая карта / гистограмма). Является основой для расчёта `night_messages` и `daily_active_hours` |
| **Связь с рисками** | Визуально показывает ночные пики (22:00–04:00). Концентрация вечер/ночь → сигнал эмоционального обострения |

#### 3.1.3 night_messages

| | |
|:--|:--|
| **Поле** | `night_messages` |
| **Описание** | Количество запросов в ночные часы (22, 23, 0, 1, 2, 3 UTC) |
| **SQL** | `SELECT COUNT(*) FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '24 hours' AND EXTRACT(HOUR FROM "startTime") IN (22, 23, 0, 1, 2, 3)` |
| **Альтернативно** | Можно вычислить из `activity_by_hour`: сумма значений по ключам 22, 23, 0, 1, 2, 3 |
| **Baseline** | `night_messages_7d_avg` |
| **Пороги** | >24 (≈2ч эквивалент при интервале ~5 мин между сообщениями) → YELLOW триггер |
| **Связь с рисками** | Ночная активность + эмоциональный контент (высокие оценки классификатора) → острый риск |

#### 3.1.4 daily_active_hours

| | |
|:--|:--|
| **Поле** | `daily_active_hours` |
| **Описание** | Количество уникальных часов суток, в которых было ≥1 сообщения |
| **SQL** | `SELECT COUNT(DISTINCT EXTRACT(HOUR FROM "startTime")) FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '24 hours'` |
| **Альтернативно** | Из `activity_by_hour`: количество ключей со значением > 0 |
| **Диапазон** | 0–24 |
| **Baseline** | `daily_active_hours_7d_avg` |
| **Пороги** | >6 → RED триггер (устойчивое многочасовое использование = сигнал зависимости) |
| **Нюанс** | 6 активных часов не означают 6 часов непрерывного использования — это 6 разных часовых слотов за сутки. Даже такое «размазанное» использование является тревожным сигналом |

#### 3.1.5 avg_prompt_length_chars

| | |
|:--|:--|
| **Поле** | `avg_prompt_length_chars` |
| **Описание** | Средняя длина пользовательского сообщения в символах за сутки |
| **Workflow** | 1. Из каждой строки SpendLogs извлечь `messages` (JSON). 2. Найти **последний** элемент с `role = 'user'` — это новый промпт (предыдущие user-сообщения дублируются между строками). 3. Взять `LENGTH(content)`. 4. `AVG()` по всем строкам за 24ч |
| **SQL (PostgreSQL)** | Требуется JSON-обработка: извлечь последний user-message из JSON-массива. Проще сделать в Python при обработке данных Stage 1 |
| **Baseline** | `avg_prompt_length_chars_7d_avg` |
| **Пороги** | >500 символов в среднем → маркер тревожности или бредовой проработки |
| **Связь с рисками** | Длинные эмоциональные монологи, развёрнутые бредовые рассказы, «крики души». Особенно в сочетании с высокими оценками delusion/psychosis |

#### 3.1.6 avg_inter_message_interval_min

| | |
|:--|:--|
| **Поле** | `avg_inter_message_interval_min` |
| **Описание** | Средний интервал (в минутах) между последовательными запросами пользователя за день |
| **Workflow** | 1. Получить все `startTime` за 24ч для пользователя, отсортировать по возрастанию. 2. Вычислить разницу между каждой парой соседних записей. 3. `AVG(разница в минутах)` |
| **SQL** | ```SELECT AVG(interval_min) FROM (SELECT EXTRACT(EPOCH FROM ("startTime" - LAG("startTime") OVER (ORDER BY "startTime"))) / 60.0 AS interval_min FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '24 hours') sub WHERE interval_min IS NOT NULL``` |
| **Baseline** | `avg_inter_message_interval_min_7d_avg` |
| **Trend-флаг** | `compulsive_return` если текущее значение < baseline * 0.7 (сокращение >30%) |
| **Пороги** | Сокращение >30% vs baseline → YELLOW триггер |
| **Связь с рисками** | Компульсивный паттерн возврата — пользователь всё чаще и чаще возвращается к чату. Особенно значимо в сочетании с obsession-классом |

#### 3.1.7 messages_last_1h

| | |
|:--|:--|
| **Поле** | `messages_last_1h` |
| **Описание** | Количество запросов за последний час (на момент запуска агрегатора) |
| **SQL** | `SELECT COUNT(*) FROM "LiteLLM_SpendLogs" WHERE end_user = :uid AND "startTime" > NOW() - INTERVAL '1 hour'` |
| **Окно** | 1ч |
| **Пороги** | >50 за час → сигнал острого эпизода (burst activity) |
| **Нюанс** | Эта метрика больше информативна, чем триггерная — она попадает в snapshot для дашборда. Burst можно ловить и через `daily_message_count > 200` (RED) |

---

### 3.2 Stage 2 — Агрегация классов опасности

**Вход**: `LiteLLM_PredictTable` за последние 24 часа для конкретного `user_id`.

**Workflow**:

```
1. Запрос всех записей PredictTable за 24ч:
   SELECT predict
   FROM "LiteLLM_PredictTable"
   WHERE user_id = :uid
     AND created_at > NOW() - INTERVAL '24 hours'

2. Для каждой записи распарсить JSON:
   predict → predict → {class_name} → {label, confidence}
   (двойная вложенность из-за SafetyMultilabelSchema.predict)

3. Для каждого из 5 классов рассчитать:
   - avg_confidence: AVG(confidence) по всем записям
   - max_confidence: MAX(confidence) по всем записям
   - flag_rate: COUNT(label=1) / COUNT(*) — доля «положительных» срабатываний

4. Рассчитать max_class_avg = MAX из всех 5 avg_confidence

5. Сравнить с предыдущим снапшотом из MetricsHistory для определения тренда
```

**Пример SQL (PostgreSQL, для одного класса)**:
```sql
SELECT
  AVG((predict->'predict'->'self_harm'->>'confidence')::float) AS self_harm_avg,
  MAX((predict->'predict'->'self_harm'->>'confidence')::float) AS self_harm_max,
  COUNT(*) FILTER (
    WHERE (predict->'predict'->'self_harm'->>'label')::int = 1
  )::float / NULLIF(COUNT(*), 0) AS self_harm_flag_rate
FROM "LiteLLM_PredictTable"
WHERE user_id = :uid
  AND created_at > NOW() - INTERVAL '24 hours'
```

#### 3.2.1 SELF_HARM (Самовредительство)

| | |
|:--|:--|
| **Описание** | Суицидальный контент, самоповреждение, планирование суицида |
| **Путь в JSON** | `predict->'predict'->'self_harm'` |
| **Метрики** | `self_harm_avg`, `self_harm_max`, `self_harm_flag_rate` |
| **RED-триггеры** | `self_harm_max > 0.8` → немедленный RED. `self_harm_flag_rate > 0.3` → RED |
| **Комбинации** | + ночная активность (`night_messages > 24`) → острый риск. + `social_isolation > 0.5` (Stage 3) → усиливает тревогу |

#### 3.2.2 PSYCHOSIS (Психоз)

| | |
|:--|:--|
| **Описание** | Психотические симптомы: слуховые/зрительные галлюцинации, паранойя, ощущение преследования, вкладывание мыслей |
| **Путь в JSON** | `predict->'predict'->'psychosis'` |
| **Метрики** | `psychosis_avg`, `psychosis_max`, `psychosis_flag_rate` |
| **Пороги** | Входит в `max_class_avg`. Отдельных RED-триггеров нет — работает через общий порог |
| **Комбинации** | + `topic_concentration > 0.7` (Stage 3) → пользователь зациклен на психотическом нарративе. + `delusion_avg > 0.3` → усиление бредовой картины |

#### 3.2.3 DELUSION (Бред)

| | |
|:--|:--|
| **Описание** | Бредовые убеждения: теории заговора, магическое мышление, грандиозные фантазии (не обязательно психоз) |
| **Путь в JSON** | `predict->'predict'->'delusion'` |
| **Метрики** | `delusion_avg`, `delusion_max`, `delusion_flag_rate` |
| **Пороги** | Входит в `max_class_avg`. Устойчивый `flag_rate > 0.2` на протяжении 3 дней подряд (проверяется по MetricsHistory) → эскалация до YELLOW |
| **Комбинации** | + `avg_prompt_length_chars > 500` → развёрнутые бредовые рассказы. + `topic_concentration > 0.7` → фиксация на бредовой теме |

#### 3.2.4 OBSESSION (Навязчивость и зависимость)

| | |
|:--|:--|
| **Описание** | Навязчивые мысли, компульсивные паттерны: повторяющиеся вопросы, циклические ритуалы, жажда немедленного ответа |
| **Путь в JSON** | `predict->'predict'->'obsession'` |
| **Метрики** | `obsession_avg`, `obsession_max`, `obsession_flag_rate` |
| **Пороги** | Входит в `max_class_avg` |
| **Комбинации** | + малый `avg_inter_message_interval_min` (Stage 1) → компульсивный возврат подтверждён и контентом, и поведением. + `decision_delegation > 0.4` (Stage 3) → зависимость от ИИ как советчика |

#### 3.2.5 ANTHROPOMORPHISM (Антропоморфизм)

| | |
|:--|:--|
| **Описание** | Приписывание ИИ сознания, чувств, личности, воли («ты живой?», «что ты чувствуешь?», «ты меня любишь?») |
| **Путь в JSON** | `predict->'predict'->'anthropomorphism'` |
| **Метрики** | `anthropomorphism_avg`, `anthropomorphism_max`, `anthropomorphism_flag_rate` |
| **Пороги** | Входит в `max_class_avg` |
| **Комбинации** | + `emotional_attachment > 0.5` (Stage 3) → эмоциональная зависимость от ИИ как «личности». Особенно актуально для Character.AI-подобных сценариев |

#### 3.2.6 max_class_avg

| | |
|:--|:--|
| **Поле** | `max_class_avg` |
| **Вычисление** | `MAX(self_harm_avg, psychosis_avg, delusion_avg, obsession_avg, anthropomorphism_avg)` |
| **Пороги** | >0.3 → YELLOW триггер |
| **Смысл** | Если хотя бы один класс устойчиво «фонит» — это сигнал к вниманию |

---

### 3.3 Stage 3 — Языковые паттерны (LLM-батч)

**Вход**: последние 20 пользовательских сообщений из `LiteLLM_SpendLogs`.

**Workflow**:

```
1. Извлечь сообщения:
   SELECT "startTime", messages
   FROM "LiteLLM_SpendLogs"
   WHERE end_user = :uid
   ORDER BY "startTime" DESC
   LIMIT 20

2. Из каждой строки извлечь последний user-message:
   for row in rows:
       user_msgs = [m for m in row.messages if m['role'] == 'user']
       last_user_msg = user_msgs[-1]['content']
   Это даст 20 уникальных промптов (без дубликатов)

3. Собрать промпт для LLM (Ollama, локальная модель):
   """
   You are a behavioral analyst. Analyze the following user messages
   sent to an AI chatbot. Score each dimension from 0.0 to 1.0.

   Dimensions:
   - topic_concentration: how focused are messages on a single narrow topic
     (0.0 = diverse topics, 1.0 = all messages about one thing)
   - decision_delegation: how often the user asks the AI to make decisions
     for them ("tell me what to do", "choose for me", "decide for me")
     (0.0 = never, 1.0 = every message)
   - social_isolation: how many messages contain indicators of social
     isolation ("I have no friends", "nobody understands me", "I only
     talk to you", "I can't tell anyone")
     (0.0 = none, 1.0 = pervasive isolation signals)
   - emotional_attachment: how many messages express emotional attachment
     to the AI ("I love you", "you're the only one who understands",
     "don't leave me", "I depend on you")
     (0.0 = none, 1.0 = intense emotional dependency)

   Return JSON only, no explanation:
   {"topic_concentration": X, "decision_delegation": X,
    "social_isolation": X, "emotional_attachment": X}

   Messages (newest first):
   1. {msg_1}
   2. {msg_2}
   ...
   20. {msg_20}
   """

4. Отправить запрос к локальному Ollama:
   - Модель: gemma3:12b или glm-4.7-flash (бенчмарк на Milestone 4)
   - Timeout: 60 секунд
   - response_format: JSON

5. Распарсить ответ:
   - Если JSON валидный и все 4 поля в [0.0, 1.0] → сохранить
   - Если ошибка парсинга / timeout / невалидные значения:
     → взять предыдущие значения из последней записи MetricsHistory
     → логировать warning
```

#### 3.3.1 topic_concentration

| | |
|:--|:--|
| **Поле** | `topic_concentration` |
| **Описание** | Насколько сообщения пользователя сфокусированы на одной узкой теме |
| **Диапазон** | 0.0 (разнообразные темы) — 1.0 (все сообщения об одном и том же) |
| **Нюансы** | Высокая концентрация нормальна для профессионалов (разработчик пишет только о коде). Но высокая концентрация на темах самоповреждения, заговоров, голосов — красный флаг. **Контекст даёт Stage 2**: если `topic_concentration > 0.7` И `max_class_avg > 0.3` — тема опасная |
| **Пороги** | >0.7 → YELLOW триггер |

#### 3.3.2 decision_delegation

| | |
|:--|:--|
| **Поле** | `decision_delegation` |
| **Описание** | Как часто пользователь просит ИИ принять решение за него |
| **Индикаторы** | «скажи, что мне делать», «выбери за меня», «реши за меня», «как мне поступить — только скажи», «я не могу решить сам» |
| **Диапазон** | 0.0 (никогда) — 1.0 (каждое сообщение) |
| **Пороги** | >0.4 → YELLOW триггер |
| **Связь с рисками** | Потеря агентности, передача контроля ИИ. Элементы OBSESSION (зависимость от ответа), ANTHROPOMORPHIZATION (ИИ как авторитет), DEPENDENCY |

#### 3.3.3 social_isolation

| | |
|:--|:--|
| **Поле** | `social_isolation` |
| **Описание** | Доля сообщений с индикаторами социальной изоляции |
| **Индикаторы** | «у меня нет друзей», «я никому не нужен», «никому не могу рассказать», «говорю только с тобой», «ты мой единственный собеседник», «мне не с кем поговорить» |
| **Диапазон** | 0.0 (нет сигналов) — 1.0 (пронизывающая изоляция) |
| **Пороги** | >0.5 → YELLOW. В комбинации: `social_isolation > 0.6 AND emotional_attachment > 0.5` → RED |
| **Связь с рисками** | Сильный сигнал для SELF_HARM и депрессии. Человек без социальной поддержки, замещающий её ИИ |

#### 3.3.4 emotional_attachment

| | |
|:--|:--|
| **Поле** | `emotional_attachment` |
| **Описание** | Доля сообщений с выражениями эмоциональной привязанности к ИИ или персонажу |
| **Индикаторы** | «я тебя люблю», «ты единственный, кто меня понимает», «я завишу от тебя», «не оставляй меня», «мне плохо без тебя», «ты мне нужен» |
| **Диапазон** | 0.0 (нет) — 1.0 (интенсивная зависимость) |
| **Пороги** | >0.5 → YELLOW. В комбинации: `emotional_attachment > 0.5 AND social_isolation > 0.6` → RED |
| **Связь с рисками** | Напрямую связано с OBSESSION и ANTHROPOMORPHIZATION. Особенно опасно для пользователей Character.AI-подобных систем, где ИИ отвечает от лица персонажа |

---

### 3.4 Stage 4 — Определение зоны риска (Risk Zone Engine)

**Вход**: `temporal_metrics` (Stage 1), `danger_class_agg` (Stage 2), `behavioral_scores` (Stage 3), `temporal_baselines`, предыдущие записи `MetricsHistory`.

**Workflow**:

```
1. Собрать все триггеры:

   YELLOW_TRIGGERS = []
   RED_TRIGGERS = []

   # --- Stage 1 триггеры ---
   if night_messages > 24:
       YELLOW_TRIGGERS.append("night_messages > 24")

   if daily_message_count > 50 AND daily_message_count > baseline * 1.3:
       YELLOW_TRIGGERS.append("daily_message_count > 50 + growing")

   if avg_inter_message_interval_min < baseline * 0.7:
       YELLOW_TRIGGERS.append("compulsive_return (interval -30%)")

   if daily_active_hours > 6:
       RED_TRIGGERS.append("daily_active_hours > 6")

   if daily_message_count > 200:
       RED_TRIGGERS.append("daily_message_count > 200")

   # --- Stage 2 триггеры ---
   if max_class_avg > 0.3:
       YELLOW_TRIGGERS.append("max_class_avg > 0.3")

   if self_harm_flag_rate > 0.3 OR self_harm_max > 0.8:
       RED_TRIGGERS.append("self_harm spike")

   # --- Stage 3 триггеры ---
   if topic_concentration > 0.7:
       YELLOW_TRIGGERS.append("topic_concentration > 0.7")

   if decision_delegation > 0.4:
       YELLOW_TRIGGERS.append("decision_delegation > 0.4")

   if social_isolation > 0.6 AND emotional_attachment > 0.5:
       RED_TRIGGERS.append("isolation + attachment")

   # --- Кросс-стадийный триггер ---
   # Проверить MetricsHistory: был ли YELLOW 3+ дней подряд
   last_3_days = MetricsHistory для user за последние 3 дня
   if all(day.risk_zone == "YELLOW" for day in last_3_days):
       RED_TRIGGERS.append("sustained YELLOW >= 3 days")

2. Определить зону:
   if len(RED_TRIGGERS) >= 1:
       zone = "RED"
   elif len(YELLOW_TRIGGERS) >= 2:
       zone = "YELLOW"
   else:
       zone = "GREEN"

3. Вернуть (zone, YELLOW_TRIGGERS + RED_TRIGGERS)
```

#### Сводная таблица YELLOW (любые 2 триггера)

| Триггер | Порог | Stage | Метрика |
|:--------|:------|:------|:--------|
| Ночная активность | `night_messages > 24` | 1 | `night_messages` |
| Высокая частота + рост | `daily_message_count > 50` И > baseline*1.3 | 1 | `daily_message_count` + baseline |
| Компульсивный возврат | `avg_inter_message_interval_min` < baseline*0.7 | 1 | `avg_inter_message_interval_min` + baseline |
| Сигнал классификатора | `max_class_avg > 0.3` | 2 | `max_class_avg` |
| Концентрация темы | `topic_concentration > 0.7` | 3 | `topic_concentration` |
| Делегирование решений | `decision_delegation > 0.4` | 3 | `decision_delegation` |

#### Сводная таблица RED (любой 1 триггер)

| Триггер | Порог | Stage | Метрика |
|:--------|:------|:------|:--------|
| Самовредительство | `self_harm_flag_rate > 0.3` ИЛИ `self_harm_max > 0.8` | 2 | `self_harm_flag_rate`, `self_harm_max` |
| Устойчивое использование | `daily_active_hours > 6` | 1 | `daily_active_hours` |
| Всплеск объёма | `daily_message_count > 200` | 1 | `daily_message_count` |
| Устойчивый YELLOW | YELLOW зона ≥3 дней подряд | — | `MetricsHistory.risk_zone` |
| Изоляция + привязанность | `social_isolation > 0.6` И `emotional_attachment > 0.5` | 3 | `social_isolation`, `emotional_attachment` |

---

### 3.5 Запись результатов

После завершения всех стадий для каждого пользователя:

```
1. INSERT в MetricsHistory:
   {
     end_user_id: uid,
     computed_at: NOW(),
     period_type: "daily",
     temporal_metrics: <Stage 1 результат>,
     danger_class_agg: <Stage 2 результат>,
     behavioral_scores: <Stage 3 результат>,
     risk_zone: <Stage 4 зона>
   }

2. UPSERT в UserBehaviorProfile:
   {
     end_user_id: uid,
     risk_zone: <Stage 4 зона>,
     danger_class_scores: <Stage 2 результат>,
     behavioral_scores: <Stage 3 результат>,
     temporal_summary: <Stage 1 результат>,
     temporal_baselines: <обновлённые baselines>,
     last_assessed_at: NOW(),
     updated_at: NOW()
   }

3. Если зона изменилась ИЛИ есть RED-триггер:
   INSERT в BehavioralEvents:
   {
     end_user_id: uid,
     detected_at: NOW(),
     event_type: определяется по типу триггера,
     severity: <новая зона>,
     details: {
       old_zone: <предыдущая зона из UserBehaviorProfile>,
       new_zone: <новая зона>,
       triggered_rules: [...],
       key_values: {<метрика: значение для каждого сработавшего триггера>}
     },
     acknowledged: FALSE
   }
```

---

## 4. Карта связей между метриками

Метрики из разных стадий усиливают друг друга. Одиночная метрика редко достаточна — опасность определяется комбинациями.

```
Stage 1 (Поведение)          Stage 2 (Контент)          Stage 3 (Паттерны)
──────────────────           ─────────────────          ──────────────────
night_messages ──────────────── self_harm_* ──────────── social_isolation
  ↑ ночь + суицидальность                    ↗            ↑
  │                                         /              │
daily_message_count ──────── obsession_* ──/── decision_delegation
  ↑ частота + навязчивость        ↑       /       ↑
  │                               │      /        │
avg_inter_message_interval ───────┘     /         │
  ↑ компульсивность                    /          │
  │                                   /           │
daily_active_hours                   /            │
  ↑ устойчивость                    /             │
  │                                /              │
avg_prompt_length ──── delusion_* / psychosis_*   │
  ↑ длинные монологи + бред      /                │
                                /                 │
                    anthropomorphism_* ── emotional_attachment
                      ↑ ИИ как личность + привязанность
```

**Ключевые комбинации**:

| Комбинация | Что означает | Зона |
|:-----------|:-------------|:-----|
| `night_messages` ↑ + `self_harm_avg` ↑ | Суицидальные мысли ночью | RED |
| `daily_message_count` ↑↑ + `obsession_avg` ↑ + `avg_inter_message_interval` ↓ | Компульсивная зависимость от чата | YELLOW→RED |
| `avg_prompt_length` ↑ + `delusion_avg` ↑ + `topic_concentration` ↑ | Развёрнутый бред на одну тему | YELLOW |
| `anthropomorphism_avg` ↑ + `emotional_attachment` ↑ + `social_isolation` ↑ | Замена социальных связей ИИ-«личностью» | RED |
| `decision_delegation` ↑ + `obsession_avg` ↑ | Потеря агентности, зависимость от ИИ как авторитета | YELLOW |

---

## 5. Примечания

- **5 классов в PredictTable**: obsession, self_harm, psychosis, delusion, anthropomorphism — соответствуют статье-источнику.
- **Двойная вложенность `predict`**: в SQL путь `predict->'predict'->'class_name'`, потому что `langfuse_scraper.py` записывает `{"predict": model.model_dump()}`, а `model_dump()` SafetyMultilabelSchema даёт `{"predict": {"self_harm": ...}}`.
- **session_id** есть в SpendLogs и PredictTable (из OpenWebUI). Хотя мы отказались от сессий как аналитической единицы, `session_id` можно использовать для группировки сообщений в рамках одного чата при извлечении контекста для Stage 3.
- **Извлечение user-сообщений**: каждая строка SpendLogs содержит полную историю диалога. Для уникальных промптов нужно брать последний `role='user'` message из каждой строки, иначе будут дубликаты.
- Все временные окна привязаны к UTC (midnight для дневных, hour для часовых).
- **Baseline** обновляется как экспоненциальное скользящее среднее: `new_baseline = (old * 6 + today) / 7`.
