"""Opt-in real PostgreSQL/Docker Web API journey using a DEVELOPMENT fixture.

Run only against a fresh dedicated PostgreSQL database migrated through the
current head. Settings come from process environment (never the application
.env). This test appends UUID-scoped owners/projects and never truncates tables.
The fixture and observed artifacts do not promote profiles or constitute a
formal calculator run. Every backend execution delegates to real Web phases.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

MANIFEST = os.environ.get("ORCHESTWIN_WEB_PHASE_TEST_BOOTSTRAP_MANIFEST")
DATABASE = os.environ.get("ORCHESTWIN_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not MANIFEST or not DATABASE,
        reason="explicit real Web runner manifest and isolated PostgreSQL environment are required",
    ),
]


def development_files():
    return {
        "index.html": (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>Unit7 development fixture</title>"
            "<style>body{font:18px sans-serif;color:#111;background:#fff;margin:24px}</style>"
            "</head><body><main><h1>Unit7 development fixture</h1>"
            "<p>This deterministic fixture exercises an approved repair.</p>"
            '</main><script src="/app.js"></script></body></html>'
        ),
        "app.js": "console.error('UNIT7_DEVELOPMENT_FAILURE');\n",
    }


async def owners_and_project(database):
    from pydantic import SecretStr

    from orchestwin.identity.application import (
        AuthenticationStatus,
        LocalIdentityApplicationService,
    )
    from orchestwin.identity.passwords import Argon2PasswordService
    from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
    from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
    from orchestwin.projects.application import LocalProjectApplicationService
    from orchestwin.projects.domain import ProjectMode
    from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory

    identity = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(database.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr("unit7-development-integration-secret-over-32-characters"),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )
    users = []
    for label in ("owner", "foreign"):
        result = await identity.register(
            email=f"unit7-{label}-{uuid4().hex}@example.com",
            password="development integration correct horse battery staple",
        )
        assert result.status is AuthenticationStatus.AUTHENTICATED
        users.append(result.authenticated.user)
    project = await LocalProjectApplicationService(
        unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(database.session_factory)
    ).create(
        owner_user_id=users[0].id,
        display_name="Unit7 DEVELOPMENT Web execution and repair",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )
    return users[0], users[1], project


async def seed_development_source(database, *, owner, project, root):
    from orchestwin.artifacts.web_source_persistence import (
        SqlAlchemyWebSourceRevisionUnitOfWork,
        WebSourceRevisionAppendStatus,
    )
    from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
    from orchestwin.artifacts.web_sources import (
        WebSourceOrigin,
        WebSourceProvenanceKind,
        WebSourceProvenanceReference,
        create_web_source_revision,
    )
    from orchestwin.sandbox.execution_profiles import ExecutionTarget
    from orchestwin.web_execution.targets import (
        WebImplementationLanguage,
        WebLanguageConfiguration,
        WebProjectLayout,
    )

    files = development_files()
    store = FileSystemWebSourceContentStore(root)
    entries = tuple(
        store.store(
            normalized_path=path,
            content=text.encode("utf-8"),
            media_type="text/html" if path.endswith(".html") else "text/javascript",
        )
        for path, text in sorted(files.items())
    )
    revision = create_web_source_revision(
        revision_id=uuid4(),
        project_id=project.id,
        created_by_user_id=owner.id,
        version_number=1,
        based_on=None,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=entries,
        provenance_references=(
            WebSourceProvenanceReference(
                WebSourceProvenanceKind.SOURCE_PLAN,
                "unit7.development.fixture",
                1,
                hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
            ),
        ),
        created_at=datetime.now(UTC),
    )
    async with SqlAlchemyWebSourceRevisionUnitOfWork(
        database.session_factory, owner_user_id=owner.id
    ) as unit:
        assert (
            await unit.revisions.append(revision)
        ).status is WebSourceRevisionAppendStatus.APPENDED
        await unit.commit()
    return revision


async def approve(store, *, owner, project, snapshot):
    from orchestwin.workflow.gates import HumanGateAction, HumanGateStatus, HumanGateType

    async with store.scope(owner_user_id=owner.id, project_id=project.id) as scope:
        operation = await scope.get(UUID(snapshot["id"]))
        assert operation is not None and operation.content_hash == snapshot["content_hash"]
        gate = await scope.gate(operation)
        assert gate.gate_type is HumanGateType.HIGH_IMPACT_OPERATION
        assert gate.artifact.content_hash == operation.content_hash
        await scope.decide(
            operation,
            expected_hash=operation.content_hash,
            expected_event_sequence=gate.event_sequence,
            action=HumanGateAction.APPROVE,
        )
        assert (await scope.gate(operation)).status is HumanGateStatus.APPROVED
        return gate.id


def test_real_api_claim_failure_approved_repair_and_rerun_survive_restart(tmp_path):
    async def scenario():
        import sqlalchemy as sa

        from orchestwin.api.governed_web_context import GovernedWebSettings, WebExecutionBackend
        from orchestwin.api.governed_web_execution_runtime import (
            SqlAlchemyGovernedWebExecutionApiService,
        )
        from orchestwin.api.web_execution import (
            WebApiCommandStatus,
            WebExecutionStartCommand,
            WebRepairChangeCommand,
            WebRepairProposalApplyCommand,
            WebRepairProposalCreateCommand,
        )
        from orchestwin.api.web_execution_read_runtime import SqlAlchemyWebExecutionReadApiService
        from orchestwin.api.web_repair_runtime import SqlAlchemyWebRepairApiService
        from orchestwin.api.web_source_runtime import SqlAlchemyWebSourceApiService
        from orchestwin.artifacts.web_change_sets import WebSourceChangeOperation
        from orchestwin.persistence import create_database_runtime, load_database_settings
        from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
        from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
        from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
        from orchestwin.web_execution.operation_persistence import (
            WEB_GOVERNED_OPERATIONS,
            SqlAlchemyWebOperationStore,
        )
        from orchestwin.web_execution.phase_runner import load_phase_runner_identity
        from orchestwin.web_execution.plans import WebExecutionPhase
        from orchestwin.web_execution.profile_loader import build_web_profile_catalog_loader
        from orchestwin.workflow.web_execution import WebExecutionPurpose

        # A single connection also detects nested-session starvation in prepare,
        # replay and finalization; the adapter must release or reuse its session.
        settings = load_database_settings(env_file=None).model_copy(
            update={"pool_size": 1, "max_overflow": 0, "pool_timeout_seconds": 2.0}
        )
        database = create_database_runtime(settings)
        try:
            owner, foreign, project = await owners_and_project(database)
            content_root, evidence_root, workspaces_root = (
                tmp_path / "source-objects",
                tmp_path / "evidence",
                tmp_path / "workspaces",
            )
            revision = await seed_development_source(
                database, owner=owner, project=project, root=content_root
            )
            original_bytes = {
                entry.storage_key: (content_root / entry.storage_key).read_bytes()
                for entry in revision.files
            }
            manifest_path, repo = Path(MANIFEST), Path(__file__).parents[4]
            bootstrap = json.loads(manifest_path.read_bytes())
            node = load_phase_runner_identity(manifest_path, repo_root=repo, kind="NODE")
            browser = load_phase_runner_identity(manifest_path, repo_root=repo, kind="BROWSER")
            config = GovernedWebSettings(
                enabled=True,
                repo_root=repo,
                runner_manifest=manifest_path,
                workspaces_root=workspaces_root,
                docker_context=bootstrap["environment"]["docker_context"],
                _env_file=None,
            )

            class ObservedRealBackend(WebExecutionBackend):
                """A concurrency barrier observes a durable claim before real execution."""

                def __init__(self, **kwargs):
                    super().__init__(**kwargs)
                    self.executions = 0
                    self.claimed = asyncio.Event()
                    self.release_first = asyncio.Event()
                    self.observed_claim_ids = []

                async def execute(self, context, *, operation, authorization, attempts):
                    self.executions += 1
                    async with database.session_factory() as session:
                        state = await session.scalar(
                            sa.select(WEB_GOVERNED_OPERATIONS.c.state).where(
                                WEB_GOVERNED_OPERATIONS.c.id == operation.id
                            )
                        )
                        assert state == "RUNNING", "claim must commit before any Docker execution"
                    self.observed_claim_ids.append(str(operation.id))
                    self.claimed.set()
                    if self.executions == 1:
                        await self.release_first.wait()
                    return await super().execute(
                        context, operation=operation, authorization=authorization, attempts=attempts
                    )

            backend = ObservedRealBackend(
                config=config,
                content_root=content_root,
                evidence_root=evidence_root,
                resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
            )

            def services():
                operations = SqlAlchemyWebOperationStore(database.session_factory)
                loader = build_web_profile_catalog_loader(database.session_factory)
                executor = SqlAlchemyGovernedWebExecutionApiService(
                    database.session_factory,
                    operation_store=operations,
                    backend=backend,
                    catalog_loader=loader,
                )
                reader = SqlAlchemyWebExecutionReadApiService(
                    database.session_factory, evidence_root=evidence_root
                )
                return operations, loader, executor, reader

            operations, loader, executor, reader = services()
            loaded = await loader.load()
            assert loaded.catalog.records == (), (
                "use a new dedicated database without synthetic promotion rows"
            )
            assert all(
                profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
                for profile in loaded.registry.profiles
            )
            command = WebExecutionStartCommand(
                source_revision_id=revision.id,
                profile_id="web.static",
                profile_version="1.0.0",
                policy_content_hash=backend.policy.content_hash,
                execution_runner_image_digest=node.image_id.removeprefix("sha256:"),
                browser_runner_image_digest=browser.image_id.removeprefix("sha256:"),
                purpose=WebExecutionPurpose.PROFILE_VALIDATION,
                trigger=WebExecutionAttemptTrigger.PROFILE_VALIDATION,
                authorization_id=None,
                rerun_phases=None,
                declared_routes=(),
            )
            assert (
                await executor.start_execution(
                    owner_user_id=owner.id, project_id=project.id, command=command
                )
            ).status is WebApiCommandStatus.APPROVAL_REQUIRED
            assert (
                await executor.prepare_execution(
                    owner_user_id=foreign.id, project_id=project.id, command=command
                )
            ).status is WebApiCommandStatus.NOT_FOUND
            assert (
                await executor.prepare_execution(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    command=replace(command, purpose=WebExecutionPurpose.OWNER_PROJECT),
                )
            ).status is WebApiCommandStatus.CAPABILITY_BLOCKED
            prepared = await executor.prepare_execution(
                owner_user_id=owner.id, project_id=project.id, command=command
            )
            assert prepared.status is WebApiCommandStatus.EXECUTION_PREPARED
            pending = prepared.snapshot
            assert (
                pending["state"] == "PENDING"
                and pending["payload"]["purpose"] == "PROFILE_VALIDATION"
            )
            assert pending["payload"]["source_revision"]["content_hash"] == revision.content_hash
            assert (
                pending["payload"]["contract"]["runners"]["browser_runner_image_digest"]
                == command.browser_runner_image_digest
            )
            authorized = replace(command, authorization_id=UUID(pending["id"]))
            unapproved = await executor.start_execution(
                owner_user_id=owner.id, project_id=project.id, command=authorized
            )
            assert unapproved.status in {
                WebApiCommandStatus.APPROVAL_REQUIRED,
                WebApiCommandStatus.CONFLICT,
            }
            assert backend.executions == 0 and not workspaces_root.exists()
            await approve(operations, owner=owner, project=project, snapshot=pending)
            assert (
                await executor.start_execution(
                    owner_user_id=foreign.id, project_id=project.id, command=authorized
                )
            ).status is WebApiCommandStatus.NOT_FOUND
            assert (
                await executor.start_execution(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    command=replace(authorized, execution_runner_image_digest="f" * 64),
                )
            ).status is WebApiCommandStatus.CONFLICT
            first_task = asyncio.create_task(
                executor.start_execution(
                    owner_user_id=owner.id, project_id=project.id, command=authorized
                )
            )
            try:
                await asyncio.wait_for(backend.claimed.wait(), timeout=15)
                duplicate = await executor.start_execution(
                    owner_user_id=owner.id, project_id=project.id, command=authorized
                )
                assert duplicate.status is WebApiCommandStatus.CONFLICT
            finally:
                backend.release_first.set()
                first = await asyncio.wait_for(first_task, timeout=180)
            assert first.status is WebApiCommandStatus.EXECUTION_RECORDED
            first_attempt = first.snapshot
            assert first_attempt["id"] == pending["id"]
            assert first_attempt["report"]["status"] == "FAILED"
            failure = next(
                item
                for item in first_attempt["report"]["failure_signatures"]
                if item["phase"] == "BROWSER_EVIDENCE"
            )
            observed_failure = await reader.browser_evidence(
                owner_user_id=owner.id, execution_id=UUID(first_attempt["id"])
            )
            assert (
                observed_failure["status"] == "FAILED"
                and observed_failure["cleanup_confirmed"] is True
            )
            assert "UNIT7_DEVELOPMENT_FAILURE" in json.dumps(observed_failure["bundle"])
            assert (
                await reader.browser_evidence(
                    owner_user_id=foreign.id, execution_id=UUID(first_attempt["id"])
                )
                is None
            )

            await database.dispose()
            database = create_database_runtime(settings)
            operations, loader, executor, reader = services()
            replay = await executor.start_execution(
                owner_user_id=owner.id, project_id=project.id, command=authorized
            )
            assert replay.snapshot == first_attempt and backend.executions == 1
            assert (
                await reader.browser_evidence(
                    owner_user_id=owner.id, execution_id=UUID(first_attempt["id"])
                )
                == observed_failure
            )
            repair = SqlAlchemyWebRepairApiService(
                database.session_factory, operation_store=operations, content_root=content_root
            )
            proposal = await repair.create_repair_proposal(
                owner_user_id=owner.id,
                execution_id=UUID(first_attempt["id"]),
                command=WebRepairProposalCreateCommand(
                    base_revision_content_hash=revision.content_hash,
                    failure_signature_digest=failure["digest"],
                    changes=(
                        WebRepairChangeCommand(
                            WebSourceChangeOperation.REPLACE,
                            "app.js",
                            "document.documentElement.dataset.unit7 = 'repaired';\n",
                            "text/javascript",
                        ),
                    ),
                    rationale="Remove the deterministic development console failure.",
                ),
            )
            assert proposal.status is WebApiCommandStatus.REPAIR_PROPOSED
            proposal_id = UUID(proposal.snapshot["id"])
            apply_command = WebRepairProposalApplyCommand(
                revision.content_hash, proposal.snapshot["proposal_content_hash"], None
            )
            assert (
                await repair.apply_repair_proposal(
                    owner_user_id=owner.id,
                    execution_id=UUID(first_attempt["id"]),
                    proposal_id=proposal_id,
                    command=apply_command,
                )
            ).status is WebApiCommandStatus.APPROVAL_REQUIRED
            gate_id = await approve(
                operations, owner=owner, project=project, snapshot=proposal.snapshot
            )
            repaired = await repair.apply_repair_proposal(
                owner_user_id=owner.id,
                execution_id=UUID(first_attempt["id"]),
                proposal_id=proposal_id,
                command=replace(apply_command, approval_id=gate_id),
            )
            assert repaired.status is WebApiCommandStatus.REPAIR_APPLIED
            assert repaired.snapshot["execution_performed"] is False and backend.executions == 1
            new_source = repaired.snapshot["source_revision"]
            assert new_source["based_on"] == revision.reference.to_snapshot()
            assert new_source["related_failure_signature"] == failure["digest"]
            rerun = replace(
                command,
                source_revision_id=UUID(new_source["id"]),
                trigger=WebExecutionAttemptTrigger.REPAIR_RERUN,
                rerun_phases=tuple(
                    WebExecutionPhase(name) for name in repaired.snapshot["required_rerun_phases"]
                ),
            )
            rerun_prepared = await executor.prepare_execution(
                owner_user_id=owner.id, project_id=project.id, command=rerun
            )
            assert rerun_prepared.status is WebApiCommandStatus.EXECUTION_PREPARED
            assert (
                rerun_prepared.snapshot["payload"]["previous_attempt"]["id"] == first_attempt["id"]
            )
            await approve(
                operations, owner=owner, project=project, snapshot=rerun_prepared.snapshot
            )
            second = await executor.start_execution(
                owner_user_id=owner.id,
                project_id=project.id,
                command=replace(rerun, authorization_id=UUID(rerun_prepared.snapshot["id"])),
            )
            assert second.status is WebApiCommandStatus.EXECUTION_RECORDED
            second_attempt = second.snapshot
            assert second_attempt["previous_attempt_id"] == first_attempt["id"]
            assert second_attempt["source_revision"]["content_hash"] == new_source["content_hash"]
            assert second_attempt["report"]["status"] == "PASSED"
            assert second_attempt["attempt_number"] == 2 and backend.executions == 2
            observed_success = await reader.browser_evidence(
                owner_user_id=owner.id, execution_id=UUID(second_attempt["id"])
            )
            assert (
                observed_success["status"] == "PASSED"
                and observed_success["cleanup_confirmed"] is True
            )
            assert (
                observed_success["bundle"]["request"]["source_revision_content_hash"]
                == new_source["content_hash"]
            )
            assert (
                await reader.execution_history(owner_user_id=owner.id, project_id=project.id)
            ) == (first_attempt, second_attempt)
            source_reader = SqlAlchemyWebSourceApiService(
                database.session_factory, content_root=content_root
            )
            assert (
                len(
                    await source_reader.source_revision_history(
                        owner_user_id=owner.id, project_id=project.id
                    )
                )
                == 2
            )
            assert (
                await source_reader.source_revision_history(
                    owner_user_id=foreign.id, project_id=project.id
                )
                == ()
            )
            assert all(
                (content_root / key).read_bytes() == value for key, value in original_bytes.items()
            )
            assert not tuple(workspaces_root.glob("api-web-input-*"))
            assert not tuple((workspaces_root / "mutable").glob("*"))
            assert (await loader.load()).catalog.records == ()
            (tmp_path / "governed-web-api-development.json").write_text(
                json.dumps(
                    {
                        "formal_run_started": False,
                        "level_d_validated": False,
                        "execution_claim_ids": backend.observed_claim_ids,
                        "failure": first_attempt,
                        "repair": repaired.snapshot,
                        "rerun": second_attempt,
                        "browser_failure": observed_failure,
                        "browser_rerun": observed_success,
                    },
                    sort_keys=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            await database.dispose()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
