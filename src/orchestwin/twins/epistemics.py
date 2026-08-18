"""Epistemic provenance primitives for User Modeling and User Twins."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from typing import Final

_MAX_SOURCE_ID_LENGTH: Final = 256
_MAX_LOCATOR_LENGTH: Final = 512
_MAX_SUMMARY_LENGTH: Final = 1000
_MAX_OBSERVATION_TEXT_LENGTH: Final = 4000
_MAX_OBSERVATION_ITEM_LENGTH: Final = 2000
_MAX_ABSTENTION_REASON_LENGTH: Final = 1000
_MAX_RATIONALE_LENGTH: Final = 2000
_MAX_OBSERVATION_KEY_LENGTH: Final = 128

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_OBSERVATION_KEY_PATTERN: Final = re.compile(
    rf"[a-z][a-z0-9_.-]"
    rf"{{0,{_MAX_OBSERVATION_KEY_LENGTH - 1}}}"
)


def _require_normalized_text(
    value: str,
    *,
    label: str,
    maximum_length: int,
) -> str:
    """Validate one non-empty, whitespace-normalized text value."""
    normalized = " ".join(value.split())

    if not normalized:
        raise ValueError(f"{label} must not be empty")

    if normalized != value:
        raise ValueError(f"{label} must be whitespace-normalized")

    if len(value) > maximum_length:
        raise ValueError(f"{label} exceeds maximum length")

    return value


class EvidenceSourceKind(StrEnum):
    """Stable categories for evidence and provenance references."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    OWNER_INPUT = "OWNER_INPUT"
    EMPIRICAL_RESEARCH = "EMPIRICAL_RESEARCH"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    SYSTEM_ARTIFACT = "SYSTEM_ARTIFACT"


class EpistemicStatus(StrEnum):
    """Allowed epistemic classifications for User Twin observations."""

    USER_PROVIDED = "USER_PROVIDED"
    EMPIRICALLY_SUPPORTED = "EMPIRICALLY_SUPPORTED"
    HUMAN_VALIDATED = "HUMAN_VALIDATED"
    MODEL_INFERRED = "MODEL_INFERRED"
    UNSUPPORTED_ASSUMPTION = "UNSUPPORTED_ASSUMPTION"


class HumanValidationRequirement(StrEnum):
    """Whether an observation requires explicit human validation."""

    REQUIRED = "REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ObservationValueKind(StrEnum):
    """Shapes supported by structured profile observations."""

    TEXT = "TEXT"
    ITEMS = "ITEMS"
    UNKNOWN = "UNKNOWN"
    ABSTAINED = "ABSTAINED"


@dataclass(
    frozen=True,
    slots=True,
    order=True,
)
class ConfidenceScore:
    """A finite confidence value in the inclusive unit interval."""

    value: float

    def __post_init__(self) -> None:
        """Protect confidence type, finiteness, and range."""
        if isinstance(
            self.value,
            bool,
        ) or not isinstance(
            self.value,
            Real,
        ):
            raise TypeError("confidence must be a real number")

        normalized = float(self.value)

        if not math.isfinite(normalized):
            raise ValueError("confidence must be finite")

        if not (0.0 <= normalized <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")

        object.__setattr__(
            self,
            "value",
            normalized,
        )

    def to_snapshot(self) -> float:
        """Return a JSON-serializable confidence value."""
        return self.value


@dataclass(
    frozen=True,
    slots=True,
)
class EvidenceReference:
    """One inspectable reference supporting an observation."""

    source_kind: EvidenceSourceKind
    source_id: str
    source_version: int | None = None
    content_hash: str | None = None
    locator: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        """Protect reference identity and optional audit metadata."""
        _require_normalized_text(
            self.source_id,
            label="evidence source ID",
            maximum_length=(_MAX_SOURCE_ID_LENGTH),
        )

        if self.source_version is not None:
            if isinstance(
                self.source_version,
                bool,
            ) or not isinstance(
                self.source_version,
                int,
            ):
                raise TypeError("evidence source version must be an integer")

            if self.source_version < 1:
                raise ValueError("evidence source version must be positive")

        if self.content_hash is not None and _SHA256_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("evidence content hash must be a lowercase SHA-256 digest")

        if self.locator is not None:
            _require_normalized_text(
                self.locator,
                label="evidence locator",
                maximum_length=(_MAX_LOCATOR_LENGTH),
            )

        if self.summary is not None:
            _require_normalized_text(
                self.summary,
                label="evidence summary",
                maximum_length=(_MAX_SUMMARY_LENGTH),
            )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable evidence snapshot."""
        return {
            "source_kind": (self.source_kind.value),
            "source_id": self.source_id,
            "source_version": (self.source_version),
            "content_hash": (self.content_hash),
            "locator": self.locator,
            "summary": self.summary,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class ObservationProvenance:
    """Ordered, non-empty, and duplicate-free provenance."""

    references: tuple[
        EvidenceReference,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect minimum provenance and reference uniqueness."""
        if not self.references:
            raise ValueError("observation provenance must not be empty")

        if len(self.references) != len(set(self.references)):
            raise ValueError("observation provenance references must be unique")

    @classmethod
    def from_references(
        cls,
        references: Iterable[EvidenceReference],
    ) -> ObservationProvenance:
        """Create provenance from an evidence-reference iterable."""
        return cls(references=tuple(references))

    def to_snapshot(
        self,
    ) -> list[dict[str, object]]:
        """Return provenance in stable supplied order."""
        return [reference.to_snapshot() for reference in self.references]


@dataclass(
    frozen=True,
    slots=True,
)
class ObservationValue:
    """A scalar, list, unknown value, or explicit abstention."""

    kind: ObservationValueKind
    text: str | None = None
    items: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        """Protect the value shape selected by its explicit kind."""
        if self.kind is ObservationValueKind.TEXT:
            if self.text is None or self.items or self.reason is not None:
                raise ValueError("text observations require only text")

            _require_normalized_text(
                self.text,
                label="observation text",
                maximum_length=(_MAX_OBSERVATION_TEXT_LENGTH),
            )
            return

        if self.kind is ObservationValueKind.ITEMS:
            if self.text is not None or not self.items or self.reason is not None:
                raise ValueError("item observations require only non-empty items")

            for item in self.items:
                _require_normalized_text(
                    item,
                    label="observation item",
                    maximum_length=(_MAX_OBSERVATION_ITEM_LENGTH),
                )

            if len(self.items) != len(set(self.items)):
                raise ValueError("observation items must be unique")

            return

        if self.kind is ObservationValueKind.UNKNOWN:
            if self.text is not None or self.items or self.reason is not None:
                raise ValueError("unknown observations must not contain a value")

            return

        if self.text is not None or self.items or self.reason is None:
            raise ValueError("abstained observations require only a reason")

        _require_normalized_text(
            self.reason,
            label="abstention reason",
            maximum_length=(_MAX_ABSTENTION_REASON_LENGTH),
        )

    @classmethod
    def from_text(
        cls,
        value: str,
    ) -> ObservationValue:
        """Create a normalized text observation value."""
        return cls(
            kind=(ObservationValueKind.TEXT),
            text=" ".join(value.split()),
        )

    @classmethod
    def from_items(
        cls,
        values: Iterable[str],
    ) -> ObservationValue:
        """Create a normalized item observation value."""
        return cls(
            kind=(ObservationValueKind.ITEMS),
            items=tuple(" ".join(value.split()) for value in values),
        )

    @classmethod
    def unknown(
        cls,
    ) -> ObservationValue:
        """Create an explicit unknown value."""
        return cls(kind=(ObservationValueKind.UNKNOWN))

    @classmethod
    def abstained(
        cls,
        reason: str,
    ) -> ObservationValue:
        """Create an explicit abstention with a normalized reason."""
        return cls(
            kind=(ObservationValueKind.ABSTAINED),
            reason=" ".join(reason.split()),
        )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable value snapshot."""
        return {
            "kind": self.kind.value,
            "text": self.text,
            "items": list(self.items),
            "reason": self.reason,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class ProfileObservation:
    """One profile observation with explicit epistemic metadata."""

    observation_key: str
    value: ObservationValue
    epistemic_status: EpistemicStatus
    confidence: ConfidenceScore
    provenance: ObservationProvenance
    human_validation: HumanValidationRequirement
    rationale: str | None = None

    def __post_init__(self) -> None:
        """Protect identity and model-generated uncertainty rules."""
        if _OBSERVATION_KEY_PATTERN.fullmatch(self.observation_key) is None:
            raise ValueError("observation key must be a lowercase stable identifier")

        if self.rationale is not None:
            _require_normalized_text(
                self.rationale,
                label="observation rationale",
                maximum_length=(_MAX_RATIONALE_LENGTH),
            )

        if self.epistemic_status in {
            EpistemicStatus.MODEL_INFERRED,
            EpistemicStatus.UNSUPPORTED_ASSUMPTION,
        }:
            if self.human_validation is not HumanValidationRequirement.REQUIRED:
                raise ValueError(
                    "model-inferred and unsupported observations require human validation"
                )

            if self.rationale is None:
                raise ValueError("model-inferred and unsupported observations require a rationale")

        if self.epistemic_status is EpistemicStatus.UNSUPPORTED_ASSUMPTION and self.value.kind in {
            ObservationValueKind.UNKNOWN,
            ObservationValueKind.ABSTAINED,
        }:
            raise ValueError("an unsupported assumption must contain a tentative value")

    @property
    def requires_human_validation(
        self,
    ) -> bool:
        """Return whether explicit human validation is required."""
        return self.human_validation is HumanValidationRequirement.REQUIRED

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable observation snapshot."""
        return {
            "observation_key": (self.observation_key),
            "value": (self.value.to_snapshot()),
            "epistemic_status": (self.epistemic_status.value),
            "confidence": (self.confidence.to_snapshot()),
            "provenance": (self.provenance.to_snapshot()),
            "human_validation": (self.human_validation.value),
            "rationale": self.rationale,
        }
