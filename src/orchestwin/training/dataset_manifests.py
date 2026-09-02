"""Versioned policies and deterministic manifests for evaluator datasets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import (
    DATASET_EXAMPLE_SCHEMA_VERSION,
    DatasetLanguage,
    EvaluatorDatasetExample,
)

DATASET_MANIFEST_SCHEMA_VERSION: Final = 1
_MAX_POLICY_ID_LENGTH: Final = 256


@dataclass(frozen=True, slots=True)
class DatasetBuildPolicy:
    """Versioned reproducibility inputs that govern one dataset build."""

    policy_id: str
    version_number: int
    seed: int
    required_languages: tuple[DatasetLanguage, ...]
    minimum_examples_per_language: int
    maximum_examples: int
    example_schema_version: int = DATASET_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized_id = normalize_required_text(
            self.policy_id,
            label="dataset build policy ID",
            maximum_length=_MAX_POLICY_ID_LENGTH,
        )
        if normalized_id != self.policy_id:
            raise ValueError("dataset build policy ID must be normalized")

        validate_positive_integer(
            self.version_number,
            label="dataset build policy version number",
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("dataset build policy seed must be a non-negative integer")
        validate_positive_integer(
            self.minimum_examples_per_language,
            label="minimum examples per language",
        )
        validate_positive_integer(
            self.maximum_examples,
            label="maximum dataset examples",
        )
        validate_positive_integer(
            self.example_schema_version,
            label="dataset example schema version",
        )

        if not self.required_languages:
            raise ValueError("dataset build policy languages must not be empty")
        if len(self.required_languages) != len(set(self.required_languages)):
            raise ValueError("dataset build policy languages must be unique")
        expected_languages = tuple(sorted(self.required_languages, key=lambda value: value.value))
        if self.required_languages != expected_languages:
            raise ValueError("dataset build policy languages must use canonical order")
        if self.maximum_examples < (
            self.minimum_examples_per_language * len(self.required_languages)
        ):
            raise ValueError("maximum examples cannot be lower than required language coverage")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "version_number": self.version_number,
            "seed": self.seed,
            "required_languages": [language.value for language in self.required_languages],
            "minimum_examples_per_language": self.minimum_examples_per_language,
            "maximum_examples": self.maximum_examples,
            "example_schema_version": self.example_schema_version,
        }


@dataclass(frozen=True, slots=True)
class DatasetManifestEntry:
    """Stable manifest projection of one immutable example."""

    example_id: str
    content_hash: str
    project_id: UUID
    scenario_family_id: str
    language: DatasetLanguage
    source_kind: str
    use_restriction: str

    def __post_init__(self) -> None:
        validate_sha256(
            self.content_hash,
            label="dataset manifest example content hash",
        )

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.example_id, self.content_hash)

    @classmethod
    def from_example(cls, example: EvaluatorDatasetExample) -> DatasetManifestEntry:
        return cls(
            example_id=example.example_id,
            content_hash=example.content_hash,
            project_id=example.project_id,
            scenario_family_id=example.scenario_family_id,
            language=example.language,
            source_kind=example.source_kind.value,
            use_restriction=example.use_restriction.value,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "example_id": self.example_id,
            "content_hash": self.content_hash,
            "project_id": str(self.project_id),
            "scenario_family_id": self.scenario_family_id,
            "language": self.language.value,
            "source_kind": self.source_kind,
            "use_restriction": self.use_restriction,
        }


@dataclass(frozen=True, slots=True)
class DatasetManifestReference:
    """Exact reference to one immutable dataset version."""

    dataset_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="dataset manifest version number",
        )
        validate_sha256(
            self.content_hash,
            label="dataset manifest content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "dataset_id": str(self.dataset_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class DatasetBuildManifest:
    """Immutable ordered manifest for one versioned evaluator dataset."""

    dataset_id: UUID
    owner_user_id: UUID
    version_number: int
    based_on: DatasetManifestReference | None
    policy: DatasetBuildPolicy
    entries: tuple[DatasetManifestEntry, ...]
    examples_digest: str
    content_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="dataset version number",
        )
        expected_base_version = None if self.version_number == 1 else self.version_number - 1
        actual_base_version = None if self.based_on is None else self.based_on.version_number
        if actual_base_version != expected_base_version:
            raise ValueError("dataset version lineage must reference the preceding version")
        if self.based_on is not None and self.based_on.dataset_id != self.dataset_id:
            raise ValueError("dataset version lineage must remain on the same dataset identity")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("dataset manifest timestamp must be timezone-aware")
        if not self.entries:
            raise ValueError("dataset manifest entries must not be empty")

        expected_entries = tuple(sorted(self.entries, key=lambda entry: entry.sort_key))
        if self.entries != expected_entries:
            raise ValueError("dataset manifest entries must use canonical order")
        example_ids = tuple(entry.example_id for entry in self.entries)
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("dataset manifest example IDs must be unique")
        if len(self.entries) > self.policy.maximum_examples:
            raise ValueError("dataset manifest exceeds the configured maximum example count")

        language_counts = {
            language: sum(entry.language is language for entry in self.entries)
            for language in self.policy.required_languages
        }
        if any(
            count < self.policy.minimum_examples_per_language for count in language_counts.values()
        ):
            raise ValueError("dataset manifest does not satisfy required language coverage")

        validate_sha256(
            self.examples_digest,
            label="dataset examples digest",
        )
        expected_examples_digest = snapshot_content_hash(
            {"entries": [entry.to_snapshot() for entry in self.entries]}
        )
        if self.examples_digest != expected_examples_digest:
            raise ValueError("dataset examples digest is inconsistent")

        validate_sha256(
            self.content_hash,
            label="dataset manifest content hash",
        )
        expected_content_hash = dataset_manifest_hash(
            dataset_id=self.dataset_id,
            owner_user_id=self.owner_user_id,
            version_number=self.version_number,
            based_on=self.based_on,
            policy=self.policy,
            entries=self.entries,
            examples_digest=self.examples_digest,
        )
        if self.content_hash != expected_content_hash:
            raise ValueError("dataset manifest content hash is inconsistent")

    @property
    def reference(self) -> DatasetManifestReference:
        return DatasetManifestReference(
            dataset_id=self.dataset_id,
            version_number=self.version_number,
            content_hash=self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
            "dataset_id": str(self.dataset_id),
            "owner_user_id": str(self.owner_user_id),
            "version_number": self.version_number,
            "based_on": None if self.based_on is None else self.based_on.to_snapshot(),
            "policy": self.policy.to_snapshot(),
            "policy_content_hash": self.policy.content_hash,
            "entries": [entry.to_snapshot() for entry in self.entries],
            "examples_digest": self.examples_digest,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
        }


def build_dataset_manifest(
    *,
    dataset_id: UUID,
    owner_user_id: UUID,
    version_number: int,
    based_on: DatasetManifestReference | None,
    policy: DatasetBuildPolicy,
    examples: Iterable[EvaluatorDatasetExample],
    created_at: datetime,
) -> DatasetBuildManifest:
    """Build a canonical manifest independent from input iteration order."""
    entries = tuple(
        sorted(
            (DatasetManifestEntry.from_example(example) for example in examples),
            key=lambda entry: entry.sort_key,
        )
    )
    examples_digest = snapshot_content_hash({"entries": [entry.to_snapshot() for entry in entries]})
    content_hash = dataset_manifest_hash(
        dataset_id=dataset_id,
        owner_user_id=owner_user_id,
        version_number=version_number,
        based_on=based_on,
        policy=policy,
        entries=entries,
        examples_digest=examples_digest,
    )
    return DatasetBuildManifest(
        dataset_id=dataset_id,
        owner_user_id=owner_user_id,
        version_number=version_number,
        based_on=based_on,
        policy=policy,
        entries=entries,
        examples_digest=examples_digest,
        content_hash=content_hash,
        created_at=created_at,
    )


def dataset_manifest_hash(
    *,
    dataset_id: UUID,
    owner_user_id: UUID,
    version_number: int,
    based_on: DatasetManifestReference | None,
    policy: DatasetBuildPolicy,
    entries: tuple[DatasetManifestEntry, ...],
    examples_digest: str,
) -> str:
    """Hash reproducibility inputs while excluding non-semantic creation time."""
    return snapshot_content_hash(
        {
            "schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
            "dataset_id": str(dataset_id),
            "owner_user_id": str(owner_user_id),
            "version_number": version_number,
            "based_on": None if based_on is None else based_on.to_snapshot(),
            "policy": policy.to_snapshot(),
            "entries": [entry.to_snapshot() for entry in entries],
            "examples_digest": examples_digest,
        }
    )
