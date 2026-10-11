from datetime import datetime
from typing import Final
from uuid import UUID

_SHA256_HEX_LENGTH: Final = 64


def is_sha256_digest(value: str) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def normalized_text(value, *, maximum):
    if not isinstance(value, str):
        raise ValueError("text is required")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("text must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"text exceeds {maximum} characters")
    return normalized


def require_uuid(value, label):
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def require_timestamp(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")
