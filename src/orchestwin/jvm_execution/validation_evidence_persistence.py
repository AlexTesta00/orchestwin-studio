"""Append-only PostgreSQL storage for platform JVM profile validation evidence.

Every observed failure and stale scope remains readable. Storage grants no
capability: the separate domain catalog evaluates each exact profile version.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.jvm_execution.validation_evidence import (
    JvmProfileValidationEvidence,
    JvmProfileValidationEvidenceCatalog,
    JvmProfileValidationEvidenceKind,
)
from orchestwin.persistence.orm import OrmBase

_PRIMARY_KEY = "pk_jvm_profile_validation_evidence"
JVM_PROFILE_VALIDATION_EVIDENCE = sa.Table(
    "jvm_profile_validation_evidence",
    OrmBase.metadata,
    sa.Column("evidence_id", sa.Text, nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("profile_id", sa.Text, nullable=False),
    sa.Column("profile_version", sa.String(64), nullable=False),
    sa.Column("baseline_scope_hash", sa.String(64), nullable=False),
    sa.Column("runner_image_digest", sa.String(64), nullable=False),
    sa.Column("runner_build_recipe_hash", sa.String(64), nullable=False),
    sa.Column("toolchain_manifest_hash", sa.String(64), nullable=False),
    sa.Column("fixture_bundle_hash", sa.String(64), nullable=False),
    sa.Column("environment_fingerprint", sa.String(64), nullable=False),
    sa.Column("artifact_content_hash", sa.String(64), nullable=False),
    sa.Column("reference", sa.Text, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("passed", sa.Boolean, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("evidence_snapshot", JSONB, nullable=False),
    sa.PrimaryKeyConstraint("evidence_id", name=_PRIMARY_KEY),
    sa.Index("ix_jvm_profile_validation_evidence_profile_version", "profile_id", "profile_version"),
)

_SNAPSHOT_FIELDS = frozenset(
    {
        "evidence_id",
        "kind",
        "profile_id",
        "profile_version",
        "baseline_scope_hash",
        "runner_image_digest",
        "runner_build_recipe_hash",
        "toolchain_manifest_hash",
        "fixture_bundle_hash",
        "environment_fingerprint",
        "artifact_content_hash",
        "reference",
        "recorded_at",
        "passed",
    }
)


class JvmValidationEvidenceAppendStatus(StrEnum):
    """An evidence ID can be reused only for the identical immutable record."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"


class JvmValidationEvidenceRepository(Protocol):
    """Platform-scoped storage without manufactured project ownership."""

    async def get(self, *, evidence_id: str) -> JvmProfileValidationEvidence | None: ...

    async def history(self) -> tuple[JvmProfileValidationEvidence, ...]: ...

    async def append(
        self, evidence: JvmProfileValidationEvidence
    ) -> JvmValidationEvidenceAppendStatus: ...


def jvm_validation_evidence_to_record(evidence: JvmProfileValidationEvidence) -> dict[str, object]:
    """Store a UTC relational instant without changing the hashed original offset."""
    snapshot = evidence.to_snapshot()
    return {
        **snapshot,
        "recorded_at": evidence.recorded_at.astimezone(UTC),
        "content_hash": evidence.content_hash,
        "evidence_snapshot": snapshot,
    }


def jvm_validation_evidence_from_record(
    record: Mapping[str, object],
) -> JvmProfileValidationEvidence:
    """Hydrate strictly and verify every projection against the complete snapshot."""
    if not isinstance(record, Mapping) or set(record) != _SNAPSHOT_FIELDS | {
        "content_hash",
        "evidence_snapshot",
    }:
        raise ValueError("persisted JVM validation evidence columns are inconsistent")
    snapshot = record["evidence_snapshot"]
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_FIELDS:
        raise ValueError("persisted JVM validation evidence snapshot fields are inconsistent")
    passed = snapshot["passed"]
    if type(passed) is not bool:
        raise ValueError("persisted JVM validation evidence passed must be a boolean")
    evidence = JvmProfileValidationEvidence(
        evidence_id=_text(snapshot["evidence_id"]),
        kind=JvmProfileValidationEvidenceKind(_text(snapshot["kind"])),
        profile_id=_text(snapshot["profile_id"]),
        profile_version=_text(snapshot["profile_version"]),
        baseline_scope_hash=_text(snapshot["baseline_scope_hash"]),
        runner_image_digest=_text(snapshot["runner_image_digest"]),
        runner_build_recipe_hash=_text(snapshot["runner_build_recipe_hash"]),
        toolchain_manifest_hash=_text(snapshot["toolchain_manifest_hash"]),
        fixture_bundle_hash=_text(snapshot["fixture_bundle_hash"]),
        environment_fingerprint=_text(snapshot["environment_fingerprint"]),
        artifact_content_hash=_text(snapshot["artifact_content_hash"]),
        reference=_text(snapshot["reference"]),
        recorded_at=datetime.fromisoformat(_text(snapshot["recorded_at"])),
        passed=passed,
    )
    expected = jvm_validation_evidence_to_record(evidence)
    # Python equality alone treats True and 1 as equal; canonical JSON does not.
    if _canonical_json(snapshot) != _canonical_json(expected["evidence_snapshot"]):
        raise ValueError("persisted JVM validation evidence snapshot is not canonical")
    for key, value in expected.items():
        actual = record[key]
        if key == "recorded_at":
            if (
                not isinstance(actual, datetime)
                or actual.tzinfo is None
                or actual.utcoffset() is None
                or actual != value
            ):
                raise ValueError("persisted JVM validation evidence recorded_at is inconsistent")
        elif key == "evidence_snapshot":
            if _canonical_json(actual) != _canonical_json(value):
                raise ValueError("persisted JVM validation evidence snapshot is inconsistent")
        elif type(actual) is not type(value) or actual != value:
            raise ValueError(f"persisted JVM validation evidence {key} is inconsistent")
    return evidence


def canonical_jvm_validation_evidence(
    records: tuple[JvmProfileValidationEvidence, ...],
) -> tuple[JvmProfileValidationEvidence, ...]:
    """Use domain ordering independently of PostgreSQL collation; retain every row."""
    ordered = tuple(
        sorted(
            records,
            key=lambda record: (
                record.profile_id,
                record.profile_version,
                record.kind.value,
                record.evidence_id,
            ),
        )
    )
    return JvmProfileValidationEvidenceCatalog(ordered).records


class SqlAlchemyJvmValidationEvidenceRepository:
    """Verified reads and savepoint-isolated races on an immutable evidence ID."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, evidence_id: str) -> JvmProfileValidationEvidence | None:
        statement = sa.select(JVM_PROFILE_VALIDATION_EVIDENCE).where(
            JVM_PROFILE_VALIDATION_EVIDENCE.c.evidence_id == evidence_id
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else jvm_validation_evidence_from_record(row)

    async def history(self) -> tuple[JvmProfileValidationEvidence, ...]:
        rows = (await self._session.execute(sa.select(JVM_PROFILE_VALIDATION_EVIDENCE))).mappings()
        return canonical_jvm_validation_evidence(
            tuple(jvm_validation_evidence_from_record(row) for row in rows)
        )

    async def append(
        self, evidence: JvmProfileValidationEvidence
    ) -> JvmValidationEvidenceAppendStatus:
        values = jvm_validation_evidence_to_record(evidence)
        # Also reject objects constructed by bypassing their frozen domain constructor.
        jvm_validation_evidence_from_record(values)
        existing = await self.get(evidence_id=evidence.evidence_id)
        if existing is not None:
            return _existing_status(existing, evidence)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    sa.insert(JVM_PROFILE_VALIDATION_EVIDENCE).values(values)
                )
        except IntegrityError as error:
            if not _is_evidence_id_conflict(error):
                raise
            existing = await self.get(evidence_id=evidence.evidence_id)
            if existing is None:
                raise
            return _existing_status(existing, evidence)
        return JvmValidationEvidenceAppendStatus.APPENDED


class JvmValidationEvidenceUnitOfWork(Protocol):
    """Explicit transactional boundary for platform validation evidence."""

    evidence: JvmValidationEvidenceRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyJvmValidationEvidenceUnitOfWork:
    """Explicit commit; closing an uncommitted context rolls back its transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.evidence: JvmValidationEvidenceRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.evidence = SqlAlchemyJvmValidationEvidenceRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            try:
                await self._session.rollback()
            finally:
                await self._session.close()
                self._session = None

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("JVM validation evidence unit of work is not open")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("JVM validation evidence unit of work is not open")
        await self._session.rollback()


def _existing_status(
    existing: JvmProfileValidationEvidence, candidate: JvmProfileValidationEvidence
) -> JvmValidationEvidenceAppendStatus:
    return (
        JvmValidationEvidenceAppendStatus.ALREADY_PRESENT
        if existing.content_hash == candidate.content_hash
        and existing.to_snapshot() == candidate.to_snapshot()
        else JvmValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
    )


def _is_evidence_id_conflict(error: IntegrityError) -> bool:
    original = error.orig
    state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    diagnostic = getattr(original, "diag", None)
    return state == "23505" and getattr(diagnostic, "constraint_name", None) == _PRIMARY_KEY


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("persisted JVM validation evidence text must be a string")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise ValueError("persisted JVM validation evidence must be canonical JSON") from error
