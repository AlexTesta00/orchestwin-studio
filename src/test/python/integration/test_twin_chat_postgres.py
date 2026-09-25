import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
import sqlalchemy as sa

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.persistence import create_database_runtime
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserTwinVersionRepository,
)
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.twins.test_user_modeling_persistence import persona_version, twin_version

__all__ = ["database"]

pytestmark = pytest.mark.integration

OUTPUT = {
    "reply": "Pochissimo tempo: lo faccio con l'ospite davanti a me.\n\nServe un solo campo.",
    "insights": [
        {
            "kind": "NEED",
            "text": "Registrazione in pochi secondi.",
            "confidence": 0.7,
            "grounded_on": ["user_twin.recurring_tasks", "user_twin.made_up"],
        }
    ],
}
BASE_URL = "http://synthetic/api/v1"


async def seeded_twin(db, owner, project):
    persona = replace(persona_version(), project_id=project, created_by_user_id=owner)
    twin = replace(twin_version(), project_id=project, created_by_user_id=owner)
    async with db.session_factory() as session, session.begin():
        personas = SqlAlchemyPersonaVersionRepository(session, owner_user_id=owner)
        assert (await personas.append(persona)).value == "APPENDED"
        twins = SqlAlchemyUserTwinVersionRepository(session, owner_user_id=owner)
        assert (await twins.append(twin)).value == "APPENDED"
    return twin


async def seed(database_runtime):
    owner, project = uuid4(), uuid4()
    async with database_runtime.session_factory() as session, session.begin():
        session.add(
            UserRecord(
                id=owner,
                email_normalized=f"{owner}@synthetic.invalid",
                password_hash="NO_LOGIN_SYNTHETIC",
            )
        )
        await session.flush()
        session.add(
            ProjectRecord(
                id=project,
                owner_user_id=owner,
                display_name="Synthetic twin chat",
                mode="GREENFIELD_GENERATION",
            )
        )
    return owner, project


def client_app(runtime, owner):
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=runtime,
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=owner)
    return app


def test_twin_chat_records_audited_turns_in_an_append_only_conversation(database, tmp_path):
    generator, transport = audited_generator(tmp_path, OUTPUT)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project = await seed(db)
            twin = await seeded_twin(db, owner, project)
            runtime = ApplicationRuntime(
                database_runtime=db,
                real_model_runtime=SimpleNamespace(
                    user_modeling=SimpleNamespace(
                        proposal_port=SimpleNamespace(generator=generator)
                    )
                ),
                proposal_evidence_store=SqlAlchemyProposalEvidenceStore(db.session_factory),
            )
            path = f"/projects/{project}/user-twins/{twin.twin_id}/conversation"
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client_app(runtime, owner)), base_url=BASE_URL
            ) as client:
                missing = await client.get(path)
                assert missing.status_code == 404
                assert missing.json()["detail"]["code"] == "TWIN_CONVERSATION_NOT_FOUND"
                first = await client.post(
                    f"{path}/turns",
                    json={"question": "  Come registri   un ospite? ", "expected_turn_count": 0},
                )
                assert first.status_code == 201, first.text
                assert first.json()["status"] == "TWIN_TURN_RECORDED"
                snapshot = first.json()["snapshot"]
                assert snapshot["twin_version_number"] == twin.version_number
                assert snapshot["twin_name"] == twin.profile.name
                turn = snapshot["turns"][0]
                assert turn["question"] == "Come registri un ospite?"
                assert turn["reply"] == OUTPUT["reply"]
                assert turn["epistemic_status"] == "HYPOTHESIS"
                assert turn["human_validation"] == "REQUIRED"
                assert turn["insights"][0]["grounded_on"] == ["user_twin.recurring_tasks"]
                stale = await client.post(
                    f"{path}/turns", json={"question": "E poi?", "expected_turn_count": 0}
                )
                assert stale.status_code == 409
                assert stale.json()["detail"]["code"] == "TWIN_CONVERSATION_CHANGED"
                second = await client.post(
                    f"{path}/turns", json={"question": "E poi?", "expected_turn_count": 1}
                )
                assert second.status_code == 201, second.text
                assert [item["ordinal"] for item in second.json()["snapshot"]["turns"]] == [1, 2]
                current = await client.get(path)
                assert current.status_code == 200
                assert len(current.json()["snapshot"]["turns"]) == 2
                unknown = await client.get(f"/projects/{project}/user-twins/{uuid4()}/conversation")
                assert unknown.status_code == 404
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=client_app(runtime, uuid4())),
                base_url=BASE_URL,
            ) as foreign:
                assert (await foreign.get(path)).status_code == 404
            assert len(transport.calls) == 2
            sent = json.loads(transport.calls[1]["payload"]["messages"][1]["content"])["context"]
            assert sent["conversation"] == [
                {"question": "Come registri un ospite?", "reply": OUTPUT["reply"]}
            ]
            assert sent["project_brief"] is None
            async with db.session_factory() as session:
                generations = (
                    (
                        await session.execute(
                            sa.text(
                                "SELECT id FROM model_proposal_generations "
                                "WHERE task_id = 'proposal-twin-chat-v1'"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(generations) == 2
                events = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id, kind, snapshot_json "
                            "FROM model_proposal_generation_events"
                        )
                    )
                ).all()
                payloads = {}
                for identifier, kind, raw in events:
                    payloads.setdefault(str(identifier), {})[kind] = json.loads(raw)["payload"]
                accepted = payloads[turn["model_generation_id"]]
                assert accepted["ADAPTER_ACCEPTED"]["generated_content_hashes"] == {
                    "TWIN_CHAT_TURN": [turn["content_hash"]]
                }
                assert accepted["APPLICATION_RESULT"]["status"] == "TWIN_TURN_RECORDED"
                stored = await session.scalar(
                    sa.text(
                        "SELECT model_generation_id FROM twin_conversation_turns WHERE ordinal = 1"
                    )
                )
                assert str(stored) == turn["model_generation_id"]
            with pytest.raises(sa.exc.DBAPIError, match="append-only"):
                async with db.session_factory() as editor, editor.begin():
                    await editor.execute(
                        sa.text("UPDATE twin_conversation_turns SET reply = 'edited'")
                    )
        finally:
            await db.dispose()

    run(scenario())
