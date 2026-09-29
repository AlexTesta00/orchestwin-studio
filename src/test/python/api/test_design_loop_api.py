from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from orchestwin.api import design_loop
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_loop import (
    DesignEvaluationMode,
    DesignEvaluationRequest,
    DesignEvaluationResult,
    DesignEvaluationStatus,
    DesignLoopApplication,
)
from orchestwin.artifacts.design_evaluation import (
    HOSTED_DOCUMENT_BYTES,
    DesignEvaluationRun,
    design_review_anchors,
    design_review_view,
    evaluation_document,
    finding_anchor_key,
)
from orchestwin.artifacts.design_static_check import (
    STATIC_PROFILE_CONSTRAINT,
    static_check_scope,
    static_check_target,
)
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.evaluation.proposer_evaluator import TWIN_REVIEW_EVALUATOR_ID, TWIN_REVIEW_TASK
from orchestwin.models.proposal_evidence import begin_model_generation
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
)
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
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_package_extension import extended_package, large_bound

CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="fake-design-evaluator",
    evaluator_version="1",
    model_config_ref="config-1",
    prompt_version_ref="prompt-1",
)
SECOND_TWIN_ID = UUID("00000000-0000-4000-8000-000000000061")
MODEL_HASH = "c" * 64


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class MemoryRuns:
    runs: ClassVar[list[DesignEvaluationRun]] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def create(self, run):
        MemoryRuns.runs.append(run)
        return design_loop.DesignEvaluationWriteStatus.WRITTEN

    async def list(self, *, project_id, limit=50):
        items = [run for run in MemoryRuns.runs if run.project_id == project_id]
        return tuple(reversed(items))[:limit]


class NoValidations:
    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def current(self, *, project_id):
        return ()


class MemoryTwins:
    references: ClassVar[dict[UUID, UserTwinVersionReference]] = {}

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, twin_id, version_number):
        reference = MemoryTwins.references.get(twin_id)
        if reference is None:
            return None
        return SimpleNamespace(
            twin_id=twin_id,
            version_number=version_number,
            content_hash=reference.content_hash,
            profile=SimpleNamespace(name=reference.name),
        )


def stub_profile(version, snapshot):
    return EvaluationUserTwinProfile(
        twin_id=version.twin_id,
        version_number=version.version_number,
        name=version.profile.name,
        lifecycle_status=next(iter(UserTwinLifecycleStatus)),
        content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        snapshot_json=snapshot,
    )


class StubProfile:
    @staticmethod
    def from_version(version):
        return stub_profile(version, '{"name": "' + version.profile.name + '"}')


OBSERVATIONS = (
    ProfileObservation(
        observation_key="user_twin.role",
        value=ObservationValue.from_text("Hotel receptionist"),
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(0.9),
        provenance=ObservationProvenance.from_references(
            (EvidenceReference(source_kind=EvidenceSourceKind.PROJECT_BRIEF, source_id="brief"),)
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    ).to_snapshot(),
    ProfileObservation(
        observation_key="user_twin.goals",
        value=ObservationValue.unknown(),
        epistemic_status=EpistemicStatus.MODEL_INFERRED,
        confidence=ConfidenceScore(0.4),
        provenance=ObservationProvenance.from_references(
            (EvidenceReference(source_kind=EvidenceSourceKind.MODEL_OUTPUT, source_id="model"),)
        ),
        human_validation=HumanValidationRequirement.REQUIRED,
        rationale="The brief does not state the goals.",
    ).to_snapshot(),
)


class ObservedProfile:
    @staticmethod
    def from_version(version):
        snapshot = canonical_json(
            {"name": version.profile.name, "observations": list(OBSERVATIONS)}
        )
        return stub_profile(version, snapshot)


def template(finding_id, location, summary):
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        location=location,
        summary=summary,
        rationale="Simulated rationale.",
        criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.7,
        recommended_action="Explain the required format.",
        requires_human_validation=True,
    )


def review(anchor="SCR-001/ELM-001", **changes):
    return {
        "assessment": "I can register a guest, but the name field needs a hint.",
        "evidence_gaps": [],
        "findings": [
            {
                "anchor": anchor,
                "concern": "The guest name field gives no format hint.",
                "grounds": "At a busy desk I cannot guess the expected name format.",
                "profile_keys": ["user_twin.role"],
                "quality_criterion": "comprehensibility",
                "recommended_action": "Show the expected format below the field.",
                "self_confidence": 0.7,
                "severity": "major",
            }
        ],
        "unable_to_assess": False,
        **changes,
    }


INCONSISTENT = review(unable_to_assess=True, evidence_gaps=["Nothing to judge."])


class MemoryEvidence:
    def __init__(self):
        self.generations = []
        self.events = []

    async def begin(self, *, owner_user_id, project_id, request):
        self.generations.append(request.request_id)

    async def append(self, *, generation_id, kind, payload, **_):
        self.events.append((self.generations.index(generation_id), kind, payload))

    def kinds(self):
        return [(index, kind) for index, kind, _ in self.events]


class FakeGenerator:
    def __init__(
        self, *outcomes, provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL
    ):
        self.outcomes = list(outcomes)
        self.calls = []
        self.configuration = SimpleNamespace(
            identity=SimpleNamespace(content_hash=MODEL_HASH),
            max_output_tokens=8192,
            provider_kind=provider_kind,
        )

    def route(self, task, purpose=None):
        return self

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        await begin_model_generation(SimpleNamespace(request_id=uuid4(), content_hash="d" * 64))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return kwargs["output_type"].model_validate(outcome)


def application(
    monkeypatch,
    *,
    version=None,
    templates=None,
    evaluator=True,
    generation=None,
    generator=None,
    evidence=None,
    profile=StubProfile,
):
    MemoryRuns.runs = []
    current_version = version if version is not None else design_fixtures.design_version()
    MemoryTwins.references = {
        item.twin_id: item for item in current_version.package.grounding.user_twin_references
    }
    monkeypatch.setattr(design_loop, "SqlAlchemyDesignEvaluationRepository", MemoryRuns)
    monkeypatch.setattr(design_loop, "SqlAlchemyFindingValidationRepository", NoValidations)
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", MemoryTwins)
    monkeypatch.setattr(design_loop, "EvaluationUserTwinProfile", profile)
    evaluators = []

    async def current(**kwargs):
        assert kwargs["owner_user_id"] == design_fixtures.OWNER_ID
        return current_version

    def create_evaluator(*, verified_content=None, **_):
        assert verified_content is not None
        created = FakeUserTwinEvaluator(
            configuration=CONFIGURATION,
            templates_by_twin=dict.fromkeys(MemoryTwins.references, templates or ()),
            summaries_by_twin=dict.fromkeys(MemoryTwins.references, "Simulated summary."),
            clock=lambda: datetime.now(UTC),
        )
        evaluators.append(created)
        return created

    runtime = SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=lambda: FakeSession()),
        design_query_service=SimpleNamespace(current=current),
        final_evaluator_runtime=SimpleNamespace(create_evaluator=create_evaluator)
        if evaluator
        else None,
        design_generation_service=generation,
        proposal_evidence_store=evidence,
        real_model_runtime=None
        if generator is None
        else SimpleNamespace(
            user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
        ),
        evaluators=evaluators,
    )
    body = DesignEvaluationRequest(
        design_version_id=current_version.id,
        design_content_hash=current_version.content_hash,
    )
    return DesignLoopApplication(runtime), body


def reviewing(monkeypatch, *outcomes, version=None):
    generator = FakeGenerator(*outcomes)
    evidence = MemoryEvidence()
    app, body = application(
        monkeypatch,
        version=version,
        generator=generator,
        evidence=evidence,
        profile=ObservedProfile,
    )
    return app, body, generator, evidence


def two_twin_version():
    package = design_fixtures.design_package()
    second = UserTwinVersionReference(
        twin_id=SECOND_TWIN_ID, version_number=1, content_hash="c" * 64, name="Night Auditor Twin"
    )
    critiques = tuple(
        replace(
            item, id=UUID(int=210 + index), code=f"CRQ-{index + 3:03d}", user_twin_reference=second
        )
        for index, item in enumerate(package.critiques)
    )
    return design_fixtures.design_version(
        package=replace(
            package,
            grounding=replace(
                package.grounding,
                user_twin_references=canonical_user_twin_references(
                    (*package.grounding.user_twin_references, second), require_items=True
                ),
            ),
            critiques=tuple(sorted((*package.critiques, *critiques), key=lambda item: item.code)),
        )
    )


def evaluate(app, body):
    return asyncio.run(
        app.evaluate(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=design_fixtures.PROJECT_ID,
            body=body,
        )
    )


def compare(app):
    return asyncio.run(
        app.comparison(
            owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
        )
    )


def test_static_check_runs_every_grounded_twin_in_the_training_format(monkeypatch):
    app, body = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."),
        ),
    )
    result = evaluate(app, body)
    assert isinstance(result, DesignEvaluationResult)
    assert result.status is DesignEvaluationStatus.RECORDED
    run = result.run
    target = static_check_target(design_fixtures.design_version(), locale=body.locale)
    assert target.screen_code == "SCR-001"
    assert [item.family for item in target.controls] == ["input_label", "button_name"]
    assert run.design_version_id == body.design_version_id
    assert run.evaluator == CONFIGURATION
    assert [response.twin_id for response in run.responses] == [design_fixtures.TWIN_ID]
    assert [finding.finding_id for finding in run.findings] == ["UTF-001"]
    [artifact] = run.bundle.artifacts
    assert artifact.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert artifact.location == f"dom:#{target.form}"
    assert run.bundle.scenario.task == static_check_scope(target)
    assert run.bundle.scenario.expected_outcomes == target.checks
    assert run.bundle.scenario.locale == "it"
    [created] = app.runtime.evaluators
    [request] = created.requests
    assert request.evaluation_run_id == run.id
    assert request.twin.twin_id == design_fixtures.TWIN_ID
    assert request.twin.snapshot_json == canonical_json(
        {
            "name": "Hotel Receptionist Twin",
            "role": "Hotel Receptionist Twin",
            "goals": ["Create a reservation"],
            "operational_constraints": [STATIC_PROFILE_CONSTRAINT[1]],
        }
    )
    assert f"artifact:{design_fixtures.PROTOTYPE_ID}:v1" in {
        item.reference_id for item in request.evidence
    }
    assert MemoryRuns.runs == [run]
    listed = asyncio.run(
        app.runs(owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID)
    )
    assert listed == (run,)
    snapshot = run.to_snapshot()
    assert snapshot["responses"][0]["findings"][0]["recommended_action"] == (
        "Explain the required format."
    )


def test_static_check_needs_a_screen_with_a_field_and_a_button(monkeypatch):
    version = design_fixtures.design_version()
    prototype = version.package.prototype
    entry = prototype.screens[0]
    fieldless = design_fixtures.design_version(
        package=replace(
            version.package,
            prototype=replace(
                prototype,
                screens=(replace(entry, elements=entry.elements[:1]), prototype.screens[1]),
                transitions=(),
            ),
        )
    )
    app, body = application(monkeypatch, version=fieldless)
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body)
    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "STATIC_CHECK_NOT_APPLICABLE"}
    assert app.runtime.evaluators == []
    assert MemoryRuns.runs == []


def test_evaluation_rejects_a_stale_design_context(monkeypatch):
    app, body = application(monkeypatch)
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body.model_copy(update={"design_content_hash": "f" * 64}))
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "DESIGN_CONTEXT_CHANGED"


@pytest.mark.parametrize(
    "mode", [DesignEvaluationMode.STATIC_CHECK, DesignEvaluationMode.TWIN_REVIEW]
)
def test_evaluation_requires_a_selected_prototype(monkeypatch, mode):
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    app, body, generator, _evidence = reviewing(monkeypatch, version=bare)
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body.model_copy(update={"mode": mode}))
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "DESIGN_PROTOTYPE_REQUIRED"
    assert generator.calls == []
    assert app.runtime.evaluators == []


@pytest.mark.parametrize(
    ("mode", "generator", "evidence", "expected"),
    [
        (None, True, True, TWIN_REVIEW_EVALUATOR_ID),
        (DesignEvaluationMode.TWIN_REVIEW, True, True, TWIN_REVIEW_EVALUATOR_ID),
        (DesignEvaluationMode.STATIC_CHECK, True, True, CONFIGURATION.evaluator_id),
        (None, True, False, CONFIGURATION.evaluator_id),
        (None, False, True, CONFIGURATION.evaluator_id),
    ],
)
def test_mode_prefers_the_twin_review_of_an_audited_proposer(
    monkeypatch, mode, generator, evidence, expected
):
    proposer = FakeGenerator(review())
    app, body = application(
        monkeypatch,
        generator=proposer if generator else None,
        evidence=MemoryEvidence() if evidence else None,
        profile=ObservedProfile,
    )
    result = evaluate(app, body.model_copy(update={"mode": mode}))
    assert result.run.evaluator.evaluator_id == expected
    reviewed = expected == TWIN_REVIEW_EVALUATOR_ID
    assert len(proposer.calls) == int(reviewed)
    assert len(app.runtime.evaluators) == int(not reviewed)


@pytest.mark.parametrize(
    ("mode", "generator", "evidence", "evaluator", "code"),
    [
        (DesignEvaluationMode.TWIN_REVIEW, False, True, True, "DESIGN_REVIEWER_NOT_CONFIGURED"),
        (DesignEvaluationMode.TWIN_REVIEW, True, False, True, "DESIGN_REVIEWER_NOT_CONFIGURED"),
        (DesignEvaluationMode.STATIC_CHECK, True, True, False, "DESIGN_EVALUATOR_NOT_CONFIGURED"),
        (None, True, False, False, "DESIGN_EVALUATOR_NOT_CONFIGURED"),
        (None, False, False, False, "DESIGN_EVALUATOR_NOT_CONFIGURED"),
    ],
)
def test_evaluation_reports_a_missing_reviewer_or_evaluator(
    monkeypatch, mode, generator, evidence, evaluator, code
):
    proposer = FakeGenerator(review())
    app, body = application(
        monkeypatch,
        generator=proposer if generator else None,
        evidence=MemoryEvidence() if evidence else None,
        evaluator=evaluator,
        profile=ObservedProfile,
    )
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body.model_copy(update={"mode": mode}))
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": code}
    assert proposer.calls == []
    assert MemoryRuns.runs == []


def test_twin_review_asks_the_proposer_for_every_twin_and_retains_the_evidence(monkeypatch):
    version = two_twin_version()
    app, body, generator, evidence = reviewing(
        monkeypatch, review(), review(anchor="SCR-002"), version=version
    )
    result = evaluate(app, body)
    run = result.run
    assert result.status is DesignEvaluationStatus.RECORDED
    assert MemoryRuns.runs == [run]
    assert app.runtime.evaluators == []
    assert run.evaluator.evaluator_id == TWIN_REVIEW_EVALUATOR_ID
    assert run.evaluator.model_config_ref == MODEL_HASH
    assert [item.kind for item in run.bundle.artifacts] == [
        EvaluationArtifactKind.DESIGN_SPECIFICATION,
        EvaluationArtifactKind.DOM_SNAPSHOT,
    ]
    assert (run.bundle.scenario.task, run.bundle.scenario.locale) == (
        "Create a reservation",
        "it-IT",
    )
    anchors = design_review_anchors(version)
    assert {
        response.twin_id: [item.location for item in response.findings]
        for response in run.responses
    } == {
        design_fixtures.TWIN_ID: [anchors["SCR-001/ELM-001"]],
        SECOND_TWIN_ID: [anchors["SCR-002"]],
    }
    assert all(
        f"user-twin:{finding.twin_id}:v{finding.twin_version}#user_twin.role"
        in finding.evidence_refs
        for finding in run.findings
    )
    assert [call["task"] for call in generator.calls] == [TWIN_REVIEW_TASK] * 2
    assert [call["context"]["user_twin"]["twin_id"] for call in generator.calls] == [
        str(design_fixtures.TWIN_ID),
        str(SECOND_TWIN_ID),
    ]
    context = generator.calls[0]["context"]
    assert context["design"] == design_review_view(version)
    assert list(context["user_twin"]["observations"]) == ["user_twin.role"]
    assert context["artifact"]["sha256"] == (
        evaluation_document(version, language="it").reference.sha256_digest
    )
    assert evidence.kinds() == [
        (0, "ADAPTER_ACCEPTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert [payload for _, kind, payload in evidence.events if kind == "APPLICATION_RESULT"] == [
        {"status": "TWIN_REVIEWED", "evaluation_run_id": str(run.id)},
        {"status": "DESIGN_EVALUATION_RECORDED", "issue": None},
    ]


@pytest.mark.parametrize(
    ("first", "rejected"),
    [
        (INCONSISTENT, True),
        (ProposalGenerationError("INVALID_PROVIDER_OUTPUT"), False),
        (ProposalGenerationError("INCOMPLETE_OUTPUT"), False),
    ],
)
def test_twin_review_retries_an_invalid_output_once(monkeypatch, first, rejected):
    app, body, generator, evidence = reviewing(monkeypatch, first, review())
    result = evaluate(app, body)
    assert len(generator.calls) == 2
    assert [item.finding_id for item in result.run.findings] == ["UTF-001"]
    assert MemoryRuns.runs == [result.run]
    rejection = [(0, "ADAPTER_REJECTED")] if rejected else []
    assert evidence.kinds() == [
        *rejection,
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.events[len(rejection)][2] == {
        "status": "TWIN_REVIEW_REJECTED",
        "evaluation_run_id": str(result.run.id),
    }
    assert evidence.events[-1][2] == {"status": "DESIGN_EVALUATION_RECORDED", "issue": None}


def test_twin_review_fails_after_a_second_invalid_output(monkeypatch):
    app, body, generator, evidence = reviewing(monkeypatch, INCONSISTENT, INCONSISTENT)
    with pytest.raises(ProposalGenerationError) as failure:
        evaluate(app, body)
    assert failure.value.code == "INVALID_TWIN_REVIEW_OUTPUT"
    assert len(generator.calls) == 2
    assert MemoryRuns.runs == []
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_REJECTED"),
        (1, "APPLICATION_RESULT"),
    ]
    assert evidence.events[-1][2] == {"status": "FAILED", "code": "INVALID_TWIN_REVIEW_OUTPUT"}


@pytest.mark.parametrize(
    "code", ["PROVIDER_UNAVAILABLE", "TIMEOUT", "IDENTITY_MISMATCH", "CONTEXT_BUDGET_EXCEEDED"]
)
def test_twin_review_does_not_retry_other_failures(monkeypatch, code):
    app, body, generator, evidence = reviewing(monkeypatch, ProposalGenerationError(code), review())
    with pytest.raises(ProposalGenerationError) as failure:
        evaluate(app, body)
    assert failure.value.code == code
    assert len(generator.calls) == 1
    assert MemoryRuns.runs == []
    assert evidence.events == [(0, "APPLICATION_RESULT", {"status": "FAILED", "code": code})]


def large_version():
    return design_fixtures.design_version(package=extended_package(large_bound()))


def test_a_hosted_twin_review_reads_a_large_generated_mockup_within_the_hosted_limits(
    monkeypatch,
):
    version = large_version()
    generator = FakeGenerator(
        review(anchor="SCR-001/ELM-016"),
        provider_kind=StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
    )
    app, body = application(
        monkeypatch,
        version=version,
        generator=generator,
        evidence=MemoryEvidence(),
        profile=ObservedProfile,
    )
    result = evaluate(app, body)
    [call] = generator.calls
    assert call["retry_schema_errors"] is False
    assert call["context"]["design"] == design_review_view(version, hosted=True, language="it")
    anchors = design_review_anchors(version, hosted=True, language="it")
    schema = call["output_type"].model_json_schema()
    assert schema["$defs"]["TwinReviewFinding"]["properties"]["anchor"]["enum"] == list(anchors)
    [document] = [
        item
        for item in result.run.bundle.artifacts
        if item.kind is EvaluationArtifactKind.DOM_SNAPSHOT
    ]
    assert document.size_bytes <= HOSTED_DOCUMENT_BYTES
    assert document.sha256_digest == (
        evaluation_document(version, language="it", hosted=True).reference.sha256_digest
    )
    [finding] = result.run.findings
    assert finding_anchor_key(finding) == "SCR-001/ELM-016"
    assert finding.location == anchors["SCR-001/ELM-016"]
    assert MemoryRuns.runs == [result.run]


def test_a_local_twin_review_refuses_a_generated_mockup_it_cannot_hold(monkeypatch):
    app, body, generator, _evidence = reviewing(monkeypatch, review(), version=large_version())
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body)
    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "EVALUATION_DOCUMENT_TOO_LARGE"}
    assert generator.calls == []


def test_a_schema_error_is_answered_once_more_within_the_attempts_of_the_review(monkeypatch):
    schema_error = ProposalGenerationError("RESPONSE_SCHEMA_ERROR")
    app, body, generator, evidence = reviewing(monkeypatch, schema_error, review())
    result = evaluate(app, body)
    assert len(generator.calls) == 2
    assert {call["retry_schema_errors"] for call in generator.calls} == {False}
    assert [item.finding_id for item in result.run.findings] == ["UTF-001"]
    assert evidence.events[0][2] == {
        "status": "TWIN_REVIEW_REJECTED",
        "evaluation_run_id": str(result.run.id),
    }
    twice, body, generator, _evidence = reviewing(
        monkeypatch,
        ProposalGenerationError("RESPONSE_SCHEMA_ERROR"),
        ProposalGenerationError("RESPONSE_SCHEMA_ERROR"),
        review(),
    )
    with pytest.raises(ProposalGenerationError) as failure:
        evaluate(twice, body)
    assert failure.value.code == "RESPONSE_SCHEMA_ERROR"
    assert len(generator.calls) == 2


def test_twin_review_needs_known_profile_observations(monkeypatch):
    generator = FakeGenerator(review())
    app, body = application(monkeypatch, generator=generator, evidence=MemoryEvidence())
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body)
    assert failure.value.status_code == 502
    assert failure.value.detail == {
        "code": "DESIGN_EVALUATION_FAILED",
        "reason": "twin review requires at least one known profile observation",
    }
    assert generator.calls == []
    assert MemoryRuns.runs == []


def test_comparison_needs_two_runs_and_then_reports_resolved_findings(monkeypatch):
    app, body = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."),
            template("UTF-002", "SCR-002 Status", "The confirmation hides the next step."),
        ),
    )
    with pytest.raises(HTTPException) as failure:
        compare(app)
    assert failure.value.detail["code"] == "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"
    first = evaluate(app, body).run
    with pytest.raises(HTTPException) as failure:
        compare(app)
    assert failure.value.status_code == 404
    second_app, _ = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 guest name", "The guest name lacks a format hint."),
        ),
    )
    MemoryRuns.runs = [first]
    second = evaluate(second_app, body).run
    comparison = compare(second_app)
    assert comparison.base_run_id == first.id
    assert comparison.head_run_id == second.id
    assert comparison.to_snapshot()["counts"] == {
        "base": 2,
        "head": 1,
        "resolved": 1,
        "persisting": 1,
        "introduced": 0,
        "dismissed": 0,
    }


def test_comparison_only_compares_runs_of_the_same_evaluator(monkeypatch):
    app, body, _generator, _evidence = reviewing(monkeypatch, review(), review())
    static = body.model_copy(update={"mode": DesignEvaluationMode.STATIC_CHECK})
    first_check = evaluate(app, static).run
    first_review = evaluate(app, body).run
    with pytest.raises(HTTPException) as failure:
        compare(app)
    assert failure.value.status_code == 404
    assert failure.value.detail == {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"}
    second_check = evaluate(app, static).run
    comparison = compare(app)
    assert (comparison.base_run_id, comparison.head_run_id) == (first_check.id, second_check.id)
    second_review = evaluate(app, body).run
    comparison = compare(app)
    assert (comparison.base_run_id, comparison.head_run_id) == (first_review.id, second_review.id)
    assert comparison.to_snapshot()["counts"]["persisting"] == 1


def test_router_records_the_run_and_returns_its_snapshot(monkeypatch):
    app, body = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."),
        ),
    )
    server = FastAPI()
    server.state.application_runtime = app.runtime
    server.include_router(design_loop.create_design_loop_router())
    server.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
        id=design_fixtures.OWNER_ID
    )
    client = TestClient(server)
    path = f"/projects/{design_fixtures.PROJECT_ID}/design/evaluations"
    payload = body.model_dump(mode="json")
    assert client.get(f"{path}/comparison").status_code == 404
    assert client.post(path, json={**payload, "mode": "HEURISTIC"}).status_code == 422
    created = client.post(path, json={**payload, "mode": "STATIC_CHECK"})
    assert created.status_code == 201
    [run] = MemoryRuns.runs
    assert created.json() == run.to_snapshot()
    assert client.get(path).json() == [run.to_snapshot()]


def test_regeneration_delegates_to_the_generation_service(monkeypatch):
    calls = []

    async def regenerate(**kwargs):
        calls.append(kwargs)
        return "result"

    app, _ = application(monkeypatch, generation=SimpleNamespace(regenerate=regenerate))
    result = asyncio.run(
        app.regenerate(
            owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
        )
    )
    assert result == "result"
    assert calls == [
        {"owner_user_id": design_fixtures.OWNER_ID, "project_id": design_fixtures.PROJECT_ID}
    ]
    missing, _ = application(monkeypatch)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            missing.regenerate(
                owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
            )
        )
    assert failure.value.status_code == 503


def test_router_registers_the_loop_routes():
    router = design_loop.create_design_loop_router()
    paths = sorted(route.path for route in router.routes)
    assert paths == [
        "/projects/{project_id}/design/evaluations",
        "/projects/{project_id}/design/evaluations",
        "/projects/{project_id}/design/evaluations/comparison",
        "/projects/{project_id}/design/evaluations/validations",
        "/projects/{project_id}/design/evaluations/{run_id}/validations",
        "/projects/{project_id}/design/regenerations",
    ]
    assert UUID(int=0) is not None
