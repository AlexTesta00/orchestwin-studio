"""Shared deterministic fixtures for architecture package and proposal tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from orchestwin.artifacts.architecture import (
    ApiMethod,
    ArchitectureComponentKind,
    ArchitectureConnectionKind,
    ArchitectureStyle,
    SoftwareArchitecture,
    create_architecture_api_operation,
    create_architecture_component,
    create_architecture_connection,
    create_architecture_data_entity,
    create_architecture_decision,
    create_architecture_risk,
    create_software_architecture,
)
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
    create_architecture_grounding,
    create_architecture_planning_package,
)
from orchestwin.artifacts.test_plans import (
    TestAutomation as AutomationMode,
)
from orchestwin.artifacts.test_plans import (
    TestEnvironmentKind as EnvironmentKind,
)
from orchestwin.artifacts.test_plans import (
    TestLevel as PlanTestLevel,
)
from orchestwin.artifacts.test_plans import (
    TestPlan,
    create_planned_test_case,
    create_quality_gate,
    create_test_environment,
    create_test_plan,
)
from orchestwin.artifacts.test_plans import (
    TestPriority as PlanTestPriority,
)
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood

from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    CRITERION_ID,
    OWNER_ID,
    PROJECT_ID,
    PROTOTYPE_ID,
    REQUIREMENT_ID,
    design_version,
)

ARCHITECTURE_ID = UUID("00000000-0000-4000-8000-000000000601")
FRONTEND_COMPONENT_ID = UUID("00000000-0000-4000-8000-000000000610")
BACKEND_COMPONENT_ID = UUID("00000000-0000-4000-8000-000000000611")
CONNECTION_ID = UUID("00000000-0000-4000-8000-000000000620")
DECISION_ID = UUID("00000000-0000-4000-8000-000000000630")
ENTITY_ID = UUID("00000000-0000-4000-8000-000000000640")
API_OPERATION_ID = UUID("00000000-0000-4000-8000-000000000650")
RISK_ID = UUID("00000000-0000-4000-8000-000000000660")
ENVIRONMENT_ID = UUID("00000000-0000-4000-8000-000000000670")
TEST_CASE_ID = UUID("00000000-0000-4000-8000-000000000680")
QUALITY_GATE_ID = UUID("00000000-0000-4000-8000-000000000690")
TEST_PLAN_ID = UUID("00000000-0000-4000-8000-000000000700")
ARCHITECTURE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000710")
ARCHITECTURE_CREATED_AT = datetime(2026, 8, 21, 10, 0, tzinfo=UTC)


def frontend_component():
    """Create the traceable user-interface component."""
    return create_architecture_component(
        component_id=FRONTEND_COMPONENT_ID,
        code="CMP-001",
        name="Reservation interface",
        kind=ArchitectureComponentKind.USER_INTERFACE,
        responsibility="Render the approved reservation workflow and accessible feedback.",
        technology="Vue 3 and TypeScript",
        interfaces=("Reservation API",),
        requirement_ids=(REQUIREMENT_ID,),
    )


def backend_component():
    """Create the traceable application-service component."""
    return create_architecture_component(
        component_id=BACKEND_COMPONENT_ID,
        code="CMP-002",
        name="Reservation service",
        kind=ArchitectureComponentKind.APPLICATION_SERVICE,
        responsibility="Validate and persist reservation commands.",
        technology="Python and FastAPI",
        interfaces=("POST /reservations",),
        requirement_ids=(REQUIREMENT_ID,),
    )


def software_architecture() -> SoftwareArchitecture:
    """Create one complete architecture for the selected design."""
    connection = create_architecture_connection(
        connection_id=CONNECTION_ID,
        code="CON-001",
        source_component_id=FRONTEND_COMPONENT_ID,
        target_component_id=BACKEND_COMPONENT_ID,
        kind=ArchitectureConnectionKind.CALLS,
        description="The interface submits reservation commands to the service.",
        data_flows=("Reservation command", "Reservation confirmation"),
        requirement_ids=(REQUIREMENT_ID,),
    )
    decision = create_architecture_decision(
        decision_id=DECISION_ID,
        code="ADR-001",
        title="Use a small client-server architecture",
        context="The selected design needs a browser interface and durable reservation state.",
        decision=(
            "Separate the trusted interface from an application API in one deployable project."
        ),
        consequences=(
            "The interface and API can be tested independently.",
            "Deployment requires coordinating two runtime processes.",
        ),
        alternatives_considered=(
            "A browser-only application without durable server state.",
            "A distributed service architecture that exceeds the project scope.",
        ),
        requirement_ids=(REQUIREMENT_ID,),
    )
    entity = create_architecture_data_entity(
        entity_id=ENTITY_ID,
        code="ENT-001",
        name="Reservation",
        description="The durable booking record created by the approved workflow.",
        fields=("id: UUID", "guest_name: string"),
        owning_component_id=BACKEND_COMPONENT_ID,
        requirement_ids=(REQUIREMENT_ID,),
    )
    operation = create_architecture_api_operation(
        operation_id=API_OPERATION_ID,
        code="API-001",
        method=ApiMethod.POST,
        path="/reservations",
        summary="Create one reservation.",
        owning_component_id=BACKEND_COMPONENT_ID,
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
        component_ids=(BACKEND_COMPONENT_ID,),
        requirement_ids=(REQUIREMENT_ID,),
    )

    return create_software_architecture(
        architecture_id=ARCHITECTURE_ID,
        code="ARC-001",
        title="Reservation system architecture",
        style=ArchitectureStyle.CLIENT_SERVER,
        summary="A small client-server architecture grounded in the selected design.",
        selected_design_alternative_id=ALTERNATIVE_ONE_ID,
        prototype_id=PROTOTYPE_ID,
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        components=(backend_component(), frontend_component()),
        connections=(connection,),
        decisions=(decision,),
        data_entities=(entity,),
        api_operations=(operation,),
        risks=(risk,),
        quality_attributes=(
            "Accessible keyboard operation",
            "Deterministic testability",
        ),
        deployment_view=("Browser", "Application API", "PostgreSQL"),
    )


def architecture_test_plan() -> TestPlan:
    """Create a complete test plan for the architecture fixture."""
    environment = create_test_environment(
        environment_id=ENVIRONMENT_ID,
        code="ENV-001",
        name="Controlled browser and API environment",
        kind=EnvironmentKind.CONTAINER,
        description="A local environment with deterministic dependencies and no external calls.",
        configuration=("Browser viewport 1280x720", "PostgreSQL test database"),
    )
    planned_case = create_planned_test_case(
        test_case_id=TEST_CASE_ID,
        code="TST-001",
        title="Create a reservation end to end",
        objective="Verify the approved workflow and visible confirmation state.",
        level=PlanTestLevel.END_TO_END,
        automation=AutomationMode.AUTOMATED,
        priority=PlanTestPriority.CRITICAL,
        preconditions=("The interface, API, and test database are running.",),
        steps=(
            "Open the reservation screen.",
            "Submit valid reservation data.",
        ),
        expected_results=(
            "The API returns a unique reservation identifier.",
            "The interface displays the reservation confirmation.",
        ),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        architecture_component_ids=(FRONTEND_COMPONENT_ID, BACKEND_COMPONENT_ID),
        design_alternative_ids=(ALTERNATIVE_ONE_ID,),
        environment_ids=(ENVIRONMENT_ID,),
    )
    gate = create_quality_gate(
        gate_id=QUALITY_GATE_ID,
        code="QGT-001",
        title="Critical acceptance suite",
        criterion="All critical automated acceptance tests pass.",
        required_test_case_ids=(TEST_CASE_ID,),
        minimum_pass_rate=100,
        blocking=True,
    )

    return create_test_plan(
        plan_id=TEST_PLAN_ID,
        code="TPL-001",
        title="Reservation architecture test plan",
        strategy="Verify the selected design through traceable deterministic checks.",
        architecture_id=ARCHITECTURE_ID,
        selected_design_alternative_id=ALTERNATIVE_ONE_ID,
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        architecture_component_ids=(FRONTEND_COMPONENT_ID, BACKEND_COMPONENT_ID),
        environments=(environment,),
        test_cases=(planned_case,),
        quality_gates=(gate,),
        fixtures=("Minimal reservation fixture",),
    )


def architecture_package() -> ArchitecturePlanningPackage:
    """Create one complete package grounded in the selected Design Package."""
    return create_architecture_planning_package(
        project_id=PROJECT_ID,
        grounding=create_architecture_grounding(design_version()),
        architecture=software_architecture(),
        test_plan=architecture_test_plan(),
        open_questions=("Which validated execution profile will implement this plan?",),
    )


def architecture_version(
    *,
    version_number: int = 1,
    package: ArchitecturePlanningPackage | None = None,
) -> ArchitecturePackageVersion:
    """Create one immutable Architecture Package version."""
    resolved_package = package if package is not None else architecture_package()

    return ArchitecturePackageVersion(
        id=(
            ARCHITECTURE_VERSION_ID
            if version_number == 1
            else UUID(int=ARCHITECTURE_VERSION_ID.int + version_number)
        ),
        project_id=PROJECT_ID,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
        package=resolved_package,
        content_hash=resolved_package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=ARCHITECTURE_CREATED_AT,
    )


__all__ = [
    "ARCHITECTURE_CREATED_AT",
    "ARCHITECTURE_ID",
    "ARCHITECTURE_VERSION_ID",
    "BACKEND_COMPONENT_ID",
    "FRONTEND_COMPONENT_ID",
    "TEST_PLAN_ID",
    "architecture_package",
    "architecture_test_plan",
    "architecture_version",
    "backend_component",
    "frontend_component",
    "software_architecture",
]
