"""Read persisted Web execution attempts without configuring an executor.

Empty history is not successful execution. Hydration uses the existing hash
and projection validators; raw JSON rows are never returned as trusted evidence.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.sandbox.evidence import SandboxArtifactReference
from orchestwin.web_execution.phase_browser_evidence import _validate_job, decode_browser_evidence
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import WebEvidenceReference, WebPhaseResultStatus
from orchestwin.web_execution.verified_browser_runner import read_json, read_regular

_REFERENCE_KEYS = {"storage_key", "sha256_digest", "size_bytes", "media_type"}
_MAX_OBJECT_BYTES = 32 * 1024 * 1024


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("WEB_EXECUTION_EVIDENCE_INTEGRITY_FAILED")


class _ReadOnlyBrowserEvidenceStore:
    """Recompute decoder references only when those exact bytes already exist."""

    def __init__(self, root: Path, references: tuple[WebEvidenceReference, ...]):
        _require(len(references) <= 128)
        self.root = root
        self.references = frozenset(references)
        self.content: dict[str, bytes] = {}

    def read_reference(self, value, *, media_type=None) -> bytes:
        if isinstance(value, dict):
            _require(set(value) == _REFERENCE_KEYS)
            value = WebEvidenceReference(**value)
        _require(isinstance(value, WebEvidenceReference) and value in self.references)
        digest = value.sha256_digest
        _require(
            value.storage_key == f"sha256/{digest[:2]}/{digest}"
            and type(value.size_bytes) is int
            and 0 <= value.size_bytes <= _MAX_OBJECT_BYTES
            and value.media_type in {"application/json", "text/plain", "text/html", "image/png"}
            and (media_type is None or value.media_type == media_type)
        )
        if value.storage_key not in self.content:
            data = read_regular(self.root / value.storage_key, _MAX_OBJECT_BYTES)
            _require(hashlib.sha256(data).hexdigest() == digest)
            _require(sum(map(len, self.content.values())) + len(data) <= 96 * 1024 * 1024)
            self.content[value.storage_key] = data
        data = self.content[value.storage_key]
        _require(len(data) == value.size_bytes)
        return data

    def store_artifact(self, *, run_id, command_id, normalized_path, content, media_type):
        # The decoder's port is intentionally implemented without a filesystem
        # writer. Missing derived objects are corruption, never created on GET.
        digest = hashlib.sha256(content).hexdigest()
        reference = WebEvidenceReference(
            f"sha256/{digest[:2]}/{digest}", digest, len(content), media_type
        )
        _require(self.read_reference(reference) == content)
        return SandboxArtifactReference(
            normalized_path, digest, len(content), reference.storage_key, media_type
        )

    def verify_nested(self, value) -> None:
        if isinstance(value, dict):
            if "storage_key" in value:
                self.read_reference(value)
            else:
                for item in value.values():
                    self.verify_nested(item)
        elif isinstance(value, list):
            for item in value:
                self.verify_nested(item)


def _verify_browser_manifest(manifest, *, attempt, phase, store):
    _require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1)
    _require(
        manifest["execution_attempt_id"] == str(attempt.id)
        and manifest["source_revision_content_hash"] == attempt.source_revision.content_hash
        and manifest["source_tree_hash"] == attempt.source_revision.source_tree_hash
        and manifest["status"] == phase.status.value
        and manifest["failure_code"] == phase.failure_code
        and datetime.fromisoformat(manifest["started_at"]) == phase.started_at
        and datetime.fromisoformat(manifest["completed_at"]) == phase.completed_at
        and type(manifest["cleanup_confirmed"]) is bool
        and manifest["formal_run_started"] is False
        and manifest["level_d_validated"] is False
    )
    for name in (
        "contract_content_hash",
        "bootstrap_manifest_hash",
        "recipe_content_hash",
        "harness_sha256",
        "seccomp_sha256",
    ):
        _require(isinstance(manifest[name], str) and re.fullmatch(r"[0-9a-f]{64}", manifest[name]))
    job = manifest["job"]
    request, _ = _validate_job(job)
    _require(
        job["execution_attempt_id"] == str(attempt.id)
        and job["harness_sha256"] == manifest["harness_sha256"]
        and request.source_revision_content_hash == attempt.source_revision.content_hash
        and request.source_tree_hash == attempt.source_revision.source_tree_hash
        and manifest["browser_image_id"] == f"sha256:{request.runner_image_digest}"
    )
    code = manifest["process_exit_code"]
    _require(code is None or type(code) is int)
    _require(phase.exit_codes == (() if code is None else (code,)))
    store.verify_nested(manifest)
    operations = manifest["operations"]
    _require(isinstance(operations, list) and len(operations) <= 32)
    labels = set()
    execute = None
    for operation in operations:
        _require(
            isinstance(operation, dict)
            and set(operation) == {"label", "status", "exit_code", "stdout_ref", "stderr_ref"}
        )
        _require(isinstance(operation["label"], str) and operation["label"] not in labels)
        _require(
            operation["status"]
            in {"COMPLETED", "TIMED_OUT", "OUTPUT_LIMIT_EXCEEDED", "RUNTIME_ERROR"}
        )
        _require(operation["exit_code"] is None or type(operation["exit_code"]) is int)
        _require(operation["status"] != "COMPLETED" or operation["exit_code"] is not None)
        labels.add(operation["label"])
        for stream, references in (("stdout", phase.stdout_refs), ("stderr", phase.stderr_refs)):
            ref = WebEvidenceReference(**operation[f"{stream}_ref"])
            _require(ref in references)
            store.read_reference(ref, media_type="text/plain")
        if operation["label"] == "EXECUTE":
            execute = operation
    metadata, bundle = manifest["browser_evidence"], manifest["bundle"]
    if bundle is None:
        _require(metadata is None and phase.is_failure and bool(manifest["failure_code"]))
        return
    _require(isinstance(metadata, dict) and isinstance(bundle, dict) and execute is not None)
    _require(execute["status"] == "COMPLETED")
    raw = store.read_reference(execute["stdout_ref"], media_type="text/plain")
    decoded = decode_browser_evidence(raw, job=job, store=store, run_id=attempt.id)
    _require(decoded.bundle.to_snapshot() == bundle and decoded.metadata == metadata)
    _require(decoded.findings == phase.findings)
    if phase.status is WebPhaseResultStatus.PASSED:
        _require(not decoded.failed and code == 0 and manifest["cleanup_confirmed"])


def _verify_validation_binding(manifest, *, attempt, root):
    validation = next(
        item for item in attempt.report.phase_results if item.phase is WebExecutionPhase.VALIDATE
    )
    if not validation.artifact_refs:
        return
    store = _ReadOnlyBrowserEvidenceStore(root, validation.artifact_refs)
    for reference in validation.artifact_refs:
        if reference.media_type != "application/json":
            continue
        metadata = read_json(store.read_reference(reference, media_type="application/json"))
        if not isinstance(metadata, dict) or metadata.get("phase") != "VALIDATE":
            continue
        _require(
            metadata["contract_hash"] == manifest["contract_content_hash"]
            and metadata["source_revision_content_hash"] == attempt.source_revision.content_hash
            and metadata["source_tree_hash"] == attempt.source_revision.source_tree_hash
            and metadata["image_id"] == f"sha256:{attempt.report.runner_image_digest}"
            and metadata["policy_hash"] == attempt.report.policy_content_hash
            and metadata["bootstrap_manifest_hash"] == manifest["bootstrap_manifest_hash"]
            and metadata.get("execution_attempt_id") in {None, str(attempt.id)}
        )


def _schema():
    # Use the authoritative tables, not a parallel schema or metadata registry.
    from orchestwin.projects.persistence.models import ProjectRecord
    from orchestwin.web_execution.attempt_persistence import WEB_EXECUTION_ATTEMPTS

    return WEB_EXECUTION_ATTEMPTS, ProjectRecord.__table__


def _decode_attempt(row: Mapping[str, object]):
    from orchestwin.web_execution.attempt_persistence import web_execution_attempt_from_record

    return web_execution_attempt_from_record(row)


def _owned_attempts(owner_user_id: UUID):
    attempts, projects = _schema()
    return (
        select(attempts)
        .join(projects, projects.c.id == attempts.c.project_id)
        .where(
            projects.c.owner_user_id == owner_user_id,
            projects.c.archived_at.is_(None),
            attempts.c.created_by_user_id == owner_user_id,
        )
    )


def _snapshot(row: Mapping[str, object]) -> dict[str, JsonValue]:
    try:
        return cast(dict[str, JsonValue], _decode_attempt(row).to_snapshot())
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=409, detail={"code": "WEB_EXECUTION_EVIDENCE_INTEGRITY_FAILED"}
        ) from None


class SqlAlchemyWebExecutionReadApiService:
    """Owner-scoped SELECT-only adapter for history, attempts and normalized reports."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        evidence_root: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._evidence_root = None if evidence_root is None else Path(evidence_root)

    async def execution_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        attempts, _ = _schema()
        async with self._session_factory() as session:
            result = await session.execute(
                _owned_attempts(owner_user_id)
                .where(attempts.c.project_id == project_id)
                .order_by(attempts.c.attempt_number.asc())
            )
            return tuple(_snapshot(row) for row in result.mappings().all())

    async def execution(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        attempts, _ = _schema()
        async with self._session_factory() as session:
            result = await session.execute(
                _owned_attempts(owner_user_id).where(attempts.c.id == execution_id)
            )
            row = result.mappings().one_or_none()
            return None if row is None else _snapshot(row)

    async def execution_report(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
    ) -> dict[str, JsonValue] | None:
        snapshot = await self.execution(owner_user_id=owner_user_id, execution_id=execution_id)
        if snapshot is None:
            return None
        return cast(dict[str, JsonValue], snapshot["report"])

    async def browser_evidence(
        self, *, owner_user_id: UUID, execution_id: UUID
    ) -> dict[str, JsonValue] | None:
        """Return the stored observed manifest, including honest partial failures."""
        attempts, _ = _schema()
        async with self._session_factory() as session:
            result = await session.execute(
                _owned_attempts(owner_user_id).where(attempts.c.id == execution_id)
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        try:
            attempt = _decode_attempt(row)
            phase = next(
                item
                for item in attempt.report.phase_results
                if item.phase is WebExecutionPhase.BROWSER_EVIDENCE
            )
            if not phase.artifact_refs:
                return None
            _require(self._evidence_root is not None)
            store = _ReadOnlyBrowserEvidenceStore(
                self._evidence_root,
                (*phase.artifact_refs, *phase.stdout_refs, *phase.stderr_refs),
            )
            manifests = []
            for reference in phase.artifact_refs:
                data = store.read_reference(reference)
                if reference.media_type == "application/json":
                    value = read_json(data)
                    if (
                        isinstance(value, dict)
                        and value.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE"
                    ):
                        manifests.append(value)
            if not manifests:
                return None
            _require(len(manifests) == 1)
            manifest = manifests[0]
            _verify_browser_manifest(manifest, attempt=attempt, phase=phase, store=store)
            _verify_validation_binding(manifest, attempt=attempt, root=self._evidence_root)
            return cast(dict[str, JsonValue], manifest)
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            RecursionError,
            StopIteration,
        ):
            raise HTTPException(
                status_code=409, detail={"code": "WEB_EXECUTION_EVIDENCE_INTEGRITY_FAILED"}
            ) from None
