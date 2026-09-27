from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_evaluation import (
    design_review_anchors,
    design_review_view,
    evaluation_bundle,
    evaluation_document,
    evaluation_reference,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.evaluation.proposer_evaluator import (
    CRITERIA,
    INSTRUCTION,
    INVALID_TWIN_REVIEW_OUTPUT,
    MAX_FINDINGS,
    QUESTIONS,
    SEVERITIES,
    TWIN_REVIEW_EVALUATOR_ID,
    TWIN_REVIEW_EVALUATOR_VERSION,
    TWIN_REVIEW_OUTPUT_TOKENS,
    TWIN_REVIEW_PROMPT_VERSION,
    TWIN_REVIEW_PURPOSE,
    TWIN_REVIEW_TASK,
    ProposerDesignTwinReviewer,
    twin_review_output_type,
    twin_review_view,
)
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

from ..artifacts import design_fixtures
from ..models.test_model_proposals import make_generator

NOW = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000000931")
MODEL_HASH = "c" * 64
ANCHORS = ("SCR-001", "SCR-001/ELM-001")
TWIN_REFERENCE = f"user-twin:{design_fixtures.TWIN_ID}:v2"
ARTIFACT_REFERENCE = f"artifact:{design_fixtures.PROTOTYPE_ID}:v1"


def observation(key, value, status=EpistemicStatus.USER_PROVIDED):
    inferred = status is EpistemicStatus.MODEL_INFERRED
    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=status,
        confidence=ConfidenceScore(0.8),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.PROJECT_BRIEF,
                    source_id="brief-version",
                    source_version=1,
                    locator=key,
                    summary="Approved project brief.",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.REQUIRED
        if inferred
        else HumanValidationRequirement.NOT_REQUIRED,
        rationale="Inferred from the approved brief." if inferred else None,
    ).to_snapshot()


OBSERVATIONS = (
    observation("user_twin.role", ObservationValue.from_text("Hotel receptionist")),
    observation("user_twin.age_range", ObservationValue.unknown()),
    observation(
        "user_twin.goals",
        ObservationValue.from_items(("Register guests quickly", "Avoid double bookings")),
        EpistemicStatus.MODEL_INFERRED,
    ),
    observation("user_twin.expertise", ObservationValue.abstained("The brief is silent.")),
)


def profile(snapshot):
    return EvaluationUserTwinProfile(
        twin_id=design_fixtures.TWIN_ID,
        version_number=2,
        name="Hotel Receptionist Twin",
        lifecycle_status=UserTwinLifecycleStatus.PROJECT_GROUNDED_UT,
        content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        snapshot_json=snapshot,
    )


def twin(observations=OBSERVATIONS):
    return profile(
        canonical_json({"name": "Hotel Receptionist Twin", "observations": list(observations)})
    )


def default_bundle():
    version = design_fixtures.design_version()
    document = evaluation_document(version, language="en")
    return evaluation_bundle(version, document, locale="en-US", created_at=NOW)


def request(evaluated=None, *, bundle=None):
    version = design_fixtures.design_version()
    return UserTwinEvaluationRequest(
        evaluation_run_id=RUN_ID,
        project_id=version.project_id,
        workflow_run_id=version.id,
        artifact_bundle=bundle or default_bundle(),
        twin=evaluated or twin(),
        evidence=(),
        requested_at=NOW,
    )


class FakeGenerator:
    def __init__(self, *outputs, max_output_tokens=8192):
        self.outputs = list(outputs)
        self.calls = []
        self.configuration = SimpleNamespace(
            identity=SimpleNamespace(content_hash=MODEL_HASH), max_output_tokens=max_output_tokens
        )

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["output_type"].model_validate(self.outputs.pop(0))


def reviewer(generator):
    version = design_fixtures.design_version()
    return ProposerDesignTwinReviewer(
        generator,
        design_view=design_review_view(version),
        anchors=design_review_anchors(version),
        clock=lambda: NOW,
    )


def finding(anchor="SCR-001/ELM-001", **changes):
    return {
        "anchor": anchor,
        "concern": "The guest name field gives no format hint.",
        "grounds": "At a busy desk I cannot guess the expected name format.",
        "profile_keys": ["user_twin.role"],
        "quality_criterion": "comprehensibility",
        "recommended_action": "Show the expected format below the field.",
        "self_confidence": 0.7,
        "severity": "major",
        **changes,
    }


def output(*findings, gaps=(), unable=False, assessment="The flow suits my desk work."):
    return {
        "assessment": assessment,
        "evidence_gaps": list(gaps),
        "findings": list(findings),
        "unable_to_assess": unable,
    }


def evaluate(generator, evaluation_request=None):
    return asyncio.run(reviewer(generator).evaluate(evaluation_request or request()))


class MemoryEvidence:
    def __init__(self):
        self.events = []

    async def begin(self, **kwargs):
        raise AssertionError("the reviewer must not begin a generation")

    async def append(self, **kwargs):
        self.events.append(kwargs)


def evaluate_in_scope(scope, generator):
    async def run():
        token = _SCOPE.set(scope)
        try:
            return await reviewer(generator).evaluate(request())
        finally:
            _SCOPE.reset(token)

    return asyncio.run(run())


def active_scope():
    generation = SimpleNamespace(request_id=uuid4(), content_hash="e" * 64)
    scope = ProposalEvidenceScope(
        MemoryEvidence(), design_fixtures.OWNER_ID, design_fixtures.PROJECT_ID, request=generation
    )
    return scope, generation


def test_twin_view_keeps_the_known_observations_without_provenance():
    view = twin_review_view(request())
    assert view == {
        "twin_id": str(design_fixtures.TWIN_ID),
        "version_number": 2,
        "name": "Hotel Receptionist Twin",
        "observations": {
            "user_twin.role": {"value": "Hotel receptionist", "epistemic_status": "USER_PROVIDED"},
            "user_twin.goals": {
                "value": ["Register guests quickly", "Avoid double bookings"],
                "epistemic_status": "MODEL_INFERRED",
            },
        },
    }
    assert list(view["observations"]) == ["user_twin.role", "user_twin.goals"]
    serialized = json.dumps(view)
    assert "provenance" not in serialized and "brief-version" not in serialized
    assert "rationale" not in serialized and "confidence" not in serialized


@pytest.mark.parametrize(
    "snapshot",
    [
        canonical_json({"name": "Twin", "observations": [OBSERVATIONS[1], OBSERVATIONS[3]]}),
        canonical_json({"name": "Twin"}),
        canonical_json(
            {
                "observations": [
                    {"observation_key": "user_twin.role", "value": {"kind": "TEXT", "text": ""}},
                    {"observation_key": "user_twin.goals", "value": {"kind": "ITEMS", "items": []}},
                    {"observation_key": "user_twin.expertise", "value": None},
                ]
            }
        ),
        "[]",
    ],
)
def test_twin_view_requires_at_least_one_known_observation(snapshot):
    with pytest.raises(ValueError, match="at least one known profile observation"):
        twin_review_view(request(profile(snapshot)))


def test_output_type_constrains_anchors_profile_keys_criteria_and_bounds():
    keys = ("user_twin.role", "user_twin.goals")
    schema = twin_review_output_type(ANCHORS, keys).model_json_schema()
    item = schema["$defs"]["TwinReviewFinding"]
    properties = item["properties"]
    assert properties["anchor"]["enum"] == list(ANCHORS)
    assert properties["profile_keys"]["items"]["enum"] == list(keys)
    profile_keys = properties["profile_keys"]
    assert (profile_keys["minItems"], profile_keys["maxItems"]) == (1, 4)
    assert properties["quality_criterion"]["enum"] == list(CRITERIA)
    assert list(CRITERIA) == [value.value for value in SyntheticFindingCriterion]
    assert properties["severity"]["enum"] == list(SEVERITIES)
    assert list(SEVERITIES) == [value.value for value in SyntheticFindingSeverity]
    confidence = properties["self_confidence"]
    assert (confidence["minimum"], confidence["maximum"]) == (0, 1)
    assert [
        (properties[name]["minLength"], properties[name]["maxLength"])
        for name in ("concern", "grounds", "recommended_action")
    ] == [(1, 300), (1, 600), (1, 400)]
    assert sorted(item["required"]) == sorted(properties)
    assert item["additionalProperties"] is False
    top = schema["properties"]
    assert (top["assessment"]["minLength"], top["assessment"]["maxLength"]) == (1, 900)
    gaps = top["evidence_gaps"]
    assert gaps["maxItems"] == 4
    assert (gaps["items"]["minLength"], gaps["items"]["maxLength"]) == (1, 300)
    assert top["findings"]["maxItems"] == MAX_FINDINGS == 6
    assert sorted(schema["required"]) == [
        "assessment",
        "evidence_gaps",
        "findings",
        "unable_to_assess",
    ]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"findings": [finding(anchor="SCR-009")]},
        {"findings": [finding(profile_keys=["user_twin.goals"])]},
        {"findings": [finding(profile_keys=[])]},
        {"findings": [finding(profile_keys=["user_twin.role"] * 5)]},
        {"findings": [finding(quality_criterion="beauty")]},
        {"findings": [finding(severity="blocker")]},
        {"findings": [finding(self_confidence=1.2)]},
        {"findings": [finding(self_confidence=-0.1)]},
        {"findings": [finding(concern="")]},
        {"findings": [finding(concern="x" * 301)]},
        {"findings": [finding(grounds="x" * 601)]},
        {"findings": [finding(recommended_action="x" * 401)]},
        {"findings": [finding(note="extra")]},
        {"findings": [finding()] * 7},
        {"evidence_gaps": ["gap"] * 5},
        {"evidence_gaps": ["x" * 301]},
        {"evidence_gaps": [""]},
        {"assessment": ""},
        {"assessment": "x" * 901},
        {"unable_to_assess": "false"},
        {"verdict": "extra"},
    ],
)
def test_output_type_rejects_values_outside_the_contract(change):
    output_type = twin_review_output_type(ANCHORS, ("user_twin.role",))
    output_type.model_validate(output(finding(), gaps=("A gap.",)))
    with pytest.raises(ValidationError):
        output_type.model_validate({**output(finding()), **change})


def test_output_type_and_reviewer_require_anchors_and_profile_keys():
    with pytest.raises(ValueError, match="requires anchors and profile keys"):
        twin_review_output_type((), ("user_twin.role",))
    with pytest.raises(ValueError, match="requires anchors and profile keys"):
        twin_review_output_type(ANCHORS, ())
    with pytest.raises(ValueError, match="anchors of the mockup"):
        ProposerDesignTwinReviewer(FakeGenerator(), design_view={}, anchors={})


def test_reviewer_identifies_itself_by_the_proposer_model():
    assert reviewer(FakeGenerator()).configuration.to_snapshot() == {
        "evaluator_id": TWIN_REVIEW_EVALUATOR_ID,
        "evaluator_version": TWIN_REVIEW_EVALUATOR_VERSION,
        "model_config_ref": MODEL_HASH,
        "prompt_version_ref": TWIN_REVIEW_PROMPT_VERSION,
    }
    assert (TWIN_REVIEW_EVALUATOR_ID, TWIN_REVIEW_EVALUATOR_VERSION) == (
        "proposer-design-twin-review",
        "1.0.0",
    )
    assert TWIN_REVIEW_PROMPT_VERSION == "s22-design-twin-review-v2"


def test_reviewer_sends_the_design_the_twin_the_criteria_and_the_questions():
    version = design_fixtures.design_version()
    generator = FakeGenerator(output())
    evaluated = request()
    evaluate(generator, evaluated)
    [call] = generator.calls
    assert call["task"] == TWIN_REVIEW_TASK == "user-twin-evaluation"
    assert call["instruction"] == INSTRUCTION
    assert call["max_output_tokens"] == TWIN_REVIEW_OUTPUT_TOKENS == 3072
    document = evaluation_document(version, language="en")
    assert call["context"] == {
        "project_id": str(version.project_id),
        "purpose": TWIN_REVIEW_PURPOSE,
        "scenario": {
            "name": "Guided reservation flow",
            "task": "Create a reservation",
            "locale": "en-US",
            "expected_outcomes": ["Review availability.", "Save the reservation."],
        },
        "user_twin": twin_review_view(evaluated),
        "design": design_review_view(version),
        "artifact": {
            "artifact_id": str(design_fixtures.PROTOTYPE_ID),
            "version": 1,
            "location": "design/mockup.html",
            "sha256": document.reference.sha256_digest,
        },
        "criteria": list(CRITERIA),
        "questions": list(QUESTIONS),
    }
    assert json.loads(json.dumps(call["context"])) == call["context"]
    properties = call["output_type"].model_json_schema()["$defs"]["TwinReviewFinding"]["properties"]
    assert properties["anchor"]["enum"] == list(design_review_anchors(version))
    assert properties["profile_keys"]["items"]["enum"] == ["user_twin.role", "user_twin.goals"]
    bounded = FakeGenerator(output(), max_output_tokens=2048)
    evaluate(bounded)
    assert bounded.calls[0]["max_output_tokens"] == 2048


def test_reviewer_needs_exactly_one_mockup_document():
    bundle = default_bundle()
    specification = next(
        item
        for item in bundle.artifacts
        if item.kind is EvaluationArtifactKind.DESIGN_SPECIFICATION
    )
    extra = evaluation_reference(
        artifact_id=design_fixtures.PROTOTYPE_ID,
        version_number=1,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        content=b"<p>Another page</p>",
        location="design/other.html",
    )
    for artifacts in ((specification,), (*bundle.artifacts, extra)):
        broken = create_evaluation_artifact_bundle(
            project_id=bundle.project_id,
            workflow_run_id=bundle.workflow_run_id,
            scenario=bundle.scenario,
            artifacts=artifacts,
            created_at=NOW,
        )
        generator = FakeGenerator(output())
        with pytest.raises(ValueError, match="exactly one mockup document"):
            evaluate(generator, request(bundle=broken))
        assert generator.calls == []


def test_reviewer_binds_findings_to_anchors_the_twin_evidence_and_the_artifact():
    bundle = default_bundle()
    generator = FakeGenerator(
        output(
            finding(
                concern="The guest name field\n gives  no format hint.",
                grounds="  At a busy desk I cannot guess the format. ",
                profile_keys=["user_twin.goals", "user_twin.role", "user_twin.role"],
                self_confidence=0.456,
            ),
            finding(
                anchor="SCR-002",
                quality_criterion="trust",
                severity="minor",
                self_confidence=1,
                recommended_action="Name  the next step.",
            ),
            gaps=(
                "Timing  cannot be judged.",
                "Colours are not visible in a static mockup.",
                "Timing cannot be judged.",
            ),
            assessment="  The flow suits\nmy desk work. ",
        )
    )
    response = evaluate(generator, request(bundle=bundle))
    first, second = response.findings
    assert [item.finding_id for item in response.findings] == ["UTF-001", "UTF-002"]
    assert first.location == "SCR-001 Create reservation · ELM-001 Guest name"
    assert second.location == "SCR-002 Reservation confirmation"
    assert first.summary == "The guest name field gives no format hint."
    assert first.rationale == "At a busy desk I cannot guess the format."
    assert first.recommended_action == "Show the expected format below the field."
    assert second.recommended_action == "Name the next step."
    assert first.evidence_refs == (
        ARTIFACT_REFERENCE,
        f"{TWIN_REFERENCE}#user_twin.goals",
        f"{TWIN_REFERENCE}#user_twin.role",
    )
    assert second.evidence_refs == (ARTIFACT_REFERENCE, f"{TWIN_REFERENCE}#user_twin.role")
    assert (first.confidence, second.confidence) == (0.46, 1.0)
    assert (first.criterion, first.severity) == (
        SyntheticFindingCriterion.COMPREHENSIBILITY,
        SyntheticFindingSeverity.MAJOR,
    )
    assert (second.criterion, second.severity) == (
        SyntheticFindingCriterion.TRUST,
        SyntheticFindingSeverity.MINOR,
    )
    for item in response.findings:
        assert item.epistemic_status is SyntheticFindingEpistemicStatus.MODEL_INFERRED
        assert item.requires_human_validation is True
        assert (item.twin_id, item.twin_version) == (design_fixtures.TWIN_ID, 2)
        assert (item.artifact_id, item.artifact_version) == (design_fixtures.PROTOTYPE_ID, 1)
        assert (item.model_config_ref, item.prompt_version_ref) == (
            MODEL_HASH,
            TWIN_REVIEW_PROMPT_VERSION,
        )
    assert response.summary == "The flow suits my desk work."
    assert response.evidence_gaps == (
        "Colours are not visible in a static mockup.",
        "Timing cannot be judged.",
    )
    assert response.completed_at == NOW
    assert response.evaluation_run_id == RUN_ID
    assert (response.artifact_bundle_id, response.artifact_bundle_hash) == (
        bundle.id,
        bundle.content_hash,
    )
    assert (response.twin_id, response.twin_version) == (design_fixtures.TWIN_ID, 2)
    assert response.evaluator == reviewer(generator).configuration


def test_reviewer_accepts_no_findings_and_a_justified_abstention():
    quiet = evaluate(FakeGenerator(output()))
    assert (quiet.findings, quiet.evidence_gaps) == ((), ())
    abstained = evaluate(
        FakeGenerator(output(gaps=("The mockup shows nothing I can relate to.",), unable=True))
    )
    assert abstained.findings == ()
    assert abstained.evidence_gaps == ("The mockup shows nothing I can relate to.",)


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (
            output(finding(), gaps=("Nothing to judge.",), unable=True),
            "must not report findings",
        ),
        (output(unable=True), "must explain the gap"),
        (output(finding(concern="   ")), "summary must not be empty"),
        (output(assessment="   "), "summary must not be empty"),
        (output(gaps=("   ",)), "evidence gap must not be empty"),
    ],
)
def test_reviewer_rejects_inconsistent_or_blank_output(value, reason):
    with pytest.raises(ProposalGenerationError) as failure:
        evaluate(FakeGenerator(value))
    assert failure.value.code == INVALID_TWIN_REVIEW_OUTPUT
    assert isinstance(failure.value.__cause__, ValueError)
    assert reason in str(failure.value.__cause__)


def test_reviewer_records_the_accepted_review_in_the_active_evidence_scope():
    scope, generation = active_scope()
    response = evaluate_in_scope(scope, FakeGenerator(output(finding())))
    assert scope.store.events == [
        {
            "generation_id": generation.request_id,
            "owner_user_id": design_fixtures.OWNER_ID,
            "project_id": design_fixtures.PROJECT_ID,
            "kind": "ADAPTER_ACCEPTED",
            "payload": {
                "result": response.to_snapshot(),
                "generated_content_hashes": {"DESIGN_TWIN_REVIEW": [response.content_hash]},
            },
            "raw_body": None,
        }
    ]
    assert scope.observed_events == {"ADAPTER_ACCEPTED"}


def test_reviewer_records_a_rejected_review_and_ignores_an_idle_scope():
    scope, _generation = active_scope()
    with pytest.raises(ProposalGenerationError):
        evaluate_in_scope(scope, FakeGenerator(output(finding(), gaps=("Gap.",), unable=True)))
    assert [(event["kind"], event["payload"]) for event in scope.store.events] == [
        (
            "ADAPTER_REJECTED",
            {
                "code": "ValueError",
                "reason": "a twin that cannot assess the design must not report findings",
            },
        )
    ]
    idle = ProposalEvidenceScope(
        MemoryEvidence(), design_fixtures.OWNER_ID, design_fixtures.PROJECT_ID
    )
    response = evaluate_in_scope(idle, FakeGenerator(output(finding())))
    assert [item.finding_id for item in response.findings] == ["UTF-001"]
    assert idle.store.events == []


def test_output_contract_passes_the_audited_proposal_generator(tmp_path):
    generator, transport = make_generator(
        tmp_path, output(finding(), gaps=("Colours are hidden.",))
    )
    response = asyncio.run(reviewer(generator).evaluate(request()))
    assert [item.location for item in response.findings] == [
        "SCR-001 Create reservation · ELM-001 Guest name"
    ]
    assert response.evidence_gaps == ("Colours are hidden.",)
    assert response.evaluator.model_config_ref == generator.configuration.identity.content_hash
    [call] = transport.calls
    payload = call["payload"]
    assert payload["max_tokens"] == TWIN_REVIEW_OUTPUT_TOKENS
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-user-twin-evaluation-v1"
    assert payload["messages"][0]["content"].endswith(INSTRUCTION)
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["$defs"]["TwinReviewFinding"]["properties"]["anchor"]["enum"] == list(
        design_review_anchors(design_fixtures.design_version())
    )
    context = json.loads(payload["messages"][1]["content"])["context"]
    assert context["purpose"] == TWIN_REVIEW_PURPOSE
    assert sorted(context["user_twin"]["observations"]) == ["user_twin.goals", "user_twin.role"]
