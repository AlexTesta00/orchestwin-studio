"""Offline operator input checks. No HTTP completion, GPU or Docker call."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from orchestwin.evaluation.artifact_content_control import (
    C63_MANIFEST_HASH,
    SOURCE_NAME,
    load_observed_axe,
    public_error,
)
from orchestwin.models.strict_evaluator_json import canonical_bytes

from .test_artifact_content_views import axe_payload


def observation(tmp_path, monkeypatch, *, source=None, digest=C63_MANIFEST_HASH):
    raw = canonical_bytes(axe_payload()) if source is None else source
    manifest = {
        "artifacts": [
            {"path": SOURCE_NAME, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        ]
    }
    body = canonical_bytes(manifest)
    (tmp_path / SOURCE_NAME).write_bytes(raw)
    result = SimpleNamespace(manifest_content_hash=digest, manifest_bytes=body)
    monkeypatch.setattr(
        "orchestwin.web_execution.verified_browser_runner.verify_browser_runner",
        lambda *_args: result,
    )
    return tmp_path / "manifest.json", raw, body


def test_control_reuses_existing_verified_axe_without_docker(tmp_path, monkeypatch):
    path, raw, body = observation(tmp_path, monkeypatch)
    assert load_observed_axe(path, tmp_path) == (raw, body)


def test_control_rechecks_bytes_after_parent_verification(tmp_path, monkeypatch):
    path, _, _ = observation(tmp_path, monkeypatch)
    (tmp_path / SOURCE_NAME).write_text("{}")
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        load_observed_axe(path, tmp_path)


def test_control_rejects_different_parent_observation(tmp_path, monkeypatch):
    path, _, _ = observation(tmp_path, monkeypatch, digest="a" * 64)
    with pytest.raises(ValueError, match="OBSERVATION_CHANGED"):
        load_observed_axe(path, tmp_path)


def test_control_rejects_missing_known_negative_observation(tmp_path, monkeypatch):
    data = axe_payload()
    data["violations"] = []
    path, _, _ = observation(tmp_path, monkeypatch, source=canonical_bytes(data))
    with pytest.raises(ValueError, match="NEGATIVE_FIXTURE_MISSING"):
        load_observed_axe(path, tmp_path)


@pytest.mark.parametrize(
    "message", ["bearer SECRET_TOKEN", "http://host?secret=x", "C:\\secret.txt", "a" * 101]
)
def test_public_errors_do_not_expose_arbitrary_exception_text(message):
    assert public_error(ValueError(message)) == "ValueError"


def test_public_errors_retain_stable_failure_codes():
    assert (
        public_error(ValueError("CONTENT_CONTROL_NO_FINDING_RETURNED"))
        == "CONTENT_CONTROL_NO_FINDING_RETURNED"
    )
    error = RuntimeError("private content")
    error.code = "INVALID_PAYLOAD"
    assert public_error(error) == "INVALID_PAYLOAD"
