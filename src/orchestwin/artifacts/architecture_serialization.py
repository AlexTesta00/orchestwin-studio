"""Canonical serialization boundaries for governed Architecture Packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.artifacts.architecture import (
    ApiMethod,
    ArchitectureComponentKind,
    ArchitectureConnectionKind,
    ArchitectureStyle,
    create_architecture_api_operation,
    create_architecture_component,
    create_architecture_connection,
    create_architecture_data_entity,
    create_architecture_decision,
    create_architecture_risk,
    create_software_architecture,
)
from orchestwin.artifacts.architecture_packages import (
    ARCHITECTURE_PACKAGE_SCHEMA_VERSION,
    ArchitectureGrounding,
    ArchitecturePlanningPackage,
    create_architecture_planning_package,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitectureArtifactKind,
    ArchitectureChangeKind,
    ArchitecturePackageChange,
    ArchitecturePackageDiff,
    ArchitecturePackageDiffStatus,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.artifacts.test_plans import (
    TestAutomation,
    TestEnvironmentKind,
    TestLevel,
    TestPriority,
    create_planned_test_case,
    create_quality_gate,
    create_test_environment,
    create_test_plan,
)
from orchestwin.projects.requirements_primitives import UserTwinVersionReference
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood

ARCHITECTURE_PACKAGE_DIFF_SCHEMA_VERSION: Final = 1


def architecture_package_from_snapshot(
    payload: Mapping[str, object],
) -> ArchitecturePlanningPackage:
    """Reconstruct and validate one complete canonical Architecture Package."""
    schema_version = _integer(
        _required(payload, "schema_version"),
        label="Architecture Package schema version",
    )

    if schema_version != ARCHITECTURE_PACKAGE_SCHEMA_VERSION:
        raise ValueError("unsupported Architecture Package schema")

    package = create_architecture_planning_package(
        project_id=_uuid(
            _required(payload, "project_id"),
            label="Architecture Package project ID",
        ),
        grounding=_grounding_from_snapshot(
            _mapping(
                _required(payload, "grounding"),
                label="Architecture Package grounding",
            )
        ),
        architecture=_architecture_from_snapshot(
            _mapping(
                _required(payload, "architecture"),
                label="Architecture Package architecture",
            )
        ),
        test_plan=_test_plan_from_snapshot(
            _mapping(
                _required(payload, "test_plan"),
                label="Architecture Package test plan",
            )
        ),
        open_questions=_string_sequence(
            _required(payload, "open_questions"),
            label="Architecture Package open questions",
        ),
    )

    if package.to_snapshot() != dict(payload):
        raise ValueError("Architecture Package snapshot is not canonical")

    return package


def architecture_diff_proposal_snapshot(
    diff: ArchitecturePackageDiff,
) -> dict[str, object]:
    """Return immutable proposal data stored independently from its decision."""
    return {
        "schema_version": ARCHITECTURE_PACKAGE_DIFF_SCHEMA_VERSION,
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


def architecture_diff_from_snapshot(
    payload: Mapping[str, object],
    *,
    status: ArchitecturePackageDiffStatus,
    decided_by_user_id: UUID | None = None,
    decided_at: datetime | None = None,
    decision_reason: str | None = None,
    applied_version_id: UUID | None = None,
) -> ArchitecturePackageDiff:
    """Reconstruct a diff proposal and attach persisted decision metadata."""
    schema_version = _integer(
        _required(payload, "schema_version"),
        label="Architecture Package diff schema version",
    )

    if schema_version != ARCHITECTURE_PACKAGE_DIFF_SCHEMA_VERSION:
        raise ValueError("unsupported Architecture Package diff schema")

    diff = ArchitecturePackageDiff(
        id=_uuid(_required(payload, "id"), label="Architecture Package diff ID"),
        project_id=_uuid(
            _required(payload, "project_id"),
            label="Architecture Package diff project ID",
        ),
        owner_user_id=_uuid(
            _required(payload, "owner_user_id"),
            label="Architecture Package diff owner ID",
        ),
        base_version_id=_uuid(
            _required(payload, "base_version_id"),
            label="Architecture Package diff base version ID",
        ),
        base_version_number=_integer(
            _required(payload, "base_version_number"),
            label="Architecture Package diff base version number",
        ),
        base_content_hash=_string(
            _required(payload, "base_content_hash"),
            label="Architecture Package diff base hash",
        ),
        proposed_package=architecture_package_from_snapshot(
            _mapping(
                _required(payload, "proposed_package"),
                label="Architecture Package diff proposed package",
            )
        ),
        proposal_hash=_string(
            _required(payload, "proposal_hash"),
            label="Architecture Package diff proposal hash",
        ),
        changes=tuple(
            _change_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "changes"),
                label="Architecture Package diff changes",
            )
        ),
        status=status,
        created_at=_datetime(
            _required(payload, "created_at"),
            label="Architecture Package diff creation timestamp",
        ),
        decided_by_user_id=decided_by_user_id,
        decided_at=decided_at,
        decision_reason=decision_reason,
        applied_version_id=applied_version_id,
    )

    expected_proposal = architecture_diff_proposal_snapshot(diff)
    if expected_proposal != dict(payload):
        raise ValueError("Architecture Package diff snapshot is not canonical")

    return diff


def _grounding_from_snapshot(payload: Mapping[str, object]) -> ArchitectureGrounding:
    return ArchitectureGrounding(
        project_id=_uuid(
            _required(payload, "project_id"),
            label="architecture grounding project ID",
        ),
        design_package_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "design_package_reference"),
                label="architecture Design Package reference",
            )
        ),
        requirements_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "requirements_reference"),
                label="architecture Requirements reference",
            )
        ),
        agent_team_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "agent_team_reference"),
                label="architecture Agent Team reference",
            )
        ),
        user_modeling_reference=_artifact_reference_from_snapshot(
            _mapping(
                _required(payload, "user_modeling_reference"),
                label="architecture User Modeling reference",
            )
        ),
        catalog_version=_integer(
            _required(
                _mapping(_required(payload, "catalog"), label="architecture catalog"),
                "version",
            ),
            label="architecture catalog version",
        ),
        catalog_content_hash=_string(
            _required(
                _mapping(_required(payload, "catalog"), label="architecture catalog"),
                "content_hash",
            ),
            label="architecture catalog content hash",
        ),
        owner_selected_alternative_id=_uuid(
            _required(payload, "owner_selected_alternative_id"),
            label="architecture selected alternative ID",
        ),
        prototype_id=_uuid(
            _required(payload, "prototype_id"),
            label="architecture prototype ID",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="architecture grounding requirement IDs",
        ),
        user_story_ids=_uuid_sequence(
            _required(payload, "user_story_ids"),
            label="architecture grounding user-story IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="architecture grounding acceptance-criterion IDs",
        ),
        user_twin_references=tuple(
            _user_twin_reference_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "user_twin_references"),
                label="architecture grounding User Twin references",
            )
        ),
    )


def _architecture_from_snapshot(payload: Mapping[str, object]):
    return create_software_architecture(
        architecture_id=_uuid(
            _required(payload, "id"),
            label="software architecture ID",
        ),
        code=_string(_required(payload, "code"), label="software architecture code"),
        title=_string(
            _required(payload, "title"),
            label="software architecture title",
        ),
        style=ArchitectureStyle(
            _string(_required(payload, "style"), label="software architecture style")
        ),
        summary=_string(
            _required(payload, "summary"),
            label="software architecture summary",
        ),
        selected_design_alternative_id=_uuid(
            _required(payload, "selected_design_alternative_id"),
            label="software architecture selected design alternative ID",
        ),
        prototype_id=_uuid(
            _required(payload, "prototype_id"),
            label="software architecture prototype ID",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="software architecture requirement IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="software architecture acceptance-criterion IDs",
        ),
        components=tuple(
            _component_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "components"),
                label="software architecture components",
            )
        ),
        connections=tuple(
            _connection_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "connections"),
                label="software architecture connections",
            )
        ),
        decisions=tuple(
            _decision_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "decisions"),
                label="software architecture decisions",
            )
        ),
        data_entities=tuple(
            _data_entity_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "data_entities"),
                label="software architecture data entities",
            )
        ),
        api_operations=tuple(
            _api_operation_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "api_operations"),
                label="software architecture API operations",
            )
        ),
        risks=tuple(
            _risk_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "risks"),
                label="software architecture risks",
            )
        ),
        quality_attributes=_string_sequence(
            _required(payload, "quality_attributes"),
            label="software architecture quality attributes",
        ),
        deployment_view=_string_sequence(
            _required(payload, "deployment_view"),
            label="software architecture deployment view",
        ),
        assumptions=_string_sequence(
            _required(payload, "assumptions"),
            label="software architecture assumptions",
        ),
        open_questions=_string_sequence(
            _required(payload, "open_questions"),
            label="software architecture open questions",
        ),
    )


def _component_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_component(
        component_id=_uuid(_required(payload, "id"), label="component ID"),
        code=_string(_required(payload, "code"), label="component code"),
        name=_string(_required(payload, "name"), label="component name"),
        kind=ArchitectureComponentKind(_string(_required(payload, "kind"), label="component kind")),
        responsibility=_string(
            _required(payload, "responsibility"),
            label="component responsibility",
        ),
        technology=_string(
            _required(payload, "technology"),
            label="component technology",
        ),
        interfaces=_string_sequence(
            _required(payload, "interfaces"),
            label="component interfaces",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="component requirement IDs",
        ),
        assumptions=_string_sequence(
            _required(payload, "assumptions"),
            label="component assumptions",
        ),
    )


def _connection_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_connection(
        connection_id=_uuid(_required(payload, "id"), label="connection ID"),
        code=_string(_required(payload, "code"), label="connection code"),
        source_component_id=_uuid(
            _required(payload, "source_component_id"),
            label="connection source component ID",
        ),
        target_component_id=_uuid(
            _required(payload, "target_component_id"),
            label="connection target component ID",
        ),
        kind=ArchitectureConnectionKind(
            _string(_required(payload, "kind"), label="connection kind")
        ),
        description=_string(
            _required(payload, "description"),
            label="connection description",
        ),
        data_flows=_string_sequence(
            _required(payload, "data_flows"),
            label="connection data flows",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="connection requirement IDs",
        ),
    )


def _decision_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_decision(
        decision_id=_uuid(_required(payload, "id"), label="decision ID"),
        code=_string(_required(payload, "code"), label="decision code"),
        title=_string(_required(payload, "title"), label="decision title"),
        context=_string(_required(payload, "context"), label="decision context"),
        decision=_string(_required(payload, "decision"), label="architecture decision"),
        consequences=_string_sequence(
            _required(payload, "consequences"),
            label="decision consequences",
        ),
        alternatives_considered=_string_sequence(
            _required(payload, "alternatives_considered"),
            label="decision alternatives",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="decision requirement IDs",
        ),
    )


def _data_entity_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_data_entity(
        entity_id=_uuid(_required(payload, "id"), label="data entity ID"),
        code=_string(_required(payload, "code"), label="data entity code"),
        name=_string(_required(payload, "name"), label="data entity name"),
        description=_string(
            _required(payload, "description"),
            label="data entity description",
        ),
        fields=_string_sequence(
            _required(payload, "fields"),
            label="data entity fields",
        ),
        owning_component_id=_uuid(
            _required(payload, "owning_component_id"),
            label="data entity owner component ID",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="data entity requirement IDs",
        ),
    )


def _api_operation_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_api_operation(
        operation_id=_uuid(_required(payload, "id"), label="API operation ID"),
        code=_string(_required(payload, "code"), label="API operation code"),
        method=ApiMethod(_string(_required(payload, "method"), label="API operation method")),
        path=_string(_required(payload, "path"), label="API operation path"),
        summary=_string(_required(payload, "summary"), label="API operation summary"),
        owning_component_id=_uuid(
            _required(payload, "owning_component_id"),
            label="API operation owner component ID",
        ),
        request_schema=_optional_string(
            payload.get("request_schema"),
            label="API operation request schema",
        ),
        response_schema=_string(
            _required(payload, "response_schema"),
            label="API operation response schema",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="API operation requirement IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="API operation acceptance-criterion IDs",
        ),
    )


def _risk_from_snapshot(payload: Mapping[str, object]):
    return create_architecture_risk(
        risk_id=_uuid(_required(payload, "id"), label="architecture risk ID"),
        code=_string(_required(payload, "code"), label="architecture risk code"),
        summary=_string(
            _required(payload, "summary"),
            label="architecture risk summary",
        ),
        likelihood=RiskLikelihood(
            _string(_required(payload, "likelihood"), label="risk likelihood")
        ),
        impact=RiskImpact(_string(_required(payload, "impact"), label="risk impact")),
        mitigation=_string(
            _required(payload, "mitigation"),
            label="architecture risk mitigation",
        ),
        component_ids=_uuid_sequence(
            _required(payload, "component_ids"),
            label="architecture risk component IDs",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="architecture risk requirement IDs",
        ),
    )


def _test_plan_from_snapshot(payload: Mapping[str, object]):
    return create_test_plan(
        plan_id=_uuid(_required(payload, "id"), label="test plan ID"),
        code=_string(_required(payload, "code"), label="test plan code"),
        title=_string(_required(payload, "title"), label="test plan title"),
        strategy=_string(_required(payload, "strategy"), label="test plan strategy"),
        architecture_id=_uuid(
            _required(payload, "architecture_id"),
            label="test plan architecture ID",
        ),
        selected_design_alternative_id=_uuid(
            _required(payload, "selected_design_alternative_id"),
            label="test plan selected design alternative ID",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="test plan requirement IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="test plan acceptance-criterion IDs",
        ),
        architecture_component_ids=_uuid_sequence(
            _required(payload, "architecture_component_ids"),
            label="test plan architecture-component IDs",
        ),
        environments=tuple(
            _environment_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "environments"),
                label="test plan environments",
            )
        ),
        test_cases=tuple(
            _test_case_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "test_cases"),
                label="test plan cases",
            )
        ),
        quality_gates=tuple(
            _quality_gate_from_snapshot(item)
            for item in _mapping_sequence(
                _required(payload, "quality_gates"),
                label="test plan quality gates",
            )
        ),
        fixtures=_string_sequence(
            _required(payload, "fixtures"),
            label="test plan fixtures",
        ),
        assumptions=_string_sequence(
            _required(payload, "assumptions"),
            label="test plan assumptions",
        ),
        open_questions=_string_sequence(
            _required(payload, "open_questions"),
            label="test plan open questions",
        ),
    )


def _environment_from_snapshot(payload: Mapping[str, object]):
    return create_test_environment(
        environment_id=_uuid(_required(payload, "id"), label="test environment ID"),
        code=_string(_required(payload, "code"), label="test environment code"),
        name=_string(_required(payload, "name"), label="test environment name"),
        kind=TestEnvironmentKind(
            _string(_required(payload, "kind"), label="test environment kind")
        ),
        description=_string(
            _required(payload, "description"),
            label="test environment description",
        ),
        configuration=_string_sequence(
            _required(payload, "configuration"),
            label="test environment configuration",
        ),
    )


def _test_case_from_snapshot(payload: Mapping[str, object]):
    return create_planned_test_case(
        test_case_id=_uuid(_required(payload, "id"), label="test case ID"),
        code=_string(_required(payload, "code"), label="test case code"),
        title=_string(_required(payload, "title"), label="test case title"),
        objective=_string(
            _required(payload, "objective"),
            label="test case objective",
        ),
        level=TestLevel(_string(_required(payload, "level"), label="test level")),
        automation=TestAutomation(
            _string(_required(payload, "automation"), label="test automation")
        ),
        priority=TestPriority(_string(_required(payload, "priority"), label="test priority")),
        preconditions=_string_sequence(
            _required(payload, "preconditions"),
            label="test case preconditions",
        ),
        steps=_string_sequence(_required(payload, "steps"), label="test case steps"),
        expected_results=_string_sequence(
            _required(payload, "expected_results"),
            label="test case expected results",
        ),
        requirement_ids=_uuid_sequence(
            _required(payload, "requirement_ids"),
            label="test case requirement IDs",
        ),
        acceptance_criterion_ids=_uuid_sequence(
            _required(payload, "acceptance_criterion_ids"),
            label="test case acceptance-criterion IDs",
        ),
        architecture_component_ids=_uuid_sequence(
            _required(payload, "architecture_component_ids"),
            label="test case architecture-component IDs",
        ),
        design_alternative_ids=_uuid_sequence(
            _required(payload, "design_alternative_ids"),
            label="test case design-alternative IDs",
        ),
        environment_ids=_uuid_sequence(
            _required(payload, "environment_ids"),
            label="test case environment IDs",
        ),
    )


def _quality_gate_from_snapshot(payload: Mapping[str, object]):
    return create_quality_gate(
        gate_id=_uuid(_required(payload, "id"), label="quality gate ID"),
        code=_string(_required(payload, "code"), label="quality gate code"),
        title=_string(_required(payload, "title"), label="quality gate title"),
        criterion=_string(
            _required(payload, "criterion"),
            label="quality gate criterion",
        ),
        required_test_case_ids=_uuid_sequence(
            _required(payload, "required_test_case_ids"),
            label="quality gate test-case IDs",
        ),
        minimum_pass_rate=_integer(
            _required(payload, "minimum_pass_rate"),
            label="quality gate minimum pass rate",
        ),
        blocking=_boolean(
            _required(payload, "blocking"),
            label="quality gate blocking flag",
        ),
    )


def _change_from_snapshot(
    payload: Mapping[str, object],
) -> ArchitecturePackageChange:
    return ArchitecturePackageChange(
        kind=ArchitectureChangeKind(
            _string(_required(payload, "kind"), label="architecture change kind")
        ),
        artifact_kind=ArchitectureArtifactKind(
            _string(
                _required(payload, "artifact_kind"),
                label="architecture changed artifact kind",
            )
        ),
        artifact_id=_uuid(
            _required(payload, "artifact_id"),
            label="architecture changed artifact ID",
        ),
        before=dict(
            _mapping(
                _required(payload, "before"),
                label="architecture change before snapshot",
            )
        ),
        after=dict(
            _mapping(
                _required(payload, "after"),
                label="architecture change after snapshot",
            )
        ),
    )


def _artifact_reference_from_snapshot(
    payload: Mapping[str, object],
) -> VersionedArtifactReference:
    return VersionedArtifactReference(
        kind=ArtifactKind(_string(_required(payload, "kind"), label="artifact reference kind")),
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
            label="artifact reference hash",
        ),
    )


def _user_twin_reference_from_snapshot(
    payload: Mapping[str, object],
) -> UserTwinVersionReference:
    return UserTwinVersionReference(
        twin_id=_uuid(_required(payload, "twin_id"), label="User Twin ID"),
        version_number=_integer(
            _required(payload, "version_number"),
            label="User Twin version",
        ),
        content_hash=_string(
            _required(payload, "content_hash"),
            label="User Twin content hash",
        ),
        name=_string(_required(payload, "name"), label="User Twin name"),
    )


def _required(values: Mapping[str, object], key: str) -> object:
    if key not in values:
        raise ValueError(f"missing Architecture Package field: {key}")

    return values[key]


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")

    return value


def _mapping_sequence(
    value: object,
    *,
    label: str,
) -> tuple[Mapping[str, object], ...]:
    sequence = _sequence(value, label=label)
    return tuple(_mapping(item, label=f"{label} item") for item in sequence)


def _string_sequence(value: object, *, label: str) -> tuple[str, ...]:
    sequence = _sequence(value, label=label)
    return tuple(_string(item, label=f"{label} item") for item in sequence)


def _uuid_sequence(value: object, *, label: str) -> tuple[UUID, ...]:
    sequence = _sequence(value, label=label)
    return tuple(_uuid(item, label=f"{label} item") for item in sequence)


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")

    return value


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


__all__ = [
    "ARCHITECTURE_PACKAGE_DIFF_SCHEMA_VERSION",
    "architecture_diff_from_snapshot",
    "architecture_diff_proposal_snapshot",
    "architecture_package_from_snapshot",
]
