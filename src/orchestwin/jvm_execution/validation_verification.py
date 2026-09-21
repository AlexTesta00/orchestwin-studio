"""Fail-closed verification of exported SQL campaign records and retained Docker bytes.

These are operator-collected observations, not signed third-party attestations.
No network access, runner execution or database mutation occurs while verifying.
"""

import hashlib
import io
from datetime import datetime
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree
from zipfile import ZipFile

from orchestwin.api.governed_jvm_context import GovernedJvmSettings, JvmExecutionBackend
from orchestwin.api.jvm_execution import JvmExecutionStartCommand
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
    JvmSourceRevisionReference,
)
from orchestwin.jvm_execution.attempt_persistence import _report
from orchestwin.jvm_execution.attempts import JvmExecutionAttempt, JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.dependency_network import INPUT_PATHS, PROBE_CHECKS, _load_manifest
from orchestwin.jvm_execution.operation_governance import (
    JvmGovernedOperation,
    JvmOperationKind,
    JvmOperationState,
    canonical_bytes,
    content_hash,
    operation_json,
    read_json,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.repair_records import jvm_repair_proposal_from_snapshot
from orchestwin.jvm_execution.source_policy import read_source_objects
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.jvm_execution.validation_fixtures import CASES, fixture_bundle, fixture_bytes
from orchestwin.jvm_execution.workspaces import portable_path, read_regular_file
from orchestwin.workflow.jvm_execution import JvmExecutionPurpose

PHASES = tuple(phase.value for phase in JvmExecutionPhase)
MAX_JSON = 16 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise ValueError(f"JVM_VALIDATION_{code}")


def read_document(path):
    return read_json(read_regular_file(Path(path).absolute(), maximum_bytes=MAX_JSON))


def verify_compiler_diagnostic(logs, target, files):
    marker = "ORCHESTWIN_INTENTIONAL_COMPILER_ERROR"
    if target.value == "JVM_KOTLIN":
        # Kotlin reports the location without echoing the offending source text.
        path = next(path for path in files if path.endswith("/Main.kt"))
        line = files[path].decode().splitlines().index(marker) + 1
        require(
            f"/workspace/{path}:{line}:1 Syntax error: Expecting a top level declaration." in logs
            and "> Task :compileKotlin FAILED" in logs,
            "EXPECTED_COMPILER_LOCATION_MISSING",
        )
    else:
        require(marker in logs, "EXPECTED_DIAGNOSTIC_MISSING")


def verified_bytes(root, reference):
    digest, size = reference["sha256_digest"], reference["size_bytes"]
    require(
        isinstance(digest, str)
        and len(digest) == 64
        and all(c in "0123456789abcdef" for c in digest)
        and type(size) is int
        and 0 <= size <= 128 * 1024 * 1024,
        "REFERENCE_INVALID",
    )
    require(reference["storage_key"] == f"sha256/{digest[:2]}/{digest}", "STORAGE_KEY_INVALID")
    data = read_regular_file(root / reference["storage_key"], maximum_bytes=size)
    require(len(data) == size and hashlib.sha256(data).hexdigest() == digest, "BYTES_MISMATCH")
    return data


def same(left, right, code):
    require(canonical_bytes(left) == canonical_bytes(right), code)


def reference_from_snapshot(value):
    return JvmSourceRevisionReference(
        **{
            **value,
            "revision_id": UUID(value["revision_id"]),
            "project_id": UUID(value["project_id"]),
        }
    )


def source_from_snapshot(value, target):
    source = JvmSourceRevision(
        **{
            key: value[key]
            for key in ("version_number", "validation_scope_hash", "related_failure_signature")
        },
        **{key: UUID(value[key]) for key in ("id", "project_id", "created_by_user_id")},
        based_on=None if value["based_on"] is None else reference_from_snapshot(value["based_on"]),
        target_selection=selection_for(target),
        origin=JvmSourceOrigin(value["origin"]),
        files=tuple(JvmSourceFileEntry(**item) for item in value["files"]),
        provenance_references=tuple(
            JvmSourceProvenanceReference(**{**item, "kind": JvmSourceProvenanceKind(item["kind"])})
            for item in value["provenance_references"]
        ),
        created_at=datetime.fromisoformat(value["created_at"]),
    )
    same(source.to_snapshot(), value, "SOURCE_SNAPSHOT_INVALID")
    return source


def attempt_from_snapshot(value):
    attempt = JvmExecutionAttempt(
        **{
            key: value[key]
            for key in (
                "attempt_number",
                "profile_id",
                "profile_version",
                "profile_validation_content_hash",
                "execution_plan_content_hash",
                "runner_id",
                "runner_version",
                "runner_image_digest",
                "policy_content_hash",
            )
        },
        **{key: UUID(value[key]) for key in ("id", "project_id", "created_by_user_id")},
        previous_attempt_id=None
        if value["previous_attempt_id"] is None
        else UUID(value["previous_attempt_id"]),
        source_revision=reference_from_snapshot(value["source_revision"]),
        trigger=JvmExecutionAttemptTrigger(value["trigger"]),
        executed_phases=tuple(JvmExecutionPhase(item) for item in value["executed_phases"]),
        report=_report(value["report"]),
        started_at=datetime.fromisoformat(value["started_at"]),
        completed_at=datetime.fromisoformat(value["completed_at"]),
    )
    same(attempt.to_snapshot(), value, "ATTEMPT_SNAPSHOT_INVALID")
    return attempt


def verified_operation(value, *, require_current=False, historical=False):
    operation = JvmGovernedOperation(
        **{
            key: UUID(value[key])
            for key in ("id", "project_id", "owner_user_id", "source_revision_id", "gate_id")
        },
        kind=JvmOperationKind(value["kind"]),
        state=JvmOperationState(value["state"]),
        payload_json=operation_json(value["payload"]),
        result_json=None if value["result"] is None else operation_json(value["result"]),
        **{
            key: None if value[key] is None else datetime.fromisoformat(value[key])
            for key in ("created_at", "started_at", "finished_at")
        },
    )
    same(
        operation.to_snapshot(),
        {key: item for key, item in value.items() if key not in {"gate", "gate_current"}},
        "OPERATION_SNAPSHOT_INVALID",
    )
    gate = value["gate"]
    if historical and gate["status"] == "STALE":
        require(
            not require_current
            and gate["id"] == value["gate_id"]
            and gate["type"] == "HIGH_IMPACT_OPERATION"
            and value["gate_current"] is False,
            "STALE_GATE_SNAPSHOT_INVALID",
        )
        return operation
    require(
        gate["status"] == "APPROVED"
        and gate["type"] == "HIGH_IMPACT_OPERATION"
        and gate["id"] == value["gate_id"]
        and gate["artifact_id"] == value["id"]
        and gate["artifact_content_hash"] == operation.content_hash
        and gate["event_sequence"] >= 2,
        "EXACT_GATE_APPROVAL_MISSING",
    )
    if require_current:
        require(
            gate["is_current"] is True and value["gate_current"] is True,
            "GATE_NOT_CURRENT_AT_EXECUTION",
        )
    return operation


def verify_gate_history(snapshot, events):
    """A superseded gate retains its earlier exact approval in immutable SQL events."""
    operation = verified_operation(snapshot, historical=True)
    gate = snapshot["gate"]
    history = sorted(
        (event for event in events if event["gate_id"] == gate["id"]),
        key=lambda event: event["sequence_number"],
    )
    require(
        len(history) == gate["event_sequence"] and len(history) in {2, 3}, "GATE_AUDIT_INCOMPLETE"
    )
    for index, event in enumerate(history, 1):
        require(
            event["sequence_number"] == index
            and event["project_id"] == str(operation.project_id)
            and event["gate_type"] == "HIGH_IMPACT_OPERATION"
            and event["artifact_version"] == 1,
            "GATE_AUDIT_BINDING_INVALID",
        )
    submitted, approved = history[:2]
    require(
        submitted["kind"] == "SUBMIT"
        and submitted["previous_status"] == "DRAFT"
        and submitted["resulting_status"] == approved["previous_status"] == "PENDING_APPROVAL"
        and approved["kind"] == "APPROVE"
        and approved["resulting_status"] == "APPROVED",
        "GATE_APPROVAL_TRANSITION_MISSING",
    )
    for event in (submitted, approved):
        require(
            event["artifact_id"] == str(operation.id)
            and event["artifact_hash"] == operation.content_hash
            and event["actor_user_id"] == str(operation.owner_user_id),
            "GATE_APPROVAL_ACTOR_OR_ARTIFACT_MISMATCH",
        )
    require(
        operation.started_at is not None
        and operation.finished_at is not None
        and operation.created_at
        <= datetime.fromisoformat(submitted["occurred_at"])
        <= datetime.fromisoformat(approved["occurred_at"])
        <= operation.started_at,
        "EXECUTION_PRECEDES_APPROVAL",
    )
    if len(history) == 3:
        superseded = history[2]
        require(
            superseded["kind"] == "ARTIFACT_SUPERSEDED"
            and superseded["previous_status"] == "APPROVED"
            and superseded["resulting_status"] == "STALE"
            and superseded["actor_user_id"] is None
            and datetime.fromisoformat(superseded["occurred_at"]) >= operation.finished_at,
            "GATE_SUPERSEDED_BEFORE_COMPLETION",
        )
    last = history[-1]
    require(
        last["resulting_status"] == gate["status"]
        and approved["artifact_id"] == gate["artifact_id"]
        and approved["artifact_hash"] == gate["artifact_content_hash"],
        "GATE_AUDIT_CURRENT_STATE_MISMATCH",
    )
    return operation


def junit_counts(documents):
    counts = dict(total=0, passed=0, failed=0, errors=0, skipped=0)
    identities = set()
    for data in documents:
        require(b"<!DOCTYPE" not in data and b"<!ENTITY" not in data, "UNSAFE_XML")
        root = ElementTree.fromstring(data)
        for case in root.iter("testcase"):
            identity = (case.get("classname"), case.get("name"))
            require(identity not in identities and identity[1], "DUPLICATE_TEST_CASE")
            identities.add(identity)
            status = next(
                (
                    name
                    for tag, name in (
                        ("failure", "failed"),
                        ("error", "errors"),
                        ("skipped", "skipped"),
                    )
                    if case.find(tag) is not None
                ),
                "passed",
            )
            counts[status] += 1
            counts["total"] += 1
    return counts


class CampaignVerifier:
    def __init__(self, *, root, repo_root, target, images, distribution_path):
        self.root, self.repo, self.target = (
            Path(root).absolute(),
            Path(repo_root).absolute(),
            target,
        )
        self.campaign = self.root / "campaign"
        self.evidence = self.campaign / "evidence"
        self.manifest = read_document(self.campaign / "campaign.json")
        self.export = read_document(self.root / "database-export.json")
        same(
            self.manifest["fixtures"],
            {target.value: fixture_bundle(self.repo, target)},
            "FIXTURE_DRIFT",
        )
        same(
            self.manifest["jobs"],
            [{"target": target.value, "case": case} for case in CASES],
            "JOBS_INVALID",
        )
        require(
            self.export["owner_id"] == self.manifest["owner_user_id"]
            and self.export["target"] == target.value,
            "SQL_EXPORT_OWNER_INVALID",
        )
        self.network = _load_manifest(self.root / "network/manifest.json")
        require(
            self.network["status"] == "READY" and self.network["probes"]["passed"] is True,
            "NETWORK_NOT_VERIFIED",
        )
        same(
            self.network["probes"]["checks"],
            dict.fromkeys(PROBE_CHECKS, True),
            "NETWORK_PROBES_INCOMPLETE",
        )
        require(
            {item["path"] for item in self.network["sources"]} == set(INPUT_PATHS),
            "NETWORK_INPUTS_INCOMPLETE",
        )
        for item in self.network["sources"]:
            data = read_regular_file(
                self.repo / portable_path(item["path"]), maximum_bytes=MAX_JSON
            )
            require(
                hashlib.sha256(data).hexdigest() == item["sha256"]
                and len(data) == item["size_bytes"],
                "NETWORK_SOURCE_DRIFT",
            )
        cleanup = read_document(self.root / "network-cleanup.json")
        require(
            cleanup["status"] == "REMOVED"
            and cleanup["source_manifest_hash"] == self.network["content_hash"]
            and not cleanup["cleanup_failures"]
            and not cleanup["resources"],
            "NETWORK_CLEANUP_MISSING",
        )
        self.backend = JvmExecutionBackend(
            config=GovernedJvmSettings(
                _env_file=None,
                enabled=True,
                repo_root=self.repo,
                workspaces_root=self.root / "workspaces",
                distribution_path=Path(distribution_path).absolute(),
                dependency_network_manifest=self.root / "network/manifest.json",
                dependency_network_manifest_hash=self.network["content_hash"],
                gradle_image_id=images["gradle"],
                sbt_image_id=images["sbt"],
                docker_context=self.network["environment"]["docker_context"],
            ),
            content_root=self.campaign / "sources",
            evidence_root=self.evidence,
        )
        self.sources, self.attempts, self.operations = {}, {}, {}
        for project in self.export["projects"]:
            for kind, destination in (
                ("sources", self.sources),
                ("attempts", self.attempts),
                ("operations", self.operations),
            ):
                for value in project[kind]:
                    require(
                        value["project_id"] == project["project_id"]
                        and value["id"] not in destination,
                        "SQL_EXPORT_DUPLICATE_OR_FOREIGN_ROW",
                    )
                    destination[value["id"]] = value
        require(
            len(self.export["projects"]) == 5
            and len(self.sources) == 6
            and len(self.attempts) == 7
            and len(self.operations) == 8,
            "SQL_EXPORT_INCOMPLETE",
        )
        if "gate_events" in self.export:
            events = self.export["gate_events"]
        else:
            event_export = read_document(self.root / "gate-events.json")
            require(
                event_export["owner_id"] == self.manifest["owner_user_id"]
                and event_export["target"] == target.value,
                "GATE_AUDIT_EXPORT_OWNER_MISMATCH",
            )
            events = event_export["events"]
        require(
            len({event["id"] for event in events}) == len(events)
            and {event["gate_id"] for event in events}
            == {operation["gate_id"] for operation in self.operations.values()},
            "GATE_AUDIT_DUPLICATE_OR_FOREIGN_EVENT",
        )
        for operation in self.operations.values():
            verify_gate_history(operation, events)
        for event in events:
            if event["kind"] == "ARTIFACT_SUPERSEDED":
                successor = self.operations.get(event["artifact_id"])
                require(
                    successor is not None
                    and successor["content_hash"] == event["artifact_hash"]
                    and successor["project_id"] == event["project_id"],
                    "GATE_SUCCESSOR_NOT_PERSISTED",
                )
        self.container_ids, self.observations = set(), {}

    def verify_attempt(self, case, step, *, expected_failure=None):
        directory = self.campaign / self.target.value / case / step
        value = read_document(directory / "attempt.json")
        same(value, self.attempts[value["id"]], "ATTEMPT_NOT_PERSISTED")
        attempt = attempt_from_snapshot(value)
        source = source_from_snapshot(
            self.sources[str(attempt.source_revision.revision_id)], self.target
        )
        require(
            source.created_by_user_id
            == attempt.created_by_user_id
            == UUID(self.manifest["owner_user_id"]),
            "OWNER_MISMATCH",
        )
        expected_case = "positive" if step == "rerun" else case
        require(
            read_source_objects(source, self.backend.content_root)
            == fixture_bytes(self.repo, self.target, expected_case),
            "SOURCE_FIXTURE_MISMATCH",
        )
        approved = read_document(directory / "approved.json")
        approved_operation = verified_operation(approved, require_current=True)
        operation_snapshot = read_document(directory / "terminal.json")
        operation = verified_operation(operation_snapshot)
        persisted_operation = verified_operation(
            self.operations[str(operation.id)], historical=True
        )
        same(operation.to_snapshot(), persisted_operation.to_snapshot(), "OPERATION_NOT_PERSISTED")
        require(
            operation.state is JvmOperationState.COMPLETED
            and operation.id == attempt.id
            and operation.content_hash == approved_operation.content_hash,
            "OPERATION_NOT_COMPLETED",
        )
        previous = (
            None
            if attempt.previous_attempt_id is None
            else attempt_from_snapshot(self.attempts[str(attempt.previous_attempt_id)])
        )
        command = operation.payload["command"]
        prepared = self.backend.prepare(
            source,
            command=JvmExecutionStartCommand(
                **{
                    key: command[key]
                    for key in (
                        "profile_id",
                        "profile_version",
                        "policy_content_hash",
                        "runner_image_digest",
                    )
                },
                source_revision_id=source.id,
                purpose=JvmExecutionPurpose(command["purpose"]),
                trigger=JvmExecutionAttemptTrigger(command["trigger"]),
                authorization_id=None,
                rerun_phases=None
                if command["rerun_phases"] is None
                else tuple(JvmExecutionPhase(item) for item in command["rerun_phases"]),
            ),
            registry=create_sprint09_jvm_profile_registry(),
            previous=previous,
        )
        same(prepared.payload, operation.payload, "APPROVED_CONTRACT_DRIFT")
        require(
            operation.result["execution_id"] == str(attempt.id)
            and operation.result["attempt_content_hash"] == attempt.content_hash
            and operation.result["report_status"] == attempt.report.status.value,
            "ATOMIC_RESULT_MISMATCH",
        )
        self.backend.verify_finalization(
            operation, value, operation.result["finalization_reference"]
        )
        require(
            attempt.source_revision == source.reference
            and attempt.execution_plan_content_hash == prepared.contract.execution_plan.content_hash
            and attempt.policy_content_hash
            == prepared.contract.runner.execution_policy.content_hash
            and attempt.runner_image_digest == prepared.contract.runner.image.digest,
            "ATTEMPT_CONTRACT_MISMATCH",
        )
        observed = {}
        failed = False
        for result in value["report"]["phase_results"]:
            phase = result["phase"]
            if failed:
                require(
                    result["status"] == "NOT_RUN"
                    and not any(
                        result[key]
                        for key in ("stdout_refs", "stderr_refs", "artifact_refs", "exit_codes")
                    ),
                    "EXECUTED_AFTER_FAILURE",
                )
                continue
            refs = result["stdout_refs"] + result["stderr_refs"] + result["artifact_refs"]
            payloads = [(ref, verified_bytes(self.evidence, ref)) for ref in refs]
            metadata = [
                read_json(data) for ref, data in payloads if ref["media_type"] == "application/json"
            ]
            metadata = [item for item in metadata if "phase_plan" in item]
            require(len(metadata) == 1, "PHASE_METADATA_MISSING")
            item = metadata[0]
            plan = prepared.contract.execution_plan.phase(JvmExecutionPhase(phase))
            same(item["phase_plan"], plan.to_snapshot(), "PHASE_PLAN_MISMATCH")
            for key, expected in {
                "execution_attempt_id": str(attempt.id),
                "contract_hash": prepared.contract.content_hash,
                "source_revision_content_hash": source.content_hash,
                "source_tree_hash": source.source_tree_hash,
                "execution_plan_content_hash": attempt.execution_plan_content_hash,
                "policy_hash": attempt.policy_content_hash,
                "image_id": "sha256:" + attempt.runner_image_digest,
                "image_id_kind": "LOCAL_CONFIG_DIGEST",
                "container_cleanup_confirmed": True,
                "oom_killed": False,
                "network_id": self.network["controlled_network"]["network_id"]
                if phase == "SETUP"
                else "none",
                "network_manifest_hash": self.network["content_hash"] if phase == "SETUP" else None,
            }.items():
                same(item[key], expected, "PHASE_BINDING_MISMATCH")
            require(
                item["container_id"] not in self.container_ids and len(item["container_id"]) == 64,
                "CONTAINER_REUSED",
            )
            self.container_ids.add(item["container_id"])
            same(
                item["resources"],
                prepared.contract.runner.resources.to_snapshot(),
                "RESOURCE_DRIFT",
            )
            same(result["stdout_refs"], [item["stdout"]], "STDOUT_MISMATCH")
            same(result["stderr_refs"], [item["stderr"]], "STDERR_MISMATCH")
            require(
                result["command_plan_hash"] == plan.command_plan.content_hash
                and result["started_at"] == item["started_at"]
                and result["completed_at"] == item["completed_at"],
                "PHASE_REPORT_MISMATCH",
            )
            logs = (
                verified_bytes(self.evidence, item["stdout"])
                + b"\n"
                + verified_bytes(self.evidence, item["stderr"])
            ).decode(errors="replace")
            if item["artifacts"] is not None:
                inventory = item["artifacts"]
                require(
                    inventory["content_hash"]
                    == content_hash({k: v for k, v in inventory.items() if k != "content_hash"}),
                    "ARTIFACT_INVENTORY_HASH_INVALID",
                )
                for artifact in inventory["artifacts"]:
                    data = verified_bytes(self.evidence, artifact["reference"])
                    if artifact["kind"] == "APPLICATION_JAR":
                        with ZipFile(io.BytesIO(data)) as archive:
                            require(
                                any(name.endswith(".class") for name in archive.namelist()),
                                "JAR_WITHOUT_CLASSES",
                            )
                for key, expected in {
                    "source_revision_content_hash": source.content_hash,
                    "execution_plan_content_hash": attempt.execution_plan_content_hash,
                    "runner_image_digest": attempt.runner_image_digest,
                    "target": self.target.value,
                }.items():
                    same(inventory[key], expected, "INVENTORY_BINDING_MISMATCH")
                if phase == "BUILD" and result["status"] == "PASSED":
                    require(
                        any(a["kind"] == "APPLICATION_JAR" for a in inventory["artifacts"]),
                        "BUILD_JAR_MISSING",
                    )
            if expected_failure is not None and phase == expected_failure:
                expected_status = "TIMED_OUT" if case == "timeout" else "FAILED"
                require(result["status"] == expected_status, "EXPECTED_FAILURE_MISSING")
                if case == "timeout":
                    require(
                        item["transport_status"] == "TIMED_OUT"
                        and "ORCHESTWIN_TIMEOUT_PROBE" in logs
                        and (
                            datetime.fromisoformat(item["completed_at"])
                            - datetime.fromisoformat(item["started_at"])
                        ).total_seconds()
                        >= plan.command_plan.commands[0].timeout_seconds,
                        "TIMEOUT_NOT_OBSERVED",
                    )
                else:
                    require(
                        item["transport_status"] == "COMPLETED"
                        and item["container_exit_code"] != 0,
                        "FAILURE_EXIT_MISSING",
                    )
                if case == "compile_failure":
                    verify_compiler_diagnostic(
                        logs, self.target, fixture_bytes(self.repo, self.target, case)
                    )
                elif case == "runtime_failure":
                    require("ORCHESTWIN_RUNTIME_FAILURE" in logs, "EXPECTED_DIAGNOSTIC_MISSING")
                failed = True
            else:
                require(
                    result["status"] == "PASSED"
                    and item["transport_status"] == "COMPLETED"
                    and item["container_exit_code"] == 0
                    and item["evidence_error_type"] is None,
                    "UNEXPECTED_PHASE_FAILURE",
                )
            if phase == "TEST":
                counts = junit_counts(
                    [
                        verified_bytes(self.evidence, a["reference"])
                        for a in item["artifacts"]["artifacts"]
                        if a["kind"] == "JUNIT_XML"
                    ]
                )
                require(
                    counts["total"] == (2 if self.target.value == "JVM_KOTLIN" else 1)
                    and counts["skipped"] == 0
                    and counts["errors"] == 0,
                    "TEST_CASES_MISSING",
                )
                for key, count in counts.items():
                    require(
                        item["parsed_evidence"]["test_summary"][key] == count,
                        "PARSED_TEST_COUNTS_MISMATCH",
                    )
                require(
                    counts["failed"] == (1 if case == "test_failure" else 0),
                    "EXPECTED_ASSERTION_RESULT_MISSING",
                )
            if phase == "RUN" and not failed:
                require(
                    ("42" if self.target.value == "JVM_KOTLIN" else "Hello, JVM!")
                    in logs.splitlines(),
                    "EXPECTED_RUN_OUTPUT_MISSING",
                )
            observed[phase] = item
        require(
            failed == (expected_failure is not None)
            and value["report"]["status"] == ("FAILED" if failed else "PASSED"),
            "REPORT_STATUS_MISMATCH",
        )
        self.observations[(case, step)] = {
            "attempt": value,
            "operation": operation_snapshot,
            "phases": observed,
        }
        return value

    def verify(self):
        first = self.verify_attempt("positive", "initial")
        repeat = self.verify_attempt("positive", "repeat")
        require(
            first["id"] != repeat["id"]
            and repeat["previous_attempt_id"] == first["id"]
            and first["source_revision"] == repeat["source_revision"]
            and repeat["trigger"] == "MANUAL_RERUN",
            "REPRODUCIBILITY_LINEAGE_INVALID",
        )
        compiler_phase = "STATIC_CHECKS" if self.target.value == "JVM_SCALA" else "BUILD"
        broken = self.verify_attempt("compile_failure", "initial", expected_failure=compiler_phase)
        repaired = self.verify_attempt("compile_failure", "rerun")
        repair_snapshot = read_document(
            self.campaign / self.target.value / "compile_failure/repair/terminal.json"
        )
        repair = verified_operation(repair_snapshot)
        same(
            repair.to_snapshot(),
            verified_operation(self.operations[str(repair.id)], historical=True).to_snapshot(),
            "REPAIR_NOT_PERSISTED",
        )
        proposal = jvm_repair_proposal_from_snapshot(repair.payload["proposal"])
        require(
            proposal.change_set.provenance_references
            in {
                (f"jvm-execution:{broken['id']}:{broken['content_hash']}",),
                # The initial local campaign retained this mislabeled descriptive
                # prefix. Exact JVM IDs/hashes and typed lineage remain mandatory.
                (f"web-execution:{broken['id']}:{broken['content_hash']}",),
            },
            "REPAIR_PROVENANCE_REFERENCE_INVALID",
        )
        require(
            repair.kind is JvmOperationKind.REPAIR
            and repair.state is JvmOperationState.COMPLETED
            and repair.payload["execution_id"] == broken["id"]
            and repair.payload["execution_content_hash"] == broken["content_hash"]
            and proposal.base_revision == reference_from_snapshot(broken["source_revision"])
            and proposal.failure_signature.signature
            in {s["signature"] for s in broken["report"]["failure_signatures"]}
            and repaired["previous_attempt_id"] == broken["id"]
            and repaired["trigger"] == "REPAIR_RERUN",
            "REPAIR_LINEAGE_INVALID",
        )
        source = source_from_snapshot(repair.result["source_revision"], self.target)
        require(
            source.based_on == proposal.base_revision
            and source.reference == reference_from_snapshot(repaired["source_revision"])
            and source.related_failure_signature == proposal.failure_signature.signature,
            "REPAIRED_SOURCE_INVALID",
        )
        require(
            repair.result["execution_performed"] is False
            and tuple(repair.result["required_rerun_phases"]) == PHASES,
            "REPAIR_RERUN_SCOPE_INVALID",
        )
        self.verify_attempt("test_failure", "initial", expected_failure="TEST")
        self.verify_attempt("runtime_failure", "initial", expected_failure="RUN")
        self.verify_attempt("timeout", "initial", expected_failure="RUN")
        require(
            {v["attempt"]["id"] for v in self.observations.values()} == set(self.attempts),
            "UNVERIFIED_ATTEMPTS",
        )
        return self.observations
