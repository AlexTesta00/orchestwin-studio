"""Model-authored profile content, without repeated governance metadata."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestwin.twins.epistemics import ObservationValue

PERSONA_TEXT_LIMIT = 600
PERSONA_ITEM_LIMIT = 6
PERSONA_ITEM_TEXT_LIMIT = 200
PERSONA_REASON_LIMIT = 240


class TwinObservationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_key: str
    value: ObservationValue
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=240)


class PersonaObservationDraft(TwinObservationDraft):
    @field_validator("value")
    @classmethod
    def bounded_content(cls, value):
        if (
            (value.text is not None and len(value.text) > PERSONA_TEXT_LIMIT)
            or len(value.items) > PERSONA_ITEM_LIMIT
            or any(len(item) > PERSONA_ITEM_TEXT_LIMIT for item in value.items)
            or (value.reason is not None and len(value.reason) > PERSONA_REASON_LIMIT)
        ):
            raise ValueError("persona draft content exceeds bounded proposal limits")
        return value


class PersonaProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ordinal: int = Field(strict=True, ge=1)
    name: str = Field(min_length=1, max_length=200)
    observations: tuple[PersonaObservationDraft, ...]


class PersonaModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[PersonaProfileDraft, ...]


class TwinProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_id: UUID
    name: str = Field(min_length=1, max_length=200)
    observations: tuple[TwinObservationDraft, ...]


class UserTwinModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[TwinProfileDraft, ...]
