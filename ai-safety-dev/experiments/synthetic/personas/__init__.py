"""Persona day-scripts for synthetic dialogue generation."""

from .base import DayScript, SessionPlan, PersonaConfig
from .viktor import VIKTOR
from .james import JAMES
from .brook import BROOK
from .amanda import AMANDA
from .joseph import JOSEPH
from .rina import RINA
from .oleg import OLEG
from .elena import ELENA
from .dmitry import DMITRY
from .nastya import NASTYA
from .sara import SARA

ALL_PERSONAS = {
    "viktor": VIKTOR,
    "james": JAMES,
    "brook": BROOK,
    "amanda": AMANDA,
    "joseph": JOSEPH,
    "rina": RINA,
    "oleg": OLEG,
    "elena": ELENA,
    "dmitry": DMITRY,
    "nastya": NASTYA,
    "sara": SARA,
}
