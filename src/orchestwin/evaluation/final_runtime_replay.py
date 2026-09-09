"""Offline replay of the recorded R2 control through the integrated evaluator factory.

This utility never imports old operators or executes code from evidence files.
Only hashes, recorded transport bytes and typed request snapshots are replayed.
No new inference or claim of a second experimental observation is made.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from orchestwin.models.final_evaluator_session import (
    SessionHttpResponse,
    bound_json,
    read_session_file,
)
from orchestwin.models.strict_evaluator_json import canonical_bytes, require, strict_json_object

OBSERVED_R2_HASH = "87d7c5ac0a9d64cb392a54c44f80828a2bcea3b05f22a399843b56a00c3511ae"


def load_r2_evidence(root: Path):
    manifest = bound_json(read_session_file(root / "manifest.json"))
    require(
        manifest["content_hash"] == OBSERVED_R2_HASH
        and manifest.get("status") == "FINAL_EVALUATOR_GENERATION_CONTRACT_PASSED"
        and manifest.get("prompt_candidate") == "FIELD_SCOPE_V2_OPERATOR_LOCAL"
        and manifest.get("formal_run_started") is False,
        "RECORDED_R2_SCOPE_MISMATCH",
    )
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, list) and len(artifacts) == 14, "RECORDED_R2_ARTIFACT_COUNT")
    contents = {}
    for entry in artifacts:
        import re

        name = entry.get("path", "")
        require(
            isinstance(name, str)
            and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}", name)
            and name not in contents,
            "RECORDED_R2_ARTIFACT_PATH",
        )
        body = read_session_file(root / name)
        require(
            type(entry.get("size_bytes")) is int
            and len(body) == entry["size_bytes"]
            and hashlib.sha256(body).hexdigest() == entry.get("sha256"),
            "RECORDED_R2_ARTIFACT_HASH",
        )
        contents[name] = body
    return manifest, contents


def restore_evaluation_request(modules: dict[str, Any], snapshot: dict[str, Any]):
    """Rebuild the same technical input with real repository types, verifying the round trip."""
    from orchestwin.twins.user_twins import UserTwinLifecycleStatus

    artifacts, evaluator = modules["artifacts"], modules["evaluator"]
    bundle_value, twin_value = snapshot["artifact_bundle"], snapshot["twin"]
    scenario_value = bundle_value["scenario"]
    bundle = artifacts.create_evaluation_artifact_bundle(
        project_id=UUID(bundle_value["project_id"]),
        workflow_run_id=UUID(bundle_value["workflow_run_id"]),
        scenario=artifacts.EvaluationScenario(
            id=UUID(scenario_value["id"]),
            name=scenario_value["name"],
            task=scenario_value["task"],
            locale=scenario_value["locale"],
            expected_outcomes=tuple(scenario_value["expected_outcomes"]),
        ),
        artifacts=tuple(
            artifacts.EvaluationArtifactReference(
                artifact_id=UUID(item["artifact_id"]),
                version_number=item["version_number"],
                kind=artifacts.EvaluationArtifactKind(item["kind"]),
                media_type=item["media_type"],
                sha256_digest=item["sha256_digest"],
                size_bytes=item["size_bytes"],
                storage_key=item["storage_key"],
                location=item["location"],
            )
            for item in bundle_value["artifacts"]
        ),
        created_at=datetime.fromisoformat(bundle_value["created_at"]),
        bundle_id=UUID(bundle_value["id"]),
    )
    require(snapshot["evidence"] == [], "PAIRED_CONTROL_MUST_HAVE_NO_EVIDENCE")
    require(
        twin_value["lifecycle_status"] == UserTwinLifecycleStatus.PROTO_UT.value,
        "PAIRED_CONTROL_MUST_BE_PROTO_UT",
    )
    twin = evaluator.EvaluationUserTwinProfile(
        twin_id=UUID(twin_value["twin_id"]),
        version_number=twin_value["version_number"],
        name=twin_value["name"],
        lifecycle_status=UserTwinLifecycleStatus.PROTO_UT,
        content_hash=twin_value["content_hash"],
        snapshot_json=twin_value["snapshot_json"],
    )
    result = evaluator.UserTwinEvaluationRequest(
        evaluation_run_id=UUID(snapshot["evaluation_run_id"]),
        project_id=UUID(snapshot["project_id"]),
        workflow_run_id=UUID(snapshot["workflow_run_id"]),
        artifact_bundle=bundle,
        twin=twin,
        evidence=(),
        requested_at=datetime.fromisoformat(snapshot["requested_at"]),
    )
    require(
        canonical_bytes(result.to_snapshot()) == canonical_bytes(snapshot), "PAIRED_INPUT_CHANGED"
    )
    return result


async def replay_r2(runtime, root: Path) -> dict[str, object]:
    from orchestwin.evaluation import artifacts, evaluator
    from orchestwin.models.final_evaluator_gateway import FinalEvaluatorGenerationPort

    manifest, files = load_r2_evidence(root)
    request = restore_evaluation_request(
        {"artifacts": artifacts, "evaluator": evaluator},
        strict_json_object(files["evaluation-request.json"]),
    )
    recorded_generation = strict_json_object(files["generation-request.json"])
    recorded_response = strict_json_object(files["evaluation-response.private.json"])
    captured = []

    def exchange(session, method, path, body, timeout):
        require(
            session.identity == manifest["model_identity"]
            and method == "POST"
            and path == "/v1/chat/completions"
            and timeout == recorded_generation["timeout_seconds"],
            "R2_REPLAY_TRANSPORT_CHANGED",
        )
        require(not captured, "R2_REPLAY_REQUEST_REPEATED")
        require(
            strict_json_object(body) == strict_json_object(files["http-request.json"]),
            "R2_REPLAY_HTTP_REQUEST_CHANGED",
        )
        captured.append(True)
        return SessionHttpResponse(
            200, files["response.private.json"], manifest["trace"]["latency_milliseconds"]
        )

    port = FinalEvaluatorGenerationPort(runtime.session, exchange=exchange)
    gateway = runtime.create_evaluator(
        generation_port=port,
        request_id_factory=lambda: UUID(recorded_generation["request_id"]),
        clock=lambda: datetime.fromisoformat(recorded_response["completed_at"]),
    )
    require(
        gateway.system_instruction == recorded_generation["system_instruction"]
        and gateway.output_schema.to_snapshot() == recorded_generation["output_schema"],
        "R2_REPLAY_PROMPT_OR_SCHEMA_CHANGED",
    )
    response = await gateway.evaluate(request)
    require(
        len(captured) == 1 and response.findings == () and len(response.evidence_gaps) == 1,
        "R2_REPLAY_RESULT_CHANGED",
    )
    actual = response.to_snapshot()
    # Factory identity differs from the operator-local evaluator ID. All semantic
    # input/output fields and model/prompt identity remain checked independently.
    for key in (
        "summary",
        "evidence_gaps",
        "findings",
        "artifact_bundle_hash",
        "twin_id",
        "twin_version",
    ):
        require(actual[key] == recorded_response[key], "R2_REPLAY_RESPONSE_CHANGED")
    require(
        gateway.traces[0].request_sha256 == manifest["trace"]["request_sha256"]
        and gateway.traces[0].result_sha256 == manifest["trace"]["result_sha256"],
        "R2_REPLAY_TRACE_CHANGED",
    )
    return {
        "status": "RECORDED_R2_REPLAY_PASSED",
        "recorded_manifest_content_hash": manifest["content_hash"],
        "verified_artifact_count": len(files),
        "transport": "RECORDED_RESPONSE_NOT_LIVE_MODEL",
        "request_hash_preserved": True,
        "prompt_schema_and_metadata_preserved": True,
        "evaluator_domain_validation_passed": True,
        "new_generation_performed": False,
        "original_evidence_modified": False,
    }
