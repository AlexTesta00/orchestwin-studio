"""Deterministic fake adapter for governed architecture proposals."""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid5

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.artifacts.architecture import (
    ArchitectureComponent,
    ArchitectureComponentKind,
    ArchitectureConnectionKind,
    ArchitectureStyle,
    create_architecture_component,
    create_architecture_connection,
    create_architecture_decision,
    create_architecture_risk,
    create_software_architecture,
)
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePlanningPackage,
    create_architecture_grounding,
    create_architecture_planning_package,
)
from orchestwin.artifacts.test_plans import (
    PlannedTestCase,
    TestAutomation,
    TestEnvironmentKind,
    TestLevel,
    TestPriority,
    create_planned_test_case,
    create_quality_gate,
    create_test_environment,
    create_test_plan,
)
from orchestwin.models.architecture import (
    ArchitectureProposalIssueCode,
    ArchitectureProposalProviderKind,
    ArchitectureProposalRequest,
    ArchitectureProposalResult,
    ArchitectureProposalStatus,
)
from orchestwin.projects.requirements import Requirement, UserStory
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    RiskImpact,
    RiskLikelihood,
    VerificationMethod,
)

FAKE_ARCHITECTURE_PROVIDER_ID: Final = "fake-deterministic-architecture"
FAKE_ARCHITECTURE_PROVIDER_VERSION: Final = 1

_FAKE_ARCHITECTURE_NAMESPACE: Final = UUID("3dc3339d-9255-49a1-9de3-b312a1aeb823")
_MAX_TITLE_FRAGMENT_LENGTH: Final = 120


class FakeDeterministicArchitectureAdapter:
    """Conservative local provider with no network or credential dependency."""

    async def propose(
        self,
        request: ArchitectureProposalRequest,
    ) -> ArchitectureProposalResult:
        """Produce one deterministic architecture and traceable test plan."""
        if AgentIdentifier.SOFTWARE_ARCHITECT not in request.team.selected_agent_ids:
            return _rejected(ArchitectureProposalIssueCode.SOFTWARE_ARCHITECT_REQUIRED)

        if AgentIdentifier.QA_TEST_ENGINEER not in request.team.selected_agent_ids:
            return _rejected(ArchitectureProposalIssueCode.QA_TEST_ENGINEER_REQUIRED)

        if not request.design.ready_for_architecture:
            return _rejected(ArchitectureProposalIssueCode.DESIGN_SELECTION_REQUIRED)

        if not _has_grounded_input(request):
            return _rejected(ArchitectureProposalIssueCode.GROUNDED_INPUT_REQUIRED)

        try:
            package = _build_package(request)
        except ValueError:
            return _rejected(ArchitectureProposalIssueCode.INVALID_PROVIDER_OUTPUT)

        return ArchitectureProposalResult(
            status=ArchitectureProposalStatus.PROPOSED,
            provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id=FAKE_ARCHITECTURE_PROVIDER_ID,
            provider_version=FAKE_ARCHITECTURE_PROVIDER_VERSION,
            package=package,
        )


def _has_grounded_input(request: ArchitectureProposalRequest) -> bool:
    """Require concrete requirements, criteria, an owner selection, and a prototype."""
    specification = request.requirements.version.specification
    package = request.design.version.package
    selected_id = package.owner_selected_alternative_id
    prototype = package.prototype

    return bool(
        specification.requirements
        and specification.acceptance_criteria
        and selected_id is not None
        and prototype is not None
        and prototype.design_alternative_id == selected_id
        and any(alternative.id == selected_id for alternative in package.alternatives)
    )


def _build_package(request: ArchitectureProposalRequest) -> ArchitecturePlanningPackage:
    """Build a complete Architecture Package from exact governed inputs."""
    specification = request.requirements.version.specification
    design_package = request.design.version.package
    selected_id = design_package.owner_selected_alternative_id
    prototype = design_package.prototype

    if selected_id is None or prototype is None:
        raise ValueError("architecture generation requires a selected design and prototype")

    selected = next(
        alternative for alternative in design_package.alternatives if alternative.id == selected_id
    )
    request_hash = request.content_hash
    requirement_ids = tuple(requirement.id for requirement in specification.requirements)
    criterion_ids = tuple(criterion.id for criterion in specification.acceptance_criteria)
    interaction_component = create_architecture_component(
        component_id=_artifact_id(request_hash, "component", "interaction"),
        code="CMP-001",
        name="Interaction surface",
        kind=ArchitectureComponentKind.USER_INTERFACE,
        responsibility=(
            "Render the owner-selected declarative prototype and preserve its accessible "
            "interaction structure."
        ),
        technology="Approved target interface stack with trusted declarative rendering",
        interfaces=("Application core boundary",),
        requirement_ids=requirement_ids,
    )
    application_component = create_architecture_component(
        component_id=_artifact_id(request_hash, "component", "application-core"),
        code="CMP-002",
        name="Application core",
        kind=ArchitectureComponentKind.APPLICATION_SERVICE,
        responsibility=(
            "Implement the approved requirements behind explicit application interfaces and "
            "keep stack-specific side effects at the boundary."
        ),
        technology="Target-stack application services selected after architecture approval",
        interfaces=("Use-case commands", "Use-case queries"),
        requirement_ids=requirement_ids,
        assumptions=(
            "The concrete execution profile remains subject to later capability negotiation.",
        ),
    )
    components = (interaction_component, application_component)
    component_ids = tuple(component.id for component in components)
    architecture_id = _artifact_id(request_hash, "architecture", "primary")
    architecture = create_software_architecture(
        architecture_id=architecture_id,
        code="ARC-001",
        title=(
            "Architecture for "
            f"{_bounded_fragment(selected.title, maximum_length=_MAX_TITLE_FRAGMENT_LENGTH)}"
        ),
        style=ArchitectureStyle.MODULAR_MONOLITH,
        summary=(
            "A small modular architecture that separates the trusted interaction surface from "
            "the application core while preserving one coherent deployment boundary."
        ),
        selected_design_alternative_id=selected_id,
        prototype_id=prototype.id,
        requirement_ids=requirement_ids,
        acceptance_criterion_ids=criterion_ids,
        components=components,
        connections=(
            create_architecture_connection(
                connection_id=_artifact_id(request_hash, "connection", "ui-to-core"),
                code="CON-001",
                source_component_id=interaction_component.id,
                target_component_id=application_component.id,
                kind=ArchitectureConnectionKind.CALLS,
                description=(
                    "The interaction surface invokes explicit application use cases and receives "
                    "structured outcomes."
                ),
                data_flows=("Validated user intent", "Structured application result"),
                requirement_ids=requirement_ids,
            ),
        ),
        decisions=(
            create_architecture_decision(
                decision_id=_artifact_id(request_hash, "decision", "modular-boundary"),
                code="ADR-001",
                title="Use a small modular application boundary",
                context=(
                    "The approved scope requires traceable implementation and testing without "
                    "introducing distributed-system complexity."
                ),
                decision=(
                    "Separate interaction concerns from application behavior inside one modular "
                    "project and defer stack-specific adapters to the execution profile."
                ),
                consequences=(
                    "Requirements and tests can be traced to explicit components.",
                    "A later execution profile must select concrete framework adapters.",
                ),
                alternatives_considered=(
                    "A single undifferentiated component with implicit boundaries.",
                    "A distributed service architecture beyond the approved small-project scope.",
                ),
                requirement_ids=requirement_ids,
            ),
        ),
        risks=(
            create_architecture_risk(
                risk_id=_artifact_id(request_hash, "risk", "execution-profile"),
                code="ARK-001",
                summary=(
                    "The approved target stack may not yet have a validated Level D execution "
                    "profile."
                ),
                likelihood=RiskLikelihood.POSSIBLE,
                impact=RiskImpact.HIGH,
                mitigation=(
                    "Perform explicit capability negotiation before implementation and expose any "
                    "degradation to DESIGN_ONLY_LEVEL_C."
                ),
                component_ids=component_ids,
                requirement_ids=requirement_ids,
            ),
        ),
        quality_attributes=(
            "Accessibility constraints from the selected design remain implementation inputs.",
            "Every approved requirement and acceptance criterion has planned verification.",
            "Framework and external-service choices remain isolated behind explicit boundaries.",
        ),
        deployment_view=(
            "Owner-selected user interface",
            "Application core",
            "Execution-profile adapters selected after Gate 6",
        ),
        assumptions=(
            (
                "No concrete framework, database, or external provider is approved by this "
                "fake adapter."
            ),
        ),
        open_questions=(
            "Which validated or experimental execution profile should implement this architecture?",
            "Which approved requirements require durable data after capability negotiation?",
        ),
    )
    test_plan = _build_test_plan(
        request_hash=request_hash,
        architecture_id=architecture.id,
        selected_design_alternative_id=selected_id,
        components=components,
        requirements=specification.requirements,
        stories=specification.user_stories,
        criteria=specification.acceptance_criteria,
    )

    return create_architecture_planning_package(
        project_id=request.project_id,
        grounding=create_architecture_grounding(request.design.version),
        architecture=architecture,
        test_plan=test_plan,
        open_questions=(
            "Which execution profile can honestly provide the requested capability level?",
            "Which architecture assumptions require owner revision before Gate 6?",
        ),
    )


def _build_test_plan(
    *,
    request_hash: str,
    architecture_id: UUID,
    selected_design_alternative_id: UUID,
    components: tuple[ArchitectureComponent, ...],
    requirements: tuple[Requirement, ...],
    stories: tuple[UserStory, ...],
    criteria: tuple[AcceptanceCriterion, ...],
):
    """Build a deterministic plan that covers every approved requirement and criterion."""
    environment = create_test_environment(
        environment_id=_artifact_id(request_hash, "environment", "deterministic-local"),
        code="ENV-001",
        name="Deterministic local verification environment",
        kind=TestEnvironmentKind.LOCAL,
        description=(
            "A controlled environment selected by the eventual execution profile, with external "
            "services mocked by default."
        ),
        configuration=(
            "Network disabled outside explicitly approved dependency setup.",
            "Exact tool versions recorded by the selected execution profile.",
        ),
    )
    story_requirements = {story.id: story.requirement_ids for story in stories}
    component_ids = tuple(component.id for component in components)
    cases: list[PlannedTestCase] = []
    covered_requirements: set[UUID] = set()

    for ordinal, criterion in enumerate(criteria, start=1):
        criterion_requirements = set(criterion.requirement_ids)
        for story_id in criterion.user_story_ids:
            criterion_requirements.update(story_requirements.get(story_id, ()))

        requirement_ids = tuple(sorted(criterion_requirements, key=lambda value: value.hex))
        if not requirement_ids:
            raise ValueError("acceptance criterion has no resolvable requirement traceability")

        covered_requirements.update(requirement_ids)
        level, automation = _verification_strategy(criterion.verification_method)
        cases.append(
            create_planned_test_case(
                test_case_id=_artifact_id(
                    request_hash,
                    "test-case",
                    f"criterion:{criterion.id}",
                ),
                code=f"TST-{ordinal:03d}",
                title=f"Verify {criterion.code}",
                objective=criterion.statement,
                level=level,
                automation=automation,
                priority=TestPriority.CRITICAL,
                preconditions=(
                    "The approved architecture has been implemented by the selected profile.",
                ),
                steps=(
                    f"Arrange the state required by {criterion.code}.",
                    "Exercise the approved behavior through its public boundary.",
                    "Capture deterministic evidence and preserve raw output.",
                ),
                expected_results=(criterion.statement,),
                requirement_ids=requirement_ids,
                acceptance_criterion_ids=(criterion.id,),
                architecture_component_ids=component_ids,
                design_alternative_ids=(selected_design_alternative_id,),
                environment_ids=(environment.id,),
            )
        )

    next_ordinal = len(cases) + 1
    for requirement in requirements:
        if requirement.id in covered_requirements:
            continue

        cases.append(
            create_planned_test_case(
                test_case_id=_artifact_id(
                    request_hash,
                    "test-case",
                    f"requirement:{requirement.id}",
                ),
                code=f"TST-{next_ordinal:03d}",
                title=f"Verify {requirement.code}",
                objective=requirement.statement,
                level=TestLevel.COMPONENT,
                automation=TestAutomation.HYBRID,
                priority=TestPriority.HIGH,
                steps=(
                    "Inspect the implemented component behavior against the requirement.",
                    "Record deterministic evidence or an explicit manual-review result.",
                ),
                expected_results=(requirement.statement,),
                requirement_ids=(requirement.id,),
                acceptance_criterion_ids=(),
                architecture_component_ids=component_ids,
                design_alternative_ids=(selected_design_alternative_id,),
                environment_ids=(environment.id,),
            )
        )
        next_ordinal += 1

    test_case_ids = tuple(case.id for case in cases)

    return create_test_plan(
        plan_id=_artifact_id(request_hash, "test-plan", "primary"),
        code="TPL-001",
        title="Traceable architecture test plan",
        strategy=(
            "Verify every approved requirement and acceptance criterion through deterministic "
            "checks where possible and explicit human review where automation is not justified."
        ),
        architecture_id=architecture_id,
        selected_design_alternative_id=selected_design_alternative_id,
        requirement_ids=(requirement.id for requirement in requirements),
        acceptance_criterion_ids=(criterion.id for criterion in criteria),
        architecture_component_ids=component_ids,
        environments=(environment,),
        test_cases=cases,
        quality_gates=(
            create_quality_gate(
                gate_id=_artifact_id(request_hash, "quality-gate", "approved-scope"),
                code="QGT-001",
                title="Approved-scope verification",
                criterion=(
                    "All critical and high-priority checks required by the approved scope pass or "
                    "receive an explicit recorded human decision."
                ),
                required_test_case_ids=test_case_ids,
                minimum_pass_rate=100,
                blocking=True,
            ),
        ),
        fixtures=(
            "Approved Requirements Specification snapshot",
            "Approved Design Package and declarative prototype snapshot",
        ),
        assumptions=(
            "Concrete commands and runners are supplied only by an approved execution profile.",
        ),
        open_questions=(
            (
                "Which profile-specific contract, integration, accessibility, and security "
                "checks are required?"
            ),
        ),
    )


def _verification_strategy(
    method: VerificationMethod,
) -> tuple[TestLevel, TestAutomation]:
    """Map existing verification semantics without inventing an execution tool."""
    if method is VerificationMethod.AUTOMATED_TEST:
        return TestLevel.END_TO_END, TestAutomation.AUTOMATED

    if method in {VerificationMethod.MANUAL_REVIEW, VerificationMethod.INSPECTION}:
        return TestLevel.MANUAL_REVIEW, TestAutomation.MANUAL

    if method is VerificationMethod.DEMONSTRATION:
        return TestLevel.END_TO_END, TestAutomation.HYBRID

    return TestLevel.COMPONENT, TestAutomation.HYBRID


def _artifact_id(
    request_hash: str,
    artifact_kind: str,
    identity: str,
) -> UUID:
    """Derive a stable UUID from exact request content and logical identity."""
    return uuid5(
        _FAKE_ARCHITECTURE_NAMESPACE,
        f"{request_hash}:{artifact_kind}:{identity}",
    )


def _bounded_fragment(value: str, *, maximum_length: int) -> str:
    """Keep approved normalized text safe for bounded generated fields."""
    if len(value) <= maximum_length:
        return value

    return f"{value[: maximum_length - 3].rstrip()}..."


def _rejected(issue: ArchitectureProposalIssueCode) -> ArchitectureProposalResult:
    """Return one typed deterministic rejection."""
    return ArchitectureProposalResult(
        status=ArchitectureProposalStatus.REJECTED,
        provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id=FAKE_ARCHITECTURE_PROVIDER_ID,
        provider_version=FAKE_ARCHITECTURE_PROVIDER_VERSION,
        issue=issue,
    )


__all__ = [
    "FAKE_ARCHITECTURE_PROVIDER_ID",
    "FAKE_ARCHITECTURE_PROVIDER_VERSION",
    "FakeDeterministicArchitectureAdapter",
]
