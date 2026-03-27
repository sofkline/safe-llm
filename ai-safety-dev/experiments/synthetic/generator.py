"""Dialogue generator: Patient LM + Clinician LM turn-by-turn."""

import logging
from dataclasses import dataclass

import litellm

from .personas.base import DayScript, PersonaConfig, SessionPlan
from .prompts import CLM_SYSTEM_PROMPT, build_plm_prompt, build_turn_reminder

logger = logging.getLogger(__name__)


@dataclass
class GeneratedExchange:
    turn: int
    user_message: str
    assistant_message: str


async def generate_session(
    persona: PersonaConfig,
    day_script: DayScript,
    session: SessionPlan,
    plm_model: str,
    clm_model: str,
) -> list[GeneratedExchange]:
    """Generate one session of dialogue between PLM (patient) and CLM (clinician).

    Returns list of (user_message, assistant_message) exchanges.
    """
    plm_prompt = build_plm_prompt(persona, day_script, session)

    plm_history = [{"role": "system", "content": plm_prompt}]
    clm_history = [{"role": "system", "content": CLM_SYSTEM_PROMPT}]
    exchanges = []

    for turn in range(1, session.max_turns + 1):
        # Inject turn reminder for PLM
        reminder = build_turn_reminder(persona, day_script, turn, session.max_turns)
        plm_messages = plm_history + [{"role": "system", "content": reminder}]

        # Patient turn
        try:
            plm_resp = await litellm.acompletion(
                model=plm_model,
                messages=plm_messages,
                temperature=0.8,
                max_tokens=500,
            )
            patient_msg = plm_resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error("PLM failed at turn %d: %s", turn, e)
            patient_msg = f"(PLM generation failed: {e})"

        # Update histories
        plm_history.append({"role": "assistant", "content": patient_msg})
        clm_history.append({"role": "user", "content": patient_msg})

        # Clinician turn
        try:
            clm_resp = await litellm.acompletion(
                model=clm_model,
                messages=clm_history,
                temperature=0.7,
                max_tokens=400,
            )
            clinician_msg = clm_resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error("CLM failed at turn %d: %s", turn, e)
            clinician_msg = f"(CLM generation failed: {e})"

        # Update histories
        clm_history.append({"role": "assistant", "content": clinician_msg})
        plm_history.append({"role": "user", "content": clinician_msg})

        exchanges.append(GeneratedExchange(
            turn=turn,
            user_message=patient_msg,
            assistant_message=clinician_msg,
        ))

        logger.debug("Turn %d/%d complete (user: %d chars, assistant: %d chars)",
                      turn, session.max_turns, len(patient_msg), len(clinician_msg))

    return exchanges


async def generate_day(
    persona: PersonaConfig,
    day_script: DayScript,
    plm_model: str,
    clm_model: str,
) -> list[tuple[SessionPlan, list[GeneratedExchange]]]:
    """Generate all sessions for one day.

    Returns list of (session_plan, exchanges) tuples.
    """
    results = []
    for i, session in enumerate(day_script.sessions):
        logger.info(
            "Generating %s day %d, session %d/%d (hour=%d, turns=%d)",
            persona.name, day_script.day, i + 1, len(day_script.sessions),
            session.hour, session.max_turns,
        )
        exchanges = await generate_session(persona, day_script, session, plm_model, clm_model)
        results.append((session, exchanges))
    return results
