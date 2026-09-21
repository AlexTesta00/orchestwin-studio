"""One unpublished model repair, bound to original sources and verified failed logs."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmFailureCategory,
    JvmNormalizedFinding,
    JvmPhaseResult,
    JvmPhaseResultStatus,
    failure_signature_for,
)
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.models.proposal_evidence import evidence_application
from orchestwin.models.repair_diagnostics import EXCERPT_BYTES, MAX_EXCERPTS, failure_log_context
from orchestwin.models.source_proposals import RepairOutput, build_source_binding
from scripts import jvm_calculator_development_probe as probe
from scripts.verify_generated_jvm_calculator import ROOT, contract

PREPARATION = "VERIFIED_JVM_CALCULATOR_REPAIR_V1"
ATTEMPT_REGISTRY = ROOT / "var/studio/jvm-calculator-repair-attempts"


def attempt_key(plan):
    """One attempt per original generation, regardless of plan filename or location."""
    return probe.digest(
        {
            "scope": probe.SCOPE,
            "base_generation_id": plan["base_generation_evidence"]["generation_id"],
            "base_source_reference": plan["execution"]["source_revision"],
        }
    )


def attempt_claim_path(plan):
    return ATTEMPT_REGISTRY / (attempt_key(plan) + ".json")


def phase_result(snapshot):
    return JvmPhaseResult(
        **{
            **snapshot,
            "phase": JvmExecutionPhase(snapshot["phase"]),
            "status": JvmPhaseResultStatus(snapshot["status"]),
            "failure_category": JvmFailureCategory(snapshot["failure_category"]),
            "started_at": datetime.fromisoformat(snapshot["started_at"]),
            "completed_at": datetime.fromisoformat(snapshot["completed_at"]),
            "exit_codes": tuple(snapshot["exit_codes"]),
            **{
                field: tuple(JvmEvidenceReference(**item) for item in snapshot[field])
                for field in ("stdout_refs", "stderr_refs", "artifact_refs")
            },
            "findings": tuple(JvmNormalizedFinding(**item) for item in snapshot["findings"]),
        }
    )


def failed_inputs(base_evidence, execution):
    base = base_evidence["source_revision"]
    if base["origin"] != "GENERATED_PLAN" or base["based_on"] is not None:
        raise ValueError("ONLY_ONE_REPAIR_OF_ORIGINAL_GENERATION_ALLOWED")
    revision = probe.source_revision(base, base["target_selection"]["target"])
    binding = probe.check_generation_binding(base, base_evidence)
    probe.validate_hash(execution)
    if (
        execution.get("scope") != probe.SCOPE
        or execution.get("passed") is not False
        or not execution.get("cleanup_confirmed")
        or not execution.get("original_sources_unchanged")
        or not execution.get("completed_at")
        or execution["source_revision"] != revision.reference.to_snapshot()
        or any(execution.get(key) != value for key, value in binding.items())
    ):
        raise ValueError("EXACT_COMPLETED_FAILED_DEVELOPMENT_EXECUTION_REQUIRED")
    failed = [p for p in execution["phase_results"] if p.get("failure_category")]
    if len(failed) != 1 or failed[0]["phase"] not in {"STATIC_CHECKS", "BUILD", "TEST", "RUN"}:
        raise ValueError("ONE_RECORDED_SOURCE_FAILURE_REQUIRED")
    phase = phase_result(failed[0])
    signature = failure_signature_for(phase)
    assert signature is not None
    return revision, phase, signature


def verify_preparation(plan):
    probe.validate_hash(plan)
    if plan.get("kind") != PREPARATION or plan.get("repair_attempt_number") != 1:
        raise ValueError("BOUNDED_REPAIR_PREPARATION_REQUIRED")
    base, phase, signature = failed_inputs(plan["base_generation_evidence"], plan["execution"])
    context = plan["context"]
    original = plan["base_generation_evidence"]
    parent = next(
        r
        for r in original["generations"]
        if r["request"]["generation_id"] == original["generation_id"]
    )
    original_context = json.loads(parent["request"]["request"]["input_payload_json"])["context"]
    expected = {
        "project_id": str(base.project_id),
        "target_selection": base.target_selection.to_snapshot(),
        "base_revision": base.reference.to_snapshot(),
        "base_files": [f.to_snapshot() for f in base.files],
        "execution_id": plan["execution"]["development_probe_id"],
        "execution_content_hash": plan["execution"]["content_hash"],
        "failure_signature": signature.to_snapshot(),
        "recorded_failure": phase.to_snapshot(),
        "independent_contract": contract(base.target_selection.target.value, 2),
        "approved_context": {
            key: original_context[key] for key in ("requirements", "design", "architecture")
        },
        **{
            key: original_context[key]
            for key in ("build_recipe_view", "build_recipes", "build_recipe_metadata_only")
        },
    }
    if any(context.get(key) != value for key, value in expected.items()):
        raise ValueError("REPAIR_PREPARATION_BINDING_MISMATCH")
    entries = {f.normalized_path: f.to_snapshot() for f in base.files}
    fixed = {item["normalized_path"]: item for item in context["fixed_files"]}
    supplied = {item["normalized_path"]: item for item in context["source_files"]}
    if (
        len(supplied) != len(context["source_files"])
        or set(fixed) != {name for name in entries if not name.startswith("src/")}
        or set(supplied) != set(entries) - set(fixed)
        or any(entries.get(name) != value for name, value in fixed.items())
    ):
        raise ValueError("REPAIR_BASE_FILE_INVENTORY_MISMATCH")
    for name, item in supplied.items():
        if probe.file_entry(name, item["content"].encode(), item["media_type"]) != entries[name]:
            raise ValueError("REPAIR_BASE_SOURCE_BYTES_MISMATCH")
    # Also bind recipe text to the original source's immutable file digest, not just
    # a repeated context field. A re-hashed plan cannot introduce different build instructions.
    for name, text in context["build_recipes"].items():
        if (
            name not in fixed
            or not isinstance(text, str)
            or probe.identity(text.encode())
            != {key: fixed[name][key] for key in ("sha256_digest", "size_bytes")}
        ):
            raise ValueError("REPAIR_BUILD_RECIPE_BYTES_MISMATCH")
    references = [*phase.stdout_refs, *phase.stderr_refs]
    logs = plan["failure_logs"]
    if len(logs) != len(references):
        raise ValueError("REPAIR_FAILURE_LOG_INVENTORY_MISMATCH")
    raw_by_hash = {}
    for item, reference in zip(logs, references, strict=True):
        raw = base64.b64decode(item["raw_base64"], validate=True)
        if item["reference"] != reference.to_snapshot() or probe.identity(raw) != {
            "sha256_digest": reference.sha256_digest,
            "size_bytes": reference.size_bytes,
        }:
            raise ValueError("REPAIR_FAILURE_LOG_CONTENT_MISMATCH")
        raw_by_hash[reference.sha256_digest] = raw
    stream_refs = [
        (stream, ref) for stream in ("stdout", "stderr") for ref in getattr(phase, stream + "_refs")
    ]
    excerpts = []
    for stream, ref in stream_refs[:MAX_EXCERPTS]:
        raw = raw_by_hash[ref.sha256_digest]
        text = raw[:EXCERPT_BYTES].decode("utf-8", errors="ignore")
        excerpts.append(
            {
                "stream": stream,
                "reference": ref.to_snapshot(),
                "start_byte": 0,
                "end_byte": len(text.encode()),
                "truncated": text != raw.decode(),
                "text": text,
            }
        )
    if context["failure_log_evidence"] != {
        "status": "VERIFIED_EXCERPTS",
        "excerpts": excerpts,
        "omitted_reference_count": max(0, len(stream_refs) - MAX_EXCERPTS),
    }:
        raise ValueError("REPAIR_FAILURE_EXCERPT_MISMATCH")
    return base


def prepare_repair(args):
    generation, execution_root, output = (
        p.absolute() for p in (args.generation_directory, args.execution_directory, args.output)
    )
    for root in (generation, execution_root, output):
        probe.regular_path(root)
    if any(
        output == root or output in root.parents or root in output.parents
        for root in (generation, execution_root)
    ):
        raise ValueError("REPAIR_OUTPUT_ROOTS_OVERLAP")
    evidence = probe.read_snapshot(generation / "generation-evidence.json")
    execution = probe.read_snapshot(execution_root / "report.json")
    base, phase, signature = failed_inputs(evidence, execution)
    if base.target_selection.target.value != args.target:
        raise ValueError("REPAIR_TARGET_MISMATCH")
    contents = probe.read_sources(base, generation / "sources")
    configuration = probe.GovernedJvmSettings(
        _env_file=None, **probe.read_snapshot(args.configuration)
    )
    probe.verify_source_policy(base, contents, repo_root=configuration.repo_root)
    fixed = probe.pinned_build_files(
        base.target_selection.target, repo_root=configuration.repo_root
    )
    recipe = probe.generation_context(args.target, fixed)
    parent = next(
        r
        for r in evidence["generations"]
        if r["request"]["generation_id"] == evidence["generation_id"]
    )
    original_context = json.loads(parent["request"]["request"]["input_payload_json"])["context"]
    logs = []
    for ref in (*phase.stdout_refs, *phase.stderr_refs):
        if ref.storage_key != f"sha256/{ref.sha256_digest[:2]}/{ref.sha256_digest}":
            raise ValueError("REPAIR_LOG_REFERENCE_INVALID")
        raw = probe.read_regular_file(
            execution_root / "phase-evidence" / ref.storage_key, maximum_bytes=8 * 1024 * 1024
        )
        logs.append({"reference": ref.to_snapshot(), "raw_base64": base64.b64encode(raw).decode()})
    context = {
        "project_id": str(base.project_id),
        "target_selection": base.target_selection.to_snapshot(),
        "execution_id": execution["development_probe_id"],
        "execution_content_hash": execution["content_hash"],
        "base_revision": base.reference.to_snapshot(),
        "base_files": [f.to_snapshot() for f in base.files],
        "source_files": [
            {
                "normalized_path": f.normalized_path,
                "content": contents[f.normalized_path].decode(),
                "media_type": f.media_type,
            }
            for f in base.files
            if f.normalized_path not in fixed
        ],
        "approved_context": {
            key: original_context[key] for key in ("requirements", "design", "architecture")
        },
        "failure_signature": signature.to_snapshot(),
        "recorded_failure": phase.to_snapshot(),
        "failure_log_evidence": failure_log_context(phase, execution_root / "phase-evidence"),
        "independent_contract": contract(args.target, 2),
        "repair_scope": "One model repair. Preserve required behavior and meaningful test coverage. Fix invalid or contradictory generated tests according to the requirements; do not remove assertions to hide failures.",
        **{
            key: recipe[key]
            for key in (
                "fixed_files",
                "build_recipe_view",
                "build_recipes",
                "build_recipe_metadata_only",
            )
        },
    }
    plan = probe.signed(
        {
            "schema_version": 1,
            "kind": PREPARATION,
            "scope": probe.SCOPE,
            "repair_attempt_number": 1,
            "base_generation_evidence": evidence,
            "execution": execution,
            "failure_logs": logs,
            "context": context,
            "configuration": configuration.model_dump(mode="json"),
        }
    )
    verify_preparation(plan)
    output.mkdir(parents=True, exist_ok=False)
    probe.write_json(output / "repair-input.json", plan)
    probe.write_json(output / "independent-contract.json", contract(args.target, 2))
    report = probe.signed(
        {
            "passed": True,
            "checks": [],
            "scope": probe.SCOPE,
            "status": "PREPARED_NO_INFERENCE",
            "target": args.target,
            "repair_input_hash": plan["content_hash"],
            "failure_signature": signature.to_snapshot(),
            "base_revision": base.reference.to_snapshot(),
            "model_called": False,
            "executed_application": False,
            "level_d_publication": False,
        }
    )
    probe.write_json(output / "report.json", report)
    return report


class RepairOperation:
    def __init__(self, store, adapter, context):
        self._proposal_evidence_store, self.adapter, self.context = store, adapter, context

    @evidence_application
    async def run(self, *, owner_user_id, project_id):
        return await self.adapter.propose(task="jvm-repair", context=self.context)


def repaired_files(plan, output):
    binding = build_source_binding("jvm-repair", plan["context"], output)
    files = {f["normalized_path"]: f for f in plan["context"]["base_files"]}
    for change in binding["changes"]:
        name = change["normalized_path"]
        if change["operation"] == "DELETE":
            # A development trial is not authorized to reduce existing test coverage.
            if name.startswith("src/test/"):
                raise ValueError("REPAIR_MUST_PRESERVE_EXISTING_TEST_FILES")
            files.pop(name)
        else:
            files[name] = {
                "normalized_path": name,
                "sha256_digest": change["content_sha256"],
                **{k: change[k] for k in ("size_bytes", "storage_key", "media_type")},
            }
    return binding, tuple(JvmSourceFileEntry(**files[name]) for name in sorted(files))


def check_repair_binding(source, evidence):
    probe.validate_hash(evidence)
    if (
        evidence.get("scope") != probe.SCOPE
        or evidence.get("publication_state") != "LOCAL_GENERATION_ONLY"
        or evidence.get("source_revision") != source
        or evidence.get("repair_attempt_number") != 1
        or len(evidence.get("generations", [])) != 1
    ):
        raise ValueError("UNPUBLISHED_SINGLE_REPAIR_EVIDENCE_REQUIRED")
    plan = evidence["preparation"]
    base = verify_preparation(plan)
    claim = evidence["attempt_claim"]
    probe.validate_hash(claim)
    if (
        claim["attempt_registry_key"] != attempt_key(plan)
        or claim["repair_input_hash"] != plan["content_hash"]
        or claim["base_revision"] != base.reference.to_snapshot()
        or claim["execution_content_hash"] != plan["execution"]["content_hash"]
        or claim["failure_signature"] != plan["context"]["failure_signature"]["signature"]
    ):
        raise ValueError("REPAIR_ATTEMPT_CLAIM_BINDING_MISMATCH")
    record = evidence["generations"][0]
    request, events = probe.validate_generation_record(record, task_id="proposal-jvm-repair-v1")
    if (
        request["generation_id"] != evidence["generation_id"]
        or request["project_id"] != str(base.project_id)
        or request["owner_user_id"] != str(base.created_by_user_id)
        or request["request"]["expected_identity"] != claim["model_identity"]
        or json.loads(request["request"]["input_payload_json"])["context"] != plan["context"]
    ):
        raise ValueError("REPAIR_MODEL_REQUEST_BINDING_MISMATCH")
    result = RepairOutput.model_validate(
        json.loads(events["PROVIDER_RESULT"]["success"]["payload_json"])
    )
    binding, files = repaired_files(plan, result)
    accepted = events["ADAPTER_ACCEPTED"]
    if (
        accepted["source_binding"] != binding
        or accepted["generated_content_hashes"].get("JVM_REPAIR") != [probe.digest(binding)]
        or accepted["result"]["kind"] != "JVM_REPAIR"
        or accepted["result"]["output"] != result.model_dump()
        or accepted["result"]["source_binding"] != binding
    ):
        raise ValueError("REPAIR_ACCEPTED_OUTPUT_MISMATCH")
    repaired = probe.source_revision(source, base.target_selection.target.value)
    if (
        repaired.based_on != base.reference
        or repaired.version_number != base.version_number + 1
        or repaired.project_id != base.project_id
        or repaired.created_by_user_id != base.created_by_user_id
        or repaired.files != files
        or repaired.provenance_references != base.provenance_references
        or repaired.related_failure_signature != plan["context"]["failure_signature"]["signature"]
    ):
        raise ValueError("REPAIRED_SOURCE_LINEAGE_MISMATCH")
    return {
        "generation_id": request["generation_id"],
        "generation_request_hash": record["content_hash"],
        "generation_evidence_hash": probe.digest(evidence),
        "generation_publication": "LOCAL_GENERATION_ONLY",
        "model_identity": request["request"]["expected_identity"],
        "repair_input_hash": plan["content_hash"],
        "base_generation_id": plan["base_generation_evidence"]["generation_id"],
        "base_execution_id": plan["execution"]["development_probe_id"],
        "repair_attempt_number": 1,
        "attempt_registry_key": claim["attempt_registry_key"],
    }


async def repair_development(args):
    prepared = args.prepared_input.absolute()
    probe.regular_path(prepared)
    plan = probe.read_snapshot(prepared)
    base = verify_preparation(plan)
    output = args.output.absolute()
    probe.regular_path(output)
    if (
        output.exists()
        or output == prepared.parent
        or output in prepared.parents
        or prepared.parent in output.parents
    ):
        raise ValueError("NEW_SEPARATE_REPAIR_OUTPUT_REQUIRED")
    generator = probe.build_proposal_generator(args.runtime_config.absolute())
    identity = generator.configuration.identity.to_snapshot()
    old_identity = plan["execution"]["model_identity"]
    fields = ("base_model_repository", "base_model_revision", "adapter_sha256")
    if all(identity[k] == old_identity[k] for k in fields):
        raise ValueError("DISTINCT_REPAIR_MODEL_REQUIRED_NO_BLIND_BASE_MODEL_RETRY")
    # This common registry is independent of the input's filename and directory.
    # A copied or re-hashed preparation still consumes the same original-source slot.
    probe.regular_path(ATTEMPT_REGISTRY)
    ATTEMPT_REGISTRY.mkdir(parents=True, exist_ok=True)
    claim_path = attempt_claim_path(plan)
    claim = probe.signed(
        {
            "attempt_registry_key": attempt_key(plan),
            "repair_input_hash": plan["content_hash"],
            "base_revision": base.reference.to_snapshot(),
            "execution_content_hash": plan["execution"]["content_hash"],
            "failure_signature": plan["context"]["failure_signature"]["signature"],
            "output": str(output),
            "model_identity": identity,
            "started_at": datetime.now(UTC).isoformat(),
        }
    )
    with claim_path.open("x", encoding="utf-8") as stream:
        json.dump(claim, stream)
    output.mkdir(parents=True, exist_ok=False)
    records = output / "model-evidence"
    records.mkdir()
    store = probe.FileEvidence(records)
    probe.write_json(output / "repair-input.json", plan)
    probe.write_json(
        output / "independent-contract.json", contract(base.target_selection.target.value, 2)
    )
    report = {
        "passed": False,
        "checks": [],
        "scope": probe.SCOPE,
        "repair_attempt_number": 1,
        "repair_input_hash": plan["content_hash"],
        "attempt_registry_key": claim["attempt_registry_key"],
        "model_identity": identity,
        "executed_application": False,
        "database_publication": False,
        "level_d_publication": False,
    }
    try:
        proposal = await RepairOperation(
            store, probe.ModelSourceProposalAdapter(generator), plan["context"]
        ).run(owner_user_id=base.created_by_user_id, project_id=base.project_id)
        probe.write_json(output / "proposal.json", probe.wire_value(proposal))
        _, files = repaired_files(plan, proposal.output)
        revision = create_jvm_source_revision(
            revision_id=uuid4(),
            project_id=base.project_id,
            created_by_user_id=base.created_by_user_id,
            version_number=base.version_number + 1,
            based_on=base.reference,
            target=base.target_selection.target,
            origin=JvmSourceOrigin.REPAIR_CHANGE_SET,
            files=files,
            provenance_references=base.provenance_references,
            related_failure_signature=plan["context"]["failure_signature"]["signature"],
            created_at=datetime.now(UTC),
        )
        evidence = probe.signed(
            {
                "schema_version": 1,
                "scope": probe.SCOPE,
                "mode": "DEVELOPMENT_REPAIR",
                "publication_state": "LOCAL_GENERATION_ONLY",
                "repair_attempt_number": 1,
                "generation_id": next(iter(store.records)),
                "source_revision": revision.to_snapshot(),
                "preparation": plan,
                "attempt_claim": claim,
                "generations": list(store.records.values()),
            }
        )
        check_repair_binding(revision.to_snapshot(), evidence)
        configuration = probe.GovernedJvmSettings(_env_file=None, **plan["configuration"])
        contents = probe.pinned_build_files(
            base.target_selection.target, repo_root=configuration.repo_root
        )
        contents.update(
            {f["normalized_path"]: f["content"].encode() for f in plan["context"]["source_files"]}
        )
        for change in proposal.output.changes:
            if change.operation == "DELETE":
                contents.pop(change.normalized_path)
            else:
                contents[change.normalized_path] = change.content.encode()
        probe.verify_source_policy(revision, contents, repo_root=configuration.repo_root)
        destination = output / "sources"
        destination.mkdir()
        for name, raw in contents.items():
            path = destination / name
            probe.regular_path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        probe.read_sources(revision, destination)
        probe.write_json(output / "source-revision.json", revision.to_snapshot())
        probe.write_json(output / "generation-evidence.json", evidence)
        report.update(
            passed=True,
            generation_id=evidence["generation_id"],
            source_content_hash=revision.content_hash,
        )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report["failure"] = type(error).__name__ + ":" + str(error)
    finally:
        probe.write_json(output / "report.json", probe.signed(report))
    return report
