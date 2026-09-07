"""Content-addressed registration of exact base-plus-LoRA adapter artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.qlora_configurations import QloraTrainingConfiguration
from orchestwin.training.unsloth_adapter import QloraTrainingOutcome, QloraTrainingStatus

ADAPTER_ARTIFACT_SCHEMA_VERSION: Final = 1
_MAX_FILE_COUNT: Final = 2_000
_MAX_TOTAL_BYTES: Final = 8 * 1024 * 1024 * 1024
_MAX_PATH_LENGTH: Final = 512
_REQUIRED_CONFIGURATION_FILE: Final = "adapter_config.json"
_WEIGHT_FILENAMES: Final = frozenset(
    {
        "adapter_model.safetensors",
        "adapter_model.bin",
    }
)


@dataclass(frozen=True, slots=True)
class AdapterArtifactFile:
    """One regular file inside an immutable adapter artifact."""

    relative_path: str
    size_bytes: int
    sha256_digest: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path, label="adapter artifact file path")
        validate_positive_integer(self.size_bytes, label="adapter artifact file size")
        validate_sha256(self.sha256_digest, label="adapter artifact file digest")

    @property
    def sort_key(self) -> str:
        return self.relative_path

    def to_snapshot(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256_digest": self.sha256_digest,
        }


@dataclass(frozen=True, slots=True)
class AdapterArtifactManifest:
    """Exact model, dataset, training, license, and file identity for one adapter."""

    adapter_id: UUID
    owner_user_id: UUID
    training_run_id: UUID
    base_model_repository: str
    base_model_revision: str
    tokenizer_repository: str
    tokenizer_revision: str
    dataset_reference: DatasetManifestReference
    training_configuration_sha256: str
    adapter_sha256: str
    license_spdx: str
    storage_key: str
    files: tuple[AdapterArtifactFile, ...]
    total_size_bytes: int
    created_at: datetime
    content_hash: str
    schema_version: int = ADAPTER_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ADAPTER_ARTIFACT_SCHEMA_VERSION:
            raise ValueError("unsupported adapter artifact schema version")
        for value, label in (
            (self.base_model_repository, "adapter base model repository"),
            (self.base_model_revision, "adapter base model revision"),
            (self.tokenizer_repository, "adapter tokenizer repository"),
            (self.tokenizer_revision, "adapter tokenizer revision"),
            (self.license_spdx, "adapter license SPDX identifier"),
        ):
            normalized = normalize_required_text(value, label=label, maximum_length=256)
            if normalized != value or any(character.isspace() for character in value):
                raise ValueError(f"{label} must be a normalized identifier")
        for value, label in (
            (self.training_configuration_sha256, "adapter training configuration digest"),
            (self.adapter_sha256, "adapter artifact digest"),
            (self.content_hash, "adapter manifest content hash"),
        ):
            validate_sha256(value, label=label)
        expected_storage_key = f"sha256/{self.adapter_sha256[:2]}/{self.adapter_sha256}"
        if self.storage_key != expected_storage_key:
            raise ValueError("adapter storage key must be content-addressed")
        if not self.files:
            raise ValueError("adapter artifact manifest must contain files")
        if self.files != tuple(sorted(self.files, key=lambda item: item.sort_key)):
            raise ValueError("adapter artifact files must use canonical order")
        paths = tuple(item.relative_path for item in self.files)
        if len(paths) != len(set(paths)):
            raise ValueError("adapter artifact file paths must be unique")
        if _REQUIRED_CONFIGURATION_FILE not in paths:
            raise ValueError("adapter artifact requires adapter_config.json")
        if not _WEIGHT_FILENAMES.intersection(paths):
            raise ValueError("adapter artifact requires LoRA weight files")
        if self.total_size_bytes != sum(item.size_bytes for item in self.files):
            raise ValueError("adapter artifact total size is inconsistent")
        if self.total_size_bytes > _MAX_TOTAL_BYTES:
            raise ValueError("adapter artifact exceeds the configured size limit")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("adapter artifact timestamp must be timezone-aware")
        if self.content_hash != adapter_artifact_manifest_hash(
            adapter_id=self.adapter_id,
            owner_user_id=self.owner_user_id,
            training_run_id=self.training_run_id,
            base_model_repository=self.base_model_repository,
            base_model_revision=self.base_model_revision,
            tokenizer_repository=self.tokenizer_repository,
            tokenizer_revision=self.tokenizer_revision,
            dataset_reference=self.dataset_reference,
            training_configuration_sha256=self.training_configuration_sha256,
            adapter_sha256=self.adapter_sha256,
            license_spdx=self.license_spdx,
            storage_key=self.storage_key,
            files=self.files,
            total_size_bytes=self.total_size_bytes,
            schema_version=self.schema_version,
        ):
            raise ValueError("adapter artifact manifest content hash is inconsistent")

    def semantic_snapshot(self) -> dict[str, object]:
        return _adapter_manifest_semantic_snapshot(
            adapter_id=self.adapter_id,
            owner_user_id=self.owner_user_id,
            training_run_id=self.training_run_id,
            base_model_repository=self.base_model_repository,
            base_model_revision=self.base_model_revision,
            tokenizer_repository=self.tokenizer_repository,
            tokenizer_revision=self.tokenizer_revision,
            dataset_reference=self.dataset_reference,
            training_configuration_sha256=self.training_configuration_sha256,
            adapter_sha256=self.adapter_sha256,
            license_spdx=self.license_spdx,
            storage_key=self.storage_key,
            files=self.files,
            total_size_bytes=self.total_size_bytes,
            schema_version=self.schema_version,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
        }


class AdapterRegistrationStatus(StrEnum):
    """Stable content-addressed registration outcomes."""

    REGISTERED = "REGISTERED"
    ALREADY_PRESENT = "ALREADY_PRESENT"


@dataclass(frozen=True, slots=True)
class AdapterRegistrationResult:
    """Registration result with exact stored paths and manifest."""

    status: AdapterRegistrationStatus
    manifest: AdapterArtifactManifest
    artifact_directory: Path
    manifest_path: Path


class ContentAddressedAdapterRegistry:
    """Local adapter registry that rejects links and verifies every copied byte."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def register(
        self,
        *,
        source_directory: Path,
        manifest: AdapterArtifactManifest,
    ) -> AdapterRegistrationResult:
        source = Path(source_directory)
        observed_files, observed_digest = inspect_adapter_directory(source)
        if observed_files != manifest.files or observed_digest != manifest.adapter_sha256:
            raise ValueError("adapter source content does not match its manifest")
        self._prepare_root()
        target = self._root / manifest.storage_key
        manifest_path = self._root / "manifests" / f"{manifest.adapter_sha256}.json"
        if target.exists():
            if target.is_symlink() or not target.is_dir():
                raise ValueError("adapter storage target is not a regular directory")
            stored_files, stored_digest = inspect_adapter_directory(target)
            if stored_files != manifest.files or stored_digest != manifest.adapter_sha256:
                raise ValueError("existing adapter storage content is inconsistent")
            self._write_or_verify_manifest(manifest_path, manifest)
            return AdapterRegistrationResult(
                AdapterRegistrationStatus.ALREADY_PRESENT,
                manifest,
                target,
                manifest_path,
            )
        temporary = target.with_name(f".{target.name}.tmp-{manifest.adapter_id.hex}")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("temporary adapter registration path already exists")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        _copy_manifest_files(source, temporary, manifest.files)
        copied_files, copied_digest = inspect_adapter_directory(temporary)
        if copied_files != manifest.files or copied_digest != manifest.adapter_sha256:
            shutil.rmtree(temporary)
            raise ValueError("copied adapter content failed digest verification")
        os.replace(temporary, target)
        self._write_or_verify_manifest(manifest_path, manifest)
        return AdapterRegistrationResult(
            AdapterRegistrationStatus.REGISTERED,
            manifest,
            target,
            manifest_path,
        )

    def history_for_owner(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[AdapterArtifactManifest, ...]:
        """Return verified manifests without disclosing other owners' adapters."""
        manifest_root = self._root / "manifests"
        if not manifest_root.exists():
            return ()
        if manifest_root.is_symlink() or not manifest_root.is_dir():
            raise ValueError("adapter manifest root must be a regular directory")
        manifests: list[AdapterArtifactManifest] = []
        for path in sorted(manifest_root.glob("*.json"), key=lambda item: item.name):
            manifest = load_adapter_artifact_manifest(path)
            self._verify_registered_manifest(manifest)
            if manifest.owner_user_id == owner_user_id:
                manifests.append(manifest)
        return tuple(
            sorted(
                manifests,
                key=lambda item: (item.created_at, item.adapter_id.hex),
            )
        )

    def get_owned(
        self,
        *,
        owner_user_id: UUID,
        adapter_id: UUID,
    ) -> AdapterArtifactManifest | None:
        """Return one exact owner-scoped adapter manifest after byte verification."""
        for manifest in self.history_for_owner(owner_user_id=owner_user_id):
            if manifest.adapter_id == adapter_id:
                return manifest
        return None

    def _prepare_root(self) -> None:
        if self._root.is_symlink():
            raise ValueError("adapter registry root must not be a symbolic link")
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise ValueError("adapter registry root must be a directory")

    def _verify_registered_manifest(self, manifest: AdapterArtifactManifest) -> None:
        artifact_directory = self._root / manifest.storage_key
        files, digest = inspect_adapter_directory(artifact_directory)
        if files != manifest.files or digest != manifest.adapter_sha256:
            raise ValueError("registered adapter content does not match its manifest")

    @staticmethod
    def _write_or_verify_manifest(
        path: Path,
        manifest: AdapterArtifactManifest,
    ) -> None:
        content = canonical_json(manifest.to_snapshot())
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise ValueError("adapter manifest target is not a regular file")
            if path.read_text(encoding="utf-8") != content:
                raise ValueError("existing adapter manifest is inconsistent")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)


def load_adapter_artifact_manifest(path: Path) -> AdapterArtifactManifest:
    """Load one canonical manifest and reconstruct its validated domain value."""
    manifest_path = Path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("adapter manifest must be a regular file")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("adapter manifest must contain valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("adapter manifest must contain a JSON object")
    return adapter_artifact_manifest_from_snapshot(raw)


def adapter_artifact_manifest_from_snapshot(
    snapshot: dict[str, object],
) -> AdapterArtifactManifest:
    """Rebuild a manifest while reapplying all identity and integrity rules."""
    dataset = _required_mapping(snapshot, "dataset_reference")
    files_raw = _required_list(snapshot, "files")
    files = tuple(
        AdapterArtifactFile(
            relative_path=_required_string(item, "relative_path"),
            size_bytes=_required_integer(item, "size_bytes"),
            sha256_digest=_required_string(item, "sha256_digest"),
        )
        for item in (_require_mapping(value, label="adapter manifest file") for value in files_raw)
    )
    try:
        created_at = datetime.fromisoformat(_required_string(snapshot, "created_at"))
        manifest = AdapterArtifactManifest(
            adapter_id=UUID(_required_string(snapshot, "adapter_id")),
            owner_user_id=UUID(_required_string(snapshot, "owner_user_id")),
            training_run_id=UUID(_required_string(snapshot, "training_run_id")),
            base_model_repository=_required_string(snapshot, "base_model_repository"),
            base_model_revision=_required_string(snapshot, "base_model_revision"),
            tokenizer_repository=_required_string(snapshot, "tokenizer_repository"),
            tokenizer_revision=_required_string(snapshot, "tokenizer_revision"),
            dataset_reference=DatasetManifestReference(
                dataset_id=UUID(_required_string(dataset, "dataset_id")),
                version_number=_required_integer(dataset, "version_number"),
                content_hash=_required_string(dataset, "content_hash"),
            ),
            training_configuration_sha256=_required_string(
                snapshot,
                "training_configuration_sha256",
            ),
            adapter_sha256=_required_string(snapshot, "adapter_sha256"),
            license_spdx=_required_string(snapshot, "license_spdx"),
            storage_key=_required_string(snapshot, "storage_key"),
            files=files,
            total_size_bytes=_required_integer(snapshot, "total_size_bytes"),
            created_at=created_at,
            content_hash=_required_string(snapshot, "content_hash"),
            schema_version=_required_integer(snapshot, "schema_version"),
        )
    except (TypeError, ValueError) as error:
        raise ValueError("adapter manifest snapshot is invalid") from error
    if canonical_json(manifest.to_snapshot()) != canonical_json(snapshot):
        raise ValueError("adapter manifest snapshot contains unsupported or missing fields")
    return manifest


def create_adapter_artifact_manifest(
    *,
    adapter_id: UUID,
    outcome: QloraTrainingOutcome,
    configuration: QloraTrainingConfiguration,
    license_spdx: str,
    files: tuple[AdapterArtifactFile, ...],
    adapter_sha256: str,
    created_at: datetime,
) -> AdapterArtifactManifest:
    """Bind a successful adapter to its exact base, dataset, and training run."""
    if outcome.status is not QloraTrainingStatus.SUCCEEDED:
        raise ValueError("only successful training outcomes can register an adapter")
    if outcome.adapter_sha256 != adapter_sha256:
        raise ValueError("training outcome adapter digest does not match inspected content")
    if outcome.configuration_sha256 != configuration.content_hash:
        raise ValueError("training outcome configuration identity does not match")
    if outcome.dataset_reference != configuration.dataset_reference:
        raise ValueError("training outcome dataset identity does not match")
    ordered_files = tuple(sorted(files, key=lambda item: item.sort_key))
    total_size_bytes = sum(item.size_bytes for item in ordered_files)
    storage_key = f"sha256/{adapter_sha256[:2]}/{adapter_sha256}"
    content_hash = adapter_artifact_manifest_hash(
        adapter_id=adapter_id,
        owner_user_id=outcome.owner_user_id,
        training_run_id=outcome.run_id,
        base_model_repository=configuration.base_model_repository,
        base_model_revision=configuration.base_model_revision,
        tokenizer_repository=configuration.tokenizer_repository,
        tokenizer_revision=configuration.tokenizer_revision,
        dataset_reference=configuration.dataset_reference,
        training_configuration_sha256=configuration.content_hash,
        adapter_sha256=adapter_sha256,
        license_spdx=license_spdx,
        storage_key=storage_key,
        files=ordered_files,
        total_size_bytes=total_size_bytes,
        schema_version=ADAPTER_ARTIFACT_SCHEMA_VERSION,
    )
    return AdapterArtifactManifest(
        adapter_id=adapter_id,
        owner_user_id=outcome.owner_user_id,
        training_run_id=outcome.run_id,
        base_model_repository=configuration.base_model_repository,
        base_model_revision=configuration.base_model_revision,
        tokenizer_repository=configuration.tokenizer_repository,
        tokenizer_revision=configuration.tokenizer_revision,
        dataset_reference=configuration.dataset_reference,
        training_configuration_sha256=configuration.content_hash,
        adapter_sha256=adapter_sha256,
        license_spdx=license_spdx,
        storage_key=storage_key,
        files=ordered_files,
        total_size_bytes=total_size_bytes,
        created_at=created_at,
        content_hash=content_hash,
    )


def inspect_adapter_directory(
    directory: Path,
) -> tuple[tuple[AdapterArtifactFile, ...], str]:
    """Inspect regular files and compute the trainer-compatible directory digest."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("adapter source must be a regular directory")
    files: list[AdapterArtifactFile] = []
    aggregate = hashlib.sha256()
    total_size = 0
    paths = sorted(root.rglob("*"), key=lambda item: item.as_posix())
    if len(paths) > _MAX_FILE_COUNT:
        raise ValueError("adapter artifact exceeds the configured file-count limit")
    for path in paths:
        if path.is_symlink():
            raise ValueError("adapter artifacts cannot contain symbolic links")
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        _validate_relative_path(relative_path, label="adapter artifact file path")
        file_digest = hashlib.sha256()
        size_bytes = 0
        aggregate.update(relative_path.encode("utf-8"))
        aggregate.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                size_bytes += len(chunk)
                total_size += len(chunk)
                if total_size > _MAX_TOTAL_BYTES:
                    raise ValueError("adapter artifact exceeds the configured size limit")
                file_digest.update(chunk)
                aggregate.update(chunk)
        aggregate.update(b"\0")
        if size_bytes < 1:
            raise ValueError("adapter artifacts cannot contain empty files")
        files.append(
            AdapterArtifactFile(
                relative_path=relative_path,
                size_bytes=size_bytes,
                sha256_digest=file_digest.hexdigest(),
            )
        )
    ordered = tuple(sorted(files, key=lambda item: item.sort_key))
    _validate_adapter_configuration(root / _REQUIRED_CONFIGURATION_FILE)
    return ordered, aggregate.hexdigest()


def _validate_adapter_configuration(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("adapter artifact requires a regular adapter_config.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("adapter_config.json must contain valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("adapter_config.json must contain a JSON object")
    peft_type = value.get("peft_type")
    if peft_type is not None and peft_type != "LORA":
        raise ValueError("adapter_config.json must describe a LoRA adapter")


def adapter_artifact_manifest_hash(
    *,
    adapter_id: UUID,
    owner_user_id: UUID,
    training_run_id: UUID,
    base_model_repository: str,
    base_model_revision: str,
    tokenizer_repository: str,
    tokenizer_revision: str,
    dataset_reference: DatasetManifestReference,
    training_configuration_sha256: str,
    adapter_sha256: str,
    license_spdx: str,
    storage_key: str,
    files: tuple[AdapterArtifactFile, ...],
    total_size_bytes: int,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        _adapter_manifest_semantic_snapshot(
            adapter_id=adapter_id,
            owner_user_id=owner_user_id,
            training_run_id=training_run_id,
            base_model_repository=base_model_repository,
            base_model_revision=base_model_revision,
            tokenizer_repository=tokenizer_repository,
            tokenizer_revision=tokenizer_revision,
            dataset_reference=dataset_reference,
            training_configuration_sha256=training_configuration_sha256,
            adapter_sha256=adapter_sha256,
            license_spdx=license_spdx,
            storage_key=storage_key,
            files=files,
            total_size_bytes=total_size_bytes,
            schema_version=schema_version,
        )
    )


def _adapter_manifest_semantic_snapshot(
    *,
    adapter_id: UUID,
    owner_user_id: UUID,
    training_run_id: UUID,
    base_model_repository: str,
    base_model_revision: str,
    tokenizer_repository: str,
    tokenizer_revision: str,
    dataset_reference: DatasetManifestReference,
    training_configuration_sha256: str,
    adapter_sha256: str,
    license_spdx: str,
    storage_key: str,
    files: tuple[AdapterArtifactFile, ...],
    total_size_bytes: int,
    schema_version: int,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "adapter_id": str(adapter_id),
        "owner_user_id": str(owner_user_id),
        "training_run_id": str(training_run_id),
        "base_model_repository": base_model_repository,
        "base_model_revision": base_model_revision,
        "tokenizer_repository": tokenizer_repository,
        "tokenizer_revision": tokenizer_revision,
        "dataset_reference": dataset_reference.to_snapshot(),
        "training_configuration_sha256": training_configuration_sha256,
        "adapter_sha256": adapter_sha256,
        "license_spdx": license_spdx,
        "storage_key": storage_key,
        "files": [item.to_snapshot() for item in files],
        "total_size_bytes": total_size_bytes,
    }


def _copy_manifest_files(
    source: Path,
    destination: Path,
    files: tuple[AdapterArtifactFile, ...],
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for item in files:
        source_file = _safe_child(source, item.relative_path)
        target_file = destination.joinpath(*PurePosixPath(item.relative_path).parts)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target_file)


def _safe_child(root: Path, relative_path: str) -> Path:
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("adapter artifacts cannot contain symbolic links")
    resolved_root = root.resolve()
    resolved = current.resolve()
    if resolved_root not in resolved.parents:
        raise ValueError("adapter artifact path escapes its source directory")
    return resolved


def _validate_relative_path(value: str, *, label: str) -> None:
    normalized = normalize_required_text(
        value,
        label=label,
        maximum_length=_MAX_PATH_LENGTH,
    )
    if normalized != value or "\\" in value:
        raise ValueError(f"{label} must be a normalized POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must remain relative and traversal-free")


def _require_mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _required_mapping(values: dict[str, object], key: str) -> dict[str, object]:
    return _require_mapping(values.get(key), label=key)


def _required_list(values: dict[str, object], key: str) -> list[object]:
    value = values.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    return value


def _required_string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _required_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value
