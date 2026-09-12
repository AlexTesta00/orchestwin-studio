"""Derive platform validation records from resolved execution and approval receipts.

Receipts enter through trusted application/provider adapters. Hashes verify their
lineage and retained bytes; they are not external attestations by themselves.
Incomplete campaigns remain inspectable and cannot publish capability records.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree import ElementTree

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.artifacts.web_sources import WebSourceRevision
from orchestwin.sandbox.docker_runtime import HostProcessResult, HostProcessStatus
from orchestwin.sandbox.evidence import SandboxArtifactReference
from orchestwin.web_execution.attempts import WebExecutionAttempt
from orchestwin.web_execution.operation_governance import WebGovernedOperation
from orchestwin.web_execution.phase_browser_evidence import decode_browser_evidence
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.profile_registry import (
    create_sprint08_web_profile_registry,
    evaluate_sprint08_web_profile_promotions,
)
from orchestwin.web_execution.repair_records import web_repair_proposal_from_snapshot
from orchestwin.web_execution.reports import WebEvidenceReference
from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.targets import WebLanguageConfiguration
from orchestwin.web_execution.validation_ci import CiVerificationStatus, VerifiedCiObservation
from orchestwin.web_execution.validation_evidence import (
    WebProfilePromotionDecision,
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceCatalog,
    WebProfileValidationEvidenceKind,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    WebValidationEvidenceAppendStatus,
    canonical_web_validation_evidence,
)
from orchestwin.web_execution.verified_browser_runner import read_json
from orchestwin.workflow.gates import HumanGate, HumanGateEvent

_HASH = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._:/-][A-Za-z0-9]+)*")
_REF_KEYS = {"storage_key", "sha256_digest", "size_bytes", "media_type"}
_PHASES = tuple(WebExecutionPhase)
_PUBLICATION_LOCK = int.from_bytes(
    hashlib.sha256(b"orchestwin.web.validation.publication.v1").digest()[:8], "big", signed=True
)
_BOOTSTRAP_LOGS = {
    f"{action}_{kind}.{stream}.log"
    for action in ("BUILD", "PROBE")
    for kind in ("NODE", "PHP", "BROWSER")
    for stream in ("stdout", "stderr")
}


class WebValidationHarvestError(ValueError):
    """Safe verifier failure; raw evidence and private filesystem paths stay out."""


def _require(condition, code):
    if not condition:
        raise WebValidationHarvestError("WEB_VALIDATION_HARVEST_" + code)


@dataclass(frozen=True, slots=True)
class HarvestFixture:
    fixture_id: str
    profile_id: str
    profile_version: str
    language_configuration: WebLanguageConfiguration
    valid_source_tree_hash: str
    failure_source_tree_hash: str
    failure_phase: WebExecutionPhase
    fixture_bundle_hash: str
    expected_failure_marker: str = "LEVEL_D_NEGATIVE_CONTROL"


@dataclass(frozen=True, slots=True)
class HarvestAttempt:
    source: WebSourceRevision
    attempt: WebExecutionAttempt
    operation: WebGovernedOperation
    gate: HumanGate
    approval_event: HumanGateEvent
    browser_manifest: dict | None = None


@dataclass(frozen=True, slots=True)
class HarvestJourney:
    fixture_id: str
    valid: HarvestAttempt
    repeated: HarvestAttempt
    failed: HarvestAttempt
    repair_operation: WebGovernedOperation
    repair_gate: HumanGate
    repair_approval_event: HumanGateEvent
    rerun: HarvestAttempt


@dataclass(frozen=True, slots=True)
class ContractTestReceipt:
    argv: tuple[str, ...]
    result: HostProcessResult
    stdout_ref: WebEvidenceReference
    stderr_ref: WebEvidenceReference
    junit_ref: WebEvidenceReference
    required_test_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HarvestInputs:
    platform_commit: str
    recorded_at: datetime
    fixtures: tuple[HarvestFixture, ...]
    journeys: tuple[HarvestJourney, ...]
    runner_identities: tuple[WebPhaseRunnerIdentity, ...]
    bootstrap_manifest_ref: WebEvidenceReference
    contract_tests: ContractTestReceipt
    limitations_ref: WebEvidenceReference
    bootstrap_artifacts: tuple[WebEvidenceReference, ...] = ()
    ci_observation: VerifiedCiObservation | None = None


@dataclass(frozen=True, slots=True)
class VerifiedWebValidationBatch:
    records: tuple[WebProfileValidationEvidence, ...]
    artifacts: tuple[tuple[WebEvidenceReference, bytes], ...]
    promotion_decisions: tuple[WebProfilePromotionDecision, ...]
    content_hash: str
    inputs: HarvestInputs = field(repr=False)

    @property
    def is_complete(self):
        return len(self.promotion_decisions) == 5 and all(
            decision.is_eligible for decision in self.promotion_decisions
        )


@dataclass(frozen=True, slots=True)
class WebValidationPublication:
    content_hash: str
    appended: int
    already_present: int


class _Artifacts:
    def __init__(self, reader):
        self.reader = reader
        self.cache = {}
        self.references = {}

    def read(self, reference, *, media_type=None):
        if isinstance(reference, dict):
            _require(set(reference) == _REF_KEYS, "ARTIFACT_REFERENCE_INVALID")
            reference = WebEvidenceReference(**reference)
        _require(isinstance(reference, WebEvidenceReference), "ARTIFACT_REFERENCE_INVALID")
        digest = reference.sha256_digest
        _require(
            reference.storage_key == f"sha256/{digest[:2]}/{digest}"
            and type(reference.size_bytes) is int
            and 0 <= reference.size_bytes <= 32 * 1024 * 1024
            and (media_type is None or reference.media_type == media_type),
            "ARTIFACT_REFERENCE_INVALID",
        )
        if reference.storage_key not in self.cache:
            try:
                data = self.reader(reference)
            except (OSError, KeyError, ValueError, TypeError):
                raise WebValidationHarvestError("WEB_VALIDATION_HARVEST_ARTIFACT_MISSING") from None
            _require(isinstance(data, bytes), "ARTIFACT_BYTES_REQUIRED")
            _require(hashlib.sha256(data).hexdigest() == digest, "ARTIFACT_HASH_MISMATCH")
            _require(
                len(self.cache) < 10_000
                and sum(map(len, self.cache.values())) + len(data) <= 512 * 1024 * 1024,
                "ARTIFACT_BUDGET_EXCEEDED",
            )
            self.cache[reference.storage_key] = data
        data = self.cache[reference.storage_key]
        _require(len(data) == reference.size_bytes, "ARTIFACT_SIZE_MISMATCH")
        self.references[(reference.storage_key, reference.media_type)] = reference
        return data

    def json(self, reference):
        value = read_json(self.read(reference, media_type="application/json"))
        _require(isinstance(value, dict), "ARTIFACT_JSON_INVALID")
        return value

    def nested(self, value):
        if isinstance(value, dict):
            if value.keys() >= _REF_KEYS:
                self.read({key: value[key] for key in _REF_KEYS})
            else:
                for item in value.values():
                    self.nested(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.nested(item)

    def store_artifact(self, *, run_id, command_id, normalized_path, content, media_type):
        reference = _reference(content, media_type)
        _require(self.read(reference) == content, "BROWSER_ARTIFACT_MISMATCH")
        return SandboxArtifactReference(
            normalized_path,
            reference.sha256_digest,
            len(content),
            reference.storage_key,
            media_type,
        )


def _reference(data, media_type="application/json"):
    digest = hashlib.sha256(data).hexdigest()
    return WebEvidenceReference(f"sha256/{digest[:2]}/{digest}", digest, len(data), media_type)


def _hashed(value, code):
    _require(isinstance(value, dict), code)
    _require(
        value.get("content_hash")
        == content_hash({key: item for key, item in value.items() if key != "content_hash"}),
        code,
    )


def _fixture_map(request, scopes):
    expected = {
        (scope.profile_id, scope.profile_version, configuration)
        for scope in scopes
        for configuration in scope.language_configurations
    }
    observed = set()
    fixtures = {}
    for fixture in request.fixtures:
        _require(isinstance(fixture, HarvestFixture), "FIXTURE_INVALID")
        _require(
            _ID.fullmatch(fixture.fixture_id) and fixture.fixture_id not in fixtures,
            "FIXTURE_ID_INVALID",
        )
        key = (fixture.profile_id, fixture.profile_version, fixture.language_configuration)
        _require(key in expected and key not in observed, "FIXTURE_CONFIGURATION_INVALID")
        _require(
            all(
                _HASH.fullmatch(value)
                for value in (
                    fixture.valid_source_tree_hash,
                    fixture.failure_source_tree_hash,
                    fixture.fixture_bundle_hash,
                )
            )
            and fixture.valid_source_tree_hash != fixture.failure_source_tree_hash
            and isinstance(fixture.failure_phase, WebExecutionPhase)
            and isinstance(fixture.expected_failure_marker, str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", fixture.expected_failure_marker)
            and fixture.failure_phase
            not in {WebExecutionPhase.VALIDATE, WebExecutionPhase.COLLECT_ARTIFACTS},
            "FIXTURE_BINDING_INVALID",
        )
        fixtures[fixture.fixture_id] = fixture
        observed.add(key)
    _require(observed == expected, "FIXTURE_COVERAGE_INCOMPLETE")
    return fixtures


def _bootstrap(request, artifacts):
    manifest = artifacts.json(request.bootstrap_manifest_ref)
    _hashed(manifest, "BOOTSTRAP_HASH_MISMATCH")
    _require(
        manifest.get("schema_version") == 2
        and manifest.get("report_type") == "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE"
        and manifest.get("status") == "IMAGES_BUILT_PROBES_RECORDED"
        and all(
            manifest.get(flag) is False
            for flag in ("level_d_validated", "formal_run_started", "browser_automation_verified")
        )
        and re.fullmatch(r"[0-9a-f]{40}", manifest.get("platform_commit", "")),
        "BOOTSTRAP_NOT_OBSERVED",
    )
    environment = manifest.get("environment")
    _require(
        isinstance(environment, dict)
        and environment.get("platform") == "linux/amd64"
        and environment.get("builder_driver") == "docker"
        and manifest.get("environment_hash") == content_hash(environment),
        "BOOTSTRAP_ENVIRONMENT_INVALID",
    )
    identities = {identity.kind: identity for identity in request.runner_identities}
    _require(
        len(request.runner_identities) == 3 and set(identities) == {"NODE", "PHP", "BROWSER"},
        "BOOTSTRAP_IDENTITIES_INVALID",
    )
    runners = manifest.get("runners")
    _require(isinstance(runners, list) and len(runners) == 3, "BOOTSTRAP_RUNNERS_INVALID")
    _require({item["kind"] for item in runners} == set(identities), "BOOTSTRAP_RUNNERS_INVALID")
    for item in runners:
        identity = identities[item["kind"]]
        _require(
            identity.bootstrap_manifest_hash == manifest["content_hash"]
            and identity.image_id == item["image_id"]
            and identity.recipe_content_hash == item["recipe_content_hash"]
            and item.get("cleanup_confirmed") is True,
            "BOOTSTRAP_IDENTITY_MISMATCH",
        )
    logs = manifest.get("artifacts")
    _require(
        isinstance(logs, list)
        and len(logs) == 12
        and {item["path"] for item in logs} == _BOOTSTRAP_LOGS,
        "BOOTSTRAP_LOGS_INCOMPLETE",
    )
    refs = {item.sha256_digest: item for item in request.bootstrap_artifacts}
    _require(bool(refs), "BOOTSTRAP_LOGS_INCOMPLETE")
    for log in logs:
        reference = refs.get(log["sha256"])
        _require(
            reference is not None and reference.size_bytes == log["size_bytes"],
            "BOOTSTRAP_LOGS_INCOMPLETE",
        )
        artifacts.read(reference, media_type="text/plain")
    return identities, manifest


def _contract_tests(receipt, artifacts):
    _require(isinstance(receipt, ContractTestReceipt), "CONTRACT_TEST_RECEIPT_INVALID")
    _require(
        len(receipt.argv) >= 4
        and receipt.argv[1:3] == ("-m", "pytest")
        and any(value.startswith("--junitxml") for value in receipt.argv)
        and isinstance(receipt.result, HostProcessResult)
        and receipt.result.status is HostProcessStatus.COMPLETED
        and receipt.result.exit_code == 0,
        "CONTRACT_TEST_NOT_COMPLETED",
    )
    _require(
        artifacts.read(receipt.stdout_ref, media_type="text/plain") == receipt.result.stdout
        and artifacts.read(receipt.stderr_ref, media_type="text/plain") == receipt.result.stderr,
        "CONTRACT_TEST_LOG_MISMATCH",
    )
    raw = artifacts.read(receipt.junit_ref)
    _require(len(raw) <= 2 * 1024 * 1024 and b"<!" not in raw, "CONTRACT_TEST_XML_INVALID")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise WebValidationHarvestError(
            "WEB_VALIDATION_HARVEST_CONTRACT_TEST_XML_INVALID"
        ) from None
    _require(root.tag in {"testsuite", "testsuites"}, "CONTRACT_TEST_XML_INVALID")
    cases = list(root.iter("testcase"))
    _require(8 <= len(cases) <= 10000, "CONTRACT_TEST_COVERAGE_INCOMPLETE")
    ids = [f"{case.get('classname', '')}.{case.get('name', '')}" for case in cases]
    required = receipt.required_test_ids
    _require(
        len(required) >= 8
        and len(set(required)) == len(required)
        and len(set(ids)) == len(ids)
        and set(required) <= set(ids)
        and not any(
            case.find(name) is not None
            for case in cases
            for name in ("failure", "error", "skipped")
        ),
        "CONTRACT_TEST_COVERAGE_INCOMPLETE",
    )
    for suite in root.iter("testsuite"):
        _require(
            int(suite.get("tests", "-1")) == len(list(suite.iter("testcase")))
            and all(int(suite.get(name, "0")) == 0 for name in ("failures", "errors", "skipped")),
            "CONTRACT_TEST_COUNTS_INCONSISTENT",
        )
    return {
        "argv": list(receipt.argv),
        "stdout_ref": receipt.stdout_ref.to_snapshot(),
        "stderr_ref": receipt.stderr_ref.to_snapshot(),
        "junit_ref": receipt.junit_ref.to_snapshot(),
        "observed_test_ids": sorted(ids),
        "required_test_ids": sorted(required),
    }


def _approval(operation, gate, event):
    _require(
        isinstance(operation, WebGovernedOperation)
        and isinstance(gate, HumanGate)
        and isinstance(event, HumanGateEvent)
        and operation.state.value == "COMPLETED"
        and operation.started_at is not None
        and gate.id == operation.gate_id
        and gate.artifact == operation.artifact
        and gate.project_id == operation.project_id
        and gate.owner_user_id == operation.owner_user_id
        and gate.status.value in {"APPROVED", "STALE"}
        and event.gate_id == gate.id
        and event.artifact == operation.artifact
        and event.kind.value == "APPROVE"
        and event.resulting_status.value == "APPROVED"
        and event.previous_status.value == "PENDING_APPROVAL"
        and event.actor_user_id == operation.owner_user_id
        and event.sequence_number <= gate.event_sequence
        and operation.created_at <= event.occurred_at <= operation.started_at,
        "APPROVAL_BINDING_INVALID",
    )


def _phase_metadata(receipt, phase, planned, identity, contract, artifacts):
    candidates = []
    for reference in (*phase.stdout_refs, *phase.stderr_refs, *phase.artifact_refs):
        artifacts.read(reference)
    for reference in phase.artifact_refs:
        if reference.media_type == "application/json":
            value = artifacts.json(reference)
            if value.get("phase") == phase.phase.value:
                candidates.append(value)
    _require(len(candidates) == 1, "PHASE_OBSERVATION_MISSING")
    data = candidates[0]
    _require(
        type(data.get("schema_version")) is int
        and data["schema_version"] == 1
        and data.get("execution_attempt_id") == str(receipt.attempt.id)
        and data.get("contract_hash") == contract["content_hash"]
        and data.get("source_revision_content_hash") == receipt.source.content_hash
        and data.get("source_tree_hash") == receipt.source.source_tree_hash
        and data.get("image_id") == identity.image_id
        and data.get("bootstrap_manifest_hash") == identity.bootstrap_manifest_hash
        and data.get("recipe_content_hash") == identity.recipe_content_hash
        and data.get("policy_hash") == receipt.attempt.report.policy_content_hash
        and data.get("status") == phase.status.value
        and data.get("phase_plan") == planned
        and data.get("level_d_validated") is False
        and datetime.fromisoformat(data["started_at"]) == phase.started_at
        and datetime.fromisoformat(data["completed_at"]) == phase.completed_at,
        "PHASE_OBSERVATION_BINDING_INVALID",
    )
    artifacts.nested(data)
    if phase.phase is WebExecutionPhase.COLLECT_ARTIFACTS:
        _require(data["observations"].get("cleanup_confirmed") is True, "CLEANUP_NOT_CONFIRMED")
        for process in data["observations"].get("processes", []):
            _require(
                process.get("application_exit_observed") is True
                and process.get("terminated_by_controller") is True
                and type(process.get("exit_code")) is int,
                "PROCESS_EXIT_NOT_OBSERVED",
            )
    if phase.phase is WebExecutionPhase.HEALTH_CHECK and phase.status.value == "PASSED":
        observed = data["observations"].get("health_checks")
        _require(
            isinstance(observed, list) and len(observed) == len(contract["health_checks"]) > 0,
            "HEALTH_OBSERVATION_MISSING",
        )
        for expected, actual in zip(contract["health_checks"], observed, strict=True):
            _require(
                actual.get("spec") == expected
                and actual.get("status") == "HEALTHY"
                and actual.get("attempts")
                and actual["attempts"][-1]["status_code"] in expected["expected_status_codes"],
                "HEALTH_OBSERVATION_INVALID",
            )
    if phase.phase is WebExecutionPhase.RUN:
        observation = data.get("observations", {})
        _require(
            phase.status.value == "PASSED"
            and isinstance(observation.get("processes_started"), list)
            and len(observation["processes_started"])
            == sum(len(plan["commands"]) for plan in planned["command_plans"])
            and observation.get("application_exit_observed") is False
            and phase.exit_codes == ()
            and phase.command_plan_hashes
            == tuple(sorted(plan["content_hash"] for plan in planned["command_plans"])),
            "PROCESS_START_NOT_OBSERVED",
        )
    elif planned["execution_kind"] == "COMMAND_PLANS":
        _commands_observed(phase, planned, data, identity, artifacts)
    return data


def _commands_observed(phase, planned, data, identity, artifacts):
    runs, plans = data.get("sandbox_runs"), planned["command_plans"]
    _require(isinstance(runs, list) and 0 < len(runs) <= len(plans), "COMMAND_OBSERVATION_MISSING")
    success = phase.status.value == "PASSED"
    _require(
        not success
        or (
            len(runs) == len(plans)
            and not data.get("runtime_failures")
            and data.get("artifact_failure") is None
        ),
        "COMMAND_PHASE_INCOMPLETE",
    )
    exits = []
    streams = {"stdout": set(), "stderr": set()}
    for index, (plan, run) in enumerate(zip(plans, runs, strict=False)):
        _hashed(plan, "COMMAND_PLAN_HASH_MISMATCH")
        commands = run.get("command_evidence")
        _require(
            run.get("plan_id") == plan["plan_id"]
            and run.get("plan_content_hash") == plan["content_hash"]
            and run.get("image_reference") == identity.image_id
            and run.get("runtime_reference") == "docker.web.phase.v1"
            and isinstance(commands, list)
            and 0 < len(commands) <= len(plan["commands"])
            and run.get("planned_command_ids")
            == [command["command_id"] for command in plan["commands"]],
            "COMMAND_BINDING_INVALID",
        )
        _require(
            not (success or index < len(runs) - 1)
            or (len(commands) == len(plan["commands"]) and run.get("status") == "SUCCEEDED"),
            "COMMAND_PREFIX_INVALID",
        )
        for command_index, (expected, actual) in enumerate(
            zip(plan["commands"], commands, strict=False)
        ):
            _require(
                actual.get("command_id") == expected["command_id"]
                and type(actual.get("exit_code")) is int,
                "COMMAND_EXIT_NOT_OBSERVED",
            )
            exits.append(actual["exit_code"])
            must_pass = success or index < len(runs) - 1 or command_index < len(commands) - 1
            _require(
                not must_pass
                or (
                    actual.get("status") == "SUCCEEDED"
                    and actual["exit_code"] in expected["expected_exit_codes"]
                ),
                "COMMAND_RESULT_INCONSISTENT",
            )
            _require(
                must_pass
                or (
                    run.get("status") == "FAILED"
                    and actual.get("status") == "FAILED"
                    and actual["exit_code"] not in expected["expected_exit_codes"]
                ),
                "COMMAND_FAILURE_NOT_OBSERVED",
            )
            for stream, references in streams.items():
                log = actual[f"{stream}_log"]
                _require(
                    set(log) == {"stream", "sha256_digest", "size_bytes", "storage_key"}
                    and log["stream"] == stream.upper(),
                    "COMMAND_LOG_BINDING_INVALID",
                )
                reference = WebEvidenceReference(
                    **{key: value for key, value in log.items() if key != "stream"},
                    media_type="text/plain",
                )
                artifacts.read(reference)
                references.add(reference)
    _require(tuple(exits) == phase.exit_codes, "COMMAND_EXITS_MISMATCH")
    _require(
        tuple(sorted(run["plan_content_hash"] for run in runs)) == phase.command_plan_hashes,
        "COMMAND_PLAN_COVERAGE_MISMATCH",
    )
    _require(
        streams["stdout"] == set(phase.stdout_refs) and streams["stderr"] == set(phase.stderr_refs),
        "COMMAND_LOG_BINDING_INVALID",
    )


def _browser(receipt, phase, contract, browser, artifacts):
    manifest = receipt.browser_manifest
    _require(isinstance(manifest, dict), "BROWSER_MANIFEST_MISSING")
    manifest_data = canonical_bytes(manifest)
    _require(
        any(
            artifacts.read(ref) == manifest_data
            for ref in phase.artifact_refs
            if ref.media_type == "application/json"
        ),
        "BROWSER_MANIFEST_NOT_RETAINED",
    )
    artifacts.nested(manifest)
    _require(
        manifest.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE"
        and manifest.get("execution_attempt_id") == str(receipt.attempt.id)
        and manifest.get("source_revision_content_hash") == receipt.source.content_hash
        and manifest.get("source_tree_hash") == receipt.source.source_tree_hash
        and manifest.get("contract_content_hash") == contract["content_hash"]
        and manifest.get("browser_image_id") == browser.image_id
        and manifest.get("bootstrap_manifest_hash") == browser.bootstrap_manifest_hash
        and manifest.get("recipe_content_hash") == browser.recipe_content_hash
        and manifest.get("status") == phase.status.value
        and manifest.get("harness_sha256") == receipt.operation.payload["browser_harness_sha256"]
        and manifest.get("seccomp_sha256") == receipt.operation.payload["browser_seccomp_sha256"]
        and datetime.fromisoformat(manifest["started_at"]) == phase.started_at
        and datetime.fromisoformat(manifest["completed_at"]) == phase.completed_at
        and manifest.get("level_d_validated") is False
        and manifest.get("formal_run_started") is False,
        "BROWSER_BINDING_INVALID",
    )
    job = manifest["job"]
    _require(
        job["request"] == contract["browser_evidence_request"]
        and job["execution_attempt_id"] == str(receipt.attempt.id)
        and job["harness_sha256"] == manifest["harness_sha256"]
        and job["interactions"] == receipt.operation.payload["browser_interactions"],
        "BROWSER_REQUEST_MISMATCH",
    )
    execute = [item for item in manifest["operations"] if item["label"] == "EXECUTE"]
    _require(len(execute) == 1 and execute[0]["status"] == "COMPLETED", "BROWSER_EXECUTION_MISSING")
    decoded = decode_browser_evidence(
        artifacts.read(execute[0]["stdout_ref"]),
        job=job,
        store=artifacts,
        run_id=receipt.attempt.id,
    )
    _require(
        decoded.bundle.to_snapshot() == manifest["bundle"]
        and decoded.metadata == manifest["browser_evidence"]
        and decoded.findings == phase.findings,
        "BROWSER_DECODE_MISMATCH",
    )
    if phase.status.value == "PASSED":
        _require(
            not decoded.failed
            and manifest.get("cleanup_confirmed") is True
            and manifest.get("process_exit_code") == 0
            and phase.exit_codes == (0,),
            "BROWSER_NOT_PASSING",
        )
    return decoded


def _attempt(receipt, fixture, identities, artifacts, *, success):
    _require(
        isinstance(receipt, HarvestAttempt)
        and isinstance(receipt.source, WebSourceRevision)
        and isinstance(receipt.attempt, WebExecutionAttempt),
        "ATTEMPT_INVALID",
    )
    source, attempt, operation = receipt.source, receipt.attempt, receipt.operation
    _approval(operation, receipt.gate, receipt.approval_event)
    payload = operation.payload
    contract = payload["contract"]
    for value in (contract, contract["validation"], contract["execution_plan"]):
        _hashed(value, "CONTRACT_HASH_MISMATCH")
    scope = next(
        profile.scope
        for profile in create_sprint08_web_profile_registry().profiles
        if profile.scope.profile_id == fixture.profile_id
    )
    identity = identities["PHP" if scope.target.value == "WEB_PHP" else "NODE"]
    browser = identities["BROWSER"] if scope.requires_browser_evidence else None
    _require(
        operation.kind.value == "EXECUTION"
        and operation.id == attempt.id
        and operation.source_revision_id == source.id
        and operation.project_id == source.project_id == attempt.project_id
        and operation.owner_user_id == source.created_by_user_id == attempt.created_by_user_id
        and attempt.source_revision == source.reference
        and payload.get("purpose") == "PROFILE_VALIDATION"
        and payload.get("source_revision") == source.reference.to_snapshot()
        and source.validation_scope_hash == scope.content_hash
        and content_hash(payload["execution_policy"]) == attempt.report.policy_content_hash
        and payload["command"]["policy_content_hash"] == attempt.report.policy_content_hash
        and contract["source_revision_content_hash"] == source.content_hash
        and contract["source_tree_hash"] == source.source_tree_hash
        and contract["validation"]["selection"] == source.target_selection.to_snapshot()
        and source.target_selection.language_configuration == fixture.language_configuration
        and source.target_selection.target == scope.target
        and contract["validation"]["validation_scope_hash"] == scope.content_hash
        and contract["validation"]["profile_id"] == fixture.profile_id
        and contract["validation"]["profile_version"] == fixture.profile_version
        and attempt.profile_validation_content_hash == contract["validation"]["content_hash"]
        and attempt.execution_plan_content_hash == contract["execution_plan"]["content_hash"]
        and attempt.report.profile_id == fixture.profile_id
        and attempt.report.profile_version == fixture.profile_version
        and attempt.report.runner_image_digest == identity.image_id.removeprefix("sha256:")
        and contract["runners"]
        == {
            "execution_runner_image_digest": identity.image_id.removeprefix("sha256:"),
            "browser_runner_image_digest": None
            if browser is None
            else browser.image_id.removeprefix("sha256:"),
        }
        and operation.result
        == {
            "execution_id": str(attempt.id),
            "attempt_content_hash": attempt.content_hash,
            "report_status": attempt.report.status.value,
        }
        and operation.started_at
        <= attempt.started_at
        <= attempt.completed_at
        <= operation.finished_at,
        "ATTEMPT_BINDING_INVALID",
    )
    _require(
        attempt.report.status.value == ("PASSED" if success else "FAILED"),
        "ATTEMPT_OUTCOME_INVALID",
    )
    _require(
        attempt.executed_phases
        == tuple(
            phase.phase
            for phase in attempt.report.phase_results
            if phase.status.value not in {"SKIPPED", "NOT_RUN"}
        ),
        "EXECUTED_PHASE_INVENTORY_INVALID",
    )
    expected = contract["execution_plan"]["phases"]
    _require(
        [item["phase"] for item in expected] == [phase.value for phase in _PHASES],
        "PHASE_PLAN_INCOMPLETE",
    )
    failed_seen = False
    for planned, phase in zip(expected, attempt.report.phase_results, strict=True):
        if not success and phase.phase is fixture.failure_phase:
            _require(
                phase.status.value == "FAILED" and phase.is_failure, "EXPECTED_FAILURE_NOT_OBSERVED"
            )
            failed_seen = True
        elif failed_seen and phase.phase is not WebExecutionPhase.COLLECT_ARTIFACTS:
            _require(phase.status.value == "NOT_RUN", "FAILURE_STOP_PREFIX_INVALID")
            continue
        elif planned["execution_kind"] == "NO_OP":
            _require(
                phase.status.value == "SKIPPED"
                and not phase.exit_codes
                and not phase.artifact_refs,
                "NO_OP_OBSERVATION_INVALID",
            )
            continue
        else:
            _require(phase.status.value == "PASSED" and not phase.findings, "PHASE_NOT_PASSING")
        if phase.phase is WebExecutionPhase.BROWSER_EVIDENCE:
            decoded = _browser(receipt, phase, contract, browser, artifacts)
        else:
            _phase_metadata(receipt, phase, planned, identity, contract, artifacts)
        if not success and phase.phase is fixture.failure_phase:
            marker = (
                any(
                    message.level.value == "ERROR"
                    and fixture.expected_failure_marker in message.message
                    for route in decoded.bundle.routes
                    for message in route.console_messages
                )
                if phase.phase is WebExecutionPhase.BROWSER_EVIDENCE
                else any(
                    fixture.expected_failure_marker.encode("ascii") in artifacts.read(reference)
                    for reference in (*phase.stdout_refs, *phase.stderr_refs)
                )
            )
            _require(marker, "EXPECTED_FAILURE_MARKER_MISSING")
    _require(success or failed_seen, "EXPECTED_FAILURE_NOT_OBSERVED")
    return {
        "source": source.to_snapshot(),
        "attempt": attempt.to_snapshot(),
        "operation": operation.to_snapshot(),
        "approval_event": _event_snapshot(receipt.approval_event),
    }


def _event_snapshot(event):
    return {
        "id": str(event.id),
        "gate_id": str(event.gate_id),
        "sequence_number": event.sequence_number,
        "kind": event.kind.value,
        "previous_status": event.previous_status.value,
        "resulting_status": event.resulting_status.value,
        "artifact": {
            "project_id": str(event.artifact.project_id),
            "gate_type": event.artifact.gate_type.value,
            "artifact_id": str(event.artifact.artifact_id),
            "version": event.artifact.version,
            "content_hash": event.artifact.content_hash,
        },
        "occurred_at": event.occurred_at.isoformat(),
        "actor_user_id": str(event.actor_user_id),
    }


def _journey(journey, fixture, identities, artifacts):
    receipts = {
        name: _attempt(
            getattr(journey, name), fixture, identities, artifacts, success=name != "failed"
        )
        for name in ("valid", "repeated", "failed", "rerun")
    }
    valid, repeated, failed, rerun = journey.valid, journey.repeated, journey.failed, journey.rerun
    _require(
        valid.source.source_tree_hash
        == repeated.source.source_tree_hash
        == fixture.valid_source_tree_hash
        and failed.source.source_tree_hash == fixture.failure_source_tree_hash
        and rerun.source.source_tree_hash == fixture.valid_source_tree_hash
        and len({valid.attempt.project_id, repeated.attempt.project_id, failed.attempt.project_id})
        == 3
        and valid.attempt.attempt_number
        == repeated.attempt.attempt_number
        == failed.attempt.attempt_number
        == 1
        and rerun.attempt.project_id == failed.attempt.project_id
        and rerun.attempt.previous_attempt_id == failed.attempt.id
        and rerun.attempt.attempt_number == 2
        and rerun.attempt.trigger.value == "REPAIR_RERUN"
        and rerun.source.based_on == failed.source.reference,
        "JOURNEY_LINEAGE_INVALID",
    )
    operation = journey.repair_operation
    _approval(operation, journey.repair_gate, journey.repair_approval_event)
    payload = operation.payload
    proposal = web_repair_proposal_from_snapshot(payload["proposal"])
    _require(
        operation.kind.value == "REPAIR"
        and operation.project_id == failed.attempt.project_id
        and operation.owner_user_id == failed.attempt.created_by_user_id
        and operation.source_revision_id == failed.source.id
        and payload["execution_id"] == str(failed.attempt.id)
        and payload["execution_content_hash"] == failed.attempt.content_hash
        and proposal.base_revision == failed.source.reference
        and proposal.failure_signature in failed.attempt.report.failure_signatures()
        and rerun.source.related_failure_signature == proposal.failure_signature.digest
        and operation.result["source_revision"] == rerun.source.to_snapshot()
        and operation.result["execution_performed"] is False
        and failed.attempt.completed_at
        <= operation.started_at
        <= operation.finished_at
        <= rerun.attempt.started_at,
        "REPAIR_BINDING_INVALID",
    )
    receipts["repair"] = {
        "operation": operation.to_snapshot(),
        "approval_event": _event_snapshot(journey.repair_approval_event),
    }
    return receipts


def verify_validation_harvest(
    request: HarvestInputs, *, read_artifact: Callable[[WebEvidenceReference], bytes]
) -> VerifiedWebValidationBatch:
    """Resolve every proof and derive records; missing observations never become passes."""
    try:
        return _verify(request, read_artifact)
    except WebValidationHarvestError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration, RecursionError):
        raise WebValidationHarvestError("WEB_VALIDATION_HARVEST_INPUT_INVALID") from None


def _verify(request, reader):
    _require(
        isinstance(request, HarvestInputs)
        and re.fullmatch(r"[0-9a-f]{40}", request.platform_commit),
        "CAMPAIGN_IDENTITY_INVALID",
    )
    _require(
        isinstance(request.recorded_at, datetime) and request.recorded_at.utcoffset() is not None,
        "CAMPAIGN_TIMESTAMP_INVALID",
    )
    scopes = tuple(profile.scope for profile in create_sprint08_web_profile_registry().profiles)
    fixtures = _fixture_map(request, scopes)
    artifacts = _Artifacts(reader)
    identities, bootstrap = _bootstrap(request, artifacts)
    tests = _contract_tests(request.contract_tests, artifacts)
    limits = artifacts.json(request.limitations_ref)
    _require(
        limits
        == {
            "schema_version": 1,
            "platform_commit": request.platform_commit,
            "profiles": [scope.to_snapshot() for scope in scopes],
        },
        "LIMITATIONS_SCOPE_MISMATCH",
    )
    journeys = {}
    for journey in request.journeys:
        _require(
            isinstance(journey, HarvestJourney)
            and journey.fixture_id in fixtures
            and journey.fixture_id not in journeys,
            "JOURNEY_FIXTURE_INVALID",
        )
        journeys[journey.fixture_id] = _journey(
            journey, fixtures[journey.fixture_id], identities, artifacts
        )
    ci = request.ci_observation
    ci_proof = None
    if ci is not None:
        _require(
            isinstance(ci, VerifiedCiObservation) and ci.commit == request.platform_commit,
            "CI_BINDING_INVALID",
        )
        for response in ci.responses:
            artifacts.read(_reference(response.body, "application/json"))
        if ci.status is CiVerificationStatus.PASSED:
            _require(
                ci.run_id is not None and ci.run_attempt is not None and ci.responses,
                "CI_PROVENANCE_MISSING",
            )
            ci_proof = ci.to_snapshot()
    records, generated = [], []

    def record(scope, kind, observation, configuration=None):
        runner = identities["PHP" if scope.target.value == "WEB_PHP" else "NODE"]
        browser = identities["BROWSER"] if scope.requires_browser_evidence else None
        proof = {
            "schema_version": 1,
            "kind": kind,
            "platform_commit": request.platform_commit,
            "baseline_scope": scope.to_snapshot(),
            "language_configuration": None
            if configuration is None
            else configuration.to_snapshot(),
            "bootstrap_manifest_ref": request.bootstrap_manifest_ref.to_snapshot(),
            "observation": observation,
        }
        body = canonical_bytes(proof)
        reference = _reference(body)
        generated.append((reference, body))
        records.append(
            WebProfileValidationEvidence(
                evidence_id=f"web-validation.{scope.profile_id}.{kind}.{reference.sha256_digest}",
                kind=WebProfileValidationEvidenceKind(kind),
                profile_id=scope.profile_id,
                profile_version=scope.profile_version,
                baseline_scope_hash=scope.content_hash,
                language_configuration=configuration,
                execution_runner_image_digest=runner.image_id.removeprefix("sha256:"),
                browser_runner_image_digest=None
                if browser is None
                else browser.image_id.removeprefix("sha256:"),
                artifact_content_hash=reference.sha256_digest,
                reference=f"web-validation:sha256:{reference.sha256_digest}",
                recorded_at=request.recorded_at.astimezone(UTC),
                passed=True,
            )
        )

    for scope in scopes:
        record(scope, "CONTRACT_TESTS", tests)
        record(
            scope,
            "RUNNER_BUILD",
            {
                "manifest": bootstrap,
                "logs": [reference.to_snapshot() for reference in request.bootstrap_artifacts],
            },
        )
        record(scope, "ENVIRONMENT_MANIFEST", bootstrap["environment"])
        record(
            scope, "KNOWN_LIMITATIONS", {"limitations_ref": request.limitations_ref.to_snapshot()}
        )
        if ci_proof is not None:
            record(scope, "CI_VERIFICATION", ci_proof)
        covered = [
            fixture
            for fixture in fixtures.values()
            if fixture.profile_id == scope.profile_id and fixture.fixture_id in journeys
        ]
        for fixture in covered:
            observed = journeys[fixture.fixture_id]
            common = {
                "fixture_id": fixture.fixture_id,
                "fixture_bundle_hash": fixture.fixture_bundle_hash,
            }
            record(
                scope,
                "VALID_FIXTURE_RUN",
                {**common, "valid": observed["valid"]},
                fixture.language_configuration,
            )
            record(
                scope,
                "FAILURE_REPAIR_RERUN",
                {
                    **common,
                    "failed": observed["failed"],
                    "repair": observed["repair"],
                    "rerun": observed["rerun"],
                },
                fixture.language_configuration,
            )
            if scope.requires_browser_evidence:
                record(
                    scope,
                    "BROWSER_EVIDENCE",
                    {**common, "valid": observed["valid"], "rerun": observed["rerun"]},
                    fixture.language_configuration,
                )
        if len(covered) == len(scope.language_configurations):
            record(
                scope,
                "REPRODUCIBILITY",
                [
                    {
                        "fixture_id": fixture.fixture_id,
                        "valid": journeys[fixture.fixture_id]["valid"],
                        "repeated": journeys[fixture.fixture_id]["repeated"],
                    }
                    for fixture in covered
                ],
            )
    ordered = canonical_web_validation_evidence(tuple(records))
    decisions = evaluate_sprint08_web_profile_promotions(
        WebProfileValidationEvidenceCatalog(ordered)
    )
    generated = tuple(sorted(generated, key=lambda item: item[0]))
    digest = content_hash(
        {
            "records": [record.to_snapshot() for record in ordered],
            "artifacts": [reference.to_snapshot() for reference, _ in generated],
        }
    )
    return VerifiedWebValidationBatch(ordered, generated, decisions, digest, request)


async def publish_validation_batch(batch, *, unit_of_work_factory, read_artifact):
    """Reverify retained proof bytes, then append one complete batch atomically."""
    _require(
        isinstance(batch, VerifiedWebValidationBatch) and batch.is_complete,
        "PUBLICATION_INCOMPLETE",
    )
    checked = verify_validation_harvest(batch.inputs, read_artifact=read_artifact)
    _require(
        checked == batch and checked.is_complete and len(batch.records) == 52,
        "PUBLICATION_BATCH_CHANGED",
    )
    artifacts = _Artifacts(read_artifact)
    for reference, body in batch.artifacts:
        _require(artifacts.read(reference) == body, "PUBLICATION_PROOF_MISSING")
    appended = present = 0
    async with unit_of_work_factory() as unit:
        # The lock uses the already-owned transaction/session, including pool size
        # one. Concurrent campaigns cannot both validate disjoint snapshots and
        # publish incompatible runner identities for the same profile version.
        session = getattr(unit, "_session", None)
        _require(isinstance(session, AsyncSession), "PUBLICATION_LOCK_UNAVAILABLE")
        await session.execute(sa.select(sa.func.pg_advisory_xact_lock(_PUBLICATION_LOCK)))
        for record in batch.records:
            status = await unit.evidence.append(record)
            if status is WebValidationEvidenceAppendStatus.APPENDED:
                appended += 1
            elif status is WebValidationEvidenceAppendStatus.ALREADY_PRESENT:
                present += 1
            else:
                raise WebValidationHarvestError("WEB_VALIDATION_HARVEST_PUBLICATION_CONFLICT")
        # Include all persisted history: a stale/conflicting record cannot be hidden
        # by publishing a selected successful campaign over the same version.
        history = await unit.evidence.history()
        decisions = evaluate_sprint08_web_profile_promotions(
            WebProfileValidationEvidenceCatalog(history)
        )
        _require(
            all(decision.is_eligible for decision in decisions), "PUBLICATION_HISTORY_CONFLICT"
        )
        await unit.commit()
    return WebValidationPublication(batch.content_hash, appended, present)
