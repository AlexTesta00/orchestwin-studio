import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from orchestwin.evaluation.aggregation import aggregate_synthetic_evaluation
from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    IndependentUserTwinEvaluationService,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.evaluation.execution_bundle import (
    artifact_evidence_references,
    artifact_reference_id,
    execution_bundle,
    execution_scenario,
)
from orchestwin.evaluation.findings import SyntheticFindingEpistemicStatus
from orchestwin.evaluation.proposer_evaluator import (
    MAX_DOM_CHARACTERS,
    ProposerUserTwinEvaluator,
    dom_text,
    evaluation_output_type,
)
from orchestwin.evaluation.run_restore import synthetic_evaluation_run_from_snapshot
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference
from orchestwin.twins.user_twins import UserTwinLifecycleStatus
from src.test.python.models.test_proposal_evidence import Command, MemoryEvidence, audited_generator
from src.test.python.twins.test_user_modeling_persistence import twin_version

EXECUTION = UUID("11111111-2222-4333-8444-555555555555")
DOM = b"<html><head><script>alert(1)</script><style>p{}</style></head><body>\n  <h1>Registro</h1>\n</body></html>"
AXE = b'{"testEngine": {"name": "axe-core", "version": "4.10.0"}, "violations": [{"id": "label", "impact": "critical", "description": "Form elements must have labels", "help": "Add a label", "nodes": [{"target": ["#name"], "html": "<input id=\\"name\\">", "failureSummary": "Fix: add a label"}]}], "incomplete": [], "passes": [], "inapplicable": []}'
NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)


def reference_snapshot(content: bytes, media_type: str):
    digest = hashlib.sha256(content).hexdigest()
    return {
        "storage_key": f"sha256/{digest[:2]}/{digest}",
        "sha256_digest": digest,
        "size_bytes": len(content),
        "media_type": media_type,
    }


CONTENT = {
    reference_snapshot(DOM, "text/html")["storage_key"]: DOM,
    reference_snapshot(AXE, "application/json")["storage_key"]: AXE,
}


def bundle(project_id, workflow_run_id):
    return execution_bundle(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        execution_id=EXECUTION,
        attempt_number=1,
        screens=[
            {
                "route_id": "SCR-001",
                "path": "/",
                "viewport": "wide",
                "final_path": "/",
                "artifacts": {
                    "screenshot": reference_snapshot(b"\x89PNG", "image/png"),
                    "dom": reference_snapshot(DOM, "text/html"),
                    "axe": reference_snapshot(AXE, "application/json"),
                    "events": None,
                },
            }
        ],
        scenario=execution_scenario(
            execution_id=EXECUTION,
            name="Registro ospiti",
            task="Registrare un ospite.",
            expected_outcomes=("Ospite registrato",),
        ),
        created_at=NOW,
    )


def read_content(key, maximum_bytes):
    return CONTENT[key]


def twin_profile(status=UserTwinLifecycleStatus.OWNER_APPROVED_UT):
    version = twin_version()
    profile = EvaluationUserTwinProfile.from_version(version)
    return EvaluationUserTwinProfile(
        twin_id=profile.twin_id,
        version_number=profile.version_number,
        name=profile.name,
        lifecycle_status=status,
        content_hash=profile.content_hash,
        snapshot_json=profile.snapshot_json,
    )


def profile_reference(twin):
    return EvaluationEvidenceReference(
        reference_id=f"user-twin:{twin.twin_id}:v{twin.version_number}",
        kind=EvaluationEvidenceKind.USER_TWIN_PROFILE,
        content_hash=twin.content_hash,
        locator="profile",
    )


def target(artifacts, twin):
    evidence = tuple(
        sorted(
            (profile_reference(twin), *artifact_evidence_references(artifacts)),
            key=lambda item: item.sort_key,
        )
    )
    return ApprovedUserTwinEvaluationTarget(twin=twin, evidence=evidence)


def model_output(artifacts, twin, *, findings=True, abstained=False, gaps=(), evidence=None):
    dom = next(item for item in artifacts if item.kind.value == "DOM_SNAPSHOT")
    refs = (
        [f"user-twin:{twin.twin_id}:v{twin.version_number}"] if evidence is None else list(evidence)
    )
    return {
        "summary": "Registrare un ospite  mi sembra rapido, ma manca un messaggio di conferma.",
        "findings": [
            {
                "artifact_id": str(dom.artifact_id),
                "location": "SCR-001, campo nome",
                "summary": "Il campo nome non spiega  il formato atteso.",
                "rationale": "Il profilo dice che lavoro sotto pressione e non voglio errori.",
                "criterion": "comprehensibility",
                "severity": "moderate",
                "confidence": 0.734,
                "recommended_action": "Aggiungere un suggerimento sotto il campo.",
                "evidence_refs": refs,
            }
        ]
        if findings
        else [],
        "evidence_gaps": list(gaps),
        "abstained": abstained,
    }


class FakeGenerator:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.configuration = SimpleNamespace(
            identity=SimpleNamespace(content_hash="c" * 64), max_output_tokens=4096
        )

    async def generate(self, *, task, context, output_type, max_output_tokens, instruction):
        self.calls.append({"task": task, "context": context, "instruction": instruction})
        return output_type(**self.outputs.pop(0))


def request(project_id, workflow_run_id, evaluated, twin):
    return UserTwinEvaluationRequest(
        evaluation_run_id=uuid4(),
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        artifact_bundle=evaluated,
        twin=twin,
        evidence=target(evaluated.artifacts, twin).evidence,
        requested_at=NOW,
    )


def test_dom_text_drops_scripts_and_styles_and_bounds_the_excerpt():
    assert dom_text(DOM) == "<html><head></head><body><h1>Registro</h1></body></html>"
    assert dom_text(b"<p>" + b"x" * (MAX_DOM_CHARACTERS + 10) + b"</p>").endswith("[truncated]")


def test_output_type_pins_bundle_artifacts_and_evidence_references():
    output_type = evaluation_output_type(("artifact-a",), ("ref-a",))
    with pytest.raises(ValueError):
        output_type(summary="x", findings=[], evidence_gaps=[], abstained=False, extra=1)
    with pytest.raises(ValueError):
        output_type(
            summary="x",
            findings=[
                {
                    "artifact_id": "artifact-b",
                    "location": "l",
                    "summary": "s",
                    "rationale": "r",
                    "criterion": "trust",
                    "severity": "minor",
                    "confidence": 0.5,
                    "recommended_action": "a",
                    "evidence_refs": [],
                }
            ],
            evidence_gaps=[],
            abstained=False,
        )


def test_evaluator_grounds_the_context_and_binds_findings_as_hypotheses():
    project_id, workflow_run_id = uuid4(), uuid4()
    evaluated = bundle(project_id, workflow_run_id)
    twin = twin_profile()
    generator = FakeGenerator([model_output(evaluated.artifacts, twin)])
    evaluator = ProposerUserTwinEvaluator(generator, read_content=read_content, clock=lambda: NOW)
    response = asyncio.run(
        evaluator.evaluate(request(project_id, workflow_run_id, evaluated, twin))
    )
    call = generator.calls[0]
    assert call["task"] == "user-twin-evaluation"
    assert call["context"]["purpose"] == "SYNTHETIC_EVALUATION"
    assert call["context"]["user_twin"]["profile"]["name"] == twin.name
    kinds = {item["kind"]: item for item in call["context"]["artifacts"]}
    assert kinds["DOM_SNAPSHOT"]["content"].startswith("<html><head></head>")
    assert kinds["AXE_REPORT"]["content"]["violations"][0]["id"] == "label"
    assert "content" not in kinds["SCREENSHOT"]
    assert "What would you try to do first" in call["context"]["questions"][0]
    assert evaluator.configuration.model_config_ref == "c" * 64
    assert response.evaluator == evaluator.configuration
    assert (
        response.summary
        == "Registrare un ospite mi sembra rapido, ma manca un messaggio di conferma."
    )
    finding = response.findings[0]
    assert finding.finding_id == "UTF-001"
    assert finding.epistemic_status is SyntheticFindingEpistemicStatus.MODEL_INFERRED
    assert finding.requires_human_validation is True
    assert finding.confidence == 0.73
    assert finding.summary == "Il campo nome non spiega il formato atteso."
    dom = kinds["DOM_SNAPSHOT"]
    assert finding.evidence_refs == tuple(
        sorted({dom["reference_id"], f"user-twin:{twin.twin_id}:v{twin.version_number}"})
    )
    assert finding.artifact_id == UUID(dom["artifact_id"])
    assert finding.prompt_version_ref == "s18-proposer-twin-evaluation-v1"


def test_abstention_without_details_records_an_evidence_gap():
    project_id, workflow_run_id = uuid4(), uuid4()
    evaluated = bundle(project_id, workflow_run_id)
    twin = twin_profile()
    generator = FakeGenerator(
        [model_output(evaluated.artifacts, twin, findings=False, abstained=True)]
    )
    evaluator = ProposerUserTwinEvaluator(generator, read_content=read_content, clock=lambda: NOW)
    response = asyncio.run(
        evaluator.evaluate(request(project_id, workflow_run_id, evaluated, twin))
    )
    assert response.findings == ()
    assert response.evidence_gaps == (
        "The evaluator abstained because the artifacts were insufficient.",
    )


def test_independent_service_runs_every_twin_and_the_run_survives_a_snapshot_roundtrip():
    project_id, workflow_run_id, owner = uuid4(), uuid4(), uuid4()
    evaluated = bundle(project_id, workflow_run_id)
    first = twin_profile()
    second_version = twin_version()
    second = EvaluationUserTwinProfile(
        twin_id=uuid4(),
        version_number=1,
        name="Seconda utente",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=second_version.content_hash,
        snapshot_json=second_version.profile.canonical_json(),
    )
    generator = FakeGenerator(
        [model_output(evaluated.artifacts, first), model_output(evaluated.artifacts, second)]
    )
    evaluator = ProposerUserTwinEvaluator(generator, read_content=read_content, clock=lambda: NOW)
    service = IndependentUserTwinEvaluationService(
        evaluator, identifier_provider=uuid4, clock=lambda: NOW
    )
    run = asyncio.run(
        service.evaluate(
            owner_user_id=owner,
            artifact_bundle=evaluated,
            targets=(target(evaluated.artifacts, first), target(evaluated.artifacts, second)),
        )
    )
    assert len(run.twin_evaluations) == 2
    assert len(run.findings) == 2
    restored = synthetic_evaluation_run_from_snapshot(json.loads(json.dumps(run.to_snapshot())))
    assert restored == run
    aggregation = aggregate_synthetic_evaluation(restored)
    assert aggregation.evaluation_run_hash == run.content_hash
    assert len(aggregation.shared_findings) == 1


def test_each_twin_evaluation_is_an_audited_generation(tmp_path):
    project_id, workflow_run_id, owner = uuid4(), uuid4(), uuid4()
    evaluated = bundle(project_id, workflow_run_id)
    twin = twin_profile()
    second_version = twin_version()
    second = EvaluationUserTwinProfile(
        twin_id=uuid4(),
        version_number=1,
        name="Seconda utente",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=second_version.content_hash,
        snapshot_json=second_version.profile.canonical_json(),
    )
    dom = next(item for item in evaluated.artifacts if item.kind.value == "DOM_SNAPSHOT")
    generator, transport = audited_generator(
        tmp_path, model_output(evaluated.artifacts, twin, evidence=[artifact_reference_id(dom)])
    )
    evaluator = ProposerUserTwinEvaluator(generator, read_content=read_content, clock=lambda: NOW)
    service = IndependentUserTwinEvaluationService(
        evaluator, identifier_provider=uuid4, clock=lambda: NOW
    )
    store = MemoryEvidence()

    async def operation():
        run = await service.evaluate(
            owner_user_id=owner,
            artifact_bundle=evaluated,
            targets=(target(evaluated.artifacts, twin), target(evaluated.artifacts, second)),
        )
        return SimpleNamespace(
            status=SimpleNamespace(value="SYNTHETIC_EVALUATION_RECORDED"), run=run
        )

    result = asyncio.run(Command(store, operation).run(owner_user_id=owner, project_id=project_id))
    assert len(transport.calls) == 2
    assert transport.calls[0]["payload"]["metadata"]["orchestwin_task_id"] == (
        "proposal-user-twin-evaluation-v1"
    )
    first_generation, second_generation = store.requests
    first_events = [(kind, data) for kind, data, _ in store.events[first_generation]]
    assert [
        kind for kind, _ in first_events if kind in {"ADAPTER_ACCEPTED", "APPLICATION_RESULT"}
    ] == [
        "ADAPTER_ACCEPTED",
        "APPLICATION_RESULT",
    ]
    accepted = next(data for kind, data in first_events if kind == "ADAPTER_ACCEPTED")
    assert accepted["generated_content_hashes"] == {
        "SYNTHETIC_EVALUATION": [result.run.twin_evaluations[0].content_hash]
    }
    assert next(data for kind, data in first_events if kind == "APPLICATION_RESULT") == {
        "status": "TWIN_EVALUATED"
    }
    second_kinds = [kind for kind, _, _ in store.events[second_generation]]
    assert "ADAPTER_ACCEPTED" not in second_kinds
    assert second_kinds[-1] == "APPLICATION_RESULT"
