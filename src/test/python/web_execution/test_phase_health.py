"""Health transport results cannot become success without a valid observation."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import replace

import pytest

from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.web_execution.phase_health import probe_web_health
from orchestwin.web_execution.runtime_evidence import WebHealthCheckSpec, WebHealthCheckStatus


def spec(**changes: object) -> WebHealthCheckSpec:
    return replace(
        WebHealthCheckSpec("health.test", "127.0.0.1", 4173, "/", (200, 204), 2, 2, 1),
        **changes,
    )


def observed(status: int | None = 200, error: str | None = None) -> HostProcessResult:
    return HostProcessResult(
        HostProcessStatus.COMPLETED,
        0,
        json.dumps(
            {"status_code": status, "error_code": error, "latency_milliseconds": 7}
        ).encode(),
        b"",
        None,
    )


class Invoke:
    def __init__(self, *results: HostProcessResult | Exception):
        self.results = iter(results)
        self.calls = []

    async def __call__(self, argv: tuple[str, ...], *, timeout_seconds: int):
        self.calls.append((argv, timeout_seconds))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("kind", ["NODE", "BROWSER", "PHP"])
def test_success_uses_trusted_argv_and_json_data_with_real_observation_time(kind: str) -> None:
    request = spec(path='/health?quoted="value"&return=https://example.invalid')
    invoke = Invoke(observed())
    result = asyncio.run(probe_web_health(request, invoke=invoke, runner_kind=kind))
    assert result.spec == request
    assert result.status is WebHealthCheckStatus.HEALTHY
    assert len(result.attempts) == 1
    assert result.attempts[0].status_code == 200
    assert result.attempts[0].latency_milliseconds == 7
    assert result.attempts[0].observed_at.utcoffset().total_seconds() == 0
    argv, timeout = invoke.calls[0]
    assert argv[0] == ("php" if kind == "PHP" else "node")
    assert argv[1] == ("-r" if kind == "PHP" else "-e")
    assert json.loads(argv[-1])["path"] == request.path
    assert request.path not in argv[2]
    assert timeout == request.request_timeout_seconds + 2


def test_retries_preserve_actual_failures_and_stop_at_first_success() -> None:
    invoke = Invoke(observed(503), observed(204))
    result = asyncio.run(probe_web_health(spec(), invoke=invoke, runner_kind="NODE"))
    assert result.status is WebHealthCheckStatus.HEALTHY
    assert tuple(attempt.status_code for attempt in result.attempts) == (503, 204)
    assert tuple(attempt.attempt_number for attempt in result.attempts) == (1, 2)


def test_request_timeout_remains_typed_after_maximum_attempts() -> None:
    invoke = Invoke(observed(None, "TIMEOUT"), observed(None, "TIMEOUT"))
    result = asyncio.run(probe_web_health(spec(), invoke=invoke, runner_kind="PHP"))
    assert result.status is WebHealthCheckStatus.TIMED_OUT
    assert len(result.attempts) == 2
    assert all(attempt.error_code == "TIMEOUT" for attempt in result.attempts)


@pytest.mark.parametrize("kind", ["NODE", "PHP"])
def test_redirect_cannot_be_healthy_even_if_spec_lists_redirect_status(kind: str) -> None:
    invoke = Invoke(observed(302))
    result = asyncio.run(
        probe_web_health(
            spec(expected_status_codes=(302,), maximum_attempts=1), invoke=invoke, runner_kind=kind
        )
    )
    assert result.status is WebHealthCheckStatus.UNHEALTHY
    assert result.attempts[0].error_code == "REDIRECT_REJECTED"
    assert result.attempts[0].status_code is None


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"status_code":200,"status_code":503,"error_code":null,"latency_milliseconds":7}',
        b'{"status_code":200,"error_code":null,"latency_milliseconds":true}',
        b'{"status_code":true,"error_code":null,"latency_milliseconds":7}',
        b'{"status_code":200,"error_code":null,"latency_milliseconds":NaN}',
        b'{"status_code":200,"error_code":null,"latency_milliseconds":-1}',
        b'{"status_code":200,"error_code":null,"latency_milliseconds":999999}',
        b'{"status_code":200,"error_code":null,"latency_milliseconds":7,"body":"private"}',
        b'{"status_code":null,"error_code":"private response text","latency_milliseconds":7}',
        b'{"status_code":200,"error_code":"TIMEOUT","latency_milliseconds":7}',
        b"x" * 4097,
        b"[" * 1100 + b"]" * 1100,
    ],
)
def test_invalid_output_never_creates_a_successful_health_observation(body: bytes) -> None:
    invoke = Invoke(HostProcessResult(HostProcessStatus.COMPLETED, 0, body, b"", None))
    result = asyncio.run(
        probe_web_health(spec(maximum_attempts=1), invoke=invoke, runner_kind="NODE")
    )
    assert result.status is WebHealthCheckStatus.UNHEALTHY
    assert result.attempts[0].error_code == "PROBE_OUTPUT_INVALID"
    assert "private" not in json.dumps(result.to_snapshot())


@pytest.mark.parametrize(
    "failure",
    [
        HostProcessResult(HostProcessStatus.COMPLETED, 1, observed().stdout, b"secret", None),
        HostProcessResult(HostProcessStatus.TIMED_OUT, None, b"", b"secret", "Private failure"),
        HostProcessResult(HostProcessStatus.SPAWN_ERROR, None, b"", b"secret", "Private failure"),
        OSError("private launch details"),
    ],
)
def test_transport_failure_never_reuses_stdout_as_success(failure) -> None:
    result = asyncio.run(
        probe_web_health(spec(maximum_attempts=1), invoke=Invoke(failure), runner_kind="PHP")
    )
    assert result.status is not WebHealthCheckStatus.HEALTHY
    assert result.attempts[0].status_code is None
    assert "private" not in json.dumps(result.to_snapshot()).casefold()


@pytest.mark.parametrize(
    "path", ["//external.invalid/", "/has space", "/fragment#x", "/" + "x" * 2048]
)
def test_ambiguous_or_unbounded_request_target_is_rejected_before_invoke(path: str) -> None:
    invoke = Invoke()
    with pytest.raises(ValueError, match="health request path"):
        asyncio.run(probe_web_health(spec(path=path), invoke=invoke, runner_kind="NODE"))
    assert invoke.calls == []


def test_localhost_uses_numeric_loopback_without_dns() -> None:
    invoke = Invoke(observed())
    asyncio.run(probe_web_health(spec(host="localhost"), invoke=invoke, runner_kind="NODE"))
    assert json.loads(invoke.calls[0][0][-1])["host"] == "127.0.0.1"


def test_unknown_runner_kind_and_cancellation_are_not_hidden() -> None:
    with pytest.raises(ValueError, match="runner kind"):
        asyncio.run(probe_web_health(spec(), invoke=Invoke(), runner_kind="SHELL"))

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(probe_web_health(spec(), invoke=cancelled, runner_kind="NODE"))


@pytest.mark.parametrize("kind", ["NODE", "PHP"])
def test_trusted_inline_probe_has_valid_interpreter_syntax_without_network(kind: str) -> None:
    executable = shutil.which("php" if kind == "PHP" else "node")
    if executable is None:
        pytest.skip(f"{kind} interpreter is unavailable; container probe is verified separately")
    invoke = Invoke(observed())
    asyncio.run(probe_web_health(spec(), invoke=invoke, runner_kind=kind))
    source = invoke.calls[0][0][2]
    arguments = [executable, "-l"] if kind == "PHP" else [executable, "--check"]
    if kind == "PHP":
        source = "<?php\n" + source
    checked = subprocess.run(arguments, input=source, text=True, capture_output=True, timeout=10)
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [("normal", None), ("redirect", "REDIRECT_REJECTED"), ("oversized", "RESPONSE_LIMIT_EXCEEDED")],
)
def test_node_probe_observes_redirect_and_body_limits_without_a_network_socket(
    mode: str, expected_error: str | None
) -> None:
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node interpreter is unavailable")
    invoke = Invoke(observed())
    asyncio.run(probe_web_health(spec(), invoke=invoke, runner_kind="NODE"))
    argv = invoke.calls[0][0]
    driver = r"""
const fs = require('node:fs'), vm = require('node:vm');
const {EventEmitter} = require('node:events');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let output, response;
const http = {request(options, callback) {
  if (options.hostname !== '127.0.0.1' || options.maxHeaderSize !== 16384)
    throw new Error('unexpected request boundary');
  const request = new EventEmitter();
  request.destroy = () => { if (response) response.emit('aborted'); };
  request.end = () => {
    response = new EventEmitter();
    response.statusCode = input.mode === 'redirect' ? 302 : 200;
    response.destroy = () => response.emit('aborted');
    callback(response);
    if (input.mode !== 'redirect') {
      response.emit('data', Buffer.alloc(input.mode === 'oversized' ? 65537 : 10));
      response.emit('end');
    }
  };
  return request;
}};
vm.runInNewContext(input.code, {
  require(name) { if (name !== 'node:http') throw new Error('unexpected module'); return http; },
  performance, setTimeout, clearTimeout,
  process: {argv:['node', input.data], stdout:{write(value) { output = JSON.parse(value); }}}
});
if (!output) throw new Error('missing observation');
process.stdout.write(JSON.stringify(output));
"""
    checked = subprocess.run(
        [executable, "-e", driver],
        input=json.dumps({"mode": mode, "code": argv[2], "data": argv[-1]}),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert checked.returncode == 0, checked.stderr
    result = json.loads(checked.stdout)
    assert result["error_code"] == expected_error
    assert result["status_code"] == (200 if expected_error is None else None)
    assert set(result) == {"error_code", "status_code", "latency_milliseconds"}
