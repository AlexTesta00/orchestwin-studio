from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.lifecycle import assess_empirical_grounding
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaField,
    PersonaProfile,
    PersonaProfileVersion,
    create_owner_provided_persona,
)
from orchestwin.twins.user_twins import (
    ConfirmedPersonaReference,
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
)


class ReadableClaimStatus(StrEnum):
    EVIDENCED = "EVIDENCED"
    INFERRED = "INFERRED"
    HYPOTHESIZED = "HYPOTHESIZED"
    CONTESTED = "CONTESTED"
    UNKNOWN = "UNKNOWN"


class TwinBasis(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    EVIDENCE_BASED = "EVIDENCE_BASED"


def observation_display_status(observation: ProfileObservation) -> ReadableClaimStatus:
    if observation.value.kind in {ObservationValueKind.UNKNOWN, ObservationValueKind.ABSTAINED}:
        return ReadableClaimStatus.UNKNOWN
    if observation.epistemic_status is EpistemicStatus.CONTESTED:
        return ReadableClaimStatus.CONTESTED
    if observation.epistemic_status is EpistemicStatus.MODEL_INFERRED:
        return ReadableClaimStatus.INFERRED
    if observation.epistemic_status is EpistemicStatus.UNSUPPORTED_ASSUMPTION:
        return ReadableClaimStatus.HYPOTHESIZED
    if observation.epistemic_status in {
        EpistemicStatus.EMPIRICALLY_SUPPORTED,
        EpistemicStatus.HUMAN_VALIDATED,
    } and any(
        reference.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH
        for reference in observation.provenance.references
    ):
        return ReadableClaimStatus.EVIDENCED
    return ReadableClaimStatus.HYPOTHESIZED


def _claim(field: UserTwinField, observation: ProfileObservation | None) -> dict[str, object]:
    return {
        "observation_key": field.observation_key,
        "value": (
            ObservationValue.unknown().to_snapshot()
            if observation is None
            else observation.value.to_snapshot()
        ),
        "display_status": (
            ReadableClaimStatus.UNKNOWN.value
            if observation is None
            else observation_display_status(observation).value
        ),
        "rationale": None if observation is None else observation.rationale,
        "provenance": [] if observation is None else observation.provenance.to_snapshot(),
    }


def twin_view(
    twin: UserTwinProfileVersion, persona: PersonaProfileVersion | None = None
) -> dict[str, object]:
    profile = twin.profile
    claims = {field: _claim(field, profile.observation_for(field)) for field in UserTwinField}
    if (
        profile.observation_for(UserTwinField.DESCRIPTION) is None
        and persona is not None
        and persona.project_id == twin.project_id
        and persona.profile.ready_for_twin_creation
        and ConfirmedPersonaReference.from_version(persona) == profile.persona_reference
    ):
        claims[UserTwinField.DESCRIPTION] = _claim(
            UserTwinField.DESCRIPTION, persona.profile.observation_for(PersonaField.SUMMARY)
        )
    assessment = assess_empirical_grounding(profile)
    basis = (
        TwinBasis.EVIDENCE_BASED
        if assessment.has_empirical_support and not assessment.has_evidence_mismatch
        else TwinBasis.PROVISIONAL
    )
    return {
        "basis": basis.value,
        "represents": claims[UserTwinField.REPRESENTS],
        "does_not_represent": claims[UserTwinField.DOES_NOT_REPRESENT],
        "contexts": claims[UserTwinField.CONTEXT_OF_USE],
        "evidence_gaps": claims[UserTwinField.EVIDENCE_GAPS],
        "empirically_supported_fields": [
            field.value for field in assessment.empirically_supported_fields
        ],
        "unsupported_fields": [
            field.value
            for field, claim in claims.items()
            if claim["display_status"] != ReadableClaimStatus.EVIDENCED.value
        ],
        "persona": {
            "description": claims[UserTwinField.DESCRIPTION],
            "goals": claims[UserTwinField.GOALS],
            "needs": claims[UserTwinField.INFORMATION_NEEDS],
            "behaviours": claims[UserTwinField.RECURRING_TASKS],
            "pain_points": claims[UserTwinField.PAIN_POINTS],
            "constraints": claims[UserTwinField.OPERATIONAL_CONSTRAINTS],
            "contexts": claims[UserTwinField.CONTEXT_OF_USE],
        },
    }


def _input_text(value: str, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds maximum length")
    return normalized


@dataclass(frozen=True, slots=True)
class ArchetypeInput:
    name: str
    description: str
    role: str
    goals: tuple[str, ...] = ()
    context: str | None = None

    def __post_init__(self) -> None:
        for field, maximum in (("name", 200), ("description", 4000), ("role", 4000)):
            object.__setattr__(
                self, field, _input_text(getattr(self, field), label=field, maximum=maximum)
            )
        if not isinstance(self.goals, tuple):
            raise TypeError("goals must be a tuple")
        goals = tuple(_input_text(goal, label="goal", maximum=2000) for goal in self.goals)
        if len(goals) != len(set(goals)):
            raise ValueError("goals must be unique")
        object.__setattr__(self, "goals", goals)
        if self.context is not None:
            object.__setattr__(
                self, "context", _input_text(self.context, label="context", maximum=4000)
            )


def archetype_profile(data: ArchetypeInput, *, source_id: str) -> PersonaProfile:
    source_id = _input_text(source_id, label="source ID", maximum=256)
    values = (
        (PersonaField.ROLE, ObservationValue.from_text(data.role)),
        (PersonaField.SUMMARY, ObservationValue.from_text(data.description)),
        (
            PersonaField.GOALS,
            ObservationValue.from_items(data.goals) if data.goals else ObservationValue.unknown(),
        ),
        (
            PersonaField.CONTEXT_OF_USE,
            ObservationValue.from_text(data.context)
            if data.context is not None
            else ObservationValue.unknown(),
        ),
    )
    return create_owner_provided_persona(
        name=data.name,
        observations=tuple(
            ProfileObservation(
                observation_key=field.observation_key,
                value=value,
                epistemic_status=EpistemicStatus.USER_PROVIDED,
                confidence=ConfidenceScore(
                    0.0 if value.kind is ObservationValueKind.UNKNOWN else 1.0
                ),
                provenance=ObservationProvenance.from_references(
                    (
                        EvidenceReference(
                            source_kind=EvidenceSourceKind.OWNER_INPUT,
                            source_id=source_id,
                            locator=field.observation_key,
                        ),
                    )
                ),
                human_validation=HumanValidationRequirement.NOT_REQUIRED,
            )
            for field, value in values
        ),
    )


def archive_archetype_profile(profile: PersonaProfile) -> PersonaProfile:
    return replace(profile, archived=True)


def archetype_payload(version: PersonaProfileVersion) -> dict[str, object]:
    profile = version.profile
    role = profile.observation_for(PersonaField.ROLE)
    description = profile.observation_for(PersonaField.SUMMARY)
    goals = profile.observation_for(PersonaField.GOALS)
    context = profile.observation_for(PersonaField.CONTEXT_OF_USE)
    return {
        "persona_id": str(version.persona_id),
        "version_id": str(version.id),
        "version_number": version.version_number,
        "name": profile.name,
        "description": None if description is None else description.value.text,
        "role": None if role is None else role.value.text,
        "goals": [] if goals is None else list(goals.value.items),
        "context": None if context is None else context.value.text,
        "source": profile.source.value,
        "confirmation_status": profile.confirmation_status.value,
        "archived": profile.archived,
    }


def active_archetype(version: PersonaProfileVersion) -> bool:
    return (
        not version.profile.archived
        and version.profile.confirmation_status is not PersonaConfirmationStatus.REJECTED
    )


def snapshot_matches_archetypes(
    snapshot: UserModelingSnapshotVersion, versions: tuple[PersonaProfileVersion, ...]
) -> bool:
    active = tuple(version for version in versions if active_archetype(version))
    if any(
        not version.profile.ready_for_twin_creation or version.project_id != snapshot.project_id
        for version in active
    ):
        return False
    current = {
        version.persona_id: (version.id, version.version_number, version.content_hash)
        for version in active
    }
    if len(current) != len(active):
        return False
    cited = {
        version.persona_id: (version.id, version.version_number, version.content_hash)
        for version in snapshot.snapshot.persona_versions
    }
    return current == cited
