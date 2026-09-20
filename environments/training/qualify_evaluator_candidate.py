"""Qualify a hashed local evaluator on an explicit held-out cohort.

The optional two-round HTML exercise waits for exact engineering revision
decisions in the output directory. It never trains, promotes a model or uses
the application database. Raw outputs pass unchanged through native validation.
"""

# Entry point supports invocation without installing the repository package.
# ruff: noqa: E402

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from orchestwin.evaluation.aggregation import aggregate_synthetic_evaluation, finding_reference
from orchestwin.evaluation.application import ApprovedUserTwinEvaluationTarget
from orchestwin.evaluation.artifact_content import (
    CONTENT_PROMPT_VERSION,
    artifact_content_instruction,
    prepare_artifact_content,
)
from orchestwin.evaluation.artifact_content_resolution import OwnerScopedArtifactContentResolver
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.authorized_content_application import (
    AuthorizedArtifactContentEvaluationService,
)
from orchestwin.evaluation.authorized_run_application import (
    AuthorizedIndependentUserTwinEvaluationService,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    UserTwinEvaluatorConfiguration,
    canonical_profile_snapshot,
)
from orchestwin.evaluation.field_scope_prompt import field_scope_instruction
from orchestwin.evaluation.model_evaluator import (
    ModelGatewayUserTwinEvaluator,
    _output_schema_payload,
    _system_instruction,
)
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.training.evaluator_assessment import request_for
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

PREFIX = "ORCHESTWIN_EVALUATOR_EVENT "


def save(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, default=str)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wsl(path):
    return str(path).replace("\\", "/").replace("C:/", "/mnt/c/", 1)


def now():
    return datetime.now(UTC)


class Port:
    def __init__(self, folder, adapter, weights, config, max_requests):
        self.folder = folder
        self.events = queue.Queue()
        self.results = []
        self.worker = folder / "worker"
        convert = wsl if os.name == "nt" else str
        command = (["wsl.exe", "--exec"] if os.name == "nt" else []) + [
            convert(ROOT / "environments/training/.venv/bin/python"),
            "-u",
            convert(ROOT / "environments/training/evaluator_candidate_worker.py"),
            "--adapter",
            convert(adapter),
            "--weights-sha256",
            weights,
            "--config-sha256",
            config,
            "--output",
            convert(self.worker),
            "--decoding",
            "schema",
            "--max-requests",
            str(max_requests),
        ]
        save(
            folder / "launch.json",
            {
                "command": command,
                "network": False,
                "training": False,
                "production_promotion": False,
            },
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.thread = threading.Thread(target=self.collect, daemon=True)
        self.thread.start()

    def start(self):
        ready = self.events.get(timeout=900)
        if ready.get("event") != "READY":
            raise RuntimeError("candidate worker did not load")
        self.identity = ModelRuntimeIdentity(**ready["identity"])
        save(self.folder / "identity.json", ready["identity"])

    def collect(self):
        with (
            (self.folder / "worker.log").open("x", encoding="utf-8") as log,
            self.process.stdout as stream,
        ):
            for line in stream:
                log.write(line)
                log.flush()
                if line.startswith(PREFIX):
                    self.events.put(json.loads(line[len(PREFIX) :]))
        self.events.put({"event": "EXIT", "code": self.process.wait()})

    async def generate(self, request):
        return await asyncio.to_thread(self.generate_sync, request)

    def generate_sync(self, request):
        self.process.stdin.write(json.dumps(request.to_snapshot()) + "\n")
        self.process.stdin.flush()
        event = self.events.get(timeout=300)
        if event.get("event") != "RESULT" or event["request_hash"] != request.content_hash:
            raise RuntimeError("candidate response missing or not bound to the exact request")
        case = self.worker / str(request.request_id)
        result = json.loads((case / "result.json").read_text(encoding="utf-8"))
        if (
            json.loads((case / "request.json").read_text(encoding="utf-8")) != request.to_snapshot()
            or result["request_hash"] != request.content_hash
            or result["identity"] != self.identity.to_snapshot()
        ):
            raise ValueError("Retained evaluator request or response identity changed")
        self.results.append(result)
        if (
            not result["schema_valid"]
            or not result["eos_finished"]
            or not result["schema_finished"]
        ):
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL,
                code=StructuredGenerationFailureCode.INCOMPLETE_OUTPUT,
                message="Unmodified candidate output did not complete the requested schema.",
                retryable=False,
            )
        return successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL,
            success=create_structured_generation_success(
                payload=strict_json_object(result["raw_output"]),
                actual_identity=self.identity,
                usage=StructuredGenerationUsage(
                    result["input_tokens"], result["output_tokens"], result["latency_milliseconds"]
                ),
                finish_reason=StructuredGenerationFinishReason.STOP,
                provider_request_id=str(request.request_id),
            ),
        )

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Owned evaluator process did not terminate on EOF") from None
        self.thread.join(timeout=5)
        save(
            self.folder / "process-result.json",
            {"exit_code": self.process.returncode, "requests": len(self.results)},
        )


def evaluator(port, content=None):
    return ModelGatewayUserTwinEvaluator(
        configuration=UserTwinEvaluatorConfiguration(
            "qualification.user-twin-evaluator",
            "1",
            port.identity.content_hash,
            CONTENT_PROMPT_VERSION,
        ),
        model_identity=port.identity,
        generation_port=port,
        request_id_factory=uuid4,
        clock=now,
        max_output_tokens=1400,
        timeout_seconds=180,
        system_instruction=artifact_content_instruction(
            field_scope_instruction(
                _system_instruction(), _output_schema_payload(require_finding_id_pattern=True)
            )
        ),
        output_schema_version=2,
        verified_content=content,
    )


def calibration_operator():
    spec = importlib.util.spec_from_file_location(
        "calibration_operator", ROOT / "environments/training/run_evaluator_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_cohort(data, split="test", group_file=None):
    _, rows = calibration_operator().read_data(data)
    values = rows[split]
    available = {r["group_id"] for r in values}
    if group_file is None:
        groups = {
            min(r["group_id"] for r in values if r["family"] == family)
            for family in {r["family"] for r in values}
        }
    else:
        selection = json.loads(group_file.read_text(encoding="utf-8"))
        if (
            selection["dataset_manifest_sha256"] != digest((data / "manifest.json").read_bytes())
            or selection["split"] != split
        ):
            raise ValueError("Cohort selection belongs to another dataset or split")
        requested = selection["group_ids"]
        if (
            not isinstance(requested, list)
            or not requested
            or any(not isinstance(x, str) for x in requested)
        ):
            raise ValueError("Cohort must contain explicit group IDs")
        groups = set(requested)
        if len(groups) != len(requested) or not groups <= available:
            raise ValueError("Cohort has duplicate or unknown groups")
    selected = sorted(
        (r for r in values if r["group_id"] in groups),
        key=lambda r: (r["family"], r["group_id"], r["locale"], r["judgement"]),
    )
    if not 1 <= len(selected) <= 252:
        raise ValueError("Cohort exceeds the bounded evaluation request count")
    return selected


async def benchmark(port, folder, data, selected, split):
    module = calibration_operator()
    groups = {row["group_id"] for row in selected}
    out = folder / "benchmark"
    out.mkdir()
    save(
        out / "protocol.json",
        {
            "dataset_manifest_sha256": digest((data / "manifest.json").read_bytes()),
            "selected_groups": sorted(groups),
            "cases": len(selected),
            "split": split,
            "max_output_tokens": 1400,
            "max_sequence": 6144,
            "timeout_seconds": 180,
            "condition": "REAL_NATIVE_MODEL_GATEWAY_V3_BOUND_ARTIFACT_IDS_WITH_SCHEMA_DECODING",
            "selection": "Whole explicit groups in selection.json, both locales and all states; no retries.",
            "threshold": {
                "each_state_minimum_fraction": 10 / 12,
                "all_responses_domain_accepted": True,
            },
            "formal_case": False,
            "model_training": False,
        },
    )
    save(
        out / "selection.json",
        [{k: r[k] for k in ("group_id", "family", "locale", "judgement")} for r in selected],
    )
    results = []
    for ordinal, row in enumerate(selected, 1):
        request = request_for(row)
        user = json.loads(row["messages"][1]["content"])
        content = None
        supplied = user["input"].get("verified_artifact_content")
        if supplied:
            item = supplied["items"][0]
            ref = request.artifact_bundle.artifacts[0]
            prepared = prepare_artifact_content(
                request,
                selected=((ref.artifact_id, ref.version_number),),
                read_content=lambda *_, item=item: item["data"].encode(),
            )
            request, content = prepared.request, prepared.content
        result = {
            "ordinal": ordinal,
            "family": row["family"],
            "locale": row["locale"],
            "judgement": row["judgement"],
            "domain_accepted": False,
        }
        start = len(port.results)
        try:
            response = await evaluator(port, content).evaluate(request)
            result["domain_accepted"] = True
            result["response"] = response.to_snapshot()
        except Exception as error:
            result.update(error_type=type(error).__name__, error=str(error)[:300])
        if len(port.results) != start + 1:
            raise RuntimeError("Benchmark did not retain exactly one real inference")
        raw = port.results[-1]
        assessment = module.assess(raw["raw_output"], row)
        result.update(
            assessment=assessment,
            request_hash=raw["request_hash"],
            passed=result["domain_accepted"] and assessment["passed"],
        )
        save(out / f"{ordinal:02d}.json", result)
        results.append(result)
        print(
            json.dumps(
                {"benchmark": ordinal, "state": row["judgement"], "passed": result["passed"]}
            ),
            flush=True,
        )
    per_state = {
        s: sum(r["passed"] for r in results if r["judgement"] == s)
        for s in ("INSUFFICIENT", "MISSING", "PRESENT")
    }
    save(
        out / "result.json",
        {
            "per_state": per_state,
            "state_totals": {s: sum(r["judgement"] == s for r in results) for s in per_state},
            "domain_accepted": sum(r["domain_accepted"] for r in results),
            "passed": sum(r["passed"] for r in results),
            "cases": len(results),
            "production_promotion": False,
        },
    )


class OwnedSource:
    def __init__(self, owner, bundle, raw):
        self.owner, self.bundle, self.raw = owner, bundle, raw

    async def resolve_owned_artifact(self, **scope):
        ref = self.bundle.artifacts[0]
        return (
            ref
            if scope
            == {
                "owner_user_id": self.owner,
                "project_id": self.bundle.project_id,
                "workflow_run_id": self.bundle.workflow_run_id,
                "artifact_id": ref.artifact_id,
                "version_number": ref.version_number,
            }
            else None
        )

    def read_content(self, key, maximum_bytes):
        if key != self.bundle.artifacts[0].storage_key or len(self.raw) > maximum_bytes:
            raise ValueError("Owned prototype content request differs")
        return self.raw


def reviewed_revision(decision, *, raw, evaluation_hash, finding_refs):
    """Bind a delegated engineering decision to the exact bytes and real findings."""
    if (
        decision["base_artifact_hash"] != digest(raw)
        or decision["evaluation_hash"] != evaluation_hash
        or not isinstance(decision.get("reason"), str)
        or len(decision["reason"].strip()) < 10
    ):
        raise ValueError("Revision decision differs from the reviewed artifact or evaluation")
    if decision["action"] == "STOP":
        return None
    selected = decision.get("supported_finding_refs")
    if (
        decision["action"] != "APPROVE"
        or not isinstance(selected, list)
        or not selected
        or any(not isinstance(ref, str) for ref in selected)
        or len(set(selected)) != len(selected)
        or not set(selected) <= set(finding_refs)
    ):
        raise ValueError("Revision needs approval bound to existing supported findings")
    replacement = decision["replacement_html"].encode()
    if not 0 < len(replacement) <= 8192 or replacement == raw or b"\x00" in replacement:
        raise ValueError("Revision must contain bounded changed HTML bytes")
    return replacement


async def journey(port, folder):
    out = folder / "iterations"
    out.mkdir()
    owner, project, workflow, artifact, scenario = (uuid4() for _ in range(5))
    targets = []
    for name, role in [
        ("Receptionist keyboard user", "Completes reservations using keyboard navigation"),
        (
            "Occasional receptionist",
            "Needs explicit names for controls while learning the reservation workflow",
        ),
    ]:
        profile, sha = canonical_profile_snapshot(
            {
                "name": name,
                "role": role,
                "goals": ["Identify the guest-name input and save action without guessing"],
            }
        )
        twin = EvaluationUserTwinProfile(
            twin_id=uuid4(),
            version_number=1,
            name=name,
            lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
            content_hash=sha,
            snapshot_json=profile,
        )
        targets.append(ApprovedUserTwinEvaluationTarget(twin=twin, evidence=()))
    save(
        out / "protocol.json",
        {
            "owner": str(owner),
            "project": str(project),
            "workflow": str(workflow),
            "twins": [t.twin.to_snapshot() for t in targets],
            "scope": "ENGINEERING_PROTOTYPE_ITERATIONS_THROUGH_NATIVE_AUTHORIZATION_AND_AGGREGATION",
            "upstream_artifacts": "SYNTHETIC_CONTROLLED_HTML_PROTOTYPE",
            "decisions": "Delegated engineering review under user authorization; not personal owner UI actions or participant feedback.",
            "revisions": "External immutable artifact versions; no application database or C94 modified.",
            "independent_calls_per_round": 2,
            "rounds": 2,
            "model_training": False,
            "formal_case": False,
            "empirical_human_validation": False,
        },
    )
    raw = b'<!doctype html><html lang="en"><head><title>Reservation</title></head><body><h1>Guest reservation</h1><form id="reservation-form"><input id="guest-name" name="guest_name" required><button id="save-reservation" type="submit"></button><p id="reservation-status" role="status"></p></form></body></html>'
    completed = 0
    for version in (1, 2):
        trial = out / f"round-{version:02d}"
        trial.mkdir()
        (trial / "artifact.html").write_bytes(raw)
        sha = digest(raw)
        ref = EvaluationArtifactReference(
            artifact_id=artifact,
            version_number=version,
            kind=EvaluationArtifactKind.DOM_SNAPSHOT,
            media_type="text/html",
            sha256_digest=sha,
            size_bytes=len(raw),
            storage_key=f"sha256/{sha[:2]}/{sha}",
            location="dom:#reservation-form",
        )
        bundle = create_evaluation_artifact_bundle(
            project_id=project,
            workflow_run_id=workflow,
            scenario=EvaluationScenario(
                id=scenario,
                name="Identify reservation form controls",
                task="Inspect the supplied #reservation-form. Determine whether #guest-name has an associated nonempty label and #save-reservation has a nonempty accessible name. Report only supported missing labels; unrelated page text is not a label. Do not predict actual user behavior.",
                locale="en",
                expected_outcomes=(
                    "The guest-name input has an associated label.",
                    "The save-reservation button has a nonempty accessible name.",
                ),
            ),
            artifacts=(ref,),
            created_at=now(),
        )
        save(trial / "bundle.json", bundle.to_snapshot())
        service = AuthorizedIndependentUserTwinEvaluationService(
            authorized_evaluation_service=AuthorizedArtifactContentEvaluationService(
                resolver=OwnerScopedArtifactContentResolver(OwnedSource(owner, bundle, raw)),
                evaluator_factory=lambda *, verified_content: evaluator(port, verified_content),
            ),
            identifier_provider=uuid4,
            clock=now,
        )
        try:
            run = await service.evaluate(
                owner_user_id=owner,
                artifact_bundle=bundle,
                targets=targets,
                selected=((artifact, version),),
            )
            save(trial / "evaluation.json", run.to_snapshot())
            aggregation = aggregate_synthetic_evaluation(run)
            save(trial / "aggregation.json", aggregation.to_snapshot())
        except Exception as error:
            save(trial / "failure.json", {"error_type": type(error).__name__, "error": str(error)})
            break
        save(
            trial / "review-request.json",
            {
                "artifact_hash": sha,
                "evaluation_hash": run.content_hash,
                "finding_references": [finding_reference(f) for f in run.findings],
            },
        )
        print("ENGINEERING_REVIEW_READY " + str(trial), flush=True)
        deadline = time.monotonic() + 900
        decision_path = trial / "revision-decision.json"
        while not decision_path.exists() and time.monotonic() < deadline:
            await asyncio.sleep(1)
        if not decision_path.exists():
            raise RuntimeError("Engineering revision review not received")
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        replacement = reviewed_revision(
            decision,
            raw=raw,
            evaluation_hash=run.content_hash,
            finding_refs=[finding_reference(f) for f in run.findings],
        )
        if replacement is None:
            break
        save(
            trial / "applied-revision.json",
            {
                "previous_version": version,
                "new_version": version + 1,
                "base_artifact_hash": sha,
                "new_artifact_hash": digest(replacement),
                "evaluation_hash": run.content_hash,
                "aggregation_hash": aggregation.content_hash,
                "decision_sha256": digest(decision_path.read_bytes()),
                "model_output_modified": False,
            },
        )
        raw = replacement
        completed += 1
    (out / "final-artifact.html").write_bytes(raw)
    save(
        out / "result.json",
        {
            "completed_revision_iterations": completed,
            "independent_twins": 2,
            "final_version": completed + 1,
            "final_artifact_sha256": digest(raw),
            "formal_case": False,
            "human_validation": False,
        },
    )


async def run(port, folder, data, selected, split, iterations):
    await benchmark(port, folder, data, selected, split)
    if iterations:
        await journey(port, folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--group-ids", type=Path)
    parser.add_argument("--iterations", type=int, choices=(0, 2), default=0)
    args = parser.parse_args()
    folder = args.output.absolute()
    if (
        ".." in folder.parts
        or folder == ROOT
        or ROOT in folder.parents
        or args.data.absolute() in (folder, *folder.parents)
        or args.adapter.absolute() in (folder, *folder.parents)
        or any(p.is_symlink() or p.is_junction() for p in (folder, *folder.parents))
    ):
        raise ValueError("Use a new external qualification directory without links")
    selected = select_cohort(args.data, args.split, args.group_ids)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "operator.py").write_bytes(Path(__file__).read_bytes())
    port = None
    try:
        port = Port(
            folder,
            args.adapter.absolute(),
            args.weights_sha256,
            args.config_sha256,
            len(selected) + args.iterations * 2,
        )
        port.start()
        asyncio.run(
            run(port, folder, args.data, selected, args.split, args.iterations),
            loop_factory=asyncio.SelectorEventLoop,
        )
    except Exception as error:
        save(folder / "failure.json", {"error_type": type(error).__name__, "error": str(error)})
        raise
    finally:
        if port:
            port.close()


if __name__ == "__main__":
    main()
