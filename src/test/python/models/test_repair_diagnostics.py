"""Raw repair diagnostics preserve evidence identity and report excerpt limits."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from orchestwin.models.repair_diagnostics import (
    EXCERPT_BYTES,
    browser_final_state,
    failure_log_context,
)
from orchestwin.models.source_proposals import file_entry
from orchestwin.web_execution.reports import WebEvidenceReference


def log(tmp_path, raw):
    entry = file_entry("stdout.log", raw, "text/plain")
    entry.pop("normalized_path")
    reference = WebEvidenceReference(**entry)
    path = tmp_path / reference.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return reference, path


def phase(reference):
    return SimpleNamespace(stdout_refs=(reference,), stderr_refs=())


def test_preserves_compiler_cause_and_explicit_utf8_excerpt_boundary(tmp_path):
    raw = b"[error] value scalameta is not a member of org\n"
    raw += b"x" * (EXCERPT_BYTES - len(raw) - 1) + "è".encode()
    reference, _ = log(tmp_path, raw)
    result = failure_log_context(phase(reference), tmp_path)
    excerpt = result["excerpts"][0]
    assert result["status"] == "VERIFIED_EXCERPTS"
    assert excerpt["text"].startswith("[error] value scalameta is not a member of org")
    assert excerpt["truncated"] is True
    assert excerpt["end_byte"] == EXCERPT_BYTES - 1
    assert excerpt["reference"] == reference.to_snapshot()
    assert excerpt["text"].encode() == raw[: excerpt["end_byte"]]


@pytest.mark.parametrize("failure", ["changed_bytes", "changed_size", "storage_key", "missing"])
def test_configured_logs_fail_closed_on_invalid_or_unavailable_evidence(tmp_path, failure):
    reference, path = log(tmp_path, b"exact compiler failure")
    if failure == "changed_bytes":
        path.write_bytes(b"other compiler failure")
    elif failure == "changed_size":
        reference = replace(reference, size_bytes=reference.size_bytes + 1)
    elif failure == "storage_key":
        reference = replace(reference, storage_key="other/location")
    else:
        path.unlink()
    with pytest.raises((ValueError, OSError)):
        failure_log_context(phase(reference), tmp_path)


def test_missing_store_is_explicit_and_never_claims_verified_logs(tmp_path):
    reference, _ = log(tmp_path, b"compiler failure")
    assert failure_log_context(phase(reference), None) == {
        "status": "STORE_NOT_CONFIGURED",
        "excerpts": [],
    }


def test_reference_budget_reports_omissions_without_inventing_content(tmp_path):
    reference, _ = log(tmp_path, b"same retained stream")
    result = failure_log_context(
        SimpleNamespace(stdout_refs=(reference, reference), stderr_refs=(reference,)), tmp_path
    )
    assert len(result["excerpts"]) == 2
    assert result["omitted_reference_count"] == 1
    assert all(not item["truncated"] for item in result["excerpts"])


def artifact(tmp_path, name, raw, media_type):
    entry = file_entry(name, raw, media_type)
    entry.pop("normalized_path")
    reference = WebEvidenceReference(**entry)
    path = tmp_path / reference.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return reference


def test_browser_final_state_reports_visible_and_hidden_screens(tmp_path):
    document = (
        b'<main><h1>App</h1><section id="SCR-001" data-design-screen="SCR-001" hidden=""></section>'
        b'<section id="SCR-002" data-design-screen="SCR-002"></section></main>'
    )
    dom = artifact(tmp_path, "root.html", document, "text/html")
    bundle = {
        "content_hash": "0" * 64,
        "normalized_findings": [],
        "request": {},
        "routes": [
            {
                "route": {"route_id": "root", "path": "/"},
                "final_path": "/",
                "dom_snapshot_ref": dom.to_snapshot(),
            }
        ],
        "status": "COLLECTED",
    }
    noise = artifact(tmp_path, "axe.json", b'{"violations": []}', "application/json")
    bundle_ref = artifact(tmp_path, "bundle.json", json.dumps(bundle).encode(), "application/json")
    phase = SimpleNamespace(artifact_refs=(noise, bundle_ref))
    assert browser_final_state(phase, tmp_path) == {
        "status": "VERIFIED",
        "routes": [
            {
                "route_id": "root",
                "final_path": "/",
                "visible_screens": ["SCR-002"],
                "hidden_screens": ["SCR-001"],
            }
        ],
    }
    assert browser_final_state(SimpleNamespace(artifact_refs=(noise,)), tmp_path) == {
        "status": "NOT_AVAILABLE",
        "routes": [],
    }
    assert browser_final_state(phase, None) == {"status": "STORE_NOT_CONFIGURED", "routes": []}


def test_browser_final_state_fails_closed_on_tampered_dom(tmp_path):
    dom = artifact(
        tmp_path, "root.html", b'<section data-design-screen="SCR-001"></section>', "text/html"
    )
    (tmp_path / dom.storage_key).write_bytes(b'<section data-design-screen="SCR-009"></section>')
    bundle = {
        "content_hash": "0" * 64,
        "normalized_findings": [],
        "request": {},
        "routes": [
            {
                "route": {"route_id": "root", "path": "/"},
                "final_path": "/",
                "dom_snapshot_ref": dom.to_snapshot(),
            }
        ],
        "status": "COLLECTED",
    }
    bundle_ref = artifact(tmp_path, "bundle.json", json.dumps(bundle).encode(), "application/json")
    with pytest.raises(ValueError, match="REPAIR_LOG_CONTENT_MISMATCH"):
        browser_final_state(SimpleNamespace(artifact_refs=(bundle_ref,)), tmp_path)


def test_tap_excerpt_starts_at_the_first_failing_record(tmp_path):
    passing = b"TAP version 13\n# Subtest: ok\nok 1 - ok\n  ---\n  type: 'test'\n  ...\n"
    failing = b"# Subtest: broken\nnot ok 2 - broken\n  ---\n  error: 'boom'\n  ...\n"
    raw = passing + failing + b"x" * EXCERPT_BYTES
    reference, _ = log(tmp_path, raw)
    excerpt = failure_log_context(phase(reference), tmp_path)["excerpts"][0]
    assert excerpt["start_byte"] == len(passing) + len(b"# Subtest: broken\n")
    assert excerpt["text"].startswith("not ok 2 - broken")
    assert excerpt["truncated"] is True
    assert excerpt["end_byte"] == excerpt["start_byte"] + EXCERPT_BYTES
    assert excerpt["text"].encode() == raw[excerpt["start_byte"] : excerpt["end_byte"]]


def test_tap_log_without_failures_keeps_the_leading_window(tmp_path):
    raw = b"TAP version 13\n# Subtest: ok\nok 1 - ok\n  ---\n  type: 'test'\n  ...\n"
    reference, _ = log(tmp_path, raw)
    excerpt = failure_log_context(phase(reference), tmp_path)["excerpts"][0]
    assert (excerpt["start_byte"], excerpt["truncated"]) == (0, False)
    assert excerpt["text"].encode() == raw
