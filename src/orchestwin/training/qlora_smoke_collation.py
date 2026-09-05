"""Evidence-bound completion-only collation checks, without training or downloads."""

from __future__ import annotations

import copy
import hashlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import strict_json_loads
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.model_source_evidence import load_captured_model_source_evidence
from orchestwin.training.qlora_smoke_tokenization import PreparedSmoke, load_smoke_preparation

COLLATION_POLICY_ID = "qlora-smoke-completion-collator-v1"


class SmokeCollationError(ValueError):
    """A verified smoke input or actual collator violates the completion-only contract."""


def checked_path(path: Path) -> Path:
    if ".." in path.parts:
        raise SmokeCollationError("parent traversal is forbidden")
    path = path.absolute()
    if any(part.is_symlink() for part in (*path.parents, path)):
        raise SmokeCollationError("symbolic links are forbidden")
    return path


def read_bounded(path: Path, limit: int = 8_000_000) -> bytes:
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise SmokeCollationError(f"expected bounded regular file: {path.name}")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise SmokeCollationError("input exceeded its size limit while reading")
    return raw


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def read_snapshot(path: Path) -> dict[str, Any]:
    raw = read_bounded(path)
    value = strict_json_loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or canonical_bytes(value) != raw:
        raise SmokeCollationError("expected canonical JSON object")
    expected = snapshot_content_hash({k: v for k, v in value.items() if k != "content_hash"})
    if value.get("content_hash") != expected:
        raise SmokeCollationError("snapshot content hash changed")
    return value


@dataclass(frozen=True, slots=True)
class SmokeTokenRow:
    sample_id: str
    split: str
    input_ids: tuple[int, ...]
    completion_mask: tuple[int, ...]

    def to_features(self) -> dict[str, list[int]]:
        return {
            "input_ids": list(self.input_ids),
            "attention_mask": [1] * len(self.input_ids),
            "completion_mask": list(self.completion_mask),
        }


@dataclass(frozen=True, slots=True)
class VerifiedSmokeInputs:
    repository: Path
    protected_roots: tuple[Path, ...]
    prepared: PreparedSmoke
    tokenization: dict[str, Any]
    examples: tuple[SmokeTokenRow, ...]
    input_inventory: tuple[tuple[str, str], ...]
    tokenizer_files: tuple[tuple[str, bytes], ...]

    def rows(self, split: str) -> list[dict[str, list[int]]]:
        return [item.to_features() for item in self.examples if item.split == split]

    @property
    def identity(self) -> dict[str, object]:
        return {
            "candidate_id": self.prepared.configuration["candidate_id"],
            "configuration_content_hash": self.prepared.configuration["content_hash"],
            "tokenization_content_hash": self.tokenization["content_hash"],
            "input_file_sha256": dict(self.input_inventory),
        }


def load_verified_smoke_inputs(
    *,
    repository_root: Path,
    preparation_root: Path,
    tokenization_root: Path,
    source_evidence_path: Path,
) -> VerifiedSmokeInputs:
    """Bind the frozen S49 data, S50 observations, token IDs and captured tokenizer files.

    This checks the recorded tokenization evidence, not a fresh tokenizer execution.
    The training adapter additionally re-tokenizes the frozen examples before loading weights.
    """
    repository = checked_path(repository_root)
    prepared = load_smoke_preparation(repository, preparation_root)
    report = read_snapshot(tokenization_root / "tokenization-report.json")
    required = {
        "schema_version": 1,
        "policy_id": "qlora-smoke-tokenization-v1",
        "status": "TOKENIZATION_VERIFIED_NOT_AUTHORIZED",
        "candidate_id": prepared.configuration["candidate_id"],
        "configuration_content_hash": prepared.configuration["content_hash"],
        "preparation_file_sha256": prepared.inventory["preparation.json"],
        "input_file_sha256": prepared.inventory,
        "completion_only_loss": True,
        "assistant_only_loss": False,
        "truncation": False,
        "packing": False,
        "training_label_ignore_index": -100,
        "training_executed": False,
        "training_authorization": "NOT_GRANTED",
    }
    if canonical_bytes({k: report.get(k) for k in required}) != canonical_bytes(required):
        raise SmokeCollationError("tokenization report differs from the verified preparation")
    inventory = {f"prepared/{name}": digest for name, digest in prepared.inventory.items()}
    inventory["tokenized/tokenization-report.json"] = sha256(
        read_bounded(tokenization_root / "tokenization-report.json")
    )
    outputs = report.get("output_file_sha256")
    if not isinstance(outputs, dict) or set(outputs) != {
        "review.md",
        "tokenized-train.jsonl",
        "tokenized-validation.jsonl",
    }:
        raise SmokeCollationError("tokenization output inventory is invalid")
    token_raw = {}
    for name, digest in outputs.items():
        raw = read_bounded(tokenization_root / name)
        if sha256(raw) != digest:
            raise SmokeCollationError(f"tokenization output changed: {name}")
        token_raw[name] = raw
        inventory[f"tokenized/{name}"] = digest

    matrix = load_frozen_model_candidate_matrix(repository)
    evidence = load_captured_model_source_evidence(source_evidence_path, matrix=matrix)
    source_digest = sha256(read_bounded(source_evidence_path))
    tokenizer = report.get("tokenizer")
    if not isinstance(tokenizer, dict) or (
        tokenizer.get("source_evidence_sha256") != source_digest
        or tokenizer.get("source_evidence_content_hash") != evidence.content_hash
        or evidence.candidate_id != prepared.configuration["candidate_id"]
        or evidence.repository_id != prepared.configuration["tokenizer_repository"]
        or evidence.resolved_revision != prepared.configuration["tokenizer_revision"]
        or tokenizer.get("revision") != evidence.resolved_revision
    ):
        raise SmokeCollationError("tokenizer source identity differs")
    inventory["sources/evidence.json"] = source_digest
    token_files = {}
    for item in evidence.files:
        raw = read_bounded(source_evidence_path.parent / "files" / item.relative_path, 100_000_000)
        if len(raw) != item.size_bytes or sha256(raw) != item.sha256:
            raise SmokeCollationError("captured tokenizer source changed")
        inventory[f"sources/{item.relative_path}"] = item.sha256
        if item.relative_path in {"tokenizer.json", "tokenizer_config.json"}:
            token_files[item.relative_path] = raw
    if {name: sha256(raw) for name, raw in token_files.items()} != tokenizer.get("file_sha256"):
        raise SmokeCollationError("tokenizer file digests differ from S50")
    if set(token_files) != {"tokenizer.json", "tokenizer_config.json"}:
        raise SmokeCollationError("both tokenizer files are required")
    for key in ("pad_token_id", "eos_token_id"):
        if type(tokenizer.get(key)) is not int or tokenizer[key] < 0:
            raise SmokeCollationError(f"invalid {key}")

    observations = report.get("observations")
    if not isinstance(observations, list) or len(observations) != len(prepared.records):
        raise SmokeCollationError("one observation is required per prepared example")
    rows = {
        split: [
            strict_json_loads(line)
            for line in token_raw[f"tokenized-{split}.jsonl"].decode("utf-8").splitlines()
        ]
        for split in ("train", "validation")
    }
    if len(rows["train"]) != 16 or len(rows["validation"]) != 4:
        raise SmokeCollationError("smoke split counts changed")
    examples = []
    limit = prepared.configuration["optimization"]["max_sequence_length"]
    for entry, observation in zip(prepared.records, observations, strict=True):
        if not isinstance(observation, dict) or observation.get("issues") != []:
            raise SmokeCollationError("tokenization contains unresolved issues")
        for key in ("sample_id", "split", "row_index", "training_record_sha256"):
            if observation.get(key) != entry[key]:
                raise SmokeCollationError("tokenization observation differs from its source row")
        row = rows[entry["split"]][entry["row_index"]]
        if not isinstance(row, dict) or set(row) != {
            "input_ids",
            "attention_mask",
            "completion_mask",
        }:
            raise SmokeCollationError("tokenized row has unsupported fields")
        ids, mask = row["input_ids"], row["completion_mask"]
        if (
            not isinstance(ids, list)
            or not 1 < len(ids) <= limit
            or any(type(value) is not int or value < 0 for value in ids)
        ):
            raise SmokeCollationError("invalid or oversized input IDs")
        prefix = observation["prompt_tokens"]
        if type(prefix) is not int or not 0 < prefix < len(ids):
            raise SmokeCollationError("completion boundary is invalid")
        if (
            mask != [0] * prefix + [1] * (len(ids) - prefix)
            or any(type(value) is not int for value in mask)
            or row["attention_mask"] != [1] * len(ids)
        ):
            raise SmokeCollationError("completion mask or attention mask changed")
        labels = [-100] * prefix + ids[prefix:]
        for key, value in (
            ("input_ids_sha256", ids),
            ("completion_mask_sha256", mask),
            ("proposed_labels_sha256", labels),
        ):
            if observation.get(key) != sha256(canonical_bytes(value)):
                raise SmokeCollationError("tokenization observation digest differs")
        if (
            observation.get("total_tokens") != len(ids)
            or observation.get("completion_tokens") != len(ids) - prefix
            or tokenizer["eos_token_id"] not in ids[prefix:]
        ):
            raise SmokeCollationError("token count or completion EOS differs")
        examples.append(SmokeTokenRow(entry["sample_id"], entry["split"], tuple(ids), tuple(mask)))
    return VerifiedSmokeInputs(
        repository,
        (
            checked_path(preparation_root),
            checked_path(tokenization_root),
            checked_path(source_evidence_path.parent),
        ),
        prepared,
        report,
        tuple(examples),
        tuple(sorted(inventory.items())),
        tuple(sorted(token_files.items())),
    )


def _plain(value: Any) -> Any:
    return value.tolist() if hasattr(value, "tolist") else value


def audit_collator(data: VerifiedSmokeInputs, collator: Callable[..., Any]) -> dict[str, Any]:
    """Compare every label/token plus right-padding in both mixed-length batch orders."""
    pad = data.tokenization["tokenizer"]["pad_token_id"]
    observations = []
    batches = [[row] for row in data.examples]
    shortest = min(data.examples, key=lambda row: len(row.input_ids))
    longest = max(data.examples, key=lambda row: len(row.input_ids))
    if len(shortest.input_ids) == len(longest.input_ids):
        raise SmokeCollationError("padding probe requires two different sequence lengths")
    batches.extend([[shortest, longest], [longest, shortest]])
    for batch in batches:
        features = [row.to_features() for row in batch]
        original = copy.deepcopy(features)
        actual = collator(features)
        if features != original:
            raise SmokeCollationError("collator mutated its source examples")
        if not isinstance(actual, Mapping) or set(actual) != {
            "input_ids",
            "attention_mask",
            "labels",
        }:
            raise SmokeCollationError("collator must return IDs, attention mask and labels only")
        width = max(len(row.input_ids) for row in batch)
        expected = {"input_ids": [], "attention_mask": [], "labels": []}
        for row in batch:
            n = len(row.input_ids)
            expected["input_ids"].append(list(row.input_ids) + [pad] * (width - n))
            expected["attention_mask"].append([1] * n + [0] * (width - n))
            expected["labels"].append(
                [
                    token if keep else -100
                    for token, keep in zip(
                        row.input_ids,
                        row.completion_mask,
                        strict=True,
                    )
                ]
                + [-100] * (width - n)
            )
        for key, value in expected.items():
            observed = _plain(actual[key])
            if (
                not isinstance(observed, list)
                or any(
                    not isinstance(row, list) or any(type(v) is not int for v in row)
                    for row in observed
                )
                or observed != value
            ):
                raise SmokeCollationError(
                    f"collator {key} differs from completion-only supervision"
                )
        observations.append(
            {
                "samples": [row.sample_id for row in batch],
                "width": width,
                "batch_sha256": sha256(canonical_bytes(expected)),
            }
        )
    return {
        "sample_count": len(data.examples),
        "single_batch_checks": len(data.examples),
        "padded_batch_checks": 2,
        "completion_only_labels_verified": True,
        "observations": observations,
    }


def new_output_root(data: VerifiedSmokeInputs, output: Path) -> Path:
    path = checked_path(output)
    for protected in (
        *data.protected_roots,
        data.repository / "src",
        data.repository / "experiments",
    ):
        if path == protected or path in protected.parents or protected in path.parents:
            raise SmokeCollationError("output overlaps protected inputs or code")
    artifacts = data.repository / "environments/training/artifacts"
    if data.repository in path.parents and artifacts not in path.parents:
        raise SmokeCollationError("repository output must be inside training artifacts")
    if path.exists():
        raise SmokeCollationError("output must be a new directory")
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
    value = dict(payload)
    value.pop("content_hash", None)
    value["content_hash"] = snapshot_content_hash(value)
    with path.open("xb") as stream:
        stream.write(canonical_bytes(value))


def package_versions(names: tuple[str, ...]) -> dict[str, str | None]:
    result = {}
    for name in names:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def run_collator_preflight(
    data: VerifiedSmokeInputs,
    collator: Callable[..., Any],
    *,
    output_root: Path,
    created_at: datetime,
) -> Path:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise SmokeCollationError("timestamp must be timezone-aware")
    audit = audit_collator(data, collator)
    try:
        implementation = sha256(inspect.getsource(type(collator)).encode("utf-8"))
    except (OSError, TypeError):
        implementation = None
    destination = new_output_root(data, output_root)
    path = destination / "collator-report.json"
    write_snapshot(
        path,
        {
            "schema_version": 1,
            "policy_id": COLLATION_POLICY_ID,
            "status": "COLLATOR_VERIFIED_NOT_AUTHORIZED",
            "created_at": created_at.isoformat(),
            "inputs": data.identity,
            "audit": audit,
            "collator_class": f"{type(collator).__module__}.{type(collator).__qualname__}",
            "collator_implementation_sha256": implementation,
            "package_versions": package_versions(("torch", "trl", "transformers")),
            "implementation_sha256": sha256(Path(__file__).read_bytes()),
            "training_executed": False,
            "model_weights_loaded": False,
            "training_authorization": "NOT_GRANTED",
            "owner_fixture_review": "PENDING",
            "license_review_status": "PENDING",
            "model_selected": False,
        },
    )
    return path
