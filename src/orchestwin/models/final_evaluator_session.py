"""Read a frozen S67 session and use direct loopback HTTP without SDKs or retries.

A ready file is evidence of startup, not proof that the server is still running.
This client never starts/restarts the model, changes credentials, or follows URLs
from a response. Session tokens are private and are never included in repr/errors.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestwin.models.strict_evaluator_json import canonical_bytes, require, strict_json_object

SERVING_BASE_COMMIT = "fa9b33e9def996a3c26c07b0d986f14b7884eaf7"
RESTART_RUNTIME_ID = "s67-final-evaluator-serving-v2"
RESTART_BASE_COMMIT = "2bfe813da9b78d9b309951b85d6dcdc0e9f14d50"
RESTART_POLICY = "EXPLICIT_COMMIT_AND_COMMITTED_FILES_V1"
RESTART_SERVER_PATH = "environments/training/serve_final_evaluator.py"

MODEL_NAME = "ut-evaluator-s67-final"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
ADAPTER_SHA256 = "82e051affb54f7fdced4c85780f8724fcc8f47063e27997bb6f5624421422664"
IDENTITY_FIELDS = {
    "provider_id": "huggingface-local",
    "runtime_id": "s67-final-evaluator-serving-v1",
    "base_model_repository": MODEL,
    "base_model_revision": REVISION,
    "tokenizer_revision": REVISION,
    "adapter_id": "s67-final-user-twin-evaluator",
    "adapter_sha256": ADAPTER_SHA256,
}


class FinalEvaluatorSessionError(RuntimeError):
    """Stable error codes only, never exception strings from HTTP or local settings."""


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_session_file(path: Path, maximum: int = 4_000_000) -> bytes:
    if ".." in path.parts or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise FinalEvaluatorSessionError("FINAL_SESSION_PATH_REDIRECTED")
    try:
        if not path.is_file() or path.stat().st_size > maximum:
            raise FinalEvaluatorSessionError("FINAL_SESSION_FILE_MISSING_OR_TOO_LARGE")
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
        require(len(raw) <= maximum, "FINAL_SESSION_FILE_TOO_LARGE")
        return raw
    except (OSError, ValueError):
        raise FinalEvaluatorSessionError("FINAL_SESSION_READ_FAILED") from None


def bound_json(raw: bytes) -> dict[str, Any]:
    value = strict_json_object(raw)
    require(
        value.get("content_hash")
        == content_hash({key: item for key, item in value.items() if key != "content_hash"}),
        "FINAL_SESSION_RECORD_HASH_MISMATCH",
    )
    return value


@dataclass(frozen=True, slots=True)
class FinalEvaluatorSession:
    ready_path: Path
    port: int
    identity_json: str
    ready_hash: str
    token: str = field(repr=False)

    @property
    def identity(self) -> dict[str, Any]:
        return strict_json_object(self.identity_json)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def assert_unchanged(self) -> None:
        if load_final_session(self.ready_path) != self:
            raise FinalEvaluatorSessionError("FINAL_SESSION_CHANGED_RECONFIGURE_REQUIRED")


def _validate_runtime_source(ready: dict[str, Any], configuration: dict[str, Any]) -> str:
    """Accept one of two explicit local contracts without relabelling v1 observations."""
    identity = ready.get("model_identity", {})
    runtime_id = identity.get("runtime_id") if isinstance(identity, dict) else None
    if runtime_id == IDENTITY_FIELDS["runtime_id"]:
        require(
            ready.get("platform_commit") == SERVING_BASE_COMMIT
            and configuration.get("platform_commit") == SERVING_BASE_COMMIT
            and ready.get("serving_contract_version", 1) == 1
            and configuration.get("serving_contract_version", 1) == 1,
            "FINAL_LEGACY_SOURCE_MISMATCH",
        )
        return runtime_id
    require(runtime_id == RESTART_RUNTIME_ID, "FINAL_SERVING_CONTRACT_UNSUPPORTED")
    source = configuration.get("source_verification")
    require(isinstance(source, dict), "FINAL_RESTART_SOURCE_MISSING")
    commit = ready.get("platform_commit")
    require(
        type(ready.get("serving_contract_version")) is int
        and ready["serving_contract_version"] == 2
        and type(configuration.get("serving_contract_version")) is int
        and configuration["serving_contract_version"] == 2
        and configuration.get("runtime_id") == RESTART_RUNTIME_ID
        and isinstance(commit, str)
        and re.fullmatch(r"[0-9a-f]{40}", commit) is not None
        and configuration.get("platform_commit") == commit
        and source.get("commit") == commit
        and source.get("base_commit") == RESTART_BASE_COMMIT
        and source.get("policy") == RESTART_POLICY
        and isinstance(source.get("tree"), str)
        and re.fullmatch(r"[0-9a-f]{40}", source["tree"]) is not None,
        "FINAL_RESTART_SOURCE_MISMATCH",
    )
    entries = source.get("files")
    require(isinstance(entries, list) and len(entries) == 3, "FINAL_RESTART_SOURCE_FILES")
    expected = {
        RESTART_SERVER_PATH: "operator_script_sha256",
        "environments/training/run_model_spike.py": "prompt_builder_sha256",
        "environments/training/uv.lock": "training_lock_sha256",
    }
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict), "FINAL_RESTART_SOURCE_FILES")
        path = entry.get("path")
        require(
            isinstance(path, str) and path in expected and path not in seen,
            "FINAL_RESTART_SOURCE_FILES",
        )
        seen.add(path)
        digest = entry.get("sha256")
        blob = entry.get("git_blob")
        require(
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
            and isinstance(blob, str)
            and re.fullmatch(r"[0-9a-f]{40}", blob) is not None
            and type(entry.get("size_bytes")) is int
            and entry["size_bytes"] > 0
            and configuration.get(expected[path]) == digest,
            "FINAL_RESTART_SOURCE_DIGEST_MISMATCH",
        )
        if path == "environments/training/run_model_spike.py":
            require(
                blob == "5cbd0c6d2c832630aa2f357eae9b8c8ebcc7e25f", "FINAL_RESTART_LOADER_CHANGED"
            )
    return runtime_id


def load_final_session(path: Path) -> FinalEvaluatorSession:
    """Require an explicit v1 or restartable v2 session, never a recent-directory guess."""
    path = Path(path)
    if not path.is_absolute():
        raise FinalEvaluatorSessionError("FINAL_SESSION_ABSOLUTE_PATH_REQUIRED")
    if any((path.parent / name).exists() for name in ("stopped.json", "failure.json")):
        raise FinalEvaluatorSessionError("FINAL_SESSION_TERMINATED")
    try:
        ready = bound_json(read_session_file(path))
        require(
            ready.get("status") == "FINAL_EVALUATOR_SERVING_READY"
            and ready.get("model_name") == MODEL_NAME
            and ready.get("host") == "127.0.0.1"
            and type(ready.get("port")) is int
            and 1024 <= ready["port"] <= 65535
            and ready.get("credential_file") == "access-token.secret",
            "FINAL_SESSION_ENDPOINT_OR_VERSION_INVALID",
        )
        identity = ready.get("model_identity")
        require(
            isinstance(identity, dict)
            and set(identity) == {*IDENTITY_FIELDS, "configuration_sha256"}
            and all(
                identity[key] == value
                for key, value in IDENTITY_FIELDS.items()
                if key != "runtime_id"
            ),
            "FINAL_SESSION_IDENTITY_INVALID",
        )
        configuration = bound_json(read_session_file(path.parent / "configuration.json"))
        _validate_runtime_source(ready, configuration)
        require(
            configuration["content_hash"] == identity["configuration_sha256"]
            and configuration.get("model_name") == MODEL_NAME
            and configuration.get("adapter_sha256") == ADAPTER_SHA256,
            "FINAL_SESSION_CONFIGURATION_INVALID",
        )
        require(
            ready.get("authenticated_health_verified") is True
            and ready.get("training_executed") is False
            and ready.get("formal_run_started") is False,
            "FINAL_SESSION_SCOPE_INVALID",
        )
        token = read_session_file(path.parent / "access-token.secret", 100).decode("ascii").strip()
        require(re.fullmatch(r"[0-9a-f]{64}", token), "FINAL_SESSION_CREDENTIAL_INVALID")
    except (ValueError, UnicodeError, KeyError, TypeError):
        raise FinalEvaluatorSessionError("FINAL_SESSION_VALIDATION_FAILED") from None
    return FinalEvaluatorSession(
        path, ready["port"], canonical_bytes(identity).decode(), ready["content_hash"], token
    )


@dataclass(frozen=True, slots=True)
class SessionHttpResponse:
    status_code: int
    body: bytes = field(repr=False)
    elapsed_milliseconds: int


def session_http(
    session: FinalEvaluatorSession,
    method: str,
    path: str,
    body: bytes | None = None,
    timeout: int = 90,
) -> SessionHttpResponse:
    require(
        (method, path) in {("GET", "/health"), ("POST", "/v1/chat/completions")},
        "FINAL_SESSION_OPERATION_FORBIDDEN",
    )
    require(type(timeout) is int and 1 <= timeout <= 90, "FINAL_SESSION_TIMEOUT_INVALID")
    require(
        body is None or (isinstance(body, bytes) and len(body) <= 2_000_000),
        "FINAL_SESSION_REQUEST_TOO_LARGE",
    )
    session.assert_unchanged()
    client = http.client.HTTPConnection("127.0.0.1", session.port, timeout=timeout)
    started = time.monotonic()
    try:
        headers = {"Authorization": "Bearer " + session.token, "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        client.request(method, path, body=body, headers=headers)
        response = client.getresponse()
        raw = response.read(4_000_001)
        require(len(raw) <= 4_000_000, "FINAL_SESSION_RESPONSE_TOO_LARGE")
        require(
            response.getheader("Content-Type", "").split(";", 1)[0] == "application/json",
            "FINAL_SESSION_CONTENT_TYPE_INVALID",
        )
        # Redirects are rejected, not followed; http.client ignores proxy environment.
        require(not 300 <= response.status < 400, "FINAL_SESSION_REDIRECT_REJECTED")
        return SessionHttpResponse(response.status, raw, round((time.monotonic() - started) * 1000))
    except (OSError, http.client.HTTPException):
        raise FinalEvaluatorSessionError("FINAL_SESSION_HTTP_FAILED_NO_RETRY") from None
    finally:
        client.close()


def check_final_health(session: FinalEvaluatorSession) -> dict[str, Any]:
    response = session_http(session, "GET", "/health", timeout=10)
    require(response.status_code == 200, "FINAL_SESSION_HEALTH_HTTP_REJECTED")
    health = strict_json_object(response.body)
    observed = health.get("load_observation", {})
    require(
        health.get("status") == "FINAL_EVALUATOR_READY"
        and health.get("model_name") == MODEL_NAME
        and health.get("model_identity") == session.identity
        and observed.get("base_revision_observed") == REVISION
        and observed.get("active_adapters") == ["default"]
        and observed.get("load_in_4bit_observed") is True
        and type(observed.get("trainable_parameters")) is int
        and observed["trainable_parameters"] == 0
        and health.get("fallback_policy") == "FAIL_CLOSED_NO_BASE_FALLBACK"
        and health.get("training_executed") is False
        and health.get("benchmark_reexecuted") is False,
        "FINAL_SESSION_LIVE_IDENTITY_OR_POLICY_MISMATCH",
    )
    require(
        type(health.get("completed_generation_count")) is int
        and health["completed_generation_count"] >= 0,
        "FINAL_SESSION_COUNTER_INVALID",
    )
    return health
