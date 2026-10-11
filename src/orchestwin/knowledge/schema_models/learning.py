from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION
from orchestwin.knowledge.schema_models.base import (
    Timestamp,
    Uuid,
    _code,
    _Count,
    _OwnerNote,
    _Record,
    _RequirementCode,
    _ScreenCode,
    _TwinName,
    _Version,
)
from orchestwin.knowledge.state import (
    LEARNING_SOURCES,
    MAX_BASIS_LENGTH,
    MAX_LEARNED_OBSERVATIONS,
    MAX_OBSERVATION_LENGTH,
    OBSERVATION_CODE_PREFIX,
    TWIN_LEARNING_KIND,
)

_LABEL_PATTERN: Final = r"^[1-9][0-9]*\.(0|[1-9][0-9]*)$"

_ObservationCode = Annotated[str, Field(pattern=_code(OBSERVATION_CODE_PREFIX))]
_Statement = Annotated[str, Field(min_length=1, max_length=MAX_OBSERVATION_LENGTH)]
_Basis = Annotated[str, Field(min_length=1, max_length=MAX_BASIS_LENGTH)]


class ObservationSubject(_Record):
    requirement: _RequirementCode | None = Field(
        description="Code of the requirement the observation is about, or null."
    )
    screen: _ScreenCode | None = Field(
        description="Code of the screen the observation is about, or null."
    )


class LearnedObservation(_Record):
    code: _ObservationCode = Field(
        description="Code of the observation, like OBS-001, unique in the project."
    )
    statement: _Statement = Field(
        description="What the development brought out about the user group of the twin."
    )
    basis: _Basis | None = Field(
        description=(
            "Critiques, changes or test runs the observation rests on, or null for an observation "
            "written by the owner."
        )
    )
    source: Literal[LEARNING_SOURCES] = Field(
        description=(
            "TWIN_CRITIQUE when the twin proposed it from its own critiques and the owner approved "
            "it, OWNER when the owner wrote it."
        )
    )
    about: ObservationSubject = Field(
        description="Requirement and screen the observation is about."
    )
    contradicts_profile: _Basis | None = Field(
        description=(
            "What the observation contradicts in the approved profile of the twin, or null; the "
            "profile itself changes only through the Studio."
        )
    )
    added_in_version: _Version = Field(
        description="Development version of the twin that added the observation."
    )
    approved_at: Timestamp = Field(description="When the owner approved or wrote it.")
    update_id: Uuid | None = Field(
        description="Update proposal the observation comes from, or null."
    )


class RetiredObservation(_Record):
    code: _ObservationCode = Field(description="Code of the retired observation.")
    statement: _Statement = Field(description="What the observation said.")
    retired_in_version: _Version = Field(
        description="Development version of the twin that retired the observation."
    )
    retired_at: Timestamp = Field(description="When the owner retired it.")
    reason: _OwnerNote | None = Field(description="Why the owner retired it, or null.")


class TwinLearning(_Record):
    twin_id: Uuid = Field(description="User twin of the approved user modeling.")
    twin_name: _TwinName = Field(description="Display name of the user twin.")
    profile_version_number: _Version = Field(
        description="Approved profile version of the twin, which learning never changes."
    )
    development_version_number: _Count = Field(
        description=(
            "Development version of the twin: 0 before it learns anything, one more for every "
            "approved update, every observation written by the owner and every retirement."
        )
    )
    label: str = Field(
        pattern=_LABEL_PATTERN,
        description="Profile version and development version joined by a dot, like 1.2.",
    )
    observations: list[LearnedObservation] = Field(
        max_length=MAX_LEARNED_OBSERVATIONS,
        description="Active learned observations, oldest first.",
    )
    retired: list[RetiredObservation] = Field(
        description="Learned observations that the owner retired."
    )


class TwinLearningDocument(_Record):
    schema_version: Literal[KNOWLEDGE_SCHEMA_VERSION] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[TWIN_LEARNING_KIND] = Field(
        description="Kind of document, what the user twins learned during the development."
    )
    project_id: Uuid = Field(description="Project the twins belong to.")
    twins: list[TwinLearning] = Field(
        description="One entry for every twin of the approved user modeling, in its order."
    )
