"""PostgreSQL integration test for immutable Web revisions and execution attempts."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.artifacts.web_source_persistence import (
    SqlAlchemyWebSourceRevisionUnitOfWork,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempt_persistence import (
    SqlAlchemyWebExecutionAttemptUnitOfWork,
    WebExecutionAttemptAppendStatus,
)
from orchestwin.web_execution.attempts import (
    WebExecutionAttempt,
    WebExecutionAttemptTrigger,
)
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebExecutionReport,
    WebPhaseResult,
    WebPhaseResultStatus,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)
REVISION_ONE_ID = UUID("40000000-0000-4000-8000-000000000101")
REVISION_TWO_ID = UUID("40000000-0000-4000-8000-000000000102")
ATTEMPT_ONE_ID = UUID("40000000-0000-4000-8000-000000000201")
ATTEMPT_TWO_ID = UUID("40000000-0000-4000-8000-000000000202")
FAILURE_SIGNATURE = "9" * 64


async def truncate_application_data(runtime) -> None:
    """Reset owner-scoped data while preserving the migrated schema."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


def source_revision(
    *,
    revision_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    version_number: int,
    predecessor: WebSourceRevision | None,
) -> WebSourceRevision:
    """Create one canonical revision in a two-version repair lineage."""
    content = (
        "<!doctype html><title>Ready</title>"
        if version_number == 1
        else ("<!doctype html><title>Repaired</title>")
    )
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return create_web_source_revision(
        revision_id=revision_id,
        project_id=project_id,
        created_by_user_id=owner_id,
        version_number=version_number,
        based_on=None if predecessor is None else predecessor.reference,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=(
            WebSourceOrigin.DETERMINISTIC_FIXTURE
            if version_number == 1
            else WebSourceOrigin.REPAIR_CHANGE_SET
        ),
        files=(
            WebSourceFileEntry(
                normalized_path="index.html",
                sha256_digest=digest,
                size_bytes=len(content.encode("utf-8")),
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/html",
            ),
        ),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=(
                    WebSourceProvenanceKind.SOURCE_PLAN
                    if version_number == 1
                    else WebSourceProvenanceKind.REPAIR_PROPOSAL
                ),
                reference_id=f"integration:web-source:v{version_number}",
                version_number=version_number,
                content_hash="a" * 64,
            ),
        ),
        related_failure_signature=(None if version_number == 1 else FAILURE_SIGNATURE),
        created_at=BASE_TIME + timedelta(minutes=version_number),
    )


def phase_result(
    phase: WebExecutionPhase,
    *,
    status: WebPhaseResultStatus,
    observed_at: datetime,
) -> WebPhaseResult:
    """Create one normalized phase result without fabricating raw logs."""
    ran = status is WebPhaseResultStatus.PASSED
    return WebPhaseResult(
        phase=phase,
        status=status,
        command_plan_hashes=(),
        started_at=observed_at if ran else None,
        completed_at=observed_at + timedelta(seconds=1) if ran else None,
        exit_codes=(),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary=(
            "Web validation passed."
            if ran
            else "Phase was not required by the persistence integration fixture."
        ),
    )


def execution_attempt(
    *,
    attempt_id: UUID,
    attempt_number: int,
    previous_attempt_id: UUID | None,
    revision: WebSourceRevision,
    owner_id: UUID,
) -> WebExecutionAttempt:
    """Create one terminal attempt bound to an exact source revision."""
    started_at = BASE_TIME + timedelta(minutes=10 + attempt_number)
    report = WebExecutionReport(
        source_revision_content_hash=revision.content_hash,
        source_tree_hash=revision.source_tree_hash,
        profile_id="web.static",
        profile_version="1.0.0",
        runner_image_digest="c" * 64,
        policy_content_hash="d" * 64,
        phase_results=tuple(
            phase_result(
                phase,
                status=(
                    WebPhaseResultStatus.PASSED
                    if phase is WebExecutionPhase.VALIDATE
                    else WebPhaseResultStatus.SKIPPED
                ),
                observed_at=started_at,
            )
            for phase in WebExecutionPhase
        ),
    )
    return WebExecutionAttempt(
        id=attempt_id,
        project_id=revision.project_id,
        created_by_user_id=owner_id,
        attempt_number=attempt_number,
        previous_attempt_id=previous_attempt_id,
        source_revision=revision.reference,
        profile_validation_content_hash="e" * 64,
        execution_plan_content_hash="f" * 64,
        trigger=(
            WebExecutionAttemptTrigger.INITIAL
            if attempt_number == 1
            else WebExecutionAttemptTrigger.REPAIR_RERUN
        ),
        executed_phases=(WebExecutionPhase.VALIDATE,),
        report=report,
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=2),
    )


async def mutation_is_rejected(runtime, *, statement: str, identifier: UUID) -> bool:
    """Return whether one append-only Sprint 08 row rejected direct mutation."""
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(text(statement), {"identifier": identifier})
    except DBAPIError:
        return True
    return False


async def run_integration_scenario() -> None:
    """Exercise migration head, lineage, ownership, idempotency, and immutability."""
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
            email="sprint-eight-owner@example.com",
            password="correct horse battery staple",
        )
        foreign_result = await identity.register(
            email="sprint-eight-foreign@example.com",
            password="another correct battery staple",
        )
        assert owner_result.status is AuthenticationStatus.AUTHENTICATED
        assert foreign_result.status is AuthenticationStatus.AUTHENTICATED
        assert owner_result.authenticated is not None
        assert foreign_result.authenticated is not None
        owner = owner_result.authenticated.user
        foreign = foreign_result.authenticated.user
        project = await projects.create(
            owner_user_id=owner.id,
            display_name="Sprint 08 PostgreSQL fixture",
            mode=ProjectMode.GREENFIELD_GENERATION,
        )

        first_revision = source_revision(
            revision_id=REVISION_ONE_ID,
            project_id=project.id,
            owner_id=owner.id,
            version_number=1,
            predecessor=None,
        )
        second_revision = source_revision(
            revision_id=REVISION_TWO_ID,
            project_id=project.id,
            owner_id=owner.id,
            version_number=2,
            predecessor=first_revision,
        )
        async with SqlAlchemyWebSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            first_append = await unit.revisions.append(first_revision)
            await unit.commit()
        async with SqlAlchemyWebSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            repeated_append = await unit.revisions.append(first_revision)
            second_append = await unit.revisions.append(second_revision)
            await unit.commit()
        assert first_append.status is WebSourceRevisionAppendStatus.APPENDED
        assert repeated_append.status is WebSourceRevisionAppendStatus.ALREADY_PRESENT
        assert second_append.status is WebSourceRevisionAppendStatus.APPENDED

        first_attempt = execution_attempt(
            attempt_id=ATTEMPT_ONE_ID,
            attempt_number=1,
            previous_attempt_id=None,
            revision=first_revision,
            owner_id=owner.id,
        )
        second_attempt = execution_attempt(
            attempt_id=ATTEMPT_TWO_ID,
            attempt_number=2,
            previous_attempt_id=first_attempt.id,
            revision=second_revision,
            owner_id=owner.id,
        )
        async with SqlAlchemyWebExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            first_attempt_append = await unit.attempts.append(first_attempt)
            await unit.commit()
        async with SqlAlchemyWebExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            repeated_attempt_append = await unit.attempts.append(first_attempt)
            second_attempt_append = await unit.attempts.append(second_attempt)
            await unit.commit()
        assert first_attempt_append.status is WebExecutionAttemptAppendStatus.APPENDED
        assert repeated_attempt_append.status is (WebExecutionAttemptAppendStatus.ALREADY_PRESENT)
        assert second_attempt_append.status is WebExecutionAttemptAppendStatus.APPENDED

        async with SqlAlchemyWebSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            owner_revisions = await unit.revisions.history(project_id=project.id)
        async with SqlAlchemyWebExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            owner_attempts = await unit.attempts.history(project_id=project.id)
        async with SqlAlchemyWebSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=foreign.id,
        ) as unit:
            foreign_revisions = await unit.revisions.history(project_id=project.id)
        async with SqlAlchemyWebExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=foreign.id,
        ) as unit:
            foreign_attempts = await unit.attempts.history(project_id=project.id)

        assert owner_revisions == (first_revision, second_revision)
        assert owner_attempts == (first_attempt, second_attempt)
        assert foreign_revisions == ()
        assert foreign_attempts == ()
        assert owner_revisions[1].based_on == owner_revisions[0].reference
        assert owner_attempts[1].previous_attempt_id == owner_attempts[0].id

        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE web_source_revisions SET content_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=REVISION_ONE_ID,
        )
        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE web_execution_attempts SET content_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=ATTEMPT_ONE_ID,
        )

        async with runtime.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        scripts = ScriptDirectory.from_config(
            create_alembic_config(database_settings.url.get_secret_value())
        )
        assert scripts.get_current_head() == "0021_web_execution_attempts"
        assert revision == scripts.get_current_head()
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_web_revision_and_execution_persistence() -> None:
    """Verify the complete Sprint 08 PostgreSQL persistence boundary."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
