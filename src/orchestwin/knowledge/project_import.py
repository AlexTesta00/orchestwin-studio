from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from orchestwin.agents.persistence.repositories import proposal_from_snapshot
from orchestwin.agents.proposals import TeamProposalRevisionKind, TeamProposalVersion
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.knowledge.archive import (
    MOCKUP_PROTOTYPE,
    KnowledgeArchiveError,
    VerifiedFolder,
    derived_prototype_snapshot,
    folder_generated_mockup,
    mockup_failure,
)
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.research_evidence import EVIDENCE_DOCUMENT
from orchestwin.knowledge.sources import StageIdentity, stage_consistency_issue
from orchestwin.projects.briefs import ProjectBrief
from orchestwin.projects.requirements_persistence import specification_from_snapshot
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.persistence.snapshots import (
    persona_profile_from_snapshot,
    user_modeling_snapshot_from_snapshot,
    user_twin_profile_from_snapshot,
)
from orchestwin.twins.user_twins import UserModelingSnapshotVersion

IMPORTED_VERSION_NUMBER: Final = 1
FOLDER_INCOMPLETE: Final = "FOLDER_INCOMPLETE"
_IDENTITY: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HASH: Final = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_IDENTITY_KEYS: Final = frozenset({"id", "persona_id", "twin_id", "project_id"})
_USER_KEYS: Final = frozenset({"created_by_user_id"})
_TIME_KEYS: Final = frozenset({"created_at"})
_VERSION_KEYS: Final = frozenset({"version_number"})
_LINEAGE_KEYS: Final = frozenset({"based_on_version_number"})
_TWIN_REFERENCE_KEYS: Final = frozenset({"twin_id", "version_number", "content_hash", "name"})
_SOURCE_KEYS: Final = frozenset({"kind", "source_id", "source_version", "content_hash", "locator"})
_MOCKUP_KEYS: Final = ("owner_selected_alternative_id", "alternatives", "generated_mockup")


@dataclass(frozen=True, slots=True)
class FolderOrigin:
    project_id: UUID
    project_name: str
    package_version: int
    package_content_hash: str
    schema_version: int

    def to_snapshot(self) -> dict[str, object]:
        return {
            "project_id": str(self.project_id),
            "project_name": self.project_name,
            "package_version": self.package_version,
            "package_content_hash": self.package_content_hash,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProjectImportPlan:
    origin: FolderOrigin
    project_id: UUID
    project_name: str
    brief_version_id: UUID
    brief: ProjectBrief
    team: TeamProposalVersion
    modeling: UserModelingSnapshotVersion
    requirements: RequirementsSpecificationVersion
    design: DesignPackageVersion
    identities: Mapping[str, str]
    hashes: Mapping[str, str]
    research_evidence: Mapping[str, object] | None = None
    evaluations: tuple = ()
    finding_decisions: tuple = ()
    import_limits: tuple[str, ...] = ()

    @property
    def personas(self):
        return self.modeling.snapshot.persona_versions

    @property
    def twins(self):
        return self.modeling.snapshot.twin_versions


def require_complete(folder: VerifiedFolder) -> None:
    if not folder.complete:
        raise KnowledgeArchiveError(FOLDER_INCOMPLETE, folder.pending_stage)


def folder_origin(folder: VerifiedFolder) -> FolderOrigin:
    return FolderOrigin(
        project_id=UUID(folder.project_id),
        project_name=folder.project_name,
        package_version=folder.package_version,
        package_content_hash=folder.content_hash,
        schema_version=int(folder.manifest["schema_version"]),
    )


def defined_identities(documents: Mapping[str, Mapping[str, object]]) -> frozenset[str]:
    found: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if (
                    key in _IDENTITY_KEYS
                    and isinstance(value, str)
                    and _IDENTITY.fullmatch(value) is not None
                ):
                    found.add(value)
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for document in documents.values():
        visit(document)
    return frozenset(found)


def _canonical(items: list[object]) -> list[object]:
    if not items:
        return items
    if all(isinstance(item, str) and _IDENTITY.fullmatch(item) is not None for item in items):
        return sorted(items, key=lambda item: UUID(item).hex)
    if not all(isinstance(item, Mapping) for item in items):
        return items
    keys = {frozenset(item) for item in items}
    if keys == {_TWIN_REFERENCE_KEYS}:
        return sorted(
            items,
            key=lambda item: (
                UUID(item["twin_id"]).hex,
                item["version_number"],
                item["content_hash"],
            ),
        )
    if keys == {_SOURCE_KEYS}:
        return sorted(
            items,
            key=lambda item: (
                item["kind"],
                item["source_id"],
                item["source_version"] or 0,
                item["content_hash"] or "",
                item["locator"] or "",
            ),
        )
    return items


class _Rewriter:
    def __init__(
        self,
        *,
        identities: Mapping[str, str],
        owner_user_id: UUID,
        created_at: datetime,
        evidence_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.identities = dict(identities)
        self.hashes: dict[str, str] = {}
        self._owner = str(owner_user_id)
        self._created_at = created_at.isoformat()
        self.evidence_ids = evidence_ids

    def text(self, value: str) -> str:
        renamed = _IDENTITY.sub(lambda match: self.identities.get(match[0], match[0]), value)
        return _HASH.sub(lambda match: self.hashes.get(match[0], match[0]), renamed)

    def _internal(self, value: object) -> bool:
        return isinstance(value, str) and any(
            match in self.identities for match in _IDENTITY.findall(value)
        )

    def rewrite(self, node: object) -> object:
        if isinstance(node, Mapping):
            internal_source = self._internal(node.get("source_id"))
            research_source = node.get("source_id") in self.evidence_ids
            if "quote" in node and "start" in node and "source_version" in node:
                return {
                    **node,
                    "source_id": self.identities.get(node["source_id"], node["source_id"]),
                }
            if frozenset(node) == _SOURCE_KEYS and not internal_source:
                return dict(node)
            result: dict[str, object] = {}
            for key, value in node.items():
                if key in _USER_KEYS:
                    result[key] = self._owner
                elif key in _TIME_KEYS:
                    result[key] = self._created_at
                elif key in _VERSION_KEYS:
                    result[key] = IMPORTED_VERSION_NUMBER
                elif key in _LINEAGE_KEYS:
                    result[key] = None
                elif key in {"source_version", "content_hash"} and research_source:
                    result[key] = value
                elif key == "source_version" and internal_source and value is not None:
                    result[key] = IMPORTED_VERSION_NUMBER
                else:
                    result[key] = self.rewrite(value)
            return result
        if isinstance(node, list):
            return _canonical([self.rewrite(item) for item in node])
        if isinstance(node, str):
            return self.text(node)
        return node

    def learn(self, old: object, new: str) -> None:
        if isinstance(old, str) and _HASH.fullmatch(old) is not None and old != new:
            self.hashes[old] = new


def _prototype_identities(prototype: object) -> list[tuple[str, str]]:
    if not isinstance(prototype, Mapping):
        return []
    entries = [(str(prototype["code"]), str(prototype["id"]))]
    for screen in prototype["screens"]:
        entries.append((str(screen["code"]), str(screen["id"])))
        entries.extend(
            (f"{screen['code']}/{element['code']}", str(element["id"]))
            for element in screen["elements"]
        )
    entries.extend(
        (str(transition["code"]), str(transition["id"])) for transition in prototype["transitions"]
    )
    return entries


def _derived_prototype(
    rewriter: _Rewriter, package: Mapping[str, object]
) -> dict[str, object] | None:
    bound = folder_generated_mockup(
        rewriter.rewrite({key: package.get(key) for key in _MOCKUP_KEYS})
    )
    if bound is None:
        return None
    derived = derived_prototype_snapshot(bound)
    before = _prototype_identities(package.get("prototype"))
    after = _prototype_identities(derived)
    if [code for code, _ in before] != [code for code, _ in after]:
        raise mockup_failure(MOCKUP_PROTOTYPE)
    for (_code, old), (_same, new) in zip(before, after, strict=True):
        rewriter.identities[old] = new
    return derived


def _parsed(stage: str, parser: Callable[[Mapping[str, object]], object], payload: object):
    try:
        return parser(payload)
    except (KeyError, TypeError, ValueError) as error:
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_INVALID", f"{stage}: {error}") from error


def _modeling(
    rewriter: _Rewriter,
    document: Mapping[str, object],
    *,
    owner_user_id: UUID,
    created_at: datetime,
) -> UserModelingSnapshotVersion:
    original = document["snapshot"]
    prepared = rewriter.rewrite(document)
    snapshot = prepared["snapshot"]
    for before, persona in zip(
        original["persona_versions"], snapshot["persona_versions"], strict=True
    ):
        profile = _parsed("twins", persona_profile_from_snapshot, persona["profile"])
        persona["content_hash"] = profile.content_hash
        rewriter.learn(before["content_hash"], profile.content_hash)
    for before, twin in zip(original["twin_versions"], snapshot["twin_versions"], strict=True):
        twin["profile"] = rewriter.rewrite(twin["profile"])
        profile = _parsed("twins", user_twin_profile_from_snapshot, twin["profile"])
        twin["content_hash"] = profile.content_hash
        rewriter.learn(before["content_hash"], profile.content_hash)
    snapshot["persona_versions"].sort(key=lambda item: UUID(item["persona_id"]).hex)
    snapshot["twin_versions"].sort(key=lambda item: UUID(item["twin_id"]).hex)
    modeling = _parsed("twins", user_modeling_snapshot_from_snapshot, snapshot)
    rewriter.learn(document["content_hash"], modeling.content_hash)
    return UserModelingSnapshotVersion(
        id=UUID(prepared["id"]),
        project_id=UUID(prepared["project_id"]),
        version_number=IMPORTED_VERSION_NUMBER,
        based_on_version_number=None,
        snapshot=modeling,
        content_hash=modeling.content_hash,
        created_by_user_id=owner_user_id,
        created_at=created_at,
    )


def plan_project_import(
    folder: VerifiedFolder,
    *,
    project_id: UUID,
    brief_version_id: UUID,
    owner_user_id: UUID,
    created_at: datetime,
) -> ProjectImportPlan:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("project import timestamp must be timezone-aware")
    try:
        return _plan(
            folder,
            project_id=project_id,
            brief_version_id=brief_version_id,
            owner_user_id=owner_user_id,
            created_at=created_at,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_INVALID", str(error) or None) from error


def _plan(
    folder: VerifiedFolder,
    *,
    project_id: UUID,
    brief_version_id: UUID,
    owner_user_id: UUID,
    created_at: datetime,
) -> ProjectImportPlan:
    require_complete(folder)
    documents = folder.documents
    if set(documents) != set(STAGES):
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_MISSING")
    old_project = str(documents["brief"]["project_id"])
    old_brief = str(documents["brief"]["id"])
    evidence = (
        json.loads(folder.files[EVIDENCE_DOCUMENT]) if EVIDENCE_DOCUMENT in folder.files else None
    )
    evidence_ids = (
        frozenset(item["id"] for item in evidence["evidence"]) if evidence else frozenset()
    )
    identities = {
        old: str(uuid5(project_id, old))
        for old in sorted((defined_identities(documents) | evidence_ids) - {old_project, old_brief})
    }
    identities[old_project] = str(project_id)
    identities[old_brief] = str(brief_version_id)
    rewriter = _Rewriter(
        identities=identities,
        owner_user_id=owner_user_id,
        created_at=created_at,
        evidence_ids=evidence_ids,
    )

    brief = _parsed("brief", ProjectBrief.from_snapshot, documents["brief"]["brief"])
    if brief.content_hash != documents["brief"]["content_hash"]:
        raise KnowledgeArchiveError("FOLDER_TAMPERED", "brief")

    team_document = rewriter.rewrite(documents["team"])
    proposal = _parsed("team", proposal_from_snapshot, team_document["proposal"])
    rewriter.learn(documents["team"]["content_hash"], proposal.content_hash)
    team = TeamProposalVersion(
        id=UUID(team_document["id"]),
        project_id=project_id,
        version_number=IMPORTED_VERSION_NUMBER,
        proposal=proposal,
        revision_kind=TeamProposalRevisionKind.PROPOSER_GENERATED,
        created_by_user_id=owner_user_id,
        created_at=created_at,
        based_on_version_number=None,
    )

    modeling = _modeling(
        rewriter, documents["twins"], owner_user_id=owner_user_id, created_at=created_at
    )

    requirements_document = rewriter.rewrite(documents["requirements"])
    specification = _parsed(
        "requirements", specification_from_snapshot, requirements_document["specification"]
    )
    rewriter.learn(documents["requirements"]["content_hash"], specification.content_hash)
    requirements = RequirementsSpecificationVersion(
        id=UUID(requirements_document["id"]),
        project_id=project_id,
        version_number=IMPORTED_VERSION_NUMBER,
        based_on_version_number=None,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=owner_user_id,
        created_at=created_at,
    )

    prototype = _derived_prototype(rewriter, documents["design"]["package"])
    design_document = rewriter.rewrite(documents["design"])
    if prototype is not None:
        design_document["package"]["prototype"] = prototype
    package = _parsed("design", design_package_from_snapshot, design_document["package"])
    rewriter.learn(documents["design"]["content_hash"], package.content_hash)
    design = DesignPackageVersion(
        id=UUID(design_document["id"]),
        project_id=project_id,
        version_number=IMPORTED_VERSION_NUMBER,
        based_on_version_number=None,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=owner_user_id,
        created_at=created_at,
    )

    issue = stage_consistency_issue(
        project_id,
        {
            "brief": StageIdentity(
                id=brief_version_id,
                project_id=project_id,
                version_number=IMPORTED_VERSION_NUMBER,
                content_hash=brief.content_hash,
            ),
            "team": team,
            "twins": modeling,
            "requirements": requirements,
            "design": design,
        },
        {
            "team": proposal.to_snapshot(),
            "twins": modeling.snapshot.to_snapshot(),
            "requirements": specification.to_snapshot(),
            "design": package.to_snapshot(),
        },
    )
    if issue is not None:
        raise KnowledgeArchiveError("FOLDER_INCONSISTENT", issue)

    from orchestwin.knowledge.feedback_import import import_feedback

    evaluations, decisions, import_limits = import_feedback(
        folder,
        identities=rewriter.identities,
        hashes=rewriter.hashes,
        project_id=project_id,
        owner_user_id=owner_user_id,
    )
    if "twins/feedback/learned.json" in folder.files:
        import_limits = (*import_limits, "LEARNED_PROJECTION_NOT_RESTORED")
    return ProjectImportPlan(
        origin=folder_origin(folder),
        project_id=project_id,
        project_name=folder.project_name,
        brief_version_id=brief_version_id,
        brief=brief,
        team=team,
        modeling=modeling,
        requirements=requirements,
        design=design,
        identities=dict(rewriter.identities),
        hashes=dict(rewriter.hashes),
        evaluations=evaluations,
        finding_decisions=decisions,
        import_limits=import_limits,
        research_evidence=None
        if evidence is None
        else imported_evidence(
            evidence,
            identities=rewriter.identities,
            project_id=project_id,
            original_twins={
                item["twin_id"]: item["version_number"]
                for item in documents["twins"]["snapshot"]["twin_versions"]
            },
        ),
    )


def imported_evidence(
    document: Mapping[str, object],
    *,
    identities: Mapping[str, str],
    project_id: UUID,
    original_twins: Mapping[str, int] | None = None,
) -> dict[str, object]:
    return {
        "kind": document["kind"],
        "schema_version": document["schema_version"],
        "project_id": str(project_id),
        "evidence": [
            {
                **source,
                "id": identities[source["id"]],
                "text_available": False,
                "imported_from": source.get("imported_from")
                or {
                    "project_id": document["project_id"],
                    "source_id": source["id"],
                    "source_version": source["version"],
                    "content_hash": source["content_hash"],
                },
            }
            for source in document["evidence"]
        ],
        "citations": [
            {
                **item,
                "twin_id": identities.get(item["twin_id"], item["twin_id"]),
                "imported_from": item.get("imported_from")
                or {
                    "project_id": document["project_id"],
                    "twin_id": item["twin_id"],
                    "twin_version": item["twin_version"],
                    "status": item["status"],
                    **(
                        {"mapped_twin_version": IMPORTED_VERSION_NUMBER}
                        if original_twins
                        and original_twins.get(item["twin_id"]) == item["twin_version"]
                        else {}
                    ),
                },
                "citation": {
                    **item["citation"],
                    "source_id": identities[item["citation"]["source_id"]],
                },
            }
            for item in document["citations"]
        ],
    }


def plan_documents(
    plan: ProjectImportPlan,
    *,
    owner_user_id: UUID,
    created_at: datetime,
) -> dict[str, dict[str, object]]:
    def envelope(identity: UUID, content_hash: str, key: str, payload: object, **extra):
        return {
            "id": str(identity),
            "project_id": str(plan.project_id),
            "version_number": IMPORTED_VERSION_NUMBER,
            "content_hash": content_hash,
            "created_by_user_id": str(owner_user_id),
            "created_at": created_at.isoformat(),
            **extra,
            key: payload,
        }

    return {
        "brief": envelope(
            plan.brief_version_id, plan.brief.content_hash, "brief", plan.brief.to_snapshot()
        ),
        "team": envelope(
            plan.team.id,
            plan.team.content_hash,
            "proposal",
            plan.team.proposal.to_snapshot(),
            revision_kind=plan.team.revision_kind.value,
        ),
        "twins": envelope(
            plan.modeling.id,
            plan.modeling.content_hash,
            "snapshot",
            plan.modeling.snapshot.to_snapshot(),
        ),
        "requirements": envelope(
            plan.requirements.id,
            plan.requirements.content_hash,
            "specification",
            plan.requirements.specification.to_snapshot(),
        ),
        "design": envelope(
            plan.design.id,
            plan.design.content_hash,
            "package",
            plan.design.package.to_snapshot(),
        ),
    }


__all__ = [
    "FOLDER_INCOMPLETE",
    "IMPORTED_VERSION_NUMBER",
    "FolderOrigin",
    "ProjectImportPlan",
    "defined_identities",
    "folder_origin",
    "plan_documents",
    "plan_project_import",
    "require_complete",
]
