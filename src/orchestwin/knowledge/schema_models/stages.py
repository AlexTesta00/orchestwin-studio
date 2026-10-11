from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from orchestwin.agents.proposals import TeamProposalRevisionKind
from orchestwin.knowledge.layout import SUPPORTED_SCHEMA_VERSIONS, TWIN_DOCUMENT_KIND
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    _OPTIONAL,
    _SLUG_PATTERN,
    ApprovedVersionReference,
    Sha256,
    Timestamp,
    Uuid,
    _Record,
    _Version,
)
from orchestwin.knowledge.schema_models.brief import BriefSnapshot
from orchestwin.knowledge.schema_models.design import DesignPackageSnapshot
from orchestwin.knowledge.schema_models.requirements import (
    RequirementsSpecificationSnapshot,
    RequirementsSpecificationSnapshot2,
)
from orchestwin.knowledge.schema_models.team import TeamProposalSnapshot
from orchestwin.knowledge.schema_models.twins import (
    PersonaVersion,
    UserModelingSnapshot,
    UserTwinVersion,
)


class _StageDocument(_Record):
    id: Uuid = Field(description="Identifier of the approved version.")
    project_id: Uuid = Field(description="Project the version belongs to.")
    version_number: _Version = Field(description="Version number of the stage artifact.")
    content_hash: Sha256 = Field(
        description="SHA-256 digest of the stage content approved at the human gate."
    )
    created_by_user_id: Uuid = Field(description="User who created the version.")
    created_at: Timestamp = Field(description="When the version was created.")


class _RevisedStageDocument(_StageDocument):
    based_on_version_number: Annotated[_Version | None, _OPTIONAL] = Field(
        default=None,
        description="Earlier version that this version revises, left out when there is none.",
    )


class BriefDocument(_StageDocument):
    brief: BriefSnapshot = Field(description="Content of the approved project brief.")


class TeamDocument(_RevisedStageDocument):
    revision_kind: Annotated[TeamProposalRevisionKind, _BY_VALUE] = Field(
        description="Whether the proposer generated the version or the owner edited it."
    )
    proposal: TeamProposalSnapshot = Field(description="Content of the approved team proposal.")


class TwinsDocument(_RevisedStageDocument):
    snapshot: UserModelingSnapshot = Field(
        description="Content of the approved user modeling: personas and user twins."
    )


class RequirementsDocument(_RevisedStageDocument):
    specification: Annotated[
        RequirementsSpecificationSnapshot | RequirementsSpecificationSnapshot2,
        Field(discriminator="schema_version"),
    ] = Field(description="Content of the approved requirements specification.")


class DesignDocument(_RevisedStageDocument):
    package: DesignPackageSnapshot = Field(description="Content of the approved design package.")


class TwinOrigin(_Record):
    project_id: Uuid = Field(description="Project the twin comes from.")
    project_name: str = Field(description="Name of that project.")
    user_modeling: ApprovedVersionReference = Field(
        description="Approved user modeling version that contains the twin."
    )
    approved_at: Timestamp = Field(description="When the owner approved that user modeling.")


class TwinDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[TWIN_DOCUMENT_KIND] = Field(description="Kind of document, a portable user twin.")
    slug: str = Field(
        pattern=_SLUG_PATTERN, description="Folder name of the twin inside the twins folder."
    )
    origin: TwinOrigin = Field(description="Project and approval the twin comes from.")
    persona: PersonaVersion = Field(description="Confirmed persona version the twin is built on.")
    twin: UserTwinVersion = Field(description="The approved user twin version.")
