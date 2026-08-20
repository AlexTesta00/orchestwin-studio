"""Shared deterministic fixtures for Sprint 06 design artifact tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from orchestwin.artifacts.design import (
    DesignApproach,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
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
from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
)
from test.python.artifacts.design_packages import (
    DesignPackageVersion,
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUIREMENTS_VERSION_ID = UUID("00000000-0000-4000-8000-000000000003")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
ALTERNATIVE_ONE_ID = UUID("00000000-0000-4000-8000-000000000070")
ALTERNATIVE_TWO_ID = UUID("00000000-0000-4000-8000-000000000071")
PROTOTYPE_ID = UUID("00000000-0000-4000-8000-000000000080")
DESIGN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000090")
CREATED_AT = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def requirement_context(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact Requirements-stage context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create the exact User Twin used throughout design tests."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def requirements_version() -> RequirementsSpecificationVersion:
    """Create one complete immutable Requirements baseline."""
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source,),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=requirement_context(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=requirement_context(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=requirement_context(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=REQUIREMENTS_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def design_alternative(
    *,
    index: int,
):
    """Create one of two deliberately different design alternatives."""
    alternative_id = ALTERNATIVE_ONE_ID if index == 1 else ALTERNATIVE_TWO_ID
    approach = DesignApproach.GUIDED_WORKFLOW if index == 1 else DesignApproach.DASHBOARD_FIRST
    workflow = create_design_workflow(
        workflow_id=UUID(int=100 + index),
        code=f"FLOW-{index:03d}",
        title="Create a reservation",
        steps=("Review availability.", "Save the reservation."),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )

    return create_design_alternative(
        alternative_id=alternative_id,
        code=f"DES-{index:03d}",
        approach=approach,
        title=("Guided reservation flow" if index == 1 else "Reservation operations dashboard"),
        summary=(
            "Guide the receptionist through one decision at a time."
            if index == 1
            else "Keep availability and reservation actions visible together."
        ),
        rationale=(
            "Reduce cognitive load for occasional users."
            if index == 1
            else "Reduce navigation for experienced users."
        ),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        user_twin_references=(twin_reference(),),
        workflows=(workflow,),
        information_architecture=("Availability", "Reservation", "Confirmation"),
        accessibility_considerations=("All controls have persistent labels",),
        security_considerations=("Guest data is minimized in summaries",),
        advantages=("Clear progression" if index == 1 else "Fast access to frequent actions",),
        trade_offs=("More navigation" if index == 1 else "Higher information density",),
    )


def critique(
    *,
    index: int,
):
    """Create one synthetic critique for the selected alternative index."""
    alternative_id = ALTERNATIVE_ONE_ID if index == 1 else ALTERNATIVE_TWO_ID
    provenance = ObservationProvenance.from_references(
        (
            EvidenceReference(
                source_kind=EvidenceSourceKind.MODEL_OUTPUT,
                source_id="fake-design-provider:1",
                source_version=1,
                content_hash="d" * 64,
                locator=f"alternatives.DES-{index:03d}",
                summary="Deterministic synthetic User Twin critique.",
            ),
        )
    )

    return create_synthetic_design_critique(
        critique_id=UUID(int=200 + index),
        code=f"CRQ-{index:03d}",
        design_alternative_id=alternative_id,
        user_twin_reference=twin_reference(),
        strengths=("The main task is visible.",),
        concerns=("The flow may require adaptation for different experience levels.",),
        suggested_changes=("Preserve visible recovery actions.",),
        provenance=provenance,
        confidence=ConfidenceScore(0.65),
        rationale="The critique is inferred from the approved User Twin profile.",
    )


def prototype():
    """Create a prototype for the owner-selected first alternative."""
    input_element = create_prototype_element(
        element_id=UUID(int=301),
        code="ELM-001",
        kind=PrototypeElementKind.TEXT_INPUT,
        content="Guest name",
        accessible_name="Guest name",
        requirement_ids=(REQUIREMENT_ID,),
        field_name="guest_name",
        required=True,
    )
    button = create_prototype_element(
        element_id=UUID(int=302),
        code="ELM-002",
        kind=PrototypeElementKind.BUTTON,
        content="Save reservation",
        accessible_name="Save reservation",
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    status = create_prototype_element(
        element_id=UUID(int=303),
        code="ELM-003",
        kind=PrototypeElementKind.STATUS,
        content="Reservation saved",
    )
    entry = create_prototype_screen(
        screen_id=UUID(int=310),
        code="SCR-001",
        title="Create reservation",
        state=PrototypeScreenState.DEFAULT,
        elements=(input_element, button),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    confirmation = create_prototype_screen(
        screen_id=UUID(int=311),
        code="SCR-002",
        title="Reservation confirmation",
        state=PrototypeScreenState.SUCCESS,
        elements=(status,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    transition = create_prototype_transition(
        transition_id=UUID(int=320),
        code="TRN-001",
        source_screen_id=entry.id,
        trigger_element_id=button.id,
        target_screen_id=confirmation.id,
        outcome="The confirmation screen becomes visible.",
    )

    return create_declarative_prototype(
        prototype_id=PROTOTYPE_ID,
        code="PRT-001",
        title="Reservation flow prototype",
        design_alternative_id=ALTERNATIVE_ONE_ID,
        entry_screen_id=entry.id,
        screens=(entry, confirmation),
        transitions=(transition,),
        supported_viewports=(PrototypeViewport.MOBILE, PrototypeViewport.DESKTOP),
    )


def design_package(
    *,
    selected: bool = True,
    include_prototype: bool = True,
):
    """Create one complete Design Package fixture."""
    requirements = requirements_version()
    owner_selection = ALTERNATIVE_ONE_ID if selected else None
    package_prototype = prototype() if selected and include_prototype else None

    return create_design_exploration_package(
        project_id=PROJECT_ID,
        grounding=create_design_grounding(requirements),
        alternatives=(design_alternative(index=2), design_alternative(index=1)),
        critiques=(critique(index=2), critique(index=1)),
        recommended_alternative_id=ALTERNATIVE_ONE_ID,
        owner_selected_alternative_id=owner_selection,
        prototype=package_prototype,
        concerns=(
            create_design_concern(
                concern_id=UUID(int=400),
                code="DRK-001",
                summary="Expert users may find the guided flow slower.",
                mitigation="Keep keyboard shortcuts visible in later revisions.",
                requirement_ids=(REQUIREMENT_ID,),
                design_alternative_ids=(ALTERNATIVE_ONE_ID,),
            ),
        ),
        open_questions=("Should expert mode be included in the first release?",),
    )


def design_version(
    *,
    version_number: int = 1,
    package=None,
) -> DesignPackageVersion:
    """Create one immutable Design Package version."""
    resolved_package = package if package is not None else design_package()

    return DesignPackageVersion(
        id=DESIGN_VERSION_ID if version_number == 1 else UUID(int=500 + version_number),
        project_id=PROJECT_ID,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
        package=resolved_package,
        content_hash=resolved_package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
