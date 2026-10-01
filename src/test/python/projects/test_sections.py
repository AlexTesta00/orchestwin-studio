from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.projects.progress import ArtifactVersion, ProjectStage
from orchestwin.projects.sections import (
    ALIGNABLE_SECTIONS,
    BriefFacts,
    DesignFacts,
    FolderFacts,
    RequirementsFacts,
    SectionBlock,
    SectionFacts,
    SectionReason,
    SectionState,
    TeamFacts,
    UserTwinsFacts,
    project_sections,
)

KEYS = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
ARTIFACTS = {"brief": 1, "team": 2, "snapshot": 3, "requirements": 4, "design": 5}
TWIN_A = UUID("00000000-0000-4000-8000-0000000000a1")
TWIN_B = UUID("00000000-0000-4000-8000-0000000000b1")
TWIN_C = UUID("00000000-0000-4000-8000-0000000000c1")


def artifact(kind: str, version: int = 1) -> ArtifactVersion:
    ordinal = ARTIFACTS[kind]
    return ArtifactVersion(
        artifact_id=UUID(f"00000000-0000-4000-8000-{ordinal:012x}"),
        version_number=version,
        content_hash=hashlib.sha256(f"{kind}-{version}".encode()).hexdigest(),
    )


def twin(identifier: UUID, version: int = 1) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_id=identifier,
        version_number=version,
        content_hash=hashlib.sha256(f"{identifier}-{version}".encode()).hexdigest(),
    )


TWINS_1 = frozenset({twin(TWIN_A), twin(TWIN_B)})
TWINS_2 = frozenset({twin(TWIN_A, 2), twin(TWIN_B, 2)})
OTHER_TWINS = frozenset({twin(TWIN_A, 2), twin(TWIN_C)})


def brief(version: int = 1, *, approved: bool = True) -> BriefFacts:
    return BriefFacts(version=artifact("brief", version), approved=approved)


def team(version: int = 1, *, approved: bool = True, on_brief: int = 1) -> TeamFacts:
    return TeamFacts(
        version=artifact("team", version),
        approved=approved,
        brief=artifact("brief", on_brief),
    )


def user_twins(
    version: int = 1,
    *,
    approved: bool = True,
    on_brief: int = 1,
    on_team: int = 1,
    twins: frozenset[ArtifactVersion] = TWINS_1,
    **flags: bool,
) -> UserTwinsFacts:
    return UserTwinsFacts(
        version=artifact("snapshot", version),
        approved=approved,
        brief=artifact("brief", on_brief),
        team=artifact("team", on_team),
        twins=twins,
        **flags,
    )


def requirements(
    version: int = 1,
    *,
    approved: bool = True,
    on_brief: int = 1,
    on_team: int = 1,
    on_snapshot: int = 1,
    twins: frozenset[ArtifactVersion] = TWINS_1,
    cited: frozenset[UUID] = frozenset({TWIN_A, TWIN_B}),
    revision_pending: bool = False,
) -> RequirementsFacts:
    return RequirementsFacts(
        version=artifact("requirements", version),
        approved=approved,
        brief=artifact("brief", on_brief),
        team=artifact("team", on_team),
        user_modeling=artifact("snapshot", on_snapshot),
        twins=twins,
        cited_twin_ids=cited,
        revision_pending=revision_pending,
    )


def design(
    version: int = 1,
    *,
    approved: bool = True,
    on_requirements: int = 1,
    on_team: int = 1,
    on_snapshot: int = 1,
    twins: frozenset[ArtifactVersion] = TWINS_1,
    **flags: object,
) -> DesignFacts:
    return DesignFacts(
        version=artifact("design", version),
        approved=approved,
        requirements=artifact("requirements", on_requirements),
        team=artifact("team", on_team),
        user_modeling=artifact("snapshot", on_snapshot),
        twins=twins,
        **flags,
    )


def folder(version_number: int = 5, **versions: int) -> FolderFacts:
    held = {"brief": 1, "team": 1, "snapshot": 1, "requirements": 1, "design": 1, **versions}
    stages = {
        ProjectStage.BRIEF: "brief",
        ProjectStage.TEAM: "team",
        ProjectStage.USER_TWINS: "snapshot",
        ProjectStage.REQUIREMENTS: "requirements",
        ProjectStage.DESIGN: "design",
    }
    return FolderFacts(
        version_number=version_number,
        stages={key: artifact(kind, held[kind]) for key, kind in stages.items() if held[kind] > 0},
    )


def aligned(**changes: object) -> SectionFacts:
    return replace(
        SectionFacts(
            brief=brief(),
            team=team(),
            user_twins=user_twins(),
            requirements=requirements(),
            design=design(),
            folder=folder(),
            design_approved_once=True,
        ),
        **changes,
    )


def row(
    key: str,
    state: str,
    version: int | None = None,
    reasons: tuple[str, ...] = (),
    blocked: str | None = None,
    codes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "state": state,
        "version_number": version,
        "reasons": list(reasons),
        "blocked": blocked,
        "codes": list(codes),
    }


def fine(key: str, version: int = 1) -> dict[str, object]:
    return row(key, "FINE", version)


def rows(facts: SectionFacts) -> list[dict[str, object]]:
    return [section.to_snapshot() for section in project_sections(facts).sections]


def alignment(facts: SectionFacts) -> dict[str, object]:
    return project_sections(facts).alignment.to_snapshot()


def dossier(facts: SectionFacts) -> dict[str, object]:
    return project_sections(facts).section(ProjectStage.PACKAGE).to_snapshot()


NOT_READY = "UPSTREAM_NOT_READY"
ALL_FINE = [fine(key) for key in KEYS[:5]] + [fine("PACKAGE", 5)]
FOLDER_WAITING = row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",), NOT_READY)

CASES = {
    "a project without anything": (
        SectionFacts(),
        [row(key, "NOT_STARTED") for key in KEYS],
    ),
    "a brief waiting for approval": (
        SectionFacts(brief=brief(approved=False)),
        [row("BRIEF", "IN_PROGRESS", 1)] + [row(key, "NOT_STARTED") for key in KEYS[1:]],
    ),
    "perspectives waiting for approval": (
        SectionFacts(brief=brief(), team=team(approved=False)),
        [fine("BRIEF"), row("TEAM", "IN_PROGRESS", 1)]
        + [row(key, "NOT_STARTED") for key in KEYS[2:]],
    ),
    "every section approved and built on what is upstream": (aligned(), ALL_FINE),
    "twins regenerated and waiting": (
        aligned(user_twins=user_twins(2, approved=False, twins=TWINS_2)),
        [
            fine("BRIEF"),
            fine("TEAM"),
            row("USER_TWINS", "IN_PROGRESS", 2),
            row("REQUIREMENTS", "TO_UPDATE", 1, ("USER_TWINS_CHANGED",), NOT_READY),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "requirements changed and waiting": (
        aligned(requirements=requirements(2, approved=False)),
        [
            *ALL_FINE[:3],
            row("REQUIREMENTS", "IN_PROGRESS", 2),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "design changed and waiting": (
        aligned(design=design(2, approved=False)),
        [*ALL_FINE[:4], row("DESIGN", "IN_PROGRESS", 2), FOLDER_WAITING],
    ),
    "a perspective switched on and waiting": (
        aligned(team=team(2, approved=False)),
        [
            fine("BRIEF"),
            row("TEAM", "IN_PROGRESS", 2),
            row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",), NOT_READY),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
                NOT_READY,
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a new brief approved after the perspectives": (
        aligned(brief=brief(2)),
        [
            fine("BRIEF", 2),
            row("TEAM", "TO_UPDATE", 1, ("BRIEF_CHANGED",), "PREPARE_AGAIN"),
            row(
                "USER_TWINS",
                "TO_UPDATE",
                1,
                ("BRIEF_CHANGED", "PERSPECTIVES_CHANGED"),
                NOT_READY,
            ),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("BRIEF_CHANGED", "PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
                NOT_READY,
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a new brief waiting for approval": (
        aligned(brief=brief(2, approved=False)),
        [
            row("BRIEF", "IN_PROGRESS", 2),
            row("TEAM", "TO_UPDATE", 1, ("BRIEF_CHANGED",), NOT_READY),
            row(
                "USER_TWINS",
                "TO_UPDATE",
                1,
                ("BRIEF_CHANGED", "PERSPECTIVES_CHANGED"),
                NOT_READY,
            ),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("BRIEF_CHANGED", "PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
                NOT_READY,
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a perspective switched on and approved": (
        aligned(team=team(2)),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",)),
            row("REQUIREMENTS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",)),
            row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",)),
        ],
    ),
    "twins re-anchored, requirements not yet": (
        aligned(team=team(2), user_twins=user_twins(2, on_team=2, twins=TWINS_2)),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            fine("USER_TWINS", 2),
            row("REQUIREMENTS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",)),
            row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",)),
        ],
    ),
    "requirements re-anchored, design not yet": (
        aligned(
            team=team(2),
            user_twins=user_twins(2, on_team=2, twins=TWINS_2),
            requirements=requirements(2, on_team=2, on_snapshot=2, twins=TWINS_2),
        ),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            fine("USER_TWINS", 2),
            fine("REQUIREMENTS", 2),
            row(
                "DESIGN",
                "TO_UPDATE",
                1,
                ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED", "REQUIREMENTS_CHANGED"),
            ),
            row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",)),
        ],
    ),
    "a design grounded on the requirements with an older context": (
        aligned(design=design(on_team=2, on_snapshot=2, twins=TWINS_2)),
        [
            *ALL_FINE[:4],
            row("DESIGN", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
            row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",)),
        ],
    ),
    "requirements changed and approved": (
        aligned(requirements=requirements(2)),
        [
            *ALL_FINE[:3],
            fine("REQUIREMENTS", 2),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",)),
            row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",)),
        ],
    ),
    "a proposed twin revision": (
        aligned(team=team(2), user_twins=user_twins(revision_pending=True)),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",), "REVISION_PENDING"),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
                NOT_READY,
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a proposed requirements revision below twins that will be updated": (
        aligned(team=team(2), requirements=requirements(revision_pending=True)),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",)),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
                "REVISION_PENDING",
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a twin cited by the requirements that the twins no longer have": (
        aligned(user_twins=user_twins(2, twins=frozenset({twin(TWIN_A, 2)}))),
        [
            *ALL_FINE[:2],
            fine("USER_TWINS", 2),
            row(
                "REQUIREMENTS",
                "TO_UPDATE",
                1,
                ("USER_TWINS_CHANGED",),
                "TWIN_NO_LONGER_AVAILABLE",
            ),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "a design that cites requirements removed by the change": (
        aligned(requirements=requirements(2), design=design(missing_codes=("REQ-002", "US-003"))),
        [
            *ALL_FINE[:3],
            fine("REQUIREMENTS", 2),
            row(
                "DESIGN",
                "TO_UPDATE",
                1,
                ("REQUIREMENTS_CHANGED",),
                "REQUIREMENT_NO_LONGER_AVAILABLE",
                ("REQ-002", "US-003"),
            ),
            FOLDER_WAITING,
        ],
    ),
    "twins and requirements regenerated with another set of twins": (
        aligned(
            user_twins=user_twins(2, twins=OTHER_TWINS),
            requirements=requirements(
                2, on_snapshot=2, twins=OTHER_TWINS, cited=frozenset({TWIN_A, TWIN_C})
            ),
        ),
        [
            *ALL_FINE[:2],
            fine("USER_TWINS", 2),
            fine("REQUIREMENTS", 2),
            row(
                "DESIGN",
                "TO_UPDATE",
                1,
                ("USER_TWINS_CHANGED", "REQUIREMENTS_CHANGED"),
                "TWIN_SET_CHANGED",
            ),
            FOLDER_WAITING,
        ],
    ),
    "a proposed design revision": (
        aligned(requirements=requirements(2), design=design(revision_pending=True)),
        [
            *ALL_FINE[:3],
            fine("REQUIREMENTS", 2),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), "REVISION_PENDING"),
            FOLDER_WAITING,
        ],
    ),
    "a proposed design revision below requirements that will be updated": (
        aligned(team=team(2), design=design(revision_pending=True)),
        [
            fine("BRIEF"),
            fine("TEAM", 2),
            row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",)),
            row("REQUIREMENTS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), "REVISION_PENDING"),
            FOLDER_WAITING,
        ],
    ),
    "twins that learned something": (
        aligned(user_twins=user_twins(learned=True)),
        [
            *ALL_FINE[:2],
            row("USER_TWINS", "UPDATE_AVAILABLE", 1, ("TWINS_LEARNED",)),
            *ALL_FINE[3:],
        ],
    ),
    "an archetype changed while the approved snapshot still holds its old version": (
        aligned(user_twins=user_twins(archetypes_current=False)),
        [
            fine("BRIEF"),
            fine("TEAM"),
            row("USER_TWINS", "TO_UPDATE", 1, ("ARCHETYPES_CHANGED",), "PREPARE_TWINS"),
            row("REQUIREMENTS", "TO_UPDATE", 1, ("USER_TWINS_CHANGED",), NOT_READY),
            row("DESIGN", "TO_UPDATE", 1, ("REQUIREMENTS_CHANGED",), NOT_READY),
            FOLDER_WAITING,
        ],
    ),
    "requirements the design does not cover": (
        aligned(design=design(uncovered_codes=("REQ-004", "REQ-005"))),
        [
            *ALL_FINE[:4],
            row(
                "DESIGN",
                "UPDATE_AVAILABLE",
                1,
                ("REQUIREMENTS_NOT_COVERED",),
                codes=("REQ-004", "REQ-005"),
            ),
            fine("PACKAGE", 5),
        ],
    ),
    "a mockup without a twin review": (
        aligned(design=design(has_mockup=True)),
        [
            *ALL_FINE[:4],
            row("DESIGN", "UPDATE_AVAILABLE", 1, ("EVALUATION_MISSING",)),
            fine("PACKAGE", 5),
        ],
    ),
    "uncovered requirements and a missing review": (
        aligned(design=design(has_mockup=True, uncovered_codes=("REQ-004",))),
        [
            *ALL_FINE[:4],
            row(
                "DESIGN",
                "UPDATE_AVAILABLE",
                1,
                ("REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING"),
                codes=("REQ-004",),
            ),
            fine("PACKAGE", 5),
        ],
    ),
    "a mockup reviewed by the twins": (
        aligned(design=design(has_mockup=True, reviewed=True)),
        ALL_FINE,
    ),
    "no folder published": (
        aligned(folder=None),
        [*ALL_FINE[:5], row("PACKAGE", "NOT_STARTED")],
    ),
    "a folder published before the design was approved": (
        aligned(folder=folder(4, design=0)),
        [*ALL_FINE[:5], row("PACKAGE", "TO_UPDATE", 4, ("FOLDER_BEHIND",))],
    ),
    "a folder that still holds the design being changed": (
        aligned(design=design(2, approved=False)),
        [*ALL_FINE[:4], row("DESIGN", "IN_PROGRESS", 2), FOLDER_WAITING],
    ),
    "a partial folder of the first pass": (
        SectionFacts(
            brief=brief(),
            team=team(),
            user_twins=user_twins(),
            requirements=requirements(approved=False),
            folder=folder(3, requirements=0, design=0),
        ),
        [
            *ALL_FINE[:3],
            row("REQUIREMENTS", "IN_PROGRESS", 1),
            row("DESIGN", "NOT_STARTED"),
            fine("PACKAGE", 3),
        ],
    ),
    "a partial folder of the first pass that holds twins being regenerated": (
        SectionFacts(
            brief=brief(),
            team=team(),
            user_twins=user_twins(2, approved=False, twins=TWINS_2),
            folder=folder(3, requirements=0, design=0),
        ),
        [
            *ALL_FINE[:2],
            row("USER_TWINS", "IN_PROGRESS", 2),
            row("REQUIREMENTS", "NOT_STARTED"),
            row("DESIGN", "NOT_STARTED"),
            row("PACKAGE", "TO_UPDATE", 3, ("FOLDER_BEHIND",), NOT_READY),
        ],
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_every_section_gets_its_state_reasons_and_obstacle(name):
    facts, expected = CASES[name]

    assert rows(facts) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a project without anything", {"available": False, "sections": []}),
        ("every section approved and built on what is upstream", {"available": False}),
        ("a perspective switched on and waiting", {"available": False}),
        ("a new brief approved after the perspectives", {"available": False}),
        (
            "a perspective switched on and approved",
            {"available": True, "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"]},
        ),
        (
            "twins re-anchored, requirements not yet",
            {"available": True, "sections": ["REQUIREMENTS", "DESIGN"]},
        ),
        ("requirements changed and approved", {"available": True, "sections": ["DESIGN"]}),
        ("twins regenerated and waiting", {"available": False}),
        ("a proposed twin revision", {"available": False}),
        (
            "a proposed requirements revision below twins that will be updated",
            {"available": True, "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"]},
        ),
        ("a design that cites requirements removed by the change", {"available": False}),
        ("twins and requirements regenerated with another set of twins", {"available": False}),
        ("a twin cited by the requirements that the twins no longer have", {"available": False}),
        ("twins that learned something", {"available": False, "sections": []}),
    ],
)
def test_the_gesture_is_available_when_the_first_section_behind_is_not_blocked(name, expected):
    behind = [
        section["key"]
        for section in rows(CASES[name][0])
        if section["state"] == "TO_UPDATE" and section["key"] in ALIGNABLE_SECTIONS
    ]
    result = alignment(CASES[name][0])

    assert result["available"] is expected["available"]
    assert result["sections"] == expected.get("sections", behind)


def test_the_example_of_the_contract_is_reproduced_exactly():
    facts = SectionFacts(
        brief=brief(2),
        team=team(2, on_brief=2),
        user_twins=user_twins(1, on_brief=2),
        requirements=requirements(3, on_brief=2),
        design=design(4, on_requirements=3),
        folder=FolderFacts(
            version_number=6,
            stages={
                ProjectStage.BRIEF: artifact("brief", 2),
                ProjectStage.TEAM: artifact("team", 1),
                ProjectStage.USER_TWINS: artifact("snapshot", 1),
                ProjectStage.REQUIREMENTS: artifact("requirements", 3),
                ProjectStage.DESIGN: artifact("design", 4),
            },
        ),
        design_approved_once=True,
    )

    assert project_sections(facts).to_snapshot() == {
        "first_pass_complete": True,
        "sections": [
            {
                "key": "BRIEF",
                "state": "FINE",
                "version_number": 2,
                "reasons": [],
                "blocked": None,
                "codes": [],
            },
            {
                "key": "TEAM",
                "state": "FINE",
                "version_number": 2,
                "reasons": [],
                "blocked": None,
                "codes": [],
            },
            {
                "key": "USER_TWINS",
                "state": "TO_UPDATE",
                "version_number": 1,
                "reasons": ["PERSPECTIVES_CHANGED"],
                "blocked": None,
                "codes": [],
            },
            {
                "key": "REQUIREMENTS",
                "state": "TO_UPDATE",
                "version_number": 3,
                "reasons": ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"],
                "blocked": None,
                "codes": [],
            },
            {
                "key": "DESIGN",
                "state": "TO_UPDATE",
                "version_number": 4,
                "reasons": ["REQUIREMENTS_CHANGED"],
                "blocked": None,
                "codes": [],
            },
            {
                "key": "PACKAGE",
                "state": "TO_UPDATE",
                "version_number": 6,
                "reasons": ["FOLDER_BEHIND"],
                "blocked": None,
                "codes": [],
            },
        ],
        "alignment": {
            "available": True,
            "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"],
            "uncovered_codes": [],
        },
    }


def test_the_uncovered_codes_are_announced_only_when_the_design_will_be_updated():
    behind = aligned(requirements=requirements(2), design=design(uncovered_codes=("REQ-006",)))
    blocked = replace(
        behind, design=design(uncovered_codes=("REQ-006",), missing_codes=("REQ-001",))
    )
    upstream_blocked = replace(
        behind,
        team=team(2),
        user_twins=user_twins(revision_pending=True),
    )

    assert alignment(behind) == {
        "available": True,
        "sections": ["DESIGN"],
        "uncovered_codes": ["REQ-006"],
    }
    assert alignment(blocked) == {"available": False, "sections": ["DESIGN"], "uncovered_codes": []}
    assert alignment(upstream_blocked)["uncovered_codes"] == []
    assert alignment(aligned(design=design(uncovered_codes=("REQ-006",))))["uncovered_codes"] == []


def test_the_dossier_waits_for_switched_perspectives_and_is_fine_once_published_again():
    switched = aligned(team=team(2, approved=False))
    confirmed = aligned(team=team(2))
    realigned = replace(
        confirmed,
        user_twins=user_twins(2, on_team=2, twins=TWINS_2),
        requirements=requirements(2, on_team=2, on_snapshot=2, twins=TWINS_2),
        design=design(2, on_requirements=2, on_team=2, on_snapshot=2, twins=TWINS_2),
    )
    published = replace(realigned, folder=folder(6, team=2, snapshot=2, requirements=2, design=2))
    behind = row("PACKAGE", "TO_UPDATE", 5, ("FOLDER_BEHIND",))
    current = [fine("BRIEF"), *(fine(key, 2) for key in KEYS[1:5])]

    assert [dossier(facts) for facts in (switched, confirmed, realigned, published)] == [
        FOLDER_WAITING,
        behind,
        behind,
        fine("PACKAGE", 6),
    ]
    assert rows(switched)[1] == row("TEAM", "IN_PROGRESS", 2)
    assert rows(realigned) == [*current, behind]
    assert rows(published) == [*current, fine("PACKAGE", 6)]
    assert alignment(realigned)["sections"] == alignment(published)["sections"] == []


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (SectionFacts(), False),
        (aligned(design=design(approved=False), design_approved_once=False), False),
        (aligned(design=design(2, approved=False)), True),
        (aligned(design_approved_once=False), True),
        (aligned(design=None, folder=None, design_approved_once=False), False),
    ],
)
def test_the_first_pass_is_complete_once_a_design_was_approved(facts, expected):
    assert project_sections(facts).first_pass_complete is expected


def test_sections_follow_the_order_of_the_stages_and_the_enums_are_the_contract():
    sections = project_sections(aligned())

    assert [section.key.value for section in sections.sections] == list(KEYS)
    assert sections.section(ProjectStage.DESIGN).state is SectionState.FINE
    assert [state.value for state in SectionState] == [
        "NOT_STARTED",
        "IN_PROGRESS",
        "FINE",
        "UPDATE_AVAILABLE",
        "TO_UPDATE",
    ]
    assert [reason.value for reason in SectionReason] == [
        "BRIEF_CHANGED",
        "PERSPECTIVES_CHANGED",
        "ARCHETYPES_CHANGED",
        "USER_TWINS_CHANGED",
        "REQUIREMENTS_CHANGED",
        "FOLDER_BEHIND",
        "TWINS_LEARNED",
        "REQUIREMENTS_NOT_COVERED",
        "EVALUATION_MISSING",
    ]
    assert {block.value for block in SectionBlock} == {
        "REQUIREMENT_NO_LONGER_AVAILABLE",
        "TWIN_SET_CHANGED",
        "TWIN_NO_LONGER_AVAILABLE",
        "REVISION_PENDING",
        "UPSTREAM_NOT_READY",
        "PREPARE_AGAIN",
        "PREPARE_TWINS",
    }


def test_every_state_reason_and_obstacle_of_the_contract_appears_in_the_table():
    seen = [section for _, (facts, _) in CASES.items() for section in rows(facts)]

    for key in KEYS:
        states = {section["state"] for section in seen if section["key"] == key}
        expected = {"NOT_STARTED", "FINE"}
        if key != "BRIEF":
            expected.add("TO_UPDATE")
        if key != "PACKAGE":
            expected.add("IN_PROGRESS")
        if key in {"USER_TWINS", "DESIGN"}:
            expected.add("UPDATE_AVAILABLE")
        assert states == expected, key
    assert {reason for section in seen for reason in section["reasons"]} == {
        reason.value for reason in SectionReason
    }
    assert {section["blocked"] for section in seen} - {None} == {
        block.value for block in SectionBlock
    }
