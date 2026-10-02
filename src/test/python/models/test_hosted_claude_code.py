from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from typing import Literal
from uuid import uuid4

import pytest
from pydantic import ConfigDict, create_model

from orchestwin.models.claude_code_cli import (
    CLAUDE_CODE_NOT_FOUND,
    CLAUDE_CODE_NOT_LOGGED_IN,
    CLAUDE_CODE_NOT_ON_SUBSCRIPTION,
    CLAUDE_CODE_URL,
    CLAUDE_VARIABLE,
    MAX_OUTPUT_BYTES,
    MAX_OUTPUT_TOKENS_VARIABLE,
    READINESS_TIMEOUT_SECONDS,
    SYSTEM_PROMPT_FILE,
    ClaudeCodeStructuredAdapter,
    ClaudeCodeTransport,
    build_claude_code_adapter,
    claude_code_executable,
    claude_code_readiness,
    run_process,
)
from orchestwin.models.generation_budget import GenerationBudget, estimated_cost_microusd
from orchestwin.models.hosted_schema import hosted_output_schema, hosted_user_message
from orchestwin.models.openai_compatible import (
    OpenAICompatibleTimeoutError,
    OpenAICompatibleTransportError,
)
from orchestwin.models.proposal_evidence import (
    _SCOPE,
    AuditedProposalTransport,
    ProposalEvidenceScope,
    begin_model_generation,
    retain_provider_result,
)
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
    StructuredOutputMode,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.models.test_hosted_generation import Review
from src.test.python.models.test_hosted_support import (
    CLAUDE_VERSION_LINE,
    REVIEW_SCHEMA,
    VALID_REVIEW,
    FakeClaudeRunner,
    SpendingEvidence,
    claude_answer,
    claude_code_document,
    finished,
    providers,
    readiness_runner,
    structured_request,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

Code = StructuredGenerationFailureCode
KIND = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
STRICT = StructuredOutputMode.STRICT
PROMPTED = StructuredOutputMode.PROMPTED
PROGRAM = "claude-synthetic-program"
BUDGET = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
SYNTHETIC_ENVIRONMENT = {
    "PATH": "/synthetic/bin",
    "HOME": "/synthetic/home",
    "SYNTHETIC_KEPT": "kept",
}
REMOVED = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
OPEN_SCHEMA = {
    "type": "object",
    "properties": {"notes": {"type": "object", "additionalProperties": {"type": "string"}}},
    "required": ["notes"],
    "additionalProperties": False,
}
ITALIAN_SCHEMA = {**REVIEW_SCHEMA, "title": "Revisione — qualità"}
ITALIAN_REVIEW = {"assessment": "Chiaro: «città» è più leggibile.", "score": 0.8, "tags": ["fast"]}
SLEEPER = (
    "import time\n"
    "from pathlib import Path\n"
    "Path(__file__).with_name('started').write_text('yes', encoding='utf-8')\n"
    "time.sleep(120)\n"
)
CHILD = """import json
import os
import sys
from pathlib import Path

expected = json.loads(Path(__file__).with_name("expected.json").read_text(encoding="utf-8"))
arguments = sys.argv[1:]
problems = []
position = arguments.index("--system-prompt-file") + 1
prompt_file = Path(arguments[position])
if arguments[:position] + arguments[position + 1 :] != expected["arguments"]:
    problems.append("arguments")
if prompt_file.name != "system-prompt.txt" or not prompt_file.parent.samefile(Path.cwd()):
    problems.append("prompt file location")
if prompt_file.read_bytes().decode("utf-8") != expected["system"]:
    problems.append("system")
if sys.stdin.buffer.read().decode("utf-8") != expected["stdin"]:
    problems.append("stdin")
if os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") != expected["ceiling"]:
    problems.append("ceiling")
if any(name.upper().startswith("ORCHESTWIN_") for name in os.environ):
    problems.append("orchestwin variables")
if any(name.upper() in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") for name in os.environ):
    problems.append("credentials")
if problems:
    sys.stderr.write(", ".join(problems))
    sys.exit(3)
sys.stdout.buffer.write(expected["answer"].encode("utf-8"))
"""


def configuration(entry="design", document=None):
    return providers(claude_code_document() if document is None else document).hosted_model(entry)


def adapter(runner, entry="design", *, environment=None, executable=PROGRAM):
    return ClaudeCodeStructuredAdapter(
        configuration=configuration(entry),
        transport=AuditedProposalTransport(
            ClaudeCodeTransport(
                executable=executable,
                run=runner,
                environment=SYNTHETIC_ENVIRONMENT if environment is None else environment,
            )
        ),
    )


def generate(runner, request=None, *, mode=STRICT, retry_note=None):
    selected = configuration()
    return asyncio.run(
        adapter(runner).generate(
            request or structured_request(selected), output_mode=mode, retry_note=retry_note
        )
    )


def without(answer, key):
    document = json.loads(answer)
    del document[key]
    return json.dumps(document).encode("utf-8")


def changed_answer(answer, **fields):
    return json.dumps({**json.loads(answer), **fields}).encode("utf-8")


def expected_options(*, effort="high", schema=None):
    options = ["--print", "--output-format", "json", "--model", "claude-opus-5-5"]
    if effort is not None:
        options += ["--effort", effort]
    options += ["--no-session-persistence", "--safe-mode", "--tools", ""]
    options += ["--system-prompt-file", SYSTEM_PROMPT_FILE]
    if schema is not None:
        options += ["--json-schema", canonical_json(schema)]
    return options


def expected_arguments(directory, **options):
    words = expected_options(**options)
    words[words.index(SYSTEM_PROMPT_FILE)] = str(directory / SYSTEM_PROMPT_FILE)
    return [PROGRAM, *words]


def italian_request(selected, schema_payload=ITALIAN_SCHEMA):
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-team-v1",
        expected_identity=selected.identity,
        output_schema=create_structured_json_schema(
            schema_id="proposal-team-v1", version_number=1, schema_payload=schema_payload
        ),
        system_instruction="Produci un solo oggetto JSON. Perché: «abbonamento di Claude».",
        input_payload={
            "context": {"progetto": "Biblioteca Sant'Ambrogio — città"},
            "output_schema": schema_payload,
        },
        allowed_evidence_refs=(),
        prompt_version_ref="proposal-team-v1",
        temperature=selected.temperature,
        max_output_tokens=4096,
        timeout_seconds=selected.timeout_seconds,
    )


def on_selector_loop(coroutine):
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


async def _in_scope(store, port, request):
    token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
    try:
        await begin_model_generation(request)
        result = await port.generate(request)
        await retain_provider_result(result)
        return result
    finally:
        _SCOPE.reset(token)


def removed_names(environment):
    return sorted(
        name
        for name in environment
        if name.upper() in REMOVED or name.upper().startswith("ORCHESTWIN_")
    )


def test_a_strict_answer_is_validated_bound_to_the_identity_and_carries_no_cost():
    runner = FakeClaudeRunner(finished(claude_answer()))
    selected = configuration()
    request = structured_request(selected)
    result = asyncio.run(adapter(runner).generate(request))
    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert result.provider_kind is KIND and result.output_mode is STRICT
    success = result.success
    assert json.loads(success.payload_json) == VALID_REVIEW
    assert success.actual_identity == selected.identity == request.expected_identity
    assert success.provider_request_id == "session-synthetic-0001"
    usage = success.usage
    assert (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens) == (1200, 900, 300)
    assert (usage.cache_read_input_tokens, usage.cache_write_input_tokens) == (100, 50)
    assert usage.cost_microusd is None and usage.latency_milliseconds >= 0
    assert "cost_microusd" not in result.to_snapshot()["success"]["usage"]


def test_the_command_carries_the_contract_options_the_system_file_and_the_standard_input():
    runner = FakeClaudeRunner(finished(claude_answer()))
    selected = configuration()
    request = structured_request(selected, max_output_tokens=4096)
    asyncio.run(adapter(runner).generate(request))
    [call] = runner.calls
    directory = call.working_directory
    schema = hosted_output_schema(REVIEW_SCHEMA, KIND)
    assert call.arguments == expected_arguments(directory, schema=schema)
    assert call.system == request.system_instruction
    assert call.stdin == hosted_user_message(request.input_payload_json).encode("utf-8")
    assert call.timeout_seconds == request.timeout_seconds == 1200
    assert call.environment == {**SYNTHETIC_ENVIRONMENT, MAX_OUTPUT_TOKENS_VARIABLE: "68096"}
    assert directory.is_absolute() and not directory.exists()


def test_a_prompted_answer_is_read_from_the_result_text_without_the_schema_option():
    text = "```json\n" + json.dumps({**VALID_REVIEW, "note": "extra"}) + "\n```"
    runner = FakeClaudeRunner(finished(claude_answer(strict=False, result=text)))
    selected = configuration()
    request = structured_request(selected)
    result = generate(runner, request, mode=PROMPTED, retry_note="Answer again.")
    assert result.output_mode is PROMPTED
    assert json.loads(result.success.payload_json) == VALID_REVIEW
    [call] = runner.calls
    assert "--json-schema" not in call.arguments
    assert call.arguments == expected_arguments(call.working_directory)
    expected = hosted_user_message(request.input_payload_json, "Answer again.")
    assert call.stdin == expected.encode("utf-8")


def test_an_entry_without_effort_passes_no_effort_option():
    document = claude_code_document()
    document["models"][0]["effort"] = None
    selected = configuration(document=document)
    runner = FakeClaudeRunner(finished(claude_answer()))
    port = ClaudeCodeStructuredAdapter(
        configuration=selected,
        transport=ClaudeCodeTransport(
            executable=PROGRAM, run=runner, environment=SYNTHETIC_ENVIRONMENT
        ),
    )
    assert asyncio.run(port.generate(structured_request(selected))).success is not None
    assert "--effort" not in runner.calls[0].arguments


def test_the_child_environment_drops_the_credentials_and_sets_the_output_ceiling():
    environment = {
        **SYNTHETIC_ENVIRONMENT,
        **{name: "synthetic-value" for name in REMOVED},
        "anthropic_api_key": "synthetic-lower-case",
        "ORCHESTWIN_DATABASE_URL": "postgresql+psycopg://synthetic",
        "orchestwin_other": "synthetic",
        MAX_OUTPUT_TOKENS_VARIABLE: "1",
    }
    runner = FakeClaudeRunner(finished(claude_answer()))
    request = structured_request(configuration(), max_output_tokens=90_000)
    asyncio.run(adapter(runner, environment=environment).generate(request))
    assert runner.calls[0].environment == {
        **SYNTHETIC_ENVIRONMENT,
        MAX_OUTPUT_TOKENS_VARIABLE: str(64_000 + 64_000),
    }


def test_the_default_environment_is_the_process_environment_without_the_removed_names(
    monkeypatch,
):
    for name in REMOVED:
        monkeypatch.setenv(name, "synthetic-value")
    monkeypatch.setenv("ORCHESTWIN_SYNTHETIC_SECRET", "synthetic-value")
    monkeypatch.setenv("SYNTHETIC_KEPT_VARIABLE", "kept")
    runner = FakeClaudeRunner(finished(claude_answer()))
    port = build_claude_code_adapter(configuration(), executable=PROGRAM, run=runner)
    asyncio.run(port.generate(structured_request(configuration())))
    environment = runner.calls[0].environment
    assert removed_names(environment) == []
    assert environment["SYNTHETIC_KEPT_VARIABLE"] == "kept"
    assert environment[MAX_OUTPUT_TOKENS_VARIABLE] == "68096"


def failed_answer(status, text):
    return claude_answer(is_error=True, api_error_status=status, result=text)


@pytest.mark.parametrize(
    "stdout,status,code,retryable",
    [
        (failed_answer(401, "SECRET-RAW-TEXT"), 401, Code.AUTHENTICATION_FAILED, False),
        (failed_answer(403, "SECRET-RAW-TEXT"), 403, Code.AUTHENTICATION_FAILED, False),
        (
            failed_answer(None, "Not logged in · Please run /login"),
            502,
            Code.AUTHENTICATION_FAILED,
            False,
        ),
        (
            failed_answer(None, "Invalid API key · Please run /login"),
            502,
            Code.AUTHENTICATION_FAILED,
            False,
        ),
        (failed_answer(429, "SECRET-RAW-TEXT"), 429, Code.RATE_LIMITED, True),
        (
            failed_answer(None, "Claude AI usage limit reached|1760000000"),
            502,
            Code.RATE_LIMITED,
            True,
        ),
        (failed_answer(None, "You've hit your limit · resets 3pm"), 502, Code.RATE_LIMITED, True),
        (failed_answer(400, "API Error: 400 SECRET-RAW-TEXT"), 400, Code.INVALID_REQUEST, False),
        (failed_answer(500, "SECRET-RAW-TEXT"), 500, Code.PROVIDER_UNAVAILABLE, True),
        (failed_answer(529, "SECRET-RAW-TEXT"), 529, Code.PROVIDER_UNAVAILABLE, True),
        (failed_answer(404, "SECRET-RAW-TEXT"), 404, Code.PROVIDER_ERROR, False),
        (failed_answer(99, "SECRET-RAW-TEXT"), 502, Code.PROVIDER_UNAVAILABLE, True),
        (failed_answer(True, "SECRET-RAW-TEXT"), 502, Code.PROVIDER_UNAVAILABLE, True),
        (b"SECRET-RAW-TEXT is not one JSON object", 502, Code.PROVIDER_UNAVAILABLE, True),
        (b"", 502, Code.PROVIDER_UNAVAILABLE, True),
    ],
)
def test_a_failed_run_maps_to_a_fixed_code_and_never_repeats_the_program(
    stdout, status, code, retryable
):
    failure = generate(FakeClaudeRunner(finished(stdout, status=1))).failure
    assert (failure.code, failure.retryable, failure.provider_status_code) == (
        code,
        retryable,
        status,
    )
    assert "SECRET" not in failure.message and failure.usage is None


def test_the_answer_object_decides_the_status_and_not_the_exit_status():
    assert generate(FakeClaudeRunner(finished(claude_answer(), status=1))).success is not None
    failure = generate(FakeClaudeRunner(finished(failed_answer(429, "x"), status=0))).failure
    assert failure.code is Code.RATE_LIMITED


@pytest.mark.parametrize(
    "answer,code",
    [
        (claude_answer(stop_reason="max_tokens"), Code.INCOMPLETE_OUTPUT),
        (claude_answer(stop_reason="refusal"), Code.PROVIDER_REFUSED),
        (claude_answer(stop_reason="pause_turn"), Code.RESPONSE_SCHEMA_ERROR),
        (claude_answer(subtype="error_max_turns"), Code.PROVIDER_ERROR),
        (
            changed_answer(claude_answer(subtype="error_during_execution"), stop_reason=None),
            Code.PROVIDER_ERROR,
        ),
    ],
)
def test_a_run_that_did_not_finish_fails_and_keeps_its_usage(answer, code):
    failure = generate(FakeClaudeRunner(finished(answer))).failure
    assert failure.code is code and failure.retryable is False
    assert failure.usage.output_tokens == 900 and failure.usage.cost_microusd is None
    assert "cost_microusd" not in failure.to_snapshot()["usage"]


def test_the_served_model_comes_from_the_model_usage():
    selected = configuration()
    dated = {"claude-opus-5-5-20261001": {"outputTokens": 900}}
    matched = generate(FakeClaudeRunner(finished(claude_answer(model_usage=dated)))).success
    assert matched.actual_identity == selected.identity
    other = {
        "claude-haiku-4-5-20251001": {"outputTokens": 20},
        "claude-sonnet-5": {"outputTokens": 900},
    }
    success = generate(FakeClaudeRunner(finished(claude_answer(model_usage=other)))).success
    assert success.actual_identity == replace(
        selected.identity, base_model_revision="claude-sonnet-5"
    )
    broken = [
        without(claude_answer(), "modelUsage"),
        claude_answer(model_usage={}),
        claude_answer(model_usage=["claude-opus-5-5"]),
        claude_answer(model_usage={"claude-opus-5-5": 3}),
        claude_answer(model_usage={"claude-opus-5-5": {"outputTokens": -1}}),
    ]
    for stdout in broken:
        failure = generate(FakeClaudeRunner(finished(stdout))).failure
        assert failure.code is Code.RESPONSE_SCHEMA_ERROR
        assert failure.message == "The Claude Code result does not name the served model."


def test_a_different_served_model_is_refused_by_the_generator():
    other = {"claude-sonnet-5": {"outputTokens": 900}}
    runner = FakeClaudeRunner(finished(claude_answer({"assessment": "Clear."}, model_usage=other)))
    generator = ProposalGenerator(configuration(), adapter(runner), BUDGET)
    with pytest.raises(ProposalGenerationError, match="IDENTITY_MISMATCH"):
        asyncio.run(
            generator.generate(
                task="team", context={"project_id": "p"}, output_type=Review, instruction="Go."
            )
        )


def test_an_answer_outside_the_full_schema_or_the_envelope_is_a_schema_error():
    long_text = {**VALID_REVIEW, "assessment": "x" * 41}
    failure = generate(FakeClaudeRunner(finished(claude_answer(long_text)))).failure
    assert failure.code is Code.RESPONSE_SCHEMA_ERROR
    assert "$.assessment (maxLength)" in failure.message and "xxxxxxxxxx" not in failure.message
    missing = generate(FakeClaudeRunner(finished(without(claude_answer(), "structured_output"))))
    assert missing.failure.message == "The hosted model answer is not one JSON object."
    prompted = generate(
        FakeClaudeRunner(finished(claude_answer(strict=False, result="not json"))), mode=PROMPTED
    ).failure
    assert prompted.code is Code.RESPONSE_SCHEMA_ERROR and prompted.usage is not None
    envelope = generate(FakeClaudeRunner(finished(without(claude_answer(), "usage")))).failure
    assert envelope.message == "The Claude Code program returned an invalid result envelope."
    assert envelope.usage is None


def test_a_timeout_a_program_that_cannot_start_and_a_long_output_are_transport_failures():
    timeout = generate(FakeClaudeRunner(OpenAICompatibleTimeoutError("synthetic"))).failure
    assert (timeout.code, timeout.retryable) == (Code.TIMEOUT, True)
    absent = generate(FakeClaudeRunner(OpenAICompatibleTransportError("synthetic"))).failure
    assert (absent.code, absent.retryable) == (Code.PROVIDER_UNAVAILABLE, True)
    answer = claude_answer()
    largest = b" " * (MAX_OUTPUT_BYTES - len(answer)) + answer
    assert generate(FakeClaudeRunner(finished(largest))).success is not None
    too_long = generate(FakeClaudeRunner(finished(b" " + largest))).failure
    assert too_long.code is Code.PROVIDER_UNAVAILABLE
    runner = FakeClaudeRunner()
    missing = adapter(runner, executable=None)
    failure = asyncio.run(missing.generate(structured_request(configuration()))).failure
    assert failure.code is Code.PROVIDER_UNAVAILABLE and runner.calls == []


def test_a_cancelled_generation_cancels_the_runner_and_removes_the_directory():
    async def scenario():
        started = asyncio.Event()
        observed = []

        async def wait_forever():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed.append("cancelled")
                raise

        runner = FakeClaudeRunner(wait_forever)
        task = asyncio.create_task(adapter(runner).generate(structured_request(configuration())))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return runner, observed

    runner, observed = asyncio.run(scenario())
    assert observed == ["cancelled"]
    assert not runner.calls[0].working_directory.exists()


def test_evidence_keeps_the_request_the_exact_output_and_the_result_in_order():
    store = MemoryEvidence()
    selected = configuration()
    request = structured_request(selected)
    stdout = claude_answer()
    runner = FakeClaudeRunner(finished(stdout, stderr=b"SECRET-STANDARD-ERROR"))
    port = build_claude_code_adapter(selected, executable=PROGRAM, run=runner)
    result = asyncio.run(_in_scope(store, port, request))
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    schema = hosted_output_schema(REVIEW_SCHEMA, KIND)
    assert events[0][1]["payload"] == {
        "model": "claude-opus-5-5",
        "effort": "high",
        "max_output_tokens": request.max_output_tokens + 64_000,
        "system": request.system_instruction,
        "prompt": hosted_user_message(request.input_payload_json),
        "schema": schema,
        "options": expected_options(schema=schema),
    }
    response, raw = events[1][1], events[1][2]
    assert raw == stdout and response["status_code"] == 200 and response["body_retained"] is True
    assert response["body_sha256"] == hashlib.sha256(stdout).hexdigest()
    assert events[2][1] == result.to_snapshot()
    assert "cost_microusd" not in events[2][1]["success"]["usage"]
    assert "SECRET-STANDARD-ERROR" not in repr(store.events)
    lost = structured_request(selected)
    failing = FakeClaudeRunner(OpenAICompatibleTransportError("synthetic"))
    asyncio.run(
        _in_scope(store, build_claude_code_adapter(selected, executable=PROGRAM, run=failing), lost)
    )
    events = store.events[lost.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "TRANSPORT_ERROR", "PROVIDER_RESULT"]
    assert events[1][1] == {"code": "OpenAICompatibleTransportError"}


def test_a_foreign_identity_or_an_inexpressible_schema_never_runs_the_program():
    runner = FakeClaudeRunner()
    foreign = structured_request(providers().hosted_model("design"))
    assert generate(runner, foreign).failure.code is Code.IDENTITY_MISMATCH
    failure = generate(runner, structured_request(configuration(), OPEN_SCHEMA)).failure
    assert failure.code is Code.INVALID_REQUEST and failure.provider_status_code is None
    assert runner.calls == []
    with pytest.raises(ValueError):
        ClaudeCodeStructuredAdapter(
            configuration=providers().hosted_model("design"),
            transport=ClaudeCodeTransport(executable=PROGRAM),
        )
    with pytest.raises(OpenAICompatibleTransportError):
        asyncio.run(
            ClaudeCodeTransport(executable=PROGRAM, run=runner).post_json(
                url="https://api.anthropic.com/v1/messages",
                payload={},
                headers={},
                timeout_seconds=1,
            )
        )
    assert CLAUDE_CODE_URL == "claude-code://print"


def test_a_schema_too_long_for_the_command_line_is_generated_in_prompted_mode():
    values = tuple(f"choice-{index:05d}-from-a-long-list" for index in range(1200))
    large = create_model(
        "LargeChoice", __config__=ConfigDict(extra="forbid"), choice=(Literal[values], ...)
    )
    runner = FakeClaudeRunner(finished(claude_answer({"choice": values[7]}, strict=False)))
    generator = ProposalGenerator(configuration(), adapter(runner), BUDGET)
    output = asyncio.run(
        generator.generate(
            task="team", context={"project_id": "p"}, output_type=large, instruction="Choose."
        )
    )
    assert output.choice == values[7]
    assert "--json-schema" not in runner.calls[0].arguments


def test_a_generation_through_the_subscription_reads_no_spending():
    selected = configuration()
    assert estimated_cost_microusd(structured_request(selected), selected) == 0
    runner = FakeClaudeRunner(
        finished(claude_answer({"assessment": "Clear."})),
        finished(claude_answer({"assessment": "Clear."})),
    )
    generator = ProposalGenerator(selected, adapter(runner), BUDGET)

    def review():
        return generator.generate(
            task="team", context={"project_id": "p"}, output_type=Review, instruction="Go."
        )

    assert asyncio.run(review()) == Review(assessment="Clear.")
    store = SpendingEvidence(project=10**12, total=10**12)

    async def scoped():
        token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
        try:
            return await review()
        finally:
            _SCOPE.reset(token)

    assert asyncio.run(scoped()) == Review(assessment="Clear.")
    assert store.reads == []


def test_the_real_runner_runs_a_child_process_with_pipes_and_utf8_on_a_selector_loop(tmp_path):
    script = tmp_path / "fake_claude.py"
    script.write_text(CHILD, encoding="utf-8")
    selected = configuration()
    request = italian_request(selected)
    schema = hosted_output_schema(ITALIAN_SCHEMA, KIND)
    answer = claude_answer(ITALIAN_REVIEW).decode("utf-8")
    arguments = expected_options(schema=schema)
    arguments.remove(SYSTEM_PROMPT_FILE)
    (tmp_path / "expected.json").write_text(
        json.dumps(
            {
                "arguments": arguments,
                "system": request.system_instruction,
                "stdin": hosted_user_message(request.input_payload_json),
                "ceiling": str(4096 + 64_000),
                "answer": answer,
            }
        ),
        encoding="utf-8",
    )
    outcomes, directories = [], []

    async def real(arguments, stdin, environment, directory, timeout_seconds):
        directories.append(directory)
        outcome = await run_process(
            [sys.executable, str(script), *arguments[1:]],
            stdin,
            environment,
            directory,
            timeout_seconds,
        )
        outcomes.append(outcome)
        return outcome

    port = build_claude_code_adapter(selected, executable=PROGRAM, run=real)
    result = on_selector_loop(port.generate(request))
    [outcome] = outcomes
    assert (outcome.status, outcome.stderr) == (0, b"")
    assert outcome.stdout == answer.encode("utf-8")
    assert json.loads(result.success.payload_json) == ITALIAN_REVIEW
    assert not directories[0].exists()


def test_the_real_runner_kills_a_program_that_exceeds_its_timeout(tmp_path):
    script = tmp_path / "sleeper.py"
    script.write_text(SLEEPER, encoding="utf-8")
    began = time.monotonic()
    with pytest.raises(OpenAICompatibleTimeoutError):
        on_selector_loop(
            run_process([sys.executable, str(script)], b"", dict(os.environ), tmp_path, 5)
        )
    assert (tmp_path / "started").is_file()
    assert time.monotonic() - began < 60


def test_the_real_runner_kills_the_program_of_a_cancelled_task(tmp_path):
    script = tmp_path / "sleeper.py"
    script.write_text(SLEEPER, encoding="utf-8")
    marker = tmp_path / "started"

    async def scenario():
        task = asyncio.create_task(
            run_process([sys.executable, str(script)], b"", dict(os.environ), tmp_path, 300)
        )
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    began = time.monotonic()
    on_selector_loop(scenario())
    assert marker.is_file()
    assert time.monotonic() - began < 60


def test_a_program_that_cannot_start_is_a_transport_error(tmp_path):
    with pytest.raises(OpenAICompatibleTransportError) as failure:
        on_selector_loop(
            run_process([str(tmp_path / "absent-program")], b"", dict(os.environ), tmp_path, 10)
        )
    assert type(failure.value) is OpenAICompatibleTransportError


def test_the_readiness_asks_only_the_version_and_the_login():
    runner = readiness_runner()
    environment = {**SYNTHETIC_ENVIRONMENT, "ANTHROPIC_API_KEY": "synthetic", "ORCHESTWIN_X": "1"}
    report = asyncio.run(
        claude_code_readiness(
            PROGRAM,
            models=(("design", "claude-opus-5-5"), ("general", "claude-opus-5-5")),
            run=runner,
            environment=environment,
        )
    )
    assert report == {
        "ready": True,
        "kind": "CLAUDE_CODE_CLI",
        "executable": PROGRAM,
        "version": "2.1.286",
        "logged_in": True,
        "subscription": "max",
        "models": {
            "design": {"model": "claude-opus-5-5", "ready": True},
            "general": {"model": "claude-opus-5-5", "ready": True},
        },
    }
    assert [call.arguments for call in runner.calls] == [
        [PROGRAM, "--version"],
        [PROGRAM, "auth", "status"],
    ]
    for call in runner.calls:
        assert (call.stdin, call.timeout_seconds) == (b"", READINESS_TIMEOUT_SECONDS)
        assert call.environment == SYNTHETIC_ENVIRONMENT
    assert not runner.calls[0].working_directory.exists()
    assert "owner@example.com" not in json.dumps(report)


def status_answer(**fields):
    return finished(json.dumps(fields).encode("utf-8"))


VERSION = finished(CLAUDE_VERSION_LINE)


@pytest.mark.parametrize(
    "outcomes,code,observed",
    [
        (
            (OpenAICompatibleTransportError("synthetic"),),
            CLAUDE_CODE_NOT_FOUND,
            (None, None, None),
        ),
        ((OpenAICompatibleTimeoutError("synthetic"),), CLAUDE_CODE_NOT_FOUND, (None, None, None)),
        ((finished(CLAUDE_VERSION_LINE, status=1),), CLAUDE_CODE_NOT_FOUND, (None, None, None)),
        ((finished(b"  \n"),), CLAUDE_CODE_NOT_FOUND, (None, None, None)),
        (
            (VERSION, status_answer(loggedIn=False)),
            CLAUDE_CODE_NOT_LOGGED_IN,
            ("2.1.286", False, None),
        ),
        ((VERSION, finished(b"not json")), CLAUDE_CODE_NOT_LOGGED_IN, ("2.1.286", False, None)),
        (
            (VERSION, OpenAICompatibleTransportError("synthetic")),
            CLAUDE_CODE_NOT_LOGGED_IN,
            ("2.1.286", False, None),
        ),
        (
            (VERSION, status_answer(loggedIn=True, authMethod="api_key")),
            CLAUDE_CODE_NOT_ON_SUBSCRIPTION,
            ("2.1.286", True, None),
        ),
        (
            (VERSION, status_answer(loggedIn=True, authMethod="oauth", subscriptionType="team")),
            CLAUDE_CODE_NOT_ON_SUBSCRIPTION,
            ("2.1.286", True, "team"),
        ),
    ],
)
def test_a_provider_that_is_not_ready_names_its_reason(outcomes, code, observed):
    report = asyncio.run(
        claude_code_readiness(
            PROGRAM,
            models=(("design", "claude-opus-5-5"),),
            run=FakeClaudeRunner(*outcomes),
            environment=SYNTHETIC_ENVIRONMENT,
        )
    )
    assert (report["ready"], report["code"]) == (False, code)
    assert (report["version"], report["logged_in"], report["subscription"]) == observed
    assert report["models"] == {
        "design": {"model": "claude-opus-5-5", "ready": False, "code": code}
    }
    assert set(report) == {
        "ready",
        "kind",
        "executable",
        "version",
        "logged_in",
        "subscription",
        "models",
        "code",
    }


def test_a_program_that_was_not_found_is_never_run():
    runner = FakeClaudeRunner()
    report = asyncio.run(claude_code_readiness(None, run=runner))
    assert report == {
        "ready": False,
        "kind": "CLAUDE_CODE_CLI",
        "executable": None,
        "version": None,
        "logged_in": None,
        "subscription": None,
        "models": {},
        "code": CLAUDE_CODE_NOT_FOUND,
    }
    assert runner.calls == []


def test_the_program_is_the_configured_path_then_the_variable_then_the_search_path(tmp_path):
    named = tmp_path / "claude-from-variable"
    named.write_bytes(b"")
    searched = []

    def which(name):
        searched.append(name)
        return "/synthetic/bin/claude"

    configured = tmp_path / "configured" / "claude"
    variables = {CLAUDE_VARIABLE: f"  {named}  "}
    assert claude_code_executable(configured, environment=variables, which=which) == str(configured)
    assert claude_code_executable(None, environment=variables, which=which) == str(named)
    assert searched == []
    for value in ("claude-relative", str(tmp_path / "absent"), ""):
        found = claude_code_executable(None, environment={CLAUDE_VARIABLE: value}, which=which)
        assert found == "/synthetic/bin/claude"
    assert searched == ["claude", "claude", "claude"]
    assert claude_code_executable(None, environment={}, which=lambda name: None) is None
