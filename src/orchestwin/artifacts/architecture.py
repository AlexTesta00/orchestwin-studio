"""Immutable software architecture and decision artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    canonical_uuid_tuple,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood

_MAX_TITLE_LENGTH: Final = 200
_MAX_SUMMARY_LENGTH: Final = 4000
_MAX_DESCRIPTION_LENGTH: Final = 4000
_MAX_ITEM_LENGTH: Final = 2000
_MAX_PATH_LENGTH: Final = 512
_MAX_SCHEMA_NAME_LENGTH: Final = 200


class ArchitectureStyle(StrEnum):
    """Supported high-level organization styles for generated projects."""

    MODULAR_MONOLITH = "MODULAR_MONOLITH"
    LAYERED_MONOLITH = "LAYERED_MONOLITH"
    CLIENT_SERVER = "CLIENT_SERVER"
    SINGLE_DEPLOYABLE_APPLICATION = "SINGLE_DEPLOYABLE_APPLICATION"


class ArchitectureComponentKind(StrEnum):
    """Stable classifications for architecture components."""

    USER_INTERFACE = "USER_INTERFACE"
    APPLICATION_SERVICE = "APPLICATION_SERVICE"
    DOMAIN_MODULE = "DOMAIN_MODULE"
    DATA_STORE = "DATA_STORE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    INTEGRATION_ADAPTER = "INTEGRATION_ADAPTER"
    BACKGROUND_WORKER = "BACKGROUND_WORKER"
    DEVICE_APPLICATION = "DEVICE_APPLICATION"


class ArchitectureConnectionKind(StrEnum):
    """Allowed semantic relationships between components."""

    CALLS = "CALLS"
    READS_FROM = "READS_FROM"
    WRITES_TO = "WRITES_TO"
    PUBLISHES_TO = "PUBLISHES_TO"
    CONSUMES_FROM = "CONSUMES_FROM"
    DEPENDS_ON = "DEPENDS_ON"


class ApiMethod(StrEnum):
    """HTTP methods represented by an architecture operation."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass(frozen=True, slots=True)
class ArchitectureComponent:
    """One bounded and traceable generated-project component."""

    id: UUID
    code: str
    name: str
    kind: ArchitectureComponentKind
    responsibility: str
    technology: str
    interfaces: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect identity, normalized content, and traceability."""
        validate_display_code(self.code, prefix="CMP", label="architecture component code")

        for value, label, maximum_length in (
            (self.name, "architecture component name", _MAX_TITLE_LENGTH),
            (self.responsibility, "architecture component responsibility", _MAX_DESCRIPTION_LENGTH),
            (self.technology, "architecture component technology", _MAX_TITLE_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label, require_items in (
            (self.interfaces, "architecture component interfaces", False),
            (self.assumptions, "architecture component assumptions", False),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="architecture component requirement IDs",
            require_items=True,
        ):
            raise ValueError("architecture component requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic component snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "kind": self.kind.value,
            "responsibility": self.responsibility,
            "technology": self.technology,
            "interfaces": list(self.interfaces),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True, slots=True)
class ArchitectureConnection:
    """One explicit dependency or data-flow relationship."""

    id: UUID
    code: str
    source_component_id: UUID
    target_component_id: UUID
    kind: ArchitectureConnectionKind
    description: str
    data_flows: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect a meaningful, normalized connection."""
        validate_display_code(self.code, prefix="CON", label="architecture connection code")

        if self.source_component_id == self.target_component_id:
            raise ValueError("architecture connections require distinct components")

        if (
            normalize_required_text(
                self.description,
                label="architecture connection description",
                maximum_length=_MAX_DESCRIPTION_LENGTH,
            )
            != self.description
        ):
            raise ValueError("architecture connection description must be normalized")

        if self.data_flows != normalize_text_items(
            self.data_flows,
            label="architecture connection data flows",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ):
            raise ValueError("architecture connection data flows must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="architecture connection requirement IDs",
            require_items=True,
        ):
            raise ValueError("architecture connection requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic connection snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "source_component_id": str(self.source_component_id),
            "target_component_id": str(self.target_component_id),
            "kind": self.kind.value,
            "description": self.description,
            "data_flows": list(self.data_flows),
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureDecision:
    """One ADR-ready generated-project architecture decision."""

    id: UUID
    code: str
    title: str
    context: str
    decision: str
    consequences: tuple[str, ...]
    alternatives_considered: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect inspectable rationale and exact traceability."""
        validate_display_code(self.code, prefix="ADR", label="architecture decision code")

        for value, label, maximum_length in (
            (self.title, "architecture decision title", _MAX_TITLE_LENGTH),
            (self.context, "architecture decision context", _MAX_DESCRIPTION_LENGTH),
            (self.decision, "architecture decision", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label, require_items in (
            (self.consequences, "architecture decision consequences", True),
            (
                self.alternatives_considered,
                "architecture decision alternatives",
                True,
            ),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="architecture decision requirement IDs",
            require_items=True,
        ):
            raise ValueError("architecture decision requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic decision snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "context": self.context,
            "decision": self.decision,
            "consequences": list(self.consequences),
            "alternatives_considered": list(self.alternatives_considered),
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureDataEntity:
    """One logical data entity owned by an architecture component."""

    id: UUID
    code: str
    name: str
    description: str
    fields: tuple[str, ...]
    owning_component_id: UUID
    requirement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect logical data ownership and schema readability."""
        validate_display_code(self.code, prefix="ENT", label="architecture data-entity code")

        for value, label, maximum_length in (
            (self.name, "architecture data-entity name", _MAX_TITLE_LENGTH),
            (self.description, "architecture data-entity description", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        if self.fields != normalize_text_items(
            self.fields,
            label="architecture data-entity fields",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ):
            raise ValueError("architecture data-entity fields must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="architecture data-entity requirement IDs",
            require_items=True,
        ):
            raise ValueError("architecture data-entity requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic data-entity snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "fields": list(self.fields),
            "owning_component_id": str(self.owning_component_id),
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureApiOperation:
    """One generated-project API operation linked to approved outcomes."""

    id: UUID
    code: str
    method: ApiMethod
    path: str
    summary: str
    owning_component_id: UUID
    request_schema: str | None
    response_schema: str
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect a normalized operation and its traceability."""
        validate_display_code(self.code, prefix="API", label="architecture API-operation code")

        normalized_path = normalize_required_text(
            self.path,
            label="architecture API-operation path",
            maximum_length=_MAX_PATH_LENGTH,
        )
        if normalized_path != self.path or not self.path.startswith("/"):
            raise ValueError("architecture API-operation path must be normalized and absolute")

        if (
            normalize_required_text(
                self.summary,
                label="architecture API-operation summary",
                maximum_length=_MAX_SUMMARY_LENGTH,
            )
            != self.summary
        ):
            raise ValueError("architecture API-operation summary must be normalized")

        normalized_request = normalize_optional_text(
            self.request_schema,
            label="architecture API request schema",
            maximum_length=_MAX_SCHEMA_NAME_LENGTH,
        )
        if normalized_request != self.request_schema:
            raise ValueError("architecture API request schema must be normalized")

        if (
            normalize_required_text(
                self.response_schema,
                label="architecture API response schema",
                maximum_length=_MAX_SCHEMA_NAME_LENGTH,
            )
            != self.response_schema
        ):
            raise ValueError("architecture API response schema must be normalized")

        for values, label in (
            (self.requirement_ids, "architecture API-operation requirement IDs"),
            (
                self.acceptance_criterion_ids,
                "architecture API-operation acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(values, label=label, require_items=True):
                raise ValueError(f"{label} must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic API-operation snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "method": self.method.value,
            "path": self.path,
            "summary": self.summary,
            "owning_component_id": str(self.owning_component_id),
            "request_schema": self.request_schema,
            "response_schema": self.response_schema,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureRisk:
    """One explicit architecture risk with mitigation."""

    id: UUID
    code: str
    summary: str
    likelihood: RiskLikelihood
    impact: RiskImpact
    mitigation: str
    component_ids: tuple[UUID, ...]
    requirement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect normalized risk content and affected references."""
        validate_display_code(self.code, prefix="ARK", label="architecture risk code")

        for value, label, maximum_length in (
            (self.summary, "architecture risk summary", _MAX_SUMMARY_LENGTH),
            (self.mitigation, "architecture risk mitigation", _MAX_DESCRIPTION_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label in (
            (self.component_ids, "architecture risk component IDs"),
            (self.requirement_ids, "architecture risk requirement IDs"),
        ):
            if values != canonical_uuid_tuple(values, label=label, require_items=True):
                raise ValueError(f"{label} must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic architecture-risk snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "summary": self.summary,
            "likelihood": self.likelihood.value,
            "impact": self.impact.value,
            "mitigation": self.mitigation,
            "component_ids": [str(value) for value in self.component_ids],
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }


class _CodedArtifact(Protocol):
    id: UUID
    code: str


def _canonical_coded_artifacts[T: _CodedArtifact](
    values: Iterable[T],
    *,
    label: str,
    require_items: bool,
) -> tuple[T, ...]:
    """Return unique coded artifacts in deterministic code order."""
    artifacts = tuple(values)

    if require_items and not artifacts:
        raise ValueError(f"{label} must not be empty")

    if len({artifact.id for artifact in artifacts}) != len(artifacts):
        raise ValueError(f"{label} identities must be unique")

    if len({artifact.code for artifact in artifacts}) != len(artifacts):
        raise ValueError(f"{label} codes must be unique")

    return tuple(sorted(artifacts, key=lambda artifact: artifact.code))


@dataclass(frozen=True, slots=True)
class SoftwareArchitecture:
    """A complete, traceable generated-project architecture specification."""

    id: UUID
    code: str
    title: str
    style: ArchitectureStyle
    summary: str
    selected_design_alternative_id: UUID
    prototype_id: UUID
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    components: tuple[ArchitectureComponent, ...]
    connections: tuple[ArchitectureConnection, ...]
    decisions: tuple[ArchitectureDecision, ...]
    data_entities: tuple[ArchitectureDataEntity, ...]
    api_operations: tuple[ArchitectureApiOperation, ...]
    risks: tuple[ArchitectureRisk, ...]
    quality_attributes: tuple[str, ...]
    deployment_view: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect canonical ordering, internal references, and stage traceability."""
        validate_display_code(self.code, prefix="ARC", label="software architecture code")

        for value, label, maximum_length in (
            (self.title, "software architecture title", _MAX_TITLE_LENGTH),
            (self.summary, "software architecture summary", _MAX_SUMMARY_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")

        for values, label in (
            (self.requirement_ids, "software architecture requirement IDs"),
            (
                self.acceptance_criterion_ids,
                "software architecture acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(values, label=label, require_items=True):
                raise ValueError(f"{label} must use canonical order")

        for values, expected, label in (
            (
                self.components,
                _canonical_coded_artifacts(
                    self.components,
                    label="architecture components",
                    require_items=True,
                ),
                "architecture components",
            ),
            (
                self.connections,
                _canonical_coded_artifacts(
                    self.connections,
                    label="architecture connections",
                    require_items=False,
                ),
                "architecture connections",
            ),
            (
                self.decisions,
                _canonical_coded_artifacts(
                    self.decisions,
                    label="architecture decisions",
                    require_items=True,
                ),
                "architecture decisions",
            ),
            (
                self.data_entities,
                _canonical_coded_artifacts(
                    self.data_entities,
                    label="architecture data entities",
                    require_items=False,
                ),
                "architecture data entities",
            ),
            (
                self.api_operations,
                _canonical_coded_artifacts(
                    self.api_operations,
                    label="architecture API operations",
                    require_items=False,
                ),
                "architecture API operations",
            ),
            (
                self.risks,
                _canonical_coded_artifacts(
                    self.risks,
                    label="architecture risks",
                    require_items=False,
                ),
                "architecture risks",
            ),
        ):
            if values != expected:
                raise ValueError(f"{label} must use canonical code order")

        for values, label, require_items in (
            (self.quality_attributes, "architecture quality attributes", True),
            (self.deployment_view, "architecture deployment view", True),
            (self.assumptions, "architecture assumptions", False),
            (self.open_questions, "architecture open questions", False),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must be normalized")

        self._validate_references()

    def _validate_references(self) -> None:
        """Reject unknown component, requirement, or criterion references."""
        component_ids = frozenset(component.id for component in self.components)
        requirement_ids = frozenset(self.requirement_ids)
        criterion_ids = frozenset(self.acceptance_criterion_ids)

        for component in self.components:
            _require_subset(
                component.requirement_ids,
                requirement_ids,
                "architecture components contain unknown requirement references",
            )

        for connection in self.connections:
            if {
                connection.source_component_id,
                connection.target_component_id,
            } - component_ids:
                raise ValueError("architecture connections contain unknown component references")
            _require_subset(
                connection.requirement_ids,
                requirement_ids,
                "architecture connections contain unknown requirement references",
            )

        for decision in self.decisions:
            _require_subset(
                decision.requirement_ids,
                requirement_ids,
                "architecture decisions contain unknown requirement references",
            )

        for entity in self.data_entities:
            if entity.owning_component_id not in component_ids:
                raise ValueError("architecture data entities contain unknown component references")
            _require_subset(
                entity.requirement_ids,
                requirement_ids,
                "architecture data entities contain unknown requirement references",
            )

        for operation in self.api_operations:
            if operation.owning_component_id not in component_ids:
                raise ValueError("architecture API operations contain unknown component references")
            _require_subset(
                operation.requirement_ids,
                requirement_ids,
                "architecture API operations contain unknown requirement references",
            )
            _require_subset(
                operation.acceptance_criterion_ids,
                criterion_ids,
                "architecture API operations contain unknown acceptance-criterion references",
            )

        for risk in self.risks:
            _require_subset(
                risk.component_ids,
                component_ids,
                "architecture risks contain unknown component references",
            )
            _require_subset(
                risk.requirement_ids,
                requirement_ids,
                "architecture risks contain unknown requirement references",
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic architecture snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "style": self.style.value,
            "summary": self.summary,
            "selected_design_alternative_id": str(self.selected_design_alternative_id),
            "prototype_id": str(self.prototype_id),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "components": [component.to_snapshot() for component in self.components],
            "connections": [connection.to_snapshot() for connection in self.connections],
            "decisions": [decision.to_snapshot() for decision in self.decisions],
            "data_entities": [entity.to_snapshot() for entity in self.data_entities],
            "api_operations": [operation.to_snapshot() for operation in self.api_operations],
            "risks": [risk.to_snapshot() for risk in self.risks],
            "quality_attributes": list(self.quality_attributes),
            "deployment_view": list(self.deployment_view),
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
        }

    def canonical_json(self) -> str:
        """Serialize this architecture deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this architecture."""
        return snapshot_content_hash(self.to_snapshot())


def _require_subset(values: Iterable[UUID], allowed: frozenset[UUID], message: str) -> None:
    """Require every UUID in one collection to resolve in an allowed set."""
    if not frozenset(values).issubset(allowed):
        raise ValueError(message)


def create_architecture_component(
    *,
    component_id: UUID,
    code: str,
    name: str,
    kind: ArchitectureComponentKind,
    responsibility: str,
    technology: str,
    requirement_ids: Iterable[UUID],
    interfaces: Iterable[str] = (),
    assumptions: Iterable[str] = (),
) -> ArchitectureComponent:
    """Create one normalized architecture component."""
    return ArchitectureComponent(
        id=component_id,
        code=code,
        name=normalize_required_text(
            name,
            label="architecture component name",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        kind=kind,
        responsibility=normalize_required_text(
            responsibility,
            label="architecture component responsibility",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        technology=normalize_required_text(
            technology,
            label="architecture component technology",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        interfaces=normalize_text_items(
            interfaces,
            label="architecture component interfaces",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture component requirement IDs",
            require_items=True,
        ),
        assumptions=normalize_text_items(
            assumptions,
            label="architecture component assumptions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
    )


def create_architecture_connection(
    *,
    connection_id: UUID,
    code: str,
    source_component_id: UUID,
    target_component_id: UUID,
    kind: ArchitectureConnectionKind,
    description: str,
    requirement_ids: Iterable[UUID],
    data_flows: Iterable[str] = (),
) -> ArchitectureConnection:
    """Create one normalized architecture connection."""
    return ArchitectureConnection(
        id=connection_id,
        code=code,
        source_component_id=source_component_id,
        target_component_id=target_component_id,
        kind=kind,
        description=normalize_required_text(
            description,
            label="architecture connection description",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        data_flows=normalize_text_items(
            data_flows,
            label="architecture connection data flows",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture connection requirement IDs",
            require_items=True,
        ),
    )


def create_architecture_decision(
    *,
    decision_id: UUID,
    code: str,
    title: str,
    context: str,
    decision: str,
    consequences: Iterable[str],
    alternatives_considered: Iterable[str],
    requirement_ids: Iterable[UUID],
) -> ArchitectureDecision:
    """Create one normalized ADR-ready decision."""
    return ArchitectureDecision(
        id=decision_id,
        code=code,
        title=normalize_required_text(
            title,
            label="architecture decision title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        context=normalize_required_text(
            context,
            label="architecture decision context",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        decision=normalize_required_text(
            decision,
            label="architecture decision",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        consequences=normalize_text_items(
            consequences,
            label="architecture decision consequences",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        alternatives_considered=normalize_text_items(
            alternatives_considered,
            label="architecture decision alternatives",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture decision requirement IDs",
            require_items=True,
        ),
    )


def create_architecture_data_entity(
    *,
    entity_id: UUID,
    code: str,
    name: str,
    description: str,
    fields: Iterable[str],
    owning_component_id: UUID,
    requirement_ids: Iterable[UUID],
) -> ArchitectureDataEntity:
    """Create one normalized logical data entity."""
    return ArchitectureDataEntity(
        id=entity_id,
        code=code,
        name=normalize_required_text(
            name,
            label="architecture data-entity name",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        description=normalize_required_text(
            description,
            label="architecture data-entity description",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        fields=normalize_text_items(
            fields,
            label="architecture data-entity fields",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        owning_component_id=owning_component_id,
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture data-entity requirement IDs",
            require_items=True,
        ),
    )


def create_architecture_api_operation(
    *,
    operation_id: UUID,
    code: str,
    method: ApiMethod,
    path: str,
    summary: str,
    owning_component_id: UUID,
    response_schema: str,
    requirement_ids: Iterable[UUID],
    acceptance_criterion_ids: Iterable[UUID],
    request_schema: str | None = None,
) -> ArchitectureApiOperation:
    """Create one normalized API operation."""
    return ArchitectureApiOperation(
        id=operation_id,
        code=code,
        method=method,
        path=normalize_required_text(
            path,
            label="architecture API-operation path",
            maximum_length=_MAX_PATH_LENGTH,
        ),
        summary=normalize_required_text(
            summary,
            label="architecture API-operation summary",
            maximum_length=_MAX_SUMMARY_LENGTH,
        ),
        owning_component_id=owning_component_id,
        request_schema=normalize_optional_text(
            request_schema,
            label="architecture API request schema",
            maximum_length=_MAX_SCHEMA_NAME_LENGTH,
        ),
        response_schema=normalize_required_text(
            response_schema,
            label="architecture API response schema",
            maximum_length=_MAX_SCHEMA_NAME_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture API-operation requirement IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="architecture API-operation acceptance-criterion IDs",
            require_items=True,
        ),
    )


def create_architecture_risk(
    *,
    risk_id: UUID,
    code: str,
    summary: str,
    likelihood: RiskLikelihood,
    impact: RiskImpact,
    mitigation: str,
    component_ids: Iterable[UUID],
    requirement_ids: Iterable[UUID],
) -> ArchitectureRisk:
    """Create one normalized architecture risk."""
    return ArchitectureRisk(
        id=risk_id,
        code=code,
        summary=normalize_required_text(
            summary,
            label="architecture risk summary",
            maximum_length=_MAX_SUMMARY_LENGTH,
        ),
        likelihood=likelihood,
        impact=impact,
        mitigation=normalize_required_text(
            mitigation,
            label="architecture risk mitigation",
            maximum_length=_MAX_DESCRIPTION_LENGTH,
        ),
        component_ids=canonical_uuid_tuple(
            component_ids,
            label="architecture risk component IDs",
            require_items=True,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="architecture risk requirement IDs",
            require_items=True,
        ),
    )


def create_software_architecture(
    *,
    architecture_id: UUID,
    code: str,
    title: str,
    style: ArchitectureStyle,
    summary: str,
    selected_design_alternative_id: UUID,
    prototype_id: UUID,
    requirement_ids: Iterable[UUID],
    acceptance_criterion_ids: Iterable[UUID],
    components: Iterable[ArchitectureComponent],
    decisions: Iterable[ArchitectureDecision],
    quality_attributes: Iterable[str],
    deployment_view: Iterable[str],
    connections: Iterable[ArchitectureConnection] = (),
    data_entities: Iterable[ArchitectureDataEntity] = (),
    api_operations: Iterable[ArchitectureApiOperation] = (),
    risks: Iterable[ArchitectureRisk] = (),
    assumptions: Iterable[str] = (),
    open_questions: Iterable[str] = (),
) -> SoftwareArchitecture:
    """Create one canonical software architecture specification."""
    return SoftwareArchitecture(
        id=architecture_id,
        code=code,
        title=normalize_required_text(
            title,
            label="software architecture title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        style=style,
        summary=normalize_required_text(
            summary,
            label="software architecture summary",
            maximum_length=_MAX_SUMMARY_LENGTH,
        ),
        selected_design_alternative_id=selected_design_alternative_id,
        prototype_id=prototype_id,
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="software architecture requirement IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="software architecture acceptance-criterion IDs",
            require_items=True,
        ),
        components=_canonical_coded_artifacts(
            components,
            label="architecture components",
            require_items=True,
        ),
        connections=_canonical_coded_artifacts(
            connections,
            label="architecture connections",
            require_items=False,
        ),
        decisions=_canonical_coded_artifacts(
            decisions,
            label="architecture decisions",
            require_items=True,
        ),
        data_entities=_canonical_coded_artifacts(
            data_entities,
            label="architecture data entities",
            require_items=False,
        ),
        api_operations=_canonical_coded_artifacts(
            api_operations,
            label="architecture API operations",
            require_items=False,
        ),
        risks=_canonical_coded_artifacts(
            risks,
            label="architecture risks",
            require_items=False,
        ),
        quality_attributes=normalize_text_items(
            quality_attributes,
            label="architecture quality attributes",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        deployment_view=normalize_text_items(
            deployment_view,
            label="architecture deployment view",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        assumptions=normalize_text_items(
            assumptions,
            label="architecture assumptions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        open_questions=normalize_text_items(
            open_questions,
            label="architecture open questions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
    )


__all__ = [
    "ApiMethod",
    "ArchitectureApiOperation",
    "ArchitectureComponent",
    "ArchitectureComponentKind",
    "ArchitectureConnection",
    "ArchitectureConnectionKind",
    "ArchitectureDataEntity",
    "ArchitectureDecision",
    "ArchitectureRisk",
    "ArchitectureStyle",
    "SoftwareArchitecture",
    "create_architecture_api_operation",
    "create_architecture_component",
    "create_architecture_connection",
    "create_architecture_data_entity",
    "create_architecture_decision",
    "create_architecture_risk",
    "create_software_architecture",
]
