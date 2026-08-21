"""Canonical serialization boundaries for governed Design Packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.artifacts.design import (
    DesignApproach,
    DesignCritiqueKind,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.artifacts.design_packages import (
    DESIGN_PACKAGE_SCHEMA_VERSION,
    DesignExplorationPackage,
    DesignGrounding,
    create_design_concern,
    create_design_exploration_package,
)
from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignPackageChange,
    DesignPackageDiff,
    DesignPackageDiffStatus,
)
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.projects.requirements_primitives import UserTwinVersionReference
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
)

DESIGN_PACKAGE_DIFF_SCHEMA_VERSION: Final = 1


def design_package_from_snapshot(
    payload: Mapping[str, object],
) -> DesignExplorationPackage:
    """Reconstruct and validate one complete canonical Design Package."""
    schema_version = _integer(
        _required(payload, "schema_version"),
        label="Design Package schema version",
    )

    if schema_version != DESIGN_PACKAGE_SCHEMA_VERSION:
        raise ValueError("unsupported Design Package schema")

    grounding = _grounding_from_snapshot(
        _mapping(
            _required(payload, "grounding"),
            label="Design Package grounding",
        )
    )
    alternatives = tuple(
        _alternative_from_snapshot(item)
        for item in _mapping_sequence(
            _required(payload, "alternatives"),
            label="Design Package alternatives",
        )
    )
    critiques = tuple(
        _critique_from_snapshot(item)
        for item in _mapping_sequence(
            _required(payload, "critiques"),
            label="Design Package critiques",
        )
    )
    prototype_payload = payload.get("prototype")
    prototype = (
        None
        if prototype_payload is None
        else _prototype_from_snapshot(
            _mapping(
                prototype_payload,
                label="Design Package prototype",
            )
        )
    )
    package = create_design_exploration_package(
        project_id=_uuid(
            _required(payload, "project_id"),
            label="Design Package project ID",
        ),
        grounding=grounding,
        alternatives=alternatives,
        critiques=critiques,
        recommended_alternative_id=_optional_uuid(
            payload.get("recommended_alternative_id"),
            label="recommended Design Alternative ID",
        ),
        owner_selected_alternative_id=_optional_uuid(
            payload.get("owner_selected_alternative_id"),
            label="owner-selected Design Alternative ID",
        ),
        prototype=prototype,
        concerns=tuple(
            _concern_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "concerns"),
                label="Design Package concerns",
            )
        ),
        open_questions=_string_sequence(
            _required(payload, "open_questions"),
            label="Design Package open questions",
        ),
    )

    if package.to_snapshot() != dict(payload):
        raise ValueError("Design Package snapshot is not canonical")

    return package


def design_diff_proposal_snapshot(
    diff: DesignPackageDiff,
) -> dict[str, object]:
    """Return immutable proposal data stored independently from its decision."""
    return {
        "schema_version": DESIGN_PACKAGE_DIFF_SCHEMA_VERSION,
        "id": str(diff.id),
        "project_id": str(diff.project_id),
        "owner_user_id": str(diff.owner_user_id),
        "base_version_id": str(diff.base_version_id),
        "base_version_number": diff.base_version_number,
        "base_content_hash": diff.base_content_hash,
        "proposed_package": diff.proposed_package.to_snapshot(),
        "proposal_hash": diff.proposal_hash,
        "changes": [change.to_snapshot() for change in diff.changes],
        "created_at": diff.created_at.isoformat(),
    }


def design_diff_from_snapshot(
    payload: Mapping[str, object],
    *,
    status: DesignPackageDiffStatus,
    decided_by_user_id: UUID | None = None,
    decided_at: datetime | None = None,
    decision_reason: str | None = None,
    applied_version_id: UUID | None = None,
) -> DesignPackageDiff:
    """Reconstruct one diff from immutable proposal and mutable decision data."""
    schema_version = _integer(
        _required(payload, "schema_version"),
        label="Design Package diff schema version",
    )

    if schema_version != DESIGN_PACKAGE_DIFF_SCHEMA_VERSION:
        raise ValueError("unsupported Design Package diff schema")

    diff = DesignPackageDiff(
        id=_uuid(
            _required(payload, "id"),
            label="Design Package diff ID",
        ),
        project_id=_uuid(
            _required(payload, "project_id"),
            label="Design Package diff project ID",
        ),
        owner_user_id=_uuid(
            _required(payload, "owner_user_id"),
            label="Design Package diff owner ID",
        ),
        base_version_id=_uuid(
            _required(payload, "base_version_id"),
            label="Design Package diff base version ID",
        ),
        base_version_number=_integer(
            _required(payload, "base_version_number"),
            label="Design Package diff base version number",
        ),
        base_content_hash=_string(
            _required(payload, "base_content_hash"),
            label="Design Package diff base content hash",
        ),
        proposed_package=design_package_from_snapshot(
            _mapping(
                _required(payload, "proposed_package"),
                label="proposed Design Package",
            )
        ),
        proposal_hash=_string(
            _required(payload, "proposal_hash"),
            label="Design Package diff proposal hash",
        ),
        changes=tuple(
            _change_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "changes"),
                label="Design Package changes",
            )
        ),
        status=status,
        created_at=_datetime(
            _required(payload, "created_at"),
            label="Design Package diff creation timestamp",
        ),
        decided_by_user_id=decided_by_user_id,
        decided_at=decided_at,
        decision_reason=decision_reason,
        applied_version_id=applied_version_id,
    )

    if design_diff_proposal_snapshot(diff) != dict(payload):
        raise ValueError("Design Package diff proposal snapshot is not canonical")

    return diff


def _grounding_from_snapshot(payload: Mapping[str, object]) -> DesignGrounding:
    catalog = _mapping(
        _required(payload, "catalog"),
        label="Design Package catalog metadata",
    )

    return DesignGrounding(
        requirements_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "requirements_reference"),
                label="Design Requirements reference",
            )
        ),
        agent_team_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "agent_team_reference"),
                label="Design Agent Team reference",
            )
        ),
        user_modeling_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "user_modeling_reference"),
                label="Design User Modeling reference",
            )
        ),
        catalog_version=_integer(
            _required(catalog, "version"),
            label="Design catalog version",
        ),
        catalog_content_hash=_string(
            _required(catalog, "content_hash"),
            label="Design catalog content hash",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="Design grounding requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="Design grounding user-story IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="Design grounding acceptance-criterion IDs",
        ),
        user_twin_references=tuple(
            _user_twin_reference_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_twin_references"),
                label="Design grounding User Twin references",
            )
        ),
    )


def _alternative_from_snapshot(payload: Mapping[str, object]):
    return create_design_alternative(
        alternative_id=_uuid(
            _required(payload, "id"),
            label="Design Alternative ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="Design Alternative code",
        ),
        approach=DesignApproach(
            _string(
                _required(payload, "approach"),
                label="Design Alternative approach",
            )
        ),
        title=_string(
            _required(payload, "title"),
            label="Design Alternative title",
        ),
        summary=_string(
            _required(payload, "summary"),
            label="Design Alternative summary",
        ),
        rationale=_string(
            _required(payload, "rationale"),
            label="Design Alternative rationale",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="Design Alternative requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="Design Alternative user-story IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="Design Alternative acceptance-criterion IDs",
        ),
        user_twin_references=tuple(
            _user_twin_reference_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_twin_references"),
                label="Design Alternative User Twin references",
            )
        ),
        workflows=tuple(
            _workflow_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "workflows"),
                label="Design Alternative workflows",
            )
        ),
        information_architecture=_string_sequence(
            _required(payload, "information_architecture"),
            label="Design information architecture",
        ),
        accessibility_considerations=_string_sequence(
            _required(payload, "accessibility_considerations"),
            label="Design accessibility considerations",
        ),
        security_considerations=_string_sequence(
            _required(payload, "security_considerations"),
            label="Design security considerations",
        ),
        advantages=_string_sequence(
            _required(payload, "advantages"),
            label="Design advantages",
        ),
        trade_offs=_string_sequence(
            _required(payload, "trade_offs"),
            label="Design trade-offs",
        ),
        assumptions=_string_sequence(
            _required(payload, "assumptions"),
            label="Design assumptions",
        ),
        open_questions=_string_sequence(
            _required(payload, "open_questions"),
            label="Design Alternative open questions",
        ),
    )


def _workflow_from_snapshot(payload: Mapping[str, object]):
    return create_design_workflow(
        workflow_id=_uuid(
            _required(payload, "id"),
            label="Design workflow ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="Design workflow code",
        ),
        title=_string(
            _required(payload, "title"),
            label="Design workflow title",
        ),
        steps=_string_sequence(
            _required(payload, "steps"),
            label="Design workflow steps",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="Design workflow requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="Design workflow user-story IDs",
        ),
    )


def _critique_from_snapshot(payload: Mapping[str, object]):
    kind = DesignCritiqueKind(
        _string(
            _required(payload, "kind"),
            label="Design critique kind",
        )
    )
    epistemic_status = EpistemicStatus(
        _string(
            _required(payload, "epistemic_status"),
            label="Design critique epistemic status",
        )
    )
    validation = HumanValidationRequirement(
        _string(
            _required(payload, "human_validation"),
            label="Design critique human-validation requirement",
        )
    )

    if kind is not DesignCritiqueKind.SYNTHETIC_USER_TWIN:
        raise ValueError("Design critique must remain explicitly synthetic")

    if epistemic_status is not EpistemicStatus.MODEL_INFERRED:
        raise ValueError("Design critique must remain model-inferred")

    if validation is not HumanValidationRequirement.REQUIRED:
        raise ValueError("Design critique must require human validation")

    critique = create_synthetic_design_critique(
        critique_id=_uuid(
            _required(payload, "id"),
            label="Design critique ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="Design critique code",
        ),
        design_alternative_id=_uuid(
            _required(payload, "design_alternative_id"),
            label="Design critique alternative ID",
        ),
        user_twin_reference=_user_twin_reference_from_snapshot(
            _mapping(
                _required(payload, "user_twin_reference"),
                label="Design critique User Twin reference",
            )
        ),
        strengths=_string_sequence(
            _required(payload, "strengths"),
            label="Design critique strengths",
        ),
        concerns=_string_sequence(
            _required(payload, "concerns"),
            label="Design critique concerns",
        ),
        unmet_needs=_string_sequence(
            _required(payload, "unmet_needs"),
            label="Design critique unmet needs",
        ),
        accessibility_observations=_string_sequence(
            _required(payload, "accessibility_observations"),
            label="Design critique accessibility observations",
        ),
        trust_concerns=_string_sequence(
            _required(payload, "trust_concerns"),
            label="Design critique trust concerns",
        ),
        questions=_string_sequence(
            _required(payload, "questions"),
            label="Design critique questions",
        ),
        suggested_changes=_string_sequence(
            _required(payload, "suggested_changes"),
            label="Design critique suggested changes",
        ),
        provenance=_provenance_from_snapshot(_required(payload, "provenance")),
        confidence=ConfidenceScore(
            _number(
                _required(payload, "confidence"),
                label="Design critique confidence",
            )
        ),
        rationale=_string(
            _required(payload, "rationale"),
            label="Design critique rationale",
        ),
    )

    if critique.to_snapshot() != dict(payload):
        raise ValueError("Design critique snapshot is not canonical")

    return critique


def _prototype_from_snapshot(payload: Mapping[str, object]):
    prototype = create_declarative_prototype(
        prototype_id=_uuid(
            _required(payload, "id"),
            label="prototype ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="prototype code",
        ),
        title=_string(
            _required(payload, "title"),
            label="prototype title",
        ),
        design_alternative_id=_uuid(
            _required(payload, "design_alternative_id"),
            label="prototype Design Alternative ID",
        ),
        entry_screen_id=_uuid(
            _required(payload, "entry_screen_id"),
            label="prototype entry screen ID",
        ),
        screens=tuple(
            _screen_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "screens"),
                label="prototype screens",
            )
        ),
        transitions=tuple(
            _transition_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "transitions"),
                label="prototype transitions",
            )
        ),
        supported_viewports=tuple(
            PrototypeViewport(_string(item, label="prototype viewport"))
            for item in _sequence(
                _required(payload, "supported_viewports"),
                label="prototype viewports",
            )
        ),
    )

    if prototype.to_snapshot() != dict(payload):
        raise ValueError("prototype snapshot is not canonical")

    return prototype


def _screen_from_snapshot(payload: Mapping[str, object]):
    screen = create_prototype_screen(
        screen_id=_uuid(
            _required(payload, "id"),
            label="prototype screen ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="prototype screen code",
        ),
        title=_string(
            _required(payload, "title"),
            label="prototype screen title",
        ),
        state=PrototypeScreenState(
            _string(
                _required(payload, "state"),
                label="prototype screen state",
            )
        ),
        elements=tuple(
            _element_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "elements"),
                label="prototype screen elements",
            )
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="prototype screen requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="prototype screen user-story IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="prototype screen acceptance-criterion IDs",
        ),
    )

    if screen.to_snapshot() != dict(payload):
        raise ValueError("prototype screen snapshot is not canonical")

    return screen


def _element_from_snapshot(payload: Mapping[str, object]):
    element = create_prototype_element(
        element_id=_uuid(
            _required(payload, "id"),
            label="prototype element ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="prototype element code",
        ),
        kind=PrototypeElementKind(
            _string(
                _required(payload, "kind"),
                label="prototype element kind",
            )
        ),
        content=_string(
            _required(payload, "content"),
            label="prototype element content",
        ),
        accessible_name=_optional_string(
            payload.get("accessible_name"),
            label="prototype element accessible name",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="prototype element requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="prototype element user-story IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="prototype element acceptance-criterion IDs",
        ),
        field_name=_optional_string(
            payload.get("field_name"),
            label="prototype element field name",
        ),
        required=_boolean(
            _required(payload, "required"),
            label="prototype element required flag",
        ),
        options=_string_sequence(
            _required(payload, "options"),
            label="prototype element options",
        ),
    )

    if element.to_snapshot() != dict(payload):
        raise ValueError("prototype element snapshot is not canonical")

    return element


def _transition_from_snapshot(payload: Mapping[str, object]):
    transition = create_prototype_transition(
        transition_id=_uuid(
            _required(payload, "id"),
            label="prototype transition ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="prototype transition code",
        ),
        source_screen_id=_uuid(
            _required(payload, "source_screen_id"),
            label="prototype transition source screen ID",
        ),
        trigger_element_id=_uuid(
            _required(payload, "trigger_element_id"),
            label="prototype transition trigger element ID",
        ),
        target_screen_id=_uuid(
            _required(payload, "target_screen_id"),
            label="prototype transition target screen ID",
        ),
        outcome=_string(
            _required(payload, "outcome"),
            label="prototype transition outcome",
        ),
    )

    if transition.to_snapshot() != dict(payload):
        raise ValueError("prototype transition snapshot is not canonical")

    return transition


def _concern_from_snapshot(payload: Mapping[str, object]):
    concern = create_design_concern(
        concern_id=_uuid(
            _required(payload, "id"),
            label="Design concern ID",
        ),
        code=_string(
            _required(payload, "code"),
            label="Design concern code",
        ),
        summary=_string(
            _required(payload, "summary"),
            label="Design concern summary",
        ),
        mitigation=_string(
            _required(payload, "mitigation"),
            label="Design concern mitigation",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="Design concern requirement IDs",
        ),
        design_alternative_ids=_uuid_sequence(
            _required(payload, "design_alternative_ids"),
            label="Design concern alternative IDs",
        ),
    )

    if concern.to_snapshot() != dict(payload):
        raise ValueError("Design concern snapshot is not canonical")

    return concern


def _change_from_snapshot(payload: Mapping[str, object]) -> DesignPackageChange:
    return DesignPackageChange(
        kind=DesignChangeKind(
            _string(
                _required(payload, "kind"),
                label="Design change kind",
            )
        ),
        artifact_kind=DesignArtifactKind(
            _string(
                _required(payload, "artifact_kind"),
                label="Design change artifact kind",
            )
        ),
        artifact_id=_uuid(
            _required(payload, "artifact_id"),
            label="Design change artifact ID",
        ),
        before=_optional_mapping_copy(
            payload.get("before"),
            label="Design change before snapshot",
        ),
        after=_optional_mapping_copy(
            payload.get("after"),
            label="Design change after snapshot",
        ),
    )


def _artifact_reference_from_snapshot(
    payload: Mapping[str, object],
) -> VersionedArtifactReference:
    return VersionedArtifactReference(
        kind=ArtifactKind(
            _string(
                _required(payload, "kind"),
                label="artifact reference kind",
            )
        ),
        artifact_id=_uuid(
            _required(payload, "artifact_id"),
            label="artifact reference ID",
        ),
        version_number=_integer(
            _required(payload, "version_number"),
            label="artifact reference version",
        ),
        content_hash=_string(
            _required(payload, "content_hash"),
            label="artifact reference content hash",
        ),
    )


def _user_twin_reference_from_snapshot(
    payload: Mapping[str, object],
) -> UserTwinVersionReference:
    return UserTwinVersionReference(
        twin_id=_uuid(
            _required(payload, "twin_id"),
            label="User Twin ID",
        ),
        version_number=_integer(
            _required(payload, "version_number"),
            label="User Twin version",
        ),
        content_hash=_string(
            _required(payload, "content_hash"),
            label="User Twin content hash",
        ),
        name=_string(
            _required(payload, "name"),
            label="User Twin name",
        ),
    )


def _provenance_from_snapshot(value: object) -> ObservationProvenance:
    return ObservationProvenance.from_references(
        _evidence_reference_from_snapshot(item)
        for item in _mapping_sequence(
            value,
            label="Design critique provenance",
        )
    )


def _evidence_reference_from_snapshot(
    payload: Mapping[str, object],
) -> EvidenceReference:
    return EvidenceReference(
        source_kind=EvidenceSourceKind(
            _string(
                _required(payload, "source_kind"),
                label="evidence source kind",
            )
        ),
        source_id=_string(
            _required(payload, "source_id"),
            label="evidence source ID",
        ),
        source_version=_optional_integer(
            payload.get("source_version"),
            label="evidence source version",
        ),
        content_hash=_optional_string(
            payload.get("content_hash"),
            label="evidence content hash",
        ),
        locator=_optional_string(
            payload.get("locator"),
            label="evidence locator",
        ),
        summary=_optional_string(
            payload.get("summary"),
            label="evidence summary",
        ),
    )


def _required(values: Mapping[str, object], key: str) -> object:
    if key not in values:
        raise ValueError(f"missing Design Package field: {key}")

    return values[key]


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")

    return value


def _optional_mapping_copy(
    value: object,
    *,
    label: str,
) -> dict[str, object] | None:
    if value is None:
        return None

    return dict(_mapping(value, label=label))


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{label} must be a sequence")

    return value


def _mapping_sequence(
    value: object,
    *,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(item, label=label) for item in _sequence(value, label=label))


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")

    return value


def _optional_string(value: object, *, label: str) -> str | None:
    return None if value is None else _string(value, label=label)


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")

    return value


def _optional_integer(value: object, *, label: str) -> int | None:
    return None if value is None else _integer(value, label=label)


def _number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")

    return float(value)


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")

    return value


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value

    if isinstance(value, str):
        return UUID(value)

    raise ValueError(f"{label} must be a UUID")


def _optional_uuid(value: object, *, label: str) -> UUID | None:
    return None if value is None else _uuid(value, label=label)


def _datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be a timestamp")

    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return result


def _uuid_sequence(value: object, *, label: str) -> tuple[UUID, ...]:
    return tuple(_uuid(item, label=label) for item in _sequence(value, label=label))


def _string_sequence(value: object, *, label: str) -> tuple[str, ...]:
    return tuple(_string(item, label=label) for item in _sequence(value, label=label))


__all__ = [
    "DESIGN_PACKAGE_DIFF_SCHEMA_VERSION",
    "design_diff_from_snapshot",
    "design_diff_proposal_snapshot",
    "design_package_from_snapshot",
]
