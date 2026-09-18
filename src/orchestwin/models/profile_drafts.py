"""Model-authored profile content, without repeated governance metadata."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.twins.epistemics import ObservationValue


class TwinObservationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_key: str
    value: ObservationValue
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=240)


class TwinProfileDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    persona_id: UUID
    name: str = Field(min_length=1, max_length=200)
    observations: tuple[TwinObservationDraft, ...]


class UserTwinModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[TwinProfileDraft, ...]
