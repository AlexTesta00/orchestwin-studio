from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from orchestwin.api.design_mockups import GENERATED_OUTPUT_TOKENS
from orchestwin.models.generation_budget import cost_microusd
from orchestwin.models.hosted_configuration import (
    HOSTED_PROVIDER_KINDS,
    HOSTED_RUNTIME_IDS,
    HOSTED_TEMPERATURE,
    PROVIDERS_CONFIGURATION_MAX_BYTES,
    HostedConfigurationError,
    ProviderKeySource,
    declared_limits_problem,
    hosted_identity,
    load_providers_configuration,
    parse_providers_configuration,
    read_provider_keys,
    served_model_matches,
    usd_to_microusd,
)
from orchestwin.models.model_proposals import HOSTED_DESIGN_OUTPUT_TOKENS
from orchestwin.models.proposal_tasks import TASKS
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.models.test_hosted_support import (
    ANTHROPIC_KEY_ENV,
    CLAUDE_CODE_EXAMPLE,
    CLAUDE_CODE_PRICES,
    EXAMPLE_PROVIDERS,
    GATEWAY_KEY,
    GATEWAY_KEY_ENV,
    TEST_KEY,
    changed,
    claude_code_document,
    model_entry,
    providers,
    providers_document,
)
from src.test.python.models.test_model_proposals import make_generator

LOCAL_CONFIG_FILE = (EXAMPLE_PROVIDERS.parent / "proposal.json").as_posix()


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.delenv(ANTHROPIC_KEY_ENV, raising=False)
    monkeypatch.delenv(GATEWAY_KEY_ENV, raising=False)
    monkeypatch.chdir(tmp_path)


def test_the_example_file_routes_design_to_opus_design_and_every_other_task_to_opus():
    configuration, raw = load_providers_configuration(EXAMPLE_PROVIDERS)
    assert raw == EXAMPLE_PROVIDERS.read_bytes()
    assert [item.id for item in configuration.models] == ["opus-design", "opus", "sonnet"]
    assert configuration.routes.model_dump() == {
        "default": "opus",
        "tasks": {"design": "opus-design"},
        "purposes": {},
    }
    purposes = (None, "DESIGN_ALTERNATIVES_HOSTED", "DESIGN_ITERATION", "DESIGN_TWIN_REVIEW")
    assert {configuration.route("design", purpose) for purpose in purposes} == {"opus-design"}
    assert {configuration.route(task) for task in TASKS - {"design"}} == {"opus"}
    assert "sonnet" not in configuration.routes.targets()
    design = configuration.hosted_model("opus-design")
    assert (design.model, design.effort, design.max_output_tokens) == (
        "claude-opus-5-5",
        "high",
        64000,
    )
    assert (design.reasoning_allowance_tokens, design.timeout_seconds) == (64000, 1200)
    opus = configuration.hosted_model("opus")
    assert (opus.model, opus.effort, opus.max_output_tokens) == ("claude-opus-5-5", "medium", 64000)
    assert (opus.reasoning_allowance_tokens, opus.timeout_seconds) == (12000, 900)
    assert design.prices == opus.prices
    sonnet = configuration.hosted_model("sonnet")
    assert (sonnet.model, sonnet.effort, sonnet.max_output_tokens) == (
        "claude-sonnet-5",
        "medium",
        32000,
    )
    budget = configuration.budget
    assert (budget.per_generation_microusd, budget.per_project_microusd, budget.total_microusd) == (
        2_500_000,
        10_000_000,
        60_000_000,
    )
    assert budget.period_start is None
    largest = design.max_tokens(max(GENERATED_OUTPUT_TOKENS, HOSTED_DESIGN_OUTPUT_TOKENS))
    assert largest == 96_000
    estimate = cost_microusd(input_tokens=70_000, output_tokens=largest, prices=design.prices)
    assert estimate == 2_200_000
    assert estimate <= budget.per_generation_microusd


def test_routes_resolve_purpose_then_task_then_default():
    configuration = providers()
    assert configuration.route("design") == "design"
    assert configuration.route("design", "DESIGN_TWIN_REVIEW") == "review"
    assert configuration.route("user-twin-evaluation", "DESIGN_TWIN_REVIEW") == "review"
    assert configuration.route("requirements") == "general"
    assert configuration.route("requirements", "UNROUTED_PURPOSE") == "general"


def test_a_resolved_entry_answers_the_attributes_read_by_the_call_sites():
    configuration = providers().hosted_model("design")
    assert configuration.provider_kind is StructuredGenerationProviderKind.ANTHROPIC_HOSTED
    assert configuration.temperature == HOSTED_TEMPERATURE
    assert (configuration.context_window_tokens, configuration.max_output_tokens) == (
        1_000_000,
        64_000,
    )
    assert configuration.characters_per_token == 3.0
    assert configuration.prices.output_per_million == Decimal("20.00")
    assert configuration.max_tokens(4096) == 4096 + 16_000
    assert configuration.max_tokens(90_000) == 64_000 + 16_000
    assert configuration.estimated_prompt_tokens(10) == 4
    assert configuration.estimated_prompt_tokens(9) == 3


def test_the_local_configuration_keeps_its_provider_kind(tmp_path):
    generator, _ = make_generator(tmp_path, {})
    assert (
        generator.configuration.provider_kind
        is StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL
    )


def test_hosted_identities_are_derived_from_the_provider_and_model_entries():
    configuration = providers()
    design = configuration.hosted_model("design")
    identity = design.identity
    assert identity.to_snapshot() == {
        "provider_id": "anthropic",
        "runtime_id": "anthropic-messages",
        "base_model_repository": "anthropic/claude-opus-5-5",
        "base_model_revision": "claude-opus-5-5",
        "tokenizer_revision": "provider-managed",
        "configuration_sha256": hashlib.sha256(
            canonical_json(
                {
                    "provider": design.provider.model_dump(mode="json"),
                    "model": design.entry.model_dump(mode="json"),
                }
            ).encode("utf-8")
        ).hexdigest(),
        "adapter_id": None,
        "adapter_sha256": None,
    }
    review = configuration.hosted_model("review").identity
    assert (review.provider_id, review.runtime_id, review.base_model_repository) == (
        "llm.example.com",
        "openai-chat-completions",
        "llm.example.com/example-model-1",
    )
    repriced = providers(
        changed(
            providers_document(),
            lambda document: document["models"][0]["prices"].update(output="21.00"),
        )
    )
    assert repriced.hosted_model("design").identity.configuration_sha256 != (
        identity.configuration_sha256
    )
    assert hosted_identity(design.provider, design.entry) == identity


def _set(path, value):
    def change(document):
        target = document
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return change


def _drop(path):
    def change(document):
        target = document
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]

    return change


REJECTIONS = {
    "unknown top level field": _set(("comment",), "no"),
    "schema version": _set(("schema_version",), 2),
    "boolean schema version": _set(("schema_version",), True),
    "no provider": _set(("providers",), []),
    "no model": _set(("models",), []),
    "duplicate provider": lambda d: d["providers"].append(dict(d["providers"][0])),
    "duplicate model": lambda d: d["models"].append(dict(d["models"][0])),
    "unknown provider kind": _set(("providers", 0, "kind"), "OPENAI_HOSTED"),
    "invalid identifier": _set(("models", 0, "id"), "Design Entry"),
    "key variable outside the namespace": _set(
        ("providers", 0, "api_key_env"), "ANTHROPIC_API_KEY"
    ),
    "key variable without suffix": _set(("providers", 0, "api_key_env"), "ORCHESTWIN_ANTHROPIC"),
    "anthropic base url": _set(("providers", 0, "base_url"), "https://api.anthropic.com"),
    "plain http base url": _set(("providers", 1, "base_url"), "http://llm.example.com"),
    "credentials in base url": _set(
        ("providers", 1, "base_url"), "https://user:pw@llm.example.com"
    ),
    "query in base url": _set(("providers", 1, "base_url"), "https://llm.example.com?x=1"),
    "fragment in base url": _set(("providers", 1, "base_url"), "https://llm.example.com#x"),
    "trailing slash": _set(("providers", 1, "base_url"), "https://llm.example.com/"),
    "missing base url": _drop(("providers", 1, "base_url")),
    "relative completion path": _set(("providers", 1, "completion_path"), "v1/chat"),
    "completion path with query": _set(("providers", 1, "completion_path"), "/v1/chat?x=1"),
    "model with spaces": _set(("models", 0, "model"), "claude opus"),
    "model too long": _set(("models", 0, "model"), "m" * 129),
    "unknown effort": _set(("models", 0, "effort"), "extreme"),
    "window too small": _set(("models", 0, "context_window_tokens"), 1023),
    "window too large": _set(("models", 0, "context_window_tokens"), 2_000_001),
    "window as text": _set(("models", 0, "context_window_tokens"), "1000000"),
    "output too small": _set(("models", 0, "max_output_tokens"), 127),
    "output too large": _set(("models", 0, "max_output_tokens"), 128_001),
    "negative allowance": _set(("models", 0, "reasoning_allowance_tokens"), -1),
    "allowance too large": _set(("models", 0, "reasoning_allowance_tokens"), 64_001),
    "timeout zero": _set(("models", 0, "timeout_seconds"), 0),
    "timeout too long": _set(("models", 0, "timeout_seconds"), 1801),
    "characters per token too small": _set(("models", 0, "characters_per_token"), 0.9),
    "characters per token too large": _set(("models", 0, "characters_per_token"), 8.1),
    "price with five decimals": _set(("models", 0, "prices", "input"), "4.00001"),
    "price as number": _set(("models", 0, "prices", "input"), 4.0),
    "negative price": _set(("models", 0, "prices", "output"), "-1.00"),
    "missing price": _drop(("models", 0, "prices", "cache_write")),
    "model without window": _drop(("models", 0, "context_window_tokens")),
    "unknown model provider": _set(("models", 0, "provider"), "missing"),
    "unused provider": lambda d: d["providers"].append(
        {"id": "spare", "kind": "ANTHROPIC_HOSTED", "api_key_env": "ORCHESTWIN_SPARE_API_KEY"}
    ),
    "unknown default route": _set(("routes", "default"), "missing"),
    "unknown task route target": _set(("routes", "tasks", "design"), "missing"),
    "unknown task name": _set(("routes", "tasks", "architecture"), "design"),
    "unknown purpose target": _set(("routes", "purposes", "DESIGN_TWIN_REVIEW"), "missing"),
    "invalid purpose name": _set(("routes", "purposes", "design review"), "design"),
    "generation above project": _set(("budget", "per_generation_usd"), "10.01"),
    "project above total": _set(("budget", "per_project_usd"), "60.01"),
    "zero budget": _set(("budget", "per_generation_usd"), "0.00"),
    "budget as number": _set(("budget", "total_usd"), 60),
    "budget with seven decimals": _set(("budget", "total_usd"), "60.0000001"),
    "period start as timestamp": _set(("budget", "period_start"), 1_760_000_000),
    "period start with time": _set(("budget", "period_start"), "2026-09-01T00:00:00"),
    "missing budget": _drop(("budget",)),
    "local provider with relative file": lambda d: (
        d["providers"].append(
            {"id": "local", "kind": "OPENAI_COMPATIBLE_LOCAL", "config_file": "proposal.json"}
        )
        or d["models"].append({"id": "tunnel", "provider": "local"})
    ),
    "local provider with a price": lambda d: (
        d["providers"].append(
            {"id": "local", "kind": "OPENAI_COMPATIBLE_LOCAL", "config_file": LOCAL_CONFIG_FILE}
        )
        or d["models"].append({"id": "tunnel", "provider": "local", "prices": dict(PRICES_ANY)})
    ),
    "hosted entry on a local provider": lambda d: (
        d["providers"].append(
            {"id": "local", "kind": "OPENAI_COMPATIBLE_LOCAL", "config_file": LOCAL_CONFIG_FILE}
        )
        or d["models"].append(dict(d["models"][0], id="tunnel", provider="local"))
    ),
    "local entry on a hosted provider": lambda d: d["models"].append(
        {"id": "bare", "provider": "anthropic"}
    ),
}
PRICES_ANY = {"input": "1.00", "output": "1.00", "cache_read": "1.00", "cache_write": "1.00"}


@pytest.mark.parametrize("name", sorted(REJECTIONS))
def test_every_invalid_file_is_rejected_with_one_fixed_code(name):
    document = changed(providers_document(), REJECTIONS[name])
    with pytest.raises(HostedConfigurationError) as failure:
        parse_providers_configuration(json.dumps(document).encode("utf-8"))
    assert failure.value.code == "HOSTED_PROVIDERS_CONFIGURATION_INVALID"
    assert str(failure.value) == "HOSTED_PROVIDERS_CONFIGURATION_INVALID"


def test_a_local_provider_entry_is_accepted_with_an_absolute_file():
    document = providers_document()
    document["providers"].append(
        {"id": "local", "kind": "OPENAI_COMPATIBLE_LOCAL", "config_file": LOCAL_CONFIG_FILE}
    )
    document["models"].append({"id": "tunnel", "provider": "local"})
    document["routes"]["tasks"]["team"] = "tunnel"
    configuration = providers(document)
    assert configuration.route("team") == "tunnel"
    assert [item.id for item in configuration.hosted_providers()] == ["anthropic", "gateway"]
    with pytest.raises(HostedConfigurationError, match="HOSTED_MODEL_ENTRY_REQUIRED"):
        configuration.hosted_model("tunnel")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b'{"schema_version": 1, "schema_version": 1}',
        b"{not json",
        b" " * (PROVIDERS_CONFIGURATION_MAX_BYTES + 1),
    ],
    ids=["empty", "array", "duplicate-key", "broken", "oversized"],
)
def test_malformed_or_oversized_files_are_rejected(raw):
    with pytest.raises(HostedConfigurationError, match="HOSTED_PROVIDERS_CONFIGURATION_INVALID"):
        parse_providers_configuration(raw)


def test_the_file_must_be_an_absolute_readable_path(tmp_path):
    with pytest.raises(HostedConfigurationError, match="PATH_INVALID"):
        load_providers_configuration(EXAMPLE_PROVIDERS.relative_to(EXAMPLE_PROVIDERS.anchor))
    with pytest.raises(HostedConfigurationError, match="UNAVAILABLE"):
        load_providers_configuration(tmp_path / "absent.json")


def test_keys_come_from_the_process_first_then_from_the_dotenv_file(tmp_path, monkeypatch):
    configuration = providers()
    dotenv = tmp_path / "keys.env"
    dotenv.write_text(
        f"{ANTHROPIC_KEY_ENV}=dotenv-{TEST_KEY}\n{GATEWAY_KEY_ENV}={GATEWAY_KEY}\n",
        encoding="utf-8",
    )
    keys = read_provider_keys(configuration, env_file=dotenv)
    assert keys["anthropic"].value == f"dotenv-{TEST_KEY}"
    assert keys["anthropic"].source is ProviderKeySource.DOTENV
    assert keys["gateway"].source is ProviderKeySource.DOTENV
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, f"  {TEST_KEY}  ")
    keys = read_provider_keys(configuration, env_file=dotenv)
    assert keys["anthropic"].value == TEST_KEY
    assert keys["anthropic"].source is ProviderKeySource.PROCESS
    assert keys["anthropic"].env_name == ANTHROPIC_KEY_ENV
    assert TEST_KEY not in repr(keys) and GATEWAY_KEY not in repr(keys)


@pytest.mark.parametrize("value", [None, "", "   ", "two words"])
def test_a_missing_or_blank_key_is_a_fixed_error(tmp_path, monkeypatch, value):
    configuration = providers()
    monkeypatch.setenv(GATEWAY_KEY_ENV, GATEWAY_KEY)
    if value is not None:
        monkeypatch.setenv(ANTHROPIC_KEY_ENV, value)
    with pytest.raises(HostedConfigurationError) as failure:
        read_provider_keys(configuration, env_file=None)
    assert failure.value.code == "HOSTED_PROVIDER_API_KEY_MISSING"
    assert GATEWAY_KEY not in str(failure.value)


def test_no_dotenv_file_is_read_when_it_is_disabled(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"{ANTHROPIC_KEY_ENV}={TEST_KEY}\n", encoding="utf-8")
    monkeypatch.setenv(GATEWAY_KEY_ENV, GATEWAY_KEY)
    with pytest.raises(HostedConfigurationError, match="HOSTED_PROVIDER_API_KEY_MISSING"):
        read_provider_keys(providers(), env_file=None)
    assert read_provider_keys(providers(), env_file=".env")["anthropic"].value == TEST_KEY


def test_served_models_match_the_configured_model_or_a_dated_snapshot():
    assert served_model_matches("claude-sonnet-5", "claude-sonnet-5")
    assert served_model_matches("claude-sonnet-5", "claude-sonnet-5-20260901")
    assert not served_model_matches("claude-sonnet-5", "claude-sonnet-50")
    assert not served_model_matches("claude-sonnet-5", "claude-opus-5-5")
    assert not served_model_matches("claude-sonnet-5", None)


def test_declared_limits_must_cover_the_window_and_the_ceiling_with_the_allowance():
    configuration = providers().hosted_model("design")
    assert (
        declared_limits_problem(
            configuration, context_window_tokens=1_000_000, max_output_tokens=80_000
        )
        is None
    )
    assert (
        declared_limits_problem(configuration, context_window_tokens=None, max_output_tokens=None)
        is None
    )
    assert (
        declared_limits_problem(
            configuration, context_window_tokens=999_999, max_output_tokens=128_000
        )
        == "HOSTED_MODEL_WINDOW_TOO_SMALL"
    )
    assert (
        declared_limits_problem(
            configuration, context_window_tokens=1_000_000, max_output_tokens=79_999
        )
        == "HOSTED_MODEL_OUTPUT_TOO_SMALL"
    )


def test_amounts_convert_to_whole_micro_dollars_and_period_starts_are_dates():
    assert usd_to_microusd("1.50") == 1_500_000
    assert usd_to_microusd("0.0000005") == 1
    document = providers_document()
    document["budget"]["period_start"] = "2026-09-01"
    assert providers(document).budget.period_start == date(2026, 9, 1)


CLAUDE_KIND = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
PROGRAM_FILE = (EXAMPLE_PROVIDERS.parent / "claude").as_posix()


def with_claude_code(document):
    document["providers"].append({"id": "claude-code", "kind": "CLAUDE_CODE_CLI"})
    document["models"].append(
        model_entry(
            "subscription", "claude-code", "claude-opus-5-5", prices=dict(CLAUDE_CODE_PRICES)
        )
    )
    return document


def test_the_claude_code_example_generates_everything_through_the_subscription():
    configuration, raw = load_providers_configuration(CLAUDE_CODE_EXAMPLE)
    assert raw == CLAUDE_CODE_EXAMPLE.read_bytes()
    [provider] = configuration.providers
    assert provider.model_dump(mode="json") == {
        "id": "claude-code",
        "kind": "CLAUDE_CODE_CLI",
        "executable": None,
    }
    assert [item.id for item in configuration.models] == ["opus-design", "opus"]
    assert configuration.routes.model_dump() == {
        "default": "opus",
        "tasks": {"design": "opus-design"},
        "purposes": {},
    }
    design = configuration.hosted_model("opus-design")
    assert (design.model, design.effort, design.context_window_tokens) == (
        "claude-opus-5-5",
        "high",
        1_000_000,
    )
    assert (design.max_output_tokens, design.reasoning_allowance_tokens) == (64_000, 64_000)
    assert (design.timeout_seconds, design.characters_per_token) == (1200, 3.0)
    opus = configuration.hosted_model("opus")
    assert (opus.model, opus.effort, opus.context_window_tokens) == (
        "claude-opus-5-5",
        "medium",
        1_000_000,
    )
    assert (opus.max_output_tokens, opus.reasoning_allowance_tokens) == (64_000, 64_000)
    assert (opus.timeout_seconds, opus.characters_per_token) == (900, 3.0)
    assert design.provider_kind is CLAUDE_KIND and opus.provider_kind is CLAUDE_KIND
    assert design.prices.unpriced and opus.prices.unpriced
    example, _ = load_providers_configuration(EXAMPLE_PROVIDERS)
    assert configuration.budget == example.budget
    assert configuration.billing() == "SUBSCRIPTION"
    assert configuration.hosted_providers() == ()
    assert read_provider_keys(configuration, env_file=None) == {}


def test_a_claude_code_identity_names_the_command_line_and_its_configuration():
    design = providers(claude_code_document()).hosted_model("design")
    assert design.provider.model_dump(mode="json") == {
        "id": "claude-code",
        "kind": "CLAUDE_CODE_CLI",
        "executable": None,
    }
    assert design.identity.to_snapshot() == {
        "provider_id": "claude-code",
        "runtime_id": "claude-code-print",
        "base_model_repository": "claude-code/claude-opus-5-5",
        "base_model_revision": "claude-opus-5-5",
        "tokenizer_revision": "provider-managed",
        "configuration_sha256": hashlib.sha256(
            canonical_json(
                {
                    "provider": design.provider.model_dump(mode="json"),
                    "model": design.entry.model_dump(mode="json"),
                }
            ).encode("utf-8")
        ).hexdigest(),
        "adapter_id": None,
        "adapter_sha256": None,
    }
    assert hosted_identity(design.provider, design.entry) == design.identity
    placed = providers(claude_code_document(executable=PROGRAM_FILE)).hosted_model("design")
    assert placed.provider.executable == Path(PROGRAM_FILE)
    assert placed.identity.configuration_sha256 != design.identity.configuration_sha256
    assert "claude-code-print" in HOSTED_RUNTIME_IDS and CLAUDE_KIND in HOSTED_PROVIDER_KINDS


@pytest.mark.parametrize("price", sorted(CLAUDE_CODE_PRICES))
def test_a_subscription_model_with_a_price_is_refused_with_its_own_code(price):
    document = claude_code_document()
    document["models"][1]["prices"][price] = "0.0001"
    with pytest.raises(HostedConfigurationError) as failure:
        parse_providers_configuration(json.dumps(document).encode("utf-8"))
    assert failure.value.code == "SUBSCRIPTION_MODEL_PRICED"
    assert str(failure.value) == "SUBSCRIPTION_MODEL_PRICED"
    document["models"][1]["prices"][price] = "0.0000"
    assert providers(document).hosted_model("general").prices.unpriced


CLAUDE_CODE_REJECTIONS = {
    "relative program": _set(("providers", 0, "executable"), "bin/claude"),
    "program with parent steps": _set(
        ("providers", 0, "executable"), (EXAMPLE_PROVIDERS.parent / ".." / "claude").as_posix()
    ),
    "program as number": _set(("providers", 0, "executable"), 7),
    "api key variable": _set(("providers", 0, "api_key_env"), "ORCHESTWIN_CLAUDE_API_KEY"),
    "base url": _set(("providers", 0, "base_url"), "https://api.anthropic.com"),
    "provider without models": lambda d: d["providers"].append(
        {"id": "spare", "kind": "CLAUDE_CODE_CLI"}
    ),
    "local entry on the subscription": lambda d: d["models"].append(
        {"id": "bare", "provider": "claude-code"}
    ),
}


@pytest.mark.parametrize("name", sorted(CLAUDE_CODE_REJECTIONS))
def test_every_invalid_claude_code_entry_is_rejected(name):
    document = changed(claude_code_document(), CLAUDE_CODE_REJECTIONS[name])
    with pytest.raises(HostedConfigurationError) as failure:
        parse_providers_configuration(json.dumps(document).encode("utf-8"))
    assert failure.value.code == "HOSTED_PROVIDERS_CONFIGURATION_INVALID"


def test_keys_are_read_only_for_the_providers_that_need_one(monkeypatch):
    configuration = providers(with_claude_code(providers_document()))
    assert [item.id for item in configuration.hosted_providers()] == ["anthropic", "gateway"]
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, TEST_KEY)
    monkeypatch.setenv(GATEWAY_KEY_ENV, GATEWAY_KEY)
    assert sorted(read_provider_keys(configuration, env_file=None)) == ["anthropic", "gateway"]
    assert read_provider_keys(providers(claude_code_document()), env_file=None) == {}


def test_billing_follows_the_kind_of_every_route():
    assert providers().billing() == "API"
    assert providers(claude_code_document()).billing() == "SUBSCRIPTION"
    document = with_claude_code(providers_document())
    assert providers(document).billing() == "API"
    document["routes"]["purposes"]["DESIGN_TWIN_REVIEW"] = "subscription"
    assert providers(document).billing() == "MIXED"
    document["routes"] = {"default": "subscription", "tasks": {}, "purposes": {}}
    assert providers(document).billing() == "SUBSCRIPTION"
