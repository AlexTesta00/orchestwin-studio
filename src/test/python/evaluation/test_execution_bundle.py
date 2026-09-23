import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.execution_bundle import (
    artifact_evidence_references,
    artifact_reference_id,
    execution_artifact_references,
    execution_bundle,
    execution_scenario,
)
from orchestwin.evaluation.validation import EvaluationEvidenceKind

EXECUTION = UUID("11111111-2222-4333-8444-555555555555")


def reference_snapshot(content: bytes, media_type: str):
    digest = hashlib.sha256(content).hexdigest()
    return {
        "storage_key": f"sha256/{digest[:2]}/{digest}",
        "sha256_digest": digest,
        "size_bytes": len(content),
        "media_type": media_type,
    }


def screen(route_id, viewport, *, axe=True):
    return {
        "route_id": route_id,
        "path": "/" + route_id,
        "viewport": viewport,
        "final_path": "/" + route_id,
        "artifacts": {
            "screenshot": reference_snapshot(b"\x89PNG" + route_id.encode(), "image/png"),
            "dom": reference_snapshot(f"<main>{route_id}</main>".encode(), "text/html"),
            "axe": reference_snapshot(b'{"violations": []}', "application/json") if axe else None,
            "events": reference_snapshot(b"[]", "application/json"),
        },
    }


def test_wide_screens_become_content_addressed_artifacts_with_stable_identities():
    screens = [
        screen("SCR-001", "narrow"),
        screen("SCR-001", "wide"),
        screen("SCR-002", "narrow"),
        screen("SCR-002", "wide", axe=False),
    ]
    references = execution_artifact_references(
        execution_id=EXECUTION, attempt_number=2, screens=screens
    )
    assert [reference.kind for reference in references] == [
        EvaluationArtifactKind.DOM_SNAPSHOT,
        EvaluationArtifactKind.AXE_REPORT,
        EvaluationArtifactKind.SCREENSHOT,
        EvaluationArtifactKind.DOM_SNAPSHOT,
        EvaluationArtifactKind.SCREENSHOT,
    ]
    assert {reference.version_number for reference in references} == {2}
    assert references[0].location == f"web-execution:{EXECUTION}:SCR-001:wide:dom"
    assert references[0].storage_key.startswith("sha256/")
    again = execution_artifact_references(execution_id=EXECUTION, attempt_number=2, screens=screens)
    assert [item.artifact_id for item in again] == [item.artifact_id for item in references]
    assert len({item.artifact_id for item in references}) == len(references)
    evidence = artifact_evidence_references(references)
    kinds = {item.reference_id: item.kind for item in evidence}
    assert kinds[artifact_reference_id(references[0])] is EvaluationEvidenceKind.PROJECT_ARTIFACT
    assert kinds[artifact_reference_id(references[1])] is EvaluationEvidenceKind.DETERMINISTIC_TEST
    assert [item.reference_id for item in evidence] == sorted(
        item.reference_id for item in evidence
    )


def test_bundles_without_evaluable_screens_are_rejected():
    with pytest.raises(ValueError):
        execution_artifact_references(
            execution_id=EXECUTION, attempt_number=1, screens=[screen("SCR-001", "narrow")]
        )
    with pytest.raises(ValueError):
        execution_artifact_references(
            execution_id=EXECUTION,
            attempt_number=1,
            screens=[screen(f"SCR-{index:03d}", "wide") for index in range(9)],
        )


def test_scenario_and_bundle_are_normalized_and_deterministic():
    scenario = execution_scenario(
        execution_id=EXECUTION,
        name="  Registro   ospiti ",
        task="La reception  registra gli ospiti.",
        expected_outcomes=("  ", "Ospite registrato in dieci secondi"),
    )
    assert scenario.name == "Registro ospiti"
    assert scenario.task == "La reception registra gli ospiti."
    assert scenario.expected_outcomes == ("Ospite registrato in dieci secondi",)
    fallback = execution_scenario(execution_id=EXECUTION, name="x", task="y", expected_outcomes=())
    assert fallback.expected_outcomes == ("The executed prototype supports the approved brief.",)
    project, workflow = uuid4(), uuid4()
    bundles = [
        execution_bundle(
            project_id=project,
            workflow_run_id=workflow,
            execution_id=EXECUTION,
            attempt_number=1,
            screens=[screen("SCR-001", "wide")],
            scenario=scenario,
            created_at=datetime(2026, 9, 23, 10, minute, tzinfo=UTC),
        )
        for minute in (0, 5)
    ]
    assert bundles[0].id == bundles[1].id
    assert bundles[0].content_hash == bundles[1].content_hash
    assert bundles[0].is_multimodal
    assert len(bundles[0].artifacts) == 3
