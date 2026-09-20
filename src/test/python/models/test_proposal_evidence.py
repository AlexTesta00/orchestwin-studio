"""Synthetic completions test retention boundaries, never model quality."""

import asyncio
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.models.model_proposals import (
    ModelArchitectureAdapter,
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    ModelTeamProposalAdapter,
    ModelUserModelingAdapter,
)
from orchestwin.models.openai_compatible import OpenAICompatibleHttpResponse
from orchestwin.models.proposal_evidence import (
    ProposalEvidenceError,
    bind_model_artifacts,
    current_proposal_evidence,
    evidence_application,
)
from orchestwin.models.proposal_generation import (
    ProposalGenerationError,
    build_proposal_generator,
)
from src.test.python.models import test_model_proposals as fixtures


class MemoryEvidence:
    def __init__(self, fail=None):
        self.requests, self.events, self.fail = {}, {}, fail

    async def begin(self, *, request, **scope):
        if self.fail == "REQUEST":
            raise ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED")
        self.requests[request.request_id] = (request, scope)
        self.events[request.request_id] = []

    async def append(self, *, generation_id, kind, payload, raw_body=None, **scope):
        if self.fail == kind:
            raise ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED")
        self.events[generation_id].append((kind, payload, raw_body))


class Command:
    def __init__(self, store, operation):
        self._proposal_evidence_store, self.operation = store, operation

    @evidence_application
    async def run(self, *, owner_user_id, project_id):
        return await self.operation()


def audited_generator(tmp_path, output, **options):
    generator, transport = fixtures.make_generator(tmp_path, output, **options)
    generator.configuration.token_file.write_text("test-secret-" + "x" * 48, encoding="ascii")
    path = tmp_path / "config.json"
    path.write_text(generator.configuration.model_dump_json(), encoding="utf-8")
    return build_proposal_generator(path, transport=transport), transport


def stage_case(stage):
    if stage == "team":
        return (
            fixtures.team_fixtures.build_request(),
            {"rationale": "Synthetic evidence contract.", "suggestions": []},
            ModelTeamProposalAdapter,
            "propose",
            "AGENT_TEAM",
        )
    if stage == "personas":
        request, output = fixtures.persona_input_output()
        return request, output, ModelUserModelingAdapter, "propose_personas", "PERSONA"
    if stage == "user-twins":
        request, output = fixtures.twin_input_output()
        return (
            request,
            output,
            ModelUserModelingAdapter,
            "propose_user_twins",
            "USER_TWIN",
        )
    source, adapter, key = {
        "requirements": (fixtures.requirements_fixtures, ModelRequirementsAdapter, "specification"),
        "design": (fixtures.design_fixtures, ModelDesignAdapter, "package"),
        "architecture": (fixtures.architecture_fixtures, ModelArchitectureAdapter, "package"),
    }[stage]
    request = source.proposal_request()
    result = asyncio.run(
        getattr(source, f"FakeDeterministic{stage.title()}Adapter")().propose(request)
    )
    value = getattr(result, key)
    if stage == "design":
        value = replace(
            value,
            critiques=tuple(
                replace(
                    c,
                    provenance=next(
                        t.observations[0].provenance
                        for t in request.user_modeling.user_twins
                        if t.reference == c.user_twin_reference
                    ),
                )
                for c in value.critiques
            ),
        )
    from .draft_fixtures import proposal_draft

    return request, proposal_draft(stage, value, request), adapter, "propose", stage.upper()


@pytest.mark.parametrize(
    "stage", ["team", "personas", "user-twins", "requirements", "design", "architecture"]
)
def test_all_six_tasks_retain_exact_request_raw_response_and_adapter_result(tmp_path, stage):
    request, output, adapter, method, kind = stage_case(stage)
    generator, transport = audited_generator(tmp_path, output)
    store = MemoryEvidence()
    command = Command(store, lambda: getattr(adapter(generator), method)(request))
    asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    generation_id, (generation, _) = next(iter(store.requests.items()))
    events = store.events[generation_id]
    assert [e[0] for e in events] == [
        "HTTP_REQUEST",
        "HTTP_RESPONSE",
        "PROVIDER_RESULT",
        "ADAPTER_ACCEPTED",
        "APPLICATION_RESULT",
    ]
    assert generation.task_id == f"proposal-{stage}-v1"
    assert generation.expected_identity == generator.configuration.identity
    assert generation.temperature == 0.6
    assert events[0][1]["payload"] == transport.calls[0]["payload"]
    assert hashlib.sha256(events[1][2]).hexdigest() == events[1][1]["body_sha256"]
    assert kind in events[3][1]["generated_content_hashes"]
    assert "test-secret-" not in repr(store.events)
    if stage in {"personas", "user-twins", "design"}:
        assert f"generation:{generation_id}" in json.dumps(events[3][1])
        canonical_output = events[2][1]["success"]["payload_json"]
        assert hashlib.sha256(canonical_output.encode()).hexdigest() in json.dumps(events[3][1])
    assert current_proposal_evidence() is None


def test_persona_content_draft_binds_exact_brief_and_generation_evidence(tmp_path):
    request, output = fixtures.persona_input_output()
    generator, _ = audited_generator(tmp_path, output)
    store = MemoryEvidence()
    command = Command(store, lambda: ModelUserModelingAdapter(generator).propose_personas(request))
    result = asyncio.run(command.run(owner_user_id=uuid4(), project_id=request.project_id))
    generation_id, (generation, _) = next(iter(store.requests.items()))
    assert generation.output_schema.schema_id == "proposal-personas-v4"
    assert generation.prompt_version_ref == "proposal-personas-v4"
    provider = next(
        payload for kind, payload, _ in store.events[generation_id] if kind == "PROVIDER_RESULT"
    )
    canonical_output = provider["success"]["payload_json"]
    raw_draft = json.loads(canonical_output)["proposals"][0]
    assert "candidate_content_hash" not in raw_draft
    assert all("provenance" not in item for item in raw_draft["observations"])
    candidate = request.candidates[0]
    proposal = result.proposals[0]
    assert proposal.candidate_content_hash == candidate.content_hash
    assert proposal.profile.observations[0] == candidate.role_observation
    for observation in proposal.profile.observations[1:]:
        assert (
            observation.provenance.references[:-2]
            == candidate.role_observation.provenance.references
        )
        reference = observation.provenance.references[-1]
        assert reference.source_kind.value == "MODEL_OUTPUT"
        assert reference.source_id == f"generation:{generation_id}"
        assert reference.content_hash == hashlib.sha256(canonical_output.encode()).hexdigest()
        assert reference.locator == observation.observation_key


@pytest.mark.parametrize(
    "options,code",
    [
        ({"timeout": True}, "TIMEOUT"),
        ({"status": 503}, "PROVIDER_UNAVAILABLE"),
        ({"drift": True}, "IDENTITY_MISMATCH"),
        ({"finish": "length"}, "INCOMPLETE_OUTPUT"),
        ({}, "INVALID_PROVIDER_OUTPUT"),
    ],
)
def test_failed_generations_remain_visible_with_no_publication(tmp_path, options, code):
    generator, transport = audited_generator(
        tmp_path, {"rationale": "x" * 2001, "suggestions": []}, **options
    )
    store = MemoryEvidence()
    command = Command(
        store,
        lambda: ModelTeamProposalAdapter(generator).propose(fixtures.team_fixtures.build_request()),
    )
    with pytest.raises(ProposalGenerationError, match=code):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    events = next(iter(store.events.values()))
    assert events[-2][0] == "ADAPTER_REJECTED"
    assert events[-1][1] == {"status": "FAILED", "code": code}
    assert "ADAPTER_ACCEPTED" not in [e[0] for e in events]
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "fail,calls",
    [
        ("REQUEST", 0),
        ("HTTP_REQUEST", 0),
        ("HTTP_RESPONSE", 1),
        ("PROVIDER_RESULT", 1),
        ("ADAPTER_ACCEPTED", 1),
    ],
)
def test_evidence_failure_stops_before_next_boundary(tmp_path, fail, calls):
    generator, transport = audited_generator(tmp_path, {"rationale": "Valid", "suggestions": []})
    store = MemoryEvidence(fail)
    command = Command(
        store,
        lambda: ModelTeamProposalAdapter(generator).propose(fixtures.team_fixtures.build_request()),
    )
    with pytest.raises(ProposalEvidenceError):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    assert len(transport.calls) == calls
    assert not any(e[0] == "ADAPTER_ACCEPTED" for events in store.events.values() for e in events)
    assert current_proposal_evidence() is None


def test_concurrent_commands_do_not_mix_generations(tmp_path):
    generator, _ = audited_generator(tmp_path, {"rationale": "Valid", "suggestions": []})
    store = MemoryEvidence()

    async def operation():
        await asyncio.sleep(0)
        return await ModelTeamProposalAdapter(generator).propose(
            fixtures.team_fixtures.build_request()
        )

    async def run():
        await asyncio.gather(
            *(
                Command(store, operation).run(owner_user_id=uuid4(), project_id=uuid4())
                for _ in range(8)
            )
        )

    asyncio.run(run())
    assert len(store.requests) == 8
    for generation_id, events in store.events.items():
        assert events[0][1]["payload"]["metadata"]["orchestwin_request_id"] == str(generation_id)
        assert len(events) == 5


def test_credential_reflection_is_withheld_and_cannot_be_published(tmp_path):
    generator, transport = audited_generator(tmp_path, {})

    async def reflect(**kwargs):
        return OpenAICompatibleHttpResponse(200, kwargs["headers"]["Authorization"].encode(), 1)

    transport.post_json = reflect
    store = MemoryEvidence()
    command = Command(
        store,
        lambda: ModelTeamProposalAdapter(generator).propose(fixtures.team_fixtures.build_request()),
    )
    with pytest.raises(ProposalEvidenceError, match="PROVIDER_REFLECTED_CREDENTIAL"):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    events = next(iter(store.events.values()))
    assert events[-1][0] == "HTTP_RESPONSE" and events[-1][2] is None
    assert events[-1][1]["withheld_reason"] == "CREDENTIAL_REFLECTION"
    assert "test-secret-" not in repr(store.events)


def test_fake_application_creates_no_model_evidence():
    store = MemoryEvidence()
    command = Command(
        store,
        lambda: fixtures.team_fixtures.FakeDeterministicTeamProposalAdapter().propose(
            fixtures.team_fixtures.build_request()
        ),
    )
    asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    assert store.requests == {} and store.events == {}


def test_raw_malformed_json_is_retained_before_envelope_rejection(tmp_path):
    generator, transport = audited_generator(tmp_path, {})
    raw = b'{"broken envelope":'

    async def malformed(**kwargs):
        return OpenAICompatibleHttpResponse(200, raw, 7)

    transport.post_json = malformed
    store = MemoryEvidence()
    command = Command(
        store,
        lambda: ModelTeamProposalAdapter(generator).propose(fixtures.team_fixtures.build_request()),
    )
    with pytest.raises(ProposalGenerationError, match="RESPONSE_SCHEMA_ERROR"):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    assert next(iter(store.events.values()))[1][2] == raw


@pytest.mark.parametrize("mismatch", ["owner", "hash", "missing_repository"])
def test_artifact_binding_fails_closed(tmp_path, mismatch):
    generator, _ = audited_generator(tmp_path, {"rationale": "Valid", "suggestions": []})
    owner, project = uuid4(), uuid4()

    async def operation():
        result = await ModelTeamProposalAdapter(generator).propose(
            fixtures.team_fixtures.build_request()
        )
        version = SimpleNamespace(
            project_id=project,
            created_by_user_id=uuid4() if mismatch == "owner" else owner,
            content_hash="f" * 64 if mismatch == "hash" else result.proposal.content_hash,
        )
        unit = (
            SimpleNamespace()
            if mismatch == "missing_repository"
            else SimpleNamespace(proposal_evidence=None)
        )
        await bind_model_artifacts(unit, "AGENT_TEAM", (version,))
        return result

    with pytest.raises(ProposalEvidenceError):
        asyncio.run(
            Command(MemoryEvidence(), operation).run(owner_user_id=owner, project_id=project)
        )
