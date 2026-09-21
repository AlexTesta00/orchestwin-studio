"""Real PostgreSQL campaign orchestration with explicitly synthetic transports.

This exercises approvals, immutable sources/attempts, repairs and restarts. Docker,
browser pixels and command outputs are test doubles: none of these records is
published as validation evidence or used to promote a profile.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from orchestwin.api import governed_web_context as context_module
from orchestwin.api.governed_web_context import (
    CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY,
    GovernedWebSettings,
    WebExecutionBackend,
)
from orchestwin.api.governed_web_execution_runtime import SqlAlchemyGovernedWebExecutionApiService
from orchestwin.api.web_repair_runtime import SqlAlchemyWebRepairApiService
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore
from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor
from orchestwin.web_execution.phase_browser_transport import WebBrowserTransportResult
from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.phase_runtime import ControlledWebNetwork
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_loader import build_web_profile_catalog_loader
from orchestwin.web_execution.static_browser_jobs import canonical_bytes
from orchestwin.web_execution.validation_campaign import (
    CampaignError,
    ValidationCampaign,
    create_campaign_plan,
    verify_campaign_plan,
)
from orchestwin.web_execution.validation_fixtures import load_repository_validation_fixtures
from orchestwin.web_execution.validation_governance import ValidationGovernance
from src.test.python.web_execution.test_phase_browser_evidence import envelope, events, report
from src.test.python.web_execution.test_phase_executor_contracts import FakeRuntime

pytestmark = pytest.mark.integration
REPOSITORY = Path(__file__).parents[4]


def test_campaign_three_approval_rounds_preserve_32_attempts_across_database_restarts(
    tmp_path, monkeypatch
):
    fixtures = load_repository_validation_fixtures(REPOSITORY)
    failures = {item.source_tree_hash(defective=True): item for item in fixtures}
    identities = tuple(
        WebPhaseRunnerIdentity(kind, "sha256:" + digit * 64, "a" * 64, digit * 64)
        for kind, digit in (("NODE", "b"), ("PHP", "c"), ("BROWSER", "d"))
    )
    by_kind = {identity.kind: identity for identity in identities}
    monkeypatch.setattr(
        context_module,
        "load_phase_runner_identity",
        lambda *args, kind, **kwargs: by_kind[kind],
    )
    executed, runtimes, guard_calls = [], [], []

    def phase_executor(**kwargs):
        fixture = failures.get(kwargs["contract"].source_tree_hash)
        test_commands = {
            command.command_id
            for plan in kwargs["contract"]
            .execution_plan.phase(WebExecutionPhase.TEST)
            .command_plans
            for command in plan.commands
        }

        class Runtime(FakeRuntime):
            def __init__(self, **arguments):
                super().__init__(**arguments)
                runtimes.append(self)

            async def run_command(self, command):
                observed = await super().run_command(command)
                if fixture is not None and command.command_id in test_commands:
                    return replace(observed, exit_code=1, stdout=b"LEVEL_D_NEGATIVE_CONTROL\n")
                return observed

        class Executor(GovernedWebPhaseExecutor):
            def bind_attempt(self, attempt_id):
                executed.append(attempt_id)
                super().bind_attempt(attempt_id)

        return Executor(**kwargs, runtime_factory=Runtime)

    class BrowserTransport:
        async def execute(self, job, **kwargs):
            observed = report(job)
            if job["request"]["source_tree_hash"] in failures:
                logged = events()
                logged["console_messages"] = [
                    {"level": "ERROR", "message": "LEVEL_D_NEGATIVE_CONTROL", "location": None}
                ]
                observed["screens"][0]["events"] = envelope(canonical_bytes(logged))
            process = BoundedHostProcessResult(
                stdout=canonical_bytes(observed),
                stderr=b"",
                failure_message=None,
                status="COMPLETED",
                exit_code=0,
            )
            return WebBrowserTransportResult(
                (("EXECUTE", process),), 0, True, None, "e" * 64, "f" * 64
            )

    monkeypatch.setattr(context_module, "GovernedWebPhaseExecutor", phase_executor)
    monkeypatch.setattr(
        context_module,
        "GovernedWebBrowserExecutor",
        lambda **kwargs: GovernedWebBrowserExecutor(**kwargs, transport=BrowserTransport()),
    )
    network = ControlledWebNetwork(
        "test-campaign",
        "e" * 64,
        CONTROLLED_GOVERNED_WEB_EXECUTION_POLICY.content_hash,
        "test-proxy",
        8080,
    )
    config = GovernedWebSettings(
        _env_file=None,
        enabled=True,
        repo_root=REPOSITORY,
        runner_manifest=tmp_path / "synthetic-manifest.json",
        workspaces_root=tmp_path / "workspaces",
        docker_context="test-transport",
        controlled_network=network,
    )
    owner = uuid4()
    plan = create_campaign_plan(
        owner_user_id=owner, commit="1" * 40, configuration_hash="2" * 64, fixtures=fixtures
    )
    verify_campaign_plan(plan, commit="1" * 40, configuration_hash="2" * 64, fixtures=fixtures)

    def compose(database):
        operations = SqlAlchemyWebOperationStore(database.session_factory)
        backend = WebExecutionBackend(
            config=config,
            content_root=tmp_path / "sources",
            evidence_root=tmp_path / "evidence",
            resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
        )
        execution = SqlAlchemyGovernedWebExecutionApiService(
            database.session_factory,
            operation_store=operations,
            backend=backend,
            catalog_loader=build_web_profile_catalog_loader(database.session_factory),
        )
        governance = ValidationGovernance(
            database.session_factory,
            operation_store=operations,
            execution_service=execution,
            repair_service=SqlAlchemyWebRepairApiService(
                database.session_factory,
                operation_store=operations,
                content_root=tmp_path / "sources",
            ),
            read_service=execution.reads,
            content_root=tmp_path / "sources",
        )
        return ValidationCampaign(
            plan=plan,
            fixtures=fixtures,
            governance=governance,
            runner_identities=identities,
            guard=lambda: guard_calls.append("checked-test-boundary"),
            policy_content_hash=backend.policy.content_hash,
        )

    def decisions(review):
        return [
            {
                "operation_id": operation["id"],
                "content_hash": operation["content_hash"],
                "event_sequence": operation["gate"]["event_sequence"],
            }
            for case in review["cases"]
            for operation in case["operations"]
            if operation["state"] == "PENDING"
        ]

    async def scenario():
        settings = load_database_settings(env_file=None)
        database = create_database_runtime(settings)
        try:
            async with database.session_factory.begin() as session:
                now = datetime.now(UTC)
                session.add(
                    UserRecord(
                        id=owner,
                        email_normalized=f"campaign-{owner.hex}@example.com",
                        password_hash="test-owner-not-used-for-authentication",
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            campaign = compose(database)
            prepared = await campaign.prepare()
            assert len(prepared["cases"]) == 24
            assert len(decisions(prepared)) == 24
            assert await campaign.prepare() == prepared
            assert executed == []
            original = decisions(prepared)[0]
            with pytest.raises(CampaignError, match="HASH_MISMATCH"):
                await campaign.approve([{**original, "content_hash": "0" * 64}])
            assert await campaign.review() == prepared
            await campaign.approve(decisions(prepared))
            await campaign.prepare()
            assert executed == []  # Repeated preparation never consumes approval.

            for round_number, expected_attempts, expected_pending in (
                (1, 24, 8),
                (2, 24, 8),
                (3, 32, 0),
            ):
                review = await campaign.advance()
                assert len(executed) == len(set(executed)) == expected_attempts
                assert len(decisions(review)) == expected_pending
                await database.dispose()
                database = create_database_runtime(settings)
                campaign = compose(database)
                assert await campaign.review() == review
                if round_number < 3:
                    await campaign.approve(decisions(review))

            assert await campaign.prepare() == review
            assert await campaign.advance() == review
            assert len(executed) == 32
            assert guard_calls
            assert all(runtime.close_count == 1 and not runtime.servers for runtime in runtimes)
            for case in review["cases"]:
                fixture = next(item for item in fixtures if item.fixture_id == case["fixture_id"])
                assert (
                    case["source_revisions"][-1]["source_tree_hash"] == fixture.source_tree_hash()
                )
                assert all(operation["state"] == "COMPLETED" for operation in case["operations"])
                executions = [item for item in case["operations"] if item["kind"] == "EXECUTION"]
                expected = ["FAILED", "PASSED"] if case["role"] == "failed" else ["PASSED"]
                receipts = [
                    await campaign.governance.harvest_attempt(
                        owner_user_id=owner,
                        project_id=UUID(case["project_id"]),
                        attempt_id=UUID(operation["id"]),
                    )
                    for operation in executions
                ]
                assert [receipt.attempt.report.status.value for receipt in receipts] == expected
                assert all(receipt.approval_event.kind.value == "APPROVE" for receipt in receipts)
                if case["role"] == "failed":
                    repair = next(item for item in case["operations"] if item["kind"] == "REPAIR")
                    await campaign.governance.harvest_repair(
                        owner_user_id=owner,
                        project_id=UUID(case["project_id"]),
                        operation_id=UUID(repair["id"]),
                    )
            async with database.engine.connect() as connection:
                for table, count in (
                    ("projects", 24),
                    ("web_source_revisions", 32),
                    ("web_execution_attempts", 32),
                    ("web_governed_operations", 40),
                    ("web_profile_validation_evidence", 0),
                ):
                    assert (
                        await connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == count
                    )
        finally:
            await database.dispose()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
