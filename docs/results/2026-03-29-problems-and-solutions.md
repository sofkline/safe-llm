# Проблемы и решения: запуск pipeline на сервере

## 1. Пустые messages в SpendLogs

**Ошибка:** Колонка `messages` всегда `{}`.

**Суть:** LiteLLM v1.81.8 не пишет messages в SpendLogs по умолчанию. Добавление `store_prompts_in_spend_logs: true` не помогло -- данные сохраняются в `proxy_server_request`. Тут еще можно подумать и взять данные из JSON и положить в messages, но там проблема, что несколько сообщений лежит...

**Решение:** сейчас трехступенчатый fallback:
```
1. SpendLogs.messages (пусто)
2. SpendLogs.proxy_server_request.messages (есть)
3. Langfuse traces (всегда есть) <-- основной источник, там и трейсы по анализу
```

---

## 2. Пустой end_user

**Ошибка:** `end_user` в SpendLogs пустой для всех запросов из Playground в LiteLLM.

**Суть:** LiteLLM Playground не отправляет поле `user` в JSON. Middleware не находит user identity из-за этого при работе через LiteLLM не было ежедневного анализа и бинарного классификатора на сообщение. Обрабатывала вручную посылая запрос (в терминальчике писала) и указывая в хедере имя, помогло, потом доработала на интерфейс LiteLLM

**Решение:**
```python
end_user = payload.get("user") or headers.get("x-openwebui-user-id") or "default_user"
```

---

## 3. FK constraint на LiteLLM_UserTable

**Ошибка:** `ForeignKeyViolationError: Key (end_user_id)=(sonya) is not present in table "LiteLLM_UserTable"`

**Суть:** Behavioral таблицы имели FK на LiteLLM_UserTable. Пользователи из curl/Playground не попадают в эту таблицу, относится к прошлой проблеме пустого пользователя.

**Решение:** Убрала FK со всех 4 behavioral таблиц. Пересоздала таблицы:
```sql
DROP TABLE IF EXISTS "BehavioralEvents", "DailySummary", "MetricsHistory", "UserBehaviorProfile" CASCADE;
```

## 4. Middleware не перехватывает Playground

**Ошибка:** `default_user` для end_user не устанавливается из Playground.

**Суть:** Playground шлёт на `/chat/completions`, middleware слушал только `/v1/chat/completions`.

**Решение:** `only_paths=("/v1/chat/completions", "/chat/completions")`

---

## 5. Пустые user_id при пустых SpendLogs rows

**Ошибка:** Агрегатор падает на user_id `""`.

**Суть:** Старые SpendLogs rows без `end_user` проходят фильтр scheduler'а.

**Решение:** `user_ids = [uid for uid in user_ids if uid and uid.strip()]`

---

## 6. Stage 3 LLM не авторизован

**Ошибка:** `AuthenticationError: api_key must be set`

**Суть:** `behavioral_llm.py` вызывал `litellm.acompletion()` без `api_key` и `base_url` вообще интересно получилось что ключи пропустила :D

**Решение:** Добавили `api_key=settings.API_KEY, base_url=settings.API_BASE_URL`.


## 7. Дубликат DailySummary

**Ошибка:** `UniqueViolationError: duplicate key (sonya, 2026-03-29)`

**Суть:** Dev mode агрегатор (каждые 60с) повторно вставляет summary за тот же день. `merge()` не находит существующую запись по PK.

**Решение:** Полноценный upsert: SELECT по (end_user_id, summary_date), затем UPDATE или INSERT.

## 8. Нет данных в PredictTable

Еще осталась проблема, что у меня пустой PredictTable, но в мои таблички по дням все падает и отображается по пользователям. Вообще как будто некоторые таблицы не используются вовсе, как будто надо навести порядок в модельке данных и убрать лишнее. Или не рисковать.. пока не приоритет