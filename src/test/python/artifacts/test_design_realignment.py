from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.artifacts.bound_mockups import BoundGeneratedMockup, create_bound_mockup
from orchestwin.artifacts.design import (
    DesignAlternative,
    DesignApproach,
    SyntheticDesignCritique,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
    create_design_concern,
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.design_realignment import (
    DesignRealignmentError,
    DesignRealignmentIssue,
    design_is_aligned,
    design_realignment_issue,
    item_codes,
    missing_item_ids,
    realign_design,
    realigned_design_version,
    uncovered_requirement_codes,
)
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.artifacts.visual_language import (
    VisualLanguage,
    create_twin_fit,
    create_visual_language,
)
from orchestwin.knowledge.sources import StageIdentity, stage_consistency_issue
from orchestwin.projects.requirements import (
    Requirement,
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
    RequirementsSpecification,
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
)

from .design_fixtures import requirement_context
from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_FIRST,
    BASE_SECOND,
    LIGHT_CHOICES,
    build,
    requirement_ids,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-00000000e000")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-00000000e001")
OWNER_ID = UUID("00000000-0000-4000-8000-00000000e002")
FIRST_REQUIREMENTS_ID = UUID("00000000-0000-4000-8000-00000000e011")
CHANGED_REQUIREMENTS_ID = UUID("00000000-0000-4000-8000-00000000e012")
DESIGN_VERSION_ID = UUID("00000000-0000-4000-8000-00000000e021")
REALIGNED_VERSION_ID = UUID("00000000-0000-4000-8000-00000000e022")
GUIDED_ID = UUID("00000000-0000-4000-8000-00000000e031")
DASHBOARD_ID = ALTERNATIVE_ID
CHECK_IN_STORY = UUID("00000000-0000-4000-8000-00000000e041")
NIGHT_REPORT_STORY = UUID("00000000-0000-4000-8000-00000000e042")
CHECK_IN_CRITERION = UUID("00000000-0000-4000-8000-00000000e051")
NIGHT_REPORT_CRITERION = UUID("00000000-0000-4000-8000-00000000e052")
SCENARIO_ID = UUID("00000000-0000-4000-8000-00000000e061")
DONE_ID = UUID("00000000-0000-4000-8000-00000000e071")
CONCERN_ID = UUID("00000000-0000-4000-8000-00000000e081")
WRITTEN_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
CHANGED_AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
REALIGNED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CODES = ("REQ-001", "REQ-002", "REQ-003", "REQ-004")
FIRST_CODES = CODES[:3]
REQUIREMENT_IDS = requirement_ids(CODES)
CHECK_IN, NIGHT_REPORT, AUDIT_LOG, WELCOME = (REQUIREMENT_IDS[code] for code in CODES)
BRIEF = requirement_context(RequirementsContextKind.PROJECT_BRIEF, 11)
TEAM = requirement_context(RequirementsContextKind.AGENT_TEAM, 12)
SECOND_TEAM = RequirementsContextReference(
    kind=RequirementsContextKind.AGENT_TEAM,
    artifact_id=UUID("00000000-0000-4000-8000-00000000e093"),
    version_number=2,
    content_hash="f" * 64,
)
FIRST_MODELING = requirement_context(RequirementsContextKind.USER_MODELING, 13)
SECOND_MODELING = RequirementsContextReference(
    kind=RequirementsContextKind.USER_MODELING,
    artifact_id=UUID("00000000-0000-4000-8000-00000000e092"),
    version_number=2,
    content_hash="e" * 64,
)
RECEPTIONIST = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-00000000e101"),
    version_number=1,
    content_hash="1" * 64,
    name="Receptionist Twin",
)
AUDITOR = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-00000000e102"),
    version_number=1,
    content_hash="2" * 64,
    name="Night Auditor Twin",
)
FRONT_DESK = UserTwinVersionReference(
    twin_id=RECEPTIONIST.twin_id,
    version_number=2,
    content_hash="3" * 64,
    name="Front Desk Twin",
)
CONCIERGE = UserTwinVersionReference(
    twin_id=UUID("00000000-0000-4000-8000-00000000e103"),
    version_number=1,
    content_hash="4" * 64,
    name="Concierge Twin",
)
TEXTS = {
    "REQ-001": ("Check guests in", "The system must check guests in at the front desk."),
    "REQ-002": ("Print the night report", "The system must print the night audit report."),
    "REQ-003": ("Keep an audit log", "The system must keep an audit log of every change."),
    "REQ-004": ("Send a welcome message", "The system must greet every guest after check-in."),
}
FITS = {
    RECEPTIONIST.twin_id: "Large rows suit a desk that is busy at check-in.",
    AUDITOR.twin_id: "A short report suits the last check of the night.",
}
PROVENANCE = ObservationProvenance.from_references(
    (
        EvidenceReference(
            source_kind=EvidenceSourceKind.MODEL_OUTPUT,
            source_id="fake-design-provider:1",
            source_version=1,
            content_hash="d" * 64,
            locator="critiques",
            summary="Deterministic synthetic User Twin critique.",
        ),
    )
)
ASSERTIONS = ("The night report stays one click away.",)
VERDICT = ("Utile, con riserve", "Trovo subito gli arrivi, ma vorrei la stampa più vicina.")


def requirement(
    code: str,
    *,
    actors: tuple[UserTwinVersionReference, ...],
    reworded: bool,
) -> Requirement:
    title, statement = TEXTS[code]
    if reworded:
        title, statement = f"{title} without waiting", statement.replace("must", "shall")
    return create_requirement(
        requirement_id=REQUIREMENT_IDS[code],
        code=code,
        title=title,
        statement=statement,
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(
            RequirementSourceReference(
                kind=RequirementSourceKind.PROJECT_BRIEF,
                source_id=str(BRIEF.artifact_id),
                source_version=BRIEF.version_number,
                content_hash=BRIEF.content_hash,
                locator="functional_requirements[0]",
            ),
        ),
        user_twin_references=dict.fromkeys(actors),
    )


def specification(
    *,
    codes: tuple[str, ...] = FIRST_CODES,
    twins: tuple[UserTwinVersionReference, ...] = (RECEPTIONIST, AUDITOR),
    modeling: RequirementsContextReference = FIRST_MODELING,
    team: RequirementsContextReference = TEAM,
    reworded: bool = False,
) -> RequirementsSpecification:
    current = {reference.twin_id: reference for reference in twins}
    receptionist = current[RECEPTIONIST.twin_id]
    auditor = current.get(AUDITOR.twin_id, receptionist)
    actors = {
        "REQ-001": (receptionist, auditor),
        "REQ-002": (auditor,),
        "REQ-003": (),
        "REQ-004": (receptionist,),
    }
    requirements = [requirement(code, actors=actors[code], reworded=reworded) for code in codes]
    stories = [
        create_user_story(
            story_id=CHECK_IN_STORY,
            code="USR-001",
            user_twin_reference=receptionist,
            goal="check a guest in",
            benefit="the room is ready on arrival",
            requirement_ids=(CHECK_IN,),
        )
    ]
    criteria = [
        create_acceptance_criterion(
            criterion_id=CHECK_IN_CRITERION,
            code="AC-001",
            statement="A checked-in guest has a room.",
            verification_method=VerificationMethod.AUTOMATED_TEST,
            requirement_ids=(CHECK_IN,),
            user_story_ids=(CHECK_IN_STORY,),
        )
    ]
    if "REQ-002" in codes:
        stories.append(
            create_user_story(
                story_id=NIGHT_REPORT_STORY,
                code="USR-002",
                user_twin_reference=auditor,
                goal="print the night report",
                benefit="the day closes with correct totals",
                requirement_ids=(NIGHT_REPORT,),
            )
        )
        criteria.append(
            create_acceptance_criterion(
                criterion_id=NIGHT_REPORT_CRITERION,
                code="AC-002",
                statement="The night report lists every payment.",
                verification_method=VerificationMethod.MANUAL_REVIEW,
                requirement_ids=(NIGHT_REPORT,),
                user_story_ids=(NIGHT_REPORT_STORY,),
            )
        )
    return create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=BRIEF,
        agent_team_reference=team,
        user_modeling_reference=modeling,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        user_twin_references=twins,
        requirements=requirements,
        user_stories=stories,
        acceptance_criteria=criteria,
        scenarios=(
            create_usage_scenario(
                scenario_id=SCENARIO_ID,
                code="SCN-001",
                title="Check in a guest",
                actor=receptionist,
                preconditions=("The room is clean.",),
                trigger="A guest arrives.",
                steps=("Find the booking.", "Assign the room."),
                expected_outcome="The guest receives the key.",
                requirement_ids=(CHECK_IN,),
                acceptance_criterion_ids=(CHECK_IN_CRITERION,),
            ),
        ),
        risks=(),
        definition_of_done=(
            create_definition_of_done_item(
                item_id=DONE_ID,
                code="DOD-001",
                statement="Every acceptance test passes.",
                verification_method=VerificationMethod.AUTOMATED_TEST,
                applicability=DefinitionOfDoneApplicability.REQUIRED,
                requirement_ids=tuple(REQUIREMENT_IDS[code] for code in codes),
            ),
        ),
    )


def requirements_version(
    value: RequirementsSpecification,
    *,
    version_id: UUID = FIRST_REQUIREMENTS_ID,
    version_number: int = 1,
    created_at: datetime = WRITTEN_AT,
) -> RequirementsSpecificationVersion:
    return RequirementsSpecificationVersion(
        id=version_id,
        project_id=value.project_id,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
        specification=value,
        content_hash=value.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=created_at,
    )


def first_requirements() -> RequirementsSpecificationVersion:
    return requirements_version(specification())


def changed_requirements(**changes) -> RequirementsSpecificationVersion:
    return requirements_version(
        specification(**changes),
        version_id=CHANGED_REQUIREMENTS_ID,
        version_number=2,
        created_at=CHANGED_AT,
    )


def reworded_requirements() -> RequirementsSpecificationVersion:
    return changed_requirements(reworded=True)


def requirements_with_a_new_requirement() -> RequirementsSpecificationVersion:
    return changed_requirements(codes=CODES)


def requirements_without_a_cited_requirement() -> RequirementsSpecificationVersion:
    return changed_requirements(codes=("REQ-001", "REQ-003"))


def requirements_without_an_uncited_requirement() -> RequirementsSpecificationVersion:
    return changed_requirements(codes=("REQ-001", "REQ-002"))


def requirements_with_revised_twins() -> RequirementsSpecificationVersion:
    return changed_requirements(twins=(FRONT_DESK, AUDITOR), modeling=SECOND_MODELING)


def requirements_with_another_twin() -> RequirementsSpecificationVersion:
    return changed_requirements(twins=(RECEPTIONIST, AUDITOR, CONCIERGE), modeling=SECOND_MODELING)


def requirements_with_new_perspectives() -> RequirementsSpecificationVersion:
    return changed_requirements(
        twins=(FRONT_DESK, AUDITOR), modeling=SECOND_MODELING, team=SECOND_TEAM
    )


def bound_mockup(
    second: str = BASE_SECOND,
    extra: Mapping[str, UUID] | None = None,
) -> BoundGeneratedMockup:
    return create_bound_mockup(
        mockup=build(BASE_FIRST, second),
        requirement_ids_by_code={"REQ-001": CHECK_IN, "REQ-002": NIGHT_REPORT, **(extra or {})},
    )


def visual_language(twins: tuple[UserTwinVersionReference, ...]) -> VisualLanguage:
    return create_visual_language(
        choices=LIGHT_CHOICES,
        product_name="Front desk",
        rationale="A calm dashboard keeps the arrivals and the night report in one place.",
        twin_fit=tuple(
            create_twin_fit(reference=twin, statement=FITS[twin.twin_id]) for twin in twins
        ),
    )


def alternative(
    alternative_id: UUID,
    index: int,
    twins: tuple[UserTwinVersionReference, ...],
) -> DesignAlternative:
    guided = index == 1
    return create_design_alternative(
        alternative_id=alternative_id,
        code=f"DES-{index:03d}",
        approach=DesignApproach.GUIDED_WORKFLOW if guided else DesignApproach.DASHBOARD_FIRST,
        title="Guided front desk" if guided else "Front desk dashboard",
        summary=(
            "Guide the receptionist one step at a time."
            if guided
            else "Keep the arrivals and the night report visible together."
        ),
        rationale=(
            "Occasional staff need one decision at a time."
            if guided
            else "Experienced staff need everything in one view."
        ),
        requirement_ids=(CHECK_IN, NIGHT_REPORT),
        user_story_ids=(CHECK_IN_STORY, NIGHT_REPORT_STORY),
        acceptance_criterion_ids=(CHECK_IN_CRITERION, NIGHT_REPORT_CRITERION),
        user_twin_references=twins,
        workflows=(
            create_design_workflow(
                workflow_id=UUID(f"00000000-0000-4000-8000-00000000e2{index}1"),
                code=f"FLOW-{2 * index - 1:03d}",
                title="Check a guest in",
                steps=("Find the booking.", "Assign the room."),
                requirement_ids=(CHECK_IN,),
                user_story_ids=(CHECK_IN_STORY,),
            ),
            create_design_workflow(
                workflow_id=UUID(f"00000000-0000-4000-8000-00000000e2{index}2"),
                code=f"FLOW-{2 * index:03d}",
                title="Close the day",
                steps=("Print the night report.",),
                requirement_ids=(NIGHT_REPORT,),
                user_story_ids=(NIGHT_REPORT_STORY,),
            ),
        ),
        information_architecture=("Arrivals", "Rooms", "Night report"),
        accessibility_considerations=("Every action is reachable from the keyboard",),
        security_considerations=("Guest data stays at the front desk",),
        advantages=("Clear progression" if guided else "Fast access to every task",),
        trade_offs=("More steps" if guided else "Denser screens",),
        visual_language=None if guided else visual_language(twins),
    )


def critiques(twins: tuple[UserTwinVersionReference, ...]) -> tuple[SyntheticDesignCritique, ...]:
    pairs = [
        (alternative_id, twin) for alternative_id in (GUIDED_ID, DASHBOARD_ID) for twin in twins
    ]
    return tuple(
        create_synthetic_design_critique(
            critique_id=UUID(f"00000000-0000-4000-8000-00000000e3{number:02d}"),
            code=f"CRQ-{number:03d}",
            design_alternative_id=alternative_id,
            user_twin_reference=twin,
            strengths=("The main task is visible.",),
            concerns=("The night report may be hard to find.",),
            provenance=PROVENANCE,
            confidence=ConfidenceScore(0.6),
            rationale="The critique is inferred from the approved User Twin profile.",
            verdict=VERDICT[0] if number == 1 else None,
            quote=VERDICT[1] if number == 1 else None,
        )
        for number, (alternative_id, twin) in enumerate(pairs, start=1)
    )


def concern(*requirement_ids: UUID):
    return create_design_concern(
        concern_id=CONCERN_ID,
        code="DRK-001",
        summary="The night auditor may miss the report.",
        mitigation="Keep the report one click away.",
        requirement_ids=requirement_ids or (NIGHT_REPORT,),
        design_alternative_ids=(GUIDED_ID,),
    )


def design_package(
    requirements: RequirementsSpecificationVersion | None = None,
) -> DesignExplorationPackage:
    grounded = requirements or first_requirements()
    twins = grounded.specification.user_twin_references
    bound = bound_mockup()
    return create_design_exploration_package(
        project_id=PROJECT_ID,
        grounding=create_design_grounding(grounded),
        alternatives=(alternative(GUIDED_ID, 1, twins), alternative(DASHBOARD_ID, 2, twins)),
        critiques=critiques(twins),
        recommended_alternative_id=GUIDED_ID,
        owner_selected_alternative_id=DASHBOARD_ID,
        prototype=bound.prototype(),
        concerns=(concern(),),
        open_questions=("Should the night report also be saved?",),
        generated_mockup=bound,
        owner_assertions=ASSERTIONS,
    )


def design_version(
    package: DesignExplorationPackage | None = None,
    *,
    version_id: UUID = DESIGN_VERSION_ID,
    version_number: int = 1,
    created_at: datetime = WRITTEN_AT,
) -> DesignPackageVersion:
    value = package if package is not None else design_package()
    return DesignPackageVersion(
        id=version_id,
        project_id=value.project_id,
        version_number=version_number,
        based_on_version_number=None if version_number == 1 else version_number - 1,
        package=value,
        content_hash=value.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=created_at,
    )


def realigned_version(
    current: RequirementsSpecificationVersion,
    written: DesignPackageVersion | None = None,
) -> DesignPackageVersion:
    return realigned_design_version(
        written or design_version(),
        current,
        version_id=REALIGNED_VERSION_ID,
        created_by_user_id=OWNER_ID,
        created_at=REALIGNED_AT,
    )


def with_twins_of(
    package: DesignExplorationPackage,
    original: DesignExplorationPackage,
) -> DesignExplorationPackage:
    return replace(
        package,
        grounding=original.grounding,
        alternatives=tuple(
            replace(
                mine,
                user_twin_references=theirs.user_twin_references,
                visual_language=theirs.visual_language,
            )
            for mine, theirs in zip(package.alternatives, original.alternatives, strict=True)
        ),
        critiques=tuple(
            replace(mine, user_twin_reference=theirs.user_twin_reference)
            for mine, theirs in zip(package.critiques, original.critiques, strict=True)
        ),
    )


def prototype_citing(requirement_id: UUID):
    screen = create_prototype_screen(
        screen_id=UUID("00000000-0000-4000-8000-00000000e501"),
        code="SCR-001",
        title="Arrivals",
        state=PrototypeScreenState.DEFAULT,
        elements=(
            create_prototype_element(
                element_id=UUID("00000000-0000-4000-8000-00000000e502"),
                code="ELM-001",
                kind=PrototypeElementKind.TEXT,
                content="Every change is written to the log.",
                requirement_ids=(requirement_id,),
            ),
        ),
        requirement_ids=(CHECK_IN,),
    )
    return create_declarative_prototype(
        prototype_id=UUID("00000000-0000-4000-8000-00000000e503"),
        code="PRT-001",
        title="Arrivals prototype",
        design_alternative_id=DASHBOARD_ID,
        entry_screen_id=screen.id,
        screens=(screen,),
        transitions=(),
        supported_viewports=(PrototypeViewport.DESKTOP,),
    )


def design_citing_the_log_in_a_concern() -> DesignExplorationPackage:
    return replace(design_package(), concerns=(concern(AUDIT_LOG),))


def design_citing_the_log_in_a_prototype_element() -> DesignExplorationPackage:
    return replace(design_package(), generated_mockup=None, prototype=prototype_citing(AUDIT_LOG))


def design_citing_the_log_in_the_generated_mockup() -> DesignExplorationPackage:
    bound = bound_mockup(
        BASE_SECOND.replace('data-req="REQ-002"', 'data-req="REQ-002 REQ-003"'),
        {"REQ-003": AUDIT_LOG},
    )
    return replace(design_package(), generated_mockup=bound, prototype=bound.prototype())


def stage_versions(
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion,
) -> dict[str, object]:
    context = requirements.specification
    return {
        stage: StageIdentity(
            reference.artifact_id, PROJECT_ID, reference.version_number, reference.content_hash
        )
        for stage, reference in (
            ("brief", context.project_brief_reference),
            ("team", context.agent_team_reference),
            ("twins", context.user_modeling_reference),
        )
    } | {"requirements": requirements, "design": design}


def stage_payloads(
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion,
) -> dict[str, dict[str, object]]:
    return {
        "team": {
            "brief_version": {
                "id": str(BRIEF.artifact_id),
                "version_number": BRIEF.version_number,
                "content_hash": BRIEF.content_hash,
            }
        },
        "twins": {
            "project_brief_reference": BRIEF.to_snapshot(),
            "agent_team_reference": requirements.specification.agent_team_reference.to_snapshot(),
        },
        "requirements": requirements.specification.to_snapshot(),
        "design": design.package.to_snapshot(),
    }


ALLOWED = (
    pytest.param(reworded_requirements, id="texts-rewritten"),
    pytest.param(requirements_with_a_new_requirement, id="requirement-added"),
    pytest.param(requirements_without_an_uncited_requirement, id="uncited-requirement-removed"),
    pytest.param(requirements_with_revised_twins, id="same-twins-new-versions"),
    pytest.param(requirements_with_new_perspectives, id="new-perspectives"),
)


def test_a_design_written_for_the_current_requirements_is_aligned():
    package = design_package()
    first = first_requirements()

    assert design_is_aligned(package, first)
    assert design_realignment_issue(package, first) is DesignRealignmentIssue.ALREADY_ALIGNED
    assert missing_item_ids(package, first) == frozenset()
    assert uncovered_requirement_codes(package, first) == ("REQ-003",)


@pytest.mark.parametrize(
    ("changed", "issue", "missing", "uncovered"),
    [
        pytest.param(reworded_requirements, None, (), ("REQ-003",), id="texts-rewritten"),
        pytest.param(
            requirements_with_a_new_requirement,
            None,
            (),
            ("REQ-003", "REQ-004"),
            id="requirement-added",
        ),
        pytest.param(
            requirements_without_a_cited_requirement,
            DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE,
            ("REQ-002", "USR-002", "AC-002"),
            ("REQ-003",),
            id="cited-requirement-removed",
        ),
        pytest.param(
            requirements_without_an_uncited_requirement,
            None,
            (),
            (),
            id="uncited-requirement-removed",
        ),
        pytest.param(
            requirements_with_revised_twins, None, (), ("REQ-003",), id="same-twins-new-versions"
        ),
        pytest.param(
            requirements_with_another_twin,
            DesignRealignmentIssue.TWIN_SET_CHANGED,
            (),
            ("REQ-003",),
            id="twin-set-changed",
        ),
        pytest.param(
            requirements_with_new_perspectives, None, (), ("REQ-003",), id="new-perspectives"
        ),
    ],
)
def test_each_change_of_the_requirements_has_its_issue_and_its_codes(
    changed, issue, missing, uncovered
):
    package = design_package()
    current = changed()

    assert not design_is_aligned(package, current)
    assert design_realignment_issue(package, current) is issue
    assert item_codes(first_requirements().specification, missing_item_ids(package, current)) == (
        missing
    )
    assert uncovered_requirement_codes(package, current) == uncovered


@pytest.mark.parametrize("changed", ALLOWED)
def test_an_allowed_realignment_keeps_the_content_and_takes_the_new_grounding(changed):
    package = design_package()
    current = changed()

    realigned = realign_design(package, current)

    assert realigned.grounding == create_design_grounding(current)
    assert realigned.grounding.requirements_reference == VersionedArtifactReference(
        kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
        artifact_id=CHANGED_REQUIREMENTS_ID,
        version_number=2,
        content_hash=current.content_hash,
    )
    assert with_twins_of(realigned, package) == package
    assert realigned.prototype is package.prototype
    assert realigned.generated_mockup is package.generated_mockup
    assert realigned.concerns is package.concerns
    assert (realigned.recommended_alternative_id, realigned.owner_selected_alternative_id) == (
        GUIDED_ID,
        DASHBOARD_ID,
    )
    assert realigned.owner_assertions == ASSERTIONS
    assert realigned.open_questions == package.open_questions
    assert realigned.content_hash != package.content_hash
    assert design_package_from_snapshot(realigned.to_snapshot()) == realigned
    assert design_realignment_issue(realigned, current) is DesignRealignmentIssue.ALREADY_ALIGNED


@pytest.mark.parametrize(
    "changed",
    [
        reworded_requirements,
        requirements_with_a_new_requirement,
        requirements_without_an_uncited_requirement,
    ],
)
def test_without_a_twin_change_alternatives_and_critiques_stay_exactly_the_same(changed):
    package = design_package()

    realigned = realign_design(package, changed())

    assert realigned.alternatives == package.alternatives
    assert realigned.critiques == package.critiques
    assert realigned.grounding.user_twin_references == (RECEPTIONIST, AUDITOR)


def test_after_a_twin_realignment_every_twin_reference_names_the_current_version():
    package = design_package()
    current = requirements_with_revised_twins()

    realigned = realign_design(package, current)

    assert realigned.grounding.user_twin_references == (FRONT_DESK, AUDITOR)
    assert realigned.grounding.user_modeling_reference.version_number == 2
    assert [item.user_twin_references for item in realigned.alternatives] == [
        (FRONT_DESK, AUDITOR),
        (FRONT_DESK, AUDITOR),
    ]
    assert [(item.code, item.user_twin_reference) for item in realigned.critiques] == [
        ("CRQ-001", FRONT_DESK),
        ("CRQ-002", AUDITOR),
        ("CRQ-003", FRONT_DESK),
        ("CRQ-004", AUDITOR),
    ]
    language = realigned.alternatives[1].visual_language
    original = package.alternatives[1].visual_language
    assert [(fit.twin_id, fit.name) for fit in language.twin_fit] == [
        (RECEPTIONIST.twin_id, "Front Desk Twin"),
        (AUDITOR.twin_id, "Night Auditor Twin"),
    ]
    assert [fit.statement for fit in language.twin_fit] == [
        fit.statement for fit in original.twin_fit
    ]
    assert replace(language, twin_fit=original.twin_fit) == original
    assert [item.verdict for item in realigned.critiques] == [
        item.verdict for item in package.critiques
    ]


@pytest.mark.parametrize(
    ("changed", "issue"),
    [
        (first_requirements, DesignRealignmentIssue.ALREADY_ALIGNED),
        (
            requirements_without_a_cited_requirement,
            DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE,
        ),
        (requirements_with_another_twin, DesignRealignmentIssue.TWIN_SET_CHANGED),
    ],
)
def test_a_realignment_is_refused_with_the_code_of_its_issue(changed, issue):
    with pytest.raises(DesignRealignmentError) as raised:
        realigned_version(changed())

    assert raised.value.issue is issue
    assert raised.value.code == issue.value
    assert str(raised.value) == issue.value


def test_a_missing_requirement_is_reported_before_a_changed_set_of_twins():
    current = changed_requirements(
        codes=("REQ-001", "REQ-003"),
        twins=(RECEPTIONIST, AUDITOR, CONCIERGE),
        modeling=SECOND_MODELING,
    )

    issue = design_realignment_issue(design_package(), current)

    assert issue is DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE


def test_a_design_cannot_be_grounded_on_the_requirements_of_another_project():
    other = requirements_version(
        replace(specification(reworded=True), project_id=OTHER_PROJECT_ID),
        version_id=CHANGED_REQUIREMENTS_ID,
        version_number=2,
        created_at=CHANGED_AT,
    )

    with pytest.raises(ValueError, match="same project"):
        realign_design(design_package(), other)


def test_the_realigned_version_continues_the_design_lineage_with_a_new_hash():
    written = design_version()
    current = reworded_requirements()

    version = realigned_version(current, written)

    assert version.id == REALIGNED_VERSION_ID
    assert (version.version_number, version.based_on_version_number) == (2, 1)
    assert (version.project_id, version.created_by_user_id, version.created_at) == (
        PROJECT_ID,
        OWNER_ID,
        REALIGNED_AT,
    )
    assert version.package == realign_design(written.package, current)
    assert version.content_hash == version.package.content_hash
    assert version.content_hash != written.content_hash


@pytest.mark.parametrize(
    "citing",
    [
        design_citing_the_log_in_a_concern,
        design_citing_the_log_in_a_prototype_element,
        design_citing_the_log_in_the_generated_mockup,
    ],
)
def test_a_requirement_cited_only_in_one_part_of_the_design_is_still_missing_when_removed(
    citing,
):
    package = citing()
    current = requirements_without_an_uncited_requirement()

    assert missing_item_ids(package, current) == frozenset({AUDIT_LOG})
    assert (
        design_realignment_issue(package, current)
        is DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE
    )
    assert item_codes(first_requirements().specification, {AUDIT_LOG}) == ("REQ-003",)


def test_item_codes_name_requirements_then_stories_then_criteria():
    identifiers = {NIGHT_REPORT_CRITERION, CHECK_IN, NIGHT_REPORT_STORY, NIGHT_REPORT, WELCOME}

    codes = item_codes(first_requirements().specification, identifiers)

    assert codes == ("REQ-001", "REQ-002", "USR-002", "AC-002")


def test_a_design_without_a_prototype_leaves_no_requirement_uncovered():
    package = replace(
        design_package(), owner_selected_alternative_id=None, prototype=None, generated_mockup=None
    )

    assert uncovered_requirement_codes(package, requirements_with_a_new_requirement()) == ()


def test_after_new_perspectives_the_design_names_the_team_version_of_the_requirements():
    realigned = realign_design(design_package(), requirements_with_new_perspectives())

    assert realigned.grounding.agent_team_reference == VersionedArtifactReference(
        kind=ArtifactKind.AGENT_TEAM,
        artifact_id=SECOND_TEAM.artifact_id,
        version_number=2,
        content_hash=SECOND_TEAM.content_hash,
    )
    assert realigned.grounding.user_twin_references == (FRONT_DESK, AUDITOR)


@pytest.mark.parametrize(
    "changed",
    [reworded_requirements, requirements_with_revised_twins, requirements_with_new_perspectives],
)
def test_the_folder_check_refuses_the_old_grounding_and_accepts_the_realigned_one(changed):
    written = design_version()
    current = changed()
    realigned = realigned_version(current, written)

    before = stage_consistency_issue(
        PROJECT_ID, stage_versions(current, written), stage_payloads(current, written)
    )
    after = stage_consistency_issue(
        PROJECT_ID, stage_versions(current, realigned), stage_payloads(current, realigned)
    )

    assert before == "DESIGN_OUTDATED"
    assert after is None
