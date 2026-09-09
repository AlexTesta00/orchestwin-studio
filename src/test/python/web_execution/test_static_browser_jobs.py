"""Real immutable revision-to-job compilation and bounded declarative contracts."""

from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.web_execution.static_browser_jobs import (
    BrowserAction,
    BrowserScenario,
    StaticBrowserError,
    StaticFile,
    content_hash,
    job_from_revision,
    validate_path,
)

from .static_browser_support import make_observation


@pytest.mark.parametrize(
    "path",
    [
        "../x.html",
        "/x.html",
        "C:/x.html",
        ".env",
        "x.js:secret",
        "x\\y.js",
        "node_modules/x.js",
        "code.py",
        "x//y.js",
        "a./x.js",
        " a.html",
    ],
)
def test_untrusted_paths_are_rejected(path):
    with pytest.raises(StaticBrowserError):
        validate_path(path)


def test_revision_compiler_preserves_exact_bytes_and_identity(tmp_path):
    _, _, job, _, revision, _ = make_observation(tmp_path)
    assert job.revision_content_hash == revision["content_hash"]
    assert job.source_tree_hash == revision["source_tree_hash"]
    assert len(job.files) == 3
    assert job.wire_bytes().startswith(b"{")


def test_owner_mismatch_is_rejected_before_reading_blobs(tmp_path):
    _, _, job, _, revision, _ = make_observation(tmp_path)

    def forbidden(_key):
        raise AssertionError("must not read blobs of another owner")

    with pytest.raises(StaticBrowserError, match="OWNER_SCOPE"):
        job_from_revision(
            revision,
            project_id=job.project_id,
            owner_user_id=uuid4(),
            read_content=forbidden,
            scenarios=job.scenarios,
            runner_manifest_content_hash=job.runner_manifest_content_hash,
            harness_sha256=job.harness_sha256,
        )


def test_corrupted_blob_never_enters_the_job(tmp_path):
    _, _, job, _, revision, _ = make_observation(tmp_path)
    with pytest.raises(StaticBrowserError, match="BLOB_MISMATCH"):
        job_from_revision(
            revision,
            project_id=job.project_id,
            owner_user_id=job.owner_user_id,
            read_content=lambda _key: b"wrong",
            scenarios=job.scenarios,
            runner_manifest_content_hash=job.runner_manifest_content_hash,
            harness_sha256=job.harness_sha256,
        )


def test_authorization_hash_changes_with_assertions_or_runner(tmp_path):
    _, _, job, _, _, _ = make_observation(tmp_path)
    changed = replace(job, runner_manifest_content_hash="9" * 64)
    assert changed.content_hash != job.content_hash
    scenario = BrowserScenario("other", "/", (BrowserAction("expect_text", "h1", "different"),))
    assert replace(job, scenarios=(scenario,)).content_hash != job.content_hash


def test_claimed_tree_hash_is_rejected(tmp_path):
    _, _, job, _, _, _ = make_observation(tmp_path)
    with pytest.raises(StaticBrowserError, match="TREE_HASH"):
        replace(job, source_tree_hash="0" * 64)


@pytest.mark.parametrize(
    "kind,selector,value",
    [
        ("evaluate", "body", "alert(1)"),
        ("click", "body", "x"),
        ("press", "body", "Control+L"),
        ("fill", "", "name"),
    ],
)
def test_actions_do_not_accept_arbitrary_code_or_keys(kind, selector, value):
    with pytest.raises(StaticBrowserError):
        BrowserAction(kind, selector, value)


def test_scenario_without_assertion_is_rejected():
    with pytest.raises(StaticBrowserError, match="ASSERTION_REQUIRED"):
        BrowserScenario("scenario", "/", (BrowserAction("click", "button"),))


def test_binary_or_overlarge_sources_are_rejected():
    with pytest.raises(StaticBrowserError):
        StaticFile("file.js", b"\xff")
    with pytest.raises(StaticBrowserError):
        StaticFile("file.js", b"x" * (1024 * 1024 + 1))


def test_source_metadata_hash_must_match(tmp_path):
    _, _, job, _, revision, blobs = make_observation(tmp_path)
    revision["version_number"] = 2
    with pytest.raises(StaticBrowserError, match="REVISION_HASH"):
        job_from_revision(
            revision,
            project_id=job.project_id,
            owner_user_id=job.owner_user_id,
            read_content=blobs.get,
            scenarios=job.scenarios,
            runner_manifest_content_hash=job.runner_manifest_content_hash,
            harness_sha256=job.harness_sha256,
        )


def test_content_addresses_cannot_select_arbitrary_paths(tmp_path):
    _, _, job, _, revision, blobs = make_observation(tmp_path)
    revision["files"][0]["storage_key"] = "../../.env"
    revision["content_hash"] = content_hash(
        {
            key: value
            for key, value in revision.items()
            if key not in {"content_hash", "source_tree_hash"}
        }
    )
    with pytest.raises(StaticBrowserError, match="ADDRESS_INVALID"):
        job_from_revision(
            revision,
            project_id=job.project_id,
            owner_user_id=job.owner_user_id,
            read_content=blobs.get,
            scenarios=job.scenarios,
            runner_manifest_content_hash=job.runner_manifest_content_hash,
            harness_sha256=job.harness_sha256,
        )
