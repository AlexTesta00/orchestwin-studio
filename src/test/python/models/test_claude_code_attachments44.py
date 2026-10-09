from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from orchestwin.models.claude_code_cli import (
    CLAUDE_CODE_URL,
    SYSTEM_PROMPT_FILE,
    ClaudeCodeResponse,
    ClaudeCodeStructuredAdapter,
    ClaudeCodeTransport,
    build_claude_code_adapter,
    command_options,
    request_payload,
)
from orchestwin.models.hosted_schema import hosted_output_schema
from orchestwin.models.openai_compatible import OpenAICompatibleTransportError
from orchestwin.models.proposal_evidence import (
    _SCOPE,
    ProposalEvidenceScope,
    begin_model_generation,
    retain_provider_result,
)
from orchestwin.models.structured_generation import (
    GenerationAttachment,
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.models.test_hosted_support import (
    REVIEW_SCHEMA,
    VALID_REVIEW,
    claude_answer,
    claude_code_document,
    finished,
    providers,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

KIND = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
PROGRAM = "claude-synthetic-program"
SYNTHETIC_ENVIRONMENT = {"PATH": "/synthetic/bin", "HOME": "/synthetic/home"}
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-screenshot-001"
JPEG = b"\xff\xd8\xff\xe0" + b"synthetic-screenshot-002"
FIRST = GenerationAttachment("screenshot-001.png", "image/png", PNG)
SECOND = GenerationAttachment("screenshot-002.jpg", "image/jpeg", JPEG)
READ_RULES = "Read(./screenshot-001.png),Read(./screenshot-002.jpg)"
CEILING = 4096 + 64_000


def configuration():
    return providers(claude_code_document()).hosted_model("design")


def strict_schema():
    return hosted_output_schema(REVIEW_SCHEMA, KIND)


def attached_request(selected, attachments=(FIRST, SECOND)):
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-team-v1",
        expected_identity=selected.identity,
        output_schema=create_structured_json_schema(
            schema_id="proposal-team-v1", version_number=1, schema_payload=REVIEW_SCHEMA
        ),
        system_instruction="Read every named screenshot, then produce one JSON object.",
        input_payload={"context": {"project_id": str(uuid4())}, "output_schema": REVIEW_SCHEMA},
        allowed_evidence_refs=(),
        prompt_version_ref="proposal-team-v1",
        temperature=selected.temperature,
        max_output_tokens=4096,
        timeout_seconds=selected.timeout_seconds,
        attachments=attachments,
    )


def options_before_attachments(*, schema=None):
    options = ["--print", "--output-format", "json", "--model", "claude-opus-5-5"]
    options += ["--effort", "high", "--no-session-persistence", "--safe-mode", "--tools", ""]
    options += ["--system-prompt-file", SYSTEM_PROMPT_FILE]
    if schema is not None:
        options += ["--json-schema", canonical_json(schema)]
    return options


class DirectoryRunner:
    def __init__(self):
        self.calls = []

    async def __call__(self, arguments, stdin, environment, working_directory, timeout_seconds):
        files = {path.name: path.read_bytes() for path in working_directory.iterdir()}
        self.calls.append((list(arguments), working_directory, files))
        return finished(claude_answer())


class RecordingTransport:
    def __init__(self):
        self.calls = []

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        return ClaudeCodeResponse(status_code=200, body=claude_answer(), elapsed_milliseconds=7)


def transport(runner):
    return ClaudeCodeTransport(executable=PROGRAM, run=runner, environment=SYNTHETIC_ENVIRONMENT)


async def _in_scope(store, port, request):
    token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
    try:
        await begin_model_generation(request)
        result = await port.generate(request)
        await retain_provider_result(result)
        return result
    finally:
        _SCOPE.reset(token)


def test_without_attachments_the_options_are_the_options_of_before():
    selected = configuration()
    schema = strict_schema()
    assert command_options(selected) == options_before_attachments()
    assert command_options(selected, schema) == options_before_attachments(schema=schema)
    assert command_options(selected, schema, ()) == options_before_attachments(schema=schema)


def test_with_attachments_only_the_reading_of_the_named_files_is_allowed():
    selected = configuration()
    schema = strict_schema()
    words = ["--print", "--output-format", "json", "--model", "claude-opus-5-5", "--effort"]
    words += ["high", "--no-session-persistence", "--safe-mode", "--tools", "Read"]
    words += ["--allowedTools", READ_RULES, "--restricted", "--permission-mode", "dontAsk"]
    words += ["--permission-prompts", "none", "--system-prompt-file", SYSTEM_PROMPT_FILE]
    assert command_options(selected, None, (FIRST, SECOND)) == words
    strict = command_options(selected, schema, (FIRST, SECOND))
    assert strict == [*words, "--json-schema", canonical_json(schema)]
    assert "" not in strict
    single = command_options(selected, schema, (FIRST,))
    assert single[single.index("--allowedTools") + 1] == "Read(./screenshot-001.png)"


def test_the_payload_names_the_attachments_without_their_bytes():
    selected = configuration()
    schema = strict_schema()
    payload = request_payload(selected, attached_request(selected), CEILING, schema=schema)
    assert payload["attachments"] == [FIRST.reference(), SECOND.reference()]
    assert payload["options"] == command_options(selected, schema, (FIRST, SECOND))
    assert payload["options"][payload["options"].index("--tools") + 1] == "Read"
    assert "synthetic-screenshot" not in canonical_json(payload)
    plain_request = attached_request(selected, ())
    plain = request_payload(selected, plain_request, CEILING, schema=schema)
    assert "attachments" not in plain
    assert plain["options"] == options_before_attachments(schema=schema)


def test_the_transport_writes_each_attachment_beside_the_system_instruction():
    selected = configuration()
    request = attached_request(selected)
    runner = DirectoryRunner()
    response = asyncio.run(
        transport(runner).post_json(
            url=CLAUDE_CODE_URL,
            payload=request_payload(selected, request, CEILING, schema=strict_schema()),
            headers={},
            timeout_seconds=60,
            attachments=request.attachments,
        )
    )
    assert (response.status_code, response.body) == (200, claude_answer())
    [(arguments, directory, files)] = runner.calls
    assert files == {
        SYSTEM_PROMPT_FILE: request.system_instruction.encode("utf-8"),
        "screenshot-001.png": PNG,
        "screenshot-002.jpg": JPEG,
    }
    assert arguments[0] == PROGRAM
    assert arguments[arguments.index("--tools") + 1] == "Read"
    assert arguments[arguments.index("--allowedTools") + 1] == READ_RULES
    assert arguments[arguments.index("--permission-mode") + 1] == "dontAsk"
    assert arguments[arguments.index("--permission-prompts") + 1] == "none"
    assert "--restricted" in arguments
    prompt_file = arguments[arguments.index("--system-prompt-file") + 1]
    assert prompt_file == str(directory / SYSTEM_PROMPT_FILE)
    assert directory.is_absolute() and not directory.exists()


def test_an_attachment_that_cannot_be_written_stops_the_run_before_the_program():
    selected = configuration()
    clash = GenerationAttachment(SYSTEM_PROMPT_FILE, "image/png", PNG)
    request = attached_request(selected, (clash,))
    runner = DirectoryRunner()
    with pytest.raises(OpenAICompatibleTransportError, match="the attachment could not be written"):
        asyncio.run(
            transport(runner).post_json(
                url=CLAUDE_CODE_URL,
                payload=request_payload(selected, request, CEILING),
                headers={},
                timeout_seconds=60,
                attachments=request.attachments,
            )
        )
    port = ClaudeCodeStructuredAdapter(configuration=selected, transport=transport(runner))
    failure = asyncio.run(port.generate(request)).failure
    assert failure.code is StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
    assert runner.calls == []


def test_the_adapter_hands_over_the_attachments_only_when_there_are_some():
    selected = configuration()
    recording = RecordingTransport()
    port = ClaudeCodeStructuredAdapter(configuration=selected, transport=recording)
    attached = asyncio.run(port.generate(attached_request(selected)))
    plain = asyncio.run(port.generate(attached_request(selected, ())))
    assert json.loads(attached.success.payload_json) == VALID_REVIEW
    assert json.loads(plain.success.payload_json) == VALID_REVIEW
    with_files, without_files = recording.calls
    assert with_files["attachments"] == (FIRST, SECOND)
    assert with_files["payload"]["attachments"] == [FIRST.reference(), SECOND.reference()]
    assert set(with_files) == {"url", "payload", "headers", "timeout_seconds", "attachments"}
    assert set(without_files) == {"url", "payload", "headers", "timeout_seconds"}
    assert "attachments" not in without_files["payload"]


def test_the_evidence_keeps_the_references_of_the_attachments_and_never_their_bytes():
    store = MemoryEvidence()
    selected = configuration()
    request = attached_request(selected)
    runner = DirectoryRunner()
    port = build_claude_code_adapter(selected, executable=PROGRAM, run=runner)
    result = asyncio.run(_in_scope(store, port, request))
    assert json.loads(result.success.payload_json) == VALID_REVIEW
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    references = [FIRST.reference(), SECOND.reference()]
    assert events[0][1]["payload"]["attachments"] == references
    assert request.to_snapshot()["attachments"] == references
    assert "synthetic-screenshot" not in repr(store.events)
    assert "synthetic-screenshot" not in json.dumps(request.to_snapshot())
    [(_, _, files)] = runner.calls
    assert (files["screenshot-001.png"], files["screenshot-002.jpg"]) == (PNG, JPEG)
