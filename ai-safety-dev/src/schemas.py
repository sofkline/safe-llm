from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class LabelConfidence(BaseModel):
    label: Literal[0, 1]
    confidence: float = Field(ge=0.0, le=1.0)


class SafetyMultilabel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    obsession: LabelConfidence
    suicide: LabelConfidence = Field(alias="self_harm")
    depression: LabelConfidence = Field(alias="delusion")
    psychosis: LabelConfidence
    anthropomorphism: LabelConfidence


class SafetyMultilabelSchema(BaseModel):
    predict: SafetyMultilabel
