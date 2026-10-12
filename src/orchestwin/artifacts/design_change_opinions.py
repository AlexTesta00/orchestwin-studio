from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.artifacts.design import contains_control_character
from orchestwin.artifacts.design_discussion import MAX_TWIN_NAME_LENGTH
from orchestwin.artifacts.generated_mockup_review import CONTROL_BORDER_THRESHOLD
from orchestwin.artifacts.visual_catalog import MODES, ColorMode
from orchestwin.models.design_change import MAX_OWNER_REQUEST_LENGTH
from orchestwin.projects.requirements_primitives import (
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.twins.limits import MAX_USER_TWINS
from orchestwin.twins.profile_checks import normalized_text

VERDICTS: Final = ("HELPS", "SLOWS", "BLOCKS")
MAX_WHY_LENGTH: Final = 600
MAX_WHAT_TO_DO_LENGTH: Final = 400
MAX_TRY_THIS_LENGTH: Final = 1000
MAX_PROFILE_KEYS: Final = 4
MIN_LOCALE_LENGTH: Final = 2
MAX_LOCALE_LENGTH: Final = 20


def normalize_owner_request(value: str) -> str:
    text = normalized_text(value, maximum=MAX_OWNER_REQUEST_LENGTH)
    if contains_control_character(text):
        raise ValueError("the request of the owner must not hold control characters")
    return text


def _require_text(value: object, *, label: str, maximum: int) -> None:
    if normalized_text(value, maximum=maximum) != value:
        raise ValueError(f"{label} must be normalized text")


def _require_profile_keys(keys: object) -> None:
    if (
        not isinstance(keys, tuple)
        or not 1 <= len(keys) <= MAX_PROFILE_KEYS
        or len(set(keys)) != len(keys)
        or not all(isinstance(key, str) and key for key in keys)
    ):
        raise ValueError(f"a change opinion derives from 1 to {MAX_PROFILE_KEYS} profile keys")


@dataclass(frozen=True, slots=True)
class ChangeOpinion:
    twin_id: UUID
    twin_version: int
    twin_name: str
    verdict: str
    why: str
    what_to_do: str
    try_this: str | None
    profile_keys: tuple[str, ...]
    confidence: float
    generation_id: UUID

    def __post_init__(self) -> None:
        if not isinstance(self.twin_id, UUID) or not isinstance(self.generation_id, UUID):
            raise ValueError("a change opinion names its twin and its generation")
        validate_positive_integer(self.twin_version, label="change opinion twin version")
        _require_text(self.twin_name, label="the twin name", maximum=MAX_TWIN_NAME_LENGTH)
        if self.verdict not in VERDICTS:
            raise ValueError("a change opinion helps, slows or blocks the twin")
        _require_text(self.why, label="the reason", maximum=MAX_WHY_LENGTH)
        _require_text(self.what_to_do, label="the action", maximum=MAX_WHAT_TO_DO_LENGTH)
        if self.try_this is not None:
            _require_text(self.try_this, label="the request to try", maximum=MAX_TRY_THIS_LENGTH)
        _require_profile_keys(self.profile_keys)
        if type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("a change opinion confidence is a float between 0 and 1")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "twin_version": self.twin_version,
            "twin_name": self.twin_name,
            "verdict": self.verdict,
            "why": self.why,
            "what_to_do": self.what_to_do,
            "try_this": self.try_this,
            "profile_keys": list(self.profile_keys),
            "confidence": self.confidence,
            "generation_id": str(self.generation_id),
        }

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, object]) -> ChangeOpinion:
        return cls(
            twin_id=UUID(str(payload["twin_id"])),
            twin_version=payload["twin_version"],
            twin_name=payload["twin_name"],
            verdict=payload["verdict"],
            why=payload["why"],
            what_to_do=payload["what_to_do"],
            try_this=payload["try_this"],
            profile_keys=tuple(payload["profile_keys"]),
            confidence=payload["confidence"],
            generation_id=UUID(str(payload["generation_id"])),
        )


@dataclass(frozen=True, slots=True)
class ChangeOpinionContrast:
    mode: ColorMode
    text_threshold: float
    large_text_threshold: float
    control_border_threshold: float

    def to_snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "text_threshold": self.text_threshold,
            "large_text_threshold": self.large_text_threshold,
            "control_border_threshold": self.control_border_threshold,
        }


def change_opinion_contrast(mode: ColorMode) -> ChangeOpinionContrast:
    rules = MODES[mode]
    return ChangeOpinionContrast(
        mode=mode,
        text_threshold=rules.text_threshold,
        large_text_threshold=rules.ui_threshold,
        control_border_threshold=CONTROL_BORDER_THRESHOLD,
    )


@dataclass(frozen=True, slots=True)
class ChangeOpinionRun:
    id: UUID
    project_id: UUID
    design_version_id: UUID
    design_content_hash: str
    request: str
    target: Mapping[str, object]
    locale: str
    requested_at: datetime
    opinions: tuple[ChangeOpinion, ...]
    contrast: ChangeOpinionContrast
    cost_microusd: int

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) for value in (self.id, self.project_id, self.design_version_id)
        ):
            raise ValueError("a change opinion run names its project and its design version")
        validate_sha256(self.design_content_hash, label="change opinion design content hash")
        if normalize_owner_request(self.request) != self.request:
            raise ValueError("the request of a change opinion run must be normalized")
        if not isinstance(self.target, Mapping) or not isinstance(
            self.target.get("screen_code"), str
        ):
            raise ValueError("the target of a change opinion run names its screen")
        if not isinstance(self.locale, str) or not (
            MIN_LOCALE_LENGTH <= len(self.locale) <= MAX_LOCALE_LENGTH
        ):
            raise ValueError("the locale of a change opinion run is a language tag")
        if not isinstance(self.requested_at, datetime) or self.requested_at.utcoffset() is None:
            raise ValueError("a change opinion run is requested at a timezone-aware time")
        self._require_opinions()
        if not isinstance(self.contrast, ChangeOpinionContrast):
            raise ValueError("a change opinion run keeps the contrast rules of the design")
        if type(self.cost_microusd) is not int or self.cost_microusd < 0:
            raise ValueError("the cost of a change opinion run is a non-negative integer")

    def _require_opinions(self) -> None:
        opinions = self.opinions
        if not isinstance(opinions, tuple) or not all(
            isinstance(opinion, ChangeOpinion) for opinion in opinions
        ):
            raise ValueError("the opinions of a change opinion run are a tuple of opinions")
        twins = {opinion.twin_id for opinion in opinions}
        if not 1 <= len(opinions) <= MAX_USER_TWINS or len(twins) != len(opinions):
            raise ValueError("a change opinion run holds one opinion for each twin")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "design_version_id": str(self.design_version_id),
            "design_content_hash": self.design_content_hash,
            "request": self.request,
            "target": dict(self.target),
            "locale": self.locale,
            "requested_at": self.requested_at.isoformat(),
            "opinions": [opinion.to_snapshot() for opinion in self.opinions],
            "contrast": self.contrast.to_snapshot(),
            "cost_microusd": self.cost_microusd,
        }

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


__all__ = [
    "MAX_LOCALE_LENGTH",
    "MAX_PROFILE_KEYS",
    "MAX_TRY_THIS_LENGTH",
    "MAX_WHAT_TO_DO_LENGTH",
    "MAX_WHY_LENGTH",
    "MIN_LOCALE_LENGTH",
    "VERDICTS",
    "ChangeOpinion",
    "ChangeOpinionContrast",
    "ChangeOpinionRun",
    "change_opinion_contrast",
    "normalize_owner_request",
]
