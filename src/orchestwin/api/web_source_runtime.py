"""Persist Web source plans and explicit owner edits after Architecture approval.

This service stores source bytes and metadata only. It does not run a model,
build, test, execute code, authorize Gate 7, or approve a formal case.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.web_execution import (
    WebApiCommandResult,
    WebApiCommandStatus,
    WebSourceRevisionCreateCommand,
)
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.web_source_persistence import (
    WEB_SOURCE_REVISIONS,
    SqlAlchemyWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
    web_source_revision_from_record,
)
from orchestwin.artifacts.web_source_plans import (
    FileSystemWebSourceContentStore,
    WebSourcePlanFile,
    create_web_source_plan,
    validate_web_source_plan,
)
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_design_contract import validate_prototype_html
from orchestwin.models.source_publication import bind_source_publication
from orchestwin.models.source_syntax import validate_source_syntax
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebTargetSelection,
    web_scope_for,
)
from orchestwin.web_execution.workspaces import (
    PreparedWebWorkspace,
    materialize_web_source_snapshot,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository

_ALLOWED_TARGETS = frozenset({"WEB_STATIC", "WEB_VUE", "WEB_NODE_EXPRESS", "WEB_VUE_NODE"})
_ALLOWED_LANGUAGES = frozenset(
    {None, WebImplementationLanguage.STATIC_ASSETS, WebImplementationLanguage.JAVASCRIPT}
)


def _rejected(status: WebApiCommandStatus, message: str) -> WebApiCommandResult:
    return WebApiCommandResult(status=status, snapshot=None, message=message)


def _owned_sources(*, owner_user_id: UUID, project_id: UUID):
    """Select immutable rows only through the active owner-scoped project."""
    return (
        select(WEB_SOURCE_REVISIONS)
        .join(ProjectRecord, ProjectRecord.id == WEB_SOURCE_REVISIONS.c.project_id)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
            WEB_SOURCE_REVISIONS.c.created_by_user_id == owner_user_id,
        )
    )


def _safe_storage_root(root: Path) -> None:
    """Reject redirected parents before using the existing content store."""
    for candidate in (root, *root.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise OSError("WEB_SOURCE_STORAGE_ROOT_UNSAFE")


def _snapshot(revision: WebSourceRevision) -> dict[str, JsonValue]:
    # The domain snapshot contains hashes and storage keys, not plaintext files.
    return cast(dict[str, JsonValue], revision.to_snapshot())


class SqlAlchemyWebSourceApiService:
    """Owner-scoped source versions without execution capability claims."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        content_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._content_root = Path(content_root).absolute()
        self._content_store = FileSystemWebSourceContentStore(self._content_root)

    async def _owner_mockup(self, *, owner_user_id, project_id, generation_id):
        """Read and validate one exact audited draft, never the latest draft."""
        from orchestwin.api.design import DesignPackagePayload

        try:
            evidence = await SqlAlchemyProposalEvidenceStore(self._session_factory).get_owned(
                owner_user_id=owner_user_id, project_id=project_id, generation_id=generation_id
            )
            if evidence is None:
                raise ValueError("mockup not owned")
            request = evidence["request"]
            context = json.loads(request["request"]["input_payload_json"])["context"]
            context = context.get("request", context)
            accepted = [
                event["payload"]
                for event in evidence["observations"]
                if event["kind"] == "ADAPTER_ACCEPTED"
            ]
            if (
                request["generation_id"] != str(generation_id)
                or request["project_id"] != str(project_id)
                or request["owner_user_id"] != str(owner_user_id)
                or context.get("purpose") != "DESIGN_MOCKUP"
                or context.get("project_id") != str(project_id)
                or len(accepted) != 1
            ):
                raise ValueError("invalid mockup request")
            result = accepted[0]["result"]
            package = DesignPackagePayload.model_validate(result["package"]).to_domain()
            prototype = package.prototype
            if (
                prototype is None
                or result["status"] != "MOCKUP_GENERATED"
                or result["generation_id"] != str(generation_id)
                or result["design_version_id"] != context["design_version_id"]
                or result["design_content_hash"] != context["design_content_hash"]
                or str(package.owner_selected_alternative_id) != context["alternative"]["id"]
                or package.content_hash not in accepted[0]["generated_content_hashes"]["DESIGN"]
            ):
                raise ValueError("mockup result does not bind request")
            return {
                "generation_id": str(generation_id),
                "design_version_id": result["design_version_id"],
                "design_content_hash": result["design_content_hash"],
                "prototype_id": str(prototype.id),
                "prototype_content_hash": prototype.content_hash,
                "package_content_hash": package.content_hash,
                "prototype": prototype.to_snapshot(),
            }
        except (ProposalEvidenceError, KeyError, TypeError, ValueError):
            raise HTTPException(
                409, detail={"code": "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"}
            ) from None

    def _api_snapshot(self, revision):
        snapshot = _snapshot(revision)
        if snapshot.get("origin") != WebSourceOrigin.OWNER_EDIT.value:
            return snapshot
        references = [
            item
            for item in snapshot["provenance_references"]
            if item["kind"] == WebSourceProvenanceKind.OWNER_DECISION.value
            and item["reference_id"] == f"source-edit:{revision.id}"
        ]
        try:
            if len(references) != 1:
                raise ValueError("missing owner decision")
            digest = references[0]["content_hash"]
            _safe_storage_root(self._content_root)
            content = self._content_store.read(f"sha256/{digest[:2]}/{digest}")
            if content is None or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("unavailable owner decision")
            decision = json.loads(content)
            if not isinstance(decision, dict):
                raise ValueError("invalid owner decision")
            expected = {
                "schema": "WEB_SOURCE_OWNER_EDIT_V1",
                "revision_id": str(revision.id),
                "project_id": str(revision.project_id),
                "owner_user_id": str(revision.created_by_user_id),
                "base_revision": snapshot["based_on"],
                "files": snapshot["files"],
            }
            if (
                any(decision.get(key) != value for key, value in expected.items())
                or references[0]["version_number"] != revision.version_number
                or not isinstance(decision.get("rationale"), str)
                or not decision["rationale"].strip()
            ):
                raise ValueError("owner decision does not bind this revision")
        except (OSError, TypeError, ValueError, KeyError):
            raise HTTPException(503, detail={"code": "WEB_SOURCE_EDIT_AUDIT_UNAVAILABLE"}) from None
        return {**snapshot, "owner_edit": decision}

    async def edit_source_revision(
        self, *, owner_user_id: UUID, project_id: UUID, revision_id: UUID, command
    ) -> WebApiCommandResult:
        """Append an explicit owner edit, without claiming model or execution evidence."""
        async with self._session_factory() as session, session.begin():
            project = await session.scalar(
                select(ProjectRecord)
                .where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
                .with_for_update()
            )
            if project is None:
                return _rejected(WebApiCommandStatus.NOT_FOUND, "WEB_SOURCE_PROJECT_NOT_FOUND")
            if project.mode != ProjectMode.GREENFIELD_GENERATION.value:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_REQUIRES_GREENFIELD")
            revisions = SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner_user_id)
            base = await revisions.current(project_id=project_id)
            if base is None:
                return _rejected(WebApiCommandStatus.NOT_FOUND, "WEB_SOURCE_NOT_FOUND")
            if base.id != revision_id or base.content_hash != command.base_revision_content_hash:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_EDIT_STALE_BASE")
            if base.target_selection.target.value != "WEB_STATIC":
                return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_EDIT_REQUIRES_STATIC")
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).get_current_owned_for_update(project_id=project_id, owner_user_id=owner_user_id)
            gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )
            if architecture is None or gate is None:
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED,
                    "WEB_SOURCE_ARCHITECTURE_APPROVAL_REQUIRED",
                )
            exact = GateArtifactReference(
                project_id,
                HumanGateType.ARCHITECTURE,
                architecture.id,
                architecture.version_number,
                architecture.content_hash,
            )
            reference = WebSourceProvenanceReference(
                WebSourceProvenanceKind.ARCHITECTURE,
                f"architecture:{architecture.id}",
                architecture.version_number,
                architecture.content_hash,
            )
            if (
                architecture.project_id != project_id
                or gate.owner_user_id != owner_user_id
                or gate.project_id != project_id
                or gate.gate_type is not HumanGateType.ARCHITECTURE
                or gate.status is not HumanGateStatus.APPROVED
                or gate.artifact != exact
                or tuple(
                    ref
                    for ref in base.provenance_references
                    if ref.kind is WebSourceProvenanceKind.ARCHITECTURE
                )
                != (reference,)
            ):
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED, "WEB_SOURCE_ARCHITECTURE_NOT_APPROVED"
                )
            visual_reference = None
            mockup_id = getattr(command, "mockup_generation_id", None)
            inherited_reference = None
            if mockup_id is None and base.origin is WebSourceOrigin.OWNER_EDIT:
                inherited_reference = self._api_snapshot(base)["owner_edit"].get("visual_reference")
                if inherited_reference is not None:
                    try:
                        mockup_id = UUID(inherited_reference["generation_id"])
                    except (KeyError, TypeError, ValueError):
                        raise HTTPException(
                            409, detail={"code": "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"}
                        ) from None
            if mockup_id is not None:
                mockup = await self._owner_mockup(
                    owner_user_id=owner_user_id, project_id=project_id, generation_id=mockup_id
                )
                visual_reference = {
                    key: value for key, value in mockup.items() if key != "prototype"
                }
                if inherited_reference is not None:
                    if visual_reference != inherited_reference:
                        raise HTTPException(
                            409, detail={"code": "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"}
                        )
                else:
                    design = await SqlAlchemyDesignPackageRepository(
                        session, owner_user_id=owner_user_id
                    ).current(project_id=project_id)
                    if design is None or (str(design.id), design.content_hash) != (
                        mockup["design_version_id"],
                        mockup["design_content_hash"],
                    ):
                        return _rejected(
                            WebApiCommandStatus.CONFLICT, "WEB_SOURCE_MOCKUP_CONTEXT_CHANGED"
                        )
            try:
                if any(
                    PureWindowsPath(f.normalized_path).drive or ":" in f.normalized_path
                    for f in command.files
                ):
                    raise ValueError("non-portable source path")
                plan = create_web_source_plan(
                    plan_id=uuid4(),
                    project_id=project_id,
                    created_by_user_id=owner_user_id,
                    target_selection=base.target_selection,
                    files=tuple(
                        WebSourcePlanFile(f.normalized_path, f.content, f.media_type)
                        for f in command.files
                    ),
                    rationale=command.rationale,
                    provenance_references=(reference,),
                    created_at=datetime.now(UTC),
                )
                if not validate_web_source_plan(plan).is_accepted or "index.html" not in {
                    f.normalized_path for f in plan.files
                }:
                    raise ValueError("invalid static source tree")
                if sum(f.size_bytes for f in plan.files) > 1_048_576:
                    raise ValueError("source edit too large")
            except (TypeError, ValueError):
                return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_EDIT_PLAN_INVALID")
            try:
                for file in plan.files:
                    await asyncio.to_thread(validate_source_syntax, file)
                if visual_reference is not None:
                    html = next(
                        file.content for file in plan.files if file.normalized_path == "index.html"
                    )
                    validate_prototype_html(html, mockup["prototype"])
            except ProposalGenerationError as error:
                if error.code == "SOURCE_JAVASCRIPT_PARSER_UNAVAILABLE":
                    raise HTTPException(503, detail={"code": error.code}) from None
                return _rejected(WebApiCommandStatus.INVALID, error.code)
            try:
                _safe_storage_root(self._content_root)
                entries = tuple(
                    self._content_store.store(
                        normalized_path=f.normalized_path,
                        content=f.content_bytes,
                        media_type=f.media_type,
                    )
                    for f in plan.files
                )
                if entries == base.files:
                    return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_EDIT_UNCHANGED")
                next_id, timestamp = uuid4(), datetime.now(UTC)
                decision = {
                    "schema": "WEB_SOURCE_OWNER_EDIT_V1",
                    "revision_id": str(next_id),
                    "project_id": str(project_id),
                    "owner_user_id": str(owner_user_id),
                    "base_revision": base.reference.to_snapshot(),
                    "rationale": plan.rationale,
                    "files": [f.to_snapshot() for f in entries],
                    "created_at": timestamp.isoformat(),
                }
                if visual_reference is not None:
                    decision["visual_reference"] = visual_reference
                audit = self._content_store.store(
                    normalized_path="owner-edit.json",
                    content=canonical_json(decision).encode("utf-8"),
                    media_type="application/json",
                )
                revision = create_web_source_revision(
                    revision_id=next_id,
                    project_id=project_id,
                    created_by_user_id=owner_user_id,
                    version_number=base.version_number + 1,
                    based_on=base.reference,
                    target=base.target_selection.target,
                    language_configuration=base.target_selection.language_configuration,
                    layout=base.target_selection.layout,
                    origin=WebSourceOrigin.OWNER_EDIT,
                    files=entries,
                    provenance_references=(
                        reference,
                        WebSourceProvenanceReference(
                            WebSourceProvenanceKind.OWNER_DECISION,
                            f"source-edit:{next_id}",
                            base.version_number + 1,
                            audit.sha256_digest,
                        ),
                    ),
                    created_at=timestamp,
                )
            except (OSError, TypeError, ValueError):
                raise HTTPException(
                    503, detail={"code": "WEB_SOURCE_STORAGE_UNAVAILABLE"}
                ) from None
            stored = await revisions.append(revision)
            if (
                stored.status is not WebSourceRevisionAppendStatus.APPENDED
                or stored.revision is None
            ):
                raise HTTPException(409, detail={"code": "WEB_SOURCE_APPEND_CONFLICT"})
            return WebApiCommandResult(
                status=WebApiCommandStatus.SOURCE_REVISION_CREATED,
                snapshot=self._api_snapshot(stored.revision),
                message="Owner edit stored as a new revision; model generation and execution are not claimed.",
            )

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebSourceRevisionCreateCommand,
    ) -> WebApiCommandResult:
        """Create revision 1; later versions require owner edits or governed repairs."""
        if command.target.value not in _ALLOWED_TARGETS or any(
            language not in _ALLOWED_LANGUAGES
            for language in (command.frontend_language, command.backend_language)
        ):
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_STACK_OUTSIDE_SCOPE")
        try:
            selection = WebTargetSelection(
                target=command.target,
                language_configuration=WebLanguageConfiguration(
                    frontend=command.frontend_language,
                    backend=command.backend_language,
                ),
                layout=command.layout,
            )
            selection.validate_against(web_scope_for(selection.target))
            # Disallow Windows drives and alternate data stream syntax as well.
            if any(
                PureWindowsPath(item.normalized_path).drive or ":" in item.normalized_path
                for item in command.files
            ):
                raise ValueError("WINDOWS_PATH_NOT_PORTABLE")
            if len(command.provenance_references) != 1:
                raise ValueError("ONE_VERIFIABLE_ARCHITECTURE_REFERENCE_REQUIRED")
            references = tuple(
                WebSourceProvenanceReference(
                    kind=item.kind,
                    reference_id=item.reference_id,
                    version_number=item.version_number,
                    content_hash=item.content_hash,
                )
                for item in command.provenance_references
            )
            timestamp = datetime.now(UTC)
            plan = create_web_source_plan(
                plan_id=uuid4(),
                project_id=project_id,
                created_by_user_id=owner_user_id,
                target_selection=selection,
                files=tuple(
                    WebSourcePlanFile(
                        normalized_path=item.normalized_path,
                        content=item.content,
                        media_type=item.media_type,
                    )
                    for item in command.files
                ),
                rationale=command.rationale,
                provenance_references=references,
                created_at=timestamp,
            )
            validation = validate_web_source_plan(plan)
        except (TypeError, ValueError):
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_PLAN_INVALID")
        if not validation.is_accepted:
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_PLAN_REJECTED")

        async with self._session_factory() as session, session.begin():
            project = await session.scalar(
                select(ProjectRecord)
                .where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
                .with_for_update()
            )
            if project is None:
                return _rejected(WebApiCommandStatus.NOT_FOUND, "WEB_SOURCE_PROJECT_NOT_FOUND")
            if project.mode != ProjectMode.GREENFIELD_GENERATION.value:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_REQUIRES_GREENFIELD")
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).get_current_owned_for_update(project_id=project_id, owner_user_id=owner_user_id)
            gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )
            if architecture is None or gate is None:
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED,
                    "WEB_SOURCE_ARCHITECTURE_APPROVAL_REQUIRED",
                )
            exact = GateArtifactReference(
                project_id=project_id,
                gate_type=HumanGateType.ARCHITECTURE,
                artifact_id=architecture.id,
                version=architecture.version_number,
                content_hash=architecture.content_hash,
            )
            if (
                architecture.project_id != project_id
                or gate.project_id != project_id
                or gate.owner_user_id != owner_user_id
                or gate.gate_type is not HumanGateType.ARCHITECTURE
                or gate.status is not HumanGateStatus.APPROVED
                or gate.artifact != exact
            ):
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED, "WEB_SOURCE_ARCHITECTURE_NOT_APPROVED"
                )
            # The domain requires provenance IDs to begin with a letter. A prefixed
            # UUID is unambiguous and can be resolved to an exact persisted version.
            expected_reference = WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.ARCHITECTURE,
                reference_id=f"architecture:{architecture.id}",
                version_number=architecture.version_number,
                content_hash=architecture.content_hash,
            )
            if references != (expected_reference,):
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_PROVENANCE_MISMATCH")
            revisions = SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner_user_id)
            if await revisions.current(project_id=project_id) is not None:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_INITIAL_REVISION_EXISTS")

            try:
                _safe_storage_root(self._content_root)
                entries = tuple(
                    self._content_store.store(
                        normalized_path=item.normalized_path,
                        content=item.content_bytes,
                        media_type=item.media_type,
                    )
                    for item in plan.files
                )
                revision = create_web_source_revision(
                    revision_id=uuid4(),
                    project_id=project_id,
                    created_by_user_id=owner_user_id,
                    version_number=1,
                    based_on=None,
                    target=selection.target,
                    language_configuration=selection.language_configuration,
                    layout=selection.layout,
                    origin=WebSourceOrigin.GENERATED_PLAN,
                    files=entries,
                    provenance_references=references,
                    created_at=datetime.now(UTC),
                )
            except (OSError, TypeError, ValueError):
                raise HTTPException(
                    503, detail={"code": "WEB_SOURCE_STORAGE_UNAVAILABLE"}
                ) from None
            stored = await revisions.append(revision)
            if (
                stored.status
                not in {
                    WebSourceRevisionAppendStatus.APPENDED,
                    WebSourceRevisionAppendStatus.ALREADY_PRESENT,
                }
                or stored.revision is None
            ):
                # Raising is necessary: the repository may have a failed INSERT.
                # The enclosing transaction rolls back; no failed result commits.
                raise HTTPException(409, detail={"code": "WEB_SOURCE_APPEND_CONFLICT"})
            await bind_source_publication(session, "WEB_SOURCE", stored.revision)
            return WebApiCommandResult(
                status=WebApiCommandStatus.SOURCE_REVISION_CREATED,
                snapshot=_snapshot(stored.revision),
                message="Web source revision stored; execution has not been performed.",
            )

    async def prepare_workspace(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> PreparedWebWorkspace | None:
        """Restore an owner-visible revision; preparation grants no execution authority."""
        snapshot = await self.source_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            revision_id=revision_id,
        )
        if snapshot is None:
            return None
        return materialize_web_source_snapshot(
            {key: value for key, value in snapshot.items() if key != "owner_edit"},
            content_root=self._content_root,
            workspaces_root=self._content_root.parent / "web-execution-workspaces",
        )

    async def source_revision_history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        _owned_sources(owner_user_id=owner_user_id, project_id=project_id).order_by(
                            WEB_SOURCE_REVISIONS.c.version_number
                        )
                    )
                )
                .mappings()
                .all()
            )
            return tuple(self._api_snapshot(web_source_revision_from_record(row)) for row in rows)

    async def source_files(self, *, owner_user_id: UUID, project_id: UUID, revision_id: UUID):
        """Read verified bytes for owner-controlled download and isolated browser preview."""
        snapshot = await self.source_revision(
            owner_user_id=owner_user_id, project_id=project_id, revision_id=revision_id
        )
        if snapshot is None:
            return None
        _safe_storage_root(self._content_root)
        files = []
        total = 0
        for entry in snapshot["files"]:
            content = self._content_store.read(entry["storage_key"])
            if (
                content is None
                or len(content) != entry["size_bytes"]
                or hashlib.sha256(content).hexdigest() != entry["sha256_digest"]
            ):
                raise HTTPException(503, detail={"code": "WEB_SOURCE_CONTENT_UNAVAILABLE"})
            total += len(content)
            if total > 10_000_000:
                raise HTTPException(413, detail={"code": "WEB_SOURCE_DOWNLOAD_TOO_LARGE"})
            files.append((entry["normalized_path"], entry["media_type"], content))
        return snapshot, files

    async def source_design_reference(
        self, *, owner_user_id: UUID, project_id: UUID, revision_id: UUID
    ):
        """Resolve the immutable design ancestry, without claiming visual conformance.

        A newer mockup draft is not part of a published source's input. Owner
        edits retain this ancestry but may change the implemented interface.
        """
        source = await self.source_revision(
            owner_user_id=owner_user_id, project_id=project_id, revision_id=revision_id
        )
        if source is None:
            return None
        owner_mockup = None
        visual_reference = source.get("owner_edit", {}).get("visual_reference")
        if visual_reference is not None:
            try:
                generation_id = UUID(visual_reference["generation_id"])
            except (KeyError, TypeError, ValueError):
                raise HTTPException(
                    409, detail={"code": "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"}
                ) from None
            owner_mockup = await self._owner_mockup(
                owner_user_id=owner_user_id, project_id=project_id, generation_id=generation_id
            )
            if {
                key: value for key, value in owner_mockup.items() if key != "prototype"
            } != visual_reference:
                raise HTTPException(409, detail={"code": "WEB_SOURCE_MOCKUP_REFERENCE_INVALID"})
            _, files = await self.source_files(
                owner_user_id=owner_user_id, project_id=project_id, revision_id=revision_id
            )
            try:
                html = next(data.decode("utf-8") for name, _, data in files if name == "index.html")
                validate_prototype_html(html, owner_mockup["prototype"])
            except (StopIteration, UnicodeError, ProposalGenerationError):
                raise HTTPException(
                    409, detail={"code": "WEB_SOURCE_MOCKUP_STRUCTURE_MISMATCH"}
                ) from None
        references = [
            item
            for item in source["provenance_references"]
            if item["kind"] == WebSourceProvenanceKind.ARCHITECTURE.value
        ]
        try:
            if len(references) != 1:
                raise ValueError("ambiguous architecture ancestry")
            reference = references[0]
            prefix, architecture_id = reference["reference_id"].split(":", 1)
            if prefix != "architecture":
                raise ValueError("invalid architecture reference")
            architecture_id = UUID(architecture_id)
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                409, detail={"code": "WEB_SOURCE_DESIGN_REFERENCE_INVALID"}
            ) from None

        def artifact_reference(version):
            return {
                "artifact_id": str(version.id),
                "version_number": version.version_number,
                "content_hash": version.content_hash,
            }

        async with self._session_factory() as session:
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).get(project_id=project_id, version_id=architecture_id)
            if (
                architecture is None
                or architecture.project_id != project_id
                or architecture.id != architecture_id
                or architecture.version_number != reference["version_number"]
                or architecture.content_hash != reference["content_hash"]
            ):
                raise HTTPException(409, detail={"code": "WEB_SOURCE_DESIGN_REFERENCE_UNAVAILABLE"})
            design_reference = architecture.package.grounding.design_package_reference
            designs = SqlAlchemyDesignPackageRepository(session, owner_user_id=owner_user_id)
            design = await designs.get(
                project_id=project_id, version_id=design_reference.artifact_id
            )
            if (
                design is None
                or design.project_id != project_id
                or design.id != design_reference.artifact_id
                or design.version_number != design_reference.version_number
                or design.content_hash != design_reference.content_hash
            ):
                raise HTTPException(409, detail={"code": "WEB_SOURCE_DESIGN_REFERENCE_UNAVAILABLE"})
            current = await designs.current(project_id=project_id)
            exact_design = artifact_reference(design)
            current_design = artifact_reference(current) if current is not None else None
            return {
                "source": {
                    "revision_id": source["id"],
                    "version_number": source["version_number"],
                    "content_hash": source["content_hash"],
                    "origin": source["origin"],
                },
                "architecture": artifact_reference(architecture),
                "design": exact_design,
                "prototype": (
                    design.package.prototype.to_snapshot()
                    if design.package.prototype is not None
                    else None
                ),
                "current_design": current_design,
                "design_status": (
                    "UNAVAILABLE"
                    if current_design is None
                    else "CURRENT"
                    if current_design == exact_design
                    else "STALE"
                ),
                "visual_conformance": "NOT_ASSESSED",
                "structure_contract": "VERIFIED" if owner_mockup is not None else "NOT_ASSESSED",
                "owner_mockup": owner_mockup,
            }

    async def source_revision(
        self, *, owner_user_id: UUID, project_id: UUID, revision_id: UUID
    ) -> dict[str, JsonValue] | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        _owned_sources(owner_user_id=owner_user_id, project_id=project_id).where(
                            WEB_SOURCE_REVISIONS.c.id == revision_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._api_snapshot(web_source_revision_from_record(row))
