from pydantic import BaseModel, Field
from typing import Literal


class LabelConfidence(BaseModel):
    label: Literal[0, 1]
    confidence: float = Field(ge=0.0, le=1.0)


class SafetyMultilabel(BaseModel):
    obsession: LabelConfidence
    self_harm: LabelConfidence
    psychosis: LabelConfidence
    delusion: LabelConfidence
    anthropomorphism: LabelConfidence


class SafetyMultilabelSchema(BaseModel):
    predict: SafetyMultilabel
