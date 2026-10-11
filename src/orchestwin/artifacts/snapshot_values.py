from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from uuid import UUID


def mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def optional_mapping_copy(value: object, *, label: str) -> dict[str, object] | None:
    return None if value is None else dict(mapping(value, label=label))


def sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{label} must be a sequence")
    return value


def mapping_sequence(value: object, *, label: str) -> tuple[Mapping[str, object], ...]:
    return tuple(mapping(item, label=label) for item in sequence(value, label=label))


def string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    return value


def optional_string(value: object, *, label: str) -> str | None:
    return None if value is None else string(value, label=label)


def integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def optional_integer(value: object, *, label: str) -> int | None:
    return None if value is None else integer(value, label=label)


def number(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{label} must be a number")
    return float(value)


def boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError(f"{label} must be a UUID")


def optional_uuid(value: object, *, label: str) -> UUID | None:
    return None if value is None else uuid(value, label=label)


def datetime(value: object, *, label: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        result = value
    elif isinstance(value, str):
        result = dt.datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be a timestamp")
    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result


def optional_datetime(value: object, *, label: str) -> dt.datetime | None:
    return None if value is None else datetime(value, label=label)


def uuid_sequence(value: object, *, label: str) -> tuple[UUID, ...]:
    return tuple(uuid(item, label=label) for item in sequence(value, label=label))


def string_sequence(value: object, *, label: str) -> tuple[str, ...]:
    return tuple(string(item, label=label) for item in sequence(value, label=label))
