from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID


def aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def uuid_value(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def uuids(values: object, label: str, *, maximum: int | None = None) -> None:
    if not isinstance(values, tuple) or not all(isinstance(item, UUID) for item in values):
        raise ValueError(f"{label} must be a tuple of UUID")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat")
    if maximum is not None and len(values) > maximum:
        raise ValueError(f"{label} hold at most {maximum} items")


def optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def optional_time(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def count(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")


def tuple_of(values: object, kind: type, label: str) -> None:
    if not isinstance(values, tuple) or not all(isinstance(item, kind) for item in values):
        raise ValueError(f"{label} must be a tuple of {kind.__name__}")


def code(value: object, pattern: re.Pattern[str], label: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} holds an invalid code")


def optional_code(value: object, pattern: re.Pattern[str], label: str) -> None:
    if value is not None:
        code(value, pattern, label)


def codes(
    values: object,
    pattern: re.Pattern[str],
    label: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} must be a tuple")
    for value in values:
        code(value, pattern, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat a code")
    if len(values) < minimum or (maximum is not None and len(values) > maximum):
        raise ValueError(f"{label} hold between {minimum} and {maximum} codes")


def control_free(value: str) -> bool:
    return all(ord(character) >= 32 and ord(character) != 127 for character in value)


def normalized_line(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is required")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    if not control_free(normalized):
        raise ValueError(f"{label} must not contain control characters")
    return normalized


def normalized_block(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is required")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    if "\x00" in normalized:
        raise ValueError(f"{label} must not contain a null character")
    return normalized


def normalized(value: object, *, label: str, maximum: int) -> None:
    if normalized_line(value, label=label, maximum=maximum) != value:
        raise ValueError(f"{label} must be normalized")


def optional_normalized(value: object, *, label: str, maximum: int) -> None:
    if value is not None:
        normalized(value, label=label, maximum=maximum)


def optional_text(
    value: object, normalize: Callable[..., str], *, label: str, maximum: int
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a text")
    if not value.strip():
        return None
    return normalize(value, label=label, maximum=maximum)
