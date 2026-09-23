import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa

from orchestwin.api.finalization_runtime import SqlAlchemyFinalizationApiService
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.web_execution_read_runtime import SqlAlchemyWebExecutionReadApiService
from orchestwin.evaluation.execution_bundle import (
    artifact_reference_id,
    execution_artifact_references,
)
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.persistence import create_database_runtime
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from src.test.python.integration.test_finalization_runtime_postgres import complete_project
from src.test.python.integration.test_model_source_generation_postgres import artifacts, client_app
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.twins.test_user_modeling_persistence import (
    BRIEF_REFERENCE,
    CATALOG_HASH,
    TEAM_REFERENCE,
    persona_version,
    twin_observations,
    twin_version,
)

__all__ = ["database"]

pytestmark = pytest.mark.integration

BASE_URL = "http://synthetic/api/v1"
DOM = (
    b"<html><body><h1>Tip</h1><form><label for='amount'>Importo</label>"
    b"<input id='amount' name='amount'></form></body></html>"
)
AXE = b'{"testEngine": {"name": "axe-core", "version": "4.10.0"}, "violations": [{"id": "label", "impact": "critical", "description": "Form elements must have labels", "help": "Add a label", "nodes": [{"target": ["#name"], "html": "<input id=\\"name\\">", "failureSummary": "Fix: add a label"}]}], "incomplete": [], "passes": [], "inapplicable": []}'
PNG = b"\x89PNG\r\n\x1a\n"


def stored(root, content, media_type):
    digest = hashlib.sha256(content).hexdigest()
    path = root / "sha256" / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "storage_key": f"sha256/{digest[:2]}/{digest}",
        "sha256_digest": digest,
        "size_bytes": len(content),
        "media_type": media_type,
    }


def screens_for(root):
    return [
        {
            "route_id": "SCR-001",
            "path": "/",
            "viewport": viewport,
            "final_path": "/",
            "artifacts": {
                "screenshot": stored(root, PNG, "image/png"),
                "dom": stored(root, DOM, "text/html"),
                "axe": stored(root, AXE, "application/json"),
                "events": None,
            },
        }
        for viewport in ("narrow", "wide")
    ]


TWIN_NAMES = ("Receptionist Twin", "Night Porter Twin")


def modeling_snapshot(owner, project):
    personas = []
    versions = []
    for name in TWIN_NAMES:
        persona = replace(
            persona_version(),
            id=uuid4(),
            persona_id=uuid4(),
            project_id=project,
            created_by_user_id=owner,
        )
        profile = replace(
            create_project_grounded_user_twin(
                name=name,
                persona_version=persona,
                project_brief_reference=BRIEF_REFERENCE,
                agent_team_reference=TEAM_REFERENCE,
                catalog_version=1,
                catalog_content_hash=CATALOG_HASH,
                observations=twin_observations(),
            ),
            validation_status=UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT,
        )
        personas.append(persona)
        versions.append(
            replace(
                twin_version(),
                id=uuid4(),
                twin_id=uuid4(),
                project_id=project,
                created_by_user_id=owner,
                profile=profile,
                content_hash=profile.content_hash,
            )
        )
    snapshot = create_user_modeling_snapshot(
        project_id=project,
        project_brief_reference=BRIEF_REFERENCE,
        agent_team_reference=TEAM_REFERENCE,
        catalog_version=1,
        catalog_content_hash=CATALOG_HASH,
        persona_versions=tuple(personas),
        twin_versions=tuple(versions),
    )
    return UserModelingSnapshotVersion(
        id=uuid4(),
        project_id=project,
        version_number=1,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=owner,
        created_at=datetime.now(UTC),
    )


def model_output(dom_reference):
    return {
        "summary": "Il calcolo è immediato, ma non vedo un messaggio di conferma dopo l'invio.",
        "findings": [
            {
                "artifact_id": str(dom_reference.artifact_id),
                "location": "SCR-001, campo importo",
                "summary": "Il campo importo non indica la valuta né il formato dei decimali.",
                "rationale": "Nel mio ruolo controllo molti conti in fretta e un formato ambiguo mi fa sbagliare.",
                "criterion": "comprehensibility",
                "severity": "moderate",
                "confidence": 0.7,
                "recommended_action": "Mostrare la valuta e un esempio di importo accanto al campo.",
                "evidence_refs": [artifact_reference_id(dom_reference)],
            }
        ],
        "evidence_gaps": ["Non vedo la schermata del risultato."],
        "abstained": False,
    }


def test_synthetic_evaluation_api_records_audited_findings_seen_by_the_final_review(
    database, tmp_path, monkeypatch
):
    versions = artifacts()

    async def scenario():
        db = create_database_runtime(database)
        try:
            content_root = tmp_path / "objects"
            owner, project = await complete_project(db, content_root, versions)
            sessions = db.session_factory
            evidence_root = tmp_path / "evidence"
            screens = screens_for(evidence_root)
            async with sessions() as session:
                attempt = await SqlAlchemyWebExecutionAttemptRepository(
                    session, owner_user_id=owner
                ).current(project_id=project)
            read = SqlAlchemyWebExecutionReadApiService(sessions, evidence_root=evidence_root)

            async def browser_evidence(*, owner_user_id, execution_id):
                if owner_user_id != owner or execution_id != attempt.id:
                    return None
                return {
                    "report_type": "GOVERNED_WEB_BROWSER_PHASE",
                    "browser_evidence": {"screens": screens},
                }

            monkeypatch.setattr(read, "browser_evidence", browser_evidence)
            snapshot = modeling_snapshot(owner, project)
            references = execution_artifact_references(
                execution_id=attempt.id, attempt_number=attempt.attempt_number, screens=screens
            )
            dom_reference = next(item for item in references if item.kind.value == "DOM_SNAPSHOT")
            (tmp_path / "model").mkdir()
            generator, transport = audited_generator(
                tmp_path / "model", model_output(dom_reference)
            )
            finalization = SqlAlchemyFinalizationApiService(
                sessions, content_root=content_root, export_root=tmp_path / "exports"
            )
            runtime = ApplicationRuntime(
                database_runtime=db,
                real_model_runtime=SimpleNamespace(
                    user_modeling=SimpleNamespace(
                        proposal_port=SimpleNamespace(generator=generator)
                    )
                ),
                proposal_evidence_store=SqlAlchemyProposalEvidenceStore(sessions),
                web_execution_read_api_service=read,
                user_modeling_services=SimpleNamespace(
                    commands=SimpleNamespace(snapshot_context_is_current=AsyncMock()),
                    revisions=SimpleNamespace(),
                    queries=SimpleNamespace(current_snapshot=AsyncMock(return_value=snapshot)),
                    gates=SimpleNamespace(current_gate=AsyncMock(return_value=None)),
                ),
                finalization_api_service=finalization,
                sandbox_evidence_root=evidence_root,
            )
            path = f"/projects/{project}/evaluation-runs"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, owner)), base_url=BASE_URL
            ) as client:
                assert (await client.get(path)).json() == {"items": []}
                missing = await client.post(path, json={"execution_id": str(uuid4())})
                assert missing.status_code == 404
                created = await client.post(path, json={"execution_id": str(attempt.id)})
                assert created.status_code == 201, created.text
                payload = created.json()
                assert payload["status"] == "SYNTHETIC_EVALUATION_RECORDED"
                run_snapshot = payload["snapshot"]
                assert run_snapshot["response_count"] == 2
                assert run_snapshot["finding_count"] == 2
                assert run_snapshot["simulated_feedback"] is True
                assert [item["finding_id"] for item in payload["findings"]] == [
                    "UTF-001",
                    "UTF-001",
                ]
                assert len({item["twin_id"] for item in payload["findings"]}) == 2
                for finding in payload["findings"]:
                    assert finding["origin"] == "MODEL_GENERATED"
                    assert finding["epistemic_status"] == "MODEL_INFERRED"
                    assert finding["requires_human_validation"] is True
                    assert finding["artifact_id"] == str(dom_reference.artifact_id)
                assert len(payload["aggregation"]["shared_findings"]) == 1
                assert payload["aggregation"]["evaluation_run_id"] == run_snapshot["id"]
                assert payload["aggregation"]["is_empirical_evidence"] is False
                listed = await client.get(path)
                assert [item["id"] for item in listed.json()["items"]] == [run_snapshot["id"]]
                detail = await client.get(f"/evaluation-runs/{run_snapshot['id']}")
                assert detail.status_code == 200
                assert detail.json()["snapshot"]["content_hash"] == run_snapshot["content_hash"]
                findings = await client.get(f"/evaluation-runs/{run_snapshot['id']}/findings")
                assert [item["finding_id"] for item in findings.json()["items"]] == [
                    "UTF-001",
                    "UTF-001",
                ]
                aggregation = await client.get(f"/evaluation-runs/{run_snapshot['id']}/aggregation")
                assert (
                    aggregation.json()["snapshot"]["evaluation_run_hash"]
                    == (run_snapshot["content_hash"])
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client_app(runtime, uuid4())),
                base_url=BASE_URL,
            ) as foreign:
                assert (await foreign.get(path)).json() == {"items": []}
                assert (
                    await foreign.get(f"/evaluation-runs/{run_snapshot['id']}")
                ).status_code == 404
            assert len(transport.calls) == 2
            contexts = [
                json.loads(call["payload"]["messages"][1]["content"])["context"]
                for call in transport.calls
            ]
            assert {sent["purpose"] for sent in contexts} == {"SYNTHETIC_EVALUATION"}
            assert {sent["scenario"]["name"] for sent in contexts} == {"Tip calculator"}
            assert {sent["user_twin"]["name"] for sent in contexts} == set(TWIN_NAMES)
            reviews = await finalization.final_reviews(owner_user_id=owner, project_id=project)
            check = next(
                item for item in reviews[-1]["checks"] if item["kind"] == "SYNTHETIC_EVALUATION"
            )
            assert check["status"] == "SATISFIED"
            assert check["evidence_refs"] == [f"evaluation-run:{run_snapshot['id']}"]
            async with sessions() as session:
                generations = (
                    (
                        await session.execute(
                            sa.text(
                                "SELECT id FROM model_proposal_generations "
                                "WHERE task_id = 'proposal-user-twin-evaluation-v1'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(generations) == 2
                outcomes = {}
                for generation in generations:
                    events = (
                        await session.execute(
                            sa.text(
                                "SELECT kind, snapshot_json FROM model_proposal_generation_events "
                                "WHERE generation_id = :generation"
                            ),
                            {"generation": generation},
                        )
                    ).all()
                    outcomes[generation] = {
                        kind: json.loads(raw)["payload"] for kind, raw in events
                    }
                statuses = sorted(
                    payloads["APPLICATION_RESULT"]["status"] for payloads in outcomes.values()
                )
                assert statuses == ["SYNTHETIC_EVALUATION_RECORDED", "TWIN_EVALUATED"]
                final = next(
                    payloads
                    for payloads in outcomes.values()
                    if payloads["APPLICATION_RESULT"]["status"] == "SYNTHETIC_EVALUATION_RECORDED"
                )
                assert final["ADAPTER_ACCEPTED"]["generated_content_hashes"] == {
                    "SYNTHETIC_EVALUATION": [run_snapshot["content_hash"]]
                }
                assert [
                    item["role"] for item in final["ADAPTER_ACCEPTED"]["related_generations"]
                ] == ["TWIN_EVALUATION"]
                stored_findings = await session.scalar(
                    sa.text("SELECT count(*) FROM synthetic_findings")
                )
                assert stored_findings == 2
        finally:
            await db.dispose()

    run(scenario())
