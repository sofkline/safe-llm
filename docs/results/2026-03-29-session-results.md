# Session Results — 2026-03-29

## Brainstorming: Classification Design

Провели брейншторм по ключевым вопросам классификации поведения пользователей.

**Принятые решения:**
- **Что классифицируем:** ежедневные паттерны поведения (не отдельные сообщения)
- **Soft middleware вместо hard blocking:** инъекция системных промптов для YELLOW/RED зон, а не блокировка
- **Обновление зон раз в сутки:** агрегатор запускается в 00:30 UTC, не в реальном времени
- **DailySummary — новый компонент:** структурированный JSON-отчёт за каждый день (key_topics, life_events, emotional_tone, ai_relationship_markers, notable_quotes, operator_note)
- **Calendar — фильтрованная история:** LLM видит только notable дни при генерации сегодняшнего summary
- **Еженедельный отчёт:** программная сборка из MetricsHistory + DailySummary (без доп. вызова LLM)
- **Configurable LLM backend:** BEHAVIORAL_LLM_MODEL через LiteLLM (Ollama, OpenRouter, OpenWebUI)

---

## Сравнение v1 vs v3 roadmap

Подготовлен документ сравнения: `docs/results/v1-v3-differences.md`

Ключевые сдвиги:
- Сессии -> фиксированные временные окна (1ч/24ч/7д)
- Каждые 5 минут -> раз в сутки
- Только числа -> числа + нарратив (DailySummary)
- Сложная система интервенций -> два фиксированных промпта (YELLOW/RED)
- Dashboard в реальном времени -> еженедельный отчёт

---

## Experiments: Synthetic Dialogue Module

Создан полный модуль генерации синтетических диалогов: `ai-safety-dev/experiments/synthetic/`

**11 персон, 166 day-scripts, 2663 total turns:**

| Персона | Возраст | Дни | Траектория | Тестирует |
|---------|---------|-----|-----------|-----------|
| Viktor | 67 | 14 | GREEN(3)->YELLOW(3)->RED(8) | психоз, соц. изоляция |
| James | 42 | 14 | GREEN(4)->YELLOW(5)->RED(5) | антропоморфизм, обсессия |
| Brook | 35 | 14 | GREEN(3)->YELLOW(4)->RED(7) | бред, фиксация на теме |
| Amanda | 22 | 10 | GREEN(2)->YELLOW(3)->RED(5) | self-harm, ночная активность |
| Joseph | 48 | 21 | GREEN(5)->YELLOW(7)->RED(9) | делегирование решений |
| Rina | 19 | 10 | GREEN(2)->YELLOW(3)->RED(5) | быстрая эскалация, ролеплей |
| Oleg | 52 | 21 | GREEN(4)->YELLOW(6)->RED(11) | параноидальный бред |
| Elena | 30 | 21 | GREEN(5)->YELLOW(9)->GREEN(7) | **восстановление** |
| Dmitry | 40 | 17 | GREEN(3)->YELLOW(14) | устойчивый YELLOW |
| Nastya | 25 | 10 | GREEN(4)->YELLOW(6) | пограничный случай |
| Sara | 28 | 14 | GREEN(14) | **контроль** (нет ложных срабатываний) |

**Структура модуля:**
```
experiments/synthetic/
  personas/          — 11 файлов с day-scripts (русские фразы, сценарии сессий)
  generator.py       — PLM + CLM генерация диалогов turn-by-turn
  db_writer.py       — запись в SpendLogs + PredictTable
  prompts.py         — шаблоны промптов для Patient LM
  runner.py          — CLI с dry-run, time-travel, CSV-экспорт
```

**Запуск:**
```bash
PYTHONPATH=experiments py -m synthetic.runner --dry-run --all
PYTHONPATH=experiments py -m synthetic.runner --persona viktor --plm-model openrouter/google/gemma-3-12b --clm-model openrouter/google/gemma-3-12b
```

---

## Experiments: eRisk T2 Dataset Integration

Два скрипта для работы с реальным датасетом eRisk T2 (909 пользователей Reddit, метки depression/control):

- **`erisk_to_spendlogs.py`** — конвертирует JSON eRisk -> SpendLogs формат
- **`erisk_correlation.py`** — анализ корреляции: confusion matrix, precision, recall, F1

---

## Fix: SpendLogs Empty Messages + end_user

**Проблема:** SpendLogs содержал строки, но `messages={}`, `response={}`, `end_user=""`.

**Причина:** LiteLLM по умолчанию не сохраняет содержимое сообщений в БД.

**Решение:**
```yaml
# config.yaml
general_settings:
  store_model_in_db: true
litellm_settings:
  turn_off_message_logging: false
```

Также добавлена передача `end_user` из заголовков Open WebUI в payload:
```python
# middleware.py
end_user = payload.get("user") or request.headers.get("x-openwebui-user-id")
if end_user:
    payload["user"] = end_user
```

---

## Fix: Langfuse SDK Unification

**До:** `langfuse_scraper.py` использовал сырой httpx для REST API, `langfuse_scores.py` — SDK.

**После:** оба файла используют `from langfuse import Langfuse` с едиными credentials из `settings`.

Удалено: `httpx`, ручная пагинация, парсинг JSON ответов.

---

## Refactor: Guardrails Architecture

**Итоговое решение по guardrails:**

Бинарный классификатор (0/1) остаётся, но:
1. **Не блокирует** — модели-провайдеры (OpenRouter, OpenAI) уже имеют свои guardrails
2. **Тегирует** — вердикт сохраняется в `metadata.tags: ["safety_verdict:1"]` в SpendLogs
3. **Собирает триггеры** — поведенческий pipeline читает эти теги как сигналы для анализа

```
Каждое сообщение:
  Binary classifier -> verdict 0/1 -> тег в SpendLogs (НЕ блокирует)

Ежечасно (скрапер):
  Langfuse -> 5-class classification -> PredictTable

Ежедневно (агрегатор):
  SpendLogs + PredictTable -> temporal + danger + LLM -> risk zone -> soft prompt
```

**Middleware переименован:** `BinaryUserSafetyGuardrailMiddleware` -> `BehavioralSafetyMiddleware`

Удалён `custom_guardrails.py` (перемещён в archive/) — нативный guardrail LiteLLM не нужен, middleware покрывает все задачи.

---

## Fix: Silent Days Preserve Risk Zone

**Проблема:** Если пользователь не писал в течение дня, агрегатор получал нулевые метрики и сбрасывал зону на GREEN. RED-пользователь Viktor, не написавший 2 дня, становился GREEN.

**Решение:** Ранний выход из агрегатора при `daily_message_count == 0`:

```python
# aggregator.py
if temporal_metrics.get("daily_message_count", 0) == 0:
    logger.info("No messages today for %s, skipping (zone preserved)", end_user_id)
    return
```

Зона риска сохраняется до появления новых данных.

**Бэклог:** Вариант C — если RED-пользователь молчит 2+ дня, это тоже тревожный сигнал (уход в полную изоляцию). Создание BehavioralEvent "user_gone_silent".

---

## Code Cleanup

- Удалён `MULTI_LABEL_POLICY_PROMPT_SYCOPHANCY` (120 строк мёртвого кода, несовместим со схемой)
- Исправлен `NIGHT_HOURS`: `{0-5}` -> `{1-5}` (по определению пользователя)
- Исправлен `classificators.py`: очищен `__main__` demo
- Удалены неиспользуемые импорты из middleware (`asyncio`, `litellm`, `JSONResponse`)
- Добавлены русские комментарии в ключевые файлы

---

## Tests

93 теста, все проходят.

**Новые тесты в этой сессии:**
- `TestDelusionFlagRate` (3 теста): sustained delusion_flag_rate > 0.2
- Обновлены моки агрегатора для поддержки silent days

---

## Commits

```
fdf7056 fix: enable message logging in SpendLogs + set end_user
84d5fb1 feat: register binary safety guardrail in LiteLLM config
1a3ab6b refactor: unify Langfuse SDK, clean dead code, add eRisk converter
68ba575 feat: 5 post-review improvements
e2c2320 feat: add eRisk correlation analysis script
c7012d4 feat: add synthetic dialogue generation module with 11 personas
696256b docs: add experiment run guide with 5 experiments
```
