"""PostgreSQL integration test for Requirements persistence and Gate 4."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_gate import (
    LocalRequirementsGateService,
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionStatus,
    RequirementsWorkflowReadiness,
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
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
    RequirementsRevisionDecision,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_runtime import (
    ManagedRequirementsUnitOfWorkFactory,
    SqlAlchemyRequirementsGateUnitOfWorkFactory,
    SqlAlchemyRequirementsQueryService,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus

pytestmark = pytest.mark.integration

INITIAL_VERSION_ID = UUID("00000000-0000-4000-8000-000000000101")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000102")
REVISED_VERSION_ID = UUID("00000000-0000-4000-8000-000000000103")
GATE_ID = UUID("00000000-0000-4000-8000-000000000104")
SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000105")
APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000106")

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000110")
STORY_ID = UUID("00000000-0000-4000-8000-000000000120")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000130")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000140")
DOD_ID = UUID("00000000-0000-4000-8000-000000000150")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000160")

BASE_TIME = datetime(2026, 8, 18, 11, 0, tzinfo=UTC)


async def truncate_application_data(runtime) -> None:
    """Reset user-owned application data while preserving Alembic state."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed input reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create the exact User Twin referenced by the requirements baseline."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def initial_specification_version(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> RequirementsSpecificationVersion:
    """Create one complete version-one requirements baseline."""
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id=str(UUID(int=11)),
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create hotel reservations.",
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
        benefit="serve a guest without booking conflicts",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A valid reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=("The receptionist is authenticated.",),
        trigger="A guest requests a room.",
        steps=("Save a valid reservation.",),
        expected_outcome="The reservation can be retrieved by its identifier.",
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
        project_id=project_id,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
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
        id=INITIAL_VERSION_ID,
        project_id=project_id,
        version_number=1,
        based_on_version_number=None,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=owner_user_id,
        created_at=BASE_TIME,
    )


def iterator_factory(values):
    """Return one zero-argument factory over deterministic fixture values."""
    iterator = iter(values)

    def next_value():
        return next(iterator)

    return next_value


async def run_integration_scenario() -> None:
    """Exercise requirements persistence, revisioning, Gate 4, and ownership."""
    database_settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(database_settings)

    try:
        await truncate_application_data(runtime)

        identity = LocalIdentityApplicationService(
            unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory),
            password_service=Argon2PasswordService(),
            access_token_service=JwtAccessTokenService(
                AccessTokenSettings(
                    jwt_secret=SecretStr(
                        "integration-test-jwt-secret-with-more-than-32-characters"
                    ),
                    access_token_leeway_seconds=0,
                    _env_file=None,
                )
            ),
        )
        projects = LocalProjectApplicationService(
            unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory)
        )

        owner_result = await identity.register(
            email="requirements-owner@example.com",
            password="correct horse battery staple",
        )
        other_result = await identity.register(
            email="requirements-other@example.com",
            password="another correct battery staple",
        )

        assert owner_result.status is AuthenticationStatus.AUTHENTICATED
        assert other_result.status is AuthenticationStatus.AUTHENTICATED
        assert owner_result.authenticated is not None
        assert other_result.authenticated is not None

        owner = owner_result.authenticated.user
        other = other_result.authenticated.user
        project = await projects.create(
            owner_user_id=owner.id,
            display_name="Requirements integration project",
            mode=ProjectMode.GREENFIELD_GENERATION,
        )

        command_uow_factory = ManagedRequirementsUnitOfWorkFactory(runtime.session_factory)
        initial = initial_specification_version(
            project_id=project.id,
            owner_user_id=owner.id,
        )

        async with command_uow_factory(owner_user_id=owner.id) as unit:
            append_status = await unit.specifications.append(initial)
            assert append_status is RequirementsVersionAppendStatus.APPENDED
            await unit.commit()

        queries = SqlAlchemyRequirementsQueryService(runtime.session_factory)
        current = await queries.current(
            owner_user_id=owner.id,
            project_id=project.id,
        )

        assert current == initial
        assert (
            await queries.current(
                owner_user_id=other.id,
                project_id=project.id,
            )
            is None
        )

        revised_requirement = replace(
            current.specification.requirements[0],
            statement=(
                "The system must create hotel reservations and prevent "
                "overlapping room allocations."
            ),
        )
        proposed_specification = replace(
            current.specification,
            requirements=(revised_requirement,),
        )
        revisions = LocalRequirementsRevisionService(
            uow_factory=command_uow_factory,
            uuid_factory=iterator_factory((DIFF_ID, REVISED_VERSION_ID)),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=1),
                    BASE_TIME + timedelta(minutes=2),
                )
            ),
        )

        proposal = await revisions.propose_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            proposed_specification=proposed_specification,
        )

        assert proposal.status is RequirementsRevisionStatus.CREATED
        assert proposal.diff is not None
        assert proposal.diff.id == DIFF_ID

        decision = await revisions.decide_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            diff_id=DIFF_ID,
            decision=RequirementsRevisionDecision.APPROVE,
        )

        assert decision.status is RequirementsRevisionStatus.APPLIED
        assert decision.version is not None
        assert decision.version.id == REVISED_VERSION_ID
        assert decision.version.version_number == 2
        assert decision.version.based_on_version_number == 1

        history = await queries.history(
            owner_user_id=owner.id,
            project_id=project.id,
        )
        diff_history = await queries.diff_history(
            owner_user_id=owner.id,
            project_id=project.id,
        )

        assert tuple(version.version_number for version in history) == (1, 2)
        assert len(diff_history) == 1
        assert diff_history[0].applied_specification_version_id == REVISED_VERSION_ID

        gate = LocalRequirementsGateService(
            unit_of_work_factory=SqlAlchemyRequirementsGateUnitOfWorkFactory(
                runtime.session_factory
            ),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=3),
                    BASE_TIME + timedelta(minutes=4),
                )
            ),
            gate_id_factory=lambda: GATE_ID,
            event_id_factory=iterator_factory((SUBMIT_EVENT_ID, APPROVE_EVENT_ID)),
        )

        submission = await gate.submit(
            project_id=project.id,
            owner_user_id=owner.id,
        )

        assert submission.status is RequirementsGateSubmissionStatus.SUBMITTED
        assert submission.gate is not None
        assert submission.gate.artifact.artifact_id == REVISED_VERSION_ID
        assert submission.gate.status is HumanGateStatus.PENDING_APPROVAL

        approval = await gate.decide(
            project_id=project.id,
            owner_user_id=owner.id,
            action=HumanGateAction.APPROVE,
        )

        assert approval.status is RequirementsGateDecisionStatus.APPLIED
        assert approval.gate is not None
        assert approval.gate.status is HumanGateStatus.APPROVED

        readiness = await gate.readiness(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        events = await gate.gate_events(
            project_id=project.id,
            owner_user_id=owner.id,
            gate_id=GATE_ID,
        )

        assert readiness.status is RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION
        assert len(events) == 2

        async with runtime.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        text(
                            "SELECT traceability_snapshot, coverage_snapshot "
                            "FROM requirements_specification_versions "
                            "WHERE id = :version_id"
                        ),
                        {"version_id": REVISED_VERSION_ID},
                    )
                )
                .mappings()
                .one()
            )

            assert row["traceability_snapshot"]["links"]
            assert row["coverage_snapshot"]["has_full_acceptance_coverage"] is True

        mutation_rejected = False

        try:
            async with runtime.session_factory.begin() as session:
                await session.execute(
                    text(
                        "UPDATE requirements_specification_versions "
                        "SET content_hash = :content_hash "
                        "WHERE id = :version_id"
                    ),
                    {
                        "content_hash": "0" * 64,
                        "version_id": REVISED_VERSION_ID,
                    },
                )
        except DBAPIError:
            mutation_rejected = True

        assert mutation_rejected is True

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        scripts = ScriptDirectory.from_config(
            create_alembic_config(database_settings.url.get_secret_value())
        )

        assert revision == scripts.get_current_head()
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_requirements_and_gate_four_main_path() -> None:
    """Verify the Requirements stage on a migrated PostgreSQL database."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
