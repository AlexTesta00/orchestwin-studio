from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext

TASK_STATUSES: Final = ("OPEN", "DONE", "DROPPED")
TASK_ORIGINS: Final = ("CODE_CHANGE", "TEST_RUN", "OWNER")
OPEN: Final = TASK_STATUSES[0]
DONE: Final = TASK_STATUSES[1]
DROPPED: Final = TASK_STATUSES[2]
CODE_CHANGE: Final = TASK_ORIGINS[0]
TEST_RUN: Final = TASK_ORIGINS[1]
OWNER: Final = TASK_ORIGINS[2]
MAX_TASKS: Final = 10
MAX_TASK_LENGTH: Final = 300
MAX_TASK_NOTE_LENGTH: Final = 300
MAX_FINDING_LENGTH: Final = 400
OPEN_FILTER: Final = "open"
ALL_FILTER: Final = "all"
CREATED: Final = "CREATED"
UPDATED: Final = "UPDATED"
TASK_SOURCE_INVALID: Final = "TASK_SOURCE_INVALID"
CODE_TASK_NOT_FOUND: Final = "CODE_TASK_NOT_FOUND"
TEST_RUN_NOT_FOUND: Final = "TEST_RUN_NOT_FOUND"
CODE_CHANGE_NOT_FOUND: Final = "CODE_CHANGE_NOT_FOUND"
CODE_CHANGE_AMBIGUOUS: Final = "CODE_CHANGE_AMBIGUOUS"
CODE_PATTERN: Final = re.compile(r"TSK-[0-9]{3,6}", re.IGNORECASE)
ORIGIN_KEYS: Final = ("kind", "commit", "test_run_id", "twin_id", "twin_name", "finding")
CUT_MARK: Final = "…"
SHORT_COMMIT: Final = 7


def tasks_path(project_id: str) -> str:
    return f"/projects/{project_id}/code-tasks"


def list_path(project_id: str, *, every: bool = False) -> str:
    return f"{tasks_path(project_id)}?status={ALL_FILTER if every else OPEN_FILTER}"


def status_path(project_id: str, code: str) -> str:
    return f"{tasks_path(project_id)}/{code}/status"


def owner_item(text: str) -> dict[str, object]:
    return {"text": text, "source": {"kind": OWNER}}


def finding_item(source: Mapping[str, object], text: str | None = None) -> dict[str, object]:
    return {"text": text, "source": dict(source)}


def run_source(run_id: str, twin_id: str, finding: int) -> dict[str, object]:
    return {"kind": TEST_RUN, "test_run_id": run_id, "twin_id": twin_id, "finding": finding}


def change_source(commit: str, twin_id: str, finding: int) -> dict[str, object]:
    return {"kind": CODE_CHANGE, "commit": commit, "twin_id": twin_id, "finding": finding}


def status_body(status: str, note: str | None = None) -> dict[str, object]:
    return {"status": status, "note": note}


def tasks(
    client: StudioClient, project_id: str, *, every: bool = False
) -> list[Mapping[str, object]]:
    document = client.get(list_path(project_id, every=every))
    return mappings(document.get("items") if isinstance(document, Mapping) else None)


def create(
    client: StudioClient,
    project_id: str,
    items: Sequence[Mapping[str, object]],
    **values: object,
) -> tuple[int, Mapping[str, object]]:
    body = {"tasks": [dict(item) for item in items]}
    reply = client.request("POST", tasks_path(project_id), body=body)
    document = reply_body(reply)
    if reply.status >= 400:
        raise failure(reply.status, document, **values)
    return reply.status, _mapping_of(document, reply.status)


def create_all(
    client: StudioClient,
    project_id: str,
    items: Sequence[Mapping[str, object]],
    **values: object,
) -> tuple[int, list[Mapping[str, object]]]:
    created = 0
    found: list[Mapping[str, object]] = []
    for start in range(0, len(items), MAX_TASKS):
        _, document = create(client, project_id, items[start : start + MAX_TASKS], **values)
        created += created_count(document)
        found.extend(created_tasks(document))
    return created, found


def set_status(
    client: StudioClient,
    project_id: str,
    code: str,
    status: str,
    *,
    note: str | None = None,
) -> Mapping[str, object]:
    reply = client.request("POST", status_path(project_id, code), body=status_body(status, note))
    document = reply_body(reply)
    if reply.status >= 400:
        raise failure(reply.status, document, task=code)
    return _mapping_of(document, reply.status)


def created_tasks(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    return mappings(document.get("tasks"))


def created_count(document: Mapping[str, object]) -> int:
    count = document.get("created")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    return len(created_tasks(document))


def changed_task(document: Mapping[str, object]) -> Mapping[str, object] | None:
    task = document.get("task")
    return task if isinstance(task, Mapping) else None


def code_of(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str) and detail["code"]:
        return str(detail["code"])
    if isinstance(detail, str) and detail:
        return detail
    return None


def failure(status: int, document: object, **values: object) -> ApiFailure:
    detail = document.get("detail") if isinstance(document, Mapping) else document
    found: dict[str, object] = {}
    index = detail.get("index") if isinstance(detail, Mapping) else None
    if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
        found["index"] = index
        found["number"] = index + 1
    found.update(values)
    return ApiFailure(
        code_of(document) or "API_FAILURE", http_status=status, detail=detail, values=found
    )


def valid_code(value: str) -> bool:
    return CODE_PATTERN.fullmatch(value.strip()) is not None


def normal_code(value: str) -> str:
    return value.strip().upper()


def task_code(task: Mapping[str, object]) -> str:
    return _text(task.get("code")) or "-"


def task_text(task: Mapping[str, object]) -> str:
    return _text(task.get("text"))


def task_status(task: Mapping[str, object]) -> str:
    status = task.get("status")
    return status if isinstance(status, str) and status in TASK_STATUSES else ""


def is_open(task: Mapping[str, object]) -> bool:
    return task.get("status") == OPEN


def open_tasks(items: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [item for item in items if is_open(item)]


def origin_of(task: Mapping[str, object]) -> dict[str, object]:
    origin = task.get("origin")
    if isinstance(origin, Mapping) and origin.get("kind") in TASK_ORIGINS:
        return {key: origin.get(key) for key in ORIGIN_KEYS}
    commit = _text(task.get("from_commit"))
    return {
        "kind": CODE_CHANGE,
        "commit": commit or None,
        "test_run_id": None,
        "twin_id": None,
        "twin_name": None,
        "finding": None,
    }


def criteria_of(task: Mapping[str, object]) -> tuple[str, ...]:
    about = task.get("about")
    values = about.get("criteria") if isinstance(about, Mapping) else None
    if not isinstance(values, list | tuple):
        return ()
    return tuple(dict.fromkeys(code for item in values if (code := _text(item))))


def finding_text(text: str, action: str | None = None) -> str:
    chosen = " ".join((action if action and action.strip() else text).split())
    if len(chosen) <= MAX_TASK_LENGTH:
        return chosen
    return chosen[: MAX_TASK_LENGTH - len(CUT_MARK)].rstrip() + CUT_MARK


def same_finding(
    task: Mapping[str, object], *, kind: str, subject: str, twin_id: str, finding: str
) -> bool:
    if not is_open(task):
        return False
    origin = origin_of(task)
    if origin["kind"] != kind:
        return False
    key = "commit" if kind == CODE_CHANGE else "test_run_id"
    return (
        _text(origin.get(key)).lower() == subject.strip().lower()
        and _text(origin.get("twin_id")).lower() == twin_id.strip().lower()
        and _text(origin.get("finding")) == _text(finding)
        and bool(subject.strip())
    )


def origin_text(
    context: CommandContext,
    task: Mapping[str, object],
    names: Mapping[str, str] | None = None,
) -> str:
    labels = names or {}
    origin = origin_of(task)
    kind = origin["kind"]
    if kind == OWNER:
        return context.text("tasks.origin_owner")
    twin = _text(origin.get("twin_name")) or context.text("tasks.origin_some_twin")
    if kind == TEST_RUN:
        run = _text(origin.get("test_run_id"))
        named = labels.get(run)
        if named:
            return context.text("tasks.origin_test_named", twin=twin, run=named)
        return context.text("tasks.origin_test", twin=twin)
    commit = _text(origin.get("commit"))
    shown = labels.get(commit) or (commit[:SHORT_COMMIT] if commit else "-")
    if not _text(origin.get("twin_id")) and not _text(origin.get("finding")):
        return context.text("tasks.origin_verdict", commit=shown)
    return context.text("tasks.origin_commit", twin=twin, commit=shown)


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_of(document: object, status: int) -> Mapping[str, object]:
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=status)
    return document


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
