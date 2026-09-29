from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

FIELDS: Final = (
    "name",
    "description",
    "problem",
    "goals",
    "target_users",
    "domain",
    "technical_constraints",
    "temporal_constraints",
    "budget",
    "functional_requirements",
    "non_functional_requirements",
    "risks",
    "stakeholders",
    "available_artifacts",
    "definition_of_done",
)
TEXT_FIELDS: Final = frozenset(
    {"name", "description", "problem", "domain", "temporal_constraints", "budget"}
)
LIST_FIELDS: Final = frozenset(field for field in FIELDS if field not in TEXT_FIELDS)
ESSENTIAL_FIELDS: Final = (
    "description",
    "problem",
    "goals",
    "target_users",
    "functional_requirements",
)
ACTIVE_STATUSES: Final = frozenset({"OPEN", "READY"})
READY: Final = "READY"
PROPOSED: Final = "PROPOSED"
TEXT: Final = "TEXT"
ITEM_LIST: Final = "ITEM_LIST"
UNKNOWN: Final = "UNKNOWN"
MODEL_NOT_CONFIGURED: Final = "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED"
DIALOGUE_ACTIVE: Final = "BRIEF_DIALOGUE_ACTIVE"
SYNTHESIS_UNCHANGED: Final = "BRIEF_SYNTHESIS_UNCHANGED"
QUESTION_LIMIT: Final = 20
MAX_STATEMENT: Final = 2000
MAX_ANSWER: Final = 2000
MAX_ITEM: Final = 500
MAX_ITEMS: Final = 20
MAX_NAME: Final = 120


def project_path(project_id: str) -> str:
    return f"/projects/{project_id}"


def current(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    return _mapping(client.get(f"{project_path(project_id)}/brief-versions/current", optional=True))


def create(client: StudioClient, project_id: str, body: Mapping[str, object]) -> tuple[int, object]:
    return _send(client, "POST", f"{project_path(project_id)}/brief-versions", body)


def dialogue(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    return _mapping(client.get(f"{project_path(project_id)}/brief-dialogue", optional=True))


def start(client: StudioClient, project_id: str, statement: str) -> tuple[int, object]:
    return _send(
        client, "POST", f"{project_path(project_id)}/brief-dialogue", {"statement": statement}
    )


def answer(
    client: StudioClient, project_id: str, reply: Mapping[str, object], turns: int
) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/brief-dialogue/answers",
        {**reply, "expected_turn_count": turns},
    )


def ask_next(client: StudioClient, project_id: str, turns: int) -> tuple[int, object]:
    return _turn(client, project_id, "questions", turns)


def synthesize(client: StudioClient, project_id: str, turns: int) -> tuple[int, object]:
    return _turn(client, project_id, "synthesis", turns)


def close(client: StudioClient, project_id: str, turns: int) -> tuple[int, object]:
    return _turn(client, project_id, "close", turns)


def assumptions(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"{project_path(project_id)}/brief-assumptions")
    if not isinstance(document, list):
        return []
    return [item for item in document if isinstance(item, Mapping)]


def proposed(items: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [item for item in items if item.get("status") == PROPOSED]


def accept_all(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{project_path(project_id)}/brief-assumptions/accept-all", {})


def accept(client: StudioClient, project_id: str, assumption_id: str) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/brief-assumptions/{assumption_id}/accept",
        {},
    )


def reject(
    client: StudioClient, project_id: str, assumption_id: str, reason: str
) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/brief-assumptions/{assumption_id}/reject",
        {"reason": reason},
    )


def gate(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    return _mapping(
        client.get(f"{project_path(project_id)}/gates/project-brief/current", optional=True)
    )


def submit_gate(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{project_path(project_id)}/gates/project-brief/submit")


def decide_gate(
    client: StudioClient, project_id: str, action: str = "APPROVE"
) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/gates/project-brief/decisions",
        {"action": action},
    )


def content(version: Mapping[str, object] | None) -> Mapping[str, object]:
    brief = None if version is None else version.get("brief")
    return brief if isinstance(brief, Mapping) else {}


def missing(version: Mapping[str, object] | None) -> list[str]:
    return _texts(content(version).get("missing_fields"))


def unknown(version: Mapping[str, object] | None) -> list[str]:
    return _texts(content(version).get("unknown_fields"))


def request_body(
    brief: Mapping[str, object],
    changes: Mapping[str, object] | None = None,
    unknown_fields: Iterable[str] = (),
) -> dict[str, object]:
    body: dict[str, object] = {}
    unknown_set = set(_texts(brief.get("unknown_fields")))
    for field in FIELDS:
        value = brief.get(field)
        body[field] = list(value) if isinstance(value, list | tuple) else value
    for field, value in (changes or {}).items():
        body[field] = list(value) if isinstance(value, list | tuple) else value
        unknown_set.discard(field)
    for field in unknown_fields:
        body[field] = None
        unknown_set.add(field)
    body["unknown_fields"] = sorted(unknown_set)
    return body


def snapshot(state: Mapping[str, object]) -> Mapping[str, object]:
    value = state.get("snapshot")
    return value if isinstance(value, Mapping) else {}


def status(state: Mapping[str, object]) -> str | None:
    value = snapshot(state).get("status")
    return value if isinstance(value, str) else None


def turns(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = snapshot(state).get("turns")
    if not isinstance(value, list):
        return []
    return [turn for turn in value if isinstance(turn, Mapping)]


def pending(state: Mapping[str, object]) -> Mapping[str, object] | None:
    found = turns(state)
    last = found[-1] if found else None
    return last if last is not None and last.get("answer") is None else None


def progress(state: Mapping[str, object]) -> Mapping[str, object]:
    value = state.get("progress")
    return value if isinstance(value, Mapping) else {}


def open_essential(
    state: Mapping[str, object], turn: Mapping[str, object] | None = None
) -> list[str]:
    found = _texts(progress(state).get("open_essential_fields"))
    essential = _texts(snapshot(state).get("essential_fields")) or list(ESSENTIAL_FIELDS)
    field = None if turn is None else turn.get("field")
    if isinstance(field, str) and field in essential and field not in found:
        found.append(field)
    return found


def question_limit(state: Mapping[str, object]) -> int:
    value = progress(state).get("question_limit")
    valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
    return value if valid else QUESTION_LIMIT


def composed(state: Mapping[str, object]) -> Mapping[str, object] | None:
    version = state.get("brief_version")
    return version if isinstance(version, Mapping) else None


def text_answer(text: str) -> dict[str, object]:
    return {"kind": TEXT, "text": text}


def list_answer(items: Sequence[str]) -> dict[str, object]:
    return {"kind": ITEM_LIST, "items": list(items)}


def unknown_answer() -> dict[str, object]:
    return {"kind": UNKNOWN}


def _turn(client: StudioClient, project_id: str, action: str, turns: int) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/brief-dialogue/{action}",
        {"expected_turn_count": turns},
    )


def _send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _texts(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [str(item) for item in value if isinstance(item, str)]
