from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.agents.selection_rules import determine_team_constraints
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.models.fake_team_proposals import FakeDeterministicTeamProposalAdapter
from orchestwin.models.team_proposals import TeamProposalRequest
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.brief_gate import LocalProjectBriefGateService
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import (
    SqlAlchemyProjectBriefGateUnitOfWorkFactory,
    SqlAlchemyProjectBriefRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from orchestwin.projects.persistence.progress import SqlAlchemyProjectOverviewRepository
from orchestwin.projects.progress import ProjectNextAction, ProjectStage
from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_runtime import ManagedRequirementsUnitOfWorkFactory
from orchestwin.twins.runtime import SqlAlchemyUserModelingGateUnitOfWorkFactory
from orchestwin.twins.user_modeling_gate import LocalUserModelingGateService
from orchestwin.workflow.gates import HumanGateAction, HumanGateType
from src.test.python.artifacts import design_fixtures
from src.test.python.integration.test_postgresql_twin_import import (
    CREATED_AT,
    add_users,
    approve,
    members_named,
    project_brief,
    seed_project,
    statements_of,
)
from src.test.python.integration.test_proposal_evidence_postgres import run
from src.test.python.knowledge.test_twin_import import OWNER_ID
from src.test.python.projects.test_requirements_realignment import requirements_version

pytestmark = pytest.mark.integration

STRANGER_ID = UUID("00000000-0000-4000-8000-00000000e000")
EARLIER = CREATED_AT - timedelta(days=1)


def project_id(ordinal: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-00000000e{ordinal:03x}")


async def add_project(
    runtime,
    *,
    identifier: UUID,
    name: str,
    created_at: datetime,
    owner_id: UUID = OWNER_ID,
    with_brief: bool = True,
) -> ProjectBriefVersion | None:
    brief = project_brief(identifier, name, owner_id=owner_id) if with_brief else None
    async with runtime.session_factory() as session, session.begin():
        session.add(
            ProjectRecord(
                id=identifier,
                owner_user_id=owner_id,
                display_name=name,
                mode=ProjectMode.GREENFIELD_GENERATION.value,
                current_brief_version=0 if brief is None else 1,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await session.flush()
        if brief is not None:
            session.add(
                ProjectBriefVersionRecord(
                    id=brief.id,
                    project_id=identifier,
                    version_number=1,
                    schema_version=brief.schema_version,
                    content=brief.brief.to_snapshot(),
                    content_hash=brief.content_hash,
                    created_by_user_id=owner_id,
                    created_at=created_at,
                )
            )
    return brief


async def add_team(runtime, *, identifier: UUID, brief: ProjectBriefVersion):
    generation = await FakeDeterministicTeamProposalAdapter().propose(
        TeamProposalRequest(
            project_mode=ProjectMode.GREENFIELD_GENERATION,
            brief_version=brief,
            constraints=determine_team_constraints(
                project_mode=ProjectMode.GREENFIELD_GENERATION, brief=brief.brief
            ),
        )
    )
    async with runtime.session_factory() as session, session.begin():
        created = await SqlAlchemyTeamProposalVersionRepository(session).create_generated_owned(
            project_id=identifier, owner_user_id=OWNER_ID, proposal=generation.proposal
        )
    return created.version


async def add_requirements(runtime, snapshot):
    version = requirements_version(
        snapshot, version_id=uuid4(), version_number=1, owner_id=OWNER_ID, created_at=CREATED_AT
    )
    async with ManagedRequirementsUnitOfWorkFactory(runtime.session_factory)(
        owner_user_id=OWNER_ID
    ) as unit:
        assert await unit.specifications.append(version) is RequirementsVersionAppendStatus.APPENDED
        await unit.commit()
    await approve(
        runtime,
        project_id=snapshot.project_id,
        gate_type=HumanGateType.REQUIREMENTS,
        version=version,
    )


async def add_design(runtime, *, identifier: UUID) -> None:
    package = replace(design_fixtures.design_package(), project_id=identifier)
    version = DesignPackageVersion(
        id=uuid4(),
        project_id=identifier,
        version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    async with runtime.session_factory() as session, session.begin():
        status = await SqlAlchemyDesignPackageRepository(session, owner_user_id=OWNER_ID).append(
            version
        )
    assert status.value == "APPENDED"
    await approve(runtime, project_id=identifier, gate_type=HumanGateType.DESIGN, version=version)


async def reopen_brief(runtime, *, identifier: UUID) -> None:
    async with runtime.session_factory() as session, session.begin():
        current = await SqlAlchemyProjectBriefRepository(session).get_current_owned(
            project_id=identifier, owner_user_id=OWNER_ID
        )
        assert current is not None
        created = await SqlAlchemyProjectBriefRepository(session).create_owned_version(
            project_id=identifier,
            owner_user_id=OWNER_ID,
            created_by_user_id=OWNER_ID,
            brief=replace(current.brief, name="A changed idea"),
        )
    assert created.version is not None and created.version.version_number == 2


def test_every_project_of_the_owner_gets_its_step_from_one_statement():
    async def scenario():
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            factory = runtime.session_factory
            await add_users(factory, OWNER_ID, STRANGER_ID)
            gates = LocalUserModelingGateService(
                unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(factory)
            )
            expected: dict[UUID, tuple[ProjectStage, ProjectNextAction]] = {}

            await add_project(
                runtime,
                identifier=project_id(1),
                name="Idea only",
                created_at=EARLIER,
                with_brief=False,
            )
            expected[project_id(1)] = (ProjectStage.BRIEF, ProjectNextAction.DESCRIBE_IDEA)

            await add_project(runtime, identifier=project_id(2), name="Brief", created_at=EARLIER)
            expected[project_id(2)] = (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)

            brief = await add_project(
                runtime, identifier=project_id(3), name="Team", created_at=EARLIER
            )
            await approve(
                runtime,
                project_id=project_id(3),
                gate_type=HumanGateType.PROJECT_BRIEF,
                version=brief,
            )
            expected[project_id(3)] = (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)

            brief = await add_project(
                runtime, identifier=project_id(4), name="Twins", created_at=EARLIER
            )
            await approve(
                runtime,
                project_id=project_id(4),
                gate_type=HumanGateType.PROJECT_BRIEF,
                version=brief,
            )
            team = await add_team(runtime, identifier=project_id(4), brief=brief)
            await approve(
                runtime, project_id=project_id(4), gate_type=HumanGateType.AGENT_TEAM, version=team
            )
            expected[project_id(4)] = (ProjectStage.USER_TWINS, ProjectNextAction.CONFIRM_TWINS)

            snapshots = {}
            for ordinal in (5, 6, 7, 8):
                snapshots[ordinal] = await seed_project(
                    runtime,
                    gates,
                    project_id=project_id(ordinal),
                    name=f"Project {ordinal}",
                    members=members_named(f"Twin {ordinal}"),
                )
            expected[project_id(5)] = (
                ProjectStage.REQUIREMENTS,
                ProjectNextAction.APPROVE_REQUIREMENTS,
            )
            for ordinal in (6, 7, 8):
                await add_requirements(runtime, snapshots[ordinal])
            expected[project_id(6)] = (ProjectStage.DESIGN, ProjectNextAction.APPROVE_DESIGN)
            for ordinal in (7, 8):
                await add_design(runtime, identifier=project_id(ordinal))
            expected[project_id(7)] = (ProjectStage.PACKAGE, ProjectNextAction.DOWNLOAD_FOLDER)
            await reopen_brief(runtime, identifier=project_id(8))
            expected[project_id(8)] = (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)

            await add_project(
                runtime, identifier=project_id(9), name="Archived", created_at=EARLIER
            )
            async with factory() as session, session.begin():
                assert await SqlAlchemyProjectRepository(session).archive_owned(
                    project_id=project_id(9), owner_user_id=OWNER_ID
                )
            await add_project(
                runtime,
                identifier=project_id(10),
                name="Stranger",
                created_at=EARLIER,
                owner_id=STRANGER_ID,
            )

            async with factory() as session:
                repository = SqlAlchemyProjectOverviewRepository(session)
                overviews, statements = await statements_of(
                    runtime, repository.list_active_owned(owner_user_id=OWNER_ID)
                )
                single, single_statements = await statements_of(
                    runtime,
                    repository.get_owned(project_id=project_id(7), owner_user_id=OWNER_ID),
                )
                archived = await repository.get_owned(
                    project_id=project_id(9), owner_user_id=OWNER_ID
                )
                foreign = await repository.get_owned(
                    project_id=project_id(10), owner_user_id=OWNER_ID
                )
                stranger = await repository.list_active_owned(owner_user_id=STRANGER_ID)
                listed_projects = await SqlAlchemyProjectRepository(session).list_active_owned(
                    owner_user_id=OWNER_ID
                )

            assert len(statements) == 1
            assert len(single_statements) == 1
            assert [overview.project for overview in overviews] == list(listed_projects)
            assert {
                overview.project.id: (
                    overview.progress.current_stage,
                    overview.progress.next_action,
                )
                for overview in overviews
            } == expected
            assert single is not None
            assert single.project.id == project_id(7)
            assert single.progress.current_stage is ProjectStage.PACKAGE
            assert archived is None
            assert foreign is None
            assert [overview.project.id for overview in stranger] == [project_id(10)]
            assert stranger[0].progress.next_action is ProjectNextAction.APPROVE_BRIEF

            service = LocalProjectApplicationService(
                unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(factory)
            )
            assert await service.list_overviews(owner_user_id=OWNER_ID) == overviews
            assert await service.get_overview(
                project_id=project_id(3), owner_user_id=OWNER_ID
            ) == next(overview for overview in overviews if overview.project.id == project_id(3))
        finally:
            await runtime.dispose()

    run(scenario())


def test_the_latest_gate_iteration_decides_and_a_new_brief_reopens_the_team():
    async def scenario():
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            factory = runtime.session_factory
            await add_users(factory, OWNER_ID)
            gates = LocalUserModelingGateService(
                unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(factory)
            )
            identifier = project_id(11)
            await seed_project(
                runtime, gates, project_id=identifier, name="Reopened", members=members_named("A")
            )
            briefs = LocalProjectBriefGateService(
                unit_of_work_factory=SqlAlchemyProjectBriefGateUnitOfWorkFactory(factory)
            )
            service = LocalProjectApplicationService(
                unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(factory)
            )

            async def progress():
                overview = await service.get_overview(project_id=identifier, owner_user_id=OWNER_ID)
                assert overview is not None
                return overview.progress.current_stage, overview.progress.next_action

            assert await progress() == (
                ProjectStage.REQUIREMENTS,
                ProjectNextAction.APPROVE_REQUIREMENTS,
            )
            await reopen_brief(runtime, identifier=identifier)
            assert await progress() == (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)

            submitted = await briefs.submit(project_id=identifier, owner_user_id=OWNER_ID)
            assert submitted.gate is not None and submitted.gate.iteration == 2
            assert await progress() == (ProjectStage.BRIEF, ProjectNextAction.APPROVE_BRIEF)

            await briefs.decide(
                project_id=identifier, owner_user_id=OWNER_ID, action=HumanGateAction.APPROVE
            )
            assert await progress() == (ProjectStage.TEAM, ProjectNextAction.APPROVE_TEAM)
        finally:
            await runtime.dispose()

    run(scenario())


def test_the_number_of_statements_does_not_grow_with_the_projects():
    async def scenario():
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            factory = runtime.session_factory
            await add_users(factory, OWNER_ID)
            for ordinal in range(20, 60):
                await add_project(
                    runtime,
                    identifier=project_id(ordinal),
                    name=f"Many {ordinal}",
                    created_at=CREATED_AT + timedelta(minutes=ordinal),
                    with_brief=ordinal % 2 == 0,
                )
            async with factory() as session:
                overviews, statements = await statements_of(
                    runtime,
                    SqlAlchemyProjectOverviewRepository(session).list_active_owned(
                        owner_user_id=OWNER_ID
                    ),
                )
            assert len(statements) == 1
            assert [overview.project.id for overview in overviews] == [
                project_id(ordinal) for ordinal in range(59, 19, -1)
            ]
            assert {
                overview.progress.next_action
                for overview in overviews
                if overview.project.current_brief_version == 0
            } == {ProjectNextAction.DESCRIBE_IDEA}
            assert {
                overview.progress.next_action
                for overview in overviews
                if overview.project.current_brief_version == 1
            } == {ProjectNextAction.APPROVE_BRIEF}
        finally:
            await runtime.dispose()

    run(scenario())
