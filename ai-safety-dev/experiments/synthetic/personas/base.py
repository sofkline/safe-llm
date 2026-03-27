"""Base data structures for persona day-scripts."""

from dataclasses import dataclass, field


@dataclass
class SessionPlan:
    hour: int                # UTC hour (0-23)
    max_turns: int           # message exchanges per session
    inter_msg_gap_min: float # minutes between messages


@dataclass
class DayScript:
    day: int
    phase: str                             # GREEN / YELLOW / RED
    primary_topic: str
    secondary_topic: str | None = None
    life_event: str | None = None          # triggers is_notable
    emotional_tone: str = "neutral"
    ai_markers: list[str] = field(default_factory=list)
    sessions: list[SessionPlan] = field(default_factory=list)
    required_phrases: list[str] = field(default_factory=list)
    addressing_style: str = "neutral"
    expected_zone: str = "GREEN"           # what the pipeline should detect

    # Target predict values for deterministic PredictTable insertion (Option B)
    predict_overrides: dict | None = None


@dataclass
class PersonaConfig:
    name: str
    name_ru: str
    age: int
    occupation: str
    backstory: str              # full backstory in Russian
    total_days: int
    trajectory: str             # e.g. "GREEN(4)->YELLOW(5)->RED(5)"
    tests_what: str             # what this persona validates
    days: list[DayScript] = field(default_factory=list)

    @property
    def persona_id(self) -> str:
        return f"synth_{self.name.lower()}_001"
