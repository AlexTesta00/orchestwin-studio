from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import ConfigDict, Field, model_validator

from orchestwin.knowledge.diagrams import DiagramKind
from orchestwin.knowledge.layout import (
    FEEDBACK_LEARNING,
    FEEDBACK_TESTS,
    KNOWLEDGE_FOLDER_KIND,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    STAGES,
    SUPPORTED_SCHEMA_VERSIONS,
)
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    _OPTIONAL,
    _SLUG_PATTERN,
    CommitHash,
    Sha256,
    Timestamp,
    Uuid,
    _Count,
    _Record,
    _Version,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType

_IDENTIFIER_KIND_PATTERN: Final = r"^[A-Z][A-Z_]*$"
_ANY_CODE_PATTERN: Final = r"^[A-Z]+-[0-9]{3,6}$"
_SCHEMA_PATH_PATTERN: Final = r"^schema/[a-z]+\.schema\.json$"
_FEEDBACK_PAIRS: Final = {
    "tests": ["test_runs"],
    "test_runs": ["tests"],
    "learned": ["learned_observations"],
    "learned_observations": ["learned"],
}
_STAGE_ORDER: Final = {"twins": ["team"], "requirements": ["twins"], "design": ["requirements"]}
_MANIFEST_VERSION_RULES: Final = {
    "allOf": [
        {
            "if": {"properties": {"schema_version": {"const": 2}}, "required": ["schema_version"]},
            "then": {"properties": {"stages": {"required": list(STAGES)}}},
        },
        {
            "if": {"properties": {"schema_version": {"const": 3}}, "required": ["schema_version"]},
            "then": {
                "required": ["progress", "state"],
                "properties": {"feedback": {"required": ["changes", "change_reviews"]}},
            },
        },
    ]
}

_AnyCode = Annotated[str, Field(pattern=_ANY_CODE_PATTERN)]


class FolderGenerator(_Record):
    name: str = Field(description="Name of the application that wrote the folder.")
    mermaid_version: str = Field(description="Mermaid version the diagrams are written for.")


class PackageVersion(_Record):
    version_number: _Version = Field(
        description="Version of the knowledge folder of the project, starting at 1."
    )
    content_hash: Sha256 = Field(
        description="SHA-256 digest of the folder content, excluding orchestwin.json and the index."
    )
    created_at: Timestamp = Field(description="When the folder was exported.")


class ProjectIdentity(_Record):
    id: Uuid = Field(description="Identifier of the project.")
    name: str = Field(description="Name of the project.")
    language: str | None = Field(
        description=(
            "ISO 639-1 code of the dominant language of the requirements, or of the brief while "
            "the requirements do not show one, or null."
        )
    )


class GateArtifact(_Record):
    artifact_id: Uuid = Field(description="Version governed by the gate.")
    version: _Version = Field(description="Version number governed by the gate.")
    content_hash: Sha256 = Field(description="SHA-256 digest governed by the gate.")


class GateRecord(_Record):
    id: Uuid = Field(description="Identifier of the human gate.")
    gate_type: Annotated[HumanGateType, _BY_VALUE] = Field(description="Kind of human gate.")
    status: Annotated[HumanGateStatus, _BY_VALUE] = Field(
        description="State of the gate; exported stages are approved."
    )
    iteration: _Version = Field(description="Iteration of the gate, starting at 1.")
    updated_at: Timestamp = Field(description="When the gate last changed state.")
    artifact: GateArtifact = Field(description="Exact artifact version the gate governs.")


class StageEntry(_Record):
    label: str = Field(description="Readable name of the stage.")
    version_id: Uuid = Field(description="Identifier of the approved version.")
    version_number: _Version = Field(description="Version number of the approved artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the approved artifact.")
    document: str = Field(description="Path of the JSON document of the stage.")
    text: str = Field(description="Path of the Markdown text of the stage.")
    gate: GateRecord = Field(description="Human gate that approved the stage.")


class StageEntries(_Record):
    model_config = ConfigDict(json_schema_extra={"dependentRequired": _STAGE_ORDER})

    brief: StageEntry = Field(description="Approved project brief.")
    team: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved agent team, left out while it is not approved."
    )
    twins: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved user modeling, left out while it is not approved."
    )
    requirements: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None,
        description="Approved requirements specification, left out while it is not approved.",
    )
    design: Annotated[StageEntry | None, _OPTIONAL] = Field(
        default=None, description="Approved design package, left out while it is not approved."
    )

    @model_validator(mode="after")
    def _approved_in_order(self) -> StageEntries:
        given = [getattr(self, stage) is not None for stage in STAGES]
        if given != sorted(given, reverse=True):
            raise ValueError("a stage is present only when every stage before it is present")
        return self


class TwinSummary(_Record):
    twin_id: Uuid = Field(description="Stable identifier of the user twin.")
    name: str = Field(description="Display name of the user twin.")
    slug: str = Field(
        pattern=_SLUG_PATTERN, description="Folder name of the twin inside the twins folder."
    )
    version_number: _Version = Field(description="Approved version of the user twin.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that version.")
    validation_status: Annotated[UserTwinLifecycleStatus, _BY_VALUE] = Field(
        description="Lifecycle and validation state of the twin."
    )
    persona_id: Uuid = Field(description="Persona the twin is built on.")
    document: str = Field(description="Path of the portable JSON document of the twin.")
    text: str = Field(description="Path of the Markdown text of the twin.")


class ViewFile(_Record):
    path: str = Field(description="Path of the file inside the folder.")
    title: str = Field(description="Readable title of the file.")


class ViewDiagram(_Record):
    key: str = Field(description="Stable key of the diagram.")
    kind: Annotated[DiagramKind, _BY_VALUE] = Field(description="Kind of Mermaid diagram.")
    subject: str | None = Field(
        description="Code of the item the diagram is about, or null for a whole-stage diagram."
    )
    title: str = Field(description="Readable title of the diagram.")
    path: str = Field(description="Path of the Mermaid file inside the folder.")


class StageViews(_Record):
    text: list[ViewFile] = Field(description="Markdown documents of the stage.")
    tables: list[ViewFile] = Field(description="CSV tables of the stage.")
    diagrams: list[ViewDiagram] = Field(description="Mermaid diagrams of the stage.")
    mockups: list[ViewFile] = Field(description="Static HTML mockups of the stage.")


class FolderViews(_Record):
    requirements: Annotated[StageViews | None, _OPTIONAL] = Field(
        default=None,
        description="Views of the requirements, left out while the requirements are not approved.",
    )
    design: Annotated[StageViews | None, _OPTIONAL] = Field(
        default=None, description="Views of the design, left out while the design is not approved."
    )


class FeedbackSummary(_Record):
    model_config = ConfigDict(json_schema_extra={"dependentRequired": _FEEDBACK_PAIRS})

    folder: str = Field(description="Folder that holds the twin feedback.")
    text: str | None = Field(
        description="Path of the Markdown summary of the feedback, or null without the design."
    )
    reviews_document: str | None = Field(
        description="Path of the reviews document, or null without the design."
    )
    discussions_document: str | None = Field(
        description="Path of the discussions document, or null without the design."
    )
    insights_document: str | None = Field(
        description="Path of the applied insights document, or null without the design."
    )
    reviews: _Count = Field(description="Number of review runs.")
    findings: _Count = Field(description="Number of findings across the review runs.")
    decisions: _Count = Field(description="Number of findings with a current owner decision.")
    discussions: _Count = Field(description="Number of approved discussions.")
    insights: _Count = Field(description="Number of applied insights.")
    changes: Annotated[str | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Path of the document of the twin critiques on the code changes; left out by "
            "folders of schema 2."
        ),
    )
    change_reviews: Annotated[_Count | None, _OPTIONAL] = Field(
        default=None,
        description="Number of review runs on the code changes; left out by folders of schema 2.",
    )
    tests: Annotated[Literal[FEEDBACK_TESTS] | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Path of the document of the acceptance test runs and of the twin critiques on them; "
            "left out, together with test_runs, by folders published before the acceptance tests."
        ),
    )
    test_runs: Annotated[_Count | None, _OPTIONAL] = Field(
        default=None,
        description="Number of acceptance test runs in that document, written together with tests.",
    )
    learned: Annotated[Literal[FEEDBACK_LEARNING] | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Path of the document of what the user twins learned during the development; left "
            "out, together with learned_observations, by folders without the user twins and by "
            "folders published before the twins could learn."
        ),
    )
    learned_observations: Annotated[_Count | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Number of active learned observations of every twin in that document, written "
            "together with learned."
        ),
    )

    @model_validator(mode="after")
    def _documents_with_their_count(self) -> FeedbackSummary:
        if (self.tests is None) != (self.test_runs is None):
            raise ValueError("tests and test_runs are written together or both left out")
        if (self.learned is None) != (self.learned_observations is None):
            raise ValueError(
                "learned and learned_observations are written together or both left out"
            )
        return self


class ProgressEntry(_Record):
    approved: list[Literal[STAGES]] = Field(
        description="Approved stages the folder holds, in stage order."
    )
    pending: Literal[STAGES] | None = Field(
        description="First stage that is not approved yet, or null when every stage is approved."
    )
    complete: bool = Field(description="True when the five stages are approved.")


class StateEntry(_Record):
    document: str = Field(description="Path of the JSON document of the development state.")
    text: str = Field(description="Path of the Markdown text of the development state.")
    changes: _Count = Field(description="Number of recorded changes.")
    pending_changes: _Count = Field(description="Number of changes after the aligned point.")
    stale_reviews: Annotated[_Count | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Number of changes after the aligned point whose latest review is stale; left out by "
            "folders published before the reviews could become stale."
        ),
    )
    aligned_commit: CommitHash | None = Field(
        description="Commit of the aligned point, or null before any."
    )
    open_tasks: _Count = Field(description="Number of open tasks for the code.")


class StableIdentifier(_Record):
    stage: Literal[STAGES] = Field(description="Stage the item belongs to.")
    kind: str = Field(
        pattern=_IDENTIFIER_KIND_PATTERN,
        description="Kind of item, such as REQUIREMENT, USER_STORY or PROTOTYPE_SCREEN.",
    )
    scope: _AnyCode | None = Field(
        description="Code of the enclosing item for nested items, or null."
    )
    code: _AnyCode = Field(description="Human-readable code of the item, unique in its scope.")
    id: Uuid = Field(description="Stable identifier of the item.")


class WhyEntry(_Record):
    document: Literal["traceability/why.json"]
    schema_version: Literal[1]


class KnowledgeManifest(_Record):
    model_config = ConfigDict(json_schema_extra=_MANIFEST_VERSION_RULES)

    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description=(
            "Version of the knowledge folder format: 3 holds the approved stages so far and the "
            "development state, 2 holds the five stages."
        )
    )
    kind: Literal[KNOWLEDGE_FOLDER_KIND] = Field(
        description="Kind of document, a knowledge folder."
    )
    manifest: Literal[KNOWLEDGE_MANIFEST] = Field(description="Path of this manifest.")
    index: Literal[KNOWLEDGE_INDEX] = Field(
        description="Path of the Markdown index that explains the folder."
    )
    generator: FolderGenerator = Field(description="Application that wrote the folder.")
    package: PackageVersion = Field(description="Version and digest of the folder.")
    project: ProjectIdentity = Field(description="Project the folder describes.")
    stages: StageEntries = Field(
        description=(
            "Approved version of every approved stage; a stage appears only after the stages "
            "before it."
        )
    )
    progress: Annotated[ProgressEntry | None, _OPTIONAL] = Field(
        default=None,
        description="Approved stages and the next one; left out by folders of schema 2.",
    )
    state: Annotated[StateEntry | None, _OPTIONAL] = Field(
        default=None,
        description=(
            "Where the development state is and a summary of it; left out by folders of schema 2."
        ),
    )
    twins: list[TwinSummary] = Field(description="Portable user twins of the folder.")
    views: FolderViews = Field(
        description="Texts, tables, diagrams and mockups of the approved requirements and design."
    )
    feedback: FeedbackSummary = Field(description="Where the twin feedback is and how much.")
    identifiers: list[StableIdentifier] = Field(
        description="Code and identifier of every approved requirement and design item."
    )
    schemas: dict[str, Annotated[str, Field(pattern=_SCHEMA_PATH_PATTERN)]] = Field(
        description="Path of the JSON Schema of every document kind, keyed by schema name."
    )
    files: dict[str, Sha256] = Field(
        description="SHA-256 digest of every file, except orchestwin.json and the index."
    )
    why: Annotated[WhyEntry | None, _OPTIONAL] = None
    workflow_inputs: Annotated[dict[str, object] | None, _OPTIONAL] = None

    @model_validator(mode="after")
    def _fits_its_version(self) -> KnowledgeManifest:
        if self.schema_version == 2:
            if any(getattr(self.stages, stage) is None for stage in STAGES):
                raise ValueError("a folder of schema 2 holds the five stages")
            return self
        if self.progress is None or self.state is None:
            raise ValueError("a folder of schema 3 states its progress and its development state")
        if self.feedback.changes is None or self.feedback.change_reviews is None:
            raise ValueError("a folder of schema 3 states where its change critiques are")
        return self
