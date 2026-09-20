"""Repair integrity checks use synthetic transport only; no model or Docker calls."""

import asyncio
import base64
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.models.source_proposals import ModelSourceProposalAdapter
from scripts import jvm_calculator_development_probe as probe
from scripts import jvm_calculator_repair as repair
from src.test.python.jvm_execution.test_development_calculator_probe import prepare
from src.test.python.models.test_proposal_evidence import audited_generator


def preparation(tmp_path, monkeypatch, target="JVM_JAVA"):
    monkeypatch.setattr(repair, "ATTEMPT_REGISTRY", tmp_path / "shared-attempt-registry")
    args = prepare(tmp_path, monkeypatch, target)
    source = probe.read_snapshot(args.source_revision)
    evidence = probe.read_snapshot(args.generation_evidence)
    base = probe.source_revision(source, target)
    args.output.mkdir()
    raw = b"Generated test compilation failed: invalid import at line 4.\n"
    ref = probe.file_entry("unused", raw, "text/plain")
    ref.pop("normalized_path")
    path = args.output / "phase-evidence" / ref["storage_key"]
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    now = datetime.now(UTC).isoformat()
    failed = {
        "phase": "TEST",
        "status": "FAILED",
        "command_plan_hash": "a" * 64,
        "started_at": now,
        "completed_at": now,
        "exit_codes": [1],
        "stdout_refs": [ref],
        "stderr_refs": [],
        "artifact_refs": [],
        "findings": [],
        "failure_category": "TEST",
        "failure_code": "JVM_TEST_CASE_FAILED",
        "normalized_summary": "Generated test failed.",
    }
    execution = probe.signed(
        {
            "scope": probe.SCOPE,
            "passed": False,
            "source_revision": base.reference.to_snapshot(),
            **probe.check_generation_binding(source, evidence),
            "development_probe_id": str(uuid4()),
            "cleanup_confirmed": True,
            "original_sources_unchanged": True,
            "completed_at": now,
            "phase_results": [failed],
        }
    )
    probe.write_json(args.output / "report.json", execution)
    options = SimpleNamespace(
        configuration=args.configuration,
        target=target,
        generation_directory=args.source_revision.parent,
        execution_directory=args.output,
        output=tmp_path / "preparation",
    )
    result = repair.prepare_repair(options)
    assert result["status"] == "PREPARED_NO_INFERENCE"
    return options.output / "repair-input.json", args


def repair_args(tmp_path, prepared):
    return SimpleNamespace(
        prepared_input=prepared, runtime_config=tmp_path / "config.json", output=tmp_path / "repair"
    )


def proposal_output(plan):
    file = next(
        f for f in plan["context"]["source_files"] if f["normalized_path"].startswith("src/test/")
    )
    return {
        "rationale": "Correct the generated test without reducing behavior coverage.",
        "changes": [
            {
                "operation": "REPLACE",
                **file,
                "content": file["content"] + "\n// Synthetic transport replacement.\n",
            }
        ],
    }


@pytest.mark.parametrize("target", ["JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA"])
def test_prepare_repair_freezes_exact_source_failure_and_v2_without_inference(
    tmp_path, monkeypatch, target
):
    path, args = preparation(tmp_path, monkeypatch, target)
    plan = probe.read_snapshot(path)
    base = repair.verify_preparation(plan)
    assert base.content_hash == probe.read_snapshot(args.source_revision)["content_hash"]
    assert plan["context"]["failure_log_evidence"]["status"] == "VERIFIED_EXCERPTS"
    assert len(plan["context"]["independent_contract"]["checks"]) == 34
    assert not repair.attempt_claim_path(plan).exists()


@pytest.mark.parametrize(
    "change",
    [
        "log",
        "source",
        "execution",
        "excerpt",
        "requirements",
        "empty_excerpts",
        "build_recipe",
        "build_recipe_view",
        "build_recipe_metadata",
    ],
)
def test_resigned_preparation_cannot_substitute_source_logs_or_execution(
    tmp_path, monkeypatch, change
):
    path, _ = preparation(tmp_path, monkeypatch)
    plan = probe.read_snapshot(path)
    if change == "log":
        plan["failure_logs"][0]["raw_base64"] = base64.b64encode(b"different").decode()
    elif change == "source":
        plan["context"]["source_files"][0]["content"] += "changed"
    elif change == "execution":
        plan["context"]["execution_id"] = str(uuid4())
    elif change == "requirements":
        plan["context"]["approved_context"]["requirements"] = {}
    elif change == "empty_excerpts":
        plan["context"]["failure_log_evidence"]["excerpts"] = []
    elif change == "build_recipe":
        recipe = next(iter(plan["context"]["build_recipes"]))
        plan["context"]["build_recipes"][recipe] += "\n// different build recipe\n"
    elif change == "build_recipe_view":
        plan["context"]["build_recipe_view"] = "UNREVIEWED_BUILD"
    elif change == "build_recipe_metadata":
        plan["context"]["build_recipe_metadata_only"] = []
    else:
        plan["context"]["failure_log_evidence"]["excerpts"][0]["text"] = "different"
    plan = probe.signed({k: v for k, v in plan.items() if k != "content_hash"})
    with pytest.raises(ValueError, match="MISMATCH"):
        repair.verify_preparation(plan)
    changed = tmp_path / "changed-input.json"
    probe.write_json(changed, plan)

    def no_transport(_):
        pytest.fail("altered preparation reached runtime construction")

    monkeypatch.setattr(probe, "build_proposal_generator", no_transport)
    with pytest.raises(ValueError, match="MISMATCH"):
        asyncio.run(repair.repair_development(repair_args(tmp_path, changed)))


def test_real_adapter_repair_preserves_native_bytes_lineage_and_allows_only_one_call(
    tmp_path, monkeypatch
):
    prepared, old = preparation(tmp_path, monkeypatch)
    plan = probe.read_snapshot(prepared)
    generator, transport = audited_generator(tmp_path, proposal_output(plan))
    monkeypatch.setattr(probe, "build_proposal_generator", lambda _: generator)
    monkeypatch.setattr(probe, "ModelSourceProposalAdapter", ModelSourceProposalAdapter)
    options = repair_args(tmp_path, prepared)
    result = asyncio.run(repair.repair_development(options))
    assert result["passed"], result
    assert len(transport.calls) == 1
    new = probe.read_snapshot(options.output / "source-revision.json")
    envelope = probe.read_snapshot(options.output / "generation-evidence.json")
    binding = probe.check_generation_binding(new, envelope)
    assert new["origin"] == "REPAIR_CHANGE_SET" and new["version_number"] == 2
    assert binding["base_execution_id"] == plan["execution"]["development_probe_id"]
    assert new["based_on"]["content_hash"] == plan["context"]["base_revision"]["content_hash"]
    probe.read_sources(probe.source_revision(new, "JVM_JAVA"), options.output / "sources")
    # The original generated bytes and failed report remain intact.
    probe.read_sources(
        probe.source_revision(probe.read_snapshot(old.source_revision), "JVM_JAVA"), old.source_root
    )
    retry = SimpleNamespace(**{**vars(options), "output": tmp_path / "second-repair"})
    with pytest.raises(FileExistsError):
        asyncio.run(repair.repair_development(retry))
    assert len(transport.calls) == 1
    # A copied plan in another directory, with a new filename and output, must not
    # reset the single-attempt allowance of its original generated source.
    alternate = tmp_path / "copied-preparation"
    alternate.mkdir()
    renamed = alternate / "renamed.json"
    renamed.write_bytes(prepared.read_bytes())
    copied_retry = SimpleNamespace(
        **{**vars(options), "prepared_input": renamed, "output": tmp_path / "copied-repair"}
    )
    with pytest.raises(FileExistsError):
        asyncio.run(repair.repair_development(copied_retry))
    assert len(transport.calls) == 1
    claims = list(repair.ATTEMPT_REGISTRY.glob("*.json"))
    assert claims == [repair.attempt_claim_path(plan)]
    claim = probe.read_snapshot(claims[0])
    probe.validate_hash(claim)
    assert envelope["attempt_claim"] == claim
    assert binding["attempt_registry_key"] == repair.attempt_key(plan)
    damaged = deepcopy(new)
    damaged["version_number"] = 3
    with pytest.raises(ValueError):
        probe.check_generation_binding(damaged, envelope)


def test_same_model_is_rejected_before_claim_or_transport(tmp_path, monkeypatch):
    prepared, _ = preparation(tmp_path, monkeypatch)
    plan = probe.read_snapshot(prepared)
    identity = probe.ModelRuntimeIdentity(**plan["execution"]["model_identity"])
    monkeypatch.setattr(
        probe,
        "build_proposal_generator",
        lambda _: SimpleNamespace(configuration=SimpleNamespace(identity=identity)),
    )
    with pytest.raises(ValueError, match="DISTINCT_REPAIR_MODEL_REQUIRED"):
        asyncio.run(repair.repair_development(repair_args(tmp_path, prepared)))
    assert not repair.attempt_claim_path(plan).exists()


def test_failed_repair_retains_native_failure_and_consumes_single_attempt(tmp_path, monkeypatch):
    prepared, _ = preparation(tmp_path, monkeypatch)
    generator, transport = audited_generator(
        tmp_path, proposal_output(probe.read_snapshot(prepared)), finish="length"
    )
    monkeypatch.setattr(probe, "build_proposal_generator", lambda _: generator)
    monkeypatch.setattr(probe, "ModelSourceProposalAdapter", ModelSourceProposalAdapter)
    options = repair_args(tmp_path, prepared)
    result = asyncio.run(repair.repair_development(options))
    assert not result["passed"] and "INCOMPLETE_OUTPUT" in result["failure"]
    assert len(transport.calls) == 1
    assert list((options.output / "model-evidence").glob("*.json"))
    assert not (options.output / "sources").exists()
    assert repair.attempt_claim_path(probe.read_snapshot(prepared)).exists()


def test_repaired_sources_cannot_run_under_old_oracle(tmp_path, monkeypatch):
    prepared, original = preparation(tmp_path, monkeypatch)
    generator, _ = audited_generator(tmp_path, proposal_output(probe.read_snapshot(prepared)))
    monkeypatch.setattr(probe, "build_proposal_generator", lambda _: generator)
    monkeypatch.setattr(probe, "ModelSourceProposalAdapter", ModelSourceProposalAdapter)
    options = repair_args(tmp_path, prepared)
    assert asyncio.run(repair.repair_development(options))["passed"]

    async def ready(_):
        return {"runtime_inputs_ready": True}

    monkeypatch.setattr(probe, "readiness", ready)
    args = SimpleNamespace(
        configuration=original.configuration,
        target="JVM_JAVA",
        source_revision=options.output / "source-revision.json",
        generation_evidence=options.output / "generation-evidence.json",
        source_root=options.output / "sources",
        output=tmp_path / "execution-v2",
        contract_version=1,
    )
    with pytest.raises(ValueError, match="REQUIRES_CONTRACT_V2"):
        asyncio.run(probe.development_probe(args))
