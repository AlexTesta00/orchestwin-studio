"""Structured immutable Project Brief values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID


class BriefField(StrEnum):
    """Fields required by the Project Brief contract."""

    NAME = "name"
    DESCRIPTION = "description"
    PROBLEM = "problem"
    GOALS = "goals"
    TARGET_USERS = "target_users"
    DOMAIN = "domain"
    TECHNICAL_CONSTRAINTS = "technical_constraints"
    TEMPORAL_CONSTRAINTS = "temporal_constraints"
    BUDGET = "budget"
    FUNCTIONAL_REQUIREMENTS = "functional_requirements"
    NON_FUNCTIONAL_REQUIREMENTS = "non_functional_requirements"
    RISKS = "risks"
    STAKEHOLDERS = "stakeholders"
    AVAILABLE_ARTIFACTS = "available_artifacts"
    DEFINITION_OF_DONE = "definition_of_done"


TEXT_FIELDS = frozenset(
    {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.PROBLEM,
        BriefField.DOMAIN,
        BriefField.TEMPORAL_CONSTRAINTS,
        BriefField.BUDGET,
    }
)
LIST_FIELDS = frozenset(field for field in BriefField if field not in TEXT_FIELDS)


@dataclass(frozen=True, slots=True)
class ProjectBrief:
    """Structured Project Brief with explicit unknown fields."""

    SCHEMA_VERSION: ClassVar[int] = 1

    name: str | None = None
    description: str | None = None
    problem: str | None = None
    goals: tuple[str, ...] | None = None
    target_users: tuple[str, ...] | None = None
    domain: str | None = None
    technical_constraints: tuple[str, ...] | None = None
    temporal_constraints: str | None = None
    budget: str | None = None
    functional_requirements: tuple[str, ...] | None = None
    non_functional_requirements: tuple[str, ...] | None = None
    risks: tuple[str, ...] | None = None
    stakeholders: tuple[str, ...] | None = None
    available_artifacts: tuple[str, ...] | None = None
    definition_of_done: tuple[str, ...] | None = None
    unknown_fields: frozenset[BriefField] = frozenset()

    def __post_init__(self) -> None:
        """Protect provided, unknown, and missing semantics."""
        for field in BriefField:
            value = self.value_for(field)

            if field in self.unknown_fields:
                if value is not None:
                    raise ValueError(f"{field.value} cannot be provided and UNKNOWN")

                continue

            if isinstance(value, str) and (not value or value != value.strip()):
                raise ValueError(f"{field.value} must contain normalized text")

            if isinstance(value, tuple):
                if not value:
                    raise ValueError(f"{field.value} must not be an empty list")

                if any(not item or item != item.strip() for item in value):
                    raise ValueError(f"{field.value} contains invalid items")

    @property
    def provided_fields(
        self,
    ) -> frozenset[BriefField]:
        """Return fields containing owner-provided values."""
        return frozenset(field for field in BriefField if self.value_for(field) is not None)

    @property
    def missing_fields(
        self,
    ) -> frozenset[BriefField]:
        """Return fields neither provided nor explicitly unknown."""
        return frozenset(
            field
            for field in BriefField
            if self.value_for(field) is None and field not in self.unknown_fields
        )

    @property
    def content_hash(self) -> str:
        """Return the deterministic SHA-256 snapshot hash."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def value_for(
        self,
        field: BriefField,
    ) -> str | tuple[str, ...] | None:
        """Return the value associated with a brief field."""
        return getattr(self, field.value)

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable snapshot."""
        fields: dict[str, object] = {}

        for field in BriefField:
            value = self.value_for(field)

            if isinstance(value, tuple):
                fields[field.value] = list(value)
            else:
                fields[field.value] = value

        return {
            "schema_version": self.SCHEMA_VERSION,
            "fields": fields,
            "unknown_fields": sorted(field.value for field in self.unknown_fields),
        }

    def canonical_json(self) -> str:
        """Serialize the snapshot with deterministic ordering."""
        return json.dumps(
            self.to_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Mapping[str, object],
    ) -> ProjectBrief:
        """Reconstruct and validate a brief snapshot."""
        schema_version = snapshot.get("schema_version")

        if schema_version != cls.SCHEMA_VERSION:
            raise ValueError("unsupported Project Brief schema version")

        raw_fields = snapshot.get("fields")
        raw_unknown_fields = snapshot.get("unknown_fields")

        if not isinstance(raw_fields, Mapping):
            raise ValueError("Project Brief snapshot fields are invalid")

        if not isinstance(
            raw_unknown_fields,
            list,
        ):
            raise ValueError("Project Brief unknown fields are invalid")

        unknown_fields = frozenset(BriefField(str(value)) for value in raw_unknown_fields)

        text_values: dict[str, str | None] = {}
        list_values: dict[
            str,
            tuple[str, ...] | None,
        ] = {}

        for field in TEXT_FIELDS:
            raw_value = raw_fields.get(field.value)

            if raw_value is not None and not isinstance(raw_value, str):
                raise ValueError(f"{field.value} must be text or null")

            text_values[field.value] = raw_value

        for field in LIST_FIELDS:
            raw_value = raw_fields.get(field.value)

            if raw_value is None:
                list_values[field.value] = None
                continue

            if not isinstance(raw_value, list) or not all(
                isinstance(item, str) for item in raw_value
            ):
                raise ValueError(f"{field.value} must be a string list or null")

            list_values[field.value] = tuple(raw_value)

        return cls(
            **text_values,
            **list_values,
            unknown_fields=unknown_fields,
        )


def normalize_optional_text(
    value: str | None,
) -> str | None:
    """Normalize optional owner-provided text."""
    if value is None:
        return None

    normalized = " ".join(value.split())

    return normalized or None


def normalize_optional_items(
    values: Iterable[str] | None,
) -> tuple[str, ...] | None:
    """Normalize an optional list while preserving order."""
    if values is None:
        return None

    normalized = tuple(item for value in values if (item := " ".join(value.split())))

    return normalized or None


def create_project_brief(
    *,
    name: str | None = None,
    description: str | None = None,
    problem: str | None = None,
    goals: Iterable[str] | None = None,
    target_users: Iterable[str] | None = None,
    domain: str | None = None,
    technical_constraints: (Iterable[str] | None) = None,
    temporal_constraints: str | None = None,
    budget: str | None = None,
    functional_requirements: (Iterable[str] | None) = None,
    non_functional_requirements: (Iterable[str] | None) = None,
    risks: Iterable[str] | None = None,
    stakeholders: Iterable[str] | None = None,
    available_artifacts: (Iterable[str] | None) = None,
    definition_of_done: (Iterable[str] | None) = None,
    unknown_fields: (Iterable[BriefField] | None) = None,
) -> ProjectBrief:
    """Create a normalized partial Project Brief."""
    return ProjectBrief(
        name=normalize_optional_text(name),
        description=normalize_optional_text(description),
        problem=normalize_optional_text(problem),
        goals=normalize_optional_items(goals),
        target_users=normalize_optional_items(target_users),
        domain=normalize_optional_text(domain),
        technical_constraints=(normalize_optional_items(technical_constraints)),
        temporal_constraints=(normalize_optional_text(temporal_constraints)),
        budget=normalize_optional_text(budget),
        functional_requirements=(normalize_optional_items(functional_requirements)),
        non_functional_requirements=(normalize_optional_items(non_functional_requirements)),
        risks=normalize_optional_items(risks),
        stakeholders=normalize_optional_items(stakeholders),
        available_artifacts=(normalize_optional_items(available_artifacts)),
        definition_of_done=(normalize_optional_items(definition_of_done)),
        unknown_fields=frozenset(unknown_fields or ()),
    )


@dataclass(frozen=True, slots=True)
class ProjectBriefVersion:
    """Immutable versioned Project Brief snapshot."""

    id: UUID
    project_id: UUID
    version_number: int
    schema_version: int
    brief: ProjectBrief
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        """Protect version-number and snapshot invariants."""
        if self.version_number < 1:
            raise ValueError("brief version number must be positive")

        if self.schema_version != self.brief.SCHEMA_VERSION:
            raise ValueError("brief version schema does not match content")

        if self.content_hash != (self.brief.content_hash):
            raise ValueError("brief version hash does not match content")

        if self.created_at.tzinfo is None:
            raise ValueError("brief-version timestamp must be timezone-aware")
