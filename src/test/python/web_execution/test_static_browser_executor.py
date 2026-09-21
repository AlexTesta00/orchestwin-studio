"""Real compiler/decoder/orchestration with only the Docker command transport doubled."""

import asyncio
import json
from dataclasses import replace

import pytest

from orchestwin.web_execution.static_browser_executor import (
    BrowserExecutionAuthorization,
    decode_inspection,
    execute_static_browser_job,
)
from orchestwin.web_execution.static_browser_jobs import StaticBrowserError, canonical_bytes

from .static_browser_support import DockerTransport, inspection_result, make_observation


async def authorize(job):
    return BrowserExecutionAuthorization(
        job.content_hash, "PROFILE_VALIDATION", "test-only:fixture"
    )


def execute(root, path, job, output, transport, authority=authorize):
    return asyncio.run(
        execute_static_browser_job(
            job,
            repo_root=root,
            runner_manifest=path,
            output_root=output,
            authorize=authority,
            runner=transport,
        )
    )


def test_runs_exact_job_through_stdin_without_build_mounts_or_downloads(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)
    transport = DockerTransport(root, job)
    result = execute(root, path, job, tmp_path / "output", transport)
    assert result["status"] == "COMPLETED"
    assert result["assertion_status"] == "PASSED"
    assert result["cleanup_confirmed"] is True
    assert result["level_d_validated"] is False
    argv = next(call for call, _ in transport.calls if "create" in call)
    assert "--read-only" in argv and "--network" in argv and "none" in argv
    assert "--entrypoint" in argv and "--interactive" in argv
    assert not {"build", "pull", "--mount", "--volume", "--privileged"} & set(argv)
    # Submitted sources and arbitrary script files never appear in Docker command arguments.
    assert not any(file.content.decode() in " ".join(argv) for file in job.files)
    assert any(data == job.wire_bytes() for _, data in transport.calls)


def test_false_assertions_are_records_not_false_successes(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)
    result = execute(
        root, path, job, tmp_path / "output", DockerTransport(root, job, assertions_fail=True)
    )
    assert result["status"] == "COMPLETED"
    assert result["assertion_status"] == "FAILED"
    assert all(screen["status"] == "FAILED" for screen in result["screens"])


@pytest.mark.parametrize("failure", ["start", "cleanup"])
def test_execution_and_cleanup_failures_preserve_failed_manifest(tmp_path, failure):
    root, path, job, _, _, _ = make_observation(tmp_path)
    output = tmp_path / "output"
    with pytest.raises(StaticBrowserError):
        execute(root, path, job, output, DockerTransport(root, job, fail=failure))
    report = json.loads((output / "manifest.json").read_bytes())
    assert report["status"] == "FAILED"
    assert report["cleanup_confirmed"] is (failure != "cleanup")


def test_no_authority_means_no_docker_operations(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)
    transport = DockerTransport(root, job)
    with pytest.raises(StaticBrowserError, match="AUTHORIZATION_REQUIRED"):
        execute(root, path, job, tmp_path / "output", transport, authority=None)
    assert transport.calls == []


def test_different_job_authority_cannot_be_replayed(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)

    async def other(_job):
        return BrowserExecutionAuthorization("f" * 64, "PROFILE_VALIDATION", "test-only")

    transport = DockerTransport(root, job)
    with pytest.raises(StaticBrowserError, match="AUTHORIZATION_MISMATCH"):
        execute(root, path, job, tmp_path / "output", transport, authority=other)
    assert transport.calls == []


def test_runner_binding_is_checked_before_docker(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)
    transport = DockerTransport(root, job)
    with pytest.raises(StaticBrowserError, match="RUNNER_OBSERVATION_MISMATCH"):
        execute(
            root,
            path,
            replace(job, runner_manifest_content_hash="f" * 64),
            tmp_path / "output",
            transport,
        )
    assert transport.calls == []


def test_output_cannot_be_inside_repository(tmp_path):
    root, path, job, _, _, _ = make_observation(tmp_path)
    with pytest.raises(StaticBrowserError, match="OUTPUT"):
        execute(root, path, job, root / "output", DockerTransport(root, job))


@pytest.mark.parametrize(
    "mutation", ["identity", "screens", "sandbox", "false_assertion", "artifact", "summary"]
)
def test_decoder_rejects_corruption_and_false_success(tmp_path, mutation):
    _, _, job, _, _, _ = make_observation(tmp_path)
    raw = inspection_result(job)
    if mutation == "identity":
        raw["job_content_hash"] = "f" * 64
    elif mutation == "screens":
        raw["screens"].pop()
    elif mutation == "sandbox":
        raw["chromium_no_sandbox_flag_absent"] = False
    elif mutation == "false_assertion":
        raw["screens"][0]["actions"][-1]["observed_text"] = "wrong"
    elif mutation == "artifact":
        raw["screens"][0]["dom"]["sha256"] = "f" * 64
    elif mutation == "summary":
        raw["status"] = "FAILED"
    with pytest.raises(StaticBrowserError):
        decode_inspection(canonical_bytes(raw), job)
