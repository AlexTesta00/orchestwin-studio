"""Contract tests with synthetic HTTP completions, never real inference evidence."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.agents.selection_rules import TeamRoleConstraintKind
from orchestwin.models.model_proposals import (
    ModelDesignAdapter,
    ModelRequirementsAdapter,
    ModelTeamProposalAdapter,
    ModelUserModelingAdapter,
)
from orchestwin.models.openai_compatible import (
    OpenAICompatibleHttpResponse,
    OpenAICompatibleLocalConfig,
    OpenAICompatibleLocalStructuredAdapter,
    OpenAICompatibleTimeoutError,
)
from orchestwin.models.proposal_generation import (
    ProposalGenerationError,
    ProposalGenerator,
    ProposalModelConfiguration,
    ProposalRuntimeConfigurationError,
    build_proposal_generator,
    wire_value,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.models.user_modeling import (
    PersonaProposalRequest,
    UserModelingBriefInput,
    UserTwinProposalRequest,
)
from orchestwin.twins.epistemics import (
    HumanValidationRequirement,
)

from . import test_fake_design as design_fixtures
from . import test_fake_requirements as requirements_fixtures
from . import test_fake_team_proposal_adapter as team_fixtures
from . import test_user_modeling as user_fixtures


class CompletionTransport:
    def __init__(self, identity, output, *, status=200, finish="stop", drift=False, timeout=False):
        self.identity, self.output, self.calls = identity, output, []
        self.status, self.finish, self.drift, self.timeout = status, finish, drift, timeout

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.timeout:
            raise OpenAICompatibleTimeoutError("synthetic timeout")
        identity = self.identity.to_snapshot()
        if self.drift:
            identity["runtime_id"] = "different-runtime"
        output = self.output
        payload = {
            "id": "synthetic-completion",
            "model_identity": identity,
            "choices": [
                {
                    "finish_reason": self.finish,
                    "message": {
                        "content": json.dumps(output),
                        "role": "assistant",
                    },
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        return OpenAICompatibleHttpResponse(self.status, json.dumps(payload).encode(), 12)


def make_generator(tmp_path, output, **options):
    identity = ModelRuntimeIdentity(
        provider_id="synthetic-http-test",
        runtime_id="contract-test",
        base_model_repository="test/base",
        base_model_revision="a" * 40,
        tokenizer_revision="a" * 40,
        configuration_sha256="b" * 64,
    )
    config = ProposalModelConfiguration(
        base_url="http://127.0.0.1:19451",
        model_name="test-base",
        identity=identity,
        token_file=tmp_path / "token.secret",
    )
    transport = CompletionTransport(identity, output, **options)
    port = OpenAICompatibleLocalStructuredAdapter(
        config=OpenAICompatibleLocalConfig(
            base_url=config.base_url, model_name=config.model_name, expected_identity=identity
        ),
        transport=transport,
    )
    return ProposalGenerator(config, port), transport


def test_team_calls_model_and_preserves_mandatory_constraints(tmp_path):
    request = team_fixtures.build_request()
    optional = next(
        item.agent_id
        for item in request.constraints.role_constraints
        if item.kind is TeamRoleConstraintKind.OPTIONAL
    )
    generator, transport = make_generator(
        tmp_path,
        {
            "rationale": "A bounded team is appropriate.",
            "suggestions": [
                {"agent_id": optional.value, "rationale": "Review cross-component integration."}
            ],
        },
    )
    result = asyncio.run(ModelTeamProposalAdapter(generator).propose(request))
    assert result.proposal.provider_kind.value == "MODEL_ADAPTER"
    assert result.proposal.suggested_agent_ids == (optional,)
    assert result.proposal.mandatory_agent_ids == request.constraints.mandatory_agent_ids
    assert len(transport.calls) == 1
    call = transport.calls[0]["payload"]
    assert call["temperature"] == 0.6
    assert (
        call["metadata"]["expected_model_identity"]
        == generator.configuration.identity.to_snapshot()
    )
    assert "output_schema" in json.loads(call["messages"][1]["content"])


@pytest.mark.parametrize(
    "options,code",
    [
        ({"timeout": True}, "TIMEOUT"),
        ({"status": 503}, "PROVIDER_UNAVAILABLE"),
        ({"drift": True}, "IDENTITY_MISMATCH"),
        ({"finish": "length"}, "INCOMPLETE_OUTPUT"),
    ],
)
def test_failure_is_not_retried_or_replaced_by_fake(tmp_path, options, code):
    generator, transport = make_generator(
        tmp_path, {"rationale": "Valid", "suggestions": []}, **options
    )
    with pytest.raises(ProposalGenerationError, match=code):
        asyncio.run(ModelTeamProposalAdapter(generator).propose(team_fixtures.build_request()))
    assert len(transport.calls) == 1


def test_team_ignores_redundant_mandatory_suggestions(tmp_path):
    request = team_fixtures.build_request()
    generator, _ = make_generator(
        tmp_path,
        {
            "rationale": "Redundant selection",
            "suggestions": [
                {
                    "agent_id": request.constraints.mandatory_agent_ids[0].value,
                    "rationale": "Duplicate role",
                }
            ],
        },
    )
    result = asyncio.run(ModelTeamProposalAdapter(generator).propose(request))
    assert result.proposal.suggested_agent_ids == ()
    assert result.proposal.mandatory_agent_ids == request.constraints.mandatory_agent_ids


@pytest.mark.parametrize("stage", ["requirements", "design"])
def test_stage_deserializes_real_contract_and_binds_context(tmp_path, stage):
    fixtures, adapter_type, output_key = {
        "requirements": (requirements_fixtures, ModelRequirementsAdapter, "specification"),
        "design": (design_fixtures, ModelDesignAdapter, "package"),
    }[stage]
    request = fixtures.proposal_request()
    fake_type = getattr(fixtures, f"FakeDeterministic{stage.title()}Adapter")
    # Domain-valid fixtures simulate HTTP output only; production does not import fakes.
    expected = getattr(asyncio.run(fake_type().propose(request)), output_key)
    if stage == "design":
        expected = replace(
            expected,
            critiques=tuple(
                replace(
                    critique,
                    provenance=next(
                        twin.observations[0].provenance
                        for twin in request.user_modeling.user_twins
                        if twin.reference == critique.user_twin_reference
                    ),
                )
                for critique in expected.critiques
            ),
        )
    from .draft_fixtures import proposal_draft

    output = proposal_draft(stage, expected, request)
    generator, transport = make_generator(tmp_path, output)
    result = asyncio.run(adapter_type(generator).propose(request))
    actual = getattr(result, output_key)
    if stage == "requirements":
        assert actual.project_brief_reference == request.brief.reference
        assert [x.statement for x in actual.requirements] == [
            x.statement for x in expected.requirements
        ]
        assert [x.sources for x in actual.requirements] == [
            x.sources for x in expected.requirements
        ]
    elif stage == "design":
        assert actual.grounding == expected.grounding
        assert [x.summary for x in actual.alternatives] == [
            x.summary for x in expected.alternatives
        ]
        assert actual.owner_selected_alternative_id is None
        assert actual.prototype is None
        assert all(
            any(ref.source_id == generator.provider_id for ref in x.provenance.references)
            for x in actual.critiques
        )
    assert result.provider_kind.value == "MODEL_ADAPTER"
    assert len(transport.calls) == 1
    output["project_id"] = str(uuid4())
    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        asyncio.run(adapter_type(generator).propose(request))


def test_nested_extra_fields_are_rejected(tmp_path):
    request = requirements_fixtures.proposal_request()
    expected = asyncio.run(
        requirements_fixtures.FakeDeterministicRequirementsAdapter().propose(request)
    )
    from .draft_fixtures import proposal_draft

    output = proposal_draft("requirements", expected.specification, request)
    output["requirements"][0]["fabricated_evidence"] = "passes"
    generator, _ = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        asyncio.run(ModelRequirementsAdapter(generator).propose(request))


def persona_input_output(version=None):
    version = version or user_fixtures.brief_version()
    candidates = user_fixtures.derive_project_persona_candidates(
        brief_version=version, brief_gate=user_fixtures.approved_gate(version)
    ).candidates
    request = PersonaProposalRequest(
        user_fixtures.PROJECT_ID, candidates, UserModelingBriefInput.from_version(version)
    )
    proposed = asyncio.run(
        user_fixtures.FakeDeterministicUserModelingAdapter().propose_personas(request)
    )
    return request, {
        "proposals": [
            {
                "candidate_ordinal": proposal.candidate_ordinal,
                "name": proposal.profile.name,
                "observations": [
                    {
                        "observation_key": item.observation_key,
                        "value": wire_value(item.value),
                        "confidence": item.confidence.value,
                        "rationale": item.rationale,
                    }
                    for item in proposal.profile.observations
                    if item.observation_key != "persona.role"
                ],
            }
            for proposal in proposed.proposals
        ]
    }


def test_personas_preserve_exact_role_and_label_model_inferences(tmp_path):
    request, output = persona_input_output()
    generator, transport = make_generator(tmp_path, output)
    result = asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    sent = json.loads(transport.calls[0]["payload"]["messages"][1]["content"])
    assert [item["candidate_content_hash"] for item in sent["context"]["candidates"]] == [
        item.content_hash for item in request.candidates
    ]
    assert result.provider_kind.value == "MODEL_ADAPTER"
    proposal, candidate = result.proposals[0], request.candidates[0]
    profile = proposal.profile
    assert proposal.candidate_content_hash == candidate.content_hash
    assert profile.confirmation_status.value == "PENDING_CONFIRMATION"
    assert profile.source.value == "SYSTEM_PROPOSED"
    assert profile.kind.value == "PROTO_PERSONA"
    assert profile.rejection_reason is None
    assert profile.observations[0] is candidate.role_observation
    for item in profile.observations[1:]:
        assert item.epistemic_status.value == "MODEL_INFERRED"
        assert item.human_validation is HumanValidationRequirement.REQUIRED
        assert item.provenance.references[:-2] == candidate.role_observation.provenance.references
        assert (
            item.provenance.references[-2].content_hash
            == request.project_brief.reference.content_hash
        )
        assert item.provenance.references[-2].locator == "brief"
        assert item.provenance.references[-1].source_id == generator.provider_id
        assert item.provenance.references[-1].source_kind.value == "MODEL_OUTPUT"
    payload = transport.calls[0]["payload"]
    assert payload["response_format"]["json_schema"]["name"] == "proposal-personas-v4"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-personas-v4"
    schema = json.dumps(sent["output_schema"])
    assert all(key not in schema for key in ("candidate_content_hash", "provenance", "source_kind"))


@pytest.mark.parametrize(
    "change",
    ["hash", "approval", "source", "epistemic", "human_validation", "provenance", "role"],
)
def test_persona_drafts_cannot_invent_governance_metadata(tmp_path, change):
    request, output = persona_input_output()
    draft = output["proposals"][0]
    if change == "hash":
        draft["candidate_content_hash"] = "f" * 64
    elif change == "approval":
        draft["confirmation_status"] = "CONFIRMED"
    elif change == "source":
        draft["source"] = "OWNER_PROVIDED"
    elif change == "epistemic":
        draft["observations"][0]["epistemic_status"] = "HUMAN_VALIDATED"
    elif change == "human_validation":
        draft["observations"][0]["human_validation"] = "NOT_REQUIRED"
    elif change == "provenance":
        draft["observations"][0]["provenance"] = {"references": []}
    else:
        draft["observations"].insert(0, wire_value(request.candidates[0].role_observation))
    generator, transport = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "change",
    ["ordinal", "missing_proposal", "extra_proposal", "missing_field", "order", "confidence"],
)
def test_persona_drafts_require_exact_candidate_and_observation_structure(tmp_path, change):
    request, output = persona_input_output()
    draft = output["proposals"][0]
    if change == "ordinal":
        draft["candidate_ordinal"] += 1
    elif change == "missing_proposal":
        output["proposals"].clear()
    elif change == "extra_proposal":
        output["proposals"].append(deepcopy(draft))
    elif change == "missing_field":
        draft["observations"].pop()
    elif change == "order":
        draft["observations"].reverse()
    else:
        draft["observations"][0]["confidence"] = 1.1
    generator, _ = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))


def test_persona_drafts_preserve_multiple_candidate_order(tmp_path):
    version = user_fixtures.brief_version()
    brief = replace(version.brief, target_users=("Hotel receptionist", "Shift manager"))
    request, output = persona_input_output(
        replace(version, brief=brief, content_hash=brief.content_hash)
    )
    candidate, second = request.candidates
    generator, _ = make_generator(tmp_path, output)
    result = asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    assert [item.candidate_content_hash for item in result.proposals] == [
        candidate.content_hash,
        second.content_hash,
    ]
    assert [item.profile.observations[0] for item in result.proposals] == [
        candidate.role_observation,
        second.role_observation,
    ]
    output["proposals"].reverse()
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))


def test_duplicate_persona_candidate_ordinals_fail_without_model_call(tmp_path):
    request, output = persona_input_output()
    request = replace(request, candidates=(request.candidates[0], request.candidates[0]))
    generator, transport = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    assert transport.calls == []


@pytest.mark.parametrize("kind", ["UNKNOWN", "ABSTAINED", "ITEMS"])
def test_persona_content_at_limits_preserves_uncertainty_and_review(tmp_path, kind):
    request, output = persona_input_output()
    observations = output["proposals"][0]["observations"]
    observations[0]["value"]["text"] = "x" * 600
    observations[1]["value"] = {
        "kind": kind,
        "text": None,
        "items": [str(i) + "x" * 199 for i in range(6)] if kind == "ITEMS" else [],
        "reason": "x" * 240 if kind == "ABSTAINED" else None,
    }
    generator, _ = make_generator(tmp_path, output)
    result = asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    profile = result.proposals[0].profile
    assert profile.observations[1].value.text == "x" * 600
    goals = profile.observations[2]
    assert goals.value.kind.value == kind
    assert goals.rationale == observations[1]["rationale"]
    assert goals.epistemic_status.value == "MODEL_INFERRED"
    assert goals.human_validation is HumanValidationRequirement.REQUIRED
    assert profile.confirmation_status.value == "PENDING_CONFIRMATION"


@pytest.mark.parametrize("change", ["text", "item_count", "item_length", "reason"])
def test_persona_content_bounds_are_enforced_before_decoding_and_afterwards(tmp_path, change):
    from orchestwin.models.profile_drafts import PersonaModelOutput

    request, output = persona_input_output()
    draft = output["proposals"][0]
    if change == "text":
        draft["observations"][0]["value"] = {
            "kind": "TEXT",
            "text": "x" * 601,
            "items": [],
            "reason": None,
        }
    elif change.startswith("item"):
        draft["observations"][1]["value"] = {
            "kind": "ITEMS",
            "text": None,
            "items": [str(i) for i in range(7)] if change == "item_count" else ["x" * 201],
            "reason": None,
        }
    else:
        draft["observations"][1]["value"] = {
            "kind": "ABSTAINED",
            "text": None,
            "items": [],
            "reason": "x" * 241,
        }
    with pytest.raises(ValueError):
        PersonaModelOutput.model_validate_json(json.dumps(output))
    generator, transport = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_personas(request))
    definitions = transport.calls[0]["payload"]["response_format"]["json_schema"]["schema"]["$defs"]
    assert definitions["ProfileValueTEXT"]["properties"]["text"]["maxLength"] == 600
    assert definitions["ProfileValueITEMS"]["properties"]["items"]["maxItems"] == 6
    assert definitions["ProfileValueITEMS"]["properties"]["items"]["items"]["maxLength"] == 200
    assert definitions["ProfileValueABSTAINED"]["properties"]["reason"]["maxLength"] == 240


def twin_draft_output(proposals):
    return {
        "proposals": [
            {
                "persona_id": str(proposal.persona_id),
                "name": proposal.profile.name,
                "observations": [
                    {
                        "observation_key": item.observation_key,
                        "value": wire_value(item.value),
                        "confidence": item.confidence.value,
                        "rationale": "Transfer grounded persona context into the twin.",
                    }
                    for item in proposal.profile.observations
                    if item.observation_key != "user_twin.age_range"
                ],
            }
            for proposal in proposals
        ]
    }


def twin_input_output():
    persona = user_fixtures.confirmed_persona_version()
    brief = UserModelingBriefInput.from_version(user_fixtures.brief_version())
    request = UserTwinProposalRequest(
        user_fixtures.PROJECT_ID,
        (persona,),
        brief.reference,
        user_fixtures.TEAM_REFERENCE,
        1,
        user_fixtures.CATALOG_HASH,
        brief,
    )
    expected = asyncio.run(
        user_fixtures.FakeDeterministicUserModelingAdapter().propose_user_twins(request)
    )
    return request, twin_draft_output(expected.proposals)


def test_twins_bind_confirmed_persona_and_current_context(tmp_path):
    request, output = twin_input_output()
    generator, _ = make_generator(tmp_path, output)
    result = asyncio.run(ModelUserModelingAdapter(generator).propose_user_twins(request))
    assert result.provider_kind.value == "MODEL_ADAPTER"
    assert result.proposals[0].profile.validation_status.value == "PROJECT_GROUNDED_UT"
    assert result.proposals[0].profile.agent_team_reference == request.agent_team_reference
    observation = result.proposals[0].profile.observations[0]
    persona = request.persona_versions[0]
    assert observation.provenance.references[0].source_id == f"persona:{persona.persona_id}"
    assert observation.provenance.references[0].content_hash == persona.content_hash
    assert observation.provenance.references[1].source_kind.value == "PROJECT_BRIEF"
    assert (
        observation.provenance.references[1].content_hash
        == request.project_brief_reference.content_hash
    )
    assert observation.provenance.references[2].source_kind.value == "MODEL_OUTPUT"
    assert all(
        o.human_validation is HumanValidationRequirement.REQUIRED
        for o in result.proposals[0].profile.observations
    )
    output["proposals"][0]["persona_id"] = str(uuid4())
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_user_twins(request))


@pytest.mark.parametrize("change", ["approval", "provenance", "missing", "order", "confidence"])
def test_compact_twin_drafts_cannot_bypass_profile_governance(tmp_path, change):
    request, output = twin_input_output()
    profile = output["proposals"][0]
    if change == "approval":
        profile["validation_status"] = "OWNER_APPROVED_UT"
    elif change == "provenance":
        profile["observations"][0]["provenance"] = {"references": []}
    elif change == "missing":
        profile["observations"].pop()
    elif change == "order":
        profile["observations"].reverse()
    else:
        profile["observations"][0]["confidence"] = 1.1
    generator, _ = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError):
        asyncio.run(ModelUserModelingAdapter(generator).propose_user_twins(request))


@pytest.mark.parametrize("stage", ["team", "user_modeling", "requirements", "design"])
def test_model_runtime_requires_explicit_configuration(monkeypatch, stage):
    import importlib

    monkeypatch.delenv("ORCHESTWIN_PROPOSAL_MODEL_CONFIG_FILE", raising=False)
    name = "runtime" if stage == "team" else f"{stage}_runtime"
    module = importlib.import_module(f"orchestwin.models.{name}")
    prefix = (
        "TeamProposal" if stage == "team" else "".join(word.title() for word in stage.split("_"))
    )
    settings_type = getattr(module, f"{prefix}RuntimeSettings")
    settings = settings_type(
        **(
            {"provider": "MODEL_ADAPTER", "_env_file": None}
            if stage == "team"
            else {"mode": "MODEL_ADAPTER"}
        )
    )
    factory = getattr(
        module, "create_team_proposal_port" if stage == "team" else f"build_{stage}_proposal_port"
    )
    with pytest.raises(ProposalRuntimeConfigurationError, match="not configured"):
        factory(settings)


def test_explicit_model_configuration_loads_without_network(tmp_path):
    generator, _ = make_generator(tmp_path, {})
    config = generator.configuration
    config.token_file.write_text("t" * 48, encoding="ascii")
    path = tmp_path / "runtime.json"
    path.write_text(config.model_dump_json(), encoding="utf-8")
    configured = build_proposal_generator(path)
    assert configured.configuration.identity == config.identity
    assert "t" * 48 not in repr(configured)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:80",
        "http://localhost:80",
        "http://127.0.0.1:80/path",
        "http://secret@127.0.0.1:80",
        "http://127.0.0.1:80?x=1",
    ],
)
def test_model_configuration_rejects_unbound_endpoints(tmp_path, url):
    generator, _ = make_generator(tmp_path, {})
    values = generator.configuration.model_dump()
    values["base_url"] = url
    with pytest.raises(ValueError):
        ProposalModelConfiguration(**values)


@pytest.mark.parametrize("stage", ["requirements", "design"])
def test_compact_planning_requests_remain_bound_to_project_and_exact_context(tmp_path, stage):
    from .draft_fixtures import proposal_draft

    source, adapter_type, key = {
        "requirements": (requirements_fixtures, ModelRequirementsAdapter, "specification"),
        "design": (design_fixtures, ModelDesignAdapter, "package"),
    }[stage]
    request = source.proposal_request()
    expected = getattr(
        asyncio.run(getattr(source, f"FakeDeterministic{stage.title()}Adapter")().propose(request)),
        key,
    )
    generator, transport = make_generator(tmp_path, proposal_draft(stage, expected, request))
    asyncio.run(adapter_type(generator).propose(request))
    context = json.loads(transport.calls[0]["payload"]["messages"][1]["content"])["context"]
    assert context["project_id"] == str(request.project_id)
    assert context["governed_request_hash"] == request.content_hash


@pytest.mark.parametrize("change", ["source", "twin", "internal_link", "owner_claim", "duplicate"])
def test_requirements_drafts_reject_invented_evidence_links_and_approval(tmp_path, change):
    from .draft_fixtures import proposal_draft

    request = requirements_fixtures.proposal_request()
    expected = asyncio.run(
        requirements_fixtures.FakeDeterministicRequirementsAdapter().propose(request)
    ).specification
    output = proposal_draft("requirements", expected, request)
    if change == "source":
        output["requirements"][0]["sources"] = ["brief:invented"]
    elif change == "twin":
        output["user_stories"][0]["twin"] = "T99"
    elif change == "internal_link":
        output["user_stories"][0]["requirements"] = ["REQ-999"]
    elif change == "owner_claim":
        output["risks"][0]["review_status"] = "OWNER_ACKNOWLEDGED"
    else:
        output["requirements"].append(output["requirements"][0])
    generator, _ = make_generator(tmp_path, output)
    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        asyncio.run(ModelRequirementsAdapter(generator).propose(request))


def test_prompt_beyond_the_context_window_is_blocked_before_any_model_call(tmp_path):
    generator, transport = make_generator(tmp_path, {"rationale": "Valid", "suggestions": []})
    narrow = ProposalGenerator(
        generator.configuration.model_copy(update={"context_window_tokens": 8448}), generator.port
    )
    with pytest.raises(ProposalGenerationError, match="CONTEXT_BUDGET_EXCEEDED"):
        asyncio.run(ModelTeamProposalAdapter(narrow).propose(team_fixtures.build_request()))
    assert transport.calls == []
