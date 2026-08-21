"""Tests for immutable software architecture artifacts."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

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
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000020")
ALTERNATIVE_ID = UUID("00000000-0000-4000-8000-000000000030")
PROTOTYPE_ID = UUID("00000000-0000-4000-8000-000000000040")
FRONTEND_ID = UUID("00000000-0000-4000-8000-000000000050")
BACKEND_ID = UUID("00000000-0000-4000-8000-000000000051")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000060")
DECISION_ID = UUID("00000000-0000-4000-8000-000000000070")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000080")
OPERATION_ID = UUID("00000000-0000-4000-8000-000000000090")
RISK_ID = UUID("00000000-0000-4000-8000-0000000000a0")
ARCHITECTURE_ID = UUID("00000000-0000-4000-8000-0000000000b0")


def frontend_component():
    """Create one traceable UI component."""
    return create_architecture_component(
        component_id=FRONTEND_ID,
        code="CMP-001",
        name="Web interface",
        kind=ArchitectureComponentKind.USER_INTERFACE,
        responsibility="Render the approved reservation workflow.",
        technology="Vue and TypeScript",
        interfaces=("HTTP API",),
        requirement_ids=(REQUIREMENT_ID,),
    )


def backend_component():
    """Create one traceable application component."""
    return create_architecture_component(
        component_id=BACKEND_ID,
        code="CMP-002",
        name="Reservation application",
        kind=ArchitectureComponentKind.APPLICATION_SERVICE,
        responsibility="Validate and persist reservation commands.",
        technology="Python and FastAPI",
        interfaces=("Reservation API",),
        requirement_ids=(REQUIREMENT_ID,),
    )


def connection():
    """Create one declared component relationship."""
    return create_architecture_connection(
        connection_id=CONNECTION_ID,
        code="CON-001",
        source_component_id=FRONTEND_ID,
        target_component_id=BACKEND_ID,
        kind=ArchitectureConnectionKind.CALLS,
        description="The interface calls the reservation application through HTTP.",
        data_flows=("Reservation command", "Reservation status"),
        requirement_ids=(REQUIREMENT_ID,),
    )


def decision():
    """Create one ADR-ready decision."""
    return create_architecture_decision(
        decision_id=DECISION_ID,
        code="ADR-001",
        title="Use a client-server boundary",
        context="The selected design requires a responsive interface and persistent state.",
        decision="Separate the web interface from the application API.",
        consequences=("The API boundary becomes independently testable.",),
        alternatives_considered=("Single server-rendered application",),
        requirement_ids=(REQUIREMENT_ID,),
    )


def architecture():
    """Create one complete generated-project architecture."""
    entity = create_architecture_data_entity(
        entity_id=ENTITY_ID,
        code="ENT-001",
        name="Reservation",
        description="The persisted reservation record.",
        fields=("id: UUID", "guest_name: string"),
        owning_component_id=BACKEND_ID,
        requirement_ids=(REQUIREMENT_ID,),
    )
    operation = create_architecture_api_operation(
        operation_id=OPERATION_ID,
        code="API-001",
        method=ApiMethod.POST,
        path="/reservations",
        summary="Create one reservation.",
        owning_component_id=BACKEND_ID,
        request_schema="ReservationInput",
        response_schema="ReservationResponse",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    risk = create_architecture_risk(
        risk_id=RISK_ID,
        code="ARK-001",
        summary="Concurrent updates could overwrite reservation state.",
        likelihood=RiskLikelihood.POSSIBLE,
        impact=RiskImpact.HIGH,
        mitigation="Use optimistic concurrency and explicit conflict responses.",
        component_ids=(BACKEND_ID,),
        requirement_ids=(REQUIREMENT_ID,),
    )

    return create_software_architecture(
        architecture_id=ARCHITECTURE_ID,
        code="ARC-001",
        title="Reservation system architecture",
        style=ArchitectureStyle.CLIENT_SERVER,
        summary="A small client-server system aligned with the selected design.",
        selected_design_alternative_id=ALTERNATIVE_ID,
        prototype_id=PROTOTYPE_ID,
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        components=(backend_component(), frontend_component()),
        connections=(connection(),),
        decisions=(decision(),),
        data_entities=(entity,),
        api_operations=(operation,),
        risks=(risk,),
        quality_attributes=("Accessible keyboard operation", "Deterministic testability"),
        deployment_view=("Browser", "Application API", "PostgreSQL"),
    )


def test_architecture_is_canonical_traceable_and_hashable() -> None:
    """Create stable architecture content from unordered child input."""
    value = architecture()

    assert tuple(component.code for component in value.components) == (
        "CMP-001",
        "CMP-002",
    )
    assert value.selected_design_alternative_id == ALTERNATIVE_ID
    assert value.prototype_id == PROTOTYPE_ID
    assert len(value.content_hash) == 64


def test_architecture_rejects_unknown_component_references() -> None:
    """Reject data flows that do not resolve to declared components."""
    invalid = replace(
        connection(),
        target_component_id=UUID("00000000-0000-4000-8000-000000000099"),
    )

    with pytest.raises(ValueError, match="unknown component references"):
        replace(architecture(), connections=(invalid,))


def test_architecture_rejects_unknown_requirement_references() -> None:
    """Keep every child artifact inside the approved requirement scope."""
    unknown = UUID("00000000-0000-4000-8000-000000000099")
    invalid = replace(frontend_component(), requirement_ids=(unknown,))

    with pytest.raises(ValueError, match="unknown requirement references"):
        replace(architecture(), components=(invalid, backend_component()))


def test_api_operation_requires_an_absolute_path() -> None:
    """Keep generated HTTP contracts unambiguous."""
    with pytest.raises(ValueError, match="normalized and absolute"):
        create_architecture_api_operation(
            operation_id=OPERATION_ID,
            code="API-001",
            method=ApiMethod.GET,
            path="reservations",
            summary="List reservations.",
            owning_component_id=BACKEND_ID,
            response_schema="ReservationList",
            requirement_ids=(REQUIREMENT_ID,),
            acceptance_criterion_ids=(CRITERION_ID,),
        )


def test_architecture_connection_cannot_target_itself() -> None:
    """Reject meaningless self-connections in the component graph."""
    with pytest.raises(ValueError, match="distinct components"):
        replace(connection(), target_component_id=FRONTEND_ID)


def test_equal_architectures_have_equal_snapshots_and_hashes() -> None:
    """Keep architecture artifacts reproducible."""
    first = architecture()
    second = architecture()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
