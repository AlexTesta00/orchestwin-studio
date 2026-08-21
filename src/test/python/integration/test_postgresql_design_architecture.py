"""PostgreSQL integration test for Sprint 06 Design and Architecture stages."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.artifacts.architecture_gate import (
    ArchitectureGateDecisionStatus,
    ArchitectureGateSubmissionStatus,
    ArchitectureWorkflowReadiness,
    LocalArchitectureGateService,
)
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    create_architecture_grounding,
)
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureRevisionStatus,
    LocalArchitectureRevisionService,
)
from orchestwin.artifacts.architecture_revisions import ArchitectureRevisionDecision
from orchestwin.artifacts.design_gate import (
    DesignGateDecisionStatus,
    DesignGateSubmissionStatus,
    DesignWorkflowReadiness,
    LocalDesignGateService,
)
from orchestwin.artifacts.design_packages import (
    DesignPackageVersion,
    create_design_grounding,
)
from orchestwin.artifacts.design_revision_application import (
    DesignRevisionStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import DesignRevisionDecision
from orchestwin.artifacts.traceability import ArtifactGraphNodeKind
from orchestwin.artifacts.traceability_runtime import SqlAlchemyArtifactGraphQueryService
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
from orchestwin.projects.architecture_application import ArchitectureVersionAppendStatus
from orchestwin.projects.architecture_runtime import (
    ManagedArchitectureUnitOfWorkFactory,
    SqlAlchemyArchitectureGateUnitOfWorkFactory,
    SqlAlchemyArchitectureQueryService,
)
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.design_runtime import (
    ManagedDesignUnitOfWorkFactory,
    SqlAlchemyDesignGateUnitOfWorkFactory,
    SqlAlchemyDesignQueryService,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.projects.requirements_application import RequirementsVersionAppendStatus
from orchestwin.projects.requirements_runtime import ManagedRequirementsUnitOfWorkFactory
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus

pytestmark = pytest.mark.integration

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"
FIXTURE_PACKAGE_NAME = "sprint_six_postgresql_fixtures"

REQUIREMENTS_VERSION_ID = UUID("00000000-0000-4000-8000-000000001001")
DESIGN_VERSION_ONE_ID = UUID("00000000-0000-4000-8000-000000001010")
DESIGN_DIFF_ID = UUID("00000000-0000-4000-8000-000000001011")
DESIGN_VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000001012")
DESIGN_GATE_ID = UUID("00000000-0000-4000-8000-000000001013")
DESIGN_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000001014")
DESIGN_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000001015")
ARCHITECTURE_VERSION_ONE_ID = UUID("00000000-0000-4000-8000-000000001020")
ARCHITECTURE_DIFF_ID = UUID("00000000-0000-4000-8000-000000001021")
ARCHITECTURE_VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000001022")
ARCHITECTURE_GATE_ID = UUID("00000000-0000-4000-8000-000000001023")
ARCHITECTURE_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000001024")
ARCHITECTURE_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000001025")

BASE_TIME = datetime(2026, 8, 21, 16, 0, tzinfo=UTC)


def load_fixture_modules() -> tuple[ModuleType, ModuleType]:
    """Load test-only Design and Architecture fixtures as one isolated package."""
    package = ModuleType(FIXTURE_PACKAGE_NAME)
    package.__path__ = [str(FIXTURE_DIRECTORY)]
    sys.modules[FIXTURE_PACKAGE_NAME] = package

    design = _load_fixture_module("design_fixtures")
    architecture = _load_fixture_module("architecture_fixtures")
    return design, architecture


def _load_fixture_module(name: str) -> ModuleType:
    """Load one package-local fixture module without production fixture leakage."""
    module_name = f"{FIXTURE_PACKAGE_NAME}.{name}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        FIXTURE_DIRECTORY / f"{name}.py",
    )

    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DESIGN_FIXTURES, ARCHITECTURE_FIXTURES = load_fixture_modules()


async def truncate_application_data(runtime) -> None:
    """Reset owner-scoped data while preserving the migrated schema."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


def iterator_factory(values):
    """Return one deterministic zero-argument factory over supplied values."""
    iterator = iter(values)

    def next_value():
        return next(iterator)

    return next_value


def scoped_requirements_version(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> RequirementsSpecificationVersion:
    """Re-scope the shared immutable Requirements fixture to a persisted project."""
    base = DESIGN_FIXTURES.requirements_version()
    specification = replace(base.specification, project_id=project_id)

    return replace(
        base,
        id=REQUIREMENTS_VERSION_ID,
        project_id=project_id,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=owner_user_id,
        created_at=BASE_TIME,
    )


def scoped_design_version(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    requirements: RequirementsSpecificationVersion,
) -> DesignPackageVersion:
    """Create a ready Design Package grounded in the persisted Requirements version."""
    base_package = DESIGN_FIXTURES.design_package()
    package = replace(
        base_package,
        project_id=project_id,
        grounding=create_design_grounding(requirements),
    )

    return DesignPackageVersion(
        id=DESIGN_VERSION_ONE_ID,
        project_id=project_id,
        version_number=1,
        based_on_version_number=None,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=owner_user_id,
        created_at=BASE_TIME + timedelta(minutes=1),
    )


def scoped_architecture_version(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    design: DesignPackageVersion,
) -> ArchitecturePackageVersion:
    """Create an Architecture Package grounded in the exact approved Design version."""
    base_package = ARCHITECTURE_FIXTURES.architecture_package()
    package = replace(
        base_package,
        project_id=project_id,
        grounding=create_architecture_grounding(design),
    )

    return ArchitecturePackageVersion(
        id=ARCHITECTURE_VERSION_ONE_ID,
        project_id=project_id,
        version_number=1,
        based_on_version_number=None,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=owner_user_id,
        created_at=BASE_TIME + timedelta(minutes=6),
    )


async def immutable_update_is_rejected(
    runtime,
    *,
    statement: str,
    version_id: UUID,
) -> bool:
    """Return whether PostgreSQL rejected a forbidden version-row update."""
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(
                text(statement),
                {
                    "content_hash": "0" * 64,
                    "version_id": version_id,
                },
            )
    except DBAPIError:
        return True

    return False


async def run_integration_scenario() -> None:
    """Exercise persistence, revisions, Gates 5-6, traceability, and ownership."""
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
            email="sprint-six-owner@example.com",
            password="correct horse battery staple",
        )
        other_result = await identity.register(
            email="sprint-six-other@example.com",
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
            display_name="Sprint 06 integration project",
            mode=ProjectMode.GREENFIELD_GENERATION,
        )

        requirements = scoped_requirements_version(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        requirements_uow_factory = ManagedRequirementsUnitOfWorkFactory(runtime.session_factory)

        async with requirements_uow_factory(owner_user_id=owner.id) as unit:
            append_status = await unit.specifications.append(requirements)
            assert append_status is RequirementsVersionAppendStatus.APPENDED
            await unit.commit()

        design_v1 = scoped_design_version(
            project_id=project.id,
            owner_user_id=owner.id,
            requirements=requirements,
        )
        design_uow_factory = ManagedDesignUnitOfWorkFactory(runtime.session_factory)

        async with design_uow_factory(owner_user_id=owner.id) as unit:
            design_append = await unit.packages.append(design_v1)
            assert design_append is DesignVersionAppendStatus.APPENDED
            await unit.commit()

        design_revisions = LocalDesignRevisionService(
            uow_factory=design_uow_factory,
            uuid_factory=iterator_factory((DESIGN_DIFF_ID, DESIGN_VERSION_TWO_ID)),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=2),
                    BASE_TIME + timedelta(minutes=3),
                )
            ),
        )
        design_proposal = await design_revisions.propose_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            proposed_package=replace(
                design_v1.package,
                open_questions=(
                    *design_v1.package.open_questions,
                    "Which keyboard shortcuts require validation before implementation?",
                ),
            ),
        )

        assert design_proposal.status is DesignRevisionStatus.CREATED
        assert design_proposal.diff is not None
        assert design_proposal.diff.id == DESIGN_DIFF_ID

        design_decision = await design_revisions.decide_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            diff_id=DESIGN_DIFF_ID,
            decision=DesignRevisionDecision.APPROVE,
        )

        assert design_decision.status is DesignRevisionStatus.APPLIED
        assert design_decision.version is not None
        design_v2 = design_decision.version
        assert design_v2.id == DESIGN_VERSION_TWO_ID
        assert design_v2.version_number == 2
        assert design_v2.based_on_version_number == 1

        design_gate = LocalDesignGateService(
            unit_of_work_factory=SqlAlchemyDesignGateUnitOfWorkFactory(runtime.session_factory),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=4),
                    BASE_TIME + timedelta(minutes=5),
                )
            ),
            gate_id_factory=lambda: DESIGN_GATE_ID,
            event_id_factory=iterator_factory((DESIGN_SUBMIT_EVENT_ID, DESIGN_APPROVE_EVENT_ID)),
        )
        design_submission = await design_gate.submit(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        design_approval = await design_gate.decide(
            project_id=project.id,
            owner_user_id=owner.id,
            action=HumanGateAction.APPROVE,
        )
        design_readiness = await design_gate.readiness(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        design_events = await design_gate.gate_events(
            project_id=project.id,
            owner_user_id=owner.id,
            gate_id=DESIGN_GATE_ID,
        )

        assert design_submission.status is DesignGateSubmissionStatus.SUBMITTED
        assert design_approval.status is DesignGateDecisionStatus.APPLIED
        assert design_approval.gate is not None
        assert design_approval.gate.status is HumanGateStatus.APPROVED
        assert design_approval.gate.artifact.artifact_id == DESIGN_VERSION_TWO_ID
        assert design_readiness.status is DesignWorkflowReadiness.READY_FOR_ARCHITECTURE_PLANNING
        assert len(design_events) == 2

        design_queries = SqlAlchemyDesignQueryService(runtime.session_factory)
        assert (
            await design_queries.current(
                owner_user_id=owner.id,
                project_id=project.id,
            )
            == design_v2
        )
        assert tuple(
            version.version_number
            for version in await design_queries.history(
                owner_user_id=owner.id,
                project_id=project.id,
            )
        ) == (1, 2)
        assert (
            await design_queries.current(
                owner_user_id=other.id,
                project_id=project.id,
            )
            is None
        )
        design_diff_history = await design_queries.diff_history(
            owner_user_id=owner.id,
            project_id=project.id,
        )
        assert len(design_diff_history) == 1
        assert design_diff_history[0].applied_version_id == DESIGN_VERSION_TWO_ID

        architecture_v1 = scoped_architecture_version(
            project_id=project.id,
            owner_user_id=owner.id,
            design=design_v2,
        )
        architecture_uow_factory = ManagedArchitectureUnitOfWorkFactory(runtime.session_factory)

        async with architecture_uow_factory(owner_user_id=owner.id) as unit:
            architecture_append = await unit.packages.append(architecture_v1)
            assert architecture_append is ArchitectureVersionAppendStatus.APPENDED
            await unit.commit()

        architecture_revisions = LocalArchitectureRevisionService(
            uow_factory=architecture_uow_factory,
            uuid_factory=iterator_factory((ARCHITECTURE_DIFF_ID, ARCHITECTURE_VERSION_TWO_ID)),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=7),
                    BASE_TIME + timedelta(minutes=8),
                )
            ),
        )
        architecture_proposal = await architecture_revisions.propose_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            proposed_package=replace(
                architecture_v1.package,
                open_questions=(
                    *architecture_v1.package.open_questions,
                    "Which validated execution profile will implement the approved plan?",
                ),
            ),
        )

        assert architecture_proposal.status is ArchitectureRevisionStatus.CREATED
        assert architecture_proposal.diff is not None
        assert architecture_proposal.diff.id == ARCHITECTURE_DIFF_ID

        architecture_decision = await architecture_revisions.decide_revision(
            owner_user_id=owner.id,
            project_id=project.id,
            diff_id=ARCHITECTURE_DIFF_ID,
            decision=ArchitectureRevisionDecision.APPROVE,
        )

        assert architecture_decision.status is ArchitectureRevisionStatus.APPLIED
        assert architecture_decision.version is not None
        architecture_v2 = architecture_decision.version
        assert architecture_v2.id == ARCHITECTURE_VERSION_TWO_ID
        assert architecture_v2.version_number == 2
        assert architecture_v2.based_on_version_number == 1
        assert (
            architecture_v2.package.grounding.design_package_reference
            == create_architecture_grounding(design_v2).design_package_reference
        )

        architecture_gate = LocalArchitectureGateService(
            unit_of_work_factory=SqlAlchemyArchitectureGateUnitOfWorkFactory(
                runtime.session_factory
            ),
            clock=iterator_factory(
                (
                    BASE_TIME + timedelta(minutes=9),
                    BASE_TIME + timedelta(minutes=10),
                )
            ),
            gate_id_factory=lambda: ARCHITECTURE_GATE_ID,
            event_id_factory=iterator_factory(
                (ARCHITECTURE_SUBMIT_EVENT_ID, ARCHITECTURE_APPROVE_EVENT_ID)
            ),
        )
        architecture_submission = await architecture_gate.submit(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        architecture_approval = await architecture_gate.decide(
            project_id=project.id,
            owner_user_id=owner.id,
            action=HumanGateAction.APPROVE,
        )
        architecture_readiness = await architecture_gate.readiness(
            project_id=project.id,
            owner_user_id=owner.id,
        )
        architecture_events = await architecture_gate.gate_events(
            project_id=project.id,
            owner_user_id=owner.id,
            gate_id=ARCHITECTURE_GATE_ID,
        )

        assert architecture_submission.status is ArchitectureGateSubmissionStatus.SUBMITTED
        assert architecture_approval.status is ArchitectureGateDecisionStatus.APPLIED
        assert architecture_approval.gate is not None
        assert architecture_approval.gate.status is HumanGateStatus.APPROVED
        assert architecture_approval.gate.artifact.artifact_id == ARCHITECTURE_VERSION_TWO_ID
        assert (
            architecture_readiness.status is ArchitectureWorkflowReadiness.READY_FOR_IMPLEMENTATION
        )
        assert len(architecture_events) == 2

        architecture_queries = SqlAlchemyArchitectureQueryService(runtime.session_factory)
        assert (
            await architecture_queries.current(
                owner_user_id=owner.id,
                project_id=project.id,
            )
            == architecture_v2
        )
        assert tuple(
            version.version_number
            for version in await architecture_queries.history(
                owner_user_id=owner.id,
                project_id=project.id,
            )
        ) == (1, 2)
        assert (
            await architecture_queries.current(
                owner_user_id=other.id,
                project_id=project.id,
            )
            is None
        )
        architecture_diff_history = await architecture_queries.diff_history(
            owner_user_id=owner.id,
            project_id=project.id,
        )
        assert len(architecture_diff_history) == 1
        assert architecture_diff_history[0].applied_version_id == ARCHITECTURE_VERSION_TWO_ID

        graph_queries = SqlAlchemyArtifactGraphQueryService(runtime.session_factory)
        graph = await graph_queries.current(
            owner_user_id=owner.id,
            project_id=project.id,
        )

        assert graph is not None
        assert (
            graph.requirements_reference
            == create_design_grounding(requirements).requirements_reference
        )
        assert (
            graph.design_reference
            == create_architecture_grounding(design_v2).design_package_reference
        )
        assert graph.architecture_reference == architecture_v2.reference
        assert graph.nodes
        assert graph.links
        assert {
            ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION,
            ArtifactGraphNodeKind.DESIGN_PACKAGE,
            ArtifactGraphNodeKind.ARCHITECTURE_PACKAGE,
            ArtifactGraphNodeKind.TEST_PLAN,
        }.issubset({node.reference.kind for node in graph.nodes})
        assert (
            await graph_queries.current(
                owner_user_id=other.id,
                project_id=project.id,
            )
            is None
        )

        assert await immutable_update_is_rejected(
            runtime,
            statement=(
                "UPDATE design_package_versions SET content_hash = :content_hash "
                "WHERE id = :version_id"
            ),
            version_id=DESIGN_VERSION_TWO_ID,
        )
        assert await immutable_update_is_rejected(
            runtime,
            statement=(
                "UPDATE architecture_package_versions SET content_hash = :content_hash "
                "WHERE id = :version_id"
            ),
            version_id=ARCHITECTURE_VERSION_TWO_ID,
        )

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))

        scripts = ScriptDirectory.from_config(
            create_alembic_config(database_settings.url.get_secret_value())
        )
        assert revision == scripts.get_current_head()
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_design_architecture_and_gate_main_path() -> None:
    """Verify the complete persisted Sprint 06 path on migrated PostgreSQL."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
