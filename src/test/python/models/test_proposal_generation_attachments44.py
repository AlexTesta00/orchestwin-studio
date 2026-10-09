from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import (
    ProposalGenerationError,
    ProposalGenerator,
    ProposalModelConfiguration,
)
from orchestwin.models.structured_generation import (
    GenerationAttachment,
    ModelRuntimeIdentity,
    StructuredGenerationProviderKind,
)
from src.test.python.models.test_hosted_generation import Review, ScriptedPort
from src.test.python.models.test_hosted_support import (
    SpendingEvidence,
    claude_code_document,
    providers,
)

KIND = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
BUDGET = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
SCREENSHOT = GenerationAttachment(
    "screenshot-001.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"synthetic-screenshot-001"
)


def local_configuration(tmp_path):
    return ProposalModelConfiguration(
        base_url="http://127.0.0.1:19451",
        model_name="test-base",
        identity=ModelRuntimeIdentity(
            provider_id="synthetic-http-test",
            runtime_id="contract-test",
            base_model_repository="test/base",
            base_model_revision="a" * 40,
            tokenizer_revision="a" * 40,
            configuration_sha256="b" * 64,
        ),
        token_file=tmp_path / "token.secret",
    )


def claude_code(port, entry="design"):
    return ProposalGenerator(providers(claude_code_document()).hosted_model(entry), port)


def review(generator, *, store=None, purpose="DESIGN_CRITIQUE", **options):
    async def run():
        call = generator.generate(
            task="user-twin-evaluation",
            context={"project_id": str(uuid4()), "purpose": purpose},
            output_type=Review,
            instruction="Read the named screenshot, then review it.",
            **options,
        )
        if store is None:
            return await call
        token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
        try:
            return await call
        finally:
            _SCOPE.reset(token)

    return asyncio.run(run())


def test_a_local_model_refuses_attachments_without_calling_its_port(tmp_path):
    port = ScriptedPort(kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL)
    generator = ProposalGenerator(local_configuration(tmp_path), port)
    with pytest.raises(ProposalGenerationError) as failure:
        review(generator, attachments=(SCREENSHOT,))
    assert failure.value.code == "ATTACHMENTS_UNSUPPORTED"
    assert (failure.value.request, failure.value.result) == (None, None)
    assert port.requests == []


@pytest.mark.parametrize("entry", ["design", "review"])
def test_a_hosted_provider_other_than_claude_code_refuses_attachments_before_any_call(entry):
    port = ScriptedPort()
    store = SpendingEvidence()
    generator = ProposalGenerator(providers().hosted_model(entry), port, BUDGET)
    with pytest.raises(ProposalGenerationError) as failure:
        review(generator, store=store, attachments=[SCREENSHOT])
    assert failure.value.code == "ATTACHMENTS_UNSUPPORTED"
    assert failure.value.request is None
    assert port.requests == [] and store.requests == {} and store.reads == []


def test_claude_code_receives_the_attachments_in_its_request():
    port = ScriptedPort(kind=KIND)
    generator = claude_code(port)
    assert review(generator, attachments=[SCREENSHOT]) == Review(assessment="Clear.")
    [request] = port.requests
    assert request.attachments == (SCREENSHOT,)
    assert [item.reference() for item in request.attachments] == [SCREENSHOT.reference()]
    assert request.to_snapshot()["attachments"] == [SCREENSHOT.reference()]
    assert request.task_id == "proposal-user-twin-evaluation-v1"


def test_claude_code_without_attachments_builds_the_request_of_before():
    port = ScriptedPort(kind=KIND)
    assert review(claude_code(port)) == Review(assessment="Clear.")
    [request] = port.requests
    assert request.attachments == ()
    assert "attachments" not in request.to_snapshot()


def test_the_routing_generator_passes_the_attachments_to_the_routed_generator():
    critique, general = ScriptedPort(kind=KIND), ScriptedPort()
    router = RoutingProposalGenerator(
        {
            "critique": claude_code(critique),
            "general": ProposalGenerator(providers().hosted_model("general"), general),
        },
        ModelRoutes(default="general", purposes={"DESIGN_CRITIQUE": "critique"}),
    )
    assert review(router, attachments=(SCREENSHOT,)) == Review(assessment="Clear.")
    assert critique.requests[0].attachments == (SCREENSHOT,)
    with pytest.raises(ProposalGenerationError, match="ATTACHMENTS_UNSUPPORTED"):
        review(router, purpose="DESIGN_TWIN_REVIEW", attachments=(SCREENSHOT,))
    assert general.requests == []
