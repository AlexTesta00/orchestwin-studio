from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from orchestwin.projects.persistence.progress import overview_statement, progress_facts
from orchestwin.projects.progress import (
    CURRENT_CATALOG,
    ArtifactVersion,
    CatalogVersion,
    GateState,
    ProjectNextAction,
    ProjectProgress,
    ProjectProgressFacts,
    ProjectStage,
    TeamState,
    UserTwinsState,
    project_progress,
)
from orchestwin.workflow.gates import HumanGateStatus

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000002")


def version(ordinal: int, number: int = 1) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_id=UUID(int=ordinal), version_number=number, content_hash=f"{ordinal:x}" * 64
    )


BRIEF = version(1)
TEAM = version(2)
TWINS = version(3)
REQUIREMENTS = version(4)
DESIGN = version(5)
OTHER_CATALOG = CatalogVersion(version=CURRENT_CATALOG.version + 1, content_hash="e" * 64)


def approved(artifact: ArtifactVersion) -> GateState:
    return GateState(status=HumanGateStatus.APPROVED, artifact=artifact)


def pending(artifact: ArtifactVersion) -> GateState:
    return GateState(status=HumanGateStatus.PENDING_APPROVAL, artifact=artifact)


def complete() -> ProjectProgressFacts:
    return ProjectProgressFacts(
        brief=BRIEF,
        brief_gate=approved(BRIEF),
        team=TeamState(artifact=TEAM, brief=BRIEF, catalog=CURRENT_CATALOG),
        team_gate=approved(TEAM),
        user_twins=UserTwinsState(artifact=TWINS, brief=BRIEF, team=TEAM, catalog=CURRENT_CATALOG),
        user_twins_gate=approved(TWINS),
        requirements=REQUIREMENTS,
        requirements_gate=approved(REQUIREMENTS),
        design=DESIGN,
        design_gate=approved(DESIGN),
    )


def stage_of(facts: ProjectProgressFacts) -> tuple[ProjectStage, ProjectNextAction]:
    progress = project_progress(facts)
    return progress.current_stage, progress.next_action


def test_a_project_without_a_brief_waits_for_the_idea() -> None:
    assert project_progress(ProjectProgressFacts()) == ProjectProgress(
        ProjectStage.BRIEF, ProjectNextAction.DESCRIBE_IDEA
    )


@pytest.mark.parametrize(
    "gate",
    [None, pending(BRIEF), approved(version(1, number=2)), approved(version(9))],
)
def test_a_brief_is_approved_only_by_an_approval_of_its_exact_version(gate) -> None:
    facts = ProjectProgressFacts(brief=BRIEF, brief_gate=gate)

    assert stage_of(facts) == (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)


def test_a_project_with_every_gate_approved_is_ready_to_download() -> None:
    assert stage_of(complete()) == (ProjectStage.PACKAGE, ProjectNextAction.DOWNLOAD_FOLDER)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"team": None}, (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)),
        (
            {"team": TeamState(artifact=TEAM, brief=version(1, 2), catalog=CURRENT_CATALOG)},
            (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM),
        ),
        (
            {"team_gate": approved(version(2, 2))},
            (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM),
        ),
        ({"team_gate": pending(TEAM)}, (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)),
        ({"user_twins": None}, (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS)),
        (
            {
                "user_twins": UserTwinsState(
                    artifact=TWINS, brief=BRIEF, team=version(2, 2), catalog=CURRENT_CATALOG
                )
            },
            (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS),
        ),
        (
            {
                "user_twins": UserTwinsState(
                    artifact=TWINS, brief=version(1, 2), team=TEAM, catalog=CURRENT_CATALOG
                )
            },
            (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS),
        ),
        (
            {
                "user_twins": UserTwinsState(
                    artifact=TWINS, brief=BRIEF, team=TEAM, catalog=OTHER_CATALOG
                )
            },
            (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS),
        ),
        (
            {"user_twins_gate": approved(version(3, 2))},
            (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS),
        ),
        (
            {"requirements": None},
            (ProjectStage.REQUIREMENTS, ProjectNextAction.APPROVE_REQUIREMENTS),
        ),
        (
            {"requirements": version(4, 2)},
            (ProjectStage.REQUIREMENTS, ProjectNextAction.APPROVE_REQUIREMENTS),
        ),
        (
            {"requirements_gate": GateState(HumanGateStatus.REJECTED, REQUIREMENTS)},
            (ProjectStage.REQUIREMENTS, ProjectNextAction.APPROVE_REQUIREMENTS),
        ),
        ({"design": None}, (ProjectStage.DESIGN, ProjectNextAction.APPROVE_DESIGN)),
        ({"design_gate": None}, (ProjectStage.DESIGN, ProjectNextAction.APPROVE_DESIGN)),
        (
            {"design_gate": GateState(HumanGateStatus.REVISION_REQUESTED, DESIGN)},
            (ProjectStage.DESIGN, ProjectNextAction.APPROVE_DESIGN),
        ),
    ],
)
def test_the_project_stands_at_the_first_step_that_is_not_approved(changes, expected) -> None:
    assert stage_of(replace(complete(), **changes)) == expected


def test_a_team_built_on_an_outdated_catalog_keeps_the_twins_open() -> None:
    facts = replace(
        complete(),
        team=TeamState(artifact=TEAM, brief=BRIEF, catalog=OTHER_CATALOG),
        user_twins=UserTwinsState(artifact=TWINS, brief=BRIEF, team=TEAM, catalog=OTHER_CATALOG),
    )

    assert stage_of(facts) == (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS)


def test_a_new_brief_version_brings_the_project_back_to_the_brief() -> None:
    facts = replace(complete(), brief=version(1, 2))

    assert stage_of(facts) == (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)


def test_an_approved_later_step_does_not_skip_an_open_earlier_step() -> None:
    facts = replace(complete(), requirements_gate=None, team_gate=pending(TEAM))

    assert stage_of(facts) == (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)


def row(**values: object) -> dict[str, object]:
    empty = {
        f"{prefix}_{field}": None
        for prefix in (
            "brief",
            "team",
            "team_brief",
            "twins",
            "twins_brief",
            "twins_team",
            "requirements",
            "design",
            "brief_gate",
            "team_gate",
            "twins_gate",
            "requirements_gate",
            "design_gate",
        )
        for field in ("id", "version", "hash", "status", "catalog_version", "catalog_hash")
    }
    return {**empty, **values}


def columns(prefix: str, artifact: ArtifactVersion) -> dict[str, object]:
    return {
        f"{prefix}_id": artifact.artifact_id,
        f"{prefix}_version": artifact.version_number,
        f"{prefix}_hash": artifact.content_hash,
    }


def test_a_database_row_becomes_the_facts_of_the_rule() -> None:
    values = row(
        **columns("brief", BRIEF),
        **columns("brief_gate", BRIEF),
        brief_gate_status="APPROVED",
        **columns("team", TEAM),
        **columns("team_brief", BRIEF),
        team_catalog_version=CURRENT_CATALOG.version,
        team_catalog_hash=CURRENT_CATALOG.content_hash,
        **columns("team_gate", TEAM),
        team_gate_status="PENDING_APPROVAL",
        **columns("twins", TWINS),
        **columns("twins_brief", BRIEF),
        **columns("twins_team", TEAM),
        twins_catalog_version=CURRENT_CATALOG.version,
        twins_catalog_hash=CURRENT_CATALOG.content_hash,
        **columns("design", DESIGN),
    )

    facts = progress_facts(values)

    assert facts == ProjectProgressFacts(
        brief=BRIEF,
        brief_gate=approved(BRIEF),
        team=TeamState(artifact=TEAM, brief=BRIEF, catalog=CURRENT_CATALOG),
        team_gate=pending(TEAM),
        user_twins=UserTwinsState(artifact=TWINS, brief=BRIEF, team=TEAM, catalog=CURRENT_CATALOG),
        design=DESIGN,
    )
    assert stage_of(facts) == (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)
    assert progress_facts(row()) == ProjectProgressFacts()


def test_a_team_without_its_brief_reference_is_refused() -> None:
    with pytest.raises(ValueError, match="team_brief reference is missing"):
        progress_facts(
            row(
                **columns("team", TEAM),
                team_catalog_version=1,
                team_catalog_hash="a" * 64,
            )
        )


def test_one_statement_reads_every_project_of_the_owner_or_one_of_them() -> None:
    listing = str(overview_statement(owner_user_id=OWNER_ID).compile(dialect=postgresql.dialect()))
    single = str(
        overview_statement(owner_user_id=OWNER_ID, project_id=PROJECT_ID).compile(
            dialect=postgresql.dialect()
        )
    )

    assert listing.count("LATERAL") == 9
    assert "projects.archived_at IS NULL" in listing
    assert "projects.owner_user_id" in listing
    assert "projects.id = " not in listing
    assert "projects.id = %(id_1)s" in single
    for table in (
        "team_proposals",
        "user_modeling_snapshot_versions",
        "requirements_specification_versions",
        "design_package_versions",
        "human_gates",
        "project_brief_versions",
    ):
        assert table in listing
