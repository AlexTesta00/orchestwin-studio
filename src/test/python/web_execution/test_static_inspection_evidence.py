"""Reject corrupted, cross-job or fabricated terminal evidence during recovery."""

import asyncio

import pytest

from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.static_inspection_backend import verify_inspection_result
from orchestwin.web_execution.static_inspections import InspectionError
from orchestwin.web_execution.verified_browser_runner import read_json

from .static_inspection_support import approve, setup_service


@pytest.mark.parametrize(
    "changed",
    [
        "owner",
        "plan",
        "authorization",
        "profile_claim",
        "cleanup",
        "runtime_commit",
        "image",
        "job",
        "screenshot",
        "reported_assertion",
        "traversal",
        "duplicate",
        "hash",
    ],
)
def test_modified_evidence_is_not_imported(tmp_path, changed):
    service, _store, backend, args = setup_service(tmp_path)

    async def run():
        expected = await approve(service, backend, args)
        await service.execute(**args, expected_hash=expected)

    asyncio.run(run())
    inspection = _store.records[args["request_id"]]
    folder = backend.output / inspection.id.hex
    path = folder / "manifest.json"
    report = read_json(path.read_bytes())
    if changed == "owner":
        report["source"]["owner_user_id"] = str(inspection.id)
    elif changed == "plan":
        report["job_content_hash"] = "f" * 64
    elif changed == "authorization":
        report["authorization_kind"] = "PROFILE_VALIDATION"
    elif changed == "profile_claim":
        report["level_d_validated"] = True
    elif changed == "cleanup":
        report["cleanup_confirmed"] = False
    elif changed == "runtime_commit":
        report["platform_commit"] = "f" * 40
    elif changed == "image":
        report["runner_image_id"] = "sha256:" + "f" * 64
    elif changed in {"job", "screenshot"}:
        name = (
            "job.json"
            if changed == "job"
            else next(item["path"] for item in report["artifacts"] if item["path"].endswith(".png"))
        )
        target = folder / name
        target.write_bytes(target.read_bytes() + b"forged")
    elif changed == "reported_assertion":
        report["assertion_status"] = "FAILED"
    elif changed == "traversal":
        report["artifacts"][0]["path"] = "../elsewhere"
    elif changed == "duplicate":
        report["artifacts"].append(report["artifacts"][0])
    if changed != "hash":
        report["content_hash"] = content_hash(
            {k: v for k, v in report.items() if k != "content_hash"}
        )
    else:
        report["content_hash"] = "f" * 64
    path.write_bytes(canonical_bytes(report))
    with pytest.raises((InspectionError, ValueError)):
        verify_inspection_result(folder, inspection)


def test_valid_recovery_summary_does_not_contain_paths_or_source_code(tmp_path):
    service, _store, backend, args = setup_service(tmp_path)

    async def run():
        expected = await approve(service, backend, args)
        return await service.execute(**args, expected_hash=expected)

    result = asyncio.run(run())["result"]
    encoded = canonical_bytes(result)
    assert str(tmp_path).encode() not in encoded
    assert b"content_base64" not in encoded
    assert all(file.content not in encoded for file in backend.job.files if len(file.content) > 20)
    assert result["full_profile_execution"] is False
