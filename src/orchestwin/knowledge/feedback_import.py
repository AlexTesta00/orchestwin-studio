from __future__ import annotations

import json
import re
from dataclasses import fields, replace
from uuid import UUID, uuid5

from orchestwin.artifacts.design_evaluation import (
    anchor_finding,
    design_evaluation_run_from_snapshot,
)
from orchestwin.artifacts.design_finding_validations import create_finding_validation
from orchestwin.evaluation.artifacts import create_evaluation_artifact_bundle
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import SyntheticFinding, create_synthetic_finding
from orchestwin.projects.requirements_primitives import snapshot_content_hash

REVIEWS_DOCUMENT = "twins/feedback/reviews.json"


def import_feedback(folder, *, identities, hashes, project_id, owner_user_id):
    if REVIEWS_DOCUMENT not in folder.files and "why" not in folder.manifest:
        return (), (), ("LEGACY_FEEDBACK_CONTEXT_MISSING",)
    document = (
        json.loads(folder.files[REVIEWS_DOCUMENT]) if REVIEWS_DOCUMENT in folder.files else {}
    )
    incoming = document.get("runs", ())
    if not incoming:
        return (), (), ()
    design = folder.documents["design"]
    twins = {
        item["twin_id"]: item["version_number"]
        for item in folder.documents["twins"]["snapshot"]["twin_versions"]
    }
    supported = []
    omissions = []
    for item in incoming:
        missing = []
        if (
            item["design_version_id"] != design["id"]
            or item["design_version_number"] != design["version_number"]
            or item["design_content_hash"] != design["content_hash"]
        ):
            missing.append(
                f"design_reference={item['design_version_id']}/v{item['design_version_number']}/{item['design_content_hash']}"
            )
        missing.extend(
            f"twin_reference={response['twin_id']}/v{response['twin_version']}"
            for response in item["responses"]
            if twins.get(response["twin_id"]) != response["twin_version"]
        )
        if missing:
            if "why" in folder.manifest:
                from orchestwin.knowledge.archive import KnowledgeArchiveError

                raise KnowledgeArchiveError(
                    "FOLDER_FEEDBACK_CONTEXT_MISSING",
                    f"{REVIEWS_DOCUMENT}: run={item['id']}: {'; '.join(missing)}",
                )
            omissions.append(f"{REVIEWS_DOCUMENT}:{item['id']}:{'; '.join(missing)}")
        else:
            supported.append(item)
    uuids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", json.dumps(document)
    )
    for old in sorted(set(uuids)):
        identities.setdefault(old, str(uuid5(project_id, old)))
    for item in supported:
        identities[item["owner_user_id"]] = str(owner_user_id)
    known_artifacts = {item["id"]: item["version_number"] for item in folder.documents.values()}

    def identity(value):
        return UUID(identities.get(str(value), str(value)))

    def text(value):
        if isinstance(value, tuple):
            return tuple(sorted(text(item) for item in value))
        if not isinstance(value, str):
            return value
        for twin_id, twin_version in twins.items():
            value = re.sub(
                rf"(user-twin:{re.escape(twin_id)}:v){twin_version}(?=#user_twin\.[a-z_]+)",
                r"\g<1>1",
                value,
            )
        for old, new in identities.items():
            value = value.replace(old, new)
        for old, new in hashes.items():
            value = value.replace(old, new)
        return value

    runs = []
    for payload in supported:
        original = design_evaluation_run_from_snapshot(payload)
        old_bundle = original.bundle
        artifacts = tuple(
            replace(
                item,
                artifact_id=identity(item.artifact_id),
                version_number=1
                if known_artifacts.get(str(item.artifact_id)) == item.version_number
                else item.version_number,
                location=text(item.location),
            )
            for item in old_bundle.artifacts
        )
        bundle = create_evaluation_artifact_bundle(
            project_id=project_id,
            workflow_run_id=identity(old_bundle.workflow_run_id),
            scenario=replace(old_bundle.scenario, id=identity(old_bundle.scenario.id)),
            artifacts=artifacts,
            created_at=old_bundle.created_at,
            bundle_id=identity(old_bundle.id),
        )
        hashes[old_bundle.content_hash] = bundle.content_hash
        responses = []
        for response in original.responses:
            twin_version = (
                1
                if twins.get(str(response.twin_id)) == response.twin_version
                else response.twin_version
            )
            findings = []
            for finding in response.findings:
                values = {
                    item.name: getattr(finding, item.name)
                    for item in fields(SyntheticFinding)
                    if item.name != "content_hash"
                }
                values.update(
                    twin_id=identity(finding.twin_id),
                    twin_version=twin_version,
                    artifact_id=identity(finding.artifact_id),
                    artifact_version=1
                    if known_artifacts.get(str(finding.artifact_id)) == finding.artifact_version
                    else finding.artifact_version,
                )
                for key in (
                    "location",
                    "summary",
                    "rationale",
                    "recommended_action",
                    "evidence_refs",
                ):
                    values[key] = text(values[key])
                mapped = create_synthetic_finding(**values)
                if hasattr(finding, "anchor_key"):
                    mapped = anchor_finding(mapped, finding.anchor_key)
                hashes[finding.content_hash] = mapped.content_hash
                findings.append(mapped)
            values = dict(
                evaluation_run_id=identity(original.id),
                artifact_bundle_id=bundle.id,
                artifact_bundle_hash=bundle.content_hash,
                twin_id=identity(response.twin_id),
                twin_version=twin_version,
                evaluator=response.evaluator,
                findings=tuple(findings),
                summary=text(response.summary),
                evidence_gaps=text(response.evidence_gaps),
            )
            mapped = UserTwinEvaluationResponse(
                **values,
                completed_at=response.completed_at,
                content_hash=user_twin_evaluation_response_hash(**values),
            )
            hashes[response.content_hash] = mapped.content_hash
            responses.append(mapped)
        semantic = {
            **original.semantic_snapshot(),
            "id": str(identity(original.id)),
            "project_id": str(project_id),
            "owner_user_id": str(owner_user_id),
            "design_version_id": str(identity(original.design_version_id)),
            "design_version_number": 1,
            "design_content_hash": hashes.get(
                original.design_content_hash, original.design_content_hash
            ),
            "alternative_id": str(identity(original.alternative_id)),
            "bundle": bundle.to_snapshot(),
            "responses": [
                item.to_snapshot() for item in sorted(responses, key=lambda item: str(item.twin_id))
            ],
        }
        semantic["content_hash"] = snapshot_content_hash(semantic)
        mapped = design_evaluation_run_from_snapshot(semantic)
        hashes[original.content_hash] = mapped.content_hash
        runs.append(mapped)
    run_ids = {item.id for item in runs}
    decisions = []
    for item in document.get("decisions", ()):
        if identity(item["evaluation_run_id"]) not in run_ids:
            continue
        from datetime import datetime

        mapped = create_finding_validation(
            evaluation_run_id=identity(item["evaluation_run_id"]),
            twin_id=identity(item["twin_id"]),
            finding_id=item["finding_id"],
            sequence_number=item["sequence_number"],
            project_id=project_id,
            owner_user_id=owner_user_id,
            decision=item["decision"],
            note=text(item["note"]),
            decided_at=datetime.fromisoformat(item["decided_at"]),
        )
        hashes[item["content_hash"]] = mapped.content_hash
        decisions.append(mapped)
    return tuple(runs), tuple(decisions), ("LEGACY_FEEDBACK_CONTEXT_MISSING",) if omissions else ()
