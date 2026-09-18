#!/usr/bin/env python3
"""Versioned inference experiment: first responses and at most one explicit retry.

Only request messages, a pinned adapter and code enter the cloud bundle. Gold
labels and the historical scorer stay local. Every native attempt is retained.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import queue
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.final_evaluator_gateway import model_visible_messages  # noqa: E402
from orchestwin.models.structured_generation import (  # noqa: E402
    ModelRuntimeIdentity,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    normalize_required_text,
    snapshot_content_hash,
)
from orchestwin.training.evaluator_coherence import (  # noqa: E402
    VERSION,
    check_coherence,
    repair_instruction,
)

PREFIX = "ORCHESTWIN_EVALUATOR_EVENT "
REPAIR_PROMPT_VERSION = VERSION + "-normalized-retry-v2"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_for(case, identity, run_id):
    user = json.loads(case["messages"][1]["content"])
    request = create_structured_generation_request(
        request_id=uuid5(NAMESPACE_URL, run_id + ":" + case["id"]),
        task_id=user["task_id"],
        expected_identity=identity,
        output_schema=create_structured_json_schema(
            schema_id="evaluator-validation-schema",
            version_number=1,
            schema_payload=user["output_schema"],
        ),
        system_instruction=case["messages"][0]["content"],
        input_payload=user["input"],
        allowed_evidence_refs=tuple(user["allowed_evidence_refs"]),
        prompt_version_ref=case.get("prompt_version_ref", VERSION),
        temperature=0,
        max_output_tokens=2048,
        timeout_seconds=180,
    )
    if model_visible_messages(request) != case["messages"]:
        raise ValueError("model-visible messages changed during hydration")
    return request


def repair_case(case, first_raw, errors):
    """Normalize the retry presentation while retaining the original response hash.

    The structured gateway accepts whitespace-normalized system instructions.
    Native outputs stay untouched; this version explicitly records the change in
    their presentation to the model and never changes the original user message.
    """
    messages = [dict(message) for message in case["messages"]]
    context = (
        messages[0]["content"]
        + " The previous response below is presented with whitespace normalized; "
        "its exact native bytes are retained separately." + repair_instruction(first_raw, errors)
    )
    messages[0]["content"] = normalize_required_text(
        context, label="repair system instruction", maximum_length=16_000
    )
    return dict(
        case,
        id=case["id"] + "-repair",
        parent_id=case["id"],
        messages=messages,
        prompt_version_ref=REPAIR_PROMPT_VERSION,
        previous_raw_sha256=hashlib.sha256(first_raw.encode("utf-8")).hexdigest(),
        previous_response_presentation="WHITESPACE_NORMALIZED_NATIVE_TEXT",
    )


def verify_identity(identity, adapter):
    revision = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
    if (
        identity.base_model_repository != "Qwen/Qwen3-4B-Instruct-2507"
        or identity.base_model_revision != revision
        or identity.tokenizer_revision != revision
        or identity.adapter_id != "experimental-" + adapter["weights_sha256"][:16]
        or identity.adapter_sha256
        != snapshot_content_hash(
            {
                "adapter_model.safetensors": adapter["weights_sha256"],
                "adapter_config.json": adapter["config_sha256"],
            }
        )
    ):
        raise ValueError("worker identity differs from pinned candidate")


def ready_guard(bundle, output, deadline):
    guard = json.loads((bundle / "guard.json").read_bytes())
    if not (
        guard["stage"] == "ARMED"
        and guard["pod_id"] == os.environ["RUNPOD_POD_ID"]
        and 0 <= time.time() - guard["updated_unix"] < 180
        and guard["run_directory"] == str(output)
    ):
        raise ValueError("fresh bound compute guard required")
    if time.time() >= deadline - 240 or (output / "STOP_REQUESTED").exists():
        raise TimeoutError("night experiment deadline reached")


def verify_runtime(bundle):
    import torch

    expected = json.loads((bundle / "expected-runtime.json").read_bytes())
    actual = dict(
        python=platform.python_version(),
        packages={name: importlib.metadata.version(name) for name in expected["packages"]},
        cuda=torch.version.cuda,
        gpu=torch.cuda.get_device_name(0),
        vram=torch.cuda.get_device_properties(0).total_memory,
        lock_sha256=digest(ROOT / "environments/training/uv.lock"),
    )
    if actual != expected:
        raise ValueError("runtime differs from the frozen native baseline")
    return actual


def run(bundle, output):
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    for name, expected in manifest["files"].items():
        if digest(bundle / name) != expected:
            raise ValueError("sealed operator or input changed: " + name)
    protocol = json.loads((bundle / "protocol.json").read_bytes())
    cases = json.loads((bundle / "cases.json").read_bytes())
    if len(cases) != 428 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("fixed 428-case screen required")
    adapter = json.loads((bundle / "adapter.json").read_bytes())
    for name, key in (
        ("adapter_model.safetensors", "weights_sha256"),
        ("adapter_config.json", "config_sha256"),
    ):
        if digest(Path(adapter["path"]) / name) != adapter[key]:
            raise ValueError("adapter changed")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(adapter["path"], local_files_only=True)
    output.mkdir(exist_ok=False)
    done, skipped, retry_cases = [], [], []
    started = time.monotonic()
    save(output / "index.json", done)

    def progress(stage):
        save(
            output / "progress.json",
            dict(
                stage=stage,
                global_step=len(done),
                max_steps=428 + len(retry_cases),
                first_completed=sum(r["attempt"] == "first" for r in done),
                repair_completed=sum(r["attempt"] == "repair" for r in done),
                repair_planned=len(retry_cases),
                skipped_repairs=len(skipped),
                active_seconds=time.monotonic() - started,
                updated_unix=time.time(),
                training=False,
                eta_seconds=None,
            ),
        )

    def export():
        files = sorted(
            p for p in output.rglob("*") if p.is_file() and p.suffix in (".json", ".log", ".py")
        )
        files += [
            bundle / name for name in ("manifest.json", "protocol.json", "source-inventory.json")
        ]
        inventory = {
            str(p.relative_to(bundle.parent)).replace("\\", "/"): {
                "sha256": digest(p),
                "bytes": p.stat().st_size,
            }
            for p in files
        }
        temporary = bundle / "results.tar.gz.part"
        with tarfile.open(temporary, "w:gz", compresslevel=1) as stream:
            for path in files:
                stream.add(
                    path, arcname=path.relative_to(bundle.parent).as_posix(), recursive=False
                )
        destination = bundle / "results.tar.gz"
        temporary.replace(destination)
        save(
            bundle / "export-receipt.json",
            dict(
                archive_sha256=digest(destination),
                archive_bytes=destination.stat().st_size,
                inventory=inventory,
            ),
        )

    def execute(selected, attempt):
        for offset in range(0, len(selected), 128):
            ready_guard(bundle, output, protocol["deadline_unix"])
            batch = selected[offset : offset + 128]
            directory = output / f"{attempt}-{offset // 128:02}"
            events = queue.Queue()
            command = [
                sys.executable,
                "-u",
                str(ROOT / "environments/training/evaluator_candidate_worker.py"),
                "--adapter",
                adapter["path"],
                "--weights-sha256",
                adapter["weights_sha256"],
                "--config-sha256",
                adapter["config_sha256"],
                "--output",
                str(directory),
                "--decoding",
                "schema",
                "--max-requests",
                str(len(batch)),
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )

            def collect(proc=process, path=output / (directory.name + ".log"), channel=events):
                with path.open("x", encoding="utf-8") as log:
                    for line in proc.stdout:
                        log.write(line)
                        log.flush()
                        if line.startswith(PREFIX):
                            channel.put(json.loads(line[len(PREFIX) :]))
                channel.put({"event": "EXIT", "code": proc.wait()})

            thread = threading.Thread(target=collect, daemon=True)
            thread.start()
            try:
                progress("COHERENCE_LOADING_" + attempt.upper())
                event = events.get(timeout=900)
                if event.get("event") != "READY":
                    raise RuntimeError("worker did not become ready")
                identity = ModelRuntimeIdentity(**event["identity"])
                verify_identity(identity, adapter)
                for case in batch:
                    ready_guard(bundle, output, protocol["deadline_unix"])
                    tokens = tokenizer.apply_chat_template(
                        case["messages"],
                        tokenize=True,
                        add_generation_prompt=True,
                        return_dict=False,
                    )
                    if len(tokens) + 2048 > 6144:
                        if attempt == "first":
                            raise ValueError("first request exceeds context; no truncation allowed")
                        skipped.append(
                            dict(
                                id=case["id"],
                                parent_id=case["parent_id"],
                                reason="CONTEXT_RESERVE",
                                input_tokens=len(tokens),
                            )
                        )
                        save(output / "skipped-repairs.json", skipped)
                        continue
                    request = request_for(case, identity, protocol["run_id"])
                    process.stdin.write(json.dumps(request.to_snapshot()) + "\n")
                    process.stdin.flush()
                    event = events.get(timeout=240)
                    if (
                        event.get("event") != "RESULT"
                        or event.get("request_hash") != request.content_hash
                    ):
                        raise RuntimeError("native inference response differs")
                    path = directory / str(request.request_id) / "result.json"
                    value = json.loads(path.read_bytes())
                    if (
                        value["input_messages"] != case["messages"]
                        or value["request_hash"] != request.content_hash
                        or value["identity"] != identity.to_snapshot()
                    ):
                        raise ValueError("retained native response differs")
                    checked = check_coherence(value["raw_output"], case["messages"])
                    if not all(
                        value[k] for k in ("eos_finished", "schema_finished", "schema_valid")
                    ):
                        checked["passed"] = False
                        checked["errors"] = sorted(
                            set(checked["errors"]) | {"NATIVE_GENERATION_INCOMPLETE"}
                        )
                    row = dict(
                        id=case["id"],
                        source_id=case["source_id"],
                        cohort=case["cohort"],
                        attempt=attempt,
                        parent_id=case.get("parent_id"),
                        directory=path.parent.relative_to(output).as_posix(),
                        result_sha256=digest(path),
                        request_hash=request.content_hash,
                        coherence=checked,
                    )
                    done.append(row)
                    save(output / "index.json", done)
                    if attempt == "first" and not checked["passed"]:
                        retry_cases.append(
                            repair_case(case, value["raw_output"], checked["errors"])
                        )
                        save(output / "repair-cases.json", retry_cases)
                    progress("COHERENCE_INFERENCE_" + attempt.upper())
                    print(
                        json.dumps(
                            dict(
                                completed=len(done),
                                attempt=attempt,
                                case=case["id"],
                                coherent=checked["passed"],
                            )
                        ),
                        flush=True,
                    )
                process.stdin.close()
                if process.wait(timeout=45) != 0:
                    raise RuntimeError("worker exited unsuccessfully")
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("worker log not finalized")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            export()

    status = "COHERENCE_INFERENCE_FAILED_OUTPUTS_RETAINED"
    try:
        save(output / "contract.json", dict(runtime=verify_runtime(bundle), training=False))
        execute(cases, "first")
        execute(retry_cases, "repair")
        status = "COHERENCE_INFERENCE_COMPLETE_LOCAL_SCORING_REQUIRED"
    finally:
        progress(status)
        value = dict(
            status=status,
            training=False,
            first_completed=sum(r["attempt"] == "first" for r in done),
            repair_completed=sum(r["attempt"] == "repair" for r in done),
            repair_planned=len(retry_cases),
            skipped_repairs=skipped,
            first_coherent=sum(r["attempt"] == "first" and r["coherence"]["passed"] for r in done),
            repair_coherent=sum(
                r["attempt"] == "repair" and r["coherence"]["passed"] for r in done
            ),
            active_seconds=time.monotonic() - started,
            gold_labels_used=False,
            production_selected=False,
        )
        save(output / "phase-result.json", value)
        save(output / "training-result.json", value)
        export()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    if bundle.parent != output.parent or output == ROOT or ROOT in output.parents:
        raise ValueError("use separate sibling experiment input and output directories")
    run(bundle, output)


if __name__ == "__main__":
    main()
