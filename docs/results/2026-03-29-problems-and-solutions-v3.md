# Проблемы и решения: запуск pipeline на сервере

10 проблем при первом реальном запуске. Все решены.

---

## 1. Несовместимость datetime (TIMESTAMP WITHOUT TIME ZONE)

**Ошибка:** `can't subtract offset-naive and offset-aware datetimes`

**Суть:** PostgreSQL SpendLogs хранит `startTime` как `TIMESTAMP WITHOUT TIME ZONE`. Код передавал `datetime.now(UTC)` (с таймзоной). asyncpg не может сравнить.

**Решение:** `datetime.now(UTC)` -> `datetime.utcnow()` во всех SQL-запросах к SpendLogs и PredictTable.

---

## 2. Пустые messages в SpendLogs

**Ошибка:** Колонка `messages` всегда `{}`.

**Суть:** LiteLLM v1.81.8 не пишет messages в SpendLogs по умолчанию. Добавление `store_prompts_in_spend_logs: true` не помогло -- данные сохраняются в `proxy_server_request`, но не всегда.

**Решение:** Трёхступенчатый fallback:
```
1. SpendLogs.messages (пусто)
2. SpendLogs.proxy_server_request.messages (иногда есть)
3. Langfuse traces (всегда есть) <-- основной источник
```

---

## 3. Пустой end_user

**Ошибка:** `end_user` в SpendLogs пустой для всех запросов из Playground.

**Суть:** LiteLLM Playground не отправляет поле `user` в JSON. Middleware не находит user identity.

**Решение:**
```python
end_user = payload.get("user") or headers.get("x-openwebui-user-id") or "default_user"
```

---

## 4. FK constraint на LiteLLM_UserTable

**Ошибка:** `ForeignKeyViolationError: Key (end_user_id)=(sonya) is not present in table "LiteLLM_UserTable"`

**Суть:** Behavioral таблицы имели FK на LiteLLM_UserTable. Пользователи из curl/Playground не попадают в эту таблицу.

**Решение:** Убрали FK со всех 4 behavioral таблиц. Пересоздали таблицы:
```sql
DROP TABLE IF EXISTS "BehavioralEvents", "DailySummary", "MetricsHistory", "UserBehaviorProfile" CASCADE;
```

---

## 5. Stage 3 LLM не авторизован

**Ошибка:** `AuthenticationError: api_key must be set`

**Суть:** `behavioral_llm.py` вызывал `litellm.acompletion()` без `api_key` и `base_url`.

**Решение:** Добавили `api_key=settings.API_KEY, base_url=settings.API_BASE_URL`.

---

## 6. Неверное имя модели

**Ошибка:** `LLM Provider NOT provided. You passed model=gemma3-vpn1`

**Суть:** `gemma3-vpn1` -- alias в LiteLLM proxy, не полное имя модели. При прямом вызове `litellm.acompletion()` нужен формат `provider/model`.

**Решение:** Default модель: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`.

---

## 7. Дубликат DailySummary

**Ошибка:** `UniqueViolationError: duplicate key (sonya, 2026-03-29)`

**Суть:** Dev mode агрегатор (каждые 60с) повторно вставляет summary за тот же день. `merge()` не находит существующую запись по PK.

**Решение:** Полноценный upsert: SELECT по (end_user_id, summary_date), затем UPDATE или INSERT.

---

## 8. Middleware не перехватывает Playground

**Ошибка:** `default_user` не устанавливается из Playground.

**Суть:** Playground шлёт на `/chat/completions`, middleware слушал только `/v1/chat/completions`.

**Решение:** `only_paths=("/v1/chat/completions", "/chat/completions")`

---

## 9. Пустые user_id при пустых SpendLogs rows

**Ошибка:** Агрегатор падает на user_id `""`.

**Суть:** Старые SpendLogs rows без `end_user` проходят фильтр scheduler'а.

**Решение:** `user_ids = [uid for uid in user_ids if uid and uid.strip()]`

---

## 10. Ночные часы не совпадают с тестами

**Ошибка:** Тест ожидал 4 night messages, получил 2.

**Суть:** `NIGHT_HOURS` был `{0,1,2,3,4,5}`, тест использовал часы 22,23,0,1. Определение пользователя: ночь = 1:00-5:59.

**Решение:** `NIGHT_HOURS = {1, 2, 3, 4, 5}`

---

## Главный вывод

```
SpendLogs:  timestamps + end_user (надёжно)
            messages (НЕНАДЁЖНО -- пустые в LiteLLM v1.81.8)

Langfuse:   messages + response (надёжно, ВСЕГДА есть)
            userId (надёжно, если middleware установил)

-> Langfuse -- основной источник сообщений для pipeline.
```
