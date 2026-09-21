"""Append-only PostgreSQL storage for platform Web profile validation evidence.

Storage preserves observed failures and stale scopes. It neither executes projects
nor grants profile capability; promotion remains a separate domain decision.
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

from orchestwin.persistence.orm import OrmBase
from orchestwin.web_execution.targets import WebImplementationLanguage, WebLanguageConfiguration
from orchestwin.web_execution.validation_evidence import (
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceCatalog,
    WebProfileValidationEvidenceKind,
)

WEB_PROFILE_VALIDATION_EVIDENCE = sa.Table(
    "web_profile_validation_evidence",
    OrmBase.metadata,
    sa.Column("evidence_id", sa.Text, primary_key=True),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("profile_id", sa.Text, nullable=False),
    sa.Column("profile_version", sa.String(64), nullable=False),
    sa.Column("baseline_scope_hash", sa.String(64), nullable=False),
    sa.Column("language_configuration", JSONB(none_as_null=True), nullable=True),
    sa.Column("execution_runner_image_digest", sa.String(64), nullable=False),
    sa.Column("browser_runner_image_digest", sa.String(64), nullable=True),
    sa.Column("artifact_content_hash", sa.String(64), nullable=False),
    sa.Column("reference", sa.Text, nullable=False),
    sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("passed", sa.Boolean, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("evidence_snapshot", JSONB, nullable=False),
    sa.Index("ix_web_profile_validation_evidence_profile_version", "profile_id", "profile_version"),
)

_SNAPSHOT_FIELDS = frozenset(
    {
        "evidence_id",
        "kind",
        "profile_id",
        "profile_version",
        "baseline_scope_hash",
        "language_configuration",
        "execution_runner_image_digest",
        "browser_runner_image_digest",
        "artifact_content_hash",
        "reference",
        "recorded_at",
        "passed",
    }
)


class WebValidationEvidenceAppendStatus(StrEnum):
    """An existing evidence ID can only be reused for identical content."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"


class WebValidationEvidenceRepository(Protocol):
    """Platform-scoped evidence port; no project ownership is manufactured."""

    async def get(self, *, evidence_id: str) -> WebProfileValidationEvidence | None: ...

    async def history(self) -> tuple[WebProfileValidationEvidence, ...]: ...

    async def append(
        self, evidence: WebProfileValidationEvidence
    ) -> WebValidationEvidenceAppendStatus: ...


def web_validation_evidence_to_record(evidence: WebProfileValidationEvidence) -> dict[str, object]:
    """Keep the original timestamp representation in the hashed snapshot."""
    snapshot = evidence.to_snapshot()
    return {
        **snapshot,
        "recorded_at": evidence.recorded_at.astimezone(UTC),
        "content_hash": evidence.content_hash,
        "evidence_snapshot": snapshot,
    }


def web_validation_evidence_from_record(
    record: Mapping[str, object],
) -> WebProfileValidationEvidence:
    """Reconstruct strictly, then verify every projection and the exact content hash."""
    if set(record) != _SNAPSHOT_FIELDS | {"content_hash", "evidence_snapshot"}:
        raise ValueError("persisted Web validation evidence columns are inconsistent")
    snapshot = _exact_mapping(record["evidence_snapshot"], fields=_SNAPSHOT_FIELDS)
    configuration = snapshot["language_configuration"]
    language = None
    if configuration is not None:
        values = _exact_mapping(configuration, fields=frozenset({"frontend", "backend"}))
        language = WebLanguageConfiguration(
            frontend=_language(values["frontend"]), backend=_language(values["backend"])
        )
    passed = snapshot["passed"]
    if type(passed) is not bool:
        raise ValueError("persisted Web validation evidence passed must be a boolean")
    evidence = WebProfileValidationEvidence(
        evidence_id=_text(snapshot["evidence_id"]),
        kind=WebProfileValidationEvidenceKind(_text(snapshot["kind"])),
        profile_id=_text(snapshot["profile_id"]),
        profile_version=_text(snapshot["profile_version"]),
        baseline_scope_hash=_text(snapshot["baseline_scope_hash"]),
        language_configuration=language,
        execution_runner_image_digest=_text(snapshot["execution_runner_image_digest"]),
        browser_runner_image_digest=(
            None
            if snapshot["browser_runner_image_digest"] is None
            else _text(snapshot["browser_runner_image_digest"])
        ),
        artifact_content_hash=_text(snapshot["artifact_content_hash"]),
        reference=_text(snapshot["reference"]),
        recorded_at=datetime.fromisoformat(_text(snapshot["recorded_at"])),
        passed=passed,
    )
    expected = web_validation_evidence_to_record(evidence)
    # JSON equality in Python alone accepts True == 1; compare canonical bytes too.
    if _canonical_json(snapshot) != _canonical_json(expected["evidence_snapshot"]):
        raise ValueError("persisted Web validation evidence snapshot is not canonical")
    for key, value in expected.items():
        actual = record[key]
        if key == "recorded_at":
            if (
                not isinstance(actual, datetime)
                or actual.tzinfo is None
                or actual.utcoffset() is None
                or actual != value
            ):
                raise ValueError("persisted Web validation evidence recorded_at is inconsistent")
        elif key in {"evidence_snapshot", "language_configuration"}:
            if _canonical_json(actual) != _canonical_json(value):
                raise ValueError(f"persisted Web validation evidence {key} is inconsistent")
        elif type(actual) is not type(value) or actual != value:
            raise ValueError(f"persisted Web validation evidence {key} is inconsistent")
    return evidence


def canonical_web_validation_evidence(
    records: tuple[WebProfileValidationEvidence, ...],
) -> tuple[WebProfileValidationEvidence, ...]:
    """Order in Python so database collation cannot change catalog identity."""

    def key(record: WebProfileValidationEvidence) -> tuple[str, ...]:
        language = record.language_configuration
        configuration = (
            ""
            if language is None
            else (
                f"{'NONE' if language.frontend is None else language.frontend.value}+"
                f"{'NONE' if language.backend is None else language.backend.value}"
            )
        )
        return (
            record.profile_id,
            record.profile_version,
            record.kind.value,
            configuration,
            record.evidence_id,
        )

    ordered = tuple(sorted(records, key=key))
    return WebProfileValidationEvidenceCatalog(ordered).records


class SqlAlchemyWebValidationEvidenceRepository:
    """Verify all reads and isolate duplicate insert races in a savepoint."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, *, evidence_id: str) -> WebProfileValidationEvidence | None:
        statement = sa.select(WEB_PROFILE_VALIDATION_EVIDENCE).where(
            WEB_PROFILE_VALIDATION_EVIDENCE.c.evidence_id == evidence_id
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_validation_evidence_from_record(row)

    async def history(self) -> tuple[WebProfileValidationEvidence, ...]:
        rows = (await self._session.execute(sa.select(WEB_PROFILE_VALIDATION_EVIDENCE))).mappings()
        return canonical_web_validation_evidence(
            tuple(web_validation_evidence_from_record(row) for row in rows)
        )

    async def append(
        self, evidence: WebProfileValidationEvidence
    ) -> WebValidationEvidenceAppendStatus:
        values = web_validation_evidence_to_record(evidence)
        # Frozen domain objects may still have been constructed outside the normal constructor.
        web_validation_evidence_from_record(values)
        existing = await self.get(evidence_id=evidence.evidence_id)
        if existing is not None:
            return _existing_status(existing, evidence)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(values)
                )
        except IntegrityError:
            existing = await self.get(evidence_id=evidence.evidence_id)
            if existing is None:
                raise
            return _existing_status(existing, evidence)
        return WebValidationEvidenceAppendStatus.APPENDED


class WebValidationEvidenceUnitOfWork(Protocol):
    """Explicit transactional boundary for a batch of validation evidence."""

    evidence: WebValidationEvidenceRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyWebValidationEvidenceUnitOfWork:
    """Explicit commit; an uncommitted context closes with rollback."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.evidence: WebValidationEvidenceRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.evidence = SqlAlchemyWebValidationEvidenceRepository(self._session)
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
            raise RuntimeError("Web validation evidence unit of work is not open")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Web validation evidence unit of work is not open")
        await self._session.rollback()


def _existing_status(
    existing: WebProfileValidationEvidence, candidate: WebProfileValidationEvidence
) -> WebValidationEvidenceAppendStatus:
    return (
        WebValidationEvidenceAppendStatus.ALREADY_PRESENT
        if existing.content_hash == candidate.content_hash
        and existing.to_snapshot() == candidate.to_snapshot()
        else WebValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("persisted Web validation evidence text must be a string")
    return value


def _language(value: object) -> WebImplementationLanguage | None:
    return None if value is None else WebImplementationLanguage(_text(value))


def _exact_mapping(value: object, *, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("persisted Web validation evidence snapshot fields are inconsistent")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise ValueError("persisted Web validation evidence must be canonical JSON") from error
