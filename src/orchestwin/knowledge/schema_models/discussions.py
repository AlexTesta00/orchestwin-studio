from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.artifacts.design_discussion import (
    PROPOSAL_CODE_PREFIX,
    DiscussionProposalTarget,
    DiscussionStance,
    DiscussionStatus,
    ReactionVerdict,
)
from orchestwin.knowledge.feedback import DISCUSSIONS_KIND
from orchestwin.knowledge.layout import SUPPORTED_SCHEMA_VERSIONS
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    _OPTIONAL,
    ApprovedVersionReference,
    Sha256,
    Timestamp,
    Uuid,
    _code,
    _Confidence,
    _Record,
    _Version,
)

_TWIN_OBSERVATION_KEY_PATTERN: Final = r"^user_twin\.[a-z_]+$"


class TwinReaction(_Record):
    twin_id: Uuid = Field(description="User twin whose statement is answered.")
    verdict: Annotated[ReactionVerdict, _BY_VALUE] = Field(
        description="Whether the speaker agrees with that statement."
    )
    reason: str = Field(description="Why the speaker reacts that way.")


class TwinStatement(_Record):
    twin_id: Uuid = Field(description="User twin that speaks.")
    twin_version: _Version = Field(description="Version of that user twin.")
    twin_name: str = Field(description="Display name of that user twin.")
    stance: Annotated[DiscussionStance, _BY_VALUE] = Field(
        description="Position of the twin on the alternative."
    )
    statement: str = Field(description="What the twin says.")
    replies_to: list[Uuid] = Field(description="User twins the statement answers.")
    proposals: list[str] = Field(description="Changes the twin proposes.")
    grounded_on: list[Annotated[str, Field(pattern=_TWIN_OBSERVATION_KEY_PATTERN)]] = Field(
        description="Observation keys of the twin profile the statement relies on."
    )
    confidence: _Confidence = Field(description="Model confidence, between 0 and 1.")
    model_generation_id: Uuid = Field(description="Model generation that produced the statement.")
    reactions: Annotated[list[TwinReaction] | None, _OPTIONAL] = Field(
        default=None,
        description="Reactions to the statements of other twins, left out when there is none.",
    )
    answer_to_owner: Annotated[str | None, _OPTIONAL] = Field(
        default=None,
        description="Answer to the owner's note of the round, left out when there is none.",
    )


class ConflictPosition(_Record):
    twin_id: Uuid = Field(description="User twin that holds the position.")
    position: str = Field(description="Position of that twin on the topic.")


class SynthesisConflict(_Record):
    topic: str = Field(description="Topic the twins disagree on.")
    positions: list[ConflictPosition] = Field(description="Position of each twin involved.")


class SynthesisProposal(_Record):
    code: str = Field(
        pattern=_code(PROPOSAL_CODE_PREFIX),
        description="Code of the proposal inside its round, like PRP-001.",
    )
    text: str = Field(description="Proposed change.")
    target: Annotated[DiscussionProposalTarget, _BY_VALUE] = Field(
        description="Artifact the change applies to."
    )
    supported_by: list[Uuid] = Field(description="User twins that support the proposal.")


class DiscussionSynthesis(_Record):
    agreements: list[str] = Field(description="Points the twins agree on.")
    conflicts: list[SynthesisConflict] = Field(description="Points the twins disagree on.")
    proposals: list[SynthesisProposal] = Field(description="Changes proposed in the round.")
    questions_for_owner: list[str] = Field(description="Questions the twins ask the owner.")
    model_generation_id: Uuid = Field(description="Model generation that wrote the synthesis.")


class DiscussionRound(_Record):
    ordinal: _Version = Field(description="Position of the round, starting at 1.")
    owner_note: str | None = Field(description="Note the owner gave the twins, or null.")
    created_at: Timestamp = Field(description="When the round was held.")
    statements: list[TwinStatement] = Field(description="One statement for every twin.")
    synthesis: DiscussionSynthesis = Field(description="Synthesis of the round.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the round content.")


class DesignDiscussion(_Record):
    id: Uuid = Field(description="Identifier of the discussion.")
    project_id: Uuid = Field(description="Project the discussion belongs to.")
    owner_user_id: Uuid = Field(description="Owner who opened the discussion.")
    design_version_id: Uuid = Field(description="Design version that was discussed.")
    design_version_number: _Version = Field(description="Version number of that design.")
    design_content_hash: Sha256 = Field(description="SHA-256 digest of that design version.")
    alternative_id: Uuid = Field(description="Design alternative that was discussed.")
    alternative_code: str = Field(
        pattern=_code("DES"), description="Code of that design alternative, like DES-001."
    )
    status: Annotated[DiscussionStatus, _BY_VALUE] = Field(
        description="State of the discussion; exported discussions are approved."
    )
    created_at: Timestamp = Field(description="When the discussion was opened.")
    decided_at: Timestamp | None = Field(
        description="When the owner decided on the discussion, or null while it is open."
    )
    max_rounds: _Version = Field(description="Largest number of rounds a discussion can hold.")
    rounds: list[DiscussionRound] = Field(description="Rounds in order.")


class DiscussionsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[DISCUSSIONS_KIND] = Field(description="Kind of document, the twin discussions.")
    project_id: Uuid = Field(description="Project the discussions belong to.")
    design: ApprovedVersionReference = Field(
        description="Approved design version exported in the same folder."
    )
    discussions: list[DesignDiscussion] = Field(
        description="Approved discussions in the order they were opened."
    )
