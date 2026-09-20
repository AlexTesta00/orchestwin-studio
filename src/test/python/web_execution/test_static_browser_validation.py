"""The intentional negative case must fail the intended assertion, not for infrastructure errors."""

import asyncio
import json

import pytest

from orchestwin.web_execution import static_browser_validation as validation
from orchestwin.web_execution.static_browser_executor import decode_inspection
from orchestwin.web_execution.static_browser_jobs import StaticBrowserError, canonical_bytes

from .static_browser_support import (
    FIXTURE_PATH,
    ROOT,
    inspection_result,
    make_observation,
    response,
)


def test_negative_control_cannot_pass_on_an_unrelated_page_error():
    outcome = {
        "status": "COMPLETED",
        "assertion_status": "FAILED",
        "cleanup_confirmed": True,
        "screens": [{"blocked_requests": 0, "page_error_count": 1, "actions": []}],
    }
    with pytest.raises(StaticBrowserError):
        validation.validate_fixture_outcome("FAILED", outcome)


def test_negative_control_cannot_pass_without_a_failed_text_assertion():
    outcome = {
        "status": "COMPLETED",
        "assertion_status": "FAILED",
        "cleanup_confirmed": True,
        "screens": [{"blocked_requests": 0, "page_error_count": 0, "actions": []}],
    }
    with pytest.raises(StaticBrowserError):
        validation.validate_fixture_outcome("FAILED", outcome)


def test_validation_runs_three_distinct_jobs_and_authorizes_only_those(tmp_path, monkeypatch):
    root, manifest_path, _, _, _, _ = make_observation(tmp_path)
    fixture_bytes = (ROOT / FIXTURE_PATH).read_bytes()
    (root / FIXTURE_PATH).parent.mkdir(parents=True)
    (root / FIXTURE_PATH).write_bytes(fixture_bytes)

    async def git_read(*_args, **_kwargs):
        return response(fixture_bytes)

    called = []

    async def executor(job, **kwargs):
        called.append(job)
        receipt = await kwargs["authorize"](job)
        assert receipt.job_content_hash == job.content_hash
        assert receipt.kind == "PROFILE_VALIDATION"
        failed = job.scenarios[0].scenario_id == "intentional-failed-assertion"
        summary, _ = decode_inspection(canonical_bytes(inspection_result(job, fail=failed)), job)
        return {
            **summary,
            "status": "COMPLETED",
            "cleanup_confirmed": True,
            "content_hash": "d" * 64,
        }

    monkeypatch.setattr(validation, "run_bounded_host_process", git_read)
    monkeypatch.setattr(validation, "execute_static_browser_job", executor)
    result = asyncio.run(
        validation.validate_static_browser_executor(root, manifest_path, tmp_path / "out")
    )
    assert result["status"] == "STATIC_BROWSER_EXECUTOR_VALIDATION_PASSED"
    assert len(called) == 3
    assert len({job.content_hash for job in called}) == 3
    assert [item["observed_assertions"] for item in result["results"]] == [
        "PASSED",
        "PASSED",
        "FAILED",
    ]
    assert result["owner_gate_integration_verified"] is False
    assert result["level_d_validated"] is False
    assert result["formal_run_started"] is False
    assert (
        json.loads((tmp_path / "out/manifest.json").read_bytes())["content_hash"]
        == result["content_hash"]
    )
