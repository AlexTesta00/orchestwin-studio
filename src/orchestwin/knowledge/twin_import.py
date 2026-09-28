from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION, TWIN_DOCUMENT_KIND
from orchestwin.knowledge.schema import KnowledgeSchemaError, validate_document
from orchestwin.twins.epistemics import (
    EvidenceReference,
    EvidenceSourceKind,
    ObservationProvenance,
    ProfileObservation,
)
from orchestwin.twins.limits import MAX_USER_TWINS
from orchestwin.twins.persistence.snapshots import (
    persona_version_from_snapshot,
    user_twin_version_from_snapshot,
)
from orchestwin.twins.personas import PersonaProfileVersion
from orchestwin.twins.user_twins import (
    ConfirmedPersonaReference,
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)

TWIN_ORIGIN_PREFIX: Final = "user-twin:"
PERSONA_ORIGIN_PREFIX: Final = "persona-origin:"
PROJECT_LOCATOR_PREFIX: Final = "project:"
_SUMMARY_LIMIT: Final = 160


class TwinImportError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class TwinOrigin:
    project_id: UUID
    project_name: str
    twin_id: UUID
    twin_version_number: int
    twin_content_hash: str
    persona_id: UUID
    persona_version_number: int
    persona_content_hash: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "project_name": self.project_name,
            "twin_id": str(self.twin_id),
            "twin_version_number": self.twin_version_number,
            "twin_content_hash": self.twin_content_hash,
            "persona_id": str(self.persona_id),
            "persona_version_number": self.persona_version_number,
            "persona_content_hash": self.persona_content_hash,
        }


@dataclass(frozen=True, slots=True)
class PortableTwinDocument:
    origin: TwinOrigin
    persona: PersonaProfileVersion
    twin: UserTwinProfileVersion


@dataclass(frozen=True, slots=True)
class TwinImportTarget:
    project_id: UUID
    project_brief_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str


@dataclass(frozen=True, slots=True)
class TwinImportIdentities:
    persona_id: UUID
    persona_version_id: UUID
    twin_id: UUID
    twin_version_id: UUID
    snapshot_version_id: UUID


@dataclass(frozen=True, slots=True)
class ImportedTwin:
    origin: TwinOrigin
    persona_version: PersonaProfileVersion
    twin_version: UserTwinProfileVersion
    snapshot_version: UserModelingSnapshotVersion


def parse_twin_document(document: object) -> PortableTwinDocument:
    if not isinstance(document, Mapping):
        raise TwinImportError("TWIN_DOCUMENT_INVALID")
    for key, expected in (
        ("kind", TWIN_DOCUMENT_KIND),
        ("schema_version", KNOWLEDGE_SCHEMA_VERSION),
    ):
        if key in document and document[key] != expected:
            raise TwinImportError("TWIN_DOCUMENT_UNSUPPORTED", key)
    try:
        validate_document("twin", document)
    except KnowledgeSchemaError as error:
        raise TwinImportError("TWIN_DOCUMENT_INVALID", error.location) from error
    project_name = " ".join(str(document["origin"]["project_name"]).split())
    if not project_name:
        raise TwinImportError("TWIN_DOCUMENT_INVALID", "origin.project_name")
    try:
        persona = persona_version_from_snapshot(document["persona"])
        twin = user_twin_version_from_snapshot(document["twin"])
        reference = ConfirmedPersonaReference.from_version(persona)
        project_id = UUID(str(document["origin"]["project_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise TwinImportError("TWIN_DOCUMENT_INVALID", str(error)) from error
    if twin.profile.persona_reference != reference:
        raise TwinImportError("TWIN_DOCUMENT_INVALID", "persona")
    if persona.project_id != twin.project_id or twin.project_id != project_id:
        raise TwinImportError("TWIN_DOCUMENT_INVALID", "project")
    return PortableTwinDocument(
        origin=TwinOrigin(
            project_id=project_id,
            project_name=project_name,
            twin_id=twin.twin_id,
            twin_version_number=twin.version_number,
            twin_content_hash=twin.content_hash,
            persona_id=persona.persona_id,
            persona_version_number=persona.version_number,
            persona_content_hash=persona.content_hash,
        ),
        persona=persona,
        twin=twin,
    )


def _summary(origin: TwinOrigin) -> str:
    text = f"Imported from the project {origin.project_name}"
    return text if len(text) <= _SUMMARY_LIMIT else f"{text[: _SUMMARY_LIMIT - 1].rstrip()}…"


def twin_origin_reference(origin: TwinOrigin) -> EvidenceReference:
    return EvidenceReference(
        source_kind=EvidenceSourceKind.SYSTEM_ARTIFACT,
        source_id=f"{TWIN_ORIGIN_PREFIX}{origin.twin_id}",
        source_version=origin.twin_version_number,
        content_hash=origin.twin_content_hash,
        locator=f"{PROJECT_LOCATOR_PREFIX}{origin.project_id}",
        summary=_summary(origin),
    )


def persona_origin_reference(origin: TwinOrigin) -> EvidenceReference:
    return EvidenceReference(
        source_kind=EvidenceSourceKind.SYSTEM_ARTIFACT,
        source_id=f"{PERSONA_ORIGIN_PREFIX}{origin.persona_id}",
        source_version=origin.persona_version_number,
        content_hash=origin.persona_content_hash,
        locator=f"{PROJECT_LOCATOR_PREFIX}{origin.project_id}",
        summary=_summary(origin),
    )


def _with_origin(
    observation: ProfileObservation, reference: EvidenceReference
) -> ProfileObservation:
    references = observation.provenance.references
    if reference in references:
        return observation
    return replace(
        observation,
        provenance=ObservationProvenance.from_references((*references, reference)),
    )


def imported_twin_ids(snapshot: UserModelingSnapshotVersion | None) -> dict[UUID, UUID]:
    if snapshot is None:
        return {}
    found: dict[UUID, UUID] = {}
    for version in snapshot.snapshot.twin_versions:
        for observation in version.profile.observations:
            for reference in observation.provenance.references:
                if (
                    reference.source_kind is EvidenceSourceKind.SYSTEM_ARTIFACT
                    and reference.source_id.startswith(TWIN_ORIGIN_PREFIX)
                ):
                    origin = reference.source_id.removeprefix(TWIN_ORIGIN_PREFIX)
                    found[UUID(origin)] = version.twin_id
    return found


def twin_origin_chain(version: UserTwinProfileVersion) -> tuple[dict[str, object], ...]:
    chain: list[dict[str, object]] = []
    for observation in version.profile.observations:
        for reference in observation.provenance.references:
            if (
                reference.source_kind is not EvidenceSourceKind.SYSTEM_ARTIFACT
                or not reference.source_id.startswith(TWIN_ORIGIN_PREFIX)
            ):
                continue
            locator = reference.locator or ""
            origin = {
                "twin_id": reference.source_id.removeprefix(TWIN_ORIGIN_PREFIX),
                "twin_version_number": reference.source_version,
                "twin_content_hash": reference.content_hash,
                "project_id": locator.removeprefix(PROJECT_LOCATOR_PREFIX) or None,
                "summary": reference.summary,
            }
            if origin not in chain:
                chain.append(origin)
    return tuple(chain)


def twin_origin_of(version: UserTwinProfileVersion) -> dict[str, object] | None:
    chain = twin_origin_chain(version)
    return chain[-1] if chain else None


def _name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def import_issue(
    document: PortableTwinDocument,
    *,
    target: TwinImportTarget,
    current: UserModelingSnapshotVersion | None,
) -> str | None:
    if current is None:
        return "USER_TWINS_REQUIRED"
    if current.project_id != target.project_id:
        return "USER_TWINS_REQUIRED"
    snapshot = current.snapshot
    if (
        snapshot.project_brief_reference != target.project_brief_reference
        or snapshot.agent_team_reference != target.agent_team_reference
        or snapshot.catalog_version != target.catalog_version
        or snapshot.catalog_content_hash != target.catalog_content_hash
    ):
        return "USER_TWINS_OUTDATED"
    if document.origin.project_id == target.project_id:
        return "TWIN_BELONGS_TO_PROJECT"
    if document.origin.twin_id in imported_twin_ids(current):
        return "TWIN_ALREADY_IMPORTED"
    if len(snapshot.twin_versions) >= MAX_USER_TWINS:
        return "TWIN_LIMIT_REACHED"
    names = {_name_key(version.profile.name) for version in snapshot.twin_versions}
    if _name_key(document.twin.profile.name) in names:
        return "TWIN_NAME_ALREADY_USED"
    return None


def import_twin(
    document: PortableTwinDocument,
    *,
    target: TwinImportTarget,
    current: UserModelingSnapshotVersion | None,
    identities: TwinImportIdentities,
    created_by_user_id: UUID,
    created_at: datetime,
) -> ImportedTwin:
    issue = import_issue(document, target=target, current=current)
    if issue is not None or current is None:
        raise TwinImportError(issue or "USER_TWINS_REQUIRED")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("twin import timestamp must be timezone-aware")
    persona_origin = persona_origin_reference(document.origin)
    twin_origin = twin_origin_reference(document.origin)
    persona_profile = replace(
        document.persona.profile,
        observations=tuple(
            _with_origin(observation, persona_origin)
            for observation in document.persona.profile.observations
        ),
    )
    persona_version = PersonaProfileVersion(
        id=identities.persona_version_id,
        project_id=target.project_id,
        persona_id=identities.persona_id,
        version_number=1,
        based_on_version_number=None,
        profile=persona_profile,
        content_hash=persona_profile.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )
    twin_profile = replace(
        document.twin.profile,
        persona_reference=ConfirmedPersonaReference.from_version(persona_version),
        project_brief_reference=target.project_brief_reference,
        agent_team_reference=target.agent_team_reference,
        catalog_version=target.catalog_version,
        catalog_content_hash=target.catalog_content_hash,
        validation_status=UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
        observations=tuple(
            _with_origin(observation, twin_origin)
            for observation in document.twin.profile.observations
        ),
    )
    twin_version = UserTwinProfileVersion(
        id=identities.twin_version_id,
        project_id=target.project_id,
        twin_id=identities.twin_id,
        version_number=1,
        based_on_version_number=None,
        profile=twin_profile,
        content_hash=twin_profile.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )
    snapshot = create_user_modeling_snapshot(
        project_id=target.project_id,
        project_brief_reference=target.project_brief_reference,
        agent_team_reference=target.agent_team_reference,
        catalog_version=target.catalog_version,
        catalog_content_hash=target.catalog_content_hash,
        persona_versions=(*current.snapshot.persona_versions, persona_version),
        twin_versions=(*current.snapshot.twin_versions, twin_version),
    )
    snapshot_version = UserModelingSnapshotVersion(
        id=identities.snapshot_version_id,
        project_id=target.project_id,
        version_number=current.version_number + 1,
        based_on_version_number=current.version_number,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=created_by_user_id,
        created_at=created_at,
    )
    return ImportedTwin(
        origin=document.origin,
        persona_version=persona_version,
        twin_version=twin_version,
        snapshot_version=snapshot_version,
    )


__all__ = [
    "PERSONA_ORIGIN_PREFIX",
    "PROJECT_LOCATOR_PREFIX",
    "TWIN_ORIGIN_PREFIX",
    "ImportedTwin",
    "PortableTwinDocument",
    "TwinImportError",
    "TwinImportIdentities",
    "TwinImportTarget",
    "TwinOrigin",
    "import_issue",
    "import_twin",
    "imported_twin_ids",
    "parse_twin_document",
    "persona_origin_reference",
    "twin_origin_chain",
    "twin_origin_of",
    "twin_origin_reference",
]
