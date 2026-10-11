from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.artifacts.design_evaluation import DESIGN_EVALUATION_SCHEMA_VERSION
from orchestwin.artifacts.design_finding_validations import FindingDecision
from orchestwin.evaluation.artifacts import EvaluationArtifactModality
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.knowledge.feedback import REVIEWS_KIND
from orchestwin.knowledge.layout import SUPPORTED_SCHEMA_VERSIONS
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    ApprovedVersionReference,
    Sha256,
    Timestamp,
    Uuid,
    _code,
    _Confidence,
    _Record,
    _Version,
)

_FINDING_CONFIDENCE_SEMANTICS: Final = "MODEL_SELF_ASSESSMENT_UNLESS_CALIBRATED"


class EvaluatorConfiguration(_Record):
    evaluator_id: str = Field(description="Identifier of the evaluator.")
    evaluator_version: str = Field(description="Version of the evaluator.")
    model_config_ref: str = Field(description="Reference to the model configuration in use.")
    prompt_version_ref: str = Field(description="Reference to the prompt version in use.")


class SyntheticFinding(_Record):
    finding_id: str = Field(
        pattern=_code("UTF"),
        description="Code of the finding inside the response of its twin, like UTF-001.",
    )
    twin_id: Uuid = Field(description="User twin that produced the finding.")
    twin_version: _Version = Field(description="Version of that user twin.")
    artifact_id: Uuid = Field(description="Artifact the finding is about.")
    artifact_version: _Version = Field(description="Version of that artifact.")
    location: str = Field(description="Place in the artifact the finding refers to.")
    summary: str = Field(description="One-line summary of the finding.")
    rationale: str = Field(description="Reasoning behind the finding.")
    criterion: Annotated[SyntheticFindingCriterion, _BY_VALUE] = Field(
        description="User-centred design criterion the finding is about."
    )
    severity: Annotated[SyntheticFindingSeverity, _BY_VALUE] = Field(
        description="Impact of the finding on the user twin."
    )
    epistemic_status: Annotated[SyntheticFindingEpistemicStatus, _BY_VALUE] = Field(
        description="Epistemic status of the finding at the weakest defensible level."
    )
    evidence_refs: list[str] = Field(description="Evidence the finding cites, in order.")
    confidence: _Confidence = Field(description="Model confidence, between 0 and 1.")
    confidence_semantics: Literal[_FINDING_CONFIDENCE_SEMANTICS] = Field(
        description="States that the confidence is a model self-assessment, not calibrated."
    )
    recommended_action: str = Field(description="Change the user twin recommends.")
    requires_human_validation: bool = Field(
        description="True when a person has to validate the finding."
    )
    model_config_ref: str = Field(description="Reference to the model configuration in use.")
    prompt_version_ref: str = Field(description="Reference to the prompt version in use.")
    is_simulated_feedback: Literal[True] = Field(
        description="Always true: the finding is simulated feedback, not empirical evidence."
    )
    content_hash: Sha256 = Field(description="SHA-256 digest of the finding content.")


class TwinEvaluationResponse(_Record):
    evaluation_run_id: Uuid = Field(description="Review run the response belongs to.")
    artifact_bundle_id: Uuid = Field(description="Artifact bundle the twin inspected.")
    artifact_bundle_hash: Sha256 = Field(description="SHA-256 digest of that artifact bundle.")
    twin_id: Uuid = Field(description="User twin that answered.")
    twin_version: _Version = Field(description="Version of that user twin.")
    evaluator: EvaluatorConfiguration = Field(description="Evaluator that produced the answer.")
    findings: list[SyntheticFinding] = Field(description="Findings of the twin, in code order.")
    summary: str = Field(description="Overall judgement of the twin.")
    evidence_gaps: list[str] = Field(description="Evidence the twin missed, in alphabetical order.")
    is_simulated_feedback: Literal[True] = Field(
        description="Always true: the response is simulated feedback, not empirical evidence."
    )
    completed_at: Timestamp = Field(description="When the twin completed the response.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the response content.")
    disclaimer: str = Field(description="Methodological disclaimer shown next to the response.")


class EvaluationBundle(_Record):
    id: Uuid = Field(description="Identifier of the artifact bundle.")
    project_id: Uuid = Field(description="Project the bundle belongs to.")
    workflow_run_id: Uuid = Field(description="Design version the bundle was built from.")
    scenario: dict[str, object] = Field(
        description=(
            "Task given to the twins with its name, locale and expected outcomes; an open object."
        )
    )
    artifacts: list[dict[str, object]] = Field(
        description=(
            "Exact artifacts the twins inspected, each with kind, modality, media type, digest "
            "and location; open objects."
        )
    )
    modalities: list[Annotated[EvaluationArtifactModality, _BY_VALUE]] = Field(
        description="Distinct modalities of the artifacts, in alphabetical order."
    )
    is_multimodal: bool = Field(description="True when the artifacts span several modalities.")
    created_at: Timestamp = Field(description="When the bundle was created.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the bundle content.")


class EvaluationRun(_Record):
    schema_version: Literal[DESIGN_EVALUATION_SCHEMA_VERSION] = Field(
        description="Version of the review run format."
    )
    id: Uuid = Field(description="Identifier of the review run.")
    project_id: Uuid = Field(description="Project the run belongs to.")
    owner_user_id: Uuid = Field(description="Owner who started the run.")
    design_version_id: Uuid = Field(description="Design version that was reviewed.")
    design_version_number: _Version = Field(description="Version number of that design.")
    design_content_hash: Sha256 = Field(description="SHA-256 digest of that design version.")
    alternative_id: Uuid = Field(description="Selected design alternative that was reviewed.")
    alternative_code: str = Field(
        pattern=_code("DES"), description="Code of that design alternative, like DES-001."
    )
    bundle: EvaluationBundle = Field(description="Exact artifacts the twins inspected.")
    responses: list[TwinEvaluationResponse] = Field(
        description="One response for every reviewing twin."
    )
    started_at: Timestamp = Field(description="When the run started.")
    completed_at: Timestamp = Field(description="When the run completed.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the run content.")


class OwnerFindingDecision(_Record):
    evaluation_run_id: Uuid = Field(description="Review run that contains the finding.")
    twin_id: Uuid = Field(description="User twin that produced the finding.")
    finding_id: str = Field(pattern=_code("UTF"), description="Code of the finding, like UTF-001.")
    sequence_number: _Version = Field(
        description="Order of this decision among the decisions on the same finding."
    )
    project_id: Uuid = Field(description="Project the decision belongs to.")
    owner_user_id: Uuid = Field(description="Owner who decided.")
    decision: Annotated[FindingDecision, _BY_VALUE] = Field(
        description="Whether the owner confirmed or dismissed the finding."
    )
    note: str | None = Field(description="Owner's note on the decision, or null.")
    decided_at: Timestamp = Field(description="When the owner decided.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the decision content.")


class ReviewsDocument(_Record):
    schema_version: Literal[SUPPORTED_SCHEMA_VERSIONS] = Field(
        description="Version of the knowledge folder format."
    )
    kind: Literal[REVIEWS_KIND] = Field(description="Kind of document, the twin reviews.")
    project_id: Uuid = Field(description="Project the reviews belong to.")
    design: ApprovedVersionReference = Field(
        description="Approved design version exported in the same folder."
    )
    runs: list[EvaluationRun] = Field(description="Review runs in the order they started.")
    decisions: list[OwnerFindingDecision] = Field(
        description="Every owner decision on the findings of those runs."
    )
