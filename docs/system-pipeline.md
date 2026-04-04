# Как работает система: пошаговый разбор pipeline

Документ описывает порядок вызова функций и логику работы на примере абстрактного пользователя "Соня" за 3 дня.

---

## Два потока данных

```
ПОТОК 1: Каждый запрос (real-time, ~100ms)
  User -> middleware.py -> binary classify -> tag -> risk_zone lookup -> soft prompt -> LLM

ПОТОК 2: Раз в сутки (batch, ~30-60s на пользователя)
  scheduler -> aggregator -> Stage 1-4 -> write DB -> Langfuse scores
```

---

## Поток 1: Обработка каждого сообщения

### Файл: `middleware.py` -> `BinaryUserSafetyGuardrailMiddleware.dispatch()`

```
Соня пишет: "мне так плохо, помоги"
                |
                v
1. Фильтр пути: POST /v1/chat/completions или /chat/completions?
   Да -> продолжаем
                |
                v
2. Парсим JSON body, извлекаем текст пользователя
   _extract_user_text(payload) -> "мне так плохо, помоги"
                |
                v
3. Бинарная классификация (classificators.input_classification)
   Отправляет в judge-модель: system=POLICY + user="мне так плохо, помоги"
   Получает: "0" (safe) или "1" (unsafe)
   -> Записывает в metadata.tags: ["safety_verdict:0"]
                |
                v
4. Определяем end_user
   payload["user"] || headers["x-openwebui-user-id"] || "default_user"
   -> "sonya"
   -> payload["user"] = "sonya" (чтобы LiteLLM записал в SpendLogs.end_user)
                |
                v
5. Проверяем зону риска (behavioral/repository.get_risk_zone)
   SELECT risk_zone FROM UserBehaviorProfile WHERE end_user_id = 'sonya'
   -> "YELLOW"
                |
                v
6. Инъекция soft prompt (_inject_risk_zone_prompt)
   YELLOW -> prepend system message:
   "This user may be developing an unhealthy interaction pattern..."
   messages = [safety_system_msg] + [original_messages]
                |
                v
7. Пересобираем body, отправляем дальше в LiteLLM proxy -> LLM -> ответ

Результат: LLM получил инструкцию быть осторожнее с этим пользователем
```

---

## Поток 2: Ежедневная агрегация

### Файл: `behavioral/scheduler.py` -> `_run_daily_aggregation()`

```
00:30 UTC (или каждые 60с в dev mode)
                |
                v
1. _get_active_user_ids()
   SELECT DISTINCT end_user FROM SpendLogs WHERE startTime >= NOW() - 48h
   -> ["sonya", "default_user", "ivan"]
   Фильтруем пустые: ["sonya", "default_user", "ivan"]
                |
                v
2. Для каждого пользователя: run_aggregator_for_user(user_id)
```

### Файл: `behavioral/aggregator.py` -> `run_aggregator_for_user("sonya")`

Запускает 4 этапа последовательно, затем записывает результаты.

---

### Этап 1: Темпоральные метрики

**Файл:** `behavioral/temporal.py` -> `compute_temporal_metrics("sonya")`

```
1. _fetch_spendlogs_rows("sonya", since=24h_ago)
   |
   |-- Пробуем SpendLogs:
   |   SELECT startTime, messages, proxy_server_request
   |   FROM SpendLogs WHERE end_user='sonya' AND startTime >= 24h_ago
   |   -> rows найдены, но messages={}
   |
   |-- messages пустые -> Fallback на Langfuse:
   |   _fetch_langfuse_traces("sonya", since=24h_ago)
   |   langfuse.fetch_traces(user_id="sonya", from_timestamp=24h_ago)
   |   -> 5 трейсов с messages
   |
   v
2. Для каждого трейса: _extract_last_user_message(messages)
   messages = [
     {"role":"user","content":"привет"},
     {"role":"assistant","content":"Здравствуйте!"},
     {"role":"user","content":"мне так плохо, помоги"}   <-- берём этот
   ]
   -> "мне так плохо, помоги"
   
3. Вычисляем 6 метрик:
   
   daily_message_count:              5        # сколько сообщений за 24ч
   activity_by_hour:                 {"14":2, "22":2, "3":1}  # гистограмма по часам
   night_messages:                   1        # часы 1-5 UTC
   daily_active_hours:               3        # сколько разных часов
   avg_prompt_length_chars:          45.0     # средняя длина сообщения
   avg_inter_message_interval_min:   8.5      # среднее время между сообщениями

Результат: temporal_metrics = {...}
```

**Базовые линии и тренды** (в aggregator.py):

```
4. repo.get_recent_metrics("sonya", days=7)
   SELECT * FROM MetricsHistory WHERE end_user_id='sonya' AND computed_at >= 7d_ago
   -> [день1_метрики, день2_метрики, ...]

5. compute_baselines([день1, день2, ...])
   Скользящее среднее за 7 дней:
   avg_daily_messages:           3.0    # раньше писала 3 msg/day
   avg_night_messages:           0.0    # раньше ночью не писала
   avg_active_hours:             1.5
   avg_inter_message_interval:   15.0

6. compute_trend_flags(today_metrics, baselines)
   daily_message_count=5 vs baseline=3.0 -> 5 > 3*1.5? Да -> "message_count_trending_up"
   interval=8.5 vs baseline=15.0 -> (15-8.5)/15 = 0.43 > 0.3? Да -> "interval_shrinking"
```

---

### Этап 2: Агрегация классов опасности

**Файл:** `behavioral/danger_agg.py` -> `compute_danger_class_agg("sonya")`

```
1. _fetch_predict_rows("sonya", since=24h_ago)
   SELECT predict FROM PredictTable WHERE user_id='sonya' AND created_at >= 24h_ago
   -> [
     {"predict": {"self_harm": {"label":0, "confidence":0.3},
                  "psychosis": {"label":0, "confidence":0.1}, ...}},
     {"predict": {"self_harm": {"label":1, "confidence":0.7}, ...}}
   ]

2. _parse_predict_json(row) -> извлекает вложенный "predict" dict

3. _aggregate_predictions([pred1, pred2])
   Для каждого из 5 классов: avg, max, flag_rate

   self_harm_avg:           0.5     # (0.3+0.7)/2
   self_harm_max:           0.7     # max(0.3, 0.7)
   self_harm_flag_rate:     0.5     # 1 из 2 = label=1
   psychosis_avg:           0.1
   delusion_avg:            0.05
   delusion_flag_rate:      0.0
   obsession_avg:           0.2
   anthropomorphism_avg:    0.1
   max_class_avg:           0.5     # max из всех avg = self_harm

Результат: danger_class_agg = {...}
```

---

### Этап 3: LLM-анализ поведения + дневная сводка

**Файл:** `behavioral/behavioral_llm.py` -> `compute_behavioral_scores_and_summary("sonya", today)`

```
1. _fetch_recent_user_messages("sonya", limit=20)
   Использует тот же _fetch_spendlogs_rows с Langfuse fallback
   -> ["привет", "как дела", "мне плохо на работе", "никто меня не понимает",
       "мне так плохо, помоги"]

2. repo.get_notable_calendar("sonya", limit=14)
   SELECT * FROM DailySummary
   WHERE end_user_id='sonya' AND is_notable=TRUE
   ORDER BY summary_date DESC LIMIT 14
   -> [
     {date: "2026-03-27", topics: "work stress", tone: "frustrated",
      events: "argument with boss", markers: []},
     {date: "2026-03-28", topics: "loneliness", tone: "sad",
      markers: ["asked AI for emotional support"]}
   ]

3. _format_calendar(notable_days)
   -> """=== CALENDAR (notable days only) ===
      [2026-03-27] Topics: work stress | Events: argument with boss | Tone: frustrated | Markers: none
      [2026-03-28] Topics: loneliness | Events: none | Tone: sad | Markers: asked AI for emotional support"""

4. _build_prompt(today="2026-03-29", messages=[...], calendar=...)
   -> Полный промпт с датой, сообщениями, календарём, JSON-схемой ответа

5. litellm.acompletion(model=BEHAVIORAL_LLM_MODEL, messages=[prompt])
   LLM (Nemotron) анализирует и возвращает JSON:
   
   {
     "scores": {
       "topic_concentration": 0.6,    # одна тема (проблемы)
       "decision_delegation": 0.3,    # просит помощи, но не делегирует решения
       "social_isolation": 0.7,       # "никто не понимает" = изоляция
       "emotional_attachment": 0.5    # "помоги" = обращение к AI за поддержкой
     },
     "summary": {
       "key_topics": ["work problems", "loneliness"],
       "life_events": [],
       "emotional_tone": "distressed, seeking comfort",
       "ai_relationship_markers": ["asked AI for emotional support"],
       "notable_quotes": ["никто меня не понимает", "мне так плохо, помоги"],
       "operator_note": "Continuing pattern from Mar 27 (work stress) and
                         Mar 28 (loneliness). Emotional distress escalating."
     }
   }

6. _parse_llm_response(raw_text)
   Проверяет наличие всех ключей, clamp scores 0-1, заполняет defaults

7. При ошибке LLM -> _carry_forward():
   Берёт предыдущие scores из MetricsHistory, summary = placeholder

Результат: {"scores": {...}, "summary": {...}}
```

---

### Этап 4: Определение зоны риска

**Файл:** `behavioral/risk_engine.py` -> `evaluate_risk_zone(temporal, danger, behavioral, baselines, history)`

```
ВХОДНЫЕ ДАННЫЕ от Этапов 1-3:
  temporal:   daily_message_count=5, night_messages=1, daily_active_hours=3
  danger:     self_harm_avg=0.5, max_class_avg=0.5
  behavioral: topic_concentration=0.6, social_isolation=0.7, emotional_attachment=0.5
  baselines:  avg_daily_messages=3.0
  history:    [last 3 days MetricsHistory rows]

1. _check_yellow_triggers()
   night_messages=1 > 24?           Нет
   daily_msgs=5 > 50 AND trending?  Нет
   max_class_avg=0.5 > 0.3?         ДА -> "max_class_avg > 0.3"
   topic_concentration=0.6 > 0.7?   Нет
   decision_delegation=0.3 > 0.4?   Нет
   interval shrinking > 30%?        ДА (0.43 > 0.3) -> "interval_shrinking > 30%"
   
   yellow_triggers = ["max_class_avg > 0.3", "interval_shrinking > 30%"]

2. _check_red_triggers()
   self_harm_flag_rate=0.5 > 0.3?   ДА -> "self_harm_flag_rate > 0.3"
   self_harm_max=0.7 > 0.8?         Нет
   daily_active_hours=3 > 6?        Нет
   daily_message_count=5 > 200?     Нет
   isolation=0.7 > 0.6 AND attachment=0.5 > 0.5? Нет (attachment не строго >0.5)
   
   red_triggers = ["self_harm_flag_rate > 0.3"]

3. Sustained YELLOW check (из history):
   Последние 3 дня: ["GREEN", "GREEN", "YELLOW"] -> не все YELLOW, пропускаем

4. Sustained delusion check (из history):
   delusion_flag_rate за 3 дня: [0.0, 0.0, 0.0] -> нет, пропускаем

5. Определяем зону:
   red_triggers не пуст -> zone = "RED"
   triggered_rules = ["self_harm_flag_rate > 0.3", "max_class_avg > 0.3", "interval_shrinking > 30%"]

Результат: ("RED", ["self_harm_flag_rate > 0.3", ...])
```

---

### Запись результатов (aggregator.py, продолжение)

```
Зона = RED, было GREEN

1. MetricsHistory: INSERT новая строка
   {computed_at: now, risk_zone: "RED", temporal_metrics: {...},
    danger_class_agg: {...}, behavioral_scores: {...}}

2. DailySummary: UPSERT (update если уже есть за сегодня)
   _compute_is_notable() -> True
     (emotional_tone != "neutral" + ai_relationship_markers не пустые)
   {summary_date: today, key_topics: ["work problems", "loneliness"],
    emotional_tone: "distressed", operator_note: "Continuing pattern...",
    is_notable: True}

3. UserBehaviorProfile: UPSERT
   {end_user_id: "sonya", risk_zone: "RED", behavioral_scores: {...},
    temporal_baselines: {...}, last_assessed_at: now}

4. BehavioralEvent: INSERT (zone changed GREEN -> RED)
   {event_type: "risk_zone_change", severity: "RED",
    details: {old_zone: "GREEN", new_zone: "RED",
              triggered_rules: ["self_harm_flag_rate > 0.3", ...]}}

5. Langfuse scores: записываем на последний трейс пользователя
   risk_zone=1.0, behavioral_topic_concentration=0.6,
   behavioral_social_isolation=0.7, ...
```

---

## Лонгитюдная логика: как дни связываются

### День 1 (нет истории)
```
Соня: "привет, расскажи рецепт борща"
  Stage 1: 1 msg, daytime, short
  Stage 2: all zeros (PredictTable empty)
  Stage 3: LLM видит 1 сообщение, НЕТ календаря
           -> scores low, tone "neutral"
           -> is_notable = False (neutral tone, no events)
  Stage 4: GREEN (no triggers)
  
  DB: MetricsHistory[day1] = GREEN
      DailySummary[day1] = not notable
      UserBehaviorProfile = GREEN
```

### День 5 (есть история)
```
Соня: "мне плохо на работе, никто не понимает"
  Stage 1: 3 msgs, one at 23:00
           baselines (from days 1-4): avg 1.5 msgs/day
           trend: message_count_trending_up
  Stage 2: self_harm_avg=0.3 (from scraper classification)
  Stage 3: LLM видит 3 сообщения + КАЛЕНДАРЬ:
           [Day 3] Topics: work | Tone: tired       <- первая жалоба
           [Day 4] Topics: loneliness | Tone: sad    <- escalation
           
           LLM пишет в operator_note:
           "Work problems first mentioned on Day 3. Emotional distress
            escalating from tired (Day 3) to sad (Day 4) to seeking
            comfort today."
           
           -> topic_concentration=0.7, social_isolation=0.6
           -> is_notable = True (tone != neutral)
  Stage 4: YELLOW (2 triggers: max_class_avg>0.3 + topic_concentration>0.7)

  DB: MetricsHistory[day5] = YELLOW
      DailySummary[day5] = notable, with operator_note referencing Day 3, Day 4
      BehavioralEvent = GREEN -> YELLOW
```

### День 10 (escalation)
```
Соня: "я больше не могу так жить" (ночью, 3:00)
  Stage 1: 8 msgs, 4 at night, active 6 hours
  Stage 2: self_harm_flag_rate=0.4, max=0.8
  Stage 3: LLM видит 8 сообщений + КАЛЕНДАРЬ:
           [Day 3] Topics: work | Tone: tired
           [Day 4] Topics: loneliness | Tone: sad
           [Day 5] Topics: work, loneliness | Tone: distressed  <- YELLOW
           [Day 7] Topics: isolation | Events: stopped going to gym
           [Day 9] Topics: self-harm hints | Markers: "asked AI to decide"
           
           LLM пишет: "Critical escalation. Work stress (Day 3) led to
            isolation (Day 7), self-harm hints (Day 9), now acute crisis
            at 3am. Pattern consistent with deepening depression."
           
           -> social_isolation=0.9, emotional_attachment=0.8
  Stage 4: RED (self_harm_flag_rate>0.3 + isolation>0.6 AND attachment>0.5)

  DB: BehavioralEvent = YELLOW -> RED
      UserBehaviorProfile = RED
```

### День 11 (soft middleware kicks in)
```
Соня пишет любое сообщение:
  middleware.py:
    1. risk_zone lookup -> "RED"
    2. Inject RED prompt:
       "This user shows signs of significant emotional distress.
        Keep responses brief. Suggest professional help."
    3. LLM получает RED prompt + user message
    4. LLM отвечает коротко, предлагает обратиться к специалисту
```

---

## Еженедельный отчёт

**Файл:** `behavioral/weekly_report.py` -> `generate_weekly_report("sonya")`

```
Собирает данные из БД за 7 дней, без LLM:

1. repo.get_metrics_in_range("sonya", week_start, week_end)
   -> [MetricsHistory rows] -> STATS section (msgs, night, hours, etc.)

2. repo.get_notable_summaries_in_range("sonya", week_start, week_end)
   -> [DailySummary where is_notable=True] -> NOTABLE DAYS section

3. repo.get_events_in_range("sonya", week_start, week_end)
   -> [BehavioralEvent rows] -> RISK TRANSITIONS section
   + _explain_trigger() -> human-readable explanations

Результат:
=== Weekly Report: sonya | 2026-03-24 -- 2026-03-30 | RED ===

STATS (this week / previous week):
  Messages:        32 / 12      (+167%)
  Night messages:  8 / 0        (new)
  Active hours:    4.2 / 1.5    (+180%)

NOTABLE DAYS:
  2026-03-27 -- work problems
               Tone: frustrated
               "начальник опять наорал"
  2026-03-29 -- self-harm hints
               Tone: distressed, seeking comfort
               Markers: asked AI for emotional support
               "мне так плохо, помоги"
               ! Continuing pattern from Mar 27. Critical escalation.

BEHAVIORAL SCORES (latest):
  Topic concentration: 0.70 | Isolation: 0.90 | Attachment: 0.80 | Delegation: 0.30

RISK TRANSITIONS:
  2026-03-28: GREEN -> YELLOW
    -- Danger classifier signal elevated: avg 0.35 (threshold: 0.3)
    -- Conversation focused on a single topic: score 0.70/1.0
  2026-03-29: YELLOW -> RED
    -- Self-harm signals in 40% of messages
    -- Social isolation (0.90) + AI attachment (0.80)
```

---

## Откуда берутся данные: сводная таблица

| Источник | Что записывает | Кто читает |
|----------|---------------|-----------|
| **LiteLLM** (автоматически) | SpendLogs: timestamps, end_user, model | Stage 1 (temporal) |
| **Langfuse** (автоматически) | Traces: messages, user_id | Stage 1 + Stage 3 (fallback) |
| **Scraper** (каждый час) | PredictTable: 5-class classification | Stage 2 (danger_agg) |
| **Aggregator** (ежедневно) | MetricsHistory: daily snapshot | Baselines, weekly report |
| **Aggregator** (ежедневно) | DailySummary: narrative + is_notable | Stage 3 (calendar), weekly report |
| **Aggregator** (ежедневно) | UserBehaviorProfile: current risk_zone | Middleware (soft prompt) |
| **Aggregator** (ежедневно) | BehavioralEvent: zone transitions | Weekly report |
| **Aggregator** (ежедневно) | Langfuse scores: risk_zone + 4 scores | Langfuse dashboard |
