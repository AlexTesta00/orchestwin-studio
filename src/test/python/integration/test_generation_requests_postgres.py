from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import httpx2
import pytest
import sqlalchemy as sa

from orchestwin.api import design_loop
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_requests import RESPOND_ASYNC
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_discussion_persistence import (
    SqlAlchemyDesignDiscussionRepository,
)
from orchestwin.config import ApplicationSettings
from orchestwin.models.proposal_evidence_persistence import (
    GENERATIONS,
    SqlAlchemyProposalEvidenceStore,
)
from orchestwin.persistence import create_database_runtime
from src.test.python.integration.test_postgresql_design_discussion import GroundedTwins
from src.test.python.integration.test_postgresql_design_loop import seed
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.models.test_proposal_evidence import audited_generator

__all__ = ["database"]

pytestmark = pytest.mark.integration

BASE_URL = "http://synthetic/api/v1"
ASYNC = {"Prefer": RESPOND_ASYNC}
SPOKEN = {
    "answer_to_owner": None,
    "argument": "The guided flow is clear, but I need the date format at the desk.",
    "confidence": 0.8,
    "grounded_on": ["user_twin.role"],
    "proposals": ["Show the date format next to the field."],
    "reactions": [],
    "stance": "CONCERN",
}
REVISED = {
    **SPOKEN,
    "answer_to_owner": "Concretely: add the date hint and I approve the flow.",
    "argument": "After the owner's note I accept the summary; only the date hint is missing.",
    "proposals": [],
}
CONFIRMED = {
    **SPOKEN,
    "answer_to_owner": "Yes, with the hint in place the desk can register guests quickly.",
    "argument": "With the date hint next to the field I register a guest without asking twice.",
    "proposals": [],
    "stance": "SUPPORT",
}
MODERATED = {
    "discussion_points": [
        {
            "positions": [{"position": "The flow is clear.", "twin": "T1"}],
            "subject": "The guided flow is clear.",
            "verdict": "AGREEMENT",
        }
    ],
    "proposals": [
        {
            "supported_by": ["T1"],
            "target": "DESIGN",
            "text": "Show the date format next to the field.",
        }
    ],
    "questions_for_owner": ["Should the desk accept other date formats?"],
}


def test_discussion_commands_run_as_jobs_record_the_same_evidence_as_synchronous_ones(
    database, tmp_path, monkeypatch
):
    generator, transport = audited_generator(tmp_path, SPOKEN)
    outputs = iter((SPOKEN, MODERATED, REVISED, MODERATED, CONFIRMED, MODERATED))
    deliver = transport.post_json

    async def scripted(**kwargs):
        transport.output = next(outputs)
        return await deliver(**kwargs)

    transport.post_json = scripted
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", GroundedTwins)

    async def scenario():
        db = create_database_runtime(database)
        try:
            owner, project, version = await seed(db)

            async def current(**_):
                return version

            application = create_app(
                ApplicationSettings(_env_file=None),
                runtime=ApplicationRuntime(
                    database_runtime=db,
                    real_model_runtime=SimpleNamespace(
                        user_modeling=SimpleNamespace(
                            proposal_port=SimpleNamespace(generator=generator)
                        )
                    ),
                    proposal_evidence_store=SqlAlchemyProposalEvidenceStore(db.session_factory),
                    design_query_service=SimpleNamespace(current=current),
                ),
                auth_settings=AuthApiSettings(_env_file=None),
            )
            application.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(
                id=owner
            )
            registry = application.state.generation_jobs
            discussions = f"/projects/{project}/design/discussions"
            jobs = f"/projects/{project}/generation-jobs"
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=application), base_url=BASE_URL
            ) as client:

                async def settled(started):
                    assert started.status_code == 202, started.text
                    job_id = started.json()["job_id"]
                    await registry.wait(UUID(job_id))
                    return (await client.get(f"{jobs}/{job_id}")).json()

                opened = await settled(
                    await client.post(
                        discussions,
                        json={
                            "design_version_id": str(version.id),
                            "design_content_hash": version.content_hash,
                            "locale": "en-US",
                        },
                        headers=ASYNC,
                    )
                )
                discussion_id = opened["response"]["body"]["id"]
                rounds = f"{discussions}/{discussion_id}/rounds"
                synchronous = await client.post(
                    rounds, json={"expected_round_count": 1, "owner_note": "Be concrete."}
                )
                continued = await settled(
                    await client.post(
                        rounds,
                        json={"expected_round_count": 2, "owner_note": "Does the hint suffice?"},
                        headers=ASYNC,
                    )
                )
                listed = (await client.get(jobs)).json()
            await registry.close()
            async with db.session_factory() as session:
                stored = await SqlAlchemyDesignDiscussionRepository(
                    session, owner_user_id=owner
                ).get(project_id=project, discussion_id=UUID(discussion_id))
                rows = (
                    await session.execute(sa.select(GENERATIONS.c.id, GENERATIONS.c.task_id))
                ).all()
                events = (
                    await session.execute(
                        sa.text(
                            "SELECT generation_id, kind, snapshot_json"
                            " FROM model_proposal_generation_events"
                        )
                    )
                ).all()
            return opened, synchronous, continued, listed, stored, rows, events
        finally:
            await db.dispose()

    opened, synchronous, continued, listed, stored, rows, events = run(scenario())
    assert (opened["operation"], opened["status"]) == ("DISCUSSION_START", "SUCCEEDED")
    assert (continued["operation"], continued["status"]) == ("DISCUSSION_ROUND", "SUCCEEDED")
    assert opened["response"]["status_code"] == continued["response"]["status_code"] == 201
    assert synchronous.status_code == 201
    first, second, third = stored.rounds
    assert opened["response"]["body"]["rounds"] == [first.to_snapshot()]
    assert synchronous.json()["rounds"] == [first.to_snapshot(), second.to_snapshot()]
    assert continued["response"]["body"] == stored.to_snapshot()
    assert third.statements[0].statement == CONFIRMED["argument"]
    assert [item["operation"] for item in listed["items"]] == [
        "DISCUSSION_START",
        "DISCUSSION_ROUND",
    ]
    assert len(transport.calls) == 6
    assert len(rows) == 6
    assert {row.task_id for row in rows} == {"proposal-twin-discussion-v1"}
    observed = {}
    for generation_id, kind, raw in events:
        observed.setdefault(str(generation_id), {})[kind] = json.loads(raw)["payload"]
    statuses = []
    for current_round in stored.rounds:
        statement_generation = str(current_round.statements[0].model_generation_id)
        synthesis_generation = str(current_round.synthesis.model_generation_id)
        assert set(observed[statement_generation]) == {
            "HTTP_REQUEST",
            "HTTP_RESPONSE",
            "PROVIDER_RESULT",
            "ADAPTER_ACCEPTED",
            "APPLICATION_RESULT",
        }
        assert observed[statement_generation]["APPLICATION_RESULT"] == {
            "status": "TWIN_STATEMENT_RECORDED",
            "discussion_id": str(stored.id),
        }
        accepted = observed[synthesis_generation]["ADAPTER_ACCEPTED"]
        assert accepted["generated_content_hashes"] == {
            "DISCUSSION_ROUND": [current_round.content_hash]
        }
        assert [
            (item["generation_id"], item["code"]) for item in accepted["related_generations"]
        ] == [(statement_generation, "TWIN_STATEMENT_RECORDED")]
        statuses.append(observed[synthesis_generation]["APPLICATION_RESULT"]["status"])
    assert statuses == [
        "DESIGN_DISCUSSION_STARTED",
        "DESIGN_DISCUSSION_ROUND_RECORDED",
        "DESIGN_DISCUSSION_ROUND_RECORDED",
    ]
