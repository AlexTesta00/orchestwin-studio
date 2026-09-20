"""Verify real bytes and lineage; never infer execution permission from a smoke result."""

import pytest

from orchestwin.web_execution.static_browser_jobs import (
    StaticBrowserError,
    canonical_bytes,
    content_hash,
)
from orchestwin.web_execution.verified_browser_runner import read_json, verify_browser_runner

from .static_browser_support import IMAGE_ID, make_observation


def test_valid_observation_preserves_local_image_identity(tmp_path):
    root, path, _, manifest, _, _ = make_observation(tmp_path)
    result = verify_browser_runner(path, root)
    assert result.image_id == IMAGE_ID
    assert result.manifest_content_hash == manifest["content_hash"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("cleanup_confirmed", False),
        ("browser_automation_verified", False),
        ("generated_projects_authorized", True),
        ("level_d_validated", True),
    ],
)
def test_invalid_claims_cannot_be_used_as_runner_evidence(tmp_path, field, value):
    root, path, _, manifest, _, _ = make_observation(tmp_path)
    manifest[field] = value
    manifest.pop("content_hash")
    manifest["content_hash"] = content_hash(manifest)
    path.write_bytes(canonical_bytes(manifest))
    with pytest.raises(StaticBrowserError, match="NOT_ELIGIBLE"):
        verify_browser_runner(path, root)


def test_changed_log_is_detected(tmp_path):
    root, path, _, _, _, _ = make_observation(tmp_path)
    (path.parent / "narrow.html").write_bytes(b"different")
    with pytest.raises(StaticBrowserError, match="ARTIFACT_MISMATCH"):
        verify_browser_runner(path, root)


def test_changed_recipe_is_detected_without_docker(tmp_path):
    root, path, _, _, _, _ = make_observation(tmp_path)
    (root / "infra/web-runners/browser-automation/probe.cjs").write_bytes(b"changed")
    with pytest.raises(StaticBrowserError, match="RECIPE_CHANGED"):
        verify_browser_runner(path, root)


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}'])
def test_ambiguous_json_is_rejected(body):
    with pytest.raises(StaticBrowserError):
        read_json(body)
