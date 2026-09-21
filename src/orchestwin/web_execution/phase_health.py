"""Observe bounded loopback HTTP health inside an already isolated runner.

The caller supplies the container transport. This module never opens a host
network connection, starts a container, follows redirects, or retains a body.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Protocol

from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.web_execution.runtime_evidence import (
    WebHealthCheckAttempt,
    WebHealthCheckResult,
    WebHealthCheckSpec,
    WebHealthCheckStatus,
)

_MAXIMUM_BODY_BYTES = 65_536
_MAXIMUM_OUTPUT_BYTES = 4096
_PROBE_ERRORS = frozenset(
    {
        "TIMEOUT",
        "CONNECTION_FAILED",
        "REDIRECT_REJECTED",
        "RESPONSE_LIMIT_EXCEEDED",
        "RESPONSE_INCOMPLETE",
        "INVALID_HTTP_RESPONSE",
        "INVALID_REQUEST",
    }
)

_NODE_CODE = r"""
const http = require("node:http");
const spec = JSON.parse(process.argv[1]);
const started = performance.now();
let finished = false, request = null, timer = null;
function finish(status_code, error_code) {
  if (finished) return;
  finished = true;
  clearTimeout(timer);
  if (request) request.destroy();
  process.stdout.write(JSON.stringify({status_code, error_code,
    latency_milliseconds: Math.max(0, Math.round(performance.now() - started))}));
}
timer = setTimeout(() => finish(null, "TIMEOUT"), spec.timeout_milliseconds);
try {
  request = http.request({hostname: spec.host, port: spec.port, path: spec.path,
    method: "GET", agent: false, maxHeaderSize: 16384,
    headers: {Connection: "close", Accept: "*/*"}}, response => {
    const status = response.statusCode;
    if (!Number.isInteger(status) || status < 100 || status > 599) {
      response.destroy(); return finish(null, "INVALID_HTTP_RESPONSE");
    }
    if (status >= 300 && status < 400) {
      response.destroy(); return finish(null, "REDIRECT_REJECTED");
    }
    let bytes = 0;
    response.on("data", chunk => {
      bytes += chunk.length;
      if (bytes > spec.maximum_body_bytes) {
        finish(null, "RESPONSE_LIMIT_EXCEEDED"); response.destroy();
      }
    });
    response.on("end", () => finish(status, null));
    response.on("aborted", () => finish(null, "RESPONSE_INCOMPLETE"));
    response.on("error", () => finish(null, "RESPONSE_INCOMPLETE"));
  });
  request.on("error", error => finish(null,
    error.code === "HPE_HEADER_OVERFLOW" ? "RESPONSE_LIMIT_EXCEEDED" : "CONNECTION_FAILED"));
  request.end();
} catch {
  finish(null, "INVALID_REQUEST");
}
"""

_PHP_CODE = r"""
$spec = json_decode($argv[1], true, 16, JSON_THROW_ON_ERROR);
$started = hrtime(true);
$deadline = $started + $spec['timeout_milliseconds'] * 1000000;
$stream = false; $buffer = '';
function finishProbe($status, $error): never {
    global $started, $stream;
    if (is_resource($stream)) fclose($stream);
    echo json_encode(['status_code'=>$status, 'error_code'=>$error,
        'latency_milliseconds'=>max(0, (int)round((hrtime(true)-$started)/1000000))],
        JSON_THROW_ON_ERROR);
    exit(0);
}
function checkDeadline(): int {
    global $deadline;
    $remaining = $deadline - hrtime(true);
    if ($remaining <= 0) finishProbe(null, 'TIMEOUT');
    return $remaining;
}
function waitSocket(bool $writing): void {
    global $stream;
    $remaining = checkDeadline();
    $read = $writing ? [] : [$stream];
    $write = $writing ? [$stream] : [];
    $except = [];
    $seconds = intdiv($remaining, 1000000000);
    $micros = max(1, intdiv($remaining % 1000000000, 1000));
    $ready = stream_select($read, $write, $except, $seconds, $micros);
    if ($ready === false) finishProbe(null, 'CONNECTION_FAILED');
    if ($ready === 0) finishProbe(null, 'TIMEOUT');
    checkDeadline();
}
function readSome(int $limit = 8192): string {
    global $stream;
    while (true) {
        checkDeadline();
        $chunk = fread($stream, $limit);
        if ($chunk === false) finishProbe(null, 'RESPONSE_INCOMPLETE');
        if ($chunk !== '' || feof($stream)) return $chunk;
        waitSocket(false);
    }
}
function readLineBounded(int &$remaining): string {
    global $buffer;
    while (($end = strpos($buffer, "\r\n")) === false) {
        if (strlen($buffer) >= $remaining) finishProbe(null, 'RESPONSE_LIMIT_EXCEEDED');
        if (str_contains($buffer, "\n")) finishProbe(null, 'INVALID_HTTP_RESPONSE');
        $part = readSome(min(8192, $remaining + 1 - strlen($buffer)));
        if ($part === '') finishProbe(null, 'RESPONSE_INCOMPLETE');
        $buffer .= $part;
    }
    if ($end + 2 > $remaining) finishProbe(null, 'RESPONSE_LIMIT_EXCEEDED');
    $line = substr($buffer, 0, $end);
    $buffer = substr($buffer, $end + 2);
    $remaining -= $end + 2;
    if (preg_match('/[\x00-\x08\x0a-\x1f\x7f]/', $line))
        finishProbe(null, 'INVALID_HTTP_RESPONSE');
    checkDeadline();
    return $line;
}
function consumeBytes(int $count, bool $retain = false): string {
    global $buffer;
    $value = '';
    while ($count > 0) {
        checkDeadline();
        if ($buffer === '') {
            $buffer = readSome(min(8192, $count));
            if ($buffer === '') finishProbe(null, 'RESPONSE_INCOMPLETE');
        }
        $take = min($count, strlen($buffer));
        if ($retain) $value .= substr($buffer, 0, $take);
        $buffer = substr($buffer, $take);
        $count -= $take;
    }
    return $value;
}
function headerParts(string $line): array {
    $separator = strpos($line, ':');
    if ($separator === false || $separator === 0) finishProbe(null, 'INVALID_HTTP_RESPONSE');
    $name = substr($line, 0, $separator);
    if (preg_match('/[^!#$%&\'*+.^_\x60|~0-9A-Za-z-]/', $name))
        finishProbe(null, 'INVALID_HTTP_RESPONSE');
    return [strtolower($name), trim(substr($line, $separator + 1))];
}
set_error_handler(static function() { return true; });
$host = $spec['host'] === '::1' ? '[::1]' : $spec['host'];
$stream = stream_socket_client('tcp://'.$host.':'.$spec['port'], $errno, $error,
    checkDeadline()/1000000000, STREAM_CLIENT_CONNECT);
if (!is_resource($stream)) {
    checkDeadline();
    finishProbe(null, 'CONNECTION_FAILED');
}
if (!stream_set_blocking($stream, false)) finishProbe(null, 'CONNECTION_FAILED');
$request = 'GET '.$spec['path']." HTTP/1.1\r\nHost: ".$host.':'.$spec['port'].
    "\r\nConnection: close\r\nAccept: */*\r\n\r\n";
while ($request !== '') {
    checkDeadline();
    $written = fwrite($stream, $request);
    if ($written === false) finishProbe(null, 'CONNECTION_FAILED');
    if ($written === 0) { waitSocket(true); continue; }
    $request = substr($request, $written);
}
$headerBudget = 16384;
do {
    $line = readLineBounded($headerBudget);
    if (!preg_match('/^HTTP\/1\.[01] ([1-5][0-9]{2})(?:[ \t].*)?$/D', $line, $match))
        finishProbe(null, 'INVALID_HTTP_RESPONSE');
    $status = (int)$match[1]; $length = null; $chunked = false;
    if ($status === 101) finishProbe(null, 'INVALID_HTTP_RESPONSE');
    if ($status >= 300 && $status < 400) finishProbe(null, 'REDIRECT_REJECTED');
    while (($line = readLineBounded($headerBudget)) !== '') {
        [$name, $value] = headerParts($line);
        if ($name === 'content-length') {
            if (!preg_match('/^[0-9]+$/D', $value)) finishProbe(null, 'INVALID_HTTP_RESPONSE');
            $digits = ltrim($value, '0');
            if (strlen($digits) > 5 || (int)$digits > $spec['maximum_body_bytes'])
                finishProbe(null, 'RESPONSE_LIMIT_EXCEEDED');
            $declared = (int)$digits;
            if ($length !== null && $length !== $declared)
                finishProbe(null, 'INVALID_HTTP_RESPONSE');
            $length = $declared;
        } elseif ($name === 'transfer-encoding') {
            if ($chunked || strtolower($value) !== 'chunked')
                finishProbe(null, 'INVALID_HTTP_RESPONSE');
            $chunked = true;
        }
    }
    if ($chunked && $length !== null) finishProbe(null, 'INVALID_HTTP_RESPONSE');
} while ($status < 200);
checkDeadline();
if ($status === 204) {
    if ($chunked || ($length !== null && $length !== 0))
        finishProbe(null, 'INVALID_HTTP_RESPONSE');
    finishProbe($status, null);
}
if ($chunked) {
    $bytes = 0;
    while (true) {
        $line = readLineBounded($headerBudget);
        $size = explode(';', $line, 2)[0];
        if (!preg_match('/^[0-9a-fA-F]+$/D', $size))
            finishProbe(null, 'INVALID_HTTP_RESPONSE');
        $digits = ltrim($size, '0');
        if (strlen($digits) > 5 || hexdec($digits ?: '0') > $spec['maximum_body_bytes'] - $bytes)
            finishProbe(null, 'RESPONSE_LIMIT_EXCEEDED');
        $size = (int)hexdec($digits ?: '0');
        if ($size === 0) {
            while (($line = readLineBounded($headerBudget)) !== '') {
                [$name, $value] = headerParts($line);
                if (in_array($name, ['content-length', 'transfer-encoding'], true))
                    finishProbe(null, 'INVALID_HTTP_RESPONSE');
            }
            finishProbe($status, null);
        }
        consumeBytes($size);
        $bytes += $size;
        if (consumeBytes(2, true) !== "\r\n") finishProbe(null, 'INVALID_HTTP_RESPONSE');
    }
}
if ($length !== null) {
    consumeBytes($length);
    checkDeadline();
    finishProbe($status, null);
}
$bytes = strlen($buffer); $buffer = '';
while (true) {
    if ($bytes > $spec['maximum_body_bytes']) finishProbe(null, 'RESPONSE_LIMIT_EXCEEDED');
    $part = readSome(min(8192, $spec['maximum_body_bytes'] + 1 - $bytes));
    if ($part === '') finishProbe($status, null);
    $bytes += strlen($part);
    unset($part);
}
"""


class WebHealthInvoker(Protocol):
    """Run trusted argv inside the caller's existing isolated container only."""

    async def __call__(
        self, argv: tuple[str, ...], *, timeout_seconds: int
    ) -> HostProcessResult: ...


async def probe_web_health(
    spec: WebHealthCheckSpec,
    *,
    invoke: WebHealthInvoker,
    runner_kind: str,
) -> WebHealthCheckResult:
    """Observe each attempt independently; neither transport errors nor redirects pass."""
    _validate_spec(spec)
    if runner_kind not in {"NODE", "BROWSER", "PHP"}:
        raise ValueError("Web health runner kind must be NODE, BROWSER or PHP")
    data = json.dumps(
        {
            "host": "::1" if spec.host == "::1" else "127.0.0.1",
            "port": spec.port,
            "path": spec.path,
            "timeout_milliseconds": spec.request_timeout_seconds * 1000,
            "maximum_body_bytes": _MAXIMUM_BODY_BYTES,
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )
    arguments = (
        ("php", "-r", _PHP_CODE, "--", data)
        if runner_kind == "PHP"
        else ("node", "-e", _NODE_CODE, "--", data)
    )
    timeout_seconds = spec.request_timeout_seconds + 2
    attempts = []
    for number in range(1, spec.maximum_attempts + 1):
        observed_at = datetime.now(UTC)
        started = time.monotonic()
        status_code = None
        error_code = None
        latency = None
        try:
            outcome = await invoke(arguments, timeout_seconds=timeout_seconds)
        except TimeoutError:
            error_code = "TIMEOUT"
        except Exception:
            # The transport may contain private diagnostics; only this fixed code escapes.
            error_code = "PROBE_TRANSPORT_ERROR"
        else:
            if not isinstance(outcome, HostProcessResult):
                error_code = "PROBE_OUTPUT_INVALID"
            elif outcome.status is HostProcessStatus.TIMED_OUT:
                error_code = "TIMEOUT"
            elif outcome.status is not HostProcessStatus.COMPLETED or outcome.exit_code != 0:
                error_code = "PROBE_TRANSPORT_ERROR"
            else:
                try:
                    status_code, error_code, latency = _decode(outcome.stdout, timeout_seconds)
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    error_code = "PROBE_OUTPUT_INVALID"
        if latency is None:
            latency = max(0, round((time.monotonic() - started) * 1000))
        if status_code is not None and 300 <= status_code < 400:
            status_code, error_code = None, "REDIRECT_REJECTED"
        attempts.append(
            WebHealthCheckAttempt(number, observed_at, latency, status_code, error_code)
        )
        if status_code in spec.expected_status_codes:
            return WebHealthCheckResult(spec, WebHealthCheckStatus.HEALTHY, tuple(attempts))
        if number < spec.maximum_attempts:
            await asyncio.sleep(spec.interval_milliseconds / 1000)
    status = (
        WebHealthCheckStatus.TIMED_OUT
        if attempts[-1].error_code == "TIMEOUT"
        else WebHealthCheckStatus.UNHEALTHY
    )
    return WebHealthCheckResult(spec, status, tuple(attempts))


def _validate_spec(spec: WebHealthCheckSpec) -> None:
    if not isinstance(spec, WebHealthCheckSpec):
        raise ValueError("Web health requires a typed specification")
    spec.__post_init__()
    if (
        len(spec.path) > 2048
        or spec.path.startswith("//")
        or "#" in spec.path
        or any(not 33 <= ord(character) <= 126 for character in spec.path)
    ):
        raise ValueError("Web health request path must be bounded unambiguous ASCII")
    for value in (
        spec.port,
        spec.request_timeout_seconds,
        spec.maximum_attempts,
        spec.interval_milliseconds,
        *spec.expected_status_codes,
    ):
        if type(value) is not int:
            raise ValueError("Web health numeric limits and status codes must be integers")


def _decode(body: bytes, timeout_seconds: int) -> tuple[int | None, str | None, int]:
    if not 1 <= len(body) <= _MAXIMUM_OUTPUT_BYTES:
        raise ValueError("invalid output size")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate observation key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("nonfinite observation value")

    value = json.loads(body, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict) or set(value) != {
        "status_code",
        "error_code",
        "latency_milliseconds",
    }:
        raise ValueError("invalid observation schema")
    status = value["status_code"]
    error = value["error_code"]
    latency = value["latency_milliseconds"]
    if type(latency) is not int or not 0 <= latency <= timeout_seconds * 1000:
        raise ValueError("invalid observation latency")
    if (status is None) == (error is None):
        raise ValueError("observation requires exactly one status or error")
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("invalid observation status")
    if error is not None and (not isinstance(error, str) or error not in _PROBE_ERRORS):
        raise ValueError("invalid observation error")
    return status, error, latency
