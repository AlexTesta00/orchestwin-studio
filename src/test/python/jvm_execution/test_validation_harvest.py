"""Integrity failures must prevent JVM evidence collection and publication."""

import copy
import hashlib
import io
import tarfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.jvm_execution.operation_governance import (
    JvmGovernedOperation,
    JvmOperationKind,
    JvmOperationState,
    operation_json,
)
from orchestwin.jvm_execution.source_policy import verify_source_policy
from orchestwin.jvm_execution.validation_fixtures import CASES, fixture_bytes
from orchestwin.jvm_execution.validation_harvest import load_publication
from orchestwin.jvm_execution.validation_prerequisites import (
    RunnerPrerequisiteCollector,
    execution_configuration,
    filesystem_inventory,
)
from orchestwin.jvm_execution.validation_verification import (
    junit_counts,
    source_from_snapshot,
    verified_bytes,
    verified_operation,
    verify_compiler_diagnostic,
    verify_gate_history,
)
from src.test.python.jvm_execution.api_support import ROOT, TARGETS, fixture_context


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("case", CASES)
def test_failure_fixtures_change_only_one_source_and_preserve_closed_build_policy(target, case):
    positive, actual = fixture_bytes(ROOT, target), fixture_bytes(ROOT, target, case)
    changed = {path for path in actual if actual[path] != positive[path]}
    assert len(changed) == (0 if case == "positive" else 1)
    assert all(path.startswith("src/") for path in changed)
    from orchestwin.jvm_execution.targets import selection_for

    declaration = verify_source_policy(
        SimpleNamespace(target_selection=selection_for(target)), actual, repo_root=ROOT
    )
    assert declaration.selection.target is target


@pytest.mark.parametrize("target", TARGETS)
def test_exported_source_requires_exact_nested_hashes(tmp_path, target):
    _, revision, _ = fixture_context(tmp_path, target)
    snapshot = revision.to_snapshot()
    assert source_from_snapshot(snapshot, target) == revision
    altered = copy.deepcopy(snapshot)
    altered["files"][0]["sha256_digest"] = "a" * 64
    with pytest.raises(ValueError, match="SOURCE_SNAPSHOT_INVALID"):
        source_from_snapshot(altered, target)


def test_evidence_bytes_require_hash_size_and_content_addressed_path(tmp_path):
    data = b"actual retained output"
    digest = hashlib.sha256(data).hexdigest()
    reference = dict(
        sha256_digest=digest, size_bytes=len(data), storage_key=f"sha256/{digest[:2]}/{digest}"
    )
    path = tmp_path / reference["storage_key"]
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    assert verified_bytes(tmp_path, reference) == data
    with pytest.raises(ValueError, match="STORAGE_KEY_INVALID"):
        verified_bytes(tmp_path, {**reference, "storage_key": "../../outside"})
    path.write_bytes(b"X" * len(data))
    with pytest.raises(ValueError, match="BYTES_MISMATCH"):
        verified_bytes(tmp_path, reference)


def operation_snapshot():
    operation = JvmGovernedOperation.create(
        project_id=uuid4(),
        owner_user_id=uuid4(),
        source_revision_id=uuid4(),
        kind=JvmOperationKind.EXECUTION,
        payload={"fixture": "bounded"},
    )
    operation = replace(
        operation,
        state=JvmOperationState.COMPLETED,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        result_json=operation_json({"execution_performed": True}),
    )
    return {
        **operation.to_snapshot(),
        "gate_current": True,
        "gate": {
            "id": str(operation.gate_id),
            "artifact_id": str(operation.id),
            "artifact_content_hash": operation.content_hash,
            "status": "APPROVED",
            "type": "HIGH_IMPACT_OPERATION",
            "event_sequence": 2,
            "is_current": True,
        },
    }


@pytest.mark.parametrize("mutation", ["gate_hash", "payload", "status", "stale"])
def test_gate_approval_cannot_be_substituted_or_moved_to_another_payload(mutation):
    value = operation_snapshot()
    verified_operation(value, require_current=True)
    if mutation == "gate_hash":
        value["gate"]["artifact_content_hash"] = "0" * 64
    elif mutation == "payload":
        value["payload"]["fixture"] = "altered"
    elif mutation == "status":
        value["gate"]["status"] = "PENDING_APPROVAL"
    else:
        value["gate"]["is_current"] = False
    with pytest.raises(ValueError):
        verified_operation(value, require_current=True)


@pytest.mark.parametrize(
    "mutation", [None, "late_approval", "foreign_actor", "missing_approval", "early_supersession"]
)
def test_superseded_gate_requires_persisted_approval_before_execution(mutation):
    value = operation_snapshot()
    base = {
        "gate_id": value["gate_id"],
        "project_id": value["project_id"],
        "gate_type": "HIGH_IMPACT_OPERATION",
        "artifact_id": value["id"],
        "artifact_hash": value["content_hash"],
        "artifact_version": 1,
        "actor_user_id": value["owner_user_id"],
        "occurred_at": value["created_at"],
    }
    events = [
        {
            **base,
            "id": str(uuid4()),
            "sequence_number": 1,
            "kind": "SUBMIT",
            "previous_status": "DRAFT",
            "resulting_status": "PENDING_APPROVAL",
        },
        {
            **base,
            "id": str(uuid4()),
            "sequence_number": 2,
            "kind": "APPROVE",
            "previous_status": "PENDING_APPROVAL",
            "resulting_status": "APPROVED",
        },
        {
            **base,
            "id": str(uuid4()),
            "sequence_number": 3,
            "kind": "ARTIFACT_SUPERSEDED",
            "previous_status": "APPROVED",
            "resulting_status": "STALE",
            "actor_user_id": None,
            "artifact_id": str(uuid4()),
            "artifact_hash": "f" * 64,
            "occurred_at": value["finished_at"],
        },
    ]
    value["gate"].update(status="STALE", event_sequence=3, is_current=False)
    value["gate_current"] = False
    if mutation == "late_approval":
        events[1]["occurred_at"] = (
            datetime.fromisoformat(value["finished_at"]) + timedelta(seconds=1)
        ).isoformat()
    elif mutation == "foreign_actor":
        events[1]["actor_user_id"] = str(uuid4())
    elif mutation == "missing_approval":
        events.pop(1)
    elif mutation == "early_supersession":
        events[2]["occurred_at"] = value["created_at"]
    if mutation is None:
        assert str(verify_gate_history(value, events).id) == value["id"]
    else:
        with pytest.raises(ValueError):
            verify_gate_history(value, events)


def test_junit_counts_actual_cases_and_rejects_duplicate_or_entity_evidence():
    xml = b'<testsuite><testcase classname="Suite" name="ok"/><testcase classname="Suite" name="bad"><failure/></testcase></testsuite>'
    assert junit_counts([xml]) == dict(total=2, passed=1, failed=1, errors=0, skipped=0)
    with pytest.raises(ValueError, match="DUPLICATE_TEST_CASE"):
        junit_counts([xml, xml])
    with pytest.raises(ValueError, match="UNSAFE_XML"):
        junit_counts([b'<!DOCTYPE x [<!ENTITY x "boom">]><testsuite/>'])


def test_publication_requires_the_operator_pinned_package_hash(tmp_path):
    (tmp_path / "publication.json").write_text('{"catalog":{},"artifacts":{}}')
    with pytest.raises(ValueError, match="PACKAGE_HASH_MISMATCH"):
        load_publication(tmp_path, expected_package_hash="0" * 64)


@pytest.mark.parametrize("mutation", [None, "foreign_file", "wrong_line", "dependency_failure"])
def test_kotlin_diagnostic_binds_the_intentional_source_location(mutation):
    target = next(target for target in TARGETS if target.value == "JVM_KOTLIN")
    files = fixture_bytes(ROOT, target, "compile_failure")
    logs = (
        "> Task :compileKotlin FAILED\n"
        "e: file:///workspace/src/main/kotlin/org/orchestwin/calculator/Main.kt:7:1 "
        "Syntax error: Expecting a top level declaration."
    )
    if mutation == "foreign_file":
        logs = logs.replace("Main.kt", "Unrelated.kt")
    elif mutation == "wrong_line":
        logs = logs.replace(":7:1", ":2:1")
    elif mutation == "dependency_failure":
        logs = "> Task :compileKotlin FAILED\nCould not resolve dependencies."
    if mutation is None:
        verify_compiler_diagnostic(logs, target, files)
    else:
        with pytest.raises(ValueError, match="EXPECTED_COMPILER_LOCATION_MISSING"):
            verify_compiler_diagnostic(logs, target, files)


def test_recipe_comparison_preserves_execution_settings_and_ignores_only_owner_label():
    config = {"User": "65532:65532", "Env": ["JAVA_HOME=/jdk"], "Labels": {"version": "24.04"}}
    labeled = copy.deepcopy(config)
    labeled["Labels"]["org.orchestwin.jvm-bootstrap"] = "a" * 32
    assert execution_configuration(labeled) == config
    labeled["Env"].append("LD_PRELOAD=unreviewed")
    assert execution_configuration(labeled) != config
    assert "org.orchestwin.jvm-bootstrap" in labeled["Labels"]


def test_image_filesystem_comparison_includes_bytes_and_mode_but_not_time():
    def inventory(data=b"class bytes", mode=0o644, timestamp=1):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo("app/Main.class")
            member.size, member.mode, member.mtime = len(data), mode, timestamp
            archive.addfile(member, io.BytesIO(data))
        stream.seek(0)
        return filesystem_inventory(stream)

    assert inventory(timestamp=1) == inventory(timestamp=100)
    assert inventory(mode=0o644) != inventory(mode=0o755)
    assert inventory(data=b"original") != inventory(data=b"altered")


def test_prerequisite_container_is_removed_even_when_observation_raises(tmp_path, monkeypatch):
    collector = RunnerPrerequisiteCollector(
        repo_root=tmp_path,
        output_root=tmp_path / "out",
        images={"gradle": "sha256:" + "a" * 64, "sbt": "sha256:" + "b" * 64},
        docker_context="test",
    )
    calls, owner = [], None

    def docker(arguments):
        nonlocal owner
        calls.append(arguments)
        if arguments[0] == "create":
            owner = arguments[arguments.index("--label") + 1].partition("=")[2]
            return SimpleNamespace(returncode=0, stdout=b"c" * 64)
        return SimpleNamespace(
            returncode=0, stdout=owner.encode() if arguments[0] == "inspect" else b""
        )

    monkeypatch.setattr(collector, "docker", docker)
    with (
        pytest.raises(TimeoutError),
        collector.owned_container(["--network", "none", "fixture-image"]),
    ):
        raise TimeoutError("Observation timed out")
    assert calls[-1] == ["rm", "--force", "--volumes", "c" * 64]
