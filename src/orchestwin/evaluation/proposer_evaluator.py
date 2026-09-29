from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from orchestwin.artifacts.design_evaluation import anchor_finding
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.models.hosted_configuration import HOSTED_PROVIDER_KINDS
from orchestwin.models.proposal_evidence import current_proposal_evidence, retain_adapter_result
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_discussion import NAMES_INSTEAD_OF_CODES

TWIN_REVIEW_TASK: Final = "user-twin-evaluation"
TWIN_REVIEW_PURPOSE: Final = "DESIGN_TWIN_REVIEW"
TWIN_REVIEW_EVALUATOR_ID: Final = "proposer-design-twin-review"
TWIN_REVIEW_EVALUATOR_VERSION: Final = "1.0.0"
TWIN_REVIEW_PROMPT_VERSION: Final = "s22-design-twin-review-v2"
HOSTED_TWIN_REVIEW_PROMPT_VERSION: Final = "s24-design-twin-review-v3"
TWIN_REVIEW_OUTPUT_TOKENS: Final = 3072
INVALID_TWIN_REVIEW_OUTPUT: Final = "INVALID_TWIN_REVIEW_OUTPUT"
MAX_FINDINGS: Final = 6
MAX_EVIDENCE_GAPS: Final = 4
MAX_PROFILE_KEYS: Final = 4
MAX_ASSESSMENT_LENGTH: Final = 900
MAX_CONCERN_LENGTH: Final = 300
MAX_GROUNDS_LENGTH: Final = 600
MAX_ACTION_LENGTH: Final = 400
MAX_GAP_LENGTH: Final = 300
CRITERIA: Final = tuple(item.value for item in SyntheticFindingCriterion)
SEVERITIES: Final = tuple(item.value for item in SyntheticFindingSeverity)
QUESTIONS: Final = (
    "What would you try to do first with this interface?",
    "Which information is missing to complete your task?",
    "Which part of the workflow is unclear?",
    "Would this design reduce or increase your workload?",
    "What could make the results difficult to trust?",
    "Which accessibility barrier would stop you?",
    "Does the flow match the way you actually do this task?",
    "Do the colours, the typography, the density and the controls suit you and your context?",
)
INSTRUCTION: Final = (
    "You are the User Twin described in user_twin: a synthetic representative of one user "
    "group, grounded only in the approved observations in user_twin.observations. design holds "
    "the design alternative chosen by the owner: its summary, its workflows, its visual "
    "language and the screens of its mockup with every element. Review the mockup from your "
    "role while trying to complete scenario.task, and answer for yourself the questions in "
    "questions. Write every text in the language of scenario.locale. assessment is a short "
    "first-person account of how this design would work for you. findings holds at most six "
    "problems or risks that you see, the most important first: report only what would really "
    "affect you, because a few well grounded findings are worth more than many weak ones, and "
    "use critical or major only for what would stop you or lead you to a wrong result. Each "
    "finding has: anchor, the "
    "exact screen or element it concerns, chosen among the allowed values; concern, what is "
    "wrong or missing, in one or two sentences; grounds, why it matters to you, citing what "
    "the mockup shows or omits and the profile observations that make it relevant; "
    "profile_keys, the observation keys it derives from; quality_criterion, one value of "
    "criteria; recommended_action, one concrete change to the design; self_confidence, between "
    "0 and 1, reflecting how directly the profile and the mockup support the finding; "
    "severity, one of critical, major, moderate, minor or observation. Judge the design and "
    "never the format of the evidence: do not ask for more files, more HTML or the exact "
    "element. The mockup is static and its sample values, such as names, numbers or texts "
    "introduced by a word like example, only illustrate the content: never report that a value "
    "is an example, that it is not real or that it does not update. Report only what the "
    "screens show or omit, including workflow steps and states "
    "that no screen covers; never invent controls, data or behaviour, never claim to be a real "
    "person and never present a finding as validated. When nothing relevant is wrong for you, "
    "return no findings. evidence_gaps lists what you cannot judge from a static mockup. "
    "unable_to_assess is true only when the design gives you nothing to judge: in that case "
    "findings is empty and evidence_gaps explains why. Findings are design hypotheses for the "
    "team to verify with real users."
)
HOSTED_INSTRUCTION: Final = f"{INSTRUCTION} {NAMES_INSTEAD_OF_CODES}"


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _normalized(value: object, *, maximum: int) -> str:
    text = " ".join(str(value).split())
    return text[:maximum].rstrip() if len(text) > maximum else text


def twin_review_route(generator):
    return generator.route(TWIN_REVIEW_TASK, TWIN_REVIEW_PURPOSE)


def hosted_twin_review(generator) -> bool:
    return twin_review_route(generator).configuration.provider_kind in HOSTED_PROVIDER_KINDS


def twin_review_view(request: UserTwinEvaluationRequest) -> dict[str, object]:
    profile = json.loads(request.twin.snapshot_json)
    observations: dict[str, object] = {}
    for item in profile.get("observations", ()) if isinstance(profile, dict) else ():
        value = item.get("value") or {}
        if value.get("kind") == "TEXT" and value.get("text"):
            known: object = value["text"]
        elif value.get("kind") == "ITEMS" and value.get("items"):
            known = list(value["items"])
        else:
            continue
        observations[str(item["observation_key"])] = {
            "value": known,
            "epistemic_status": item.get("epistemic_status"),
        }
    if not observations:
        raise ValueError("twin review requires at least one known profile observation")
    return {
        "twin_id": str(request.twin.twin_id),
        "version_number": request.twin.version_number,
        "name": request.twin.name,
        "observations": observations,
    }


def twin_review_output_type(anchors: tuple[str, ...], profile_keys: tuple[str, ...]):
    if not anchors or not profile_keys:
        raise ValueError("twin review requires anchors and profile keys")
    finding = create_model(
        "TwinReviewFinding",
        __base__=_Output,
        anchor=(Literal[anchors], ...),
        concern=(str, Field(min_length=1, max_length=MAX_CONCERN_LENGTH)),
        grounds=(str, Field(min_length=1, max_length=MAX_GROUNDS_LENGTH)),
        profile_keys=(
            list[Literal[profile_keys]],
            Field(min_length=1, max_length=MAX_PROFILE_KEYS),
        ),
        quality_criterion=(Literal[CRITERIA], ...),
        recommended_action=(str, Field(min_length=1, max_length=MAX_ACTION_LENGTH)),
        self_confidence=(float, Field(ge=0, le=1)),
        severity=(Literal[SEVERITIES], ...),
    )
    return create_model(
        "TwinReviewOutput",
        __base__=_Output,
        assessment=(str, Field(min_length=1, max_length=MAX_ASSESSMENT_LENGTH)),
        evidence_gaps=(
            list[Annotated[str, Field(min_length=1, max_length=MAX_GAP_LENGTH)]],
            Field(max_length=MAX_EVIDENCE_GAPS),
        ),
        findings=(list[finding], Field(max_length=MAX_FINDINGS)),
        unable_to_assess=(bool, ...),
    )


class ProposerDesignTwinReviewer:
    def __init__(
        self,
        generator,
        *,
        design_view: Mapping[str, object],
        anchors: Mapping[str, str],
        clock=None,
    ) -> None:
        if not anchors:
            raise ValueError("twin review requires the anchors of the mockup")
        self._generator = generator
        self._hosted = hosted_twin_review(generator)
        self._design_view = dict(design_view)
        self._anchors = dict(anchors)
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def configuration(self) -> UserTwinEvaluatorConfiguration:
        return UserTwinEvaluatorConfiguration(
            evaluator_id=TWIN_REVIEW_EVALUATOR_ID,
            evaluator_version=TWIN_REVIEW_EVALUATOR_VERSION,
            model_config_ref=twin_review_route(self._generator).configuration.identity.content_hash,
            prompt_version_ref=HOSTED_TWIN_REVIEW_PROMPT_VERSION
            if self._hosted
            else TWIN_REVIEW_PROMPT_VERSION,
        )

    def context(self, request: UserTwinEvaluationRequest) -> dict[str, object]:
        bundle = request.artifact_bundle
        document = self._document(request)
        scenario = bundle.scenario
        return {
            "project_id": str(request.project_id),
            "purpose": TWIN_REVIEW_PURPOSE,
            "scenario": {
                "name": scenario.name,
                "task": scenario.task,
                "locale": scenario.locale,
                "expected_outcomes": list(scenario.expected_outcomes),
            },
            "user_twin": twin_review_view(request),
            "design": self._design_view,
            "artifact": {
                "artifact_id": str(document.artifact_id),
                "version": document.version_number,
                "location": document.location,
                "sha256": document.sha256_digest,
            },
            "criteria": list(CRITERIA),
            "questions": list(QUESTIONS),
        }

    async def evaluate(self, request: UserTwinEvaluationRequest) -> UserTwinEvaluationResponse:
        context = self.context(request)
        profile_keys = tuple(context["user_twin"]["observations"])
        ceiling = twin_review_route(self._generator).configuration.max_output_tokens
        output = await self._generator.generate(
            task=TWIN_REVIEW_TASK,
            context=context,
            output_type=twin_review_output_type(tuple(self._anchors), profile_keys),
            max_output_tokens=min(TWIN_REVIEW_OUTPUT_TOKENS, ceiling),
            instruction=HOSTED_INSTRUCTION if self._hosted else INSTRUCTION,
            retry_schema_errors=False,
        )
        try:
            response = self._bind(request, output)
        except (TypeError, ValueError) as error:
            await retain_adapter_result(error=error, reason=str(error))
            raise ProposalGenerationError(INVALID_TWIN_REVIEW_OUTPUT) from error
        scope = current_proposal_evidence()
        if scope is not None:
            await scope.event(
                "ADAPTER_ACCEPTED",
                {
                    "result": response.to_snapshot(),
                    "generated_content_hashes": {"DESIGN_TWIN_REVIEW": [response.content_hash]},
                    **(
                        {"related_generations": list(scope.related_generations)}
                        if scope.related_generations
                        else {}
                    ),
                },
            )
        return response

    @staticmethod
    def _document(request: UserTwinEvaluationRequest):
        documents = [
            item
            for item in request.artifact_bundle.artifacts
            if item.kind is EvaluationArtifactKind.DOM_SNAPSHOT
        ]
        if len(documents) != 1:
            raise ValueError("twin review requires exactly one mockup document")
        return documents[0]

    def _bind(self, request: UserTwinEvaluationRequest, output) -> UserTwinEvaluationResponse:
        if output.unable_to_assess and output.findings:
            raise ValueError("a twin that cannot assess the design must not report findings")
        document = self._document(request)
        configuration = self.configuration
        twin = request.twin
        artifact_reference = f"artifact:{document.artifact_id}:v{document.version_number}"
        findings = tuple(
            anchor_finding(
                create_synthetic_finding(
                    finding_id=f"UTF-{index:03d}",
                    twin_id=twin.twin_id,
                    twin_version=twin.version_number,
                    artifact_id=document.artifact_id,
                    artifact_version=document.version_number,
                    location=_normalized(self._anchors[item.anchor], maximum=500),
                    summary=_normalized(item.concern, maximum=1000),
                    rationale=_normalized(item.grounds, maximum=4000),
                    criterion=SyntheticFindingCriterion(item.quality_criterion),
                    severity=SyntheticFindingSeverity(item.severity),
                    epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
                    evidence_refs=tuple(
                        sorted(
                            {
                                artifact_reference,
                                *(
                                    f"user-twin:{twin.twin_id}:v{twin.version_number}#{key}"
                                    for key in item.profile_keys
                                ),
                            }
                        )
                    ),
                    confidence=round(float(item.self_confidence), 2),
                    recommended_action=_normalized(item.recommended_action, maximum=2000),
                    requires_human_validation=True,
                    model_config_ref=configuration.model_config_ref,
                    prompt_version_ref=configuration.prompt_version_ref,
                ),
                item.anchor,
            )
            for index, item in enumerate(output.findings, 1)
        )
        gaps = sorted({_normalized(item, maximum=1000) for item in output.evidence_gaps})
        if output.unable_to_assess and not gaps:
            raise ValueError("a twin that cannot assess the design must explain the gap")
        summary = _normalized(output.assessment, maximum=4000)
        return UserTwinEvaluationResponse(
            evaluation_run_id=request.evaluation_run_id,
            artifact_bundle_id=request.artifact_bundle.id,
            artifact_bundle_hash=request.artifact_bundle.content_hash,
            twin_id=twin.twin_id,
            twin_version=twin.version_number,
            evaluator=configuration,
            findings=findings,
            summary=summary,
            evidence_gaps=tuple(gaps),
            completed_at=self._clock(),
            content_hash=user_twin_evaluation_response_hash(
                evaluation_run_id=request.evaluation_run_id,
                artifact_bundle_id=request.artifact_bundle.id,
                artifact_bundle_hash=request.artifact_bundle.content_hash,
                twin_id=twin.twin_id,
                twin_version=twin.version_number,
                evaluator=configuration,
                findings=findings,
                summary=summary,
                evidence_gaps=tuple(gaps),
            ),
        )


__all__ = [
    "CRITERIA",
    "HOSTED_INSTRUCTION",
    "HOSTED_TWIN_REVIEW_PROMPT_VERSION",
    "INSTRUCTION",
    "INVALID_TWIN_REVIEW_OUTPUT",
    "MAX_FINDINGS",
    "QUESTIONS",
    "SEVERITIES",
    "TWIN_REVIEW_EVALUATOR_ID",
    "TWIN_REVIEW_EVALUATOR_VERSION",
    "TWIN_REVIEW_OUTPUT_TOKENS",
    "TWIN_REVIEW_PROMPT_VERSION",
    "TWIN_REVIEW_PURPOSE",
    "TWIN_REVIEW_TASK",
    "ProposerDesignTwinReviewer",
    "hosted_twin_review",
    "twin_review_output_type",
    "twin_review_route",
    "twin_review_view",
]
