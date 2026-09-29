from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from orchestwin.agents.persistence.repositories import proposal_from_snapshot
from orchestwin.agents.proposals import TeamProposalRevisionKind, TeamProposalVersion
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.knowledge.layout import STAGE_PAYLOAD_KEYS
from orchestwin.projects.briefs import ProjectBrief, ProjectBriefVersion
from orchestwin.projects.requirements_persistence import specification_from_snapshot
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.persistence.snapshots import user_modeling_snapshot_from_snapshot
from orchestwin.twins.user_twins import UserModelingSnapshotVersion


class StageDocumentError(ValueError):
    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


def _envelope(stage: str, document: Mapping[str, object]) -> dict[str, object]:
    try:
        return {
            "id": UUID(str(document["id"])),
            "project_id": UUID(str(document["project_id"])),
            "version_number": int(document["version_number"]),
            "created_by_user_id": UUID(str(document["created_by_user_id"])),
            "created_at": datetime.fromisoformat(str(document["created_at"])),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise StageDocumentError(stage, str(error)) from error


def _payload(stage: str, document: Mapping[str, object], parser: Callable[[object], object]):
    try:
        return parser(document[STAGE_PAYLOAD_KEYS[stage]])
    except (KeyError, TypeError, ValueError) as error:
        raise StageDocumentError(stage, str(error)) from error


def _built(stage: str, build: Callable[[], object]):
    try:
        return build()
    except (KeyError, TypeError, ValueError) as error:
        raise StageDocumentError(stage, str(error)) from error


def brief_version_from_document(document: Mapping[str, object]) -> ProjectBriefVersion:
    envelope = _envelope("brief", document)
    brief = _payload("brief", document, ProjectBrief.from_snapshot)
    return _built(
        "brief",
        lambda: ProjectBriefVersion(
            schema_version=brief.SCHEMA_VERSION,
            brief=brief,
            content_hash=str(document["content_hash"]),
            **envelope,
        ),
    )


def team_version_from_document(document: Mapping[str, object]) -> TeamProposalVersion:
    envelope = _envelope("team", document)
    proposal = _payload("team", document, proposal_from_snapshot)

    def build() -> TeamProposalVersion:
        version = TeamProposalVersion(
            proposal=proposal,
            revision_kind=TeamProposalRevisionKind(str(document["revision_kind"])),
            based_on_version_number=document.get("based_on_version_number"),
            **envelope,
        )
        if version.content_hash != document["content_hash"]:
            raise ValueError("team proposal hash does not match its content")
        return version

    return _built("team", build)


def modeling_version_from_document(
    document: Mapping[str, object],
) -> UserModelingSnapshotVersion:
    envelope = _envelope("twins", document)
    snapshot = _payload("twins", document, user_modeling_snapshot_from_snapshot)
    return _built(
        "twins",
        lambda: UserModelingSnapshotVersion(
            snapshot=snapshot,
            content_hash=str(document["content_hash"]),
            based_on_version_number=document.get("based_on_version_number"),
            **envelope,
        ),
    )


def requirements_version_from_document(
    document: Mapping[str, object],
) -> RequirementsSpecificationVersion:
    envelope = _envelope("requirements", document)
    specification = _payload("requirements", document, specification_from_snapshot)
    return _built(
        "requirements",
        lambda: RequirementsSpecificationVersion(
            specification=specification,
            content_hash=str(document["content_hash"]),
            based_on_version_number=document.get("based_on_version_number"),
            **envelope,
        ),
    )


def design_version_from_document(document: Mapping[str, object]) -> DesignPackageVersion:
    envelope = _envelope("design", document)
    package = _payload("design", document, design_package_from_snapshot)
    return _built(
        "design",
        lambda: DesignPackageVersion(
            package=package,
            content_hash=str(document["content_hash"]),
            based_on_version_number=document.get("based_on_version_number"),
            **envelope,
        ),
    )


STAGE_READERS = {
    "brief": brief_version_from_document,
    "team": team_version_from_document,
    "twins": modeling_version_from_document,
    "requirements": requirements_version_from_document,
    "design": design_version_from_document,
}


def stage_versions(documents: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    return {
        stage: reader(documents[stage])
        for stage, reader in STAGE_READERS.items()
        if stage in documents
    }


__all__ = [
    "STAGE_READERS",
    "StageDocumentError",
    "brief_version_from_document",
    "design_version_from_document",
    "modeling_version_from_document",
    "requirements_version_from_document",
    "stage_versions",
    "team_version_from_document",
]
