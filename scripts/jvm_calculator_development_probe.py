"""Separate, unpublished development execution of unmodified model-generated JVM sources."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from orchestwin.api.governed_jvm_context import GovernedJvmSettings
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevisionReference,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot, JvmTextFile
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.phase_executor import GovernedJvmPhaseExecutor
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.runtime_artifacts import (
    JvmArtifactKind,
    collect_jvm_artifact_inventory,
)
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.source_policy import (
    SOURCE_POLICY_HASH,
    pinned_build_files,
    verify_source_policy,
)
from orchestwin.jvm_execution.targets import selection_for
from orchestwin.jvm_execution.workspaces import read_regular_file, regular_path
from orchestwin.models.proposal_evidence import evidence_application
from orchestwin.models.proposal_generation import build_proposal_generator, wire_value
from orchestwin.models.source_proposals import ModelSourceProposalAdapter, file_entry
from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from scripts.verify_generated_jvm_calculator import (
    canonical,
    identity,
    read_snapshot,
    readiness,
    verify_jar_bundle,
)
from scripts.verify_generated_jvm_calculator import (
    contract as calculator_contract,
)

MODE = "DEVELOPMENT_PROBE"
SCOPE = "DEVELOPMENT_CONSOLE_MODEL_PROBE_NOT_LEVEL_D"
REAL_PROVIDERS = {"OPENAI_COMPATIBLE_LOCAL", "UNSLOTH_DIRECT_LOCAL"}


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def signed(value):
    return {**value, "content_hash": digest(value)}


def validate_hash(value, *, omitted=()):
    payload = {k: v for k, v in value.items() if k not in {"content_hash", *omitted}}
    if digest(payload) != value["content_hash"]:
        raise ValueError("GENERATION_EVIDENCE_HASH_MISMATCH")
    return payload


def source_revision(source, target):
    """Reconstruct the domain object, checking every serialized field, not just hashes."""
    source = {k: v for k, v in source.items() if k != "model_generation_id"}
    if source["origin"] not in {"GENERATED_PLAN", "REPAIR_CHANGE_SET"}:
        raise ValueError("MODEL_GENERATED_SOURCE_REQUIRED")
    previous = source["based_on"]
    revision = create_jvm_source_revision(
        revision_id=UUID(source["id"]),
        project_id=UUID(source["project_id"]),
        created_by_user_id=UUID(source["created_by_user_id"]),
        version_number=source["version_number"],
        based_on=None
        if previous is None
        else JvmSourceRevisionReference(
            **{
                **previous,
                "revision_id": UUID(previous["revision_id"]),
                "project_id": UUID(previous["project_id"]),
            }
        ),
        target=ExecutionTarget(target),
        origin=JvmSourceOrigin(source["origin"]),
        files=tuple(JvmSourceFileEntry(**entry) for entry in source["files"]),
        provenance_references=tuple(
            JvmSourceProvenanceReference(**{**ref, "kind": JvmSourceProvenanceKind(ref["kind"])})
            for ref in source["provenance_references"]
        ),
        created_at=datetime.fromisoformat(source["created_at"]),
        related_failure_signature=source.get("related_failure_signature"),
    )
    if revision.to_snapshot() != source:
        raise ValueError("SOURCE_REVISION_SNAPSHOT_MISMATCH")
    return revision


def regular_files(root, *, maximum_entries=20_000):
    """Walk without following links and bound even directories that contain no files."""
    root = root.absolute()
    regular_path(root)
    count = 0
    for folder, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            count += 1
            if count > maximum_entries:
                raise ValueError("PROBE_FILE_INVENTORY_LIMIT_EXCEEDED")
            regular_path(Path(folder) / name)
        for name in names:
            yield Path(folder) / name


def read_sources(revision, root):
    expected = {entry.normalized_path: entry for entry in revision.files}
    observed = {p.relative_to(root).as_posix(): p for p in regular_files(root)}
    if set(observed) != set(expected):
        raise ValueError("SOURCE_INVENTORY_MISMATCH")
    contents = {}
    total = 0
    for name, entry in expected.items():
        raw = read_regular_file(observed[name], maximum_bytes=16 * 1024 * 1024)
        if identity(raw) != {"sha256_digest": entry.sha256_digest, "size_bytes": entry.size_bytes}:
            raise ValueError("ORIGINAL_MODEL_SOURCE_CHANGED")
        total += len(raw)
        if total > 64 * 1024 * 1024:
            raise ValueError("SOURCE_INVENTORY_BYTE_LIMIT_EXCEEDED")
        contents[name] = raw
    return contents


def validate_generation_record(record, *, task_id="proposal-jvm-source-v1"):
    request = record["request"]
    if digest(request) != record["content_hash"]:
        raise ValueError("GENERATION_REQUEST_HASH_MISMATCH")
    generation_id = request["generation_id"]
    UUID(generation_id)
    inner = request["request"]
    if inner["request_id"] != generation_id or inner["task_id"] != task_id:
        raise ValueError("JVM_MODEL_REQUEST_REQUIRED")
    expected_identity = ModelRuntimeIdentity(**inner["expected_identity"])
    inner_payload = {
        k: v for k, v in inner.items() if k not in {"content_hash", "input_payload_json"}
    }
    inner_payload["input_payload"] = json.loads(inner["input_payload_json"])
    if digest(inner_payload) != inner["content_hash"]:
        raise ValueError("MODEL_REQUEST_CONTENT_HASH_MISMATCH")
    observations, raw_responses = {}, {}
    for observation in record["observations"]:
        payload = validate_hash(observation, omitted=("raw_body_base64",))
        if payload["generation_id"] != generation_id or payload["kind"] in observations:
            raise ValueError("GENERATION_OBSERVATION_BINDING_MISMATCH")
        raw = observation.get("raw_body_base64")
        raw = None if raw is None else base64.b64decode(raw, validate=True)
        if payload["raw_body_sha256"] != (None if raw is None else hashlib.sha256(raw).hexdigest()):
            raise ValueError("MODEL_RESPONSE_HASH_MISMATCH")
        observations[payload["kind"]] = payload["payload"]
        raw_responses[payload["kind"]] = raw
    provider = observations["PROVIDER_RESULT"]
    if (
        provider["provider_kind"] not in REAL_PROVIDERS
        or provider["status"] != "SUCCEEDED"
        or provider["failure"] is not None
        or provider["success"]["actual_identity"] != expected_identity.to_snapshot()
    ):
        raise ValueError("SUCCESSFUL_REAL_MODEL_IDENTITY_REQUIRED")
    success = provider["success"]
    result_payload = {k: v for k, v in success.items() if k not in {"content_hash", "payload_json"}}
    result_payload["payload"] = json.loads(success["payload_json"])
    if digest(result_payload) != success["content_hash"]:
        raise ValueError("MODEL_RESULT_CONTENT_HASH_MISMATCH")
    if provider["provider_kind"] == "OPENAI_COMPATIBLE_LOCAL":
        response = observations.get("HTTP_RESPONSE", {})
        raw = raw_responses.get("HTTP_RESPONSE")
        if (
            response.get("status_code") != 200
            or response.get("body_retained") is not True
            or raw is None
            or response.get("body_sha256") != hashlib.sha256(raw).hexdigest()
            or response.get("body_size_bytes") != len(raw)
        ):
            raise ValueError("ORIGINAL_MODEL_HTTP_RESPONSE_REQUIRED")
        response_payload = json.loads(json.loads(raw)["choices"][0]["message"]["content"])
        if response_payload != json.loads(success["payload_json"]):
            raise ValueError("MODEL_HTTP_RESPONSE_RESULT_MISMATCH")
    return request, observations


def check_generation_binding(source, evidence):
    """Accept an API export or an explicitly unpublished local generation envelope."""
    if source["origin"] == "REPAIR_CHANGE_SET":
        from scripts.jvm_calculator_repair import check_repair_binding

        return check_repair_binding(source, evidence)
    offline = evidence.get("scope") == SCOPE
    if offline:
        validate_hash(evidence)
        if evidence.get("publication_state") != "LOCAL_GENERATION_ONLY":
            raise ValueError("OFFLINE_GENERATION_MUST_NOT_CLAIM_PUBLICATION")
        if evidence["source_revision"] != source:
            raise ValueError("OFFLINE_GENERATION_SOURCE_MISMATCH")
        records = evidence["generations"]
        for item in records:
            validate_generation_record(item)
        parents = [r for r in records if r["request"]["generation_id"] == evidence["generation_id"]]
        if len(parents) != 1:
            raise ValueError("SOURCE_PARENT_GENERATION_REQUIRED")
        record = parents[0]
    else:
        record = evidence
        if record["publication_state"] != "ARTIFACTS_LINKED":
            raise ValueError("PUBLISHED_GENERATION_EVIDENCE_REQUIRED")
        links = [validate_hash(link) for link in record["artifact_links"]]
        if not any(
            link["generation_id"] == record["request"]["generation_id"]
            and link["artifact"]
            == {
                "kind": "JVM_SOURCE",
                "version_id": source["id"],
                "version_number": source["version_number"],
                "content_hash": source["content_hash"],
                "relation": "SOURCE_GENERATED",
            }
            for link in links
        ):
            raise ValueError("MODEL_PUBLICATION_SOURCE_BINDING_MISMATCH")
    request, observations = validate_generation_record(record)
    if (
        request["project_id"] != source["project_id"]
        or request["owner_user_id"] != source["created_by_user_id"]
    ):
        raise ValueError("MODEL_SOURCE_OWNER_MISMATCH")
    binding = {key: source[key] for key in ("files", "target_selection", "provenance_references")}
    accepted = observations["ADAPTER_ACCEPTED"]
    if accepted["source_binding"] != binding or accepted["generated_content_hashes"][
        "JVM_SOURCE"
    ] != [digest(binding)]:
        raise ValueError("ACCEPTED_MODEL_SOURCE_BINDING_MISMATCH")
    output = accepted["result"]
    if output["kind"] != "JVM_SOURCE" or output["source_binding"] != binding:
        raise ValueError("ACCEPTED_JVM_SOURCE_REQUIRED")
    entries = {entry["normalized_path"]: entry for entry in source["files"]}
    generated_paths = [file["normalized_path"] for file in output["output"]["files"]]
    expected_paths = {name for name in entries if name.startswith("src/")}
    if len(generated_paths) != len(set(generated_paths)) or set(generated_paths) != expected_paths:
        raise ValueError("COMPLETE_MODEL_SOURCE_OUTPUT_REQUIRED")
    for file in output["output"]["files"]:
        actual = identity(file["content"].encode("utf-8"))
        if any(entries[file["normalized_path"]][key] != value for key, value in actual.items()):
            raise ValueError("MODEL_OUTPUT_SOURCE_BYTES_MISMATCH")
    if offline:
        by_id = {r["request"]["generation_id"]: r for r in records}
        steps = output.get("generation_steps", [])
        if (
            len(by_id) != len(records)
            or {step["file"]["normalized_path"] for step in steps} != expected_paths
            or len(steps) != len(expected_paths)
        ):
            raise ValueError("COMPLETE_MODEL_FILE_GENERATION_EVIDENCE_REQUIRED")
        for step in steps:
            child = by_id.get(step["generation_id"])
            if child is None:
                raise ValueError("MODEL_FILE_GENERATION_EVIDENCE_MISSING")
            _, child_events = validate_generation_record(child)
            child_text = json.loads(child_events["PROVIDER_RESULT"]["success"]["payload_json"])[
                "content"
            ]
            child_request = child["request"]["request"]
            source_step = json.loads(child_request["input_payload_json"])["context"]["source_step"]
            if (
                step["request_hash"] != child_request["content_hash"]
                or source_step["parent_generation_id"] != request["generation_id"]
                or source_step["parent_request_hash"] != request["request"]["content_hash"]
                or child_request["expected_identity"] != request["request"]["expected_identity"]
                or child["request"]["project_id"] != request["project_id"]
                or child["request"]["owner_user_id"] != request["owner_user_id"]
            ):
                raise ValueError("MODEL_FILE_PARENT_BINDING_MISMATCH")
            path = step["file"]["normalized_path"]
            if source_step["file"]["normalized_path"] != path:
                raise ValueError("MODEL_FILE_REQUEST_PATH_MISMATCH")
            if identity(child_text.encode())["sha256_digest"] != entries[path]["sha256_digest"]:
                raise ValueError("MODEL_FILE_RESPONSE_SOURCE_MISMATCH")
    return {
        "generation_id": request["generation_id"],
        "generation_request_hash": record["content_hash"],
        "generation_evidence_hash": digest(evidence),
        "generation_publication": "LOCAL_GENERATION_ONLY" if offline else "ARTIFACTS_LINKED",
        "model_identity": request["request"]["expected_identity"],
    }


def build_contract(revision, contents, configuration):
    declaration = verify_source_policy(revision, contents, repo_root=configuration.repo_root)
    texts = []
    for path, data in sorted(contents.items()):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        texts.append(JvmTextFile(path, text, hashlib.sha256(data).hexdigest()))
    snapshot = JvmDetectionSnapshot(
        revision.source_tree_hash, tuple(sorted(contents)), tuple(texts)
    )
    scala = revision.target_selection.target is ExecutionTarget.JVM_SCALA
    family, image = (
        ("sbt", configuration.sbt_image_id) if scala else ("gradle", configuration.gradle_image_id)
    )
    factory = create_sbt_jvm_runner_contract if scala else create_gradle_jvm_runner_contract
    runner = factory(ContainerImageReference(f"orchestwin/jvm-{family}-runner@{image}"))
    profile = create_sprint09_jvm_profile_registry().for_target(revision.target_selection.target)
    execution_contract = profile.create_contract(
        snapshot, declaration, source_revision=revision.reference, runner=runner
    )
    if not execution_contract.validation.is_ready:
        raise ValueError("GENERATED_SOURCE_PROFILE_NOT_STRUCTURALLY_READY")
    return snapshot, execution_contract, image


def retain_runtime_dependencies(workspace, probe_id, target, destination):
    """Copy runtime libraries immediately after trusted SETUP, before generated code runs."""
    patterns = {
        "JVM_JAVA": (),
        "JVM_KOTLIN": (r"kotlin-stdlib-2\.4\.10\.jar",),
        "JVM_SCALA": (r"scala3-library_3-3\.3\.8\.jar", r"scala-library-2\.13\.[0-9]+\.jar"),
    }[target]
    if not patterns:
        return []
    cache = workspace / f".orchestwin/jvm/{probe_id.hex}"
    # Exclude sbt's own Scala boot libraries; only project dependency cache is admissible.
    cache = cache / ("coursier" if target == "JVM_SCALA" else "gradle/caches/modules-2/files-2.1")
    matches = {pattern: {} for pattern in patterns}
    for path in regular_files(cache):
        for pattern in patterns:
            if re.fullmatch(pattern, path.name):
                raw = read_regular_file(path, maximum_bytes=16 * 1024 * 1024)
                matches[pattern][hashlib.sha256(raw).hexdigest()] = (path, raw)
    retained = []
    for pattern, variants in matches.items():
        if len(variants) != 1:
            raise ValueError(f"UNAMBIGUOUS_RUNTIME_DEPENDENCY_REQUIRED:{pattern}")
        path, raw = next(iter(variants.values()))
        output = destination / path.name
        output.write_bytes(raw)
        retained.append(output)
    return retained


def retain_application(executor, execution_contract, probe_id, store, destination):
    inventory = collect_jvm_artifact_inventory(
        execution_contract,
        workspace_path=executor.workspace.path,
        run_id=probe_id,
        command_id="development.calculator.build",
        evidence_store=store,
    )
    jars = [
        item.reference
        for item in inventory.artifacts
        if item.kind is JvmArtifactKind.APPLICATION_JAR
    ]
    if len(jars) != 1:
        raise ValueError("EXACTLY_ONE_APPLICATION_JAR_REQUIRED")
    raw = store.read(jars[0].storage_key)
    if raw is None:
        raise ValueError("BUILT_APPLICATION_EVIDENCE_UNAVAILABLE")
    (destination / "application.jar").write_bytes(raw)
    return raw, jars[0].to_snapshot()


async def development_probe(args):
    """No project workflow, authorization, validation publication or database calls."""
    configuration = GovernedJvmSettings(_env_file=None, **read_snapshot(args.configuration))
    preflight = await readiness(args.configuration)
    if not preflight["runtime_inputs_ready"]:
        raise ValueError(
            "JVM_DEVELOPMENT_PREREQUISITES_NOT_READY:" + ",".join(preflight["blockers"])
        )
    source = read_snapshot(args.source_revision)
    revision = source_revision(source, args.target)
    source = revision.to_snapshot()
    evidence = read_snapshot(args.generation_evidence)
    binding = check_generation_binding(source, evidence)
    contract_version = getattr(args, "contract_version", 1)
    if source["origin"] == "REPAIR_CHANGE_SET" and contract_version != 2:
        raise ValueError("REPAIRED_CALCULATOR_REQUIRES_CONTRACT_V2")
    source_root, output = args.source_root.absolute(), args.output.absolute()
    roots = (source_root, output, configuration.workspaces_root)
    for index, root in enumerate(roots):
        regular_path(root)
        if any(
            root == other or root in other.parents or other in root.parents
            for other in roots[index + 1 :]
        ):
            raise ValueError("DEVELOPMENT_PROBE_STORAGE_ROOTS_OVERLAP")
    contents = read_sources(revision, source_root)
    snapshot, execution_contract, image = build_contract(revision, contents, configuration)
    output.mkdir(parents=True, exist_ok=False)
    retained = output / "built-artifacts"
    retained.mkdir()
    probe_id = uuid4()
    store = FileSystemSandboxEvidenceStore(output / "phase-evidence")
    report = {
        "schema_version": 1,
        "mode": MODE,
        "scope": SCOPE,
        "development_probe_id": str(probe_id),
        "recorded_at": datetime.now(UTC).isoformat(),
        "target": args.target,
        "source_revision": revision.reference.to_snapshot(),
        **binding,
        "source_policy_hash": SOURCE_POLICY_HASH,
        "execution_contract_hash": execution_contract.content_hash,
        "image_id": image,
        "dependency_network_manifest_hash": configuration.dependency_network_manifest_hash,
        "capability_status": execution_contract.validation.capability_status.value,
        "independent_contract_version": contract_version,
        "phase_results": [],
        "checks": [],
        "cleanup_confirmed": False,
        "original_sources_unchanged": False,
        "passed": False,
        "claims": {
            "level_d_publication": False,
            "owner_project_execution": False,
            "database_publication": False,
            "graphical_preview": False,
        },
    }
    write_json(output / "source-revision.json", source)
    write_json(output / "generation-evidence.json", evidence)
    write_json(output / "execution-contract.json", execution_contract.to_snapshot())
    write_json(output / "report.json", signed(report))
    executor = GovernedJvmPhaseExecutor(
        contract=execution_contract,
        source_revision=revision,
        snapshot=snapshot,
        source_path=source_root,
        workspaces_root=configuration.workspaces_root,
        evidence_store=store,
        docker_context=configuration.docker_context,
        distribution_path=configuration.distribution_path,
        dependency_network_manifest=configuration.dependency_network_manifest,
        dependency_network_manifest_hash=configuration.dependency_network_manifest_hash,
    )
    executor.bind_attempt(
        probe_id, contract=execution_contract, phases_to_execute=tuple(JvmExecutionPhase)
    )
    app_data, runtime_jars = None, []
    try:
        for phase in JvmExecutionPhase:
            observed = await executor.execute(
                execution_contract.execution_plan.phase(phase), contract=execution_contract
            )
            report["phase_results"].append(observed.to_snapshot())
            write_json(output / "report.json", signed(report))
            if observed.is_failure:
                report["failure"] = "DEVELOPMENT_PHASE_FAILED:" + phase.value
                break
            if phase is JvmExecutionPhase.SETUP:
                runtime_jars = retain_runtime_dependencies(
                    executor.workspace.path, probe_id, args.target, retained
                )
            if phase is JvmExecutionPhase.BUILD:
                app_data, report["application_jar"] = retain_application(
                    executor, execution_contract, probe_id, store, retained
                )
        else:
            final_jar, _ = retain_application(executor, execution_contract, probe_id, store, output)
            if final_jar != app_data:
                raise ValueError("BUILT_APPLICATION_CHANGED_DURING_TEST_OR_RUN")
            check = await verify_jar_bundle(
                SimpleNamespace(
                    target=args.target,
                    image=image,
                    docker_context=configuration.docker_context,
                    runtime_jar=runtime_jars,
                    output=output / "independent-checks",
                    contract_version=contract_version,
                ),
                source=source,
                app_data=app_data,
                binding={
                    "mode": MODE,
                    "scope": SCOPE,
                    "development_probe_id": str(probe_id),
                    **binding,
                },
            )
            report.update(
                checks=check["checks"],
                independent_report_hash=digest(check),
                passed=check["passed"],
            )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report.update(passed=False, failure=type(error).__name__ + ":" + str(error))
    finally:
        try:
            await executor.finalize()
            report["cleanup_confirmed"] = True
            report["finalization_reference"] = executor.finalization_reference.to_snapshot()
        except (OSError, ValueError, RuntimeError) as error:
            report.update(passed=False, cleanup_failure=type(error).__name__ + ":" + str(error))
        try:
            report["original_sources_unchanged"] = read_sources(revision, source_root) == contents
        except (OSError, ValueError) as error:
            report["source_verification_failure"] = str(error)
        report["passed"] = (
            report["passed"]
            and report["cleanup_confirmed"]
            and report["original_sources_unchanged"]
        )
        report["completed_at"] = datetime.now(UTC).isoformat()
        write_json(output / "report.json", signed(report))
    return report


class FileEvidence:
    """Append observations using production envelope hashes without claiming SQL publication."""

    def __init__(self, root):
        self.root, self.records = root, {}

    async def begin(self, *, owner_user_id, project_id, request):
        generation_id = str(request.request_id)
        if generation_id in self.records:
            raise ValueError("DUPLICATE_GENERATION_REQUEST")
        envelope = {
            "schema_version": 1,
            "recorded_at": datetime.now(UTC).isoformat(),
            "generation_id": generation_id,
            "project_id": str(project_id),
            "owner_user_id": str(owner_user_id),
            "request": request.to_snapshot(),
        }
        self.records[generation_id] = {
            "request": envelope,
            "content_hash": digest(envelope),
            "observations": [],
        }
        write_json(self.root / f"{generation_id}.json", self.records[generation_id])

    async def append(self, *, generation_id, kind, payload, raw_body=None, **scope):
        record = self.records[str(generation_id)]
        if any(event["kind"] == kind for event in record["observations"]):
            raise ValueError("DUPLICATE_GENERATION_EVENT")
        event = signed(
            {
                "schema_version": 1,
                "recorded_at": datetime.now(UTC).isoformat(),
                "generation_id": str(generation_id),
                "kind": kind,
                "payload": wire_value(payload),
                "raw_body_sha256": None
                if raw_body is None
                else hashlib.sha256(raw_body).hexdigest(),
            }
        )
        record["observations"].append(
            {
                **event,
                "raw_body_base64": None
                if raw_body is None
                else base64.b64encode(raw_body).decode("ascii"),
            }
        )
        write_json(self.root / f"{generation_id}.json", record)


class GenerationOperation:
    def __init__(self, store, adapter, context):
        self._proposal_evidence_store, self.adapter, self.context = store, adapter, context

    @evidence_application
    async def run(self, *, owner_user_id, project_id):
        return await self.adapter.propose_files(task="jvm-source", context=self.context)


def generation_context(target, fixed):
    """Synthetic requirements are explicit; no owner approvals or UX mockups are invented."""
    requirement = calculator_contract(target)["approved_requirement_text"]
    contents = {
        "requirements": {
            "requirements": [
                {
                    "code": "REQ-001",
                    "kind": "FUNCTIONAL",
                    "priority": "MUST",
                    "title": "Console calculator",
                    "statement": requirement,
                }
            ]
        },
        "design": {
            "interaction": "Finite console demonstration plus a public arithmetic function. No graphical preview or browser interface."
        },
        "architecture": {
            "style": "A small self-contained console calculator in the pinned main file and behavioral tests in the pinned test file. No external dependencies beyond the reviewed recipe."
        },
    }
    recipes = {"build.gradle.kts", "settings.gradle.kts", "build.sbt", "project/build.properties"}
    return {
        "project_id": str(uuid4()),
        "target_selection": selection_for(ExecutionTarget(target)).to_snapshot(),
        "fixed_files": [
            file_entry(name, data, "application/octet-stream")
            for name, data in sorted(fixed.items())
        ],
        "build_recipe_view": "PINNED_BUILD_DEFINITIONS_V1",
        "build_recipes": {
            name: raw.decode("utf-8") for name, raw in sorted(fixed.items()) if name in recipes
        },
        "build_recipe_metadata_only": sorted(set(fixed) - recipes),
        **{kind: {"content": content} for kind, content in contents.items()},
        "provenance_references": [
            {
                "kind": kind.upper(),
                "reference_id": f"development.{kind}.{uuid4().hex}",
                "version_number": 1,
                "content_hash": digest(content),
            }
            for kind, content in sorted(contents.items())
        ],
    }


async def generate_development(args):
    """Explicit real inference only; execution remains a separate user-invoked command."""
    configuration = GovernedJvmSettings(_env_file=None, **read_snapshot(args.configuration))
    fixed = pinned_build_files(ExecutionTarget(args.target), repo_root=configuration.repo_root)
    payload = generation_context(args.target, fixed)
    output = args.output.absolute()
    regular_path(output)
    output.mkdir(parents=True, exist_ok=False)
    records_root = output / "model-evidence"
    records_root.mkdir()
    store = FileEvidence(records_root)
    write_json(output / "context.json", payload)
    write_json(output / "independent-contract.json", calculator_contract(args.target))
    owner = uuid4()
    report = {
        "mode": MODE,
        "scope": SCOPE,
        "target": args.target,
        "passed": False,
        "checks": [],
        "executed_application": False,
        "database_publication": False,
        "level_d_publication": False,
    }
    try:
        generator = build_proposal_generator(args.runtime_config.absolute())
        proposal = await GenerationOperation(
            store, ModelSourceProposalAdapter(generator), payload
        ).run(owner_user_id=owner, project_id=UUID(payload["project_id"]))
        write_json(output / "proposal.json", wire_value(proposal))
        now = datetime.now(UTC)
        source = create_jvm_source_revision(
            revision_id=uuid4(),
            project_id=UUID(payload["project_id"]),
            created_by_user_id=owner,
            version_number=1,
            based_on=None,
            target=ExecutionTarget(args.target),
            origin=JvmSourceOrigin.GENERATED_PLAN,
            files=tuple(JvmSourceFileEntry(**entry) for entry in proposal.source_binding["files"]),
            provenance_references=tuple(
                JvmSourceProvenanceReference(
                    **{**ref, "kind": JvmSourceProvenanceKind(ref["kind"])}
                )
                for ref in proposal.source_binding["provenance_references"]
            ),
            created_at=now,
        ).to_snapshot()
        evidence = signed(
            {
                "schema_version": 1,
                "scope": SCOPE,
                "mode": MODE,
                "generation_id": next(iter(store.records)),
                "recorded_at": now.isoformat(),
                "publication_state": "LOCAL_GENERATION_ONLY",
                "source_revision": source,
                "generations": list(store.records.values()),
            }
        )
        check_generation_binding(source, evidence)
        sources = {
            **fixed,
            **{
                file.normalized_path: file.content.encode("utf-8") for file in proposal.output.files
            },
        }
        revision = source_revision(source, args.target)
        verify_source_policy(revision, sources, repo_root=configuration.repo_root)
        destination = output / "sources"
        destination.mkdir()
        for name, data in sources.items():
            path = destination / name
            regular_path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        read_sources(revision, destination)
        write_json(output / "source-revision.json", source)
        write_json(output / "generation-evidence.json", evidence)
        report.update(
            passed=True,
            generation_id=evidence["generation_id"],
            source_content_hash=source["content_hash"],
            model_identity=generator.configuration.identity.to_snapshot(),
        )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report["failure"] = type(error).__name__ + ":" + str(error)
    finally:
        write_json(output / "report.json", signed(report))
    return report
