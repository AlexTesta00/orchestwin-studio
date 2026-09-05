"""Offline, immutable tokenizer preflight for prepared QLoRA smoke examples.

No model weights, trainer, network client, or training authorization belongs here.
Token IDs and proposed completion masks are evidence, not a successful training run.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import strict_json_loads
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.model_source_evidence import load_captured_model_source_evidence
from orchestwin.training.qlora_smoke_preparation import prepare_qlora_smoke

TOKENIZATION_POLICY_ID = "qlora-smoke-tokenization-v1"
_PREPARED_FILES = frozenset(
    {
        "preparation.json",
        "configuration.json",
        "dataset-manifest.json",
        "reanalysis-source.json",
        "train.jsonl",
        "validation.jsonl",
    }
)


class SmokeTokenizationError(ValueError):
    """Inputs or tokenizer behavior cannot support a trustworthy smoke preflight."""


@dataclass(frozen=True, slots=True)
class PreparedSmoke:
    preparation: dict[str, Any]
    configuration: dict[str, Any]
    records: tuple[dict[str, Any], ...]
    inventory: dict[str, str]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _checked_path(path: Path) -> Path:
    if ".." in path.parts:
        raise SmokeTokenizationError("parent traversal is forbidden")
    path = path.absolute()
    if any(part.is_symlink() for part in (*path.parents, path)):
        raise SmokeTokenizationError("symbolic links are forbidden in preflight paths")
    return path


def _read(path: Path, *, limit: int = 8_000_000) -> bytes:
    path = _checked_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise SmokeTokenizationError("expected a bounded regular preflight file")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise SmokeTokenizationError("file exceeded size limit while being read")
    return raw


def _object(raw: bytes) -> dict[str, Any]:
    value = strict_json_loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or _bytes(value) != raw:
        raise SmokeTokenizationError("preflight metadata must be a canonical JSON object")
    return value


def load_smoke_preparation(repository: Path, root: Path) -> PreparedSmoke:
    """Reproduce S49 artifacts from frozen fixtures rather than trusting self-reported hashes.

    The recorded S49 implementation hashes are retained as historical provenance. Their
    bytes need not equal today's formatted source. All other semantic fields must match.
    This reuses S49's report-binding scope, not an independent replay of the GPU benchmark.
    """
    root = _checked_path(root)
    if not root.is_dir() or {p.name for p in root.iterdir()} != _PREPARED_FILES:
        raise SmokeTokenizationError("prepared directory must contain exactly the six S49 files")
    raw = {name: _read(root / name) for name in sorted(_PREPARED_FILES)}
    metadata = _object(raw["preparation.json"])
    semantic = {key: value for key, value in metadata.items() if key != "content_hash"}
    if metadata.get("content_hash") != snapshot_content_hash(semantic):
        raise SmokeTokenizationError("preparation content hash changed")
    recorded = metadata.get("implementation_sha256")
    if not isinstance(recorded, dict) or set(recorded) != {
        "qlora_smoke_fixtures.py",
        "qlora_smoke_preparation.py",
    }:
        raise SmokeTokenizationError("preparation implementation provenance is missing")
    for digest in recorded.values():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise SmokeTokenizationError("invalid recorded implementation digest")
    timestamp = datetime.fromisoformat(metadata["created_at"])
    with tempfile.TemporaryDirectory(prefix="orchestwin-smoke-reproduction-") as temporary:
        expected_path = prepare_qlora_smoke(
            repository_root=repository,
            reanalysis_path=root / "reanalysis-source.json",
            candidate_id=metadata["candidate_id"],
            output_root=Path(temporary) / "expected",
            created_at=timestamp,
        )
        expected = _object(expected_path.read_bytes())
        for key in ("implementation_sha256", "content_hash"):
            expected.pop(key)
        original = {
            k: v
            for k, v in metadata.items()
            if k
            not in {
                "implementation_sha256",
                "content_hash",
            }
        }
        if _bytes(original) != _bytes(expected):
            raise SmokeTokenizationError("preparation differs from its reproducible S49 contract")
        for name in _PREPARED_FILES - {"preparation.json"}:
            if raw[name] != (expected_path.parent / name).read_bytes():
                raise SmokeTokenizationError(
                    f"prepared artifact differs from frozen fixtures: {name}"
                )
    manifest = _object(raw["dataset-manifest.json"])
    records = []
    for split in ("train", "validation"):
        rows = [strict_json_loads(line) for line in raw[f"{split}.jsonl"].decode().splitlines()]
        entries = [item for item in manifest["entries"] if item["split"] == split]
        for row, entry in zip(rows, entries, strict=True):
            records.append({**entry, "record": row})
    return PreparedSmoke(
        metadata,
        _object(raw["configuration.json"]),
        tuple(records),
        {name: _sha(value) for name, value in raw.items()},
    )


def _ids(value: object) -> list[int]:
    if isinstance(value, Mapping):
        value = value.get("input_ids")
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value)
    ):
        raise SmokeTokenizationError("tokenizer must return a nonempty list of integer token IDs")
    return value


def audit_tokenized_record(
    record: Mapping[str, Any],
    *,
    tokenizer: Any,
    max_length: int,
    template_kwargs: dict[str, bool],
) -> tuple[dict[str, Any], dict[str, list[int]] | None]:
    """Measure the intact conversation and a prefix-based completion mask; never truncate.

    The proposed -100 labels follow completion-only supervision. This function does not
    instantiate TRL's collator or attest that a future trainer has consumed these labels.
    """
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise SmokeTokenizationError("maximum length must be a positive integer")
    prompt, completion = record["prompt"], record["completion"]
    if not isinstance(prompt, list) or not isinstance(completion, list) or len(completion) != 1:
        raise SmokeTokenizationError("expected one conversational assistant completion")
    if completion[0].get("role") != "assistant" or not completion[0].get("content"):
        raise SmokeTokenizationError("assistant content must be nonempty")
    prompt_text = tokenizer.apply_chat_template(
        prompt,
        tokenize=False,
        add_generation_prompt=True,
        **template_kwargs,
    )
    full_text = tokenizer.apply_chat_template(
        prompt + completion,
        tokenize=False,
        add_generation_prompt=False,
        **template_kwargs,
    )
    if not isinstance(prompt_text, str) or not isinstance(full_text, str):
        raise SmokeTokenizationError("chat template did not return text")
    options = {"add_special_tokens": False, "truncation": False, "padding": False}
    prompt_ids = _ids(tokenizer(prompt_text, **options))
    full_ids = _ids(tokenizer(full_text, **options))
    native_ids = _ids(
        tokenizer.apply_chat_template(
            prompt + completion,
            tokenize=True,
            add_generation_prompt=False,
            **template_kwargs,
        )
    )
    repeated_ids = _ids(tokenizer(full_text, **options))
    prefix_length = len(prompt_ids)
    suffix = full_ids[prefix_length:]
    issues = []
    if not full_text.startswith(prompt_text):
        issues.append("PROMPT_TEXT_NOT_PREFIX")
    elif not full_text[len(prompt_text) :].startswith(completion[0]["content"]):
        issues.append("ASSISTANT_CONTENT_CHANGED")
    if full_ids[:prefix_length] != prompt_ids:
        issues.append("PROMPT_TOKEN_IDS_NOT_PREFIX")
    if full_ids != native_ids:
        issues.append("NATIVE_CHAT_TOKENIZATION_DIFFERS")
    if full_ids != repeated_ids:
        issues.append("TOKENIZATION_NOT_DETERMINISTIC")
    if not suffix:
        issues.append("EMPTY_COMPLETION_TOKENS")
    eos = getattr(tokenizer, "eos_token_id", None)
    if isinstance(eos, bool) or not isinstance(eos, int) or eos not in suffix:
        issues.append("EOS_MISSING_FROM_COMPLETION")
    pad = getattr(tokenizer, "pad_token_id", None)
    if isinstance(pad, bool) or not isinstance(pad, int) or pad < 0:
        issues.append("PAD_TOKEN_UNAVAILABLE")
    if len(full_ids) > max_length:
        issues.append("SEQUENCE_OVERFLOW")
    completion_mask = [0] * min(prefix_length, len(full_ids)) + [1] * len(suffix)
    labels = [
        value if mask else -100 for value, mask in zip(full_ids, completion_mask, strict=True)
    ]
    observation = {
        "prompt_tokens": prefix_length,
        "completion_tokens": len(suffix),
        "total_tokens": len(full_ids),
        "max_sequence_length": max_length,
        "remaining_tokens": max_length - len(full_ids),
        "issues": issues,
        "prompt_text_sha256": _sha(prompt_text.encode()),
        "conversation_text_sha256": _sha(full_text.encode()),
        "input_ids_sha256": _sha(_bytes(full_ids)),
        "completion_mask_sha256": _sha(_bytes(completion_mask)),
        "proposed_labels_sha256": _sha(_bytes(labels)),
        "proposed_ignored_label_count": labels.count(-100),
        "training_collator_verified": False,
    }
    row = {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "completion_mask": completion_mask,
    }
    return observation, None if issues else row


def _output_path(repository: Path, output: Path, *protected: Path) -> Path:
    output = _checked_path(output)
    repository = repository.absolute()
    for root in protected:
        root = root.absolute()
        if output == root or root in output.parents or output in root.parents:
            raise SmokeTokenizationError("output overlaps protected inputs")
    artifacts = repository / "environments/training/artifacts"
    if output == repository or (repository in output.parents and artifacts not in output.parents):
        raise SmokeTokenizationError("repository output must be inside training artifacts")
    if output.exists():
        raise SmokeTokenizationError("output must be a new directory")
    return output


def _source_files(evidence_path: Path, repository: Path, prepared: PreparedSmoke):
    path = _checked_path(evidence_path)
    raw = _read(path)
    matrix = load_frozen_model_candidate_matrix(repository)
    evidence = load_captured_model_source_evidence(path, matrix=matrix)
    if raw != _bytes(evidence.to_snapshot()):
        raise SmokeTokenizationError("source evidence is not canonical")
    config = prepared.configuration
    if (evidence.candidate_id, evidence.repository_id, evidence.resolved_revision) != (
        config["candidate_id"],
        config["tokenizer_repository"],
        config["tokenizer_revision"],
    ):
        raise SmokeTokenizationError("tokenizer evidence differs from prepared candidate")
    files = {}
    for item in evidence.files:
        pure = PurePosixPath(item.relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise SmokeTokenizationError("unsafe tokenizer source reference")
        file = path.parent / "files" / pure
        payload = _read(file, limit=100_000_000)
        if len(payload) != item.size_bytes or _sha(payload) != item.sha256:
            raise SmokeTokenizationError(
                f"captured tokenizer source bytes changed: {item.relative_path}"
            )
        files[item.relative_path] = payload
    names = {"tokenizer.json", "tokenizer_config.json"}
    if not names <= files.keys():
        raise SmokeTokenizationError("preflight requires tokenizer.json and tokenizer_config.json")
    tokenizer_config = strict_json_loads(files["tokenizer_config.json"].decode())
    if not isinstance(tokenizer_config, dict) or "auto_map" in tokenizer_config:
        raise SmokeTokenizationError("custom remote tokenizer code is not permitted")
    if not isinstance(tokenizer_config.get("chat_template"), str):
        raise SmokeTokenizationError("captured tokenizer must contain one explicit chat template")
    return evidence, {name: files[name] for name in sorted(names)}, tokenizer_config, raw


def _package_versions() -> dict[str, str | None]:
    packages = {}
    for name in ("transformers", "tokenizers", "jinja2"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return packages


def _review_text(prepared: PreparedSmoke, observations: list[dict[str, Any]]) -> str:
    lines = [
        "# QLoRA smoke: owner review pending",
        "",
        "Assistant-authored fictional fixtures. No human approval or training is asserted.",
        "Review all 20 inputs and target answers, especially abstention and evidence refs.",
        "A successful tokenization preflight does not approve the supervision or the license.",
        "",
    ]
    for item, observation in zip(prepared.records, observations, strict=True):
        lines.extend(
            [
                f"## {item['sample_id']} | {item['split']} | {item['scenario_family_id']}",
                "",
                f"Tokens: prompt={observation['prompt_tokens']}, "
                f"completion={observation['completion_tokens']}, total={observation['total_tokens']}.",
                "",
                "### Model-visible prompt",
                "",
                "````json",
                json.dumps(item["record"]["prompt"], ensure_ascii=False, indent=2),
                "````",
                "",
                "### Supervised answer (not a model observation)",
                "",
                "````json",
                json.dumps(
                    json.loads(item["record"]["completion"][0]["content"]),
                    ensure_ascii=False,
                    indent=2,
                ),
                "````",
                "",
                "Owner decision: PENDING. Notes: ____________________",
                "",
            ]
        )
    return "\n".join(lines)


def tokenize_prepared_smoke(
    *,
    repository_root: Path,
    preparation_root: Path,
    source_evidence_path: Path,
    output_root: Path,
    created_at: datetime,
    tokenizer_loader: Callable[[Path], Any],
) -> Path:
    """Validate frozen data, load only copied tokenizer files, and write new evidence."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise SmokeTokenizationError("tokenization timestamp must be timezone-aware")
    destination = _output_path(
        repository_root, output_root, preparation_root, source_evidence_path.parent
    )
    prepared = load_smoke_preparation(repository_root, preparation_root)
    evidence, token_files, tokenizer_config, evidence_raw = _source_files(
        source_evidence_path,
        repository_root,
        prepared,
    )
    control = prepared.preparation["chat_template_control"]
    kwargs = (
        {}
        if control["mode"] == "DEFAULT_NON_THINKING"
        else {
            control["argument_name"]: control["argument_value"],
        }
    )
    records: dict[str, list[dict[str, list[int]]]] = {"train": [], "validation": []}
    observations = []
    # Only verified tokenizer metadata are visible to AutoTokenizer. No weights or
    # unrelated files from a cache snapshot can enter this temporary local directory.
    with tempfile.TemporaryDirectory(prefix="orchestwin-tokenizer-only-") as temporary:
        local = Path(temporary)
        for name, raw in token_files.items():
            (local / name).write_bytes(raw)
        tokenizer = tokenizer_loader(local)
        if getattr(tokenizer, "is_fast", False) is not True:
            raise SmokeTokenizationError("a fast local tokenizer is required")
        template = tokenizer.get_chat_template()
        if template != tokenizer_config["chat_template"]:
            raise SmokeTokenizationError("loaded chat template differs from captured source")
        for item in prepared.records:
            observation, row = audit_tokenized_record(
                item["record"],
                tokenizer=tokenizer,
                max_length=prepared.configuration["optimization"]["max_sequence_length"],
                template_kwargs=kwargs,
            )
            observations.append(
                {
                    "sample_id": item["sample_id"],
                    "split": item["split"],
                    "language": item["language"],
                    "row_index": item["row_index"],
                    "training_record_sha256": item["training_record_sha256"],
                    **observation,
                }
            )
            if row is not None:
                records[item["split"]].append(row)
        backend = getattr(tokenizer, "backend_tokenizer", None)
        backend_hash = None if backend is None else _sha(backend.to_str().encode())
        tokenizer_identity = {
            "repository_id": evidence.repository_id,
            "revision": evidence.resolved_revision,
            "revision_evidence": "CAPTURED_SNAPSHOT_FILES_SHA256",
            "live_remote_revision_query": False,
            "tokenizer_object_commit_hash_required": False,
            "source_evidence_sha256": _sha(evidence_raw),
            "source_evidence_content_hash": evidence.content_hash,
            "file_sha256": {name: _sha(raw) for name, raw in token_files.items()},
            "chat_template_sha256": _sha(template.encode()),
            "backend_serialization_sha256": backend_hash,
            "class_name": type(tokenizer).__name__,
            "eos_token_id": getattr(tokenizer, "eos_token_id", None),
            "pad_token_id": getattr(tokenizer, "pad_token_id", None),
            "bos_token_id": getattr(tokenizer, "bos_token_id", None),
            "package_versions": _package_versions(),
        }
    for name, digest in prepared.inventory.items():
        if _sha(_read(preparation_root / name)) != digest:
            raise SmokeTokenizationError("preparation changed during tokenization")
    _, after_files, _, after_evidence = _source_files(
        source_evidence_path, repository_root, prepared
    )
    if token_files != after_files or after_evidence != evidence_raw:
        raise SmokeTokenizationError("tokenizer sources changed during tokenization")
    successful = all(not item["issues"] for item in observations)
    outputs = {"review.md": _review_text(prepared, observations).encode()}
    if successful:
        for split, rows in records.items():
            outputs[f"tokenized-{split}.jsonl"] = b"".join(_bytes(row) + b"\n" for row in rows)
    report = {
        "schema_version": 1,
        "report_id": "ut-evaluator-qlora-smoke-tokenization-v1",
        "policy_id": TOKENIZATION_POLICY_ID,
        "created_at": created_at.isoformat(),
        "status": "TOKENIZATION_VERIFIED_NOT_AUTHORIZED" if successful else "TOKENIZATION_BLOCKED",
        "candidate_id": prepared.preparation["candidate_id"],
        "preparation_content_hash": prepared.preparation["content_hash"],
        "preparation_file_sha256": prepared.inventory["preparation.json"],
        "configuration_content_hash": prepared.preparation["configuration_content_hash"],
        "dataset_manifest_content_hash": prepared.preparation["dataset_manifest_content_hash"],
        "package_lock_sha256": prepared.preparation["package_lock_sha256"],
        "prepared_environment_sha256": prepared.preparation["environment_sha256"],
        "input_file_sha256": prepared.inventory,
        "tokenizer": tokenizer_identity,
        "chat_template_control": control,
        "completion_only_loss": True,
        "assistant_only_loss": False,
        "truncation": False,
        "packing": False,
        "tokenized_dataset_format": "TRL_INPUT_IDS_ATTENTION_MASK_COMPLETION_MASK",
        "loss_mask_policy": "EXACT_PROMPT_PREFIX_ZERO_COMPLETION_ONE",
        "training_label_ignore_index": -100,
        "summary": {
            "sample_count": len(observations),
            "valid_sample_count": sum(not item["issues"] for item in observations),
            "max_total_tokens": max(item["total_tokens"] for item in observations),
            "overflow_count": sum("SEQUENCE_OVERFLOW" in item["issues"] for item in observations),
        },
        "observations": observations,
        "output_file_sha256": {name: _sha(raw) for name, raw in sorted(outputs.items())},
        "network_authorized": False,
        "model_weights_loaded": False,
        "training_executed": False,
        "training_authorization": "NOT_GRANTED",
        "model_selected": False,
        "owner_fixture_review": "PENDING",
        "license_review_status": "PENDING",
        "training_collator_verified": False,
        "runner_compatibility_status": "PENDING_PREFLIGHT",
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "limitations": [
            "Tokenization and proposed completion masks are not a training/collator execution.",
            "Revision evidence binds captured snapshot file hashes; no live Hub query is performed.",
            "S49 report provenance is a self-consistency binding, not a fresh raw-bundle replay.",
        ],
    }
    report["content_hash"] = snapshot_content_hash(report)
    outputs["tokenization-report.json"] = _bytes(report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(exist_ok=False)
    for name, raw in outputs.items():
        with (destination / name).open("xb") as target:
            target.write(raw)
    return destination / "tokenization-report.json"
