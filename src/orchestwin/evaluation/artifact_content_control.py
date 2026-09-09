"""One opt-in content-to-evaluator check using a previously observed technical axe report.

This is not a benchmark task, owner judgment, persisted evaluation, or formal run.
The core content resolver is generic; only this explicit test uses the C63 fixture.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from orchestwin.evaluation.artifact_content import CONTENT_PROMPT_VERSION, prepare_artifact_content
from orchestwin.models.strict_evaluator_json import canonical_bytes, require, strict_json_object

C63_MANIFEST_HASH = "29ed22fbdab55a448d0c1c31dc9ff229da11d6f68b0eaf1fb5f17bb84645d8ab"
SOURCE_NAME = "negative-control.axe.json"


def load_observed_axe(manifest_path: Path, repo_root: Path) -> tuple[bytes, bytes]:
    from orchestwin.web_execution.verified_browser_runner import read_regular, verify_browser_runner

    observed = verify_browser_runner(manifest_path, repo_root)
    require(
        observed.manifest_content_hash == C63_MANIFEST_HASH, "CONTENT_CONTROL_OBSERVATION_CHANGED"
    )
    manifest = strict_json_object(observed.manifest_bytes)
    entries = [item for item in manifest["artifacts"] if item["path"] == SOURCE_NAME]
    require(len(entries) == 1, "CONTENT_CONTROL_SOURCE_MISSING")
    raw = read_regular(manifest_path.parent / SOURCE_NAME, 2 * 1024 * 1024)
    require(
        hashlib.sha256(raw).hexdigest() == entries[0]["sha256"]
        and len(raw) == entries[0]["size_bytes"],
        "CONTENT_CONTROL_SOURCE_CHANGED",
    )
    report = strict_json_object(raw)
    require(
        any(rule.get("id") == "button-name" for rule in report.get("violations", [])),
        "CONTENT_CONTROL_NEGATIVE_FIXTURE_MISSING",
    )
    return raw, observed.manifest_bytes


def build_content_request(raw: bytes):
    from orchestwin.evaluation.artifacts import (
        EvaluationArtifactKind,
        EvaluationArtifactReference,
        EvaluationScenario,
        create_evaluation_artifact_bundle,
    )
    from orchestwin.evaluation.evaluator import (
        EvaluationUserTwinProfile,
        UserTwinEvaluationRequest,
        canonical_profile_snapshot,
    )
    from orchestwin.twins.user_twins import UserTwinLifecycleStatus

    now = datetime.now(UTC)
    project_id, workflow_id = uuid4(), uuid4()
    digest = hashlib.sha256(raw).hexdigest()
    artifact_id = uuid5(NAMESPACE_URL, "orchestwin-technical-axe:" + digest)
    reference = EvaluationArtifactReference(
        artifact_id=artifact_id,
        version_number=1,
        kind=EvaluationArtifactKind.AXE_REPORT,
        media_type="application/json",
        sha256_digest=digest,
        size_bytes=len(raw),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location="technical-fixture:negative-control",
    )
    bundle = create_evaluation_artifact_bundle(
        project_id=project_id,
        workflow_run_id=workflow_id,
        scenario=EvaluationScenario(
            id=uuid4(),
            name="Technical artifact-content contract",
            task="Review supplied automated accessibility observations from the represented role.",
            locale="en",
            expected_outcomes=("Only content-supported, explicitly simulated feedback.",),
        ),
        artifacts=(reference,),
        created_at=now,
    )
    profile, profile_hash = canonical_profile_snapshot(
        {
            "name": "Technical keyboard-usage Proto-UT",
            "role": "Uses labelled controls to complete a small interface task",
            "basis": "Synthetic infrastructure test profile, not an observed person or owner approval",
        }
    )
    request = UserTwinEvaluationRequest(
        evaluation_run_id=uuid4(),
        project_id=project_id,
        workflow_run_id=workflow_id,
        artifact_bundle=bundle,
        twin=EvaluationUserTwinProfile(
            twin_id=uuid4(),
            version_number=1,
            name="Technical keyboard-usage Proto-UT",
            lifecycle_status=UserTwinLifecycleStatus.PROTO_UT,
            content_hash=profile_hash,
            snapshot_json=profile,
        ),
        evidence=(),
        requested_at=now,
    )

    def reader(key: str, maximum: int) -> bytes:
        require(
            key == reference.storage_key and len(raw) <= maximum, "CONTENT_CONTROL_READ_MISMATCH"
        )
        return raw

    return prepare_artifact_content(
        request,
        selected=((artifact_id, 1),),
        read_content=reader,
    )


def public_error(error: BaseException) -> str:
    code = getattr(error, "provider_failure_code", None) or getattr(error, "code", None)
    if code is not None:
        code = str(getattr(code, "value", code))
    elif isinstance(error, ValueError):
        code = str(error)
    else:
        code = type(error).__name__
    return (
        code
        if 0 < len(code) <= 100
        and code.isascii()
        and code.isupper()
        and all(letter.isalnum() or letter == "_" for letter in code)
        else type(error).__name__
    )


async def run_content_control(
    factory: Any,
    repo_root: Path,
    runner_manifest: Path,
    output: Path,
    *,
    platform_commit: str,
):
    from orchestwin.models.final_evaluator_gateway import FinalEvaluatorGenerationPort
    from orchestwin.models.final_evaluator_session import session_http

    output = output.absolute()
    repo_root = repo_root.absolute()
    require(
        not output.exists() and repo_root not in (output, *output.parents),
        "CONTENT_CONTROL_OUTPUT_MUST_BE_NEW_AND_EXTERNAL",
    )
    require(
        not any(part.is_symlink() or part.is_junction() for part in (output, *output.parents)),
        "CONTENT_CONTROL_OUTPUT_REDIRECTED",
    )
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "IN_PROGRESS",
        "report_type": "ARTIFACT_CONTENT_EVALUATOR_NOT_FORMAL_EVIDENCE",
        "started_at": datetime.now(UTC).isoformat(),
        "artifacts": [],
        "platform_commit": platform_commit,
        "configured_model_identity": factory.session.identity,
        "generation_http_attempts": 0,
        "new_generation_performed": False,
        "source_content_verified": False,
        "evaluator_domain_validation_passed": False,
        "automatic_retry_performed": False,
        "original_evidence_modified": False,
        "response_repaired": False,
        "response_is_replay": False,
        "prompt_version_ref": CONTENT_PROMPT_VERSION,
        "formal_run_started": False,
        "full_workflow_validated": False,
        "training_executed": False,
        "benchmark_reexecuted": False,
        "database_queries_performed": False,
        "docker_operations_performed": False,
        "public_evaluation_endpoint_added": False,
        "workflow_evaluator_routing_completed": False,
        "images_sent_to_model": False,
        "semantic_quality_independently_scored": False,
    }

    def store(name: str, body: bytes) -> None:
        with (output / name).open("xb") as stream:
            stream.write(body)
        report["artifacts"].append(
            {
                "path": name,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )

    def exchange(session, method, path, body, timeout):
        require(method == "POST" and path == "/v1/chat/completions", "CONTENT_CONTROL_HTTP_SCOPE")
        require(report["generation_http_attempts"] == 0, "CONTENT_CONTROL_RETRY_FORBIDDEN")
        report["generation_http_attempts"] += 1
        report["new_generation_performed"] = None  # Unknown until a response/health observation.
        # body has no Authorization header; the token is used only by session_http.
        store("http-request.private.json", body)
        response = session_http(session, method, path, body, timeout)
        report["http_status"] = response.status_code
        store("response.private.json", response.body)
        return response

    inner = FinalEvaluatorGenerationPort(factory.session, exchange=exchange)

    class RecordingPort:
        async def generate(self, request):
            store("generation-request.private.json", canonical_bytes(request.to_snapshot()))
            result = await inner.generate(request)
            store("adapter-result.private.json", canonical_bytes(result.to_snapshot()))
            return result

    before = None
    try:
        report["stage"] = "VERIFY_RECORDED_ARTIFACTS"
        raw, parent = load_observed_axe(runner_manifest, repo_root)
        store("source-manifest.json", parent)
        store("source-axe.private.json", raw)
        prepared = build_content_request(raw)
        store("content-context.private.json", canonical_bytes(prepared.content.to_snapshot()))
        store("evaluation-request.private.json", canonical_bytes(prepared.request.to_snapshot()))
        report["source_content_verified"] = True
        report["source_sha256"] = hashlib.sha256(raw).hexdigest()
        report["source_size_bytes"] = len(raw)
        report["source_observation_content_hash"] = C63_MANIFEST_HASH
        report["source_kind"] = "AXE_REPORT_TECHNICAL_NEGATIVE_CONTROL"
        report["content_view_sha256"] = prepared.content.to_snapshot()["items"][0]["view_sha256"]
        report["stage"] = "HEALTH_BEFORE"
        before = await factory.check_health()
        store("health-before.json", canonical_bytes(before))
        report["completed_generation_count_before"] = before["completed_generation_count"]
        evaluator = factory.create_evaluator(
            generation_port=RecordingPort(),
            verified_content=prepared.content,
        )
        report["stage"] = "ONE_LIVE_CONTENT_EVALUATION"
        print("[ONE_LIVE_CONTENT_EVALUATION] No retry, training, benchmark or Docker.", flush=True)
        response = await evaluator.evaluate(prepared.request)
        store("evaluation-response.private.json", canonical_bytes(response.to_snapshot()))
        report["evaluator_domain_validation_passed"] = True
        report["new_generation_performed"] = True
        report["findings_count"] = len(response.findings)
        report["evidence_gap_count"] = len(response.evidence_gaps)
        report["trace"] = evaluator.traces[0].to_snapshot()
        require(bool(response.findings), "CONTENT_CONTROL_NO_FINDING_RETURNED")
        require(
            any(finding.criterion.value == "accessibility" for finding in response.findings),
            "CONTENT_CONTROL_ACCESSIBILITY_FINDING_MISSING",
        )
        require(
            all(
                finding.requires_human_validation
                and finding.epistemic_status.value
                in {
                    "MODEL_INFERRED",
                    "UNSUPPORTED_ASSUMPTION",
                }
                for finding in response.findings
            ),
            "CONTENT_CONTROL_EPISTEMIC_STATUS_INVALID",
        )
        report["stage"] = "HEALTH_AFTER"
        after = await factory.check_health()
        store("health-after.json", canonical_bytes(after))
        report["completed_generation_count_after"] = after["completed_generation_count"]
        require(
            report["generation_http_attempts"] == 1
            and after["completed_generation_count"] == before["completed_generation_count"] + 1,
            "CONTENT_CONTROL_GENERATION_COUNT_MISMATCH",
        )
        report["artifact_citations_validated"] = True
        report["status"] = "FINAL_EVALUATOR_ARTIFACT_CONTENT_CONTROL_PASSED"
        report["stage"] = "COMPLETE"
    except (asyncio.CancelledError, KeyboardInterrupt):
        report["status"] = "INTERRUPTED"
        report["failure_code"] = "INTERRUPTED_INFERENCE_OUTCOME_MAY_BE_UNKNOWN"
        raise
    except Exception as error:
        # Local operator boundary: retain full raw response privately, emit only safe codes.
        report["status"] = "FAILED"
        report["failure_code"] = public_error(error)
        if before is not None:
            try:
                after = await factory.check_health()
                report["completed_generation_count_after"] = after["completed_generation_count"]
                if after["completed_generation_count"] > before["completed_generation_count"]:
                    report["new_generation_performed"] = True
                store("health-after-failure.json", canonical_bytes(after))
            except Exception as health_error:
                report["health_after_failure"] = public_error(health_error)
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["content_hash"] = hashlib.sha256(canonical_bytes(report)).hexdigest()
        with (output / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
