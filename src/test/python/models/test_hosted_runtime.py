from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import anthropic
import pytest

from orchestwin.models import real_runtime
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.real_runtime import RealModelRuntimeError, build_real_model_runtime
from orchestwin.models.serialized_generation import SerializedGenerationPort
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from src.test.python.models.test_hosted_generation import Review
from src.test.python.models.test_hosted_support import (
    ANTHROPIC_KEY_ENV,
    CLAUDE_CODE_PRICES,
    GATEWAY_KEY,
    GATEWAY_KEY_ENV,
    TEST_KEY,
    FakeAnthropicClient,
    FakeClaudeRunner,
    SpendingEvidence,
    claude_answer,
    claude_code_document,
    finished,
    message,
    model_entry,
    model_info,
    providers_document,
    readiness_runner,
    status_error,
)
from src.test.python.models.test_local_evaluator_runtime import (
    configuration as evaluator_configuration,
)
from src.test.python.models.test_proposal_evidence import Command


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, TEST_KEY)
    (tmp_path / ".env").write_text(f"{GATEWAY_KEY_ENV}={GATEWAY_KEY}\n", encoding="utf-8")
    return tmp_path


class ClientFactory:
    def __init__(self, *outcomes, models=None):
        self.outcomes, self.models, self.clients, self.keys = outcomes, models, [], []

    def __call__(self, api_key):
        self.keys.append(api_key)
        client = FakeAnthropicClient(
            *self.outcomes,
            models=self.models
            or {
                "claude-opus-5-5": model_info("claude-opus-5-5"),
                "claude-sonnet-5": model_info("claude-sonnet-5"),
            },
        )
        self.clients.append(client)
        return client


def gateway_fetch(provider, model, api_key):
    assert api_key == GATEWAY_KEY
    return 200, json.dumps({"id": model, "context_window": 2_000_000}).encode()


def write_manifest(tmp_path, document=None, **manifest):
    providers_file = tmp_path / "model-providers.json"
    providers_file.write_text(json.dumps(document or providers_document()), encoding="utf-8")
    path = tmp_path / "models-hosted.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "providers_config_file": str(providers_file),
                "final_evaluator_config_file": None,
                **manifest,
            }
        ),
        encoding="utf-8",
    )
    return path, providers_file


def build(path, factory=None, fetch=gateway_fetch, claude_code_run=None):
    return build_real_model_runtime(
        path,
        env_file=".env",
        anthropic_client_factory=factory or ClientFactory(),
        openai_model_fetch=fetch,
        claude_code_run=claude_code_run,
    )


@pytest.fixture
def keyless(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_a_version_two_manifest_routes_every_adapter_through_one_router(environment):
    path, _ = write_manifest(environment)
    factory = ClientFactory()
    runtime = build(path, factory)
    router = runtime.team.generator
    assert isinstance(router, RoutingProposalGenerator)
    for member in (runtime.user_modeling, runtime.requirements, runtime.design):
        assert member.mode.value == "MODEL_ADAPTER"
        assert member.proposal_port.generator is router
    assert runtime.schema_version == 2
    assert runtime.final_evaluator is None
    assert runtime.budget == GenerationBudget(1_500_000, 10_000_000, 60_000_000)
    assert runtime.proposal_configuration is router.configuration
    design = router.route("design")
    assert isinstance(design, ProposalGenerator) and design.budget is runtime.budget
    assert design.configuration.model == "claude-opus-5-5"
    assert router.route("requirements").configuration.model == "claude-sonnet-5"
    review = router.route("user-twin-evaluation", "DESIGN_TWIN_REVIEW")
    assert review.configuration.provider_kind is (
        StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED
    )
    for generator in router.generators.values():
        assert not isinstance(generator.port, SerializedGenerationPort)
        assert generator.prompted_schemas is design.prompted_schemas
    assert factory.keys == [TEST_KEY] and len(factory.clients) == 1
    assert TEST_KEY not in repr(runtime) and GATEWAY_KEY not in repr(runtime)


def test_the_evaluator_of_a_version_two_manifest_is_optional(environment):
    evaluator_file, _ = evaluator_configuration(environment)
    path, _ = write_manifest(environment, final_evaluator_config_file=str(evaluator_file))
    runtime = build(path)
    assert runtime.final_evaluator.identity["adapter_id"] == "local-trained-candidate"
    assert runtime.final_evaluator.generation_lock is not None
    for generator in runtime.team.generator.generators.values():
        assert not isinstance(generator.port, SerializedGenerationPort)


def test_a_local_entry_keeps_the_shared_lock_and_the_local_rules(environment):
    evaluator_file, base = evaluator_configuration(environment)
    proposal = environment / "proposal.json"
    proposal.write_text(base.model_dump_json(), encoding="utf-8")
    document = providers_document()
    document["providers"].append(
        {"id": "local", "kind": "OPENAI_COMPATIBLE_LOCAL", "config_file": str(proposal)}
    )
    document["models"].append({"id": "tunnel", "provider": "local"})
    document["routes"]["tasks"]["team"] = "tunnel"
    path, _ = write_manifest(environment, document, final_evaluator_config_file=str(evaluator_file))
    runtime = build(path)
    local = runtime.team.generator.route("team")
    assert isinstance(local.port, SerializedGenerationPort)
    assert local.port._lock is runtime.final_evaluator.generation_lock
    assert local.budget is None
    routes = runtime.routes_report()
    assert routes["tasks"]["team"] == {
        "model_entry": "tunnel",
        "provider_kind": "OPENAI_COMPATIBLE_LOCAL",
        "model": base.model_name,
    }
    proposal.write_text(
        base.model_copy(update={"temperature": 0.0}).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(RealModelRuntimeError, match="SAMPLED_BASE_PROPOSAL_MODEL_REQUIRED"):
        build(path)


def test_a_missing_key_stops_the_runtime_with_a_fixed_code(environment, monkeypatch):
    path, _ = write_manifest(environment)
    monkeypatch.delenv(ANTHROPIC_KEY_ENV)
    with pytest.raises(RealModelRuntimeError) as failure:
        build(path)
    assert str(failure.value) == "HOSTED_PROVIDER_API_KEY_MISSING"
    (environment / ".env").write_text(
        f"{GATEWAY_KEY_ENV}={GATEWAY_KEY}\n{ANTHROPIC_KEY_ENV}={TEST_KEY}\n", encoding="utf-8"
    )
    assert build(path).schema_version == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ("providers", "HOSTED_PROVIDERS_CONFIGURATION_INVALID"),
        ("manifest_field", "REAL_MODEL_CONFIGURATION_INVALID"),
        ("relative", "REAL_MODEL_CONFIGURATION_INVALID"),
        ("absent", "REAL_MODEL_CONFIGURATION_FILE_REQUIRED"),
    ],
)
def test_invalid_version_two_files_fail_closed(environment, change, code):
    path, providers_file = write_manifest(environment)
    manifest = json.loads(path.read_text())
    if change == "providers":
        providers_file.write_text('{"schema_version": 1}', encoding="utf-8")
    elif change == "manifest_field":
        manifest["secret_extra_field"] = "must-not-appear"
    elif change == "relative":
        manifest["providers_config_file"] = "model-providers.json"
    else:
        manifest["providers_config_file"] = str(environment / "absent.json")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RealModelRuntimeError) as failure:
        build(path)
    assert str(failure.value) == code


@pytest.mark.parametrize(
    "variable,value",
    [
        ("PROPOSAL_MODEL_CONFIG_FILE", "C:/models/proposal.json"),
        ("FINAL_EVALUATOR_ENABLED", "true"),
        ("FINAL_EVALUATOR_READY_FILE", "C:/models/ready.json"),
        ("DESIGN_MODE", "FAKE_DETERMINISTIC"),
    ],
)
def test_conflicting_overrides_are_refused(environment, monkeypatch, variable, value):
    path, _ = write_manifest(environment)
    monkeypatch.setenv("ORCHESTWIN_" + variable, value)
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CONFLICT"):
        build(path)


async def _schema(_):
    return {"revision": "0062_hosted_model_providers"}


def test_readiness_reports_providers_routes_and_budget_without_inference(environment, monkeypatch):
    monkeypatch.setattr(real_runtime, "_check_schema", _schema)
    path, _ = write_manifest(environment)
    factory = ClientFactory()
    runtime = build(path, factory)
    report = asyncio.run(runtime.check_readiness(None))
    assert report["ready"] is True
    assert report["mode"] == "REAL_REQUIRED" and report["manifest_schema_version"] == 2
    anthropic_component = report["components"]["provider:anthropic"]
    assert anthropic_component == {
        "ready": True,
        "kind": "ANTHROPIC_HOSTED",
        "api_key_env": ANTHROPIC_KEY_ENV,
        "api_key_present": True,
        "api_key_source": "PROCESS",
        "models": {
            "design": {
                "model": "claude-opus-5-5",
                "declared_context_window_tokens": 1_000_000,
                "declared_max_output_tokens": 128_000,
                "ready": True,
            },
            "general": {
                "model": "claude-sonnet-5",
                "declared_context_window_tokens": 1_000_000,
                "declared_max_output_tokens": 128_000,
                "ready": True,
            },
        },
    }
    gateway = report["components"]["provider:gateway"]
    assert gateway["api_key_source"] == "DOTENV" and gateway["ready"] is True
    assert gateway["models"]["review"]["declared_context_window_tokens"] == 2_000_000
    assert report["components"]["database"]["ready"] is True
    assert "evaluator" not in report["components"] and report["evaluator_configured"] is False
    assert sorted(report["routes"]["tasks"]) == sorted(TASKS)
    assert report["routes"]["tasks"]["design"] == {
        "model_entry": "design",
        "provider_kind": "ANTHROPIC_HOSTED",
        "model": "claude-opus-5-5",
    }
    assert report["routes"]["tasks"]["team"]["model"] == "claude-sonnet-5"
    assert report["routes"]["purposes"]["DESIGN_TWIN_REVIEW"]["model_entry"] == "review"
    assert report["budget"] == {
        "currency": "USD",
        "per_generation_microusd": 1_500_000,
        "per_project_microusd": 10_000_000,
        "total_microusd": 60_000_000,
        "spent_total_microusd": None,
        "remaining_total_microusd": None,
        "period_start": None,
    }
    assert report["generation_performed"] is False
    serialized = json.dumps(report)
    assert TEST_KEY not in serialized and GATEWAY_KEY not in serialized
    assert factory.clients[0].messages.calls == []


def test_readiness_fails_when_a_provider_does_not_serve_a_model(environment, monkeypatch):
    monkeypatch.setattr(real_runtime, "_check_schema", _schema)
    path, _ = write_manifest(environment)
    factory = ClientFactory(
        models={
            "claude-opus-5-5": model_info("claude-opus-5-5"),
            "claude-sonnet-5": status_error(anthropic.NotFoundError, 404),
        }
    )
    report = asyncio.run(build(path, factory).check_readiness(None))
    component = report["components"]["provider:anthropic"]
    assert report["ready"] is False and component["ready"] is False
    assert component["models"]["general"] == {
        "model": "claude-sonnet-5",
        "ready": False,
        "code": "HOSTED_MODEL_NOT_FOUND",
    }


def test_the_spent_total_comes_from_the_evidence_store(environment, monkeypatch):
    monkeypatch.setattr(real_runtime, "_check_schema", _schema)
    path, _ = write_manifest(environment)
    runtime = build(path)
    calls = []

    class Store:
        def __init__(self, session_factory):
            calls.append(session_factory)

        async def spent_microusd(self, *, project_id=None, since=None):
            return 2_500_000

    from orchestwin.models import proposal_evidence_persistence

    monkeypatch.setattr(proposal_evidence_persistence, "SqlAlchemyProposalEvidenceStore", Store)
    report = asyncio.run(runtime.check_readiness("session-factory"))
    assert report["budget"]["spent_total_microusd"] == 2_500_000
    assert report["budget"]["remaining_total_microusd"] == 57_500_000
    assert calls == ["session-factory"]


def test_changed_files_require_recomposition(environment):
    path, providers_file = write_manifest(environment)
    runtime = build(path, ClientFactory(message(model="claude-sonnet-5")))
    with providers_file.open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CHANGED"):
        asyncio.run(runtime.check_readiness(None))
    command = Command(
        SpendingEvidence(),
        lambda: runtime.team.generator.generate(
            task="team", context={"project_id": "p"}, output_type=Review, instruction="Review."
        ),
    )
    with pytest.raises(RealModelRuntimeError, match="CONFIGURATION_CHANGED"):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))


def test_hosted_generations_run_concurrently(environment):
    path, _ = write_manifest(environment)
    active = {"now": 0, "peak": 0}

    def outcome():
        async def answer():
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            await asyncio.sleep(0.05)
            active["now"] -= 1
            return message({"assessment": "Clear."}, model="claude-sonnet-5")

        return answer

    runtime = build(path, ClientFactory(outcome(), outcome()))

    async def operation():
        review = await runtime.team.generator.generate(
            task="team", context={"project_id": "p"}, output_type=Review, instruction="Review."
        )
        return SimpleNamespace(status=SimpleNamespace(value="REVIEWED"), review=review)

    async def run():
        commands = [Command(SpendingEvidence(), operation) for _ in range(2)]
        return await asyncio.gather(
            *(command.run(owner_user_id=uuid4(), project_id=uuid4()) for command in commands)
        )

    results = asyncio.run(run())
    assert [item.review.assessment for item in results] == ["Clear.", "Clear."]
    assert active["peak"] == 2


def test_closing_the_runtime_closes_the_provider_clients(environment):
    path, _ = write_manifest(environment)
    factory = ClientFactory()
    runtime = build(path, factory)
    asyncio.run(runtime.close())
    assert factory.clients[0].closed is True


def test_a_version_one_runtime_keeps_its_shape(tmp_path, monkeypatch):
    from src.test.python.models.final_session_support import make_session
    from src.test.python.models.test_model_proposals import make_generator

    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    generator, _ = make_generator(tmp_path, {})
    generator.configuration.token_file.write_text("proposal-secret-" + "t" * 40, encoding="ascii")
    proposal = tmp_path / "proposal.json"
    proposal.write_text(generator.configuration.model_dump_json(), encoding="utf-8")
    final = make_session(tmp_path / "final")
    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_config_file": str(proposal),
                "final_evaluator_ready_file": str(final.ready_path),
            }
        ),
        encoding="utf-8",
    )
    runtime = build_real_model_runtime(manifest)
    assert runtime.schema_version == 1
    assert runtime.budget is None and runtime.providers is None and runtime.routes_report() is None
    assert runtime.billing is None
    assert isinstance(runtime.team.generator, ProposalGenerator)
    assert isinstance(runtime.team.generator.port, SerializedGenerationPort)


def review_generation(router, **options):
    return router.generate(
        task="team",
        context={"project_id": "p"},
        output_type=Review,
        instruction="Review.",
        **options,
    )


def test_a_manifest_with_only_claude_code_builds_without_any_api_key(keyless):
    program = str(keyless / "claude-synthetic")
    path, _ = write_manifest(keyless, claude_code_document(executable=program))
    factory = ClientFactory()
    runner = FakeClaudeRunner(finished(claude_answer({"assessment": "Clear."})))
    runtime = build(path, factory, claude_code_run=runner)
    assert factory.keys == [] and runtime._clients == ()
    assert runtime.billing == "SUBSCRIPTION"
    router = runtime.team.generator
    design = router.route("design")
    assert design.configuration.provider_kind is StructuredGenerationProviderKind.CLAUDE_CODE_CLI
    assert design.budget is runtime.budget and not isinstance(design.port, SerializedGenerationPort)
    assert runtime.routes_report()["tasks"]["design"] == {
        "model_entry": "design",
        "provider_kind": "CLAUDE_CODE_CLI",
        "model": "claude-opus-5-5",
    }
    assert asyncio.run(review_generation(router)) == Review(assessment="Clear.")
    [call] = runner.calls
    assert call.arguments[:2] == [program, "--print"]
    assert call.arguments[call.arguments.index("--effort") + 1] == "medium"


def test_the_claude_code_readiness_reports_the_contract_keys_without_inference(
    keyless, monkeypatch
):
    monkeypatch.setattr(real_runtime, "_check_schema", _schema)
    program = str(keyless / "claude-synthetic")
    path, _ = write_manifest(keyless, claude_code_document(executable=program))
    runner = readiness_runner()
    report = asyncio.run(build(path, claude_code_run=runner).check_readiness(None))
    assert report["ready"] is True
    assert set(report["components"]) == {"provider:claude-code", "database"}
    assert report["components"]["provider:claude-code"] == {
        "ready": True,
        "kind": "CLAUDE_CODE_CLI",
        "executable": program,
        "version": "2.1.286",
        "logged_in": True,
        "subscription": "max",
        "models": {
            "design": {"model": "claude-opus-5-5", "ready": True},
            "general": {"model": "claude-opus-5-5", "ready": True},
        },
    }
    assert [call.arguments[1:] for call in runner.calls] == [["--version"], ["auth", "status"]]
    assert report["routes"]["tasks"]["requirements"]["provider_kind"] == "CLAUDE_CODE_CLI"
    assert report["budget"]["total_microusd"] == 60_000_000
    assert report["generation_performed"] is False


def test_a_program_that_cannot_be_found_is_reported_and_fails_the_generation(keyless, monkeypatch):
    monkeypatch.setattr(real_runtime, "_check_schema", _schema)
    (keyless / "empty").mkdir()
    monkeypatch.setenv("PATH", str(keyless / "empty"))
    path, _ = write_manifest(keyless, claude_code_document())
    runner = FakeClaudeRunner()
    runtime = build(path, claude_code_run=runner)
    report = asyncio.run(runtime.check_readiness(None))
    component = report["components"]["provider:claude-code"]
    assert report["ready"] is False and component["ready"] is False
    assert (component["code"], component["executable"], component["version"]) == (
        "CLAUDE_CODE_NOT_FOUND",
        None,
        None,
    )
    with pytest.raises(ProposalGenerationError, match="PROVIDER_UNAVAILABLE"):
        asyncio.run(review_generation(runtime.team.generator, retry_transient_failures=False))
    assert runner.calls == []


def test_billing_reports_api_mixed_and_subscription_routes(environment):
    path, _ = write_manifest(environment)
    assert build(path).billing == "API"
    document = providers_document()
    document["providers"].append(
        {
            "id": "claude-code",
            "kind": "CLAUDE_CODE_CLI",
            "executable": str(environment / "claude-synthetic"),
        }
    )
    document["models"].append(
        model_entry(
            "subscription", "claude-code", "claude-opus-5-5", prices=dict(CLAUDE_CODE_PRICES)
        )
    )
    document["routes"]["tasks"]["design"] = "subscription"
    path, _ = write_manifest(environment, document)
    mixed = build(path)
    assert mixed.billing == "MIXED"
    checks = {check.provider_id: type(check).__name__ for check in mixed._hosted_checks}
    assert checks == {
        "anthropic": "HostedProviderCheck",
        "gateway": "HostedProviderCheck",
        "claude-code": "ClaudeCodeProviderCheck",
    }
    document["routes"] = {"default": "subscription", "tasks": {}, "purposes": {}}
    path, _ = write_manifest(environment, document)
    assert build(path).billing == "SUBSCRIPTION"


def test_a_priced_subscription_model_stops_the_runtime(keyless):
    document = claude_code_document(executable=str(keyless / "claude-synthetic"))
    document["models"][0]["prices"]["output"] = "1.00"
    path, _ = write_manifest(keyless, document)
    with pytest.raises(RealModelRuntimeError) as failure:
        build(path)
    assert str(failure.value) == "SUBSCRIPTION_MODEL_PRICED"
