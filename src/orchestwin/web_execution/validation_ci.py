"""Read-only, bounded GitHub Actions observations for Web validation provenance.

This module verifies provider observations; it does not publish evidence or promote
profiles. Callers persist ``responses`` as bytes in their evidence store. Async
callers must run the synchronous verifier outside the event-loop thread.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

WORKFLOW_PATH: Final = ".github/workflows/ci-cd.yml"
_API_ROOT: Final = "https://api.github.com"
_REPOSITORY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
_MAX_TOTAL_BYTES: Final = 16 * 1024 * 1024
_MAX_WORKFLOW_BYTES: Final = 256 * 1024
_MAX_PAGES: Final = 10
_TIMEOUT_SECONDS: Final = 15
_REQUIRED_JOB_STEPS: Final = (
    (
        "Test (ubuntu-24.04)",
        (
            "Run backend tests with coverage",
            "Run frontend tests",
            "Upgrade PostgreSQL to Alembic head",
            "Run PostgreSQL integration tests with coverage",
        ),
    ),
    (
        "Test (macos-14)",
        (
            "Run backend tests",
            "Run frontend tests",
            "Upgrade PostgreSQL to Alembic head",
            "Run PostgreSQL integration tests",
        ),
    ),
    (
        "Test (windows-2025)",
        (
            "Run backend tests",
            "Run frontend tests",
            "Upgrade PostgreSQL to Alembic head",
            "Run PostgreSQL integration tests",
        ),
    ),
    (
        "Verify Web runners and fixture contracts",
        (
            "Validate pinned runner manifest",
            "Verify complete Web profile fixture matrix",
            "Build controlled Web runner images",
            "Smoke test non-root runner images without network",
            "Record local runner image identities",
        ),
    ),
)


class CiVerificationStatus(StrEnum):
    PASSED = "PASSED"
    INCOMPLETE = "INCOMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CiHttpResponse:
    status_code: int
    body: bytes


class CiTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> CiHttpResponse: ...


@dataclass(frozen=True, slots=True)
class CiProviderResponse:
    """Original provider bytes with a computed digest, never supplied by a caller."""

    url: str
    status_code: int
    body: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "sha256": self.sha256,
            "size_bytes": len(self.body),
        }


@dataclass(frozen=True, slots=True)
class VerifiedCiObservation:
    """Typed result including incomplete/failed observations, without a supplied pass flag."""

    status: CiVerificationStatus
    repository: str
    commit: str
    run_id: int | None
    run_attempt: int | None
    workflow_sha256: str | None
    observed_at: datetime
    issue_codes: tuple[str, ...]
    responses: tuple[CiProviderResponse, ...]
    conclusion: str | None = None
    verified_jobs: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status is CiVerificationStatus.PASSED

    @property
    def provider(self) -> str:
        return "GITHUB_ACTIONS"

    @property
    def head_sha(self) -> str:
        return self.commit

    @property
    def workflow_path(self) -> str:
        return WORKFLOW_PATH

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "provider": self.provider,
            "status": self.status.value,
            "repository": self.repository,
            "commit": self.commit,
            "head_sha": self.head_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "conclusion": self.conclusion,
            "workflow_path": self.workflow_path,
            "workflow_sha256": self.workflow_sha256,
            "observed_at": self.observed_at.isoformat(),
            "issue_codes": list(self.issue_codes),
            "required_jobs": [name for name, _ in _REQUIRED_JOB_STEPS],
            "verified_jobs": list(self.verified_jobs),
            "responses": [row.to_snapshot() for row in self.responses],
        }


class _CiIssue(Exception):
    def __init__(self, code: str, status=CiVerificationStatus.INCOMPLETE):
        super().__init__(code)
        self.code = code
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibCiTransport:
    """HTTPS GitHub only; no redirects or implicit operator proxy credentials."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> CiHttpResponse:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.fragment:
            raise ValueError("CI transport only accepts the GitHub HTTPS API")
        request = Request(url, headers=dict(headers), method="GET")
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            response = opener.open(request, timeout=timeout_seconds)
        except HTTPError as error:
            response = error
        with response:
            deadline = time.monotonic() + timeout_seconds
            chunks = []
            size = 0
            while size <= max_response_bytes:
                if time.monotonic() >= deadline:
                    raise TimeoutError("CI response deadline exceeded")
                chunk = response.read1(min(65536, max_response_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if time.monotonic() >= deadline:
                raise TimeoutError("CI response deadline exceeded")
            return CiHttpResponse(response.status, b"".join(chunks))


class GitHubCiVerifier:
    """Collect exact-revision CI/CD status and latest-attempt job/step observations."""

    def __init__(
        self,
        repository: str,
        commit: str,
        *,
        repo_root: Path,
        transport: CiTransport | None = None,
        token: str | None = None,
    ):
        if (
            not isinstance(repository, str)
            or _REPOSITORY.fullmatch(repository) is None
            or repository.split("/")[1] in {".", ".."}
        ):
            raise ValueError("CI repository must be a normalized GitHub owner/repository")
        if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
            raise ValueError("CI commit must be a full lowercase Git commit SHA")
        if token is not None and (
            not isinstance(token, str)
            or not token
            or not token.isascii()
            or not token.isprintable()
        ):
            raise ValueError("CI token must be a nonempty printable ASCII value")
        self.repository = repository
        self.commit = commit
        self.repo_root = Path(repo_root)
        self._transport = transport or UrllibCiTransport()
        self._token = token

    def verify(self) -> VerifiedCiObservation:
        collection = _CiCollection(self)
        return collection.verify()


class _CiCollection:
    """One invocation's isolated receipt set; verifier instances do not cache evidence."""

    def __init__(self, verifier: GitHubCiVerifier):
        self.verifier = verifier
        self.responses: list[CiProviderResponse] = []
        self.total_bytes = 0
        self.run_id = None
        self.run_attempt = None
        self.conclusion = None
        self.workflow_sha256 = None
        self.verified_jobs = ()

    def verify(self) -> VerifiedCiObservation:
        status = CiVerificationStatus.PASSED
        issues = ()
        try:
            local_workflow = self._committed_workflow()
            selected = self._latest_run()
            self.run_id = _positive_int(selected.get("id"))
            self.run_attempt = _positive_int(selected.get("run_attempt"))
            current = self._get(f"actions/runs/{self.run_id}")
            self._same_run(current)
            self.conclusion = (
                current.get("conclusion") if isinstance(current.get("conclusion"), str) else None
            )
            _require_success(current, "CI_RUN")
            self._workflow(local_workflow)
            rows = self._pages(
                f"actions/runs/{self.run_id}/attempts/{self.run_attempt}/jobs", "jobs"
            )
            self._jobs(rows)
            # A rerun starting while pages are read must not inherit the earlier
            # attempt's successful jobs. Also recheck the newest run for the SHA.
            refreshed = self._get(f"actions/runs/{self.run_id}")
            self._same_run(refreshed)
            _require_success(refreshed, "CI_RUN")
            latest = self._latest_run()
            self._same_run(latest)
            _require_success(latest, "CI_RUN")
        except _CiIssue as issue:
            status = issue.status
            issues = (issue.code,)
        return VerifiedCiObservation(
            status=status,
            repository=self.verifier.repository,
            commit=self.verifier.commit,
            run_id=self.run_id,
            run_attempt=self.run_attempt,
            workflow_sha256=self.workflow_sha256,
            observed_at=datetime.now(UTC),
            issue_codes=issues,
            responses=tuple(self.responses),
            conclusion=self.conclusion,
            verified_jobs=self.verified_jobs,
        )

    def _committed_workflow(self) -> bytes:
        prefix = ["git", "-C", str(self.verifier.repo_root)]
        reference = f"{self.verifier.commit}:{WORKFLOW_PATH}"
        try:
            size = subprocess.run(
                [*prefix, "cat-file", "-s", reference],
                capture_output=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
            if size.returncode != 0 or not 0 < int(size.stdout) <= _MAX_WORKFLOW_BYTES:
                raise _CiIssue("CI_LOCAL_WORKFLOW_UNAVAILABLE")
            result = subprocess.run(
                [*prefix, "show", reference],
                capture_output=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
            if result.returncode != 0 or len(result.stdout) != int(size.stdout):
                raise _CiIssue("CI_LOCAL_WORKFLOW_UNAVAILABLE")
            return result.stdout
        except (OSError, ValueError, subprocess.SubprocessError) as from_error:
            raise _CiIssue("CI_LOCAL_WORKFLOW_UNAVAILABLE") from from_error

    def _get(self, path: str, query: Mapping[str, object] | None = None) -> dict:
        url = f"{_API_ROOT}/repos/{self.verifier.repository}/{path}"
        if query:
            url += "?" + urlencode(query)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OrchesTwin-Web-Validation",
        }
        if self.verifier._token is not None:
            headers["Authorization"] = "Bearer " + self.verifier._token
        try:
            response = self.verifier._transport.get(
                url,
                headers=headers,
                timeout_seconds=_TIMEOUT_SECONDS,
                max_response_bytes=_MAX_RESPONSE_BYTES,
            )
        except (OSError, URLError, ValueError):
            # Exception messages may contain credentials or response bodies.
            raise _CiIssue("CI_PROVIDER_UNAVAILABLE") from None
        if not isinstance(response, CiHttpResponse) or not isinstance(response.body, bytes):
            raise _CiIssue("CI_PROVIDER_RESPONSE_INVALID")
        self.total_bytes += len(response.body)
        if len(response.body) > _MAX_RESPONSE_BYTES or self.total_bytes > _MAX_TOTAL_BYTES:
            raise _CiIssue("CI_RESPONSE_LIMIT")
        self.responses.append(CiProviderResponse(url, response.status_code, response.body))
        if type(response.status_code) is not int or response.status_code != 200:
            raise _CiIssue("CI_PROVIDER_HTTP_ERROR")
        try:
            payload = json.loads(
                response.body,
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise _CiIssue("CI_PROVIDER_JSON_INVALID") from None
        if not isinstance(payload, dict):
            raise _CiIssue("CI_PROVIDER_JSON_INVALID")
        return payload

    def _pages(self, path: str, key: str, query: Mapping[str, object] | None = None) -> list:
        rows = []
        total = None
        for page in range(1, _MAX_PAGES + 1):
            payload = self._get(path, dict(query or {}) | {"per_page": 100, "page": page})
            count = payload.get("total_count")
            batch = payload.get(key)
            if type(count) is not int or count < 0 or not isinstance(batch, list):
                raise _CiIssue("CI_PAGINATION_INVALID")
            if count > _MAX_PAGES * 100:
                raise _CiIssue("CI_PAGINATION_LIMIT")
            if total is not None and total != count:
                raise _CiIssue("CI_PROVIDER_CHANGED")
            total = count
            if len(batch) > 100 or any(not isinstance(row, dict) for row in batch):
                raise _CiIssue("CI_PAGINATION_INVALID")
            rows.extend(batch)
            if len(rows) == total:
                return rows
            if len(batch) != 100 or len(rows) > total:
                raise _CiIssue("CI_PAGINATION_INVALID")
        raise _CiIssue("CI_PAGINATION_LIMIT")

    def _is_expected_run(self, row: dict) -> bool:
        path = row.get("path")
        return (
            row.get("head_sha") == self.verifier.commit
            and row.get("name") == "CI/CD"
            and isinstance(path, str)
            and (path == WORKFLOW_PATH or path.startswith(WORKFLOW_PATH + "@"))
            and isinstance(row.get("event"), str)
            and row.get("event") in {"push", "pull_request", "workflow_dispatch"}
            and all(
                isinstance(row.get(key), dict)
                and isinstance(row[key].get("full_name"), str)
                and row[key]["full_name"].casefold() == self.verifier.repository.casefold()
                for key in ("repository", "head_repository")
            )
        )

    def _latest_run(self) -> dict:
        rows = self._pages("actions/runs", "workflow_runs", {"head_sha": self.verifier.commit})
        matching = [row for row in rows if self._is_expected_run(row)]
        if not matching:
            raise _CiIssue("CI_MATCHING_RUN_MISSING")
        identities = [_positive_int(row.get("id")) for row in matching]
        if len(set(identities)) != len(identities):
            raise _CiIssue("CI_PROVIDER_CHANGED")
        return max(matching, key=lambda row: row["id"])

    def _same_run(self, row: dict) -> None:
        if (
            not self._is_expected_run(row)
            or row.get("id") != self.run_id
            or type(row.get("id")) is not int
            or row.get("run_attempt") != self.run_attempt
            or type(row.get("run_attempt")) is not int
        ):
            raise _CiIssue("CI_PROVIDER_CHANGED")

    def _workflow(self, local: bytes) -> None:
        payload = self._get("contents/" + WORKFLOW_PATH, {"ref": self.verifier.commit})
        content = payload.get("content")
        if (
            payload.get("type") != "file"
            or payload.get("path") != WORKFLOW_PATH
            or payload.get("encoding") != "base64"
            or type(payload.get("size")) is not int
            or not 0 < payload["size"] <= _MAX_WORKFLOW_BYTES
            or not isinstance(content, str)
        ):
            raise _CiIssue("CI_WORKFLOW_RESPONSE_INVALID")
        try:
            raw = base64.b64decode(content.replace("\n", "").replace("\r", ""), validate=True)
        except (ValueError, binascii.Error):
            raise _CiIssue("CI_WORKFLOW_RESPONSE_INVALID") from None
        if len(raw) != payload["size"] or raw != local:
            raise _CiIssue("CI_WORKFLOW_MISMATCH", CiVerificationStatus.FAILED)
        self.workflow_sha256 = hashlib.sha256(raw).hexdigest()

    def _jobs(self, rows: list[dict]) -> None:
        ids = [_positive_int(row.get("id")) for row in rows]
        if len(set(ids)) != len(ids):
            raise _CiIssue("CI_JOB_DUPLICATE", CiVerificationStatus.FAILED)
        for row in rows:
            if (
                row.get("head_sha") != self.verifier.commit
                or row.get("run_id") != self.run_id
                or type(row.get("run_id")) is not int
                or (
                    "run_attempt" in row
                    and (
                        type(row["run_attempt"]) is not int
                        or row["run_attempt"] != self.run_attempt
                    )
                )
            ):
                raise _CiIssue("CI_JOB_IDENTITY_MISMATCH", CiVerificationStatus.FAILED)
        for name, steps in _REQUIRED_JOB_STEPS:
            matching = [row for row in rows if row.get("name") == name]
            if not matching:
                raise _CiIssue("CI_REQUIRED_JOB_MISSING")
            if len(matching) != 1:
                raise _CiIssue("CI_JOB_DUPLICATE", CiVerificationStatus.FAILED)
            row = matching[0]
            _require_success(row, "CI_JOB")
            observed_steps = row.get("steps")
            if not isinstance(observed_steps, list) or any(
                not isinstance(step, dict) for step in observed_steps
            ):
                raise _CiIssue("CI_REQUIRED_STEP_MISSING")
            for step_name in steps:
                found = [step for step in observed_steps if step.get("name") == step_name]
                if not found:
                    raise _CiIssue("CI_REQUIRED_STEP_MISSING")
                if len(found) != 1:
                    raise _CiIssue("CI_STEP_DUPLICATE", CiVerificationStatus.FAILED)
                _require_success(found[0], "CI_STEP")
        self.verified_jobs = tuple(name for name, _ in _REQUIRED_JOB_STEPS)


def _require_success(row: dict, label: str) -> None:
    if row.get("status") != "completed":
        raise _CiIssue(label + "_INCOMPLETE")
    conclusion = row.get("conclusion")
    if not isinstance(conclusion, str):
        raise _CiIssue(label + "_INCOMPLETE")
    if conclusion != "success":
        status = (
            CiVerificationStatus.FAILED
            if conclusion
            in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
            else CiVerificationStatus.INCOMPLETE
        )
        raise _CiIssue(label + "_UNSUCCESSFUL", status)


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise _CiIssue("CI_PROVIDER_IDENTITY_INVALID")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")
