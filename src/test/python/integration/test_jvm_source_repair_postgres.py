"""Governed JVM repairs against actual PostgreSQL transactions and source objects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.jvm_execution.phase_executor import GovernedJvmPhaseExecutor
from src.test.python.integration.test_jvm_execution_api_postgres import (
    DATABASE,
    api_fixture,
    approve,
    prepared,
    run,
)
from src.test.python.jvm_execution.api_support import TARGETS
from src.test.python.jvm_execution.test_phase_executor import Runtime

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE, reason="explicit disposable PostgreSQL URL required"),
]


@pytest.mark.parametrize("target", TARGETS)
def test_repair_requires_exact_gate_creates_revision_and_fresh_cache_rerun(
    tmp_path, monkeypatch, target
):
    async def scenario():
        async with api_fixture(tmp_path, monkeypatch, target=target, mode="failed-test") as f:
            operation = await prepared(f)
            body = await approve(f, operation)
            response = await f.client.post(f.path, json=body)
            assert response.status_code == 201, response.text
            attempt = response.json()["snapshot"]
            path = next(
                item for item in f.revision.files if item.normalized_path.startswith("src/main/")
            )
            original = (f.backend.content_root / path.storage_key).read_text()
            url = f"/jvm-executions/{attempt['id']}/repair-proposals"
            response = await f.client.post(
                url,
                json={
                    "base_revision_content_hash": f.revision.content_hash,
                    "failure_signature": attempt["report"]["failure_signatures"][0]["signature"],
                    "rationale": "Bounded repair test",
                    "changes": [
                        {
                            "operation": "REPLACE",
                            "normalized_path": path.normalized_path,
                            "content": original + "\n// reviewed repair\n",
                            "media_type": "text/plain",
                        }
                    ],
                },
            )
            assert response.status_code == 201, response.text
            repair = response.json()["snapshot"]
            assert repair["payload"]["proposal"]["change_set"]["provenance_references"] == [
                f"jvm-execution:{attempt['id']}:{attempt['content_hash']}"
            ]
            apply_body = {
                "base_revision_content_hash": f.revision.content_hash,
                "proposal_content_hash": repair["content_hash"],
            }
            assert (
                await f.client.post(url + f"/{repair['id']}/apply", json=apply_body)
            ).status_code == 409
            assert len(f.instances) == 1
            await approve(f, repair)
            assert (
                await f.client.post(
                    url + f"/{repair['id']}/apply", json={**apply_body, "approval_id": str(uuid4())}
                )
            ).status_code == 409
            apply_body["approval_id"] = repair["gate"]["id"]
            # An append conflict must roll back the RUNNING claim as well as the revision.
            with monkeypatch.context() as patch:
                patch.setattr(
                    SqlAlchemyJvmSourceRevisionRepository,
                    "append",
                    AsyncMock(
                        return_value=SimpleNamespace(
                            status=SimpleNamespace(value="CONFLICT"), revision=None
                        )
                    ),
                )
                rejected = await f.client.post(url + f"/{repair['id']}/apply", json=apply_body)
                assert rejected.status_code == 409
            pending = (
                await f.client.get(f"/projects/{f.project}/jvm-operations/{repair['id']}")
            ).json()["snapshot"]
            assert pending["state"] == "PENDING" and pending["result"] is None
            response = await f.client.post(url + f"/{repair['id']}/apply", json=apply_body)
            assert response.status_code == 200, response.text
            result = response.json()["snapshot"]
            assert not result["execution_performed"] and len(result["required_rerun_phases"]) == 7
            assert result["source_revision"]["version_number"] == 2
            assert len(f.instances) == 1
            # A stale repair cannot create a third revision.
            assert (
                await f.client.post(url + f"/{repair['id']}/apply", json=apply_body)
            ).status_code == 409
            assert (
                len(
                    (await f.client.get(f"/projects/{f.project}/jvm-source-revisions")).json()[
                        "items"
                    ]
                )
                == 2
            )

            def passing_transport(**kwargs):
                runtime = Runtime(**kwargs)
                f.instances.append(runtime)
                return runtime

            f.backend.executor_factory = lambda **kwargs: GovernedJvmPhaseExecutor(
                **kwargs, runtime_factory=passing_transport
            )
            rerun_body = {
                **f.body,
                "source_revision_id": result["source_revision"]["id"],
                "trigger": "REPAIR_RERUN",
                "rerun_phases": result["required_rerun_phases"],
            }
            response = await f.client.post(f.path + "/prepare", json=rerun_body)
            assert response.status_code == 201, response.text
            rerun_operation = response.json()["snapshot"]
            await approve(f, rerun_operation)
            response = await f.client.post(
                f.path, json={**rerun_body, "authorization_id": rerun_operation["id"]}
            )
            assert response.status_code == 201, response.text
            rerun = response.json()["snapshot"]
            assert rerun["report"]["status"] == "PASSED"
            assert rerun["previous_attempt_id"] == attempt["id"]
            assert rerun["source_revision"]["revision_id"] == result["source_revision"]["id"]
            assert len(rerun["executed_phases"]) == 7 and len(f.instances) == 2

    run(scenario())
