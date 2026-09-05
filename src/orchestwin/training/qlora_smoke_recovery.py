"""Post-training evidence contracts for QLoRA adapter reload and checkpoint recovery.

This module validates a completed bounded smoke run and its immutable request. It does
not load GPU libraries and never authorizes or executes additional training steps.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from orchestwin.training.qlora_smoke_collation import (
    canonical_bytes,
    checked_path,
    read_snapshot,
    sha256,
)
from orchestwin.training.qlora_smoke_requests import load_request

RECOVERY_POLICY_ID: Final = "qlora-smoke-recovery-v1"
COMPLETED_TRAINING_STATUS: Final = "SMOKE_TRAINING_COMPLETED_RELOAD_PENDING"
COMPLETED_EXECUTION_STATUS: Final = "RUNNER_COMPLETED"
REQUIRED_CHECKPOINT_STEPS: Final = (4, 8)
REQUIRED_RESUME_FILES: Final = frozenset(
    {
        "trainer_state.json",
        "adapter_config.json",
        "adapter_model.safetensors",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    }
)
_MAX_SMALL_JSON_BYTES: Final = 8_000_000


class SmokeRecoveryError(ValueError):
    """Completed smoke artifacts cannot support a trustworthy recovery verification."""


@dataclass(frozen=True, slots=True)
class RecoveryBundle:
    repository: Path
    training_root: Path
    request: dict[str, Any]
    execution: dict[str, Any]
    result: dict[str, Any]
    bindings: dict[str, Path]
    adapter_root: Path
    checkpoint_roots: dict[int, Path]

    @property
    def checkpoint8(self) -> Path:
        return self.checkpoint_roots[8]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, *, limit: int | None = None) -> Path:
    path = checked_path(path)
    if not path.is_file():
        raise SmokeRecoveryError(f"expected regular file: {path.name}")
    if limit is not None and path.stat().st_size > limit:
        raise SmokeRecoveryError(f"file exceeds recovery size limit: {path.name}")
    return path


def _safe_relative(reference: object) -> PurePosixPath:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise SmokeRecoveryError("request reference must use relative POSIX syntax")
    pure = PurePosixPath(reference)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SmokeRecoveryError("request reference is unsafe")
    return pure


def resolve_historical_bindings(
    repository_root: Path,
    request: dict[str, Any],
) -> dict[str, Path]:
    """Verify request anchors without requiring the repository HEAD to remain the training HEAD.

    A post-training verifier is necessarily committed after the training run. Exact input and
    runner bytes remain bound by the immutable request SHA-256 anchors.
    """
    repository = checked_path(repository_root)
    references = request.get("references")
    anchors = request.get("anchor_sha256")
    if not isinstance(references, dict) or not isinstance(anchors, dict):
        raise SmokeRecoveryError("request bindings are missing")

    required = {
        "prepared_root",
        "tokenized_root",
        "source_evidence",
        "collator_report",
        "license_audit",
        "runner",
        "uv_lock",
        "environment",
    }
    if set(references) != required:
        raise SmokeRecoveryError("request references differ from the required recovery set")

    paths: dict[str, Path] = {}
    for label, reference in references.items():
        pure = _safe_relative(reference)
        path = repository.joinpath(*pure.parts).absolute()
        try:
            path.relative_to(repository)
        except ValueError as error:
            raise SmokeRecoveryError(f"request reference escapes repository: {label}") from error
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise SmokeRecoveryError(f"request reference traverses symbolic links: {label}")
        paths[label] = path

    files = {
        "preparation.json": paths["prepared_root"] / "preparation.json",
        "tokenization-report.json": paths["tokenized_root"] / "tokenization-report.json",
        "source-evidence.json": paths["source_evidence"],
        "collator-report.json": paths["collator_report"],
        "license-audit.json": paths["license_audit"],
        "run_qlora_smoke.py": paths["runner"],
        "uv.lock": paths["uv_lock"],
        "environment.json": paths["environment"],
    }
    if set(anchors) != set(files):
        raise SmokeRecoveryError("request anchor set changed")

    for label, path in files.items():
        _regular_file(path)
        if sha256_file(path) != anchors[label]:
            raise SmokeRecoveryError(f"historical request anchor changed: {label}")

    return paths


def _inventory_map(recorded: object) -> dict[str, tuple[int, str]]:
    if not isinstance(recorded, list) or not recorded:
        raise SmokeRecoveryError("artifact inventory must be a nonempty list")
    parsed: dict[str, tuple[int, str]] = {}
    for item in recorded:
        if not isinstance(item, dict):
            raise SmokeRecoveryError("artifact inventory row must be an object")
        reference = item.get("path")
        size = item.get("size_bytes")
        digest = item.get("sha256")
        pure = _safe_relative(reference)
        normalized = pure.as_posix()
        if (
            normalized in parsed
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SmokeRecoveryError("artifact inventory row is invalid")
        parsed[normalized] = (size, digest)
    return parsed


def verify_inventory(root: Path, recorded: object) -> dict[str, tuple[int, str]]:
    """Match every recorded artifact path, size and digest against current immutable bytes."""
    root = checked_path(root)
    if not root.is_dir():
        raise SmokeRecoveryError("artifact inventory root must be a directory")
    expected = _inventory_map(recorded)
    actual_paths: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SmokeRecoveryError("recovery artifact contains a symbolic link")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            actual_paths[relative] = path
    if set(actual_paths) != set(expected):
        raise SmokeRecoveryError("artifact inventory file set changed")
    for relative, (size, digest) in expected.items():
        path = actual_paths[relative]
        if path.stat().st_size != size or sha256_file(path) != digest:
            raise SmokeRecoveryError(f"artifact bytes changed: {relative}")
    return expected


def _load_json(path: Path) -> dict[str, Any]:
    path = _regular_file(path, limit=_MAX_SMALL_JSON_BYTES)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeRecoveryError(f"invalid UTF-8 JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise SmokeRecoveryError(f"expected JSON object: {path.name}")
    return value


def _validate_result_contract(
    *,
    request: dict[str, Any],
    execution: dict[str, Any],
    result: dict[str, Any],
    result_sha256: str,
) -> None:
    if any(
        (
            execution.get("status") != COMPLETED_EXECUTION_STATUS,
            execution.get("runner_exit_code") != 0,
            execution.get("training_executed") is not True,
            execution.get("runner_result_present") is not True,
            execution.get("runner_result_sha256") != result_sha256,
            execution.get("request_id") != request.get("request_id"),
            execution.get("request_sha256") != request.get("request_sha256"),
            execution.get("repository_head") != request.get("repository_head"),
            execution.get("runtime_id") != request.get("runtime_id"),
        )
    ):
        raise SmokeRecoveryError("execution report does not bind the completed owner request")

    if any(
        (
            result.get("runtime_id") != request.get("runtime_id"),
            result.get("status") != COMPLETED_TRAINING_STATUS,
            result.get("training_executed") is not True,
            result.get("model_weights_loaded") is not True,
            result.get("model_selected") is not False,
            result.get("full_training_approved") is not False,
            result.get("network_authorized") is not False,
            result.get("implementation_sha256")
            != request.get("anchor_sha256", {}).get("run_qlora_smoke.py"),
        )
    ):
        raise SmokeRecoveryError("runner result is not the completed bounded QLoRA smoke")

    observations = result.get("observations")
    if not isinstance(observations, dict) or any(
        (
            observations.get("global_step") != 8,
            observations.get("adapter_exported") is not True,
            observations.get("adapter_reload_status") != "NOT_RUN",
            observations.get("checkpoint_restore_status") != "NOT_RUN",
            observations.get("quality_improvement_measured") is not False,
            observations.get("serving_validated") is not False,
        )
    ):
        raise SmokeRecoveryError(
            "completed result does not leave only recovery verification pending"
        )


def load_recovery_bundle(repository_root: Path, training_root: Path) -> RecoveryBundle:
    repository = checked_path(repository_root)
    training_root = checked_path(training_root)
    artifacts = repository / "environments/training/artifacts"
    if artifacts != training_root and artifacts not in training_root.parents:
        raise SmokeRecoveryError("training root must remain inside training artifacts")
    if not training_root.is_dir():
        raise SmokeRecoveryError("training root must be an existing directory")

    request_path = _regular_file(training_root / "request.json")
    execution_path = _regular_file(training_root / "execution/execution.json")
    result_path = _regular_file(training_root / "execution/runner-output/result.json")

    request = load_request(request_path)
    execution = read_snapshot(execution_path)
    result = read_snapshot(result_path)
    bindings = resolve_historical_bindings(repository, request)
    result_digest = sha256_file(result_path)
    _validate_result_contract(
        request=request,
        execution=execution,
        result=result,
        result_sha256=result_digest,
    )

    runner_output = training_root / "execution/runner-output"
    adapter_root = checked_path(runner_output / "adapter")
    checkpoints = {
        step: checked_path(runner_output / "checkpoints" / f"checkpoint-{step}")
        for step in REQUIRED_CHECKPOINT_STEPS
    }

    observations = result["observations"]
    verify_inventory(adapter_root, observations.get("adapter_files"))

    recorded_checkpoints = observations.get("checkpoints")
    if not isinstance(recorded_checkpoints, list) or [
        item.get("step") for item in recorded_checkpoints if isinstance(item, dict)
    ] != list(REQUIRED_CHECKPOINT_STEPS):
        raise SmokeRecoveryError("completed result must bind checkpoint steps 4 and 8")

    for recorded in recorded_checkpoints:
        step = recorded["step"]
        inventory = verify_inventory(checkpoints[step], recorded.get("files"))
        if step == 8 and not set(inventory) >= REQUIRED_RESUME_FILES:
            missing = sorted(REQUIRED_RESUME_FILES - set(inventory))
            raise SmokeRecoveryError(
                "checkpoint 8 cannot exercise full Trainer resume state: " + ", ".join(missing)
            )

    trainer_state = _load_json(checkpoints[8] / "trainer_state.json")
    if trainer_state.get("global_step") != 8:
        raise SmokeRecoveryError("checkpoint 8 trainer state does not attest global_step 8")

    adapter_config = _load_json(adapter_root / "adapter_config.json")
    if adapter_config.get("base_model_name_or_path") != request.get("base_model_repository"):
        raise SmokeRecoveryError("adapter base model differs from the immutable request")

    return RecoveryBundle(
        repository=repository,
        training_root=training_root,
        request=request,
        execution=execution,
        result=result,
        bindings=bindings,
        adapter_root=adapter_root,
        checkpoint_roots=checkpoints,
    )


def recovery_identity(bundle: RecoveryBundle) -> dict[str, object]:
    observations = bundle.result["observations"]
    return {
        "request_id": bundle.request["request_id"],
        "request_sha256": bundle.request["request_sha256"],
        "training_repository_head": bundle.request["repository_head"],
        "runtime_id": bundle.request["runtime_id"],
        "candidate_id": bundle.request["candidate_id"],
        "base_model_repository": bundle.request["base_model_repository"],
        "base_model_revision": bundle.request["base_model_revision"],
        "configuration_content_hash": bundle.request["configuration_content_hash"],
        "source_training_global_step": observations["global_step"],
        "source_training_result_content_hash": bundle.result["content_hash"],
        "adapter_inventory_sha256": sha256(canonical_bytes(observations["adapter_files"])),
        "checkpoint8_inventory_sha256": sha256(
            canonical_bytes(bundle.result["observations"]["checkpoints"][1]["files"])
        ),
    }
