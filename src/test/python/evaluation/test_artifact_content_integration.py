"""Native domain/gateway tests; all inference is a deterministic test double."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.evaluation.artifact_content import (
    CONTENT_PROMPT_VERSION,
    CONTENT_PROMPT_VERSION_V1,
    prepare_artifact_content,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import UserTwinEvaluatorConfiguration
from orchestwin.evaluation.field_scope_prompt import FIELD_SCOPE_PROMPT_VERSION
from orchestwin.evaluation.final_runtime import FinalEvaluatorRuntime
from orchestwin.evaluation.model_evaluator import (
    ModelGatewayEvaluationError,
    ModelGatewayUserTwinEvaluator,
)
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference
from orchestwin.models.final_evaluator_gateway import FinalEvaluatorGenerationPort
from orchestwin.models.structured_generation import ModelRuntimeIdentity

from ..models.final_session_support import make_session
from .test_artifact_content_views import axe_payload
from .test_model_evaluator import NOW, REQUEST_ID, _identity, _Port, _request, _valid_payload

RAW = b'<main><button id="activate">Activate</button><p id="result">Ready</p></main>'


def request_with_content(raw=RAW, kind=EvaluationArtifactKind.DOM_SNAPSHOT):
    original = _request()
    digest = hashlib.sha256(raw).hexdigest()
    ref = replace(
        original.artifact_bundle.artifacts[0],
        kind=kind,
        media_type="text/html"
        if kind is EvaluationArtifactKind.DOM_SNAPSHOT
        else "application/json",
        sha256_digest=digest,
        size_bytes=len(raw),
        storage_key=f"sha256/{digest[:2]}/{digest}",
    )
    old = original.artifact_bundle
    bundle = create_evaluation_artifact_bundle(
        project_id=old.project_id,
        workflow_run_id=old.workflow_run_id,
        scenario=old.scenario,
        artifacts=(ref,),
        created_at=old.created_at,
        bundle_id=old.id,
    )
    request = replace(original, artifact_bundle=bundle)
    prepared = prepare_artifact_content(
        request,
        selected=((ref.artifact_id, ref.version_number),),
        read_content=lambda _key, _limit: raw,
    )
    return request, prepared, ref


def configured_evaluator(prepared, port):
    return ModelGatewayUserTwinEvaluator(
        configuration=UserTwinEvaluatorConfiguration(
            "test-content", "1", port.identity.content_hash, CONTENT_PROMPT_VERSION
        ),
        model_identity=port.identity,
        generation_port=port,
        request_id_factory=lambda: REQUEST_ID,
        clock=lambda: NOW,
        output_schema_version=2,
        verified_content=prepared.content,
    )


def test_prepare_adds_bound_reference_without_mutating_original_request():
    request, prepared, ref = request_with_content()
    assert len(prepared.request.evidence) == len(request.evidence) + 1
    citation = next(e for e in prepared.request.evidence if e.reference_id.startswith("artifact:"))
    assert citation.content_hash == ref.sha256_digest
    assert citation.kind is EvaluationEvidenceKind.PROJECT_ARTIFACT
    assert "verified_artifact_content" not in request.to_snapshot()
    assert prepared.request.evaluation_run_id == request.evaluation_run_id


def test_axe_citations_are_deterministic_not_empirical():
    raw = json.dumps(axe_payload()).encode()
    _, prepared, _ = request_with_content(raw, EvaluationArtifactKind.AXE_REPORT)
    citation = next(e for e in prepared.request.evidence if e.reference_id.startswith("artifact:"))
    assert citation.kind is EvaluationEvidenceKind.DETERMINISTIC_TEST
    assert "AXE_RULE_AND_NODE_VIEW_V1" in prepared.content.payload_json


@pytest.mark.parametrize("selection", [(), ((UUID(int=999), 1),)])
def test_invalid_selection_is_rejected_before_read(selection):
    request = _request()
    calls = []
    with pytest.raises(ValueError):
        prepare_artifact_content(
            request, selected=selection, read_content=lambda *_args: calls.append(True)
        )
    assert calls == []


def test_images_cannot_be_sent_to_the_text_model_as_observed_pixels():
    request = _request()
    ref = request.artifact_bundle.artifacts[0]
    calls = []
    with pytest.raises(ValueError, match="KIND_NOT_SUPPORTED"):
        prepare_artifact_content(
            request,
            selected=((ref.artifact_id, ref.version_number),),
            read_content=lambda *_args: calls.append(True),
        )
    assert not calls


def test_wrong_bytes_fail_before_any_model_call():
    request, _, ref = request_with_content()
    with pytest.raises(ValueError, match="HASH_OR_SIZE"):
        prepare_artifact_content(
            request,
            selected=((ref.artifact_id, ref.version_number),),
            read_content=lambda *_args: b"wrong",
        )


def test_conflicting_existing_citation_is_rejected():
    request, prepared, ref = request_with_content()
    added = next(e for e in prepared.request.evidence if e.reference_id.startswith("artifact:"))
    conflict = EvaluationEvidenceReference(added.reference_id, added.kind, "0" * 64, added.locator)
    request = replace(
        request, evidence=tuple(sorted((*request.evidence, conflict), key=lambda e: e.sort_key))
    )
    with pytest.raises(ValueError, match="REFERENCE_CONFLICT"):
        prepare_artifact_content(
            request,
            selected=((ref.artifact_id, ref.version_number),),
            read_content=lambda *_args: RAW,
        )


def test_native_evaluator_delivers_content_and_keeps_schema_validation():
    _, prepared, ref = request_with_content()
    payload = _valid_payload()
    payload["findings"][0]["evidence_refs"] = [f"artifact:{ref.artifact_id}:v{ref.version_number}"]
    port = _Port(_identity(), payload)
    evaluator = configured_evaluator(prepared, port)
    response = asyncio.run(evaluator.evaluate(prepared.request))
    sent = json.loads(port.request.input_payload_json)
    assert sent["verified_artifact_content"]["items"][0]["data"].encode() == RAW
    assert port.request.prompt_version_ref == CONTENT_PROMPT_VERSION
    assert response.findings[0].requires_human_validation is True
    assert evaluator.traces[0].request_sha256 == port.request.content_hash


def test_unchanged_metadata_only_input_does_not_gain_new_fields():
    request, prepared, _ = request_with_content()
    port = _Port(_identity(), _valid_payload())
    content_evaluator = configured_evaluator(prepared, port)
    plain = ModelGatewayUserTwinEvaluator(
        configuration=content_evaluator.configuration,
        model_identity=port.identity,
        generation_port=port,
        request_id_factory=lambda: REQUEST_ID,
        clock=lambda: NOW,
    )
    from orchestwin.evaluation.model_evaluator import _input_payload

    assert plain.build_input_payload(request) == _input_payload(request)
    assert "verified_artifact_content" not in plain.build_input_payload(request)
    with pytest.raises(ValueError, match="REQUEST_BINDING"):
        asyncio.run(content_evaluator.evaluate(request))
    assert port.request is None


def test_content_result_must_cite_the_artifact_not_only_an_unrelated_requirement():
    _, prepared, _ = request_with_content()
    port = _Port(_identity(), _valid_payload())
    with pytest.raises(ModelGatewayEvaluationError):
        asyncio.run(configured_evaluator(prepared, port).evaluate(prepared.request))


def test_content_path_keeps_root_field_rejection():
    _, prepared, _ = request_with_content()
    payload = {
        "overall_summary": "Insufficient evidence.",
        "findings": [],
        "evidence_gaps": ["Only technical data supplied."],
        "abstained": True,
        "severity": "minor",
    }
    with pytest.raises(ModelGatewayEvaluationError):
        asyncio.run(
            configured_evaluator(prepared, _Port(_identity(), payload)).evaluate(prepared.request)
        )


def test_factory_versions_content_schema_without_changing_metadata_only_r2(tmp_path):
    _, prepared, _ = request_with_content()
    runtime = FinalEvaluatorRuntime(make_session(tmp_path))
    plain = runtime.create_evaluator()
    content = runtime.create_evaluator(verified_content=prepared.content)
    assert plain.configuration.prompt_version_ref == FIELD_SCOPE_PROMPT_VERSION
    assert CONTENT_PROMPT_VERSION_V1 == "s12-verified-artifact-content-v1"
    assert CONTENT_PROMPT_VERSION == "s12-verified-artifact-content-v2-finding-id-pattern"
    assert content.configuration.prompt_version_ref == CONTENT_PROMPT_VERSION
    assert content.system_instruction.startswith(plain.system_instruction)
    assert "^UTF-[0-9]{3,6}$" in content.system_instruction
    assert plain.output_schema.version_number == 1
    assert content.output_schema.version_number == 2
    plain_schema = json.loads(plain.output_schema.canonical_schema_json)
    content_schema = json.loads(content.output_schema.canonical_schema_json)
    plain_id = plain_schema["properties"]["findings"]["items"]["properties"]["finding_id"]
    content_id = content_schema["properties"]["findings"]["items"]["properties"]["finding_id"]
    assert plain_id == {"type": "string"}
    assert content_id == {"type": "string", "pattern": r"^UTF-[0-9]{3,6}$"}
    assert content._model_identity == plain._model_identity
    assert plain.traces is not content.traces
    with pytest.raises(TypeError):
        runtime.create_evaluator(verified_content={})


def test_gateway_allows_only_well_bound_content_requests(tmp_path):
    from orchestwin.models.structured_generation import create_structured_generation_request

    _, prepared, _ = request_with_content()
    runtime = FinalEvaluatorRuntime(make_session(tmp_path))
    evaluator = runtime.create_evaluator(verified_content=prepared.content)
    payload = evaluator.build_input_payload(prepared.request)
    payload["verified_artifact_content"]["bundle_content_hash"] = "f" * 64
    request = create_structured_generation_request(
        request_id=REQUEST_ID,
        task_id="user-twin-evaluation-v1",
        expected_identity=ModelRuntimeIdentity(**runtime.session.identity),
        output_schema=evaluator.output_schema,
        system_instruction=evaluator.system_instruction,
        input_payload=payload,
        allowed_evidence_refs=tuple(e.reference_id for e in prepared.request.evidence),
        prompt_version_ref=CONTENT_PROMPT_VERSION,
        temperature=0.0,
        max_output_tokens=1024,
        timeout_seconds=90,
    )
    calls = []
    result = asyncio.run(
        FinalEvaluatorGenerationPort(
            runtime.session,
            exchange=lambda *_args: calls.append(True),
        ).generate(request)
    )
    assert result.failure.code.value == "INVALID_REQUEST"
    assert calls == []
