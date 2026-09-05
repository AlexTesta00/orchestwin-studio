#!/usr/bin/env python3
"""Execute one immutable QLoRA smoke request through the already-tested bounded runner."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.qlora_smoke_requests import (  # noqa: E402
    QloraSmokeRequestError,
    canonical_json,
    load_request,
    sha256_bytes,
    snapshot_hash,
    verify_request_bindings,
)

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
_MAX_RUNTIME_SECONDS = 1_900


def _new_execution_root(path: Path) -> Path:
    path = path.absolute()
    artifacts = ROOT / "environments/training/artifacts"
    if ROOT not in path.parents or artifacts not in path.parents:
        raise QloraSmokeRequestError("execution output must remain inside training artifacts")
    if path.exists() or path.is_symlink():
        raise QloraSmokeRequestError("execution output must be a new directory")
    path.mkdir(parents=True)
    return path


def _write_snapshot(path: Path, payload: dict[str, object]) -> None:
    value = dict(payload)
    value["content_hash"] = snapshot_hash(value)
    path.write_bytes(canonical_json(value).encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    started = datetime.now(UTC)
    execution = {
        "schema_version": 1,
        "started_at": started.isoformat(),
        "training_gate_observed": os.environ.get(TRAINING_GATE) == "1",
        "training_executed": False,
    }
    root = None
    try:
        request = load_request(args.request)
        if os.environ.get(TRAINING_GATE) != "1":
            raise QloraSmokeRequestError(f"execution requires {TRAINING_GATE}=1")
        bindings = verify_request_bindings(ROOT, request)
        root = _new_execution_root(args.output_root)
        execution["request_id"] = request["request_id"]
        execution["request_sha256"] = request["request_sha256"]
        execution["repository_head"] = request["repository_head"]
        execution["runtime_id"] = request["runtime_id"]
        execution["owner_declarations"] = request["owner_declarations"]
        runner_output = root / "runner-output"
        approvals = request["owner_declarations"]
        command = [
            sys.executable,
            str(bindings["runner"]),
            "--prepared",
            str(bindings["prepared_root"]),
            "--tokenized",
            str(bindings["tokenized_root"]),
            "--source-evidence",
            str(bindings["source_evidence"]),
            "--collator-report",
            str(bindings["collator_report"]),
            "--output-root",
            str(runner_output),
            "--owner-id",
            str(approvals["owner_id"]),
            "--approve-fixtures",
            "--approve-model-license",
            "--approve-local-training",
        ]
        environment = dict(os.environ)
        environment.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        for key in (
            "ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK",
            "ORCHESTWIN_MODEL_SOURCE_ALLOW_NETWORK",
        ):
            environment.pop(key, None)
        execution["command"] = [Path(command[0]).name, Path(command[1]).name, *command[2:]]
        execution["network_authorized"] = False
        execution["training_call_attempted"] = True
        try:
            completed = subprocess.run(
                command,
                cwd=ROOT / "environments/training",
                env=environment,
                capture_output=True,
                text=True,
                timeout=_MAX_RUNTIME_SECONDS,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            timed_out = False
        except subprocess.TimeoutExpired as error:
            exit_code = 124
            stdout = (
                error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
            )
            stderr = (
                error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
            )
            timed_out = True
        (root / "runner.stdout.log").write_text(stdout, encoding="utf-8")
        (root / "runner.stderr.log").write_text(stderr, encoding="utf-8")
        result_path = runner_output / "result.json"
        execution.update(
            runner_exit_code=exit_code,
            timed_out=timed_out,
            runner_result_present=result_path.is_file(),
            runner_stdout_sha256=sha256_bytes(stdout.encode("utf-8")),
            runner_stderr_sha256=sha256_bytes(stderr.encode("utf-8")),
        )
        if result_path.is_file():
            result_raw = result_path.read_bytes()
            execution["runner_result_sha256"] = sha256_bytes(result_raw)
            execution["runner_result_reference"] = result_path.relative_to(root).as_posix()
            try:
                runner_result = __import__("json").loads(result_raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise QloraSmokeRequestError("runner result is not UTF-8 JSON") from error
            if not isinstance(runner_result, dict):
                raise QloraSmokeRequestError("runner result must contain a JSON object")
            execution["training_executed"] = runner_result.get("training_executed") is True
            execution["runner_status"] = runner_result.get("status")
        execution["status"] = "RUNNER_COMPLETED" if exit_code == 0 else "RUNNER_FAILED"
    except (QloraSmokeRequestError, OSError, ValueError, TypeError, KeyError) as error:
        exit_code = 22
        execution.update(
            status="REQUEST_REJECTED",
            failure_kind=type(error).__name__,
            failure_message=str(error)[:2000],
            training_call_attempted=False,
        )
        print(f"qlora_smoke_execution_failed: {type(error).__name__}: {error}", file=sys.stderr)
    if root is not None:
        execution["completed_at"] = datetime.now(UTC).isoformat()
        _write_snapshot(root / "execution.json", execution)
        print(root / "execution.json")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
