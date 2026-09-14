"""Raw repair diagnostics preserve evidence identity and report excerpt limits."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from orchestwin.jvm_execution.evidence import JvmEvidenceReference
from orchestwin.models.repair_diagnostics import EXCERPT_BYTES, failure_log_context
from orchestwin.models.source_proposals import file_entry


def log(tmp_path, raw):
    entry = file_entry("stdout.log", raw, "text/plain")
    entry.pop("normalized_path")
    reference = JvmEvidenceReference(**entry)
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
