import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model

from orchestwin.evaluation.artifact_content import project_axe_report
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.execution_bundle import artifact_reference_id, normalized_text
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.proposal_evidence import current_proposal_evidence

TWIN_EVALUATION_TASK = "user-twin-evaluation"
EVALUATOR_ID = "proposer-user-twin-evaluator"
EVALUATOR_VERSION = "1.0.0"
PROMPT_VERSION = "s18-proposer-twin-evaluation-v1"
MAX_FINDINGS = 8
MAX_EVIDENCE_GAPS = 6
MAX_DOM_CHARACTERS = 6000
MAX_OUTPUT_TOKENS = 4096
CRITERIA = tuple(item.value for item in SyntheticFindingCriterion)
SEVERITIES = tuple(item.value for item in SyntheticFindingSeverity)
QUESTIONS = (
    "What would you try to do first with this interface?",
    "Which information is missing to complete your task?",
    "Which part of the workflow is unclear?",
    "Would this feature reduce or increase your workload?",
    "What could make the results difficult to trust?",
    "Which accessibility barrier would stop you?",
    "Does the flow match the way you actually do this task?",
)
INSTRUCTION = (
    "You are the User Twin described in user_twin.profile: a synthetic representative of one user group, "
    "grounded only in that approved profile. The artifacts are the executed prototype as observed in a sandbox: "
    "DOM snapshots of each screen, accessibility reports and screenshots metadata. Inspect them from your role and answer "
    "the questions in questions for yourself, in the language of the profile and the scenario. "
    "Return a short first-person summary of how the prototype would work for you, then up to eight findings, each bound to one "
    "artifact_id from artifacts, with the exact location on that screen, a summary, a rationale grounded in the profile "
    "observations and the artifact content, one criterion from criteria, a severity (critical, major, moderate, minor or observation), "
    "a confidence between 0 and 1 that reflects how directly the profile and the artifact support it, a concrete recommended_action, "
    "and evidence_refs chosen from evidence_references. Report only what the artifacts show or omit: never invent controls, "
    "data or behaviour, never claim to be a real person and never present a finding as validated. When the artifacts are "
    "insufficient for a question, write it in evidence_gaps instead of guessing. Findings are design hypotheses for the "
    "team to verify with real users. Return the structured output only."
)
_SCRIPT_BLOCKS = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_GAPS = re.compile(r">\s+<")


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def dom_text(raw):
    text = raw.decode("utf-8", errors="replace")
    text = _SCRIPT_BLOCKS.sub(" ", text)
    text = _TAG_GAPS.sub("><", text)
    text = " ".join(text.split())
    if len(text) > MAX_DOM_CHARACTERS:
        return text[:MAX_DOM_CHARACTERS] + " [truncated]"
    return text


def evaluation_output_type(artifact_ids, evidence_ids):
    finding = create_model(
        "TwinEvaluationFinding",
        __base__=_Output,
        artifact_id=(Literal[tuple(artifact_ids)], ...),
        location=(str, Field(min_length=1, max_length=500)),
        summary=(str, Field(min_length=1, max_length=1000)),
        rationale=(str, Field(min_length=1, max_length=1500)),
        criterion=(Literal[CRITERIA], ...),
        severity=(Literal[SEVERITIES], ...),
        confidence=(float, Field(ge=0, le=1)),
        recommended_action=(str, Field(min_length=1, max_length=800)),
        evidence_refs=(list[Literal[tuple(evidence_ids)]], Field(max_length=4)),
    )
    return create_model(
        "TwinEvaluationOutput",
        __base__=_Output,
        summary=(str, Field(min_length=1, max_length=2000)),
        findings=(list[finding], Field(max_length=MAX_FINDINGS)),
        evidence_gaps=(
            list[Annotated[str, Field(min_length=1, max_length=500)]],
            Field(max_length=MAX_EVIDENCE_GAPS),
        ),
        abstained=(bool, ...),
    )


class ProposerUserTwinEvaluator:
    def __init__(self, generator, *, read_content, clock=None):
        self._generator = generator
        self._read_content = read_content
        self._clock = clock or (lambda: datetime.now(UTC))
        self._pending = None

    @property
    def configuration(self):
        return UserTwinEvaluatorConfiguration(
            evaluator_id=EVALUATOR_ID,
            evaluator_version=EVALUATOR_VERSION,
            model_config_ref=self._generator.configuration.identity.content_hash,
            prompt_version_ref=PROMPT_VERSION,
        )

    async def evaluate(self, request):
        bundle = request.artifact_bundle
        artifacts = [self._artifact_entry(reference) for reference in bundle.artifacts]
        evidence_ids = tuple(item.reference_id for item in request.evidence)
        scenario = bundle.scenario
        context = {
            "project_id": str(request.project_id),
            "purpose": "SYNTHETIC_EVALUATION",
            "scenario": {
                "name": scenario.name,
                "task": scenario.task,
                "locale": scenario.locale,
                "expected_outcomes": list(scenario.expected_outcomes),
            },
            "user_twin": {
                "twin_id": str(request.twin.twin_id),
                "version_number": request.twin.version_number,
                "name": request.twin.name,
                "profile": json.loads(request.twin.snapshot_json),
            },
            "artifacts": artifacts,
            "evidence_references": list(evidence_ids),
            "criteria": list(CRITERIA),
            "questions": list(QUESTIONS),
        }
        await self._rotate_evidence()
        output = await self._generator.generate(
            task=TWIN_EVALUATION_TASK,
            context=context,
            output_type=evaluation_output_type(
                tuple(str(reference.artifact_id) for reference in bundle.artifacts), evidence_ids
            ),
            max_output_tokens=min(
                MAX_OUTPUT_TOKENS, self._generator.configuration.max_output_tokens
            ),
            instruction=INSTRUCTION,
        )
        configuration = self.configuration
        references = {str(reference.artifact_id): reference for reference in bundle.artifacts}
        findings = tuple(
            create_synthetic_finding(
                finding_id=f"UTF-{index:03d}",
                twin_id=request.twin.twin_id,
                twin_version=request.twin.version_number,
                artifact_id=UUID(item.artifact_id),
                artifact_version=references[item.artifact_id].version_number,
                location=normalized_text(item.location, maximum=500),
                summary=normalized_text(item.summary, maximum=1000),
                rationale=normalized_text(item.rationale, maximum=4000),
                criterion=SyntheticFindingCriterion(item.criterion),
                severity=SyntheticFindingSeverity(item.severity),
                epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
                evidence_refs=tuple(
                    sorted(
                        {artifact_reference_id(references[item.artifact_id]), *item.evidence_refs}
                    )
                ),
                confidence=round(float(item.confidence), 2),
                recommended_action=normalized_text(item.recommended_action, maximum=2000),
                requires_human_validation=True,
                model_config_ref=configuration.model_config_ref,
                prompt_version_ref=configuration.prompt_version_ref,
            )
            for index, item in enumerate(output.findings, 1)
        )
        gaps = sorted({normalized_text(item, maximum=1000) for item in output.evidence_gaps})
        if output.abstained and not gaps:
            gaps = ["The evaluator abstained because the artifacts were insufficient."]
        summary = normalized_text(output.summary, maximum=4000)
        response = UserTwinEvaluationResponse(
            evaluation_run_id=request.evaluation_run_id,
            artifact_bundle_id=bundle.id,
            artifact_bundle_hash=bundle.content_hash,
            twin_id=request.twin.twin_id,
            twin_version=request.twin.version_number,
            evaluator=configuration,
            findings=findings,
            summary=summary,
            evidence_gaps=tuple(gaps),
            completed_at=self._clock(),
            content_hash=user_twin_evaluation_response_hash(
                evaluation_run_id=request.evaluation_run_id,
                artifact_bundle_id=bundle.id,
                artifact_bundle_hash=bundle.content_hash,
                twin_id=request.twin.twin_id,
                twin_version=request.twin.version_number,
                evaluator=configuration,
                findings=findings,
                summary=summary,
                evidence_gaps=tuple(gaps),
            ),
        )
        self._pending = response
        return response

    def _artifact_entry(self, reference):
        entry = {
            "artifact_id": str(reference.artifact_id),
            "version": reference.version_number,
            "kind": reference.kind.value,
            "location": reference.location,
            "reference_id": artifact_reference_id(reference),
        }
        if reference.kind is EvaluationArtifactKind.DOM_SNAPSHOT:
            entry["content"] = dom_text(
                self._read_content(reference.storage_key, reference.size_bytes)
            )
        elif reference.kind is EvaluationArtifactKind.AXE_REPORT:
            raw = self._read_content(reference.storage_key, reference.size_bytes)
            try:
                entry["content"] = project_axe_report(raw)
            except ValueError as error:
                entry["content"] = {"unavailable": "AXE_REPORT_UNPROJECTABLE", "reason": str(error)}
        return entry

    async def _rotate_evidence(self):
        scope = current_proposal_evidence()
        pending = self._pending
        self._pending = None
        if scope is None or scope.request is None or pending is None:
            return
        await scope.event(
            "ADAPTER_ACCEPTED",
            {
                "result": pending.to_snapshot(),
                "generated_content_hashes": {"SYNTHETIC_EVALUATION": [pending.content_hash]},
            },
        )
        await scope.event("APPLICATION_RESULT", {"status": "TWIN_EVALUATED"})
        scope.retire(role="TWIN_EVALUATION", code="TWIN_EVALUATED")
