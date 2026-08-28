"""PostgreSQL integration coverage for immutable JVM revisions and attempts."""

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

from orchestwin.artifacts.jvm_source_persistence import (
    JvmSourceRevisionAppendStatus,
    SqlAlchemyJvmSourceRevisionUnitOfWork,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
    create_jvm_source_revision,
)
from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.jvm_execution.attempt_persistence import (
    JvmExecutionAttemptAppendStatus,
    SqlAlchemyJvmExecutionAttemptUnitOfWork,
)
from orchestwin.jvm_execution.attempts import (
    JvmExecutionAttempt,
    JvmExecutionAttemptTrigger,
)
from orchestwin.jvm_execution.evidence import (
    JvmExecutionReport,
    JvmExecutionReportStatus,
    JvmPhaseResult,
    JvmPhaseResultStatus,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.sandbox.execution_profiles import ExecutionTarget

pytestmark = pytest.mark.integration

BASE_TIME = datetime(2026, 8, 28, 21, 0, tzinfo=UTC)
REVISION_IDS = (
    UUID("93000000-0000-4000-8000-000000000101"),
    UUID("93000000-0000-4000-8000-000000000102"),
)
ATTEMPT_IDS = (
    UUID("93000000-0000-4000-8000-000000000201"),
    UUID("93000000-0000-4000-8000-000000000202"),
)
FAILURE_SIGNATURE = "9" * 64
EXECUTION_PLAN_HASH = "f" * 64


async def truncate_application_data(runtime) -> None:
    """Reset owner-scoped rows while preserving the migrated schema."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


def source_revision(
    *,
    revision_id: UUID,
    project_id: UUID,
    owner_id: UUID,
    version_number: int,
    predecessor: JvmSourceRevision | None,
) -> JvmSourceRevision:
    """Create one Kotlin source revision in a linear repair lineage."""
    operator = "-" if version_number == 1 else "+"
    content = (
        "package example\n"
        f"fun add(left: Int, right: Int): Int = left {operator} right\n"
        "fun main() = println(add(2, 3))"
    )
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return create_jvm_source_revision(
        revision_id=revision_id,
        project_id=project_id,
        created_by_user_id=owner_id,
        version_number=version_number,
        based_on=None if predecessor is None else predecessor.reference,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=(
            JvmSourceOrigin.DETERMINISTIC_FIXTURE
            if predecessor is None
            else JvmSourceOrigin.REPAIR_CHANGE_SET
        ),
        files=(
            JvmSourceFileEntry(
                normalized_path="src/main/kotlin/example/Calculator.kt",
                sha256_digest=digest,
                size_bytes=len(payload),
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/x-kotlin",
            ),
        ),
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=(
                    JvmSourceProvenanceKind.SOURCE_PLAN
                    if predecessor is None
                    else JvmSourceProvenanceKind.FAILURE_SIGNATURE
                ),
                reference_id=f"integration:jvm-source:v{version_number}",
                version_number=version_number,
                content_hash="a" * 64 if predecessor is None else FAILURE_SIGNATURE,
            ),
        ),
        related_failure_signature=None if predecessor is None else FAILURE_SIGNATURE,
        created_at=BASE_TIME + timedelta(minutes=version_number),
    )


def phase_result(
    phase: JvmExecutionPhase,
    *,
    observed_at: datetime,
) -> JvmPhaseResult:
    """Create a minimal truthful phase result for persistence verification."""
    ran = phase is JvmExecutionPhase.VALIDATE
    return JvmPhaseResult(
        phase=phase,
        status=JvmPhaseResultStatus.PASSED if ran else JvmPhaseResultStatus.SKIPPED,
        command_plan_hash=hashlib.sha256(phase.value.encode("utf-8")).hexdigest(),
        started_at=observed_at if ran else None,
        completed_at=observed_at + timedelta(seconds=1) if ran else None,
        exit_codes=(0,) if ran else (),
        stdout_refs=(),
        stderr_refs=(),
        artifact_refs=(),
        findings=(),
        failure_category=None,
        failure_code=None,
        normalized_summary=(
            "JVM validation passed."
            if ran
            else "Phase was not required by the persistence integration fixture."
        ),
    )


def execution_attempt(
    *,
    attempt_id: UUID,
    attempt_number: int,
    previous_attempt_id: UUID | None,
    revision: JvmSourceRevision,
    owner_id: UUID,
) -> JvmExecutionAttempt:
    """Create an append-only attempt bound to one exact source revision."""
    started_at = BASE_TIME + timedelta(minutes=10 + attempt_number)
    report = JvmExecutionReport(
        target_selection=selection_for(ExecutionTarget.JVM_KOTLIN),
        execution_plan_content_hash=EXECUTION_PLAN_HASH,
        status=JvmExecutionReportStatus.INCOMPLETE,
        phase_results=tuple(
            phase_result(phase, observed_at=started_at) for phase in JvmExecutionPhase
        ),
        failure_signatures=(),
    )
    return JvmExecutionAttempt(
        id=attempt_id,
        project_id=revision.project_id,
        created_by_user_id=owner_id,
        attempt_number=attempt_number,
        previous_attempt_id=previous_attempt_id,
        source_revision=revision.reference,
        profile_id="jvm.kotlin-gradle",
        profile_version="1.0.0",
        profile_validation_content_hash="e" * 64,
        execution_plan_content_hash=EXECUTION_PLAN_HASH,
        runner_id="jvm.gradle",
        runner_version="1.0.0",
        runner_image_digest="c" * 64,
        policy_content_hash="d" * 64,
        trigger=(
            JvmExecutionAttemptTrigger.PROFILE_VALIDATION
            if attempt_number == 1
            else JvmExecutionAttemptTrigger.REPAIR_RERUN
        ),
        executed_phases=(JvmExecutionPhase.VALIDATE,),
        report=report,
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=2),
    )


async def mutation_is_rejected(runtime, *, statement: str, identifier: UUID) -> bool:
    """Return whether an append-only row rejected a direct mutation."""
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(text(statement), {"identifier": identifier})
    except DBAPIError:
        return True
    return False


async def run_integration_scenario() -> None:
    """Verify ownership, lineage, idempotency, migration, and immutability."""
    settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(settings)

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
            email="sprint-nine-owner@example.com",
            password="correct horse battery staple",
        )
        foreign_result = await identity.register(
            email="sprint-nine-foreign@example.com",
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
            display_name="Sprint 09 PostgreSQL JVM fixture",
            mode=ProjectMode.GREENFIELD_GENERATION,
        )

        first_revision = source_revision(
            revision_id=REVISION_IDS[0],
            project_id=project.id,
            owner_id=owner.id,
            version_number=1,
            predecessor=None,
        )
        second_revision = source_revision(
            revision_id=REVISION_IDS[1],
            project_id=project.id,
            owner_id=owner.id,
            version_number=2,
            predecessor=first_revision,
        )
        async with SqlAlchemyJvmSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            first_append = await unit.revisions.append(first_revision)
            await unit.commit()
        async with SqlAlchemyJvmSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            repeated_append = await unit.revisions.append(first_revision)
            second_append = await unit.revisions.append(second_revision)
            await unit.commit()
        assert first_append.status is JvmSourceRevisionAppendStatus.APPENDED
        assert repeated_append.status is JvmSourceRevisionAppendStatus.ALREADY_PRESENT
        assert second_append.status is JvmSourceRevisionAppendStatus.APPENDED

        first_attempt = execution_attempt(
            attempt_id=ATTEMPT_IDS[0],
            attempt_number=1,
            previous_attempt_id=None,
            revision=first_revision,
            owner_id=owner.id,
        )
        second_attempt = execution_attempt(
            attempt_id=ATTEMPT_IDS[1],
            attempt_number=2,
            previous_attempt_id=first_attempt.id,
            revision=second_revision,
            owner_id=owner.id,
        )
        async with SqlAlchemyJvmExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            first_attempt_append = await unit.attempts.append(first_attempt)
            await unit.commit()
        async with SqlAlchemyJvmExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            repeated_attempt_append = await unit.attempts.append(first_attempt)
            second_attempt_append = await unit.attempts.append(second_attempt)
            await unit.commit()
        assert first_attempt_append.status is JvmExecutionAttemptAppendStatus.APPENDED
        assert repeated_attempt_append.status is JvmExecutionAttemptAppendStatus.ALREADY_PRESENT
        assert second_attempt_append.status is JvmExecutionAttemptAppendStatus.APPENDED

        async with SqlAlchemyJvmSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            owner_revisions = await unit.revisions.history(project_id=project.id)
        async with SqlAlchemyJvmExecutionAttemptUnitOfWork(
            runtime.session_factory,
            owner_user_id=owner.id,
        ) as unit:
            owner_attempts = await unit.attempts.history(project_id=project.id)
        async with SqlAlchemyJvmSourceRevisionUnitOfWork(
            runtime.session_factory,
            owner_user_id=foreign.id,
        ) as unit:
            foreign_revisions = await unit.revisions.history(project_id=project.id)
        async with SqlAlchemyJvmExecutionAttemptUnitOfWork(
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
                "UPDATE jvm_source_revisions SET content_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=REVISION_IDS[0],
        )
        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE jvm_execution_attempts SET content_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=ATTEMPT_IDS[0],
        )

        async with runtime.engine.connect() as connection:
            database_revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        scripts = ScriptDirectory.from_config(
            create_alembic_config(settings.url.get_secret_value())
        )
        current_head = scripts.get_current_head()
        assert current_head is not None
        assert database_revision == current_head
        revisions = {
            script.revision for script in scripts.walk_revisions(base="base", head=current_head)
        }
        assert "0022_jvm_source_revisions" in revisions
        assert "0023_jvm_execution_attempts" in revisions
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_jvm_revision_and_execution_persistence() -> None:
    """Verify the complete Sprint 09 PostgreSQL persistence boundary."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
