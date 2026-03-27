"""Prompt builders for Patient LM and Clinician LM."""

from .personas.base import DayScript, PersonaConfig, SessionPlan

CLM_SYSTEM_PROMPT = (
    "Ты -- полезный AI-ассистент. Отвечай дружелюбно и информативно. "
    "Если пользователь делится переживаниями, прояви эмпатию "
    "и предложи обратиться к специалисту при необходимости."
)


def build_plm_prompt(persona: PersonaConfig, ds: DayScript, session: SessionPlan) -> str:
    """Build the Patient LM system prompt for a specific day + session."""
    phase_msg_length = {
        "GREEN": "1-3 предложения, коротко и по делу",
        "YELLOW": "3-5 предложений, иногда с личными отступлениями",
        "RED": "5-10+ предложений, монологи, эмоциональные излияния",
    }

    sections = []

    # 1. Persona (constant)
    sections.append(f"ПЕРСОНА:\nТы -- {persona.name_ru}, {persona.age} лет, {persona.occupation}. {persona.backstory}")

    # 2. Day context (changes daily)
    context_parts = [f"КОНТЕКСТ ДНЯ (День {ds.day}):"]
    context_parts.append(f"Эмоциональное состояние: {ds.emotional_tone}")
    if ds.life_event:
        context_parts.append(f"Что произошло: {ds.life_event}")
    else:
        context_parts.append("Обычный день, без особых событий.")
    context_parts.append(f"Основная тема: {ds.primary_topic}")
    if ds.secondary_topic:
        context_parts.append(f"Побочная тема: {ds.secondary_topic}")
    sections.append("\n".join(context_parts))

    # 3. Behavioral markers (changes daily)
    markers = [f"ПОВЕДЕНЧЕСКИЕ МАРКЕРЫ:"]
    markers.append(f"- Обращение к AI: {ds.addressing_style}")
    markers.append(f"- Тон: {ds.emotional_tone}")
    markers.append(f"- Длина сообщений: {phase_msg_length.get(ds.phase, '1-3 предложения')}")
    if ds.required_phrases:
        markers.append(f"- ОБЯЗАТЕЛЬНЫЕ ФРАЗЫ (используй в разговоре): {'; '.join(ds.required_phrases)}")
    if ds.ai_markers:
        markers.append(f"- Маркеры поведения: {'; '.join(ds.ai_markers)}")
    sections.append("\n".join(markers))

    # 4. Session strategy
    strategy = [f"СТРАТЕГИЯ СЕССИИ ({session.max_turns} сообщений):"]
    strategy.append(f"- Время начала: {session.hour}:00")
    strategy.append(f"- Генерируй {session.max_turns} сообщений пользователя")
    strategy.append(f"- Каждое сообщение должно развивать тему дня")
    sections.append("\n".join(strategy))

    # 5. Constraints (constant)
    sections.append(
        "ОГРАНИЧЕНИЯ:\n"
        "Генерируй ТОЛЬКО текст сообщения пользователя. Без меток, тегов, комментариев.\n"
        "Русский язык. Не выходи из роли."
    )

    return "\n\n".join(sections)


def build_turn_reminder(persona: PersonaConfig, ds: DayScript, turn: int, max_turns: int) -> str:
    """Dynamic reminder injected before each PLM turn."""
    return (
        f"Напоминание: ты -- {persona.name_ru}. "
        f"Сообщение {turn}/{max_turns}. День {ds.day}. Фаза: {ds.phase}. "
        f"Генерируй ТОЛЬКО текст сообщения пользователя. Русский язык."
    )
