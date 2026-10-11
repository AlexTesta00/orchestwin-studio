from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    ArtifactReference,
    CatalogReference,
    EvidenceReference,
    Sha256,
    Timestamp,
    Uuid,
    _Confidence,
    _Record,
    _Version,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    HumanValidationRequirement,
    ObservationValueKind,
)
from orchestwin.twins.personas import (
    PERSONA_PROFILE_SCHEMA_VERSION,
    PersonaConfirmationStatus,
    PersonaKind,
    PersonaSource,
)
from orchestwin.twins.user_twins import (
    USER_MODELING_SNAPSHOT_SCHEMA_VERSION,
    USER_TWIN_PROFILE_SCHEMA_VERSION,
    UserTwinLifecycleStatus,
)

_OBSERVATION_KEY_PATTERN: Final = r"^[a-z][a-z0-9_.-]{0,127}$"


class ObservationValue(_Record):
    kind: Annotated[ObservationValueKind, _BY_VALUE] = Field(
        description="Shape of the value: one text, a list of items, unknown or an abstention."
    )
    text: str | None = Field(description="The value when kind is TEXT, otherwise null.")
    items: list[str] = Field(description="The values when kind is ITEMS, otherwise empty.")
    reason: str | None = Field(
        description="Why the model abstained when kind is ABSTAINED, otherwise null."
    )


class ProfileObservation(_Record):
    observation_key: str = Field(
        pattern=_OBSERVATION_KEY_PATTERN,
        description="Stable key of the profile field, such as persona.goals or user_twin.goals.",
    )
    value: ObservationValue = Field(description="Observed value of the profile field.")
    epistemic_status: Annotated[EpistemicStatus, _BY_VALUE] = Field(
        description="How the value is known, from owner input to unsupported assumption."
    )
    confidence: _Confidence = Field(description="Confidence in the value, between 0 and 1.")
    provenance: list[EvidenceReference] = Field(
        description="Sources that support the value, in the order they were given."
    )
    human_validation: Annotated[HumanValidationRequirement, _BY_VALUE] = Field(
        description="Whether a person still has to validate the value."
    )
    rationale: str | None = Field(
        description="Reasoning behind an inferred or assumed value, or null."
    )


class PersonaProfile(_Record):
    archived: bool = False
    schema_version: Literal[PERSONA_PROFILE_SCHEMA_VERSION] = Field(
        description="Version of the persona profile format."
    )
    name: str = Field(description="Display name of the persona.")
    source: Annotated[PersonaSource, _BY_VALUE] = Field(
        description="Whether the owner provided the persona or the system proposed it."
    )
    kind: Annotated[PersonaKind, _BY_VALUE] = Field(
        description="Whether the profile is an owner persona or a proto-persona."
    )
    confirmation_status: Annotated[PersonaConfirmationStatus, _BY_VALUE] = Field(
        description="Owner confirmation state of the persona."
    )
    rejection_reason: str | None = Field(
        description="Why the owner rejected the persona, or null when it was not rejected."
    )
    observations: list[ProfileObservation] = Field(
        description="Fields of the persona with their epistemic metadata."
    )


class PersonaVersion(_Record):
    id: Uuid = Field(description="Identifier of this persona version.")
    project_id: Uuid = Field(description="Project the persona belongs to.")
    persona_id: Uuid = Field(description="Stable identifier of the persona across its versions.")
    version_number: _Version = Field(description="Version number of the persona.")
    based_on_version_number: _Version | None = Field(
        description="Version that this version revises, or null for the first version."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the persona profile.")
    profile: PersonaProfile = Field(description="Content of the persona at this version.")
    created_by_user_id: Uuid = Field(description="User who created this version.")
    created_at: Timestamp = Field(description="When this version was created.")


class PersonaReference(_Record):
    persona_id: Uuid = Field(description="Stable identifier of the persona.")
    version_number: _Version = Field(description="Confirmed persona version the twin uses.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that persona version.")
    source: Annotated[PersonaSource, _BY_VALUE] = Field(
        description="Whether the owner provided the persona or the system proposed it."
    )
    kind: Annotated[PersonaKind, _BY_VALUE] = Field(
        description="Whether the persona is an owner persona or a proto-persona."
    )
    confirmation_status: Annotated[PersonaConfirmationStatus, _BY_VALUE] = Field(
        description="Confirmation state of the persona, always confirmed for a twin."
    )


class UserTwinProfile(_Record):
    schema_version: Literal[USER_TWIN_PROFILE_SCHEMA_VERSION] = Field(
        description="Version of the user twin profile format."
    )
    name: str = Field(description="Display name of the user twin.")
    persona_reference: PersonaReference = Field(
        description="Confirmed persona version the twin is grounded on."
    )
    project_brief_reference: ArtifactReference = Field(
        description="Approved project brief version the twin was built from."
    )
    agent_team_reference: ArtifactReference = Field(
        description="Approved agent team version the twin was built with."
    )
    catalog: CatalogReference = Field(description="Agent catalog used when the twin was built.")
    validation_status: Annotated[UserTwinLifecycleStatus, _BY_VALUE] = Field(
        description="Lifecycle and validation state of the twin."
    )
    requires_human_validation: bool = Field(
        description="True when at least one observation still needs human validation."
    )
    observations: list[ProfileObservation] = Field(
        description="Fields of the twin, such as role, goals and frustrations, in canonical order."
    )


class UserTwinVersion(_Record):
    id: Uuid = Field(description="Identifier of this user twin version.")
    project_id: Uuid = Field(description="Project the user twin belongs to.")
    twin_id: Uuid = Field(description="Stable identifier of the user twin across its versions.")
    version_number: _Version = Field(description="Version number of the user twin.")
    based_on_version_number: _Version | None = Field(
        description="Version that this version revises, or null for the first version."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the user twin profile.")
    profile: UserTwinProfile = Field(description="Content of the user twin at this version.")
    created_by_user_id: Uuid = Field(description="User who created this version.")
    created_at: Timestamp = Field(description="When this version was created.")


class UserModelingSnapshot(_Record):
    schema_version: Literal[USER_MODELING_SNAPSHOT_SCHEMA_VERSION] = Field(
        description="Version of the user modeling snapshot format."
    )
    project_id: Uuid = Field(description="Project the personas and twins belong to.")
    project_brief_reference: ArtifactReference = Field(
        description="Approved project brief version every twin was built from."
    )
    agent_team_reference: ArtifactReference = Field(
        description="Approved agent team version every twin was built with."
    )
    catalog: CatalogReference = Field(description="Agent catalog shared by every twin.")
    persona_versions: list[PersonaVersion] = Field(
        description="One confirmed persona version for each twin, ordered by persona identifier."
    )
    twin_versions: list[UserTwinVersion] = Field(
        description="User twin versions ordered by twin identifier."
    )
