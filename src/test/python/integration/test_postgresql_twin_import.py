from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from orchestwin.agents.persistence.repositories import SqlAlchemyTeamProposalVersionRepository
from orchestwin.agents.selection_rules import determine_team_constraints
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.knowledge.twin_import import TwinImportError, imported_twin_ids
from orchestwin.knowledge.twin_import_service import TwinImportService, TwinImportStatus
from orchestwin.knowledge.twin_import_sources import (
    SqlAlchemyTwinImportCandidateQuery,
    TwinImportCandidate,
)
from orchestwin.models.fake_team_proposals import FakeDeterministicTeamProposalAdapter
from orchestwin.models.team_proposals import TeamProposalRequest
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import (
    SqlAlchemyProjectRepository,
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_realignment import requirements_are_aligned
from orchestwin.projects.requirements_realignment_service import (
    RequirementsAlignment,
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_runtime import (
    ManagedRequirementsUnitOfWorkFactory,
    SqlAlchemyRequirementsQueryService,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    SqlAlchemyUserTwinVersionRepository,
    VersionAppendStatus,
)
from orchestwin.twins.runtime import (
    ManagedUserModelingUnitOfWorkFactory,
    SqlAlchemyUserModelingGateUnitOfWorkFactory,
    SqlAlchemyUserModelingGovernanceAdapter,
    SqlAlchemyUserModelingQueryService,
)
from orchestwin.twins.user_modeling_gate import (
    LocalUserModelingGateService,
    UserModelingGateDecisionStatus,
    UserModelingGateSubmissionStatus,
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import UserModelingSnapshotVersion, VersionedArtifactReference
from orchestwin.workflow.gates import HumanGateAction, HumanGateType
from src.test.python.integration.test_proposal_evidence_postgres import (
    _approve_gate,
    _persist_pending_gate,
    run,
)
from src.test.python.knowledge.test_twin_import import (
    OWNER_ID,
    SOURCE_PROJECT_ID,
    TARGET_MEMBERS,
    TARGET_PROJECT_ID,
    Member,
    modeling,
)
from src.test.python.knowledge.test_twin_import_service import AUDITOR, RECEPTIONIST
from src.test.python.projects.test_requirements_realignment import requirements_version
from src.test.python.twins.test_user_modeling_application import brief_version

pytestmark = pytest.mark.integration

CREATED_AT = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
FIRST_APPROVAL = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
SECOND_APPROVAL = datetime(2026, 9, 27, 9, 30, tzinfo=UTC)
THIRD_APPROVAL = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
LATEST_APPROVAL = datetime(2026, 9, 27, 11, 0, tzinfo=UTC)
STRANGER_ID = UUID("00000000-0000-4000-8000-00000000f000")
BAKERY_ID = UUID("00000000-0000-4000-8000-00000000d100")
SPA_ID = UUID("00000000-0000-4000-8000-00000000d200")
POOL_ID = UUID("00000000-0000-4000-8000-00000000d300")
ARCHIVED_ID = UUID("00000000-0000-4000-8000-00000000d400")
FOREIGN_ID = UUID("00000000-0000-4000-8000-00000000d500")
TABLES = (
    "persona_profile_versions",
    "user_twin_profile_versions",
    "user_modeling_snapshot_versions",
)


def project_brief(project_id: UUID, name: str, *, owner_id: UUID = OWNER_ID) -> ProjectBriefVersion:
    brief = replace(brief_version().brief, name=name)
    return ProjectBriefVersion(
        id=uuid4(),
        project_id=project_id,
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=owner_id,
        created_at=CREATED_AT,
    )


def members_named(*names: str) -> tuple[Member, ...]:
    return tuple(
        Member(persona_id=uuid4(), twin_id=uuid4(), name=name, role=name.removesuffix(" Twin"))
        for name in names
    )


def approving_at(factory, moment: datetime) -> LocalUserModelingGateService:
    return LocalUserModelingGateService(
        unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(factory),
        clock=lambda: moment,
    )


async def add_users(factory, *user_ids: UUID) -> None:
    async with factory() as session, session.begin():
        session.add_all(
            UserRecord(
                id=user_id,
                email_normalized=f"{user_id}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
            for user_id in user_ids
        )


async def approve(
    runtime, *, project_id: UUID, gate_type: HumanGateType, version, owner_id: UUID = OWNER_ID
) -> None:
    await _persist_pending_gate(
        runtime,
        owner_id=owner_id,
        project_id=project_id,
        gate_id=uuid4(),
        gate_type=gate_type,
        artifact_id=version.id,
        artifact_hash=version.content_hash,
        occurred_at=datetime.now(UTC),
    )
    await _approve_gate(
        runtime,
        owner_id=owner_id,
        project_id=project_id,
        gate_type=gate_type,
        occurred_at=datetime.now(UTC),
    )


async def approve_twins(
    gates: LocalUserModelingGateService, project_id: UUID, *, owner_id: UUID = OWNER_ID
) -> None:
    submitted = await gates.submit(project_id=project_id, owner_user_id=owner_id)
    assert submitted.status is UserModelingGateSubmissionStatus.SUBMITTED
    decided = await gates.decide(
        project_id=project_id, owner_user_id=owner_id, action=HumanGateAction.APPROVE
    )
    assert decided.status is UserModelingGateDecisionStatus.APPLIED


async def seed_project(
    runtime,
    gates: LocalUserModelingGateService,
    *,
    project_id: UUID,
    name: str,
    members: Sequence[Member],
    owner_id: UUID = OWNER_ID,
) -> UserModelingSnapshotVersion:
    brief = project_brief(project_id, name, owner_id=owner_id)
    async with runtime.session_factory() as session, session.begin():
        session.add(
            ProjectRecord(
                id=project_id,
                owner_user_id=owner_id,
                display_name=name,
                mode=ProjectMode.GREENFIELD_GENERATION.value,
                current_brief_version=1,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.flush()
        session.add(
            ProjectBriefVersionRecord(
                id=brief.id,
                project_id=project_id,
                version_number=1,
                schema_version=brief.schema_version,
                content=brief.brief.to_snapshot(),
                content_hash=brief.content_hash,
                created_by_user_id=owner_id,
                created_at=CREATED_AT,
            )
        )
    await approve(
        runtime,
        project_id=project_id,
        gate_type=HumanGateType.PROJECT_BRIEF,
        version=brief,
        owner_id=owner_id,
    )
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
        team = (
            await SqlAlchemyTeamProposalVersionRepository(session).create_generated_owned(
                project_id=project_id, owner_user_id=owner_id, proposal=generation.proposal
            )
        ).version
    await approve(
        runtime,
        project_id=project_id,
        gate_type=HumanGateType.AGENT_TEAM,
        version=team,
        owner_id=owner_id,
    )
    snapshot = modeling(
        project_id,
        members,
        snapshot_id=uuid4(),
        brief=VersionedArtifactReference(brief.id, brief.version_number, brief.content_hash),
        team=VersionedArtifactReference(team.id, team.version_number, team.content_hash),
        catalog_version=team.proposal.catalog_version,
        catalog_hash=team.proposal.catalog_content_hash,
        owner_id=owner_id,
    )
    async with runtime.session_factory() as session, session.begin():
        personas = SqlAlchemyPersonaVersionRepository(session, owner_user_id=owner_id)
        twins = SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner_id)
        snapshots = SqlAlchemyUserModelingSnapshotRepository(session, owner_user_id=owner_id)
        for persona in snapshot.snapshot.persona_versions:
            assert await personas.append(persona) is VersionAppendStatus.APPENDED
        for twin in snapshot.snapshot.twin_versions:
            assert await twins.append(twin) is VersionAppendStatus.APPENDED
        assert await snapshots.append(snapshot) is VersionAppendStatus.APPENDED
    await approve_twins(gates, project_id, owner_id=owner_id)
    return snapshot


async def counts(runtime, project_id: UUID) -> tuple[int, ...]:
    async with runtime.session_factory() as session:
        return tuple(
            [
                await session.scalar(
                    sa.text(f"SELECT count(*) FROM {table} WHERE project_id = :project_id"),
                    {"project_id": project_id},
                )
                for table in TABLES
            ]
        )


def import_service(factory) -> TwinImportService:
    return TwinImportService(
        governance=SqlAlchemyUserModelingGovernanceAdapter(factory),
        uow_factory=ManagedUserModelingUnitOfWorkFactory(factory),
        project_service=LocalProjectApplicationService(
            unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(factory)
        ),
        user_modeling_queries=SqlAlchemyUserModelingQueryService(factory),
        user_modeling_gates=LocalUserModelingGateService(
            unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(factory)
        ),
        candidates=SqlAlchemyTwinImportCandidateQuery(factory),
    )


async def statements_of[T](runtime, operation: Awaitable[T]) -> tuple[T, list[str]]:
    executed: list[str] = []

    def record(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        executed.append(statement)

    engine = runtime.engine.sync_engine
    sa.event.listen(engine, "before_cursor_execute", record)
    try:
        result = await operation
    finally:
        sa.event.remove(engine, "before_cursor_execute", record)
    return result, executed


def test_a_twin_approved_in_one_project_is_imported_into_another_and_requirements_follow():
    async def scenario():
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            factory = runtime.session_factory
            async with factory() as session, session.begin():
                session.add(
                    UserRecord(
                        id=OWNER_ID,
                        email_normalized=f"{OWNER_ID}@synthetic.invalid",
                        password_hash="NO_LOGIN_SYNTHETIC",
                    )
                )
            gates = LocalUserModelingGateService(
                unit_of_work_factory=SqlAlchemyUserModelingGateUnitOfWorkFactory(factory)
            )
            await seed_project(
                runtime,
                gates,
                project_id=SOURCE_PROJECT_ID,
                name="Hotel Operations Studio",
                members=(RECEPTIONIST, AUDITOR),
            )
            written = await seed_project(
                runtime,
                gates,
                project_id=TARGET_PROJECT_ID,
                name="Guest Services Studio",
                members=TARGET_MEMBERS,
            )
            requirements = requirements_version(
                written,
                version_id=uuid4(),
                version_number=1,
                owner_id=OWNER_ID,
                created_at=CREATED_AT,
            )
            async with ManagedRequirementsUnitOfWorkFactory(factory)(
                owner_user_id=OWNER_ID
            ) as unit:
                assert (
                    await unit.specifications.append(requirements)
                    is RequirementsVersionAppendStatus.APPENDED
                )
                await unit.commit()
            queries = SqlAlchemyUserModelingQueryService(factory)
            service = TwinImportService(
                governance=SqlAlchemyUserModelingGovernanceAdapter(factory),
                uow_factory=ManagedUserModelingUnitOfWorkFactory(factory),
                project_service=LocalProjectApplicationService(
                    unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(factory)
                ),
                user_modeling_queries=queries,
                user_modeling_gates=gates,
            )
            realignment = RequirementsRealignmentService(
                uow_factory=ManagedRequirementsUnitOfWorkFactory(factory),
                user_modeling_queries=queries,
                user_modeling_gates=gates,
            )
            scope = {"owner_user_id": OWNER_ID, "project_id": TARGET_PROJECT_ID}

            assert (await realignment.status(**scope)).issue == "REQUIREMENTS_ALREADY_ALIGNED"

            listing = await service.source(**scope, source_project_id=SOURCE_PROJECT_ID)

            assert listing.project_name == "Hotel Operations Studio"
            assert [(twin.name, twin.issue) for twin in listing.twins] == [
                ("Receptionist Twin", None),
                ("Night Auditor Twin", "TWIN_NAME_ALREADY_USED"),
            ]
            before = await counts(runtime, TARGET_PROJECT_ID)

            result = await service.import_from_project(
                **scope, source_project_id=SOURCE_PROJECT_ID, twin_id=RECEPTIONIST.twin_id
            )

            imported = result.imported
            current = await queries.current_snapshot(**scope)
            assert result.status is TwinImportStatus.IMPORTED
            assert current == imported.snapshot_version
            assert (current.version_number, current.snapshot.twin_count) == (2, 3)
            assert imported_twin_ids(current) == {
                RECEPTIONIST.twin_id: imported.twin_version.twin_id
            }
            assert imported.origin.project_name == "Hotel Operations Studio"
            async with factory() as session:
                persona = await SqlAlchemyPersonaVersionRepository(
                    session, owner_user_id=OWNER_ID
                ).current(
                    project_id=TARGET_PROJECT_ID, persona_id=imported.persona_version.persona_id
                )
                twin = await SqlAlchemyUserTwinVersionRepository(
                    session, owner_user_id=OWNER_ID
                ).current(project_id=TARGET_PROJECT_ID, twin_id=imported.twin_version.twin_id)
            assert persona == imported.persona_version
            assert twin == imported.twin_version
            assert await counts(runtime, TARGET_PROJECT_ID) == tuple(count + 1 for count in before)
            assert not user_modeling_gate_is_currently_approved(
                await gates.current_gate(project_id=TARGET_PROJECT_ID, owner_user_id=OWNER_ID),
                current,
            )

            with pytest.raises(TwinImportError) as repeated:
                await service.import_from_project(
                    **scope, source_project_id=SOURCE_PROJECT_ID, twin_id=RECEPTIONIST.twin_id
                )
            with pytest.raises(TwinImportError) as stranger:
                await service.import_from_project(
                    owner_user_id=STRANGER_ID,
                    project_id=TARGET_PROJECT_ID,
                    source_project_id=SOURCE_PROJECT_ID,
                    twin_id=AUDITOR.twin_id,
                )
            assert repeated.value.code == "TWIN_ALREADY_IMPORTED"
            assert stranger.value.code == "SOURCE_PROJECT_NOT_FOUND"
            assert await counts(runtime, TARGET_PROJECT_ID) == tuple(count + 1 for count in before)

            assert await realignment.status(**scope) == RequirementsAlignment(
                aligned=False,
                issue="USER_TWINS_APPROVAL_REQUIRED",
                requirements_version_number=1,
                snapshot_version_number=2,
                twins_approved=False,
            )
            await approve_twins(gates, TARGET_PROJECT_ID)
            assert await realignment.status(**scope) == RequirementsAlignment(
                aligned=False,
                issue=None,
                requirements_version_number=1,
                snapshot_version_number=2,
                twins_approved=True,
            )

            version = await realignment.realign(**scope)

            stored = await SqlAlchemyRequirementsQueryService(factory).current(**scope)
            assert stored == version
            assert (version.version_number, version.based_on_version_number) == (2, 1)
            assert requirements_are_aligned(stored.specification, current)
            assert len(stored.specification.user_twin_references) == 3
            assert await realignment.status(**scope) == RequirementsAlignment(
                aligned=True,
                issue="REQUIREMENTS_ALREADY_ALIGNED",
                requirements_version_number=2,
                snapshot_version_number=2,
                twins_approved=True,
            )
        finally:
            await runtime.dispose()

    run(scenario())


def test_only_other_active_projects_of_the_owner_whose_current_twins_are_approved_are_offered():
    async def scenario():
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            factory = runtime.session_factory
            await add_users(factory, OWNER_ID, STRANGER_ID)
            for project_id, name, twins, approved_at, owner_id in (
                (
                    SOURCE_PROJECT_ID,
                    "Hotel Operations Studio",
                    (RECEPTIONIST, AUDITOR),
                    FIRST_APPROVAL,
                    OWNER_ID,
                ),
                (BAKERY_ID, "Bakery Studio", members_named("Baker Twin"), FIRST_APPROVAL, OWNER_ID),
                (
                    TARGET_PROJECT_ID,
                    "Guest Services Studio",
                    TARGET_MEMBERS,
                    SECOND_APPROVAL,
                    OWNER_ID,
                ),
                (
                    SPA_ID,
                    "Spa Studio",
                    members_named("Zoe Twin", "anna Twin", "Bruno Twin"),
                    THIRD_APPROVAL,
                    OWNER_ID,
                ),
                (
                    POOL_ID,
                    "Pool Studio",
                    members_named("Lifeguard Twin"),
                    LATEST_APPROVAL,
                    OWNER_ID,
                ),
                (
                    ARCHIVED_ID,
                    "Archived Studio",
                    members_named("Archivist Twin"),
                    LATEST_APPROVAL,
                    OWNER_ID,
                ),
                (
                    FOREIGN_ID,
                    "Stranger Studio",
                    members_named("Stranger Twin"),
                    LATEST_APPROVAL,
                    STRANGER_ID,
                ),
            ):
                await seed_project(
                    runtime,
                    approving_at(factory, approved_at),
                    project_id=project_id,
                    name=name,
                    members=twins,
                    owner_id=owner_id,
                )
            service = import_service(factory)
            await service.import_from_project(
                owner_user_id=OWNER_ID,
                project_id=POOL_ID,
                source_project_id=SOURCE_PROJECT_ID,
                twin_id=RECEPTIONIST.twin_id,
            )
            async with factory() as session, session.begin():
                assert await SqlAlchemyProjectRepository(session).archive_owned(
                    project_id=ARCHIVED_ID, owner_user_id=OWNER_ID
                )
            query = SqlAlchemyTwinImportCandidateQuery(factory)
            spa = TwinImportCandidate(
                project_id=SPA_ID,
                project_name="Spa Studio",
                snapshot_version_number=1,
                approved_at=THIRD_APPROVAL,
                twin_names=("anna Twin", "Bruno Twin", "Zoe Twin"),
            )
            guests = TwinImportCandidate(
                project_id=TARGET_PROJECT_ID,
                project_name="Guest Services Studio",
                snapshot_version_number=1,
                approved_at=SECOND_APPROVAL,
                twin_names=("Concierge Twin", "Night Auditor Twin"),
            )
            bakery = TwinImportCandidate(
                project_id=BAKERY_ID,
                project_name="Bakery Studio",
                snapshot_version_number=1,
                approved_at=FIRST_APPROVAL,
                twin_names=("Baker Twin",),
            )
            hotel = TwinImportCandidate(
                project_id=SOURCE_PROJECT_ID,
                project_name="Hotel Operations Studio",
                snapshot_version_number=1,
                approved_at=FIRST_APPROVAL,
                twin_names=("Night Auditor Twin", "Receptionist Twin"),
            )

            listing, statements = await statements_of(
                runtime, query.list(owner_user_id=OWNER_ID, exclude_project_id=TARGET_PROJECT_ID)
            )

            assert listing == (spa, bakery, hotel)
            assert len(statements) == 2
            assert await query.list(
                owner_user_id=OWNER_ID, exclude_project_id=SOURCE_PROJECT_ID
            ) == (spa, guests, bakery)
            assert await query.list(
                owner_user_id=OWNER_ID, exclude_project_id=TARGET_PROJECT_ID, limit=1
            ) == (spa,)
            assert await query.list(
                owner_user_id=STRANGER_ID, exclude_project_id=TARGET_PROJECT_ID
            ) == (
                TwinImportCandidate(
                    project_id=FOREIGN_ID,
                    project_name="Stranger Studio",
                    snapshot_version_number=1,
                    approved_at=LATEST_APPROVAL,
                    twin_names=("Stranger Twin",),
                ),
            )
            assert await service.sources(owner_user_id=OWNER_ID, project_id=TARGET_PROJECT_ID) == (
                listing
            )
            with pytest.raises(TwinImportError) as stranger:
                await service.sources(owner_user_id=STRANGER_ID, project_id=TARGET_PROJECT_ID)
            with pytest.raises(TwinImportError) as archived:
                await service.sources(owner_user_id=OWNER_ID, project_id=ARCHIVED_ID)
            with pytest.raises(ValueError, match="limit must be positive"):
                await query.list(
                    owner_user_id=OWNER_ID, exclude_project_id=TARGET_PROJECT_ID, limit=0
                )
            assert stranger.value.code == archived.value.code == "PROJECT_NOT_FOUND"
        finally:
            await runtime.dispose()

    run(scenario())
