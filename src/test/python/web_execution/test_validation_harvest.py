"""Verifier regressions use synthetic receipts, never publish profile capability."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.reports import WebEvidenceReference
from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.validation_harvest import (
    ContractTestReceipt,
    HarvestFixture,
    HarvestInputs,
    WebValidationHarvestError,
    publish_validation_batch,
    verify_validation_harvest,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
COMMIT = "a" * 40


class Objects:
    def __init__(self):
        self.values = {}

    def put(self, body, media_type="application/json"):
        if not isinstance(body, bytes):
            body = canonical_bytes(body)
        digest = hashlib.sha256(body).hexdigest()
        reference = WebEvidenceReference(
            f"sha256/{digest[:2]}/{digest}", digest, len(body), media_type
        )
        self.values[reference.storage_key] = body
        return reference

    def read(self, reference):
        return self.values[reference.storage_key]


def inputs():
    objects = Objects()
    profiles = create_sprint08_web_profile_registry().profiles
    fixtures = tuple(
        HarvestFixture(
            fixture_id=f"fixture.{profile.scope.profile_id}.{index}",
            profile_id=profile.scope.profile_id,
            profile_version=profile.scope.profile_version,
            language_configuration=configuration,
            valid_source_tree_hash="b" * 64,
            failure_source_tree_hash="c" * 64,
            failure_phase=WebExecutionPhase.TEST,
            fixture_bundle_hash="d" * 64,
        )
        for profile in profiles
        for index, configuration in enumerate(profile.scope.language_configurations)
    )
    artifacts = []
    logs = []
    for kind in ("NODE", "PHP", "BROWSER"):
        for action in ("BUILD", "PROBE"):
            for stream in ("stdout", "stderr"):
                name = f"{action}_{kind}.{stream}.log"
                reference = objects.put(name.encode(), "text/plain")
                logs.append(reference)
                artifacts.append(
                    {
                        "path": name,
                        "sha256": reference.sha256_digest,
                        "size_bytes": reference.size_bytes,
                    }
                )
    environment = {"platform": "linux/amd64", "builder_driver": "docker"}
    manifest = {
        "schema_version": 2,
        "report_type": "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE",
        "status": "IMAGES_BUILT_PROBES_RECORDED",
        "level_d_validated": False,
        "formal_run_started": False,
        "browser_automation_verified": False,
        "platform_commit": COMMIT,
        "environment": environment,
        "environment_hash": content_hash(environment),
        "artifacts": artifacts,
        "runners": [
            {
                "kind": kind,
                "image_id": "sha256:" + str(index + 1) * 64,
                "recipe_content_hash": str(index + 4) * 64,
                "cleanup_confirmed": True,
            }
            for index, kind in enumerate(("NODE", "PHP", "BROWSER"))
        ],
    }
    manifest["content_hash"] = content_hash(manifest)
    identities = tuple(
        WebPhaseRunnerIdentity(
            item["kind"], item["image_id"], manifest["content_hash"], item["recipe_content_hash"]
        )
        for item in manifest["runners"]
    )
    required = tuple(f"fixture.contract.test_{index}" for index in range(8))
    xml = (
        '<testsuite tests="8" errors="0" failures="0" skipped="0">'
        + "".join(
            f'<testcase classname="fixture.contract" name="test_{index}"/>' for index in range(8)
        )
        + "</testsuite>"
    ).encode()
    command = ContractTestReceipt(
        argv=(
            "python",
            "-m",
            "pytest",
            "src/test/python/web_execution/test_profile_fixture_matrix.py",
            "--junitxml=results.xml",
        ),
        result=HostProcessResult(HostProcessStatus.COMPLETED, 0, b"8 passed", b"", None),
        stdout_ref=objects.put(b"8 passed", "text/plain"),
        stderr_ref=objects.put(b"", "text/plain"),
        junit_ref=objects.put(xml, "application/xml"),
        required_test_ids=required,
    )
    limitations = objects.put(
        {
            "schema_version": 1,
            "platform_commit": COMMIT,
            "profiles": [profile.scope.to_snapshot() for profile in profiles],
        }
    )
    return objects, HarvestInputs(
        platform_commit=COMMIT,
        recorded_at=NOW,
        fixtures=fixtures,
        journeys=(),
        runner_identities=identities,
        bootstrap_manifest_ref=objects.put(manifest),
        bootstrap_artifacts=tuple(logs),
        contract_tests=command,
        limitations_ref=limitations,
    )


def test_missing_actual_journeys_and_ci_remain_incomplete_without_fabricated_records():
    objects, request = inputs()
    batch = verify_validation_harvest(request, read_artifact=objects.read)
    assert not batch.is_complete
    assert len(batch.records) == 20
    assert all(record.passed for record in batch.records)
    assert {record.kind.value for record in batch.records} == {
        "CONTRACT_TESTS",
        "RUNNER_BUILD",
        "ENVIRONMENT_MANIFEST",
        "KNOWN_LIMITATIONS",
    }
    assert all(decision.status.value == "INCOMPLETE" for decision in batch.promotion_decisions)
    assert all(
        "profile:CI_VERIFICATION" in decision.missing_requirements
        for decision in batch.promotion_decisions
    )
    assert verify_validation_harvest(request, read_artifact=objects.read) == batch
    assert all(
        hashlib.sha256(body).hexdigest() == ref.sha256_digest for ref, body in batch.artifacts
    )


@pytest.mark.parametrize("field", ["bootstrap_manifest_ref", "limitations_ref"])
def test_changed_content_addressed_proof_is_rejected(field):
    objects, request = inputs()
    reference = getattr(request, field)
    objects.values[reference.storage_key] += b"changed"
    with pytest.raises(WebValidationHarvestError, match="ARTIFACT"):
        verify_validation_harvest(request, read_artifact=objects.read)


def test_missing_bootstrap_log_and_mismatched_identity_are_rejected():
    objects, request = inputs()
    with pytest.raises(WebValidationHarvestError, match="BOOTSTRAP"):
        verify_validation_harvest(
            replace(request, bootstrap_artifacts=()), read_artifact=objects.read
        )
    changed = replace(request.runner_identities[0], image_id="sha256:" + "9" * 64)
    with pytest.raises(WebValidationHarvestError, match="BOOTSTRAP"):
        verify_validation_harvest(
            replace(request, runner_identities=(changed, *request.runner_identities[1:])),
            read_artifact=objects.read,
        )


@pytest.mark.parametrize(
    "body",
    [
        b'<testsuite tests="8"><testcase classname="fixture.contract" name="test_0"/></testsuite>',
        b'<testsuite tests="1"><testcase classname="fixture.contract" name="test_0"><skipped/></testcase></testsuite>',
        b'<!DOCTYPE foo [<!ENTITY x "bad">]><testsuite/>',
        b'{"passed":true}',
    ],
)
def test_exit_zero_does_not_replace_actual_complete_junit_observations(body):
    objects, request = inputs()
    receipt = replace(request.contract_tests, junit_ref=objects.put(body, "application/xml"))
    with pytest.raises(WebValidationHarvestError, match="CONTRACT_TEST"):
        verify_validation_harvest(
            replace(request, contract_tests=receipt), read_artifact=objects.read
        )


def test_missing_configuration_and_wrong_limitations_scope_are_rejected():
    objects, request = inputs()
    with pytest.raises(WebValidationHarvestError, match="FIXTURE"):
        verify_validation_harvest(
            replace(request, fixtures=request.fixtures[:-1]), read_artifact=objects.read
        )
    limits = objects.put({"schema_version": 1, "platform_commit": COMMIT, "profiles": []})
    with pytest.raises(WebValidationHarvestError, match="LIMITATIONS"):
        verify_validation_harvest(
            replace(request, limitations_ref=limits), read_artifact=objects.read
        )


def test_incomplete_batch_never_opens_a_publication_transaction():
    objects, request = inputs()
    batch = verify_validation_harvest(request, read_artifact=objects.read)

    def forbidden():
        pytest.fail("incomplete evidence must not open a publication transaction")

    with pytest.raises(WebValidationHarvestError, match="INCOMPLETE"):
        asyncio.run(
            publish_validation_batch(
                batch, unit_of_work_factory=forbidden, read_artifact=objects.read
            )
        )


def test_real_phase_adapter_receipts_include_persistent_run_without_invented_terminal_exit(
    tmp_path,
):
    from types import SimpleNamespace
    from uuid import uuid4

    from orchestwin.web_execution.validation_harvest import _Artifacts, _phase_metadata

    from .test_phase_executor_contracts import executor_for_fixture

    async def scenario():
        executor, contract, store, _, _ = executor_for_fixture(tmp_path, "web-express-js-valid")
        attempt_id = uuid4()
        executor.bind_attempt(attempt_id)
        receipt = SimpleNamespace(
            source=SimpleNamespace(
                content_hash=contract.source_revision_content_hash,
                source_tree_hash=contract.source_tree_hash,
            ),
            attempt=SimpleNamespace(
                id=attempt_id,
                report=SimpleNamespace(policy_content_hash=executor.policy.content_hash),
            ),
        )
        objects = _Artifacts(lambda ref: store.read(ref.storage_key))
        for planned in contract.execution_plan.phases:
            if planned.phase is WebExecutionPhase.COLLECT_ARTIFACTS:
                break
            phase = await executor.execute(planned, contract=contract)
            if planned.execution_kind.value != "NO_OP":
                _phase_metadata(
                    receipt,
                    phase,
                    planned.to_snapshot(),
                    executor.identity,
                    contract.to_snapshot(),
                    objects,
                )
        finalized = await executor.finalize()
        _phase_metadata(
            receipt,
            finalized,
            contract.execution_plan.phase(WebExecutionPhase.COLLECT_ARTIFACTS).to_snapshot(),
            executor.identity,
            contract.to_snapshot(),
            objects,
        )

    asyncio.run(scenario())


@pytest.fixture(scope="module")
def complete_campaign(tmp_path_factory):
    """Production prepare/phase/browser/repair code; only transport observations are fixtures."""
    from pathlib import Path
    from uuid import uuid4

    from orchestwin.api.governed_web_context import GovernedWebSettings, WebExecutionBackend
    from orchestwin.api.governed_web_execution_runtime import (
        SqlAlchemyGovernedWebExecutionApiService,
    )
    from orchestwin.api.web_execution import WebExecutionStartCommand
    from orchestwin.artifacts.web_change_sets import (
        WebSourceChange,
        WebSourceChangeOperation,
        WebSourceChangeSet,
    )
    from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
    from orchestwin.artifacts.web_sources import (
        WebSourceOrigin,
        WebSourceProvenanceKind,
        WebSourceProvenanceReference,
        create_web_source_revision,
    )
    from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
    from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
    from orchestwin.sandbox.host_process import BoundedHostProcessResult
    from orchestwin.web_execution.attempts import WebExecutionAttempt, WebExecutionAttemptTrigger
    from orchestwin.web_execution.operation_governance import (
        WebGovernedOperation,
        WebOperationState,
        operation_json,
    )
    from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor
    from orchestwin.web_execution.phase_browser_transport import WebBrowserTransportResult
    from orchestwin.web_execution.phase_executor import GovernedWebPhaseExecutor
    from orchestwin.web_execution.phase_runtime import ControlledWebNetwork
    from orchestwin.web_execution.repair_records import web_repair_proposal_to_snapshot
    from orchestwin.web_execution.reports import WebExecutionReport
    from orchestwin.web_execution.validation_ci import (
        CiProviderResponse,
        CiVerificationStatus,
        VerifiedCiObservation,
    )
    from orchestwin.web_execution.validation_harvest import HarvestAttempt, HarvestJourney
    from orchestwin.web_execution.workspaces import materialize_web_source_snapshot
    from orchestwin.workflow.gates import (
        HumanGateAction,
        HumanGateType,
        create_human_gate,
        transition_human_gate,
    )
    from orchestwin.workflow.web_execution import WebExecutionPurpose, _not_run_result
    from orchestwin.workflow.web_repair import WebRepairProposal, apply_web_repair_revision

    from .test_phase_browser_evidence import envelope, events, report
    from .test_phase_executor_contracts import TEST_POLICY, FakeRuntime
    from .test_profile_fixture_matrix import fixture_files, matrix

    root = tmp_path_factory.mktemp("harvest-production-adapters")
    objects, initial = inputs()
    identities = {identity.kind: identity for identity in initial.runner_identities}
    source_store = FileSystemWebSourceContentStore(root / "sources")
    evidence_store = FileSystemSandboxEvidenceStore(root / "evidence")
    registry = create_sprint08_web_profile_registry()
    patch = pytest.MonkeyPatch()
    patch.setattr(
        "orchestwin.api.governed_web_context.load_phase_runner_identity",
        lambda *args, kind, **kwargs: identities[kind],
    )
    configuration = GovernedWebSettings(
        _env_file=None,
        enabled=True,
        repo_root=Path(__file__).parents[4],
        runner_manifest=root / "manifest.json",
        workspaces_root=root / "workspaces",
        docker_context="test-transport",
    ).model_copy(
        update={
            "controlled_network": ControlledWebNetwork(
                "test-transport", "a" * 64, TEST_POLICY.content_hash, "test-proxy", 8080
            )
        }
    )
    backend = WebExecutionBackend(
        config=configuration,
        content_root=root / "sources",
        evidence_root=root / "evidence",
        resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
    )
    backend.policy = TEST_POLICY

    def read(reference):
        return objects.values.get(reference.storage_key, evidence_store.read(reference.storage_key))

    def approve(operation):
        gate = create_human_gate(
            project_id=operation.project_id,
            owner_user_id=operation.owner_user_id,
            gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            artifact=operation.artifact,
            gate_id=operation.gate_id,
            created_at=operation.created_at,
        )
        submitted = transition_human_gate(
            gate, action=HumanGateAction.SUBMIT, actor_user_id=operation.owner_user_id
        )
        approved = transition_human_gate(
            submitted.gate, action=HumanGateAction.APPROVE, actor_user_id=operation.owner_user_id
        )
        return approved.gate, approved.event

    def source(files, scope):
        return create_web_source_revision(
            revision_id=uuid4(),
            project_id=uuid4(),
            created_by_user_id=uuid4(),
            version_number=1,
            based_on=None,
            target=scope.target,
            language_configuration=scope.language_configurations[0],
            layout=scope.layout,
            origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
            files=tuple(
                source_store.store(
                    normalized_path=name, content=body.encode(), media_type="text/plain"
                )
                for name, body in sorted(
                    files.items(), key=lambda item: (item[0].casefold(), item[0])
                )
            ),
            provenance_references=(
                WebSourceProvenanceReference(
                    WebSourceProvenanceKind.SOURCE_PLAN,
                    "harvest.transport.fixture",
                    1,
                    content_hash(files),
                ),
            ),
            created_at=datetime.now(UTC),
        )

    async def attempt(revision, *, failed=False, previous=None):
        scope = registry.for_target(revision.target_selection.target).scope
        identity = identities["PHP" if scope.target.value == "WEB_PHP" else "NODE"]
        browser = identities["BROWSER"] if scope.requires_browser_evidence else None
        trigger = (
            WebExecutionAttemptTrigger.PROFILE_VALIDATION
            if previous is None
            else WebExecutionAttemptTrigger.REPAIR_RERUN
        )
        command = WebExecutionStartCommand(
            revision.id,
            scope.profile_id,
            scope.profile_version,
            TEST_POLICY.content_hash,
            identity.image_id.removeprefix("sha256:"),
            None if browser is None else browser.image_id.removeprefix("sha256:"),
            WebExecutionPurpose.PROFILE_VALIDATION,
            trigger,
            None,
            None if previous is None else tuple(WebExecutionPhase),
            (),
        )
        context = backend.prepare(
            revision,
            command=command,
            registry=registry,
            previous=None if previous is None else previous.attempt,
        )
        operation = WebGovernedOperation.create(
            project_id=revision.project_id,
            owner_user_id=revision.created_by_user_id,
            source_revision_id=revision.id,
            kind="EXECUTION",
            payload=context.payload,
        )
        gate, approval_event = approve(operation)
        operation = replace(
            operation, state=WebOperationState.RUNNING, started_at=datetime.now(UTC)
        )
        prepared = materialize_web_source_snapshot(
            revision.to_snapshot(),
            content_root=root / "sources",
            workspaces_root=root / "prepared" / operation.id.hex,
        )
        test_commands = {
            command.command_id
            for plan in context.contract.execution_plan.phase(WebExecutionPhase.TEST).command_plans
            for command in plan.commands
        }

        class Runtime(FakeRuntime):
            async def run_command(self, command):
                observed = await super().run_command(command)
                if failed and command.command_id in test_commands:
                    return replace(observed, exit_code=1, stdout=b"LEVEL_D_NEGATIVE_CONTROL\n")
                return observed

        class BrowserTransport:
            async def execute(self, job, **kwargs):
                observed = report(job)
                if failed:
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
                    (("EXECUTE", process),), 0, True, None, "a" * 64, "b" * 64
                )

        browser_executor = (
            None
            if browser is None
            else GovernedWebBrowserExecutor(
                runner_identity=browser,
                repo_root=configuration.repo_root,
                evidence_store=evidence_store,
                transport=BrowserTransport(),
                expected_harness_sha256=context.payload["browser_harness_sha256"],
                expected_seccomp_sha256=context.payload["browser_seccomp_sha256"],
            )
        )
        executor = GovernedWebPhaseExecutor(
            contract=context.contract,
            prepared_workspace=prepared,
            snapshot=context.snapshot,
            lock_report=context.locks,
            runner_identity=identity,
            execution_policy=TEST_POLICY,
            resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
            workspaces_root=root / "phases",
            evidence_store=evidence_store,
            docker_context="test-transport",
            runtime_factory=Runtime,
            controlled_network=configuration.controlled_network,
            browser_executor=browser_executor,
        )
        executor.bind_attempt(operation.id)
        started = datetime.now(UTC)
        results, executed, halted = [], [], False
        for planned in context.contract.execution_plan.phases:
            if planned.phase is WebExecutionPhase.COLLECT_ARTIFACTS:
                result = await executor.finalize()
            elif halted:
                results.append(_not_run_result(planned.phase, "Previous observed phase failed."))
                continue
            else:
                result = await executor.execute(planned, contract=context.contract)
            results.append(result)
            if result.status.value != "SKIPPED":
                executed.append(result.phase)
            halted |= result.is_failure
        execution_report = WebExecutionReport(
            revision.content_hash,
            revision.source_tree_hash,
            scope.profile_id,
            scope.profile_version,
            identity.image_id.removeprefix("sha256:"),
            TEST_POLICY.content_hash,
            tuple(results),
        )
        observed = WebExecutionAttempt(
            operation.id,
            revision.project_id,
            revision.created_by_user_id,
            1 if previous is None else 2,
            None if previous is None else previous.attempt.id,
            revision.reference,
            context.contract.validation.content_hash,
            context.contract.execution_plan.content_hash,
            trigger,
            tuple(executed),
            execution_report,
            started,
            datetime.now(UTC),
        )
        operation = replace(
            operation,
            state=WebOperationState.COMPLETED,
            finished_at=datetime.now(UTC),
            result_json=operation_json(
                SqlAlchemyGovernedWebExecutionApiService._recorded_result(
                    operation, observed.to_snapshot()
                )
            ),
        )
        browser_manifest = None
        browser_phase = next(
            item for item in results if item.phase is WebExecutionPhase.BROWSER_EVIDENCE
        )
        for reference in browser_phase.artifact_refs:
            if reference.media_type == "application/json":
                import json

                value = json.loads(read(reference))
                if value.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE":
                    browser_manifest = value
        return HarvestAttempt(revision, observed, operation, gate, approval_event, browser_manifest)

    async def campaign():
        fixtures, journeys = [], []
        for item in matrix()["valid_fixtures"]:
            from orchestwin.sandbox.execution_profiles import ExecutionTarget
            from orchestwin.web_execution.targets import (
                WebImplementationLanguage,
                WebLanguageConfiguration,
            )

            scope = registry.for_target(ExecutionTarget(item["target"])).scope
            configuration = WebLanguageConfiguration(
                None if item["frontend"] is None else WebImplementationLanguage(item["frontend"]),
                None if item["backend"] is None else WebImplementationLanguage(item["backend"]),
            )
            files = {**fixture_files(item["id"]), "fixture-control.txt": "VALID"}
            base = source(files, scope)
            base = replace(
                base,
                target_selection=replace(
                    base.target_selection, language_configuration=configuration
                ),
            )
            valid = await attempt(base)
            repeated = await attempt(
                replace(base, id=uuid4(), project_id=uuid4(), created_by_user_id=uuid4())
            )
            bad = source({**files, "fixture-control.txt": "FAILED"}, scope)
            bad = replace(
                bad,
                target_selection=replace(
                    bad.target_selection, language_configuration=configuration
                ),
            )
            failed = await attempt(bad, failed=True)
            signature = failed.attempt.report.failure_signatures()[0]
            restored = base.file_by_path("fixture-control.txt")
            proposal = WebRepairProposal(
                uuid4(),
                bad.project_id,
                bad.created_by_user_id,
                bad.reference,
                signature,
                WebSourceChangeSet(
                    uuid4(),
                    bad.project_id,
                    bad.reference,
                    (
                        WebSourceChange(
                            restored.normalized_path,
                            WebSourceChangeOperation.REPLACE,
                            restored.sha256_digest,
                            restored.size_bytes,
                            restored.storage_key,
                            restored.media_type,
                        ),
                    ),
                    "Repair deterministic transport fixture.",
                    ("harvest.fixture.failure",),
                ),
                1,
                1,
                (
                    WebSourceProvenanceReference(
                        WebSourceProvenanceKind.FAILURE_SIGNATURE,
                        "harvest.fixture.failure",
                        1,
                        signature.digest,
                    ),
                ),
                datetime.now(UTC),
            )
            repair = WebGovernedOperation.create(
                project_id=bad.project_id,
                owner_user_id=bad.created_by_user_id,
                source_revision_id=bad.id,
                kind="REPAIR",
                payload={
                    "schema_version": 1,
                    "execution_id": str(failed.attempt.id),
                    "execution_content_hash": failed.attempt.content_hash,
                    "proposal": web_repair_proposal_to_snapshot(proposal),
                },
            )
            repair_gate, repair_approval = approve(repair)
            repair = replace(repair, state=WebOperationState.RUNNING, started_at=datetime.now(UTC))
            applied = apply_web_repair_revision(
                proposal,
                base_revision=bad,
                revision_id=uuid4(),
                created_by_user_id=bad.created_by_user_id,
                created_at=datetime.now(UTC),
                content_store=source_store,
            )
            assert applied.revision is not None
            repair = replace(
                repair,
                state=WebOperationState.COMPLETED,
                finished_at=datetime.now(UTC),
                result_json=operation_json(
                    {
                        "source_revision": applied.revision.to_snapshot(),
                        "required_rerun_phases": [
                            phase.value for phase in applied.required_rerun_phases
                        ],
                        "execution_performed": False,
                    }
                ),
            )
            rerun = await attempt(applied.revision, previous=failed)
            fixtures.append(
                HarvestFixture(
                    item["id"],
                    scope.profile_id,
                    scope.profile_version,
                    configuration,
                    base.source_tree_hash,
                    bad.source_tree_hash,
                    signature.phase,
                    content_hash(files),
                )
            )
            journeys.append(
                HarvestJourney(
                    item["id"], valid, repeated, failed, repair, repair_gate, repair_approval, rerun
                )
            )
        response = CiProviderResponse(
            "https://api.github.com/repos/test/fixture/actions/runs/1",
            200,
            b'{"test_fixture":"provider"}',
        )
        objects.put(response.body)
        ci = VerifiedCiObservation(
            CiVerificationStatus.PASSED,
            "test/fixture",
            COMMIT,
            1,
            1,
            "c" * 64,
            datetime.now(UTC),
            (),
            (response,),
            "success",
        )
        return replace(
            initial, fixtures=tuple(fixtures), journeys=tuple(journeys), ci_observation=ci
        )

    try:
        request = asyncio.run(campaign())
        yield objects, request, read
    finally:
        patch.undo()


def test_complete_actual_adapter_receipts_cover_all_52_requirements(complete_campaign):
    _, request, read = complete_campaign
    batch = verify_validation_harvest(request, read_artifact=read)
    assert batch.is_complete and len(batch.records) == 52
    assert len({item.kind for item in batch.records}) == 9
    assert all(
        item.language_configuration is None
        or item.profile_id != "web.node-express"
        or item.kind.value != "BROWSER_EVIDENCE"
        for item in batch.records
    )


def test_complete_publication_is_idempotent_and_conflict_rolls_back_whole_batch(complete_campaign):
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestwin.web_execution.validation_evidence_persistence import (
        WebValidationEvidenceAppendStatus,
        canonical_web_validation_evidence,
    )

    objects, request, read = complete_campaign
    batch = verify_validation_harvest(request, read_artifact=read)
    for reference, body in batch.artifacts:
        assert objects.put(body) == reference
    committed, events = {}, []

    class Unit:
        def __init__(self):
            self._session = AsyncSession()
            self._session.execute = self.lock
            self.evidence = self

        async def lock(self, *args, **kwargs):
            events.append("lock")

        async def __aenter__(self):
            self.pending = dict(committed)
            return self

        async def __aexit__(self, *args):
            await self._session.close()

        async def append(self, record):
            if record.evidence_id in self.pending:
                return (
                    WebValidationEvidenceAppendStatus.ALREADY_PRESENT
                    if self.pending[record.evidence_id] == record
                    else WebValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
                )
            self.pending[record.evidence_id] = record
            return WebValidationEvidenceAppendStatus.APPENDED

        async def history(self):
            return canonical_web_validation_evidence(tuple(self.pending.values()))

        async def commit(self):
            committed.update(self.pending)
            events.append("commit")

    async def scenario():
        first = await publish_validation_batch(batch, unit_of_work_factory=Unit, read_artifact=read)
        second = await publish_validation_batch(
            batch, unit_of_work_factory=Unit, read_artifact=read
        )
        assert (first.appended, first.already_present) == (52, 0)
        assert (second.appended, second.already_present) == (0, 52)
        assert events == ["lock", "commit", "lock", "commit"]
        last = batch.records[-1]
        committed.clear()
        committed[last.evidence_id] = replace(last, passed=False)
        before = dict(committed)
        with pytest.raises(WebValidationHarvestError, match="CONFLICT"):
            await publish_validation_batch(batch, unit_of_work_factory=Unit, read_artifact=read)
        assert committed == before and events[-1] == "lock"

    asyncio.run(scenario())


def test_negative_control_marker_cannot_be_satisfied_by_an_unrelated_failure(complete_campaign):
    _, request, read = complete_campaign
    changed = replace(request.fixtures[0], expected_failure_marker="ANOTHER_CONTROL")
    with pytest.raises(WebValidationHarvestError, match="FAILURE_MARKER"):
        verify_validation_harvest(
            replace(request, fixtures=(changed, *request.fixtures[1:])), read_artifact=read
        )


def test_historical_exact_approval_survives_stale_gate_but_not_wrong_actor(complete_campaign):
    from uuid import uuid4

    from orchestwin.workflow.gates import HumanGateStatus, mark_human_gate_stale

    _, request, read = complete_campaign
    journey = request.journeys[0]
    stale = mark_human_gate_stale(
        journey.failed.gate,
        current_artifact=journey.repair_operation.artifact,
        occurred_at=journey.repair_operation.created_at,
    )
    assert stale.gate.status is HumanGateStatus.STALE
    changed = replace(journey, failed=replace(journey.failed, gate=stale.gate))
    revised = replace(request, journeys=(changed, *request.journeys[1:]))
    assert verify_validation_harvest(revised, read_artifact=read).is_complete
    changed = replace(
        changed,
        failed=replace(
            changed.failed,
            approval_event=replace(changed.failed.approval_event, actor_user_id=uuid4()),
        ),
    )
    with pytest.raises(WebValidationHarvestError, match="APPROVAL"):
        verify_validation_harvest(
            replace(request, journeys=(changed, *request.journeys[1:])), read_artifact=read
        )


def test_hashed_failure_cannot_claim_a_successful_terminal_command(complete_campaign):
    import json

    from orchestwin.api.governed_web_execution_runtime import (
        SqlAlchemyGovernedWebExecutionApiService,
    )
    from orchestwin.web_execution.operation_governance import operation_json

    objects, request, read = complete_campaign
    index = next(
        index
        for index, fixture in enumerate(request.fixtures)
        if fixture.failure_phase is WebExecutionPhase.TEST
    )
    journey = request.journeys[index]
    receipt = journey.failed
    phase = next(
        phase
        for phase in receipt.attempt.report.phase_results
        if phase.phase is WebExecutionPhase.TEST
    )
    reference, metadata = next(
        (ref, json.loads(read(ref)))
        for ref in phase.artifact_refs
        if ref.media_type == "application/json" and json.loads(read(ref)).get("phase") == "TEST"
    )
    metadata["sandbox_runs"][-1]["command_evidence"][-1]["status"] = "SUCCEEDED"
    metadata["sandbox_runs"][-1]["command_evidence"][-1]["exit_code"] = 0
    changed_ref = objects.put(metadata)
    changed_phase = replace(
        phase,
        exit_codes=(*phase.exit_codes[:-1], 0),
        artifact_refs=tuple(
            sorted(changed_ref if ref == reference else ref for ref in phase.artifact_refs)
        ),
    )
    changed_attempt = replace(
        receipt.attempt,
        report=replace(
            receipt.attempt.report,
            phase_results=tuple(
                changed_phase if item.phase is phase.phase else item
                for item in receipt.attempt.report.phase_results
            ),
        ),
    )
    operation = replace(
        receipt.operation,
        result_json=operation_json(
            SqlAlchemyGovernedWebExecutionApiService._recorded_result(
                receipt.operation, changed_attempt.to_snapshot()
            )
        ),
    )
    changed = replace(
        journey, failed=replace(receipt, attempt=changed_attempt, operation=operation)
    )
    with pytest.raises(WebValidationHarvestError, match="COMMAND"):
        verify_validation_harvest(
            replace(
                request,
                journeys=tuple(
                    changed if offset == index else item
                    for offset, item in enumerate(request.journeys)
                ),
            ),
            read_artifact=read,
        )


@pytest.mark.parametrize("mutation", ["unbound_log", "omitted_executed_phase"])
def test_observed_command_logs_and_phase_inventory_are_exact(complete_campaign, mutation):
    import json

    from orchestwin.api.governed_web_execution_runtime import (
        SqlAlchemyGovernedWebExecutionApiService,
    )
    from orchestwin.web_execution.operation_governance import operation_json

    objects, request, read = complete_campaign
    journey = request.journeys[1]
    receipt = journey.valid
    observed = receipt.attempt
    if mutation == "omitted_executed_phase":
        observed = replace(
            observed,
            executed_phases=tuple(
                phase for phase in observed.executed_phases if phase is not WebExecutionPhase.TEST
            ),
        )
    else:
        phase = next(
            phase
            for phase in observed.report.phase_results
            if phase.phase is WebExecutionPhase.TEST
        )
        reference, metadata = next(
            (ref, json.loads(read(ref)))
            for ref in phase.artifact_refs
            if ref.media_type == "application/json" and json.loads(read(ref)).get("phase") == "TEST"
        )
        unrelated = objects.put(b"unrelated passing command log", "text/plain")
        metadata["sandbox_runs"][-1]["command_evidence"][-1]["stdout_log"] = {
            "stream": "STDOUT",
            **{key: value for key, value in unrelated.to_snapshot().items() if key != "media_type"},
        }
        changed_ref = objects.put(metadata)
        changed_phase = replace(
            phase,
            artifact_refs=tuple(
                sorted(changed_ref if ref == reference else ref for ref in phase.artifact_refs)
            ),
        )
        observed = replace(
            observed,
            report=replace(
                observed.report,
                phase_results=tuple(
                    changed_phase if item.phase is phase.phase else item
                    for item in observed.report.phase_results
                ),
            ),
        )
    operation = replace(
        receipt.operation,
        result_json=operation_json(
            SqlAlchemyGovernedWebExecutionApiService._recorded_result(
                receipt.operation, observed.to_snapshot()
            )
        ),
    )
    changed = replace(journey, valid=replace(receipt, attempt=observed, operation=operation))
    with pytest.raises(WebValidationHarvestError, match=r"COMMAND_LOG|EXECUTED_PHASE"):
        verify_validation_harvest(
            replace(
                request,
                journeys=tuple(
                    changed if index == 1 else item for index, item in enumerate(request.journeys)
                ),
            ),
            read_artifact=read,
        )


@pytest.mark.parametrize("mutation", ["policy", "browser_harness"])
def test_phase_observations_match_exact_approved_runtime_inputs(complete_campaign, mutation):
    from orchestwin.web_execution.operation_governance import operation_json

    _, request, read = complete_campaign
    journey = request.journeys[0]
    receipt = journey.valid
    payload = receipt.operation.payload
    if mutation == "policy":
        payload["execution_policy"]["maximum_memory_mib"] += 1
    else:
        payload["browser_harness_sha256"] = "f" * 64
    operation = replace(receipt.operation, payload_json=operation_json(payload))
    changed = replace(
        journey,
        valid=replace(
            receipt,
            operation=operation,
            gate=replace(receipt.gate, artifact=operation.artifact),
            approval_event=replace(receipt.approval_event, artifact=operation.artifact),
        ),
    )
    with pytest.raises(WebValidationHarvestError, match=r"ATTEMPT_BINDING|BROWSER_BINDING"):
        verify_validation_harvest(
            replace(request, journeys=(changed, *request.journeys[1:])), read_artifact=read
        )
