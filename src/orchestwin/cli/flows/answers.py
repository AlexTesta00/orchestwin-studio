from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from orchestwin.cli.api import brief, requirements
from orchestwin.cli.errors import USAGE_STATUS, CliError

KEYS: Final = (
    "mode",
    "name",
    "idea",
    "answers",
    "proposals",
    "team",
    "profiles",
    "twins",
    "requirements",
)
REQUIREMENT_KEYS: Final = ("changes", "decision")
MODES: Final = ("DESIGN_ONLY", "DESIGN_AND_CODE")
ACCEPT_ALL: Final = "ACCEPT_ALL"
ACCEPT_NONE: Final = "ACCEPT_NONE"
PROPOSAL_CHOICES: Final = (ACCEPT_ALL, ACCEPT_NONE)
CONFIRM_ALL: Final = "CONFIRM_ALL"
PROFILE_CHOICES: Final = (CONFIRM_ALL,)
APPROVE: Final = "APPROVE"
STOP: Final = "STOP"
DECISIONS: Final = (APPROVE, STOP)
MAX_FILE_BYTES: Final = 1_000_000
MAX_CHANGES: Final = 10
INVALID: Final = "ANSWERS_FILE_INVALID"


@dataclass(frozen=True, slots=True)
class Answers:
    path: str
    mode: str | None = None
    name: str | None = None
    idea: str | None = None
    answers: Mapping[str, str | tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    proposals: str = ACCEPT_ALL
    team: str = APPROVE
    profiles: str = CONFIRM_ALL
    twins: str = APPROVE
    changes: tuple[str, ...] = ()
    requirements: str = APPROVE

    def reply(self, turn: Mapping[str, object]) -> dict[str, object]:
        name = turn.get("field")
        value = self.answers.get(name) if isinstance(name, str) else None
        if value is None:
            return brief.unknown_answer()
        if turn.get("answer_type") == brief.ITEM_LIST:
            return brief.list_answer([value] if isinstance(value, str) else list(value))
        return brief.text_answer(value if isinstance(value, str) else "; ".join(value))

    def value(self, name: str) -> str | tuple[str, ...] | None:
        return self.answers.get(name)

    def missing(self, key: str) -> CliError:
        return invalid(self.path, key, "missing")


def load(path: Path) -> Answers:
    shown = str(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise invalid(shown, "", "unreadable") from None
    if len(raw) > MAX_FILE_BYTES:
        raise invalid(shown, "", "unreadable")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise invalid(shown, "", "not_json") from None
    if not isinstance(document, dict):
        raise invalid(shown, "", "not_object")
    _known_keys(shown, document, KEYS, "")
    section = _object(shown, document, "requirements")
    _known_keys(shown, section, REQUIREMENT_KEYS, "requirements.")
    return Answers(
        path=shown,
        mode=_choice(shown, document, "mode", MODES, None),
        name=_text(shown, document, "name", brief.MAX_NAME),
        idea=_text(shown, document, "idea", brief.MAX_STATEMENT),
        answers=MappingProxyType(_dialogue(shown, _object(shown, document, "answers"))),
        proposals=_choice(shown, document, "proposals", PROPOSAL_CHOICES, ACCEPT_ALL),
        team=_choice(shown, document, "team", DECISIONS, APPROVE),
        profiles=_choice(shown, document, "profiles", PROFILE_CHOICES, CONFIRM_ALL),
        twins=_choice(shown, document, "twins", DECISIONS, APPROVE),
        changes=_changes(shown, section),
        requirements=_choice(
            shown, section, "decision", DECISIONS, APPROVE, prefix="requirements."
        ),
    )


def invalid(path: str, key: str, reason: str, **values: object) -> CliError:
    return CliError(
        INVALID,
        status=USAGE_STATUS,
        values={"path": path, "entry": key, "reason": reason, **values},
    )


def _known_keys(
    path: str, document: Mapping[str, object], keys: tuple[str, ...], prefix: str
) -> None:
    for key in document:
        if key not in keys:
            raise invalid(path, f"{prefix}{key}", "unknown_key", allowed=", ".join(keys))


def _object(path: str, document: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = document.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise invalid(path, key, "object")
    return value


def _choice(
    path: str,
    document: Mapping[str, object],
    key: str,
    allowed: tuple[str, ...],
    default: str | None,
    *,
    prefix: str = "",
) -> str | None:
    value = document.get(key)
    if value is None:
        return default
    if value not in allowed:
        raise invalid(
            path,
            f"{prefix}{key}",
            "choice",
            value=json.dumps(value, ensure_ascii=False),
            allowed=", ".join(allowed),
        )
    return str(value)


def _text(path: str, document: Mapping[str, object], key: str, limit: int) -> str | None:
    value = document.get(key)
    if value is None:
        return None
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or len(normalized) > limit:
        raise invalid(path, key, "text", limit=limit)
    return normalized


def _dialogue(path: str, document: Mapping[str, object]) -> dict[str, str | tuple[str, ...]]:
    found: dict[str, str | tuple[str, ...]] = {}
    for key, value in document.items():
        if key not in brief.FIELDS:
            raise invalid(path, f"answers.{key}", "unknown_key", allowed=", ".join(brief.FIELDS))
        if value is None:
            continue
        found[key] = _answer(path, f"answers.{key}", value)
    return found


def _answer(path: str, key: str, value: object) -> str | tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        if text and len(text) <= brief.MAX_ANSWER:
            return text
    elif isinstance(value, list) and 0 < len(value) <= brief.MAX_ITEMS:
        items = tuple(item.strip() for item in value if isinstance(item, str))
        if len(items) == len(value) and all(0 < len(item) <= brief.MAX_ITEM for item in items):
            return items
    raise invalid(path, key, "texts")


def _changes(path: str, document: Mapping[str, object]) -> tuple[str, ...]:
    value = document.get("changes")
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_CHANGES:
        raise invalid(path, "requirements.changes", "texts")
    changes = []
    limit = requirements.MAX_REQUEST
    for index, item in enumerate(value, start=1):
        text = item.strip() if isinstance(item, str) else ""
        if not text or len(text) > limit:
            raise invalid(path, f"requirements.changes[{index}]", "text", limit=limit)
        changes.append(text)
    return tuple(changes)
