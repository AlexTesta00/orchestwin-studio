from __future__ import annotations

from collections.abc import Mapping

from orchestwin.cli.errors import ApiFailure


def squeezed(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def collapsed(text: str) -> str:
    return " ".join(text.split())


def shortened(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def required_mapping(document: object, status: int = 200) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document


def sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def dict_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def version_number_of(version: Mapping[str, object] | None) -> int | None:
    return None if version is None else whole(version.get("version_number"))
