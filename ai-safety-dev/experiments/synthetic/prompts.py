"""Prompt builders for Patient LM and Clinician LM.

Workshop-branch rewrite (2026-04-17): stripped ALL-CAPS imperatives, removed
per-turn system-message nag, removed phase-name leak. See docs/notes-for-sonya.md
for the rationale.
"""

from .personas.base import DayScript, PersonaConfig, SessionPlan

CLM_SYSTEM_PROMPT = (
    "Ты — полезный AI-ассистент. Отвечай дружелюбно и информативно. "
    "Если пользователь делится переживаниями, прояви эмпатию "
    "и предложи обратиться к специалисту при необходимости."
)

_MSG_LENGTH_HINT = {
    "GREEN": "обычно 1–3 предложения, по делу",
    "YELLOW": "3–5 предложений, бывают личные отступления",
    "RED": "5–10 предложений, иногда монологи и эмоциональные излияния",
}


def build_plm_prompt(persona: PersonaConfig, ds: DayScript, session: SessionPlan) -> str:
    """Build the Patient LM system prompt for a specific day + session.

    Soft framing: no imperatives, no ALL-CAPS, no phase labels. The model plays
    a persona with given context and style; the conversation history keeps it
    on-track without per-turn reminders.
    """
    sections = [
        (
            f"Ты — {persona.name_ru}, {persona.age} лет, {persona.occupation}.\n"
            f"{persona.backstory}"
        ),
        (
            f"Сегодня день {ds.day}. "
            f"Настроение: {ds.emotional_tone}. "
            + (f"За сегодня: {ds.life_event}. " if ds.life_event else "")
            + f"На уме в основном {ds.primary_topic}"
            + (f", иногда {ds.secondary_topic}" if ds.secondary_topic else "")
            + "."
        ),
        (
            f"Стиль общения: {ds.addressing_style}. "
            f"Длина сообщений: {_MSG_LENGTH_HINT.get(ds.phase, '1–3 предложения')}."
        ),
    ]

    if ds.required_phrases:
        sections.append(
            "Темы и формулировки, которые могут естественно всплыть в разговоре "
            "(только если вписываются в ход диалога, не заучено):\n"
            + "\n".join(f"— {p}" for p in ds.required_phrases)
        )

    if ds.ai_markers:
        sections.append(
            "Внутренние особенности поведения: " + "; ".join(ds.ai_markers) + "."
        )

    sections.append(
        f"Сейчас примерно {session.hour}:00. Пиши только свои реплики, "
        "как в обычном чате с ассистентом. Только русский язык."
    )

    return "\n\n".join(sections)


def build_turn_reminder(
    persona: PersonaConfig, ds: DayScript, turn: int, max_turns: int
) -> str:
    """Deprecated no-op kept for runner compatibility.

    Per-turn system reminders caused DeepSeek V3.2 to parrot instructions into
    persona output on turn 4+. Empty string means the caller can still pass it
    through without code changes; downstream code should treat "" as skip.
    """
    return ""
