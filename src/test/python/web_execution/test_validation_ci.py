"""Observed GitHub CI provenance, with no network access in these tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler

import pytest

from orchestwin.web_execution.validation_ci import (
    CiHttpResponse,
    CiVerificationStatus,
    GitHubCiVerifier,
    UrllibCiTransport,
)

REPOSITORY = "owner/project"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
WORKFLOW = b"name: CI/CD\non: [push]\njobs: {}\n"


def run_record(run_id=90, attempt=2, **changes):
    row = {
        "id": run_id,
        "run_attempt": attempt,
        "head_sha": COMMIT,
        "name": "CI/CD",
        "path": ".github/workflows/ci-cd.yml",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }
    return row | changes


def jobs():
    rows = []
    for index, os_name in enumerate(("ubuntu-24.04", "macos-14", "windows-2025"), 1):
        suffix = " with coverage" if os_name.startswith("ubuntu") else ""
        names = [
            "Run backend tests" + suffix,
            "Run frontend tests",
            "Upgrade PostgreSQL to Alembic head",
            "Run PostgreSQL integration tests" + suffix,
        ]
        rows.append(job(index, f"Test ({os_name})", names))
    rows.append(
        job(
            4,
            "Verify Web runners and fixture contracts",
            [
                "Validate pinned runner manifest",
                "Verify complete Web profile fixture matrix",
                "Build controlled Web runner images",
                "Smoke test non-root runner images without network",
                "Record local runner image identities",
            ],
        )
    )
    return rows


def job(job_id, name, step_names):
    return {
        "id": job_id,
        "run_id": 90,
        "head_sha": COMMIT,
        "name": name,
        "status": "completed",
        "conclusion": "success",
        "steps": [
            {"name": name, "status": "completed", "conclusion": "success"} for name in step_names
        ],
    }


class FakeTransport:
    def __init__(self):
        self.runs = [run_record()]
        self.job_rows = jobs()
        self.workflow = WORKFLOW
        self.calls = []
        self.response_bodies = []
        self.status_code = 200
        self.exception = None
        self.run_reads = 0
        self.changed_attempt = False
        self.jobs_total = None
        self.raw_body = None

    def get(self, url, *, headers, timeout_seconds, max_response_bytes):
        self.calls.append((url, dict(headers), timeout_seconds, max_response_bytes))
        if self.exception:
            raise self.exception
        path = urlsplit(url).path
        query = parse_qs(urlsplit(url).query)
        if "/contents/" in path:
            payload = {
                "type": "file",
                "path": ".github/workflows/ci-cd.yml",
                "size": len(self.workflow),
                "encoding": "base64",
                "content": base64.b64encode(self.workflow).decode(),
            }
        elif path.endswith("/jobs"):
            page = int(query["page"][0])
            payload = {
                "total_count": len(self.job_rows) if self.jobs_total is None else self.jobs_total,
                "jobs": self.job_rows[(page - 1) * 100 : page * 100],
            }
        elif path.endswith("/actions/runs"):
            page = int(query["page"][0])
            payload = {
                "total_count": len(self.runs),
                "workflow_runs": self.runs[(page - 1) * 100 : page * 100],
            }
        else:
            self.run_reads += 1
            payload = copy.deepcopy(max(self.runs, key=lambda row: row["id"]))
            if self.changed_attempt and self.run_reads > 1:
                payload["run_attempt"] += 1
        body = self.raw_body if self.raw_body is not None else json.dumps(payload).encode()
        self.response_bodies.append(body)
        return CiHttpResponse(self.status_code, body)


@pytest.fixture
def verifier(monkeypatch, tmp_path):
    def local_git(argv, **kwargs):
        assert argv[:3] == ["git", "-C", str(tmp_path)]
        assert argv[-1] == f"{COMMIT}:.github/workflows/ci-cd.yml"
        assert kwargs["timeout"] <= 30
        output = str(len(WORKFLOW)).encode() if "cat-file" in argv else WORKFLOW
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")

    monkeypatch.setattr(subprocess, "run", local_git)
    transport = FakeTransport()
    instance = GitHubCiVerifier(REPOSITORY, COMMIT, repo_root=tmp_path, transport=transport)
    return instance, transport


def test_exact_success_preserves_provider_bytes_and_workflow_commit(verifier):
    instance, transport = verifier
    result = instance.verify()
    assert result.status is CiVerificationStatus.PASSED
    assert result.passed
    assert result.run_id == 90
    assert result.run_attempt == 2
    assert result.head_sha == COMMIT
    assert result.workflow_sha256 == hashlib.sha256(WORKFLOW).hexdigest()
    assert result.observed_at.utcoffset().total_seconds() == 0
    assert [row.body for row in result.responses] == transport.response_bodies
    assert all(row.sha256 == hashlib.sha256(row.body).hexdigest() for row in result.responses)
    assert result.to_snapshot()["status"] == "PASSED"
    assert all(urlsplit(row[0]).hostname == "api.github.com" for row in transport.calls)
    assert any("/90/attempts/2/jobs?" in row[0] for row in transport.calls)
    assert any(f"ref={COMMIT}" in row[0] for row in transport.calls)


@pytest.mark.parametrize("event", ["push", "pull_request", "workflow_dispatch"])
def test_same_repository_commit_events_are_accepted(verifier, event):
    instance, transport = verifier
    transport.runs[0]["event"] = event
    transport.runs[0]["path"] += "@main"
    assert instance.verify().passed


@pytest.mark.parametrize(
    "changes",
    [
        {"head_sha": "f" * 40},
        {"head_repository": {"full_name": "other/fork"}},
        {"repository": {"full_name": "other/project"}},
        {"path": ".github/workflows/other.yml"},
        {"name": "Other workflow"},
        {"event": "pull_request_target"},
    ],
)
def test_unrelated_run_cannot_supply_evidence(verifier, changes):
    instance, transport = verifier
    transport.runs = [run_record(**changes)]
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


@pytest.mark.parametrize("state", ["queued", "in_progress", "waiting"])
def test_latest_running_run_does_not_fall_back_to_older_success(verifier, state):
    instance, transport = verifier
    transport.runs.append(run_record(91, status=state, conclusion=None))
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert result.run_id == 91


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "action_required"])
def test_observed_unsuccessful_run_is_failed(verifier, conclusion):
    instance, transport = verifier
    transport.runs[0]["conclusion"] = conclusion
    result = instance.verify()
    assert result.status is CiVerificationStatus.FAILED
    assert result.conclusion == conclusion


@pytest.mark.parametrize("index", range(4))
def test_missing_required_job_is_incomplete(verifier, index):
    instance, transport = verifier
    del transport.job_rows[index]
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


@pytest.mark.parametrize("index", range(4))
def test_missing_required_step_is_incomplete(verifier, index):
    instance, transport = verifier
    del transport.job_rows[index]["steps"][0]
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


@pytest.mark.parametrize("conclusion", ["skipped", "failure", "cancelled"])
def test_non_success_required_step_cannot_pass(verifier, conclusion):
    instance, transport = verifier
    transport.job_rows[0]["steps"][0]["conclusion"] = conclusion
    assert not instance.verify().passed


@pytest.mark.parametrize("field,value", [("head_sha", "f" * 40), ("run_id", 89)])
def test_job_identity_must_match_observed_run(verifier, field, value):
    instance, transport = verifier
    transport.job_rows[0][field] = value
    assert instance.verify().status is CiVerificationStatus.FAILED


def test_duplicate_required_job_is_rejected(verifier):
    instance, transport = verifier
    transport.job_rows.append(copy.deepcopy(transport.job_rows[0]) | {"id": 99})
    assert instance.verify().status is CiVerificationStatus.FAILED


def test_latest_attempt_changes_during_collection_fail_closed(verifier):
    instance, transport = verifier
    transport.changed_attempt = True
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


def test_workflow_content_must_match_local_committed_bytes(verifier):
    instance, transport = verifier
    transport.workflow = WORKFLOW + b"# changed\n"
    assert instance.verify().status is CiVerificationStatus.FAILED


def test_jobs_are_paginated_and_required_jobs_can_be_on_second_page(verifier):
    instance, transport = verifier
    transport.job_rows = [job(100 + i, f"Other {i}", []) for i in range(100)] + jobs()
    assert instance.verify().passed
    assert any("/jobs?" in row[0] and "page=2" in row[0] for row in transport.calls)


def test_pagination_limit_never_claims_complete(verifier):
    instance, transport = verifier
    transport.jobs_total = 1001
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert "CI_PAGINATION_LIMIT" in result.issue_codes


@pytest.mark.parametrize("status_code", [301, 302, 401, 403, 404, 429, 500])
def test_http_errors_are_incomplete_without_following_returned_urls(verifier, status_code):
    instance, transport = verifier
    transport.status_code = status_code
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert len(result.responses) == 1


@pytest.mark.parametrize("raw", [b"{", b"null", b"[]", b'{"total_count":NaN}', b'{"a":1,"a":2}'])
def test_malformed_provider_json_fails_closed(verifier, raw):
    instance, transport = verifier
    transport.raw_body = raw
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


def test_network_exception_does_not_leak_token_or_exception_text(verifier):
    instance, transport = verifier
    transport.exception = OSError("secret-token-never-report")
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert "secret-token" not in repr(result)
    assert "secret-token" not in json.dumps(result.to_snapshot())


def test_response_size_limit_is_applied_even_to_injected_transport(verifier):
    instance, transport = verifier
    transport.raw_body = b" " * (2 * 1024 * 1024 + 1)
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert "CI_RESPONSE_LIMIT" in result.issue_codes


@pytest.mark.parametrize(
    "repository,commit",
    [
        ("https://github.com/owner/project", COMMIT),
        ("owner/../project", COMMIT),
        ("owner/project?secret", COMMIT),
        ("owner/project", "main"),
        ("owner/project", "-" * 40),
    ],
)
def test_untrusted_repository_and_revision_inputs_are_rejected(repository, commit):
    with pytest.raises(ValueError):
        GitHubCiVerifier(repository, commit, repo_root=Path.cwd())


@pytest.mark.parametrize("field,value", [("event", []), ("conclusion", {}), ("id", True)])
def test_malformed_run_field_types_are_incomplete(verifier, field, value):
    instance, transport = verifier
    transport.runs[0][field] = value
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


def test_changed_current_run_status_after_job_collection_is_incomplete(verifier):
    instance, transport = verifier
    original = transport.get

    def changing(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith("/actions/runs/90") and transport.run_reads == 2:
            payload = json.loads(response.body) | {"status": "in_progress", "conclusion": None}
            return CiHttpResponse(200, json.dumps(payload).encode())
        return response

    transport.get = changing
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


def test_job_attempt_boolean_is_not_a_valid_attempt_number(verifier):
    instance, transport = verifier
    transport.runs[0]["run_attempt"] = 1
    transport.job_rows[0]["run_attempt"] = True
    assert instance.verify().status is CiVerificationStatus.FAILED


def test_newest_run_starting_during_collection_invalidates_previous_success(verifier):
    instance, transport = verifier
    original = transport.get

    def new_run(url, **kwargs):
        if url.endswith("/actions/runs/90") and transport.run_reads == 1:
            response = original(url, **kwargs)
            transport.runs.append(run_record(91, status="in_progress", conclusion=None))
            return response
        return original(url, **kwargs)

    transport.get = new_run
    assert instance.verify().status is CiVerificationStatus.INCOMPLETE


def test_urllib_transport_disables_redirects_and_ambient_proxies(monkeypatch):
    calls = []
    seen_handlers = []

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request, timeout))
            return Response(b"123456789")

    def make_opener(*handlers):
        seen_handlers.extend(handlers)
        return Opener()

    monkeypatch.setattr("orchestwin.web_execution.validation_ci.build_opener", make_opener)
    result = UrllibCiTransport().get(
        "https://api.github.com/repos/owner/project/actions/runs",
        headers={"Authorization": "Bearer test-token"},
        timeout_seconds=3,
        max_response_bytes=5,
    )
    assert result.body == b"123456"
    assert calls[0][0].method == "GET"
    assert calls[0][1] == 3
    proxy = next(row for row in seen_handlers if isinstance(row, ProxyHandler))
    assert proxy.proxies == {}
    redirect = next(row for row in seen_handlers if isinstance(row, HTTPRedirectHandler))
    assert redirect.redirect_request(None, None, 302, "", {}, "https://evil.invalid") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/repos/owner/project",
        "https://api.github.com.evil.invalid/repos/owner/project",
        "https://token@api.github.com/repos/owner/project",
        "https://api.github.com:8443/repos/owner/project",
    ],
)
def test_urllib_transport_refuses_destinations_outside_https_github(url):
    with pytest.raises(ValueError):
        UrllibCiTransport().get(url, headers={}, timeout_seconds=1, max_response_bytes=100)


def test_local_git_failure_has_no_network_or_stderr_disclosure(verifier, monkeypatch):
    instance, transport = verifier
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, stdout=b"", stderr=b"sensitive local diagnostics"
        ),
    )
    result = instance.verify()
    assert result.status is CiVerificationStatus.INCOMPLETE
    assert result.issue_codes == ("CI_LOCAL_WORKFLOW_UNAVAILABLE",)
    assert not transport.calls
    assert "sensitive" not in repr(result)
