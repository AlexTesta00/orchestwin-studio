from uuid import UUID, uuid5

from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference

EXECUTION_BUNDLE_NAMESPACE = UUID("5c0b0b3e-2e1a-4c8f-9c8e-7a2f5d1e9b21")
PRIMARY_VIEWPORT = "wide"
MAX_BUNDLE_ROUTES = 8
SCENARIO_LOCALE = "it"
_SCREEN_ARTIFACTS = (
    ("dom", EvaluationArtifactKind.DOM_SNAPSHOT, EvaluationEvidenceKind.PROJECT_ARTIFACT),
    ("axe", EvaluationArtifactKind.AXE_REPORT, EvaluationEvidenceKind.DETERMINISTIC_TEST),
    ("screenshot", EvaluationArtifactKind.SCREENSHOT, EvaluationEvidenceKind.PROJECT_ARTIFACT),
)
_EVIDENCE_KINDS = {kind: evidence for _, kind, evidence in _SCREEN_ARTIFACTS}


def artifact_reference_id(reference):
    return f"artifact:{reference.artifact_id}:v{reference.version_number}"


def normalized_text(value, *, maximum):
    text = " ".join(str(value).split())
    return text[:maximum].rstrip() if len(text) > maximum else text


def execution_artifact_references(
    *, execution_id, attempt_number, screens, viewport=PRIMARY_VIEWPORT
):
    references = []
    routes = 0
    for screen in screens:
        if not isinstance(screen, dict) or screen.get("viewport") != viewport:
            continue
        routes += 1
        if routes > MAX_BUNDLE_ROUTES:
            raise ValueError("execution evidence exceeds the evaluation bundle route limit")
        route_id = str(screen["route_id"])
        artifacts = screen.get("artifacts") or {}
        for key, kind, _ in _SCREEN_ARTIFACTS:
            snapshot = artifacts.get(key)
            if not isinstance(snapshot, dict):
                continue
            references.append(
                EvaluationArtifactReference(
                    artifact_id=uuid5(
                        EXECUTION_BUNDLE_NAMESPACE, f"{execution_id}:{route_id}:{viewport}:{key}"
                    ),
                    version_number=attempt_number,
                    kind=kind,
                    media_type=str(snapshot["media_type"]),
                    sha256_digest=str(snapshot["sha256_digest"]),
                    size_bytes=int(snapshot["size_bytes"]),
                    storage_key=str(snapshot["storage_key"]),
                    location=f"web-execution:{execution_id}:{route_id}:{viewport}:{key}",
                )
            )
    if not references:
        raise ValueError("execution evidence contains no evaluable screens")
    return tuple(references)


def artifact_evidence_references(references):
    return tuple(
        sorted(
            (
                EvaluationEvidenceReference(
                    reference_id=artifact_reference_id(reference),
                    kind=_EVIDENCE_KINDS[reference.kind],
                    content_hash=reference.sha256_digest,
                    locator=reference.location,
                )
                for reference in references
            ),
            key=lambda item: item.sort_key,
        )
    )


def execution_scenario(*, execution_id, name, task, expected_outcomes, locale=SCENARIO_LOCALE):
    outcomes = tuple(
        normalized_text(item, maximum=1000) for item in expected_outcomes if str(item).strip()
    )
    return EvaluationScenario(
        id=uuid5(EXECUTION_BUNDLE_NAMESPACE, f"{execution_id}:scenario"),
        name=normalized_text(name, maximum=200),
        task=normalized_text(task, maximum=2000),
        locale=locale,
        expected_outcomes=outcomes or ("The executed prototype supports the approved brief.",),
    )


def execution_bundle(
    *, project_id, workflow_run_id, execution_id, attempt_number, screens, scenario, created_at
):
    return create_evaluation_artifact_bundle(
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        scenario=scenario,
        artifacts=execution_artifact_references(
            execution_id=execution_id, attempt_number=attempt_number, screens=screens
        ),
        created_at=created_at,
        bundle_id=uuid5(EXECUTION_BUNDLE_NAMESPACE, f"{execution_id}:bundle"),
    )
