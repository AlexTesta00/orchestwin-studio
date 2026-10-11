from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from numbers import Real
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

PROJECTS = sa.table(
    "projects",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
)


def required(mapping: Mapping[str, object], key: str) -> object:
    """Return one required persistence field."""
    if key not in mapping:
        raise ValueError(f"missing persistence field: {key}")
    return mapping[key]


def field[T](record: Mapping[str, object], key: str, parser: Callable[..., T], label: str) -> T:
    return parser(required(record, key), label=label)


def sequence(value: object, *, label: str) -> Sequence[object]:
    """Require a non-string sequence."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    return value


def string(value: object, *, label: str) -> str:
    """Require a string."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def optional_string(value: object, *, label: str) -> str | None:
    """Require string or null."""
    return None if value is None else string(value, label=label)


def integer(value: object, *, label: str) -> int:
    """Require a non-boolean integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def optional_integer(value: object, *, label: str) -> int | None:
    """Require integer or null."""
    return None if value is None else integer(value, label=label)


def real(value: object, *, label: str) -> float:
    """Require a non-boolean real number."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a real number")
    return float(value)


def uuid_value(value: object, *, label: str) -> UUID:
    """Require or reconstruct a UUID."""
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a UUID") from error
    raise ValueError(f"{label} must be a UUID")


def optional_uuid(value: object, *, label: str) -> UUID | None:
    """Require UUID or null."""
    return None if value is None else uuid_value(value, label=label)


def datetime_value(value: object, *, label: str) -> datetime:
    """Require or reconstruct a timezone-aware datetime."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO datetime") from error
    else:
        raise ValueError(f"{label} must be a datetime")
    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result


def optional_datetime(value: object, *, label: str) -> datetime | None:
    """Require datetime or null."""
    return None if value is None else datetime_value(value, label=label)


def owned_project_exists(*, project_id: UUID, owner_user_id: UUID) -> sa.ColumnElement[bool]:
    """Create a reusable owner-project EXISTS predicate."""
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(PROJECTS)
        .where(PROJECTS.c.id == project_id, PROJECTS.c.owner_user_id == owner_user_id)
    )


async def project_is_owned(session: AsyncSession, *, project_id: UUID, owner_user_id: UUID) -> bool:
    """Resolve ownership without leaking foreign-project existence."""
    result = await session.execute(
        sa.select(sa.literal(True)).where(
            owned_project_exists(project_id=project_id, owner_user_id=owner_user_id)
        )
    )
    return result.scalar_one_or_none() is True
