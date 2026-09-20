"""Development receipts remain distinct; source/provenance checks precede transport.

All inference and Docker execution in this file are mocked. Fixture sources are
unit-test data, never represented as successful real model/calculator execution.
"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.models.proposal_evidence import (
    begin_model_generation,
    child_proposal_evidence,
    current_proposal_evidence,
    retain_adapter_result,
    retain_provider_result,
)
from orchestwin.models.source_proposals import (
    SourceFile,
    SourceOutput,
    SourceProposal,
    build_source_binding,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_request,
    create_structured_generation_success,
    create_structured_json_schema,
    successful_structured_generation_result,
)
from scripts import jvm_calculator_development_probe as probe
from scripts.verify_generated_jvm_calculator import ROOT

IDENTITY = ModelRuntimeIdentity(
    "unit-test-protocol", "mocked-runtime", "unit-test-model", "a" * 40, "b" * 40, "c" * 64
)


def request(context):
    return create_structured_generation_request(
        request_id=uuid4(),
        task_id="proposal-jvm-source-v1",
        expected_identity=IDENTITY,
        output_schema=create_structured_json_schema(
            schema_id="test.jvm.source", version_number=1, schema_payload={"type": "object"}
        ),
        system_instruction="Unit test protocol, no inference.",
        input_payload={"context": context},
        allowed_evidence_refs=(),
        prompt_version_ref="test.jvm.v1",
        temperature=0.6,
        max_output_tokens=2048,
        timeout_seconds=60,
    )


def result(payload):
    return successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        success=create_structured_generation_success(
            payload=payload,
            actual_identity=IDENTITY,
            usage=StructuredGenerationUsage(10, 10, 1),
            finish_reason=StructuredGenerationFinishReason.STOP,
            provider_request_id="test-only",
        ),
    )


async def recorded_result(payload):
    raw = json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]}).encode()
    await current_proposal_evidence().event(
        "HTTP_RESPONSE",
        {
            "status_code": 200,
            "body_retained": True,
            "body_sha256": probe.identity(raw)["sha256_digest"],
            "body_size_bytes": len(raw),
        },
        raw_body=raw,
    )
    await retain_provider_result(result(payload))


class MockSourceAdapter:
    def __init__(self, generator):
        pass

    async def propose_files(self, *, task, context):
        target = context["target_selection"]["target"]
        fixture = {
            "JVM_JAVA": "jvm-java-greeting",
            "JVM_KOTLIN": "jvm-kotlin-calculator",
            "JVM_SCALA": "jvm-scala-greeting",
        }[target]
        fixture_root = ROOT / "src/test/fixtures/jvm_execution" / fixture
        parent = request(context)
        await begin_model_generation(parent)
        await recorded_result({"test_manifest": True})
        files, steps = [], []
        for ordinal, path in enumerate(sorted((fixture_root / "src").rglob("*")), 1):
            if not path.is_file():
                continue
            file = SourceFile(
                normalized_path=path.relative_to(fixture_root).as_posix(),
                content=path.read_text(encoding="utf-8"),
                media_type="text/plain",
            )
            with child_proposal_evidence() as child:
                child_request = request(
                    {
                        "source_step": {
                            "parent_generation_id": str(parent.request_id),
                            "parent_request_hash": parent.content_hash,
                            "file": {"normalized_path": file.normalized_path},
                        }
                    }
                )
                await begin_model_generation(child_request)
                await recorded_result({"content": file.content})
                await child.event("ADAPTER_ACCEPTED", {"source_file": file.model_dump()})
                await child.event("APPLICATION_RESULT", {"status": "SOURCE_FILE_GENERATED"})
                steps.append(
                    {
                        "generation_id": str(child_request.request_id),
                        "request_hash": child_request.content_hash,
                        "ordinal": ordinal,
                        "file": probe.file_entry(
                            file.normalized_path, file.content.encode(), "text/plain"
                        ),
                    }
                )
                files.append(file)
        output = SourceOutput(rationale="Unit test fixture bytes.", files=files)
        proposal = SourceProposal(
            kind="JVM_SOURCE",
            output=output,
            source_binding=build_source_binding(task, context, output),
            generation_steps=tuple(steps),
        )
        await retain_adapter_result(proposal)
        return proposal


def prepare(tmp_path, monkeypatch, target="JVM_JAVA"):
    configuration = {
        "enabled": True,
        "repo_root": str(ROOT),
        "workspaces_root": str(tmp_path / "workspaces"),
        "distribution_path": str(tmp_path / "gradle.zip"),
        "dependency_network_manifest": str(tmp_path / "network.json"),
        "dependency_network_manifest_hash": "d" * 64,
        "gradle_image_id": "sha256:" + "e" * 64,
        "sbt_image_id": "sha256:" + "f" * 64,
    }
    config_file = tmp_path / "jvm.json"
    probe.write_json(config_file, configuration)
    monkeypatch.setattr(
        probe,
        "build_proposal_generator",
        lambda _: SimpleNamespace(configuration=SimpleNamespace(identity=IDENTITY)),
    )
    monkeypatch.setattr(probe, "ModelSourceProposalAdapter", MockSourceAdapter)
    options = SimpleNamespace(
        configuration=config_file,
        runtime_config=tmp_path / "not-opened.json",
        target=target,
        output=tmp_path / "generation",
    )
    report = asyncio.run(probe.generate_development(options))
    assert report["passed"], report
    return SimpleNamespace(
        configuration=config_file,
        target=target,
        source_revision=options.output / "source-revision.json",
        source_root=options.output / "sources",
        generation_evidence=options.output / "generation-evidence.json",
        output=tmp_path / "execution",
    )


@pytest.mark.parametrize("target", ["JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA"])
def test_generation_keeps_original_protocol_evidence_and_console_profile(
    tmp_path, monkeypatch, target
):
    args = prepare(tmp_path, monkeypatch, target)
    source, evidence = (
        probe.read_snapshot(args.source_revision),
        probe.read_snapshot(args.generation_evidence),
    )
    binding = probe.check_generation_binding(source, evidence)
    assert binding["generation_publication"] == "LOCAL_GENERATION_ONLY"
    assert evidence["scope"] == "DEVELOPMENT_CONSOLE_MODEL_PROBE_NOT_LEVEL_D"
    revision = probe.source_revision(source, target)
    contents = probe.read_sources(revision, args.source_root)
    config = probe.GovernedJvmSettings(_env_file=None, **probe.read_snapshot(args.configuration))
    _, contract, _ = probe.build_contract(revision, contents, config)
    assert contract.validation.capability_status.value == "DESIGN_ONLY_LEVEL_C"
    assert contract.validation.is_ready
    assert "OWNER_PROJECT" not in json.dumps(evidence)
    assert len(evidence["generations"]) >= 3


def test_changed_source_or_added_unrecorded_file_rejected(tmp_path, monkeypatch):
    args = prepare(tmp_path, monkeypatch)
    revision = probe.source_revision(probe.read_snapshot(args.source_revision), args.target)
    source_file = next((args.source_root / "src/main").rglob("*.java"))
    original = source_file.read_bytes()
    source_file.write_bytes(original + b"\n// changed")
    with pytest.raises(ValueError, match="ORIGINAL_MODEL_SOURCE_CHANGED"):
        probe.read_sources(revision, args.source_root)
    source_file.write_bytes(original)
    (args.source_root / "extra.txt").write_bytes(b"extra")
    with pytest.raises(ValueError, match="SOURCE_INVENTORY_MISMATCH"):
        probe.read_sources(revision, args.source_root)


@pytest.mark.parametrize("change", ["fake_provider", "missing_child", "changed_output"])
def test_offline_envelope_requires_real_complete_source_evidence(tmp_path, monkeypatch, change):
    args = prepare(tmp_path, monkeypatch)
    source, evidence = (
        probe.read_snapshot(args.source_revision),
        probe.read_snapshot(args.generation_evidence),
    )
    if change == "missing_child":
        evidence["generations"].pop()
    else:
        parent = evidence["generations"][0]
        event = next(
            e
            for e in parent["observations"]
            if e["kind"] == ("PROVIDER_RESULT" if change == "fake_provider" else "ADAPTER_ACCEPTED")
        )
        if change == "fake_provider":
            event["payload"]["provider_kind"] = "FAKE_DETERMINISTIC"
        else:
            event["payload"]["result"]["output"]["files"][0]["content"] += "\n// changed"
        event["content_hash"] = probe.digest(
            {k: v for k, v in event.items() if k not in {"content_hash", "raw_body_base64"}}
        )
    evidence["content_hash"] = probe.digest(
        {k: v for k, v in evidence.items() if k != "content_hash"}
    )
    with pytest.raises(ValueError, match=r"REAL_MODEL|EVIDENCE_MISSING|SOURCE_BYTES_MISMATCH"):
        probe.check_generation_binding(source, evidence)


@pytest.mark.parametrize("failure", [None, "BUILD", "cleanup", "source_mutation"])
def test_development_execution_cleans_and_never_promotes(tmp_path, monkeypatch, failure):
    args = prepare(tmp_path, monkeypatch)
    events = []

    async def readiness(_):
        return {"runtime_inputs_ready": True, "blockers": []}

    class Executor:
        def __init__(self, **kwargs):
            self.workspace = SimpleNamespace(path=tmp_path / "mock-workspace")
            self.finalization_reference = SimpleNamespace(
                to_snapshot=lambda: {"sha256_digest": "a" * 64}
            )

        def bind_attempt(self, probe_id, **kwargs):
            events.append("bind")

        async def execute(self, plan, **kwargs):
            phase = plan.phase.value
            events.append(phase)
            return SimpleNamespace(
                is_failure=phase == failure,
                to_snapshot=lambda: {
                    "phase": phase,
                    "status": "FAILED" if phase == failure else "PASSED",
                },
            )

        async def finalize(self):
            events.append("finalize")
            if failure == "cleanup":
                raise RuntimeError("CLEANUP_NOT_CONFIRMED")
            if failure == "source_mutation":
                next((args.source_root / "src/main").rglob("*.java")).write_bytes(b"changed")

    def retain_dependencies(*args):
        events.append("retain-dependencies")
        return []

    def retain_application(*args):
        events.append("retain-application")
        return b"mock-jar", {"sha256_digest": "a" * 64}

    async def verify_bundle(options, *, source, app_data, binding):
        events.append("independent")
        assert binding["mode"] == "DEVELOPMENT_PROBE"
        assert "execution_attempt_id" not in binding
        return {"passed": True, "checks": [{"passed": True}]}

    monkeypatch.setattr(probe, "readiness", readiness)
    monkeypatch.setattr(probe, "GovernedJvmPhaseExecutor", Executor)
    monkeypatch.setattr(probe, "retain_runtime_dependencies", retain_dependencies)
    monkeypatch.setattr(probe, "retain_application", retain_application)
    monkeypatch.setattr(probe, "verify_jar_bundle", verify_bundle)
    report = asyncio.run(probe.development_probe(args))
    assert report["passed"] is (failure is None)
    assert not any(report["claims"].values())
    assert report["mode"] == "DEVELOPMENT_PROBE"
    assert report["capability_status"] == "DESIGN_ONLY_LEVEL_C"
    assert events[-1] == "finalize"
    assert events.index("SETUP") < events.index("retain-dependencies") < events.index("BUILD")
    if failure == "BUILD":
        assert "TEST" not in events and "independent" not in events
    else:
        assert events.index("retain-application") < events.index("TEST")
    stored = probe.read_snapshot(args.output / "report.json")
    probe.validate_hash(stored)
    assert stored["passed"] is (failure is None)


def test_runtime_library_selection_excludes_sbt_boot_and_rejects_ambiguity(tmp_path):
    probe_id = uuid4()
    cache = tmp_path / f".orchestwin/jvm/{probe_id.hex}/coursier"
    cache.mkdir(parents=True)
    output = tmp_path / "retained"
    output.mkdir()
    for name in ("scala-library-2.13.16.jar", "scala3-library_3-3.3.8.jar"):
        (cache / name).write_bytes(name.encode())
    jars = probe.retain_runtime_dependencies(tmp_path, probe_id, "JVM_SCALA", output)
    assert len(jars) == 2
    (cache / "scala-library-2.13.18.jar").write_bytes(b"ambiguous")
    with pytest.raises(ValueError, match="UNAMBIGUOUS_RUNTIME_DEPENDENCY_REQUIRED"):
        probe.retain_runtime_dependencies(tmp_path, probe_id, "JVM_SCALA", output)
