import json
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
import sqlalchemy as sa

from orchestwin.api.services import ApplicationRuntime
from orchestwin.models.proposal_evidence_persistence import (
    GENERATIONS,
    SqlAlchemyProposalEvidenceStore,
)
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.persistence.models import BriefAssumptionRecord
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.integration.test_twin_chat_postgres import client_app, seed
from src.test.python.models.test_brief_dialogue import SYNTHESIS
from src.test.python.models.test_proposal_evidence import audited_generator

__all__ = ["database"]

pytestmark = pytest.mark.integration

BASE_URL = "http://synthetic/api/v1"
STATEMENT = "  Una lista ospiti per il workshop.\n\n\n Serve   ai volontari. "
ESSENTIAL = ["problem", "goals", "target_users", "functional_requirements"]


def question(field, text):
    return {"question": {"field": field, "text": text}}


def runtime_for(db, generator):
    return ApplicationRuntime(
        database_runtime=db,
        real_model_runtime=SimpleNamespace(team=SimpleNamespace(generator=generator)),
        proposal_evidence_store=SqlAlchemyProposalEvidenceStore(db.session_factory),
    )


def test_dialogue_asks_answers_and_synthesizes_the_brief_with_audited_generations(
    database, tmp_path
):
    generator, transport = audited_generator(tmp_path, question("problem", " Quale problema? "))

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            runtime = runtime_for(db, generator)
            path = f"/projects/{project}/brief-dialogue"
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client_app(runtime, owner)), base_url=BASE_URL
            ) as client:
                missing = await client.get(path)
                assert missing.status_code == 404
                assert missing.json()["detail"]["code"] == "BRIEF_DIALOGUE_NOT_FOUND"
                started = await client.post(path, json={"statement": STATEMENT})
                assert started.status_code == 201, started.text
                body = started.json()
                assert body["status"] == "BRIEF_DIALOGUE_STARTED"
                assert body["snapshot"]["statement"] == (
                    "Una lista ospiti per il workshop.\n\nServe ai volontari."
                )
                assert body["brief_version"]["version_number"] == 1
                assert body["brief_version"]["brief"]["description"] == (
                    "Una lista ospiti per il workshop. Serve ai volontari."
                )
                assert body["progress"]["open_essential_fields"] == ESSENTIAL[1:]
                first = body["snapshot"]["turns"][0]
                assert (first["ordinal"], first["field"], first["question"]) == (
                    1,
                    "problem",
                    "Quale problema?",
                )
                assert first["answer_type"] == "TEXT" and first["answer"] is None
                duplicate = await client.post(path, json={"statement": "Ancora"})
                assert duplicate.status_code == 409
                assert duplicate.json()["detail"]["code"] == "BRIEF_DIALOGUE_ACTIVE"
                sent = json.loads(transport.calls[0]["payload"]["messages"][1]["content"])
                assert sent["context"]["open_fields"] == ESSENTIAL
                assert (
                    '"enum": ["problem", "goals", "target_users", "functional_requirements"]'
                    in (json.dumps(sent["output_schema"]))
                )

                stale = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 0, "kind": "TEXT", "text": "Si perdono i nomi."},
                )
                assert stale.status_code == 409
                assert stale.json()["detail"]["code"] == "BRIEF_DIALOGUE_CHANGED"
                mismatched = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 1, "kind": "ITEM_LIST", "items": ["x"]},
                )
                assert mismatched.status_code == 422
                assert mismatched.json()["detail"]["code"] == "BRIEF_ANSWER_INVALID"

                transport.output = question("goals", "Quali obiettivi?")
                answered = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 1, "kind": "TEXT", "text": " Si perdono i nomi. "},
                )
                assert answered.status_code == 201, answered.text
                snapshot = answered.json()["snapshot"]
                assert answered.json()["status"] == "BRIEF_QUESTION_ASKED"
                assert snapshot["turns"][0]["answer"] == {
                    "kind": "TEXT",
                    "text": "Si perdono i nomi.",
                    "items": None,
                }
                assert snapshot["turns"][1]["field"] == "goals"
                assert snapshot["turns"][1]["answer_type"] == "ITEM_LIST"
                assert answered.json()["progress"]["open_essential_fields"] == [
                    "target_users",
                    "functional_requirements",
                ]
                sent = json.loads(transport.calls[1]["payload"]["messages"][1]["content"])
                assert sent["context"]["conversation"][0]["answer"]["text"] == "Si perdono i nomi."

                transport.status = 503
                interrupted = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 2, "kind": "ITEM_LIST", "items": ["Aggiungere"]},
                )
                assert interrupted.status_code == 503
                assert interrupted.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"
                transport.status = 200
                current = await client.get(path)
                assert current.json()["snapshot"]["turns"][1]["answer"]["items"] == ["Aggiungere"]
                assert current.json()["status"] == "BRIEF_DIALOGUE_CURRENT"
                repeated = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 2, "kind": "ITEM_LIST", "items": ["Altro"]},
                )
                assert repeated.status_code == 409

                transport.output = question("target_users", "Chi la usa?")
                resumed = await client.post(f"{path}/questions", json={"expected_turn_count": 2})
                assert resumed.status_code == 201, resumed.text
                assert resumed.json()["snapshot"]["turns"][2]["field"] == "target_users"
                transport.output = question("functional_requirements", "Cosa deve fare?")
                unknown = await client.post(
                    f"{path}/answers", json={"expected_turn_count": 3, "kind": "UNKNOWN"}
                )
                assert unknown.status_code == 201, unknown.text
                assert unknown.json()["snapshot"]["turns"][3]["field"] == "functional_requirements"
                transport.output = question(None, "I volontari usano un tablet condiviso?")
                follow_up = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 4, "kind": "ITEM_LIST", "items": ["Un nome"]},
                )
                assert follow_up.status_code == 201, follow_up.text
                body = follow_up.json()
                assert body["progress"]["open_essential_fields"] == []
                assert body["snapshot"]["turns"][4]["field"] is None
                assert body["snapshot"]["turns"][4]["answer_type"] == "TEXT"
                sent = json.loads(transport.calls[-1]["payload"]["messages"][1]["content"])
                assert sent["context"]["follow_up_allowed"] is True
                assert sent["context"]["stop_allowed"] is True
                assert "name" in sent["context"]["open_fields"]

                transport.output = question(None, "I volontari usano un tablet condiviso?")
                ready = await client.post(
                    f"{path}/answers",
                    json={"expected_turn_count": 5, "kind": "TEXT", "text": "Sì, uno solo."},
                )
                assert ready.status_code == 201, ready.text
                assert ready.json()["status"] == "BRIEF_DIALOGUE_READY"
                assert ready.json()["snapshot"]["status"] == "READY"
                assert ready.json()["snapshot"]["asked_fields"] == [
                    "functional_requirements",
                    "goals",
                    "problem",
                    "target_users",
                ]
                no_more = await client.post(f"{path}/questions", json={"expected_turn_count": 5})
                assert no_more.status_code == 409

                transport.output = SYNTHESIS
                synthesized = await client.post(
                    f"{path}/synthesis", json={"expected_turn_count": 5}
                )
                assert synthesized.status_code == 201, synthesized.text
                body = synthesized.json()
                assert body["status"] == "BRIEF_SYNTHESIZED"
                assert body["snapshot"]["status"] == "SYNTHESIZED"
                assert body["snapshot"]["resulting_brief_version_number"] == 2
                version = body["brief_version"]
                assert version["version_number"] == 2
                assert version["brief"]["name"] == "Lista ospiti"
                assert version["brief"]["description"] == (
                    "Una lista ospiti per il workshop. Serve ai volontari."
                )
                assert version["brief"]["target_users"] is None
                assert version["brief"]["missing_fields"] == []
                assert "target_users" in version["brief"]["unknown_fields"]
                assumptions = {item["field"]: item for item in body["assumptions"]}
                assert set(assumptions) == {
                    "target_users",
                    "domain",
                    "non_functional_requirements",
                    "definition_of_done",
                }
                assert assumptions["target_users"]["source"] == "MODEL_PROPOSED"
                assert assumptions["target_users"]["status"] == "PROPOSED"
                assert assumptions["target_users"]["brief_version_number"] == 2
                sent = json.loads(transport.calls[-1]["payload"]["messages"][1]["content"])
                assert sent["context"]["owner_unknown_fields"] == ["target_users"]
                assert len(sent["context"]["conversation"]) == 5
                again = await client.post(f"{path}/synthesis", json={"expected_turn_count": 5})
                assert again.status_code == 409

                transport.output = question(None, "Cosa cambia con la nuova idea?")
                restarted = await client.post(path, json={"statement": "Nuova idea."})
                assert restarted.status_code == 201, restarted.text
                assert restarted.json()["brief_version"]["version_number"] == 2
                assert restarted.json()["snapshot"]["source_brief_version_number"] == 2
                assert restarted.json()["snapshot"]["turns"][0]["field"] is None
                assert restarted.json()["progress"]["open_fields"] == []
                sent = json.loads(transport.calls[-1]["payload"]["messages"][1]["content"])
                assert sent["context"]["open_fields"] == []
                assert '"type": "null"' in json.dumps(sent["output_schema"])
                closed = await client.post(f"{path}/close", json={"expected_turn_count": 1})
                assert closed.status_code == 200, closed.text
                assert closed.json()["status"] == "BRIEF_DIALOGUE_CLOSED"
                assert (await client.get(path)).json()["snapshot"]["status"] == "CLOSED"
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client_app(runtime, uuid4())),
                base_url=BASE_URL,
            ) as foreign:
                assert (await foreign.get(path)).status_code == 404
            async with db.session_factory() as session:
                generations = await session.execute(
                    sa.select(GENERATIONS.c.task_id).where(GENERATIONS.c.project_id == project)
                )
                assert sorted(row[0] for row in generations) == ["proposal-brief-dialogue-v1"] * 9
                stored = await session.execute(
                    sa.select(BriefAssumptionRecord.field_name, BriefAssumptionRecord.source)
                    .where(BriefAssumptionRecord.project_id == project)
                    .order_by(BriefAssumptionRecord.field_name)
                )
                assert stored.all() == [
                    ("definition_of_done", "MODEL_PROPOSED"),
                    ("domain", "MODEL_PROPOSED"),
                    ("non_functional_requirements", "MODEL_PROPOSED"),
                    ("target_users", "MODEL_PROPOSED"),
                ]
        finally:
            await db.dispose()

    run(scenario())


def test_dialogue_requires_a_configured_model(database, tmp_path):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            runtime = ApplicationRuntime(
                database_runtime=db,
                proposal_evidence_store=SqlAlchemyProposalEvidenceStore(db.session_factory),
            )
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client_app(runtime, owner)), base_url=BASE_URL
            ) as client:
                response = await client.post(
                    f"/projects/{project}/brief-dialogue", json={"statement": "Idea."}
                )
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"
                assert (await client.get(f"/projects/{project}/brief-dialogue")).status_code == 404
        finally:
            await db.dispose()

    run(scenario())
