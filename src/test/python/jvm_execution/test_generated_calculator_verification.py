"""Independent checks must reject wrong behavior and unrelated execution evidence."""

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import verify_generated_jvm_calculator as verifier


def observed(**replacements):
    rows = []
    for name, left, operation, right in verifier.INPUTS:
        expected = verifier.expected(left, operation, right)
        if expected["kind"] == "VALUE":
            value = f"VALUE\t{expected['value']}"
        else:
            fields = ("java.lang.IllegalArgumentException", "Invalid input or division by zero")
            value = "ERROR\t" + "\t".join(
                base64.b64encode(item.encode()).decode() for item in fields
            )
        rows.append("nonce-" + name + "\t" + replacements.get(name, value))
    return "\n".join(rows)


def test_decimal_oracle_and_all_expected_results():
    assert verifier.expected("1,5", "+", "2.25") == {"kind": "VALUE", "value": "3.75"}
    assert verifier.expected("4", "/", "-0.0") == {"kind": "ERROR"}
    results = verifier.evaluate_output(observed(), "nonce-")
    assert len(results) == 20
    assert all(result["passed"] for result in results)


@pytest.mark.parametrize(
    "case,value",
    [
        ("addition", "VALUE\t0"),
        ("fractional-division", "VALUE\t3"),
        ("zero-divisor", "VALUE\tInfinity"),
        ("invalid-number", "VALUE\tNaN"),
        ("comma-decimal", "VALUE\t15.25"),
    ],
)
def test_independent_oracle_rejects_behavioral_failures(case, value):
    results = verifier.evaluate_output(observed(**{case: value}), "nonce-")
    assert not next(result for result in results if result["id"] == case)["passed"]


def test_missing_or_duplicate_cases_never_count_as_success():
    with pytest.raises(ValueError, match="INCOMPLETE"):
        verifier.evaluate_output(observed().split("\n", 1)[1], "nonce-")
    with pytest.raises(ValueError, match="DUPLICATE"):
        verifier.evaluate_output(observed() + "\nnonce-addition\tVALUE\t12", "nonce-")


def test_console_demo_must_show_the_expected_result():
    assert verifier.console_demo_passed("9 + 3 = 12.0\n")
    assert not verifier.console_demo_passed("Hello from Main\n")
    assert not verifier.console_demo_passed("9 + 3 = 13\n")
    assert not verifier.console_demo_passed("")


def snapshots():
    source = {
        "id": "source-1",
        "project_id": "project-1",
        "version_number": 1,
        "origin": "GENERATED_PLAN",
        "target_selection": {"target": "JVM_KOTLIN"},
    }
    source["content_hash"] = hashlib.sha256(verifier.canonical(source)).hexdigest()
    source["source_tree_hash"] = "tree-hash"
    attempt = {
        "id": "attempt-1",
        "profile_id": "jvm.kotlin-gradle",
        "profile_version": "1.0.0",
        "source_revision": {
            "revision_id": "source-1",
            "project_id": "project-1",
            "version_number": 1,
            "content_hash": source["content_hash"],
            "source_tree_hash": "tree-hash",
        },
        "report": {
            "status": "PASSED",
            "target_selection": {"target": "JVM_KOTLIN"},
            "phase_results": [{"artifact_refs": [verifier.identity(b"application-jar")]}],
        },
    }
    attempt["content_hash"] = hashlib.sha256(verifier.canonical(attempt)).hexdigest()
    return source, attempt


def test_application_jar_must_be_recorded_for_exact_generated_source():
    source, attempt = snapshots()
    verifier.check_binding(source, attempt, "JVM_KOTLIN", b"application-jar")
    with pytest.raises(ValueError, match="JAR_NOT_IN_EXECUTION"):
        verifier.check_binding(source, attempt, "JVM_KOTLIN", b"different-jar")
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        verifier.check_binding(source, attempt, "JVM_JAVA", b"application-jar")


def test_modified_snapshot_and_failed_execution_rejected():
    source, attempt = snapshots()
    attempt["report"]["status"] = "FAILED"
    with pytest.raises(ValueError, match="SNAPSHOT_HASH_MISMATCH"):
        verifier.check_binding(source, attempt, "JVM_KOTLIN", b"application-jar")
    attempt["content_hash"] = hashlib.sha256(
        verifier.canonical({key: value for key, value in attempt.items() if key != "content_hash"})
    ).hexdigest()
    with pytest.raises(ValueError, match="SUCCESSFUL_GOVERNED_EXECUTION_REQUIRED"):
        verifier.check_binding(source, attempt, "JVM_KOTLIN", b"application-jar")


@pytest.mark.parametrize("target", verifier.PROFILES)
def test_contract_does_not_claim_execution_or_graphical_preview(target):
    contract = verifier.contract(target)
    assert contract["claims"] == {
        "executed": False,
        "graphical_preview": False,
        "level_d_publication": False,
    }
    assert "calculate(left: String" in contract["approved_requirement_text"]
    assert "no-argument main" in contract["approved_requirement_text"]


def test_failed_probe_is_retained_and_owned_containers_are_cleaned(tmp_path, monkeypatch):
    source, attempt = snapshots()
    for name, value in (("source.json", source), ("attempt.json", attempt)):
        (tmp_path / name).write_text(json.dumps(value))
    jar = tmp_path / "application.jar"
    jar.write_bytes(b"application-jar")
    image = "sha256:" + "a" * 64
    commands = []

    async def process(arguments, timeout=60):
        commands.append(arguments)
        output, code = "", 0
        if "inspect" in arguments:
            output = image
        elif "run" in arguments:
            if "/probe/CalculatorProbe.java" in arguments:
                output, code = "Missing required public calculate method", 1
            else:
                output = "9 + 3 = 12"
        return {"status": "COMPLETED", "exit_code": code, "stdout": output, "stderr": ""}

    monkeypatch.setattr(verifier, "process", process)
    options = SimpleNamespace(
        target="JVM_KOTLIN",
        source_revision=tmp_path / "source.json",
        execution_attempt=tmp_path / "attempt.json",
        application_jar=jar,
        runtime_jar=[],
        image=image,
        docker_context="desktop-linux",
        output=tmp_path / "evidence",
    )
    report = asyncio.run(verifier.verify(options))
    assert report["passed"] is False
    assert report["checks"] == []
    assert all(item["cleanup_confirmed"] for item in report["processes"])
    assert len([item for item in commands if "rm" in item]) == 2
    assert (options.output / "report.json").is_file()
    for command in [item for item in commands if "run" in item]:
        assert {"--network=none", "--read-only", "--cap-drop=ALL", "--pull=never"} <= set(command)
        assert command[command.index("--mount") + 1].endswith(",target=/probe,readonly")
