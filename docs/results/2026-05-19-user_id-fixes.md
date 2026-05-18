
# Проблема с идентификацией пользователя — итог
#### Исходная проблема
В Langfuse все трейсы имели userId: null или userId: "default_user" — реальный пользователь OpenWebUI не идентифицировался.

#### Что пробовали и почему не сработало
Внешнее подключение (External) — поле API Key есть, но OpenWebUI не пробрасывает X-OpenWebUI-User-Id к внешним подключениям архитектурно. userId оставался null.

Виртуальные ключи LiteLLM — рабочий путь, но требует раздавать ключи каждому пользователю вручную через профиль OpenWebUI, плюс при локальном подключении поля для ключа нет вообще.

Локальное подключение — payload["user"] приходит как "default_user" для всех, реальный UUID не передаётся.

#### Решение которое сработало
Переменная окружения OpenWebUI:
```
text
ENABLE_FORWARD_USER_INFO_HEADERS=True
```
Выставляется в терминале перед запуском OpenWebUI (или в .env). После этого OpenWebUI автоматически добавляет заголовок X-OpenWebUI-User-Id: <uuid> ко всем запросам к LiteLLM.

Фикс в middleware.py — изменён порядок приоритетов при извлечении user_id:
```
python
# БЫЛО:
user_id = raw_headers.get(b"x-openwebui-user-id", b"").decode() or "default_user"

# СТАЛО:
_header_user = raw_headers.get(b"x-openwebui-user-id", b"").decode()
user_id = (
    _header_user                  # 1. заголовок OpenWebUI ← теперь работает
    or payload.get("user", "")    # 2. fallback из тела запроса
    or "anonymous"                # 3. последний fallback
)
```
Фикс в langfuse_scraper.py — убран тестовый хардкод:
```
python
# БЫЛО:
return "playground_user"

# СТАЛО:
return None
```
#### Итоговый результат
```
json
"user_api_key_user_id": "b303ad3b-...",
"end_user": "b303ad3b-..."
```
Реальный UUID пользователя OpenWebUI записывается в Langfuse трейсы и в predict table.