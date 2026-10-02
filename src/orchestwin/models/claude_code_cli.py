from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from orchestwin.models.hosted_configuration import (
    HostedModelConfiguration,
    served_model_matches,
)
from orchestwin.models.hosted_schema import (
    HostedSchemaError,
    hosted_output_schema,
    hosted_user_message,
    parse_prompted_answer,
    prune_undefined_properties,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.openai_compatible import (
    OpenAICompatibleTimeoutError,
    OpenAICompatibleTransportError,
)
from orchestwin.models.proposal_evidence import AuditedProposalTransport
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationPort,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    StructuredOutputMode,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import canonical_json

CLAUDE_CODE_URL: Final = "claude-code://print"
CLAUDE_PROGRAM: Final = "claude"
CLAUDE_VARIABLE: Final = "ORCHESTWIN_CLAUDE"
MAX_OUTPUT_TOKENS_VARIABLE: Final = "CLAUDE_CODE_MAX_OUTPUT_TOKENS"
REMOVED_VARIABLES: Final = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    }
)
REMOVED_PREFIX: Final = "ORCHESTWIN_"
SYSTEM_PROMPT_OPTION: Final = "--system-prompt-file"
SYSTEM_PROMPT_FILE: Final = "system-prompt.txt"
SCHEMA_OPTION: Final = "--json-schema"
MAX_OUTPUT_BYTES: Final = 4_000_000
UNAVAILABLE_STATUS: Final = 502
READINESS_TIMEOUT_SECONDS: Final = 10
SUBSCRIPTION_AUTH_METHOD: Final = "claude.ai"
CLAUDE_CODE_NOT_FOUND: Final = "CLAUDE_CODE_NOT_FOUND"
CLAUDE_CODE_NOT_LOGGED_IN: Final = "CLAUDE_CODE_NOT_LOGGED_IN"
CLAUDE_CODE_NOT_ON_SUBSCRIPTION: Final = "CLAUDE_CODE_NOT_ON_SUBSCRIPTION"
_KIND: Final = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
_Code = StructuredGenerationFailureCode
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_VERSION_LENGTH: Final = 64
_MAX_SUBSCRIPTION_LENGTH: Final = 64
_FOLDER_PREFIX: Final = "orchestwin-claude-"
_FINISHED: Final = frozenset({"end_turn", "tool_use"})
_NOT_LOGGED_IN: Final = re.compile(
    r"not logged in|/login|log ?in again|invalid api key|oauth token", re.IGNORECASE
)
_LIMITED: Final = re.compile(
    r"usage limit|rate limit|limit reached|hit your limit|too many requests", re.IGNORECASE
)
_CREATION_FLAGS: Final = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_FAILURE_MESSAGES: Final = {
    _Code.AUTHENTICATION_FAILED: "The Claude Code program is not logged in to a Claude account.",
    _Code.RATE_LIMITED: "The Claude subscription reached a usage or rate limit.",
    _Code.TIMEOUT: "The Claude Code request exceeded its timeout.",
    _Code.PROVIDER_UNAVAILABLE: "The Claude Code program or its service is not available now.",
    _Code.INVALID_REQUEST: "The Claude Code program rejected the request.",
    _Code.PROVIDER_ERROR: "The Claude Code program returned an unexpected error.",
}


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    status: int
    stdout: bytes
    stderr: bytes


ProcessRunner = Callable[
    [Sequence[str], bytes, Mapping[str, str], Path, float], Awaitable[ProcessOutcome]
]


@dataclass(frozen=True, slots=True)
class ClaudeCodeResponse:
    status_code: int
    body: bytes
    elapsed_milliseconds: int


class _Child:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._stopped = False

    def run(
        self,
        arguments: Sequence[str],
        stdin: bytes,
        environment: Mapping[str, str],
        working_directory: Path,
    ) -> ProcessOutcome:
        with self._lock:
            if self._stopped:
                raise OpenAICompatibleTransportError("the program was stopped before it started")
            try:
                process = subprocess.Popen(
                    [str(argument) for argument in arguments],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=working_directory,
                    env=dict(environment),
                    creationflags=_CREATION_FLAGS,
                )
            except (OSError, ValueError):
                raise OpenAICompatibleTransportError("the program could not be started") from None
            self._process = process
        with process:
            try:
                stdout, stderr = process.communicate(stdin)
            except OSError:
                process.kill()
                raise OpenAICompatibleTransportError("the program could not be read") from None
        return ProcessOutcome(status=process.returncode, stdout=stdout, stderr=stderr)

    def stop(self) -> None:
        with self._lock:
            self._stopped = True
            process = self._process
        if process is not None and process.poll() is None:
            with contextlib.suppress(OSError):
                process.kill()


async def run_process(
    arguments: Sequence[str],
    stdin: bytes,
    environment: Mapping[str, str],
    working_directory: Path,
    timeout_seconds: float,
) -> ProcessOutcome:
    child = _Child()
    try:
        async with asyncio.timeout(timeout_seconds):
            return await asyncio.to_thread(
                child.run, arguments, stdin, environment, working_directory
            )
    except TimeoutError:
        child.stop()
        raise OpenAICompatibleTimeoutError("the program exceeded its timeout") from None
    except BaseException:
        child.stop()
        raise


def child_environment(
    variables: Mapping[str, str], *, max_output_tokens: int | None = None
) -> dict[str, str]:
    environment = {name: value for name, value in variables.items() if not _removed(name)}
    if max_output_tokens is not None:
        environment[MAX_OUTPUT_TOKENS_VARIABLE] = str(max_output_tokens)
    return environment


def _removed(name: str) -> bool:
    upper = name.upper()
    return (
        upper in REMOVED_VARIABLES
        or upper.startswith(REMOVED_PREFIX)
        or upper == MAX_OUTPUT_TOKENS_VARIABLE
    )


def command_options(
    configuration: HostedModelConfiguration, schema: dict[str, Any] | None = None
) -> list[str]:
    options = ["--print", "--output-format", "json", "--model", configuration.model]
    if configuration.effort is not None:
        options.extend(["--effort", configuration.effort])
    options.extend(
        [
            "--no-session-persistence",
            "--safe-mode",
            "--tools",
            "",
            SYSTEM_PROMPT_OPTION,
            SYSTEM_PROMPT_FILE,
        ]
    )
    if schema is not None:
        options.extend([SCHEMA_OPTION, canonical_json(schema)])
    return options


def command_arguments(executable: str, options: Sequence[str], directory: Path) -> list[str]:
    arguments = [executable]
    previous = None
    for option in options:
        arguments.append(str(directory / option) if previous == SYSTEM_PROMPT_OPTION else option)
        previous = option
    return arguments


def answer_status(stdout: bytes) -> int:
    try:
        answer = strict_json_object(stdout)
    except ValueError:
        return UNAVAILABLE_STATUS
    if answer.get("is_error") is False:
        return 200
    status = answer.get("api_error_status")
    if isinstance(status, int) and not isinstance(status, bool) and status >= 100:
        return status
    return UNAVAILABLE_STATUS


@contextlib.contextmanager
def _working_directory() -> Iterator[Path]:
    try:
        folder = tempfile.TemporaryDirectory(prefix=_FOLDER_PREFIX, ignore_cleanup_errors=True)
    except OSError:
        raise OpenAICompatibleTransportError("the working directory is not available") from None
    with folder as name:
        yield Path(name)


def _elapsed(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


class ClaudeCodeTransport:
    def __init__(
        self,
        *,
        executable: str | Path | None,
        run: ProcessRunner | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._executable = None if executable is None else str(executable)
        self._run = run_process if run is None else run
        self._environment = environment

    async def post_json(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> ClaudeCodeResponse:
        if url != CLAUDE_CODE_URL:
            raise OpenAICompatibleTransportError("the Claude Code transport has one address")
        if self._executable is None:
            raise OpenAICompatibleTransportError("the Claude Code program was not found")
        variables = os.environ if self._environment is None else self._environment
        started = time.perf_counter()
        with _working_directory() as directory:
            try:
                (directory / SYSTEM_PROMPT_FILE).write_bytes(payload["system"].encode("utf-8"))
            except OSError:
                raise OpenAICompatibleTransportError(
                    "the system instruction could not be written"
                ) from None
            outcome = await self._run(
                command_arguments(self._executable, payload["options"], directory),
                payload["prompt"].encode("utf-8"),
                child_environment(variables, max_output_tokens=payload["max_output_tokens"]),
                directory,
                timeout_seconds,
            )
        if len(outcome.stdout) > MAX_OUTPUT_BYTES:
            raise OpenAICompatibleTransportError("the program answered with too much output")
        return ClaudeCodeResponse(
            status_code=answer_status(outcome.stdout),
            body=outcome.stdout,
            elapsed_milliseconds=_elapsed(started),
        )


class ClaudeCodeStructuredAdapter(StructuredGenerationPort):
    def __init__(self, *, configuration: HostedModelConfiguration, transport: Any) -> None:
        if configuration.provider_kind is not _KIND:
            raise ValueError("the Claude Code adapter requires a Claude Code model entry")
        self._configuration = configuration
        self._transport = transport

    @property
    def identity(self) -> ModelRuntimeIdentity:
        return self._configuration.identity

    async def generate(
        self,
        request: StructuredGenerationRequest,
        *,
        output_mode: StructuredOutputMode = StructuredOutputMode.STRICT,
        retry_note: str | None = None,
    ) -> StructuredGenerationResult:
        mode = StructuredOutputMode(output_mode)
        if request.expected_identity != self._configuration.identity:
            return _failure(
                _Code.IDENTITY_MISMATCH,
                "The requested model identity differs from the configured hosted model.",
                mode=mode,
                retryable=False,
            )
        full_schema = json.loads(request.output_schema.canonical_schema_json)
        schema = None
        if mode is StructuredOutputMode.STRICT:
            try:
                schema = hosted_output_schema(full_schema, _KIND)
            except HostedSchemaError:
                return _failure(
                    _Code.INVALID_REQUEST,
                    "The output schema cannot be expressed for the hosted model provider.",
                    mode=mode,
                    retryable=False,
                )
        max_tokens = self._configuration.max_tokens(request.max_output_tokens)
        payload = request_payload(
            self._configuration, request, max_tokens, schema=schema, retry_note=retry_note
        )
        try:
            response = await self._transport.post_json(
                url=CLAUDE_CODE_URL,
                payload=payload,
                headers={},
                timeout_seconds=request.timeout_seconds,
            )
        except OpenAICompatibleTimeoutError:
            return _failure(
                _Code.TIMEOUT, _FAILURE_MESSAGES[_Code.TIMEOUT], mode=mode, retryable=True
            )
        except OpenAICompatibleTransportError:
            return _failure(
                _Code.PROVIDER_UNAVAILABLE,
                "The Claude Code program could not be run.",
                mode=mode,
                retryable=True,
            )
        if response.status_code != 200:
            return status_failure(response.status_code, response.body, output_mode=mode)
        return self._answer(response, full_schema, mode)

    def _answer(
        self, response: Any, full_schema: dict[str, Any], mode: StructuredOutputMode
    ) -> StructuredGenerationResult:
        try:
            answer = strict_json_object(response.body)
            usage = _usage(answer.get("usage"), response.elapsed_milliseconds)
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The Claude Code program returned an invalid result envelope.",
                mode=mode,
                retryable=False,
            )
        stop_reason = answer.get("stop_reason")
        if stop_reason == "max_tokens":
            return _failure(
                _Code.INCOMPLETE_OUTPUT,
                "The hosted model stopped at its output limit; no partial output was accepted.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if stop_reason == "refusal":
            return _failure(
                _Code.PROVIDER_REFUSED,
                "The hosted model declined to answer.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if answer.get("subtype") != "success":
            return _failure(
                _Code.PROVIDER_ERROR,
                _FAILURE_MESSAGES[_Code.PROVIDER_ERROR],
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if stop_reason not in _FINISHED:
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model ended with an unsupported stop reason.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            identity = _served_identity(self._configuration, answer.get("modelUsage"))
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The Claude Code result does not name the served model.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            output = _output(answer, mode)
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model answer is not one JSON object.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        violations = validate_against_schema(output, full_schema)
        if violations and mode is StructuredOutputMode.PROMPTED:
            pruned = prune_undefined_properties(output, full_schema)
            if pruned is not None:
                output, violations = pruned.payload, ()
        if violations:
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                violation_message(violations),
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            success = create_structured_generation_success(
                payload=output,
                actual_identity=identity,
                usage=usage,
                finish_reason=StructuredGenerationFinishReason.STOP,
                provider_request_id=_provider_request_id(answer.get("session_id")),
            )
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model answer does not satisfy the structured contract.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        return successful_structured_generation_result(
            provider_kind=_KIND, success=success, output_mode=mode
        )


def request_payload(
    configuration: HostedModelConfiguration,
    request: StructuredGenerationRequest,
    max_tokens: int,
    *,
    schema: dict[str, Any] | None = None,
    retry_note: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": configuration.model,
        "effort": configuration.effort,
        "max_output_tokens": max_tokens,
        "system": request.system_instruction,
        "prompt": hosted_user_message(request.input_payload_json, retry_note),
        "options": command_options(configuration, schema),
    }
    if schema is not None:
        payload["schema"] = schema
    return payload


def status_failure(
    status_code: int,
    body: bytes,
    *,
    output_mode: StructuredOutputMode = StructuredOutputMode.STRICT,
) -> StructuredGenerationResult:
    message = _program_message(body)
    if status_code in {401, 403} or _NOT_LOGGED_IN.search(message):
        code, retryable = _Code.AUTHENTICATION_FAILED, False
    elif status_code == 429 or _LIMITED.search(message):
        code, retryable = _Code.RATE_LIMITED, True
    elif status_code == 400:
        code, retryable = _Code.INVALID_REQUEST, False
    elif status_code >= 500:
        code, retryable = _Code.PROVIDER_UNAVAILABLE, True
    else:
        code, retryable = _Code.PROVIDER_ERROR, False
    return _failure(
        code, _FAILURE_MESSAGES[code], mode=output_mode, retryable=retryable, status=status_code
    )


def _program_message(body: bytes) -> str:
    try:
        text = strict_json_object(body).get("result")
    except ValueError:
        return ""
    return text if isinstance(text, str) else ""


def _failure(
    code: StructuredGenerationFailureCode,
    message: str,
    *,
    mode: StructuredOutputMode,
    retryable: bool,
    status: int | None = None,
    usage: StructuredGenerationUsage | None = None,
) -> StructuredGenerationResult:
    return failed_structured_generation_result(
        provider_kind=_KIND,
        code=code,
        message=message,
        retryable=retryable,
        provider_status_code=status,
        usage=usage,
        output_mode=mode,
    )


def _count(values: Mapping[str, object], key: str, *, required: bool) -> int:
    value = values.get(key)
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _usage(value: object, elapsed_milliseconds: int) -> StructuredGenerationUsage:
    if not isinstance(value, dict):
        raise ValueError("result usage is required")
    details = value.get("output_tokens_details")
    return StructuredGenerationUsage(
        input_tokens=_count(value, "input_tokens", required=True),
        output_tokens=_count(value, "output_tokens", required=True),
        latency_milliseconds=elapsed_milliseconds,
        cache_read_input_tokens=_count(value, "cache_read_input_tokens", required=False),
        cache_write_input_tokens=_count(value, "cache_creation_input_tokens", required=False),
        reasoning_tokens=(
            _count(details, "thinking_tokens", required=False) if isinstance(details, dict) else 0
        ),
        cost_microusd=None,
    )


def _served_identity(
    configuration: HostedModelConfiguration, model_usage: object
) -> ModelRuntimeIdentity:
    if not isinstance(model_usage, dict) or not model_usage:
        raise ValueError("the served models are required")
    produced: dict[str, int] = {}
    for name, figures in model_usage.items():
        if not isinstance(name, str) or not name or not isinstance(figures, dict):
            raise ValueError("every served model needs its figures")
        produced[name] = _count(figures, "outputTokens", required=False)
    if any(served_model_matches(configuration.model, name) for name in produced):
        return configuration.identity
    revision = max(produced, key=lambda name: (produced[name], name))
    return replace(configuration.identity, base_model_revision=revision)


def _output(answer: Mapping[str, Any], mode: StructuredOutputMode) -> dict[str, Any]:
    if mode is StructuredOutputMode.STRICT:
        output = answer.get("structured_output")
        if not isinstance(output, dict):
            raise ValueError("the structured output must be one JSON object")
        return output
    text = answer.get("result")
    if not isinstance(text, str):
        raise ValueError("the result text is required")
    return parse_prompted_answer(text)


def _provider_request_id(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value) <= _MAX_IDENTIFIER_LENGTH
        and not any(character.isspace() for character in value)
    ):
        return value
    return None


def build_claude_code_adapter(
    configuration: HostedModelConfiguration,
    *,
    executable: str | Path | None,
    run: ProcessRunner | None = None,
) -> ClaudeCodeStructuredAdapter:
    return ClaudeCodeStructuredAdapter(
        configuration=configuration,
        transport=AuditedProposalTransport(ClaudeCodeTransport(executable=executable, run=run)),
    )


def claude_code_executable(
    configured: str | Path | None,
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> str | None:
    if configured is not None:
        return str(configured)
    variables = os.environ if environment is None else environment
    named = variables.get(CLAUDE_VARIABLE, "").strip()
    if named:
        candidate = Path(named)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    return (shutil.which if which is None else which)(CLAUDE_PROGRAM)


async def claude_code_readiness(
    executable: str | Path | None,
    *,
    models: Iterable[tuple[str, str]] = (),
    run: ProcessRunner | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    program = None if executable is None else str(executable)
    observation: dict[str, object] = {"version": None, "logged_in": None, "subscription": None}
    code: str | None = CLAUDE_CODE_NOT_FOUND
    if program is not None:
        variables = child_environment(os.environ if environment is None else environment)
        runner = run_process if run is None else run
        code = await _observe(runner, program, variables, observation)
    ready = code is None
    failure: dict[str, object] = {} if code is None else {"code": code}
    return {
        "ready": ready,
        "kind": _KIND.value,
        "executable": program,
        **observation,
        "models": {
            entry_id: {"model": model, "ready": ready, **failure} for entry_id, model in models
        },
        **failure,
    }


async def _observe(
    run: ProcessRunner,
    program: str,
    variables: Mapping[str, str],
    observation: dict[str, object],
) -> str | None:
    with _working_directory() as directory:
        version = _version_number(await _command(run, [program, "--version"], variables, directory))
        if version is None:
            return CLAUDE_CODE_NOT_FOUND
        observation["version"] = version
        status = _status_document(
            await _command(run, [program, "auth", "status"], variables, directory)
        )
    logged_in = status.get("loggedIn") is True
    subscription = status.get("subscriptionType")
    observation["logged_in"] = logged_in
    observation["subscription"] = (
        subscription
        if isinstance(subscription, str) and 0 < len(subscription) <= _MAX_SUBSCRIPTION_LENGTH
        else None
    )
    if not logged_in:
        return CLAUDE_CODE_NOT_LOGGED_IN
    if status.get("authMethod") != SUBSCRIPTION_AUTH_METHOD:
        return CLAUDE_CODE_NOT_ON_SUBSCRIPTION
    return None


async def _command(
    run: ProcessRunner, arguments: list[str], variables: Mapping[str, str], directory: Path
) -> ProcessOutcome | None:
    try:
        return await run(arguments, b"", variables, directory, READINESS_TIMEOUT_SECONDS)
    except OpenAICompatibleTransportError:
        return None


def _version_number(outcome: ProcessOutcome | None) -> str | None:
    if outcome is None or outcome.status != 0:
        return None
    words = outcome.stdout.decode("utf-8", errors="replace").split()
    if not words or len(words[0]) > _MAX_VERSION_LENGTH:
        return None
    return words[0]


def _status_document(outcome: ProcessOutcome | None) -> dict[str, Any]:
    if outcome is None:
        return {}
    try:
        return strict_json_object(outcome.stdout)
    except ValueError:
        return {}


__all__ = [
    "CLAUDE_CODE_NOT_FOUND",
    "CLAUDE_CODE_NOT_LOGGED_IN",
    "CLAUDE_CODE_NOT_ON_SUBSCRIPTION",
    "CLAUDE_CODE_URL",
    "CLAUDE_PROGRAM",
    "CLAUDE_VARIABLE",
    "MAX_OUTPUT_BYTES",
    "MAX_OUTPUT_TOKENS_VARIABLE",
    "READINESS_TIMEOUT_SECONDS",
    "REMOVED_PREFIX",
    "REMOVED_VARIABLES",
    "SCHEMA_OPTION",
    "SUBSCRIPTION_AUTH_METHOD",
    "SYSTEM_PROMPT_FILE",
    "SYSTEM_PROMPT_OPTION",
    "UNAVAILABLE_STATUS",
    "ClaudeCodeResponse",
    "ClaudeCodeStructuredAdapter",
    "ClaudeCodeTransport",
    "ProcessOutcome",
    "ProcessRunner",
    "answer_status",
    "build_claude_code_adapter",
    "child_environment",
    "claude_code_executable",
    "claude_code_readiness",
    "command_arguments",
    "command_options",
    "request_payload",
    "run_process",
    "status_failure",
]
