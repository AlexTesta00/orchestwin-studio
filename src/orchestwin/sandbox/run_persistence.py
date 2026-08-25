"""Owner-scoped append-only persistence for terminal sandbox run evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.projects.brownfield_persistence import BROWNFIELD_INTAKE_VERSIONS
from orchestwin.projects.domain import Project
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_sha256,
)
from orchestwin.sandbox.evidence import SandboxCommandStatus, SandboxRunStatus
from orchestwin.sandbox.project_runs import (
    PROJECT_SANDBOX_RUN_SCHEMA_VERSION,
    ProjectSandboxRunEvidence,
)

SANDBOX_RUNS = sa.Table(
    "sandbox_runs",
    OrmBase.metadata,
    sa.Column("run_id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id",
        sa.Uuid,
        sa.ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "intake_id",
        sa.Uuid,
        sa.ForeignKey("brownfield_intake_versions.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.Column("intake_version_number", sa.Integer, nullable=True),
    sa.Column("intake_content_hash", sa.String(64), nullable=True),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("evidence_content_hash", sa.String(64), nullable=False),
    sa.Column("plan_id", sa.String(128), nullable=False),
    sa.Column("plan_content_hash", sa.String(64), nullable=False),
    sa.Column("profile_id", sa.String(128), nullable=False),
    sa.Column("profile_version", sa.String(64), nullable=False),
    sa.Column("image_reference", sa.Text, nullable=False),
    sa.Column("runtime_reference", sa.String(128), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("failure_message", sa.Text, nullable=True),
    sa.Column("evidence_snapshot", JSONB, nullable=False),
    sa.Column(
        "created_by_user_id",
        sa.Uuid,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("schema_version > 0", name="positive_schema"),
    sa.CheckConstraint(
        "evidence_content_hash ~ '^[0-9a-f]{64}$'",
        name="evidence_content_hash",
    ),
    sa.CheckConstraint(
        "plan_content_hash ~ '^[0-9a-f]{64}$'",
        name="plan_content_hash",
    ),
    sa.CheckConstraint(
        "intake_content_hash IS NULL OR intake_content_hash ~ '^[0-9a-f]{64}$'",
        name="intake_content_hash",
    ),
    sa.CheckConstraint(
        "(intake_id IS NULL AND intake_version_number IS NULL "
        "AND intake_content_hash IS NULL) OR "
        "(intake_id IS NOT NULL AND intake_version_number > 0 "
        "AND intake_content_hash IS NOT NULL)",
        name="intake_reference_shape",
    ),
    sa.CheckConstraint("finished_at >= started_at", name="time_range"),
    sa.CheckConstraint("recorded_at >= finished_at", name="recording_time"),
    sa.CheckConstraint(
        "status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT', "
        "'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR')",
        name="status",
    ),
)

SANDBOX_COMMAND_RESULTS = sa.Table(
    "sandbox_command_results",
    OrmBase.metadata,
    sa.Column(
        "run_id",
        sa.Uuid,
        sa.ForeignKey("sandbox_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("command_id", sa.String(128), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("exit_code", sa.Integer, nullable=True),
    sa.Column("output_parser_id", sa.String(128), nullable=True),
    sa.Column("failure_message", sa.Text, nullable=True),
    sa.Column("stdout_log", JSONB, nullable=False),
    sa.Column("stderr_log", JSONB, nullable=False),
    sa.Column("artifacts", JSONB, nullable=False),
    sa.PrimaryKeyConstraint("run_id", "ordinal"),
    sa.UniqueConstraint(
        "run_id",
        "command_id",
        name="uq_sandbox_command_results_run_command",
    ),
    sa.CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
    sa.CheckConstraint("finished_at >= started_at", name="time_range"),
    sa.CheckConstraint(
        "exit_code IS NULL OR exit_code BETWEEN 0 AND 255",
        name="portable_exit_code",
    ),
    sa.CheckConstraint(
        "status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT', "
        "'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR')",
        name="status",
    ),
)


class SandboxRunStoreStatus(StrEnum):
    """Typed owner-safe outcomes of storing one terminal sandbox run."""

    STORED = "STORED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    INTAKE_CONTEXT_NOT_FOUND = "INTAKE_CONTEXT_NOT_FOUND"
    RUN_CONFLICT = "RUN_CONFLICT"


@dataclass(frozen=True, slots=True)
class PersistedSandboxCommandResult:
    """One validated command-result row with raw evidence references."""

    run_id: UUID
    ordinal: int
    command_id: str
    status: SandboxCommandStatus
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    output_parser_id: str | None
    failure_message: str | None
    stdout_log_json: str
    stderr_log_json: str
    artifacts_json: str

    def __post_init__(self) -> None:
        """Protect ordering, time, status shape, and canonical JSON values."""
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("sandbox command ordinal must not be negative")
        if not self.command_id:
            raise ValueError("sandbox command ID is required")
        _validate_time_range(self.started_at, self.finished_at, label="sandbox command")
        stdout = _canonical_json_object(self.stdout_log_json, label="stdout log")
        stderr = _canonical_json_object(self.stderr_log_json, label="stderr log")
        artifacts = _canonical_json_array(self.artifacts_json, label="sandbox artifacts")
        if stdout.get("stream") != "STDOUT" or stderr.get("stream") != "STDERR":
            raise ValueError("sandbox command log stream projections are inconsistent")
        if any(not isinstance(item, Mapping) for item in artifacts):
            raise ValueError("sandbox command artifacts must contain objects")

        if self.status is SandboxCommandStatus.SUCCEEDED:
            if self.exit_code is None or self.failure_message is not None:
                raise ValueError("successful command persistence shape is invalid")
        elif self.status is SandboxCommandStatus.FAILED:
            if self.exit_code is None or self.failure_message is None:
                raise ValueError("failed command persistence shape is invalid")
        elif self.exit_code is not None or self.failure_message is None:
            raise ValueError("non-process command persistence shape is invalid")
        if self.exit_code is not None and not 0 <= self.exit_code <= 255:
            raise ValueError("persisted sandbox exit code must be portable")

    @property
    def stdout_log(self) -> dict[str, object]:
        return _canonical_json_object(self.stdout_log_json, label="stdout log")

    @property
    def stderr_log(self) -> dict[str, object]:
        return _canonical_json_object(self.stderr_log_json, label="stderr log")

    @property
    def artifacts(self) -> tuple[dict[str, object], ...]:
        values = _canonical_json_array(self.artifacts_json, label="sandbox artifacts")
        return tuple(_mapping(value, label="sandbox artifact") for value in values)

    def to_snapshot(self) -> dict[str, object]:
        """Return the exact queryable command-result projection."""
        return {
            "run_id": str(self.run_id),
            "ordinal": self.ordinal,
            "command_id": self.command_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "exit_code": self.exit_code,
            "output_parser_id": self.output_parser_id,
            "failure_message": self.failure_message,
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
            "artifacts": list(self.artifacts),
        }


@dataclass(frozen=True, slots=True)
class PersistedProjectSandboxRun:
    """Validated immutable run envelope plus ordered command-result rows."""

    run_id: UUID
    project_id: UUID
    intake_reference: BrownfieldIntakeReference | None
    schema_version: int
    evidence_content_hash: str
    plan_id: str
    plan_content_hash: str
    profile_id: str
    profile_version: str
    image_reference: str
    runtime_reference: str
    status: SandboxRunStatus
    started_at: datetime
    finished_at: datetime
    failure_message: str | None
    evidence_snapshot_json: str
    created_by_user_id: UUID
    recorded_at: datetime
    command_results: tuple[PersistedSandboxCommandResult, ...]

    def __post_init__(self) -> None:
        """Validate exact envelope identity and every relational projection."""
        if self.schema_version != PROJECT_SANDBOX_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported persisted sandbox run schema")
        validate_sha256(
            self.evidence_content_hash,
            label="persisted sandbox evidence content hash",
        )
        validate_sha256(
            self.plan_content_hash,
            label="persisted sandbox plan content hash",
        )
        _validate_time_range(self.started_at, self.finished_at, label="sandbox run")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("persisted sandbox recording time must be timezone-aware")
        if self.recorded_at < self.finished_at:
            raise ValueError("persisted sandbox run was recorded before completion")
        if self.intake_reference is not None and (
            self.intake_reference.project_id != self.project_id
        ):
            raise ValueError("persisted sandbox intake belongs to another project")

        payload = _canonical_json_object(
            self.evidence_snapshot_json,
            label="sandbox evidence snapshot",
        )
        if snapshot_content_hash(payload) != self.evidence_content_hash:
            raise ValueError("persisted sandbox evidence snapshot hash is inconsistent")
        if payload.get("schema_version") != self.schema_version:
            raise ValueError("persisted sandbox evidence schema is inconsistent")
        if payload.get("project_id") != str(self.project_id):
            raise ValueError("persisted sandbox evidence project is inconsistent")
        if payload.get("owner_user_id") != str(self.created_by_user_id):
            raise ValueError("persisted sandbox evidence owner is inconsistent")
        expected_intake = (
            None if self.intake_reference is None else self.intake_reference.to_snapshot()
        )
        if payload.get("brownfield_intake_reference") != expected_intake:
            raise ValueError("persisted sandbox intake projection is inconsistent")
        if payload.get("recorded_at") != self.recorded_at.isoformat():
            raise ValueError("persisted sandbox recording projection is inconsistent")

        evidence = _mapping(payload.get("evidence"), label="sandbox evidence")
        projections = {
            "run_id": str(self.run_id),
            "plan_id": self.plan_id,
            "plan_content_hash": self.plan_content_hash,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "image_reference": self.image_reference,
            "runtime_reference": self.runtime_reference,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "failure_message": self.failure_message,
        }
        if any(evidence.get(key) != value for key, value in projections.items()):
            raise ValueError("persisted sandbox run projection is inconsistent")

        if self.command_results != tuple(
            sorted(self.command_results, key=lambda result: result.ordinal)
        ):
            raise ValueError("persisted sandbox command results must be ordered")
        if any(result.run_id != self.run_id for result in self.command_results):
            raise ValueError("persisted sandbox command result belongs to another run")
        if tuple(result.ordinal for result in self.command_results) != tuple(
            range(len(self.command_results))
        ):
            raise ValueError("persisted sandbox command ordinals must be contiguous")

        commands = _sequence(evidence.get("command_evidence"), label="command evidence")
        if len(commands) != len(self.command_results):
            raise ValueError("persisted sandbox command projection count is inconsistent")
        for command, result in zip(commands, self.command_results, strict=True):
            command_payload = _mapping(command, label="command evidence")
            if _command_projection(result) != command_payload:
                raise ValueError("persisted sandbox command projection is inconsistent")

    @property
    def evidence_snapshot(self) -> dict[str, object]:
        """Return a fresh JSON-compatible snapshot copy."""
        return _canonical_json_object(
            self.evidence_snapshot_json,
            label="sandbox evidence snapshot",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return persisted metadata and exact run evidence."""
        return {
            "run_id": str(self.run_id),
            "project_id": str(self.project_id),
            "intake_reference": (
                None if self.intake_reference is None else self.intake_reference.to_snapshot()
            ),
            "schema_version": self.schema_version,
            "evidence_content_hash": self.evidence_content_hash,
            "evidence_snapshot": self.evidence_snapshot,
            "created_by_user_id": str(self.created_by_user_id),
            "recorded_at": self.recorded_at.isoformat(),
            "command_results": [result.to_snapshot() for result in self.command_results],
        }


@dataclass(frozen=True, slots=True)
class SandboxRunStoreResult:
    """One expected persistence outcome without authorization leakage."""

    status: SandboxRunStoreStatus
    run: PersistedProjectSandboxRun | None

    def __post_init__(self) -> None:
        successful = self.status in {
            SandboxRunStoreStatus.STORED,
            SandboxRunStoreStatus.ALREADY_PRESENT,
        }
        if successful != (self.run is not None):
            raise ValueError("sandbox run store result shape is inconsistent")


class SandboxRunRepository(Protocol):
    """Owner-scoped append-only sandbox evidence repository."""

    async def get(self, *, run_id: UUID) -> PersistedProjectSandboxRun | None: ...

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]: ...

    async def store(self, run: ProjectSandboxRunEvidence) -> SandboxRunStoreResult: ...


class SandboxRunUnitOfWork(Protocol):
    """Transactional boundary for one sandbox evidence write."""

    runs: SandboxRunRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SandboxRunUnitOfWorkFactory(Protocol):
    """Create one owner-scoped sandbox evidence transaction."""

    def __call__(self, *, owner_user_id: UUID) -> SandboxRunUnitOfWork: ...


class SqlAlchemySandboxRunRepository:
    """PostgreSQL-backed owner-scoped sandbox run repository."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def get(self, *, run_id: UUID) -> PersistedProjectSandboxRun | None:
        row = (
            (
                await self._session.execute(
                    _owned_run_select(owner_user_id=self._owner_user_id).where(
                        SANDBOX_RUNS.c.run_id == run_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        commands = await self._command_records(run_id)
        return persisted_project_sandbox_run_from_records(row, commands)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]:
        rows = (
            (
                await self._session.execute(
                    _owned_run_select(owner_user_id=self._owner_user_id)
                    .where(SANDBOX_RUNS.c.project_id == project_id)
                    .order_by(SANDBOX_RUNS.c.recorded_at.asc(), SANDBOX_RUNS.c.run_id.asc())
                )
            )
            .mappings()
            .all()
        )
        results: list[PersistedProjectSandboxRun] = []
        for row in rows:
            run_id = _uuid(row.get("run_id"), label="sandbox run ID")
            results.append(
                persisted_project_sandbox_run_from_records(
                    row,
                    await self._command_records(run_id),
                )
            )
        return tuple(results)

    async def store(self, run: ProjectSandboxRunEvidence) -> SandboxRunStoreResult:
        if run.owner_user_id != self._owner_user_id:
            return SandboxRunStoreResult(SandboxRunStoreStatus.PROJECT_NOT_FOUND, None)
        project_exists = await self._owned_project_exists(run.project_id)
        if not project_exists:
            return SandboxRunStoreResult(SandboxRunStoreStatus.PROJECT_NOT_FOUND, None)
        if run.brownfield_intake_reference is not None and not await self._intake_exists(
            run.brownfield_intake_reference
        ):
            return SandboxRunStoreResult(
                SandboxRunStoreStatus.INTAKE_CONTEXT_NOT_FOUND,
                None,
            )

        existing = await self.get(run_id=run.run_id)
        if existing is not None:
            status = (
                SandboxRunStoreStatus.ALREADY_PRESENT
                if existing.evidence_content_hash == run.content_hash
                else SandboxRunStoreStatus.RUN_CONFLICT
            )
            return SandboxRunStoreResult(
                status,
                existing if status is SandboxRunStoreStatus.ALREADY_PRESENT else None,
            )

        run_record, command_records = project_sandbox_run_to_records(run)
        try:
            await self._session.execute(sa.insert(SANDBOX_RUNS).values(**run_record))
            if command_records:
                await self._session.execute(
                    sa.insert(SANDBOX_COMMAND_RESULTS),
                    list(command_records),
                )
        except IntegrityError:
            return SandboxRunStoreResult(SandboxRunStoreStatus.RUN_CONFLICT, None)
        return SandboxRunStoreResult(
            SandboxRunStoreStatus.STORED,
            persisted_project_sandbox_run_from_records(run_record, command_records),
        )

    async def _owned_project_exists(self, project_id: UUID) -> bool:
        projects = _projects_table()
        value = await self._session.scalar(
            sa.select(projects.c.id).where(
                projects.c.id == project_id,
                projects.c.owner_user_id == self._owner_user_id,
                projects.c.archived_at.is_(None),
            )
        )
        return value is not None

    async def _intake_exists(self, reference: BrownfieldIntakeReference) -> bool:
        value = await self._session.scalar(
            sa.select(BROWNFIELD_INTAKE_VERSIONS.c.id).where(
                BROWNFIELD_INTAKE_VERSIONS.c.id == reference.intake_id,
                BROWNFIELD_INTAKE_VERSIONS.c.project_id == reference.project_id,
                BROWNFIELD_INTAKE_VERSIONS.c.version_number == reference.version_number,
                BROWNFIELD_INTAKE_VERSIONS.c.content_hash == reference.content_hash,
                BROWNFIELD_INTAKE_VERSIONS.c.created_by_user_id == self._owner_user_id,
            )
        )
        return value is not None

    async def _command_records(self, run_id: UUID) -> tuple[Mapping[str, object], ...]:
        rows = (
            (
                await self._session.execute(
                    sa.select(SANDBOX_COMMAND_RESULTS)
                    .where(SANDBOX_COMMAND_RESULTS.c.run_id == run_id)
                    .order_by(SANDBOX_COMMAND_RESULTS.c.ordinal.asc())
                )
            )
            .mappings()
            .all()
        )
        return tuple(rows)


class SqlAlchemySandboxRunUnitOfWork:
    """Async SQLAlchemy transaction for owner-scoped sandbox runs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._owner_user_id = owner_user_id
        self._session: AsyncSession | None = None
        self._completed = False
        self.runs: SandboxRunRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._completed = False
        self.runs = SqlAlchemySandboxRunRepository(
            self._session,
            owner_user_id=self._owner_user_id,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if self._session is None:
            return
        try:
            if not self._completed:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("sandbox run unit of work is not open")
        await self._session.commit()
        self._completed = True

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("sandbox run unit of work is not open")
        await self._session.rollback()
        self._completed = True


class SqlAlchemySandboxRunUnitOfWorkFactory:
    """Create PostgreSQL sandbox-run units of work."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(self, *, owner_user_id: UUID) -> SqlAlchemySandboxRunUnitOfWork:
        return SqlAlchemySandboxRunUnitOfWork(
            self._session_factory,
            owner_user_id=owner_user_id,
        )


class InMemorySandboxRunRepository:
    """Deterministic owner-scoped repository for application and workflow tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        projects: Mapping[UUID, Project],
        intake_references: tuple[BrownfieldIntakeReference, ...] = (),
    ) -> None:
        self._owner_user_id = owner_user_id
        self._projects = dict(projects)
        self._intake_references = frozenset(intake_references)
        self._runs: dict[UUID, PersistedProjectSandboxRun] = {}

    async def get(self, *, run_id: UUID) -> PersistedProjectSandboxRun | None:
        run = self._runs.get(run_id)
        if run is None or not self._is_owned(run.project_id):
            return None
        return run

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]:
        if not self._is_owned(project_id):
            return ()
        return tuple(
            sorted(
                (run for run in self._runs.values() if run.project_id == project_id),
                key=lambda run: (run.recorded_at, run.run_id.hex),
            )
        )

    async def store(self, run: ProjectSandboxRunEvidence) -> SandboxRunStoreResult:
        if run.owner_user_id != self._owner_user_id or not self._is_owned(run.project_id):
            return SandboxRunStoreResult(SandboxRunStoreStatus.PROJECT_NOT_FOUND, None)
        if (
            run.brownfield_intake_reference is not None
            and run.brownfield_intake_reference not in self._intake_references
        ):
            return SandboxRunStoreResult(
                SandboxRunStoreStatus.INTAKE_CONTEXT_NOT_FOUND,
                None,
            )
        existing = self._runs.get(run.run_id)
        if existing is not None:
            if existing.evidence_content_hash == run.content_hash:
                return SandboxRunStoreResult(
                    SandboxRunStoreStatus.ALREADY_PRESENT,
                    existing,
                )
            return SandboxRunStoreResult(SandboxRunStoreStatus.RUN_CONFLICT, None)

        run_record, command_records = project_sandbox_run_to_records(run)
        persisted = persisted_project_sandbox_run_from_records(
            run_record,
            command_records,
        )
        self._runs[run.run_id] = persisted
        return SandboxRunStoreResult(SandboxRunStoreStatus.STORED, persisted)

    def _is_owned(self, project_id: UUID) -> bool:
        project = self._projects.get(project_id)
        return (
            project is not None
            and project.owner_user_id == self._owner_user_id
            and project.archived_at is None
        )


def project_sandbox_run_to_records(
    run: ProjectSandboxRunEvidence,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Convert one validated run envelope into relational persistence values."""
    intake = run.brownfield_intake_reference
    evidence = run.evidence
    run_record: dict[str, object] = {
        "run_id": run.run_id,
        "project_id": run.project_id,
        "intake_id": None if intake is None else intake.intake_id,
        "intake_version_number": None if intake is None else intake.version_number,
        "intake_content_hash": None if intake is None else intake.content_hash,
        "schema_version": run.schema_version,
        "evidence_content_hash": run.content_hash,
        "plan_id": evidence.plan_id,
        "plan_content_hash": evidence.plan_content_hash,
        "profile_id": evidence.profile_id,
        "profile_version": evidence.profile_version,
        "image_reference": evidence.image_reference,
        "runtime_reference": evidence.runtime_reference,
        "status": evidence.status.value,
        "started_at": evidence.started_at,
        "finished_at": evidence.finished_at,
        "failure_message": evidence.failure_message,
        "evidence_snapshot": run.to_snapshot(),
        "created_by_user_id": run.owner_user_id,
        "recorded_at": run.recorded_at,
    }
    command_records = tuple(
        {
            "run_id": run.run_id,
            "ordinal": ordinal,
            "command_id": command.command_id,
            "status": command.status.value,
            "started_at": command.started_at,
            "finished_at": command.finished_at,
            "exit_code": command.exit_code,
            "output_parser_id": command.output_parser_id,
            "failure_message": command.failure_message,
            "stdout_log": command.stdout_log.to_snapshot(),
            "stderr_log": command.stderr_log.to_snapshot(),
            "artifacts": [artifact.to_snapshot() for artifact in command.artifacts],
        }
        for ordinal, command in enumerate(evidence.command_evidence)
    )
    return run_record, command_records


def persisted_project_sandbox_run_from_domain(
    run: ProjectSandboxRunEvidence,
) -> PersistedProjectSandboxRun:
    """Project a validated domain envelope into its persistence view."""
    run_record, command_records = project_sandbox_run_to_records(run)
    return persisted_project_sandbox_run_from_records(run_record, command_records)


def persisted_project_sandbox_run_from_records(
    run_record: Mapping[str, object],
    command_records: tuple[Mapping[str, object], ...],
) -> PersistedProjectSandboxRun:
    """Validate database rows before exposing immutable sandbox evidence."""
    intake_id = _optional_uuid(run_record.get("intake_id"))
    intake_version = _optional_integer(run_record.get("intake_version_number"))
    intake_hash = _optional_string(run_record.get("intake_content_hash"))
    intake_values = (intake_id, intake_version, intake_hash)
    project_id = _uuid(run_record.get("project_id"), label="sandbox project ID")
    if all(value is None for value in intake_values):
        intake = None
    elif all(value is not None for value in intake_values):
        intake = BrownfieldIntakeReference(
            intake_id=cast(UUID, intake_id),
            project_id=project_id,
            version_number=cast(int, intake_version),
            content_hash=cast(str, intake_hash),
        )
    else:
        raise ValueError("persisted sandbox intake metadata must be all-null or complete")

    command_results = tuple(
        persisted_sandbox_command_result_from_record(record) for record in command_records
    )
    snapshot = _mapping(
        run_record.get("evidence_snapshot"),
        label="sandbox evidence snapshot",
    )
    return PersistedProjectSandboxRun(
        run_id=_uuid(run_record.get("run_id"), label="sandbox run ID"),
        project_id=project_id,
        intake_reference=intake,
        schema_version=_integer(
            run_record.get("schema_version"),
            label="sandbox run schema version",
        ),
        evidence_content_hash=_string(
            run_record.get("evidence_content_hash"),
            label="sandbox evidence content hash",
        ),
        plan_id=_string(run_record.get("plan_id"), label="sandbox plan ID"),
        plan_content_hash=_string(
            run_record.get("plan_content_hash"),
            label="sandbox plan content hash",
        ),
        profile_id=_string(run_record.get("profile_id"), label="sandbox profile ID"),
        profile_version=_string(
            run_record.get("profile_version"),
            label="sandbox profile version",
        ),
        image_reference=_string(
            run_record.get("image_reference"),
            label="sandbox image reference",
        ),
        runtime_reference=_string(
            run_record.get("runtime_reference"),
            label="sandbox runtime reference",
        ),
        status=SandboxRunStatus(_string(run_record.get("status"), label="sandbox run status")),
        started_at=_datetime(run_record.get("started_at"), label="sandbox start time"),
        finished_at=_datetime(run_record.get("finished_at"), label="sandbox finish time"),
        failure_message=_optional_string(run_record.get("failure_message")),
        evidence_snapshot_json=canonical_json(snapshot),
        created_by_user_id=_uuid(
            run_record.get("created_by_user_id"),
            label="sandbox run creator",
        ),
        recorded_at=_datetime(
            run_record.get("recorded_at"),
            label="sandbox recording time",
        ),
        command_results=command_results,
    )


def persisted_sandbox_command_result_from_record(
    record: Mapping[str, object],
) -> PersistedSandboxCommandResult:
    """Validate one command-result database row."""
    stdout = _mapping(record.get("stdout_log"), label="stdout log")
    stderr = _mapping(record.get("stderr_log"), label="stderr log")
    artifacts = _sequence(record.get("artifacts"), label="sandbox artifacts")
    return PersistedSandboxCommandResult(
        run_id=_uuid(record.get("run_id"), label="sandbox command run ID"),
        ordinal=_integer(record.get("ordinal"), label="sandbox command ordinal"),
        command_id=_string(record.get("command_id"), label="sandbox command ID"),
        status=SandboxCommandStatus(_string(record.get("status"), label="sandbox command status")),
        started_at=_datetime(record.get("started_at"), label="sandbox command start"),
        finished_at=_datetime(record.get("finished_at"), label="sandbox command finish"),
        exit_code=_optional_integer(record.get("exit_code")),
        output_parser_id=_optional_string(record.get("output_parser_id")),
        failure_message=_optional_string(record.get("failure_message")),
        stdout_log_json=canonical_json(stdout),
        stderr_log_json=canonical_json(stderr),
        artifacts_json=json.dumps(
            artifacts,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _owned_run_select(*, owner_user_id: UUID) -> sa.Select[tuple[object, ...]]:
    projects = _projects_table()
    return (
        sa.select(SANDBOX_RUNS)
        .select_from(SANDBOX_RUNS.join(projects, projects.c.id == SANDBOX_RUNS.c.project_id))
        .where(
            projects.c.owner_user_id == owner_user_id,
            projects.c.archived_at.is_(None),
        )
    )


def _projects_table() -> sa.TableClause:
    return sa.table(
        "projects",
        sa.column("id"),
        sa.column("owner_user_id"),
        sa.column("archived_at"),
    )


def _command_projection(result: PersistedSandboxCommandResult) -> dict[str, object]:
    return {
        "command_id": result.command_id,
        "status": result.status.value,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "duration_seconds": (result.finished_at - result.started_at).total_seconds(),
        "exit_code": result.exit_code,
        "stdout_log": result.stdout_log,
        "stderr_log": result.stderr_log,
        "artifacts": list(result.artifacts),
        "output_parser_id": result.output_parser_id,
        "failure_message": result.failure_message,
    }


def _canonical_json_object(value: str, *, label: str) -> dict[str, object]:
    parsed = _canonical_json_value(value, label=label)
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ValueError(f"{label} must be a JSON object")
    return cast(dict[str, object], parsed)


def _canonical_json_array(value: str, *, label: str) -> tuple[object, ...]:
    parsed = _canonical_json_value(value, label=label)
    if not isinstance(parsed, list):
        raise ValueError(f"{label} must be a JSON array")
    return tuple(parsed)


def _canonical_json_value(value: str, *, label: str) -> object:
    if not isinstance(value, str):
        raise TypeError(f"{label} JSON must be text")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} JSON is invalid") from error
    canonical = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if canonical != value:
        raise ValueError(f"{label} JSON must be canonical")
    return parsed


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, *, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return tuple(value)


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a UUID") from error
    raise TypeError(f"{label} must be a UUID")


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    return _uuid(value, label="optional UUID")


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    return _integer(value, label="optional integer")


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value, label="optional text")


def _datetime(value: object, *, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    return value


def _validate_time_range(started_at: datetime, finished_at: datetime, *, label: str) -> None:
    if (
        started_at.tzinfo is None
        or started_at.utcoffset() is None
        or finished_at.tzinfo is None
        or finished_at.utcoffset() is None
    ):
        raise ValueError(f"{label} timestamps must be timezone-aware")
    if finished_at < started_at:
        raise ValueError(f"{label} finish must not precede start")
