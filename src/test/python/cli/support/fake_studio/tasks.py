from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from orchestwin.knowledge.state import (
    MAX_TASK_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MAX_TASKS,
    TASK_STATUSES,
)

from .common import _error, _model_rule, _optional_line, _prepared_task, _single_line, _task_origin
from .fields import _Fields
from .values import COMMIT_PATTERN, _Answer, _Invalid, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


TASK_CODE = re.compile(r"TSK-[0-9]{3,6}", re.IGNORECASE)
TASK_FILTERS = ("open", "all")
TASK_FIELDS = ("tasks",)
TASK_ITEM_FIELDS = ("text", "source")
SOURCE_FIELDS = {
    "OWNER": ("kind",),
    "TEST_RUN": ("kind", "test_run_id", "twin_id", "finding"),
    "CODE_CHANGE": ("kind", "commit", "twin_id", "finding"),
}
TASK_STATUS_FIELDS = ("status", "note")
CLOSED_STATUSES = ("DONE", "DROPPED")


class _TaskRoutes:
    def _task_list(self, project: FakeProject, *, every: bool) -> list[dict[str, object]]:
        return [
            copy.deepcopy(task) for task in project.code_tasks if every or task["status"] == "OPEN"
        ]

    def _find_task(self, project: FakeProject, code: str) -> dict[str, object]:
        wanted = code.upper()
        task = None
        if TASK_CODE.fullmatch(wanted) is not None:
            task = next((item for item in project.code_tasks if item["code"] == wanted), None)
        if task is None:
            raise _Refusal(404, {"code": "CODE_TASK_NOT_FOUND"})
        return task

    def _resolve_sources(
        self, project: FakeProject, sources: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        runs: dict[int, dict[str, object]] = {}
        changes: dict[int, dict[str, object]] = {}
        refusals: list[_Refusal] = []
        for index, source in enumerate(sources):
            if source["kind"] == "TEST_RUN":
                runs[index] = self._find_test_run(project, str(source["test_run_id"]))
        for index, source in enumerate(sources):
            if source["kind"] == "CODE_CHANGE":
                try:
                    changes[index] = self._find_change(project, str(source["commit"]))
                except _Refusal as refusal:
                    refusals.append(refusal)
        if refusals:
            raise min(refusals, key=lambda refusal: refusal.status == 409)
        resolved: list[dict[str, object]] = []
        for index, source in enumerate(sources):
            if source["kind"] == "OWNER":
                resolved.append({"origin": _task_origin("OWNER"), "finding": None})
                continue
            if source["kind"] == "TEST_RUN":
                record = runs[index]
                review = next(
                    (item for item in project.acceptance_reviews if item["run_id"] == record["id"]),
                    None,
                )
                critiques = [] if review is None else review["critiques"]
                subject = {"test_run_id": str(record["id"])}
            else:
                record = changes[index]
                latest = self._latest_run(project, record["commit"])
                critiques = [] if latest is None else latest["critiques"]
                subject = {"commit": str(record["commit"])}
            critique = next(
                (item for item in critiques if item["twin_id"] == source["twin_id"]), None
            )
            findings = [] if critique is None else critique["findings"]
            position = int(source["finding"])
            if position >= len(findings):
                raise _Refusal(422, {"code": "TASK_SOURCE_INVALID", "index": index})
            finding = findings[position]
            origin = _task_origin(
                str(source["kind"]),
                **subject,
                twin_id=str(critique["twin_id"]),
                twin_name=str(critique["twin_name"]),
                finding=str(finding["text"]),
            )
            resolved.append({"origin": origin, "finding": finding})
        return resolved

    def _new_task(
        self,
        project: FakeProject,
        text: str,
        about: Mapping[str, object],
        origin: Mapping[str, object],
        moment: str,
    ) -> dict[str, object]:
        task: dict[str, object] = {
            "code": f"TSK-{len(project.code_tasks) + 1:03d}",
            "text": text,
            "about": {
                "requirements": list(about["requirements"]),
                "screens": list(about["screens"]),
                "criteria": list(about["criteria"]),
            },
            "origin": dict(origin),
            "from_commit": origin["commit"],
            "created_at": moment,
            "status": "OPEN",
            "closed_at": None,
            "note": None,
        }
        project.code_tasks.append(task)
        return task

    def _create_tasks(
        self,
        project: FakeProject,
        prepared: Sequence[Mapping[str, object]],
        moment: str,
    ) -> tuple[int, list[dict[str, object]]]:
        created = 0
        tasks: list[dict[str, object]] = []
        for item in prepared:
            origin = item["origin"]
            existing = None if origin["twin_id"] is None else _open_task(project, origin)
            if existing is not None:
                tasks.append(existing)
                continue
            tasks.append(self._new_task(project, item["text"], item["about"], origin, moment))
            created += 1
        return created, tasks

    def _route_code_tasks(self, call: _Call) -> _Answer:
        wanted = call.value("status")
        if wanted is not None and wanted not in TASK_FILTERS:
            raise _Invalid([_error(("query", "status"), "literal_error")])
        project = self._code_project(call)
        return _Answer(200, {"items": self._task_list(project, every=wanted == "all")})

    def _route_create_tasks(self, call: _Call) -> _Answer:
        items = _task_items(call.json())
        project = self._code_project(call)
        created, tasks = self._created_tasks(project, items)
        return _Answer(
            201,
            {
                "status": "CREATED",
                "created": created,
                "tasks": copy.deepcopy(tasks),
                "alignment": self._alignment_payload(project),
            },
        )

    def _created_tasks(
        self, project: FakeProject, items: Sequence[Mapping[str, object]]
    ) -> tuple[int, list[dict[str, object]]]:
        resolved = self._resolve_sources(project, [item["source"] for item in items])
        prepared = [
            _prepared_task(item["text"], found) for item, found in zip(items, resolved, strict=True)
        ]
        return self._create_tasks(project, prepared, _iso(self._now()))

    def _route_task_status(self, call: _Call) -> _Answer:
        status, note = _task_status_of(call.json())
        project = self._code_project(call)
        task = self._find_task(project, call.params["code"])
        _set_task_status(task, status, note, _iso(self._now()))
        return _Answer(
            200,
            {
                "status": "UPDATED",
                "task": copy.deepcopy(task),
                "alignment": self._alignment_payload(project),
            },
        )

    def _changed_task(
        self, project: FakeProject, code: str, body: Mapping[str, object]
    ) -> dict[str, object]:
        status, note = _task_status_of(dict(body))
        task = self._find_task(project, code)
        _set_task_status(task, status, note, _iso(self._now()))
        return copy.deepcopy(task)

    def _add_tasks(
        self, project: FakeProject, items: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        _, tasks = self._created_tasks(
            project, _task_items({"tasks": [dict(item) for item in items]})
        )
        return copy.deepcopy(tasks)

    def _seeded(self, work: Callable[[], object]) -> object:
        try:
            return work()
        except _Refusal as refusal:
            raise ValueError(f"the fake studio refuses: {refusal.detail}") from refusal
        except _Invalid as invalid:
            raise ValueError(f"the fake studio refuses: {invalid.errors}") from invalid


def _open_task(project: FakeProject, origin: Mapping[str, object]) -> dict[str, object] | None:
    keys = ("kind", "commit", "test_run_id", "twin_id", "finding")
    return next(
        (
            task
            for task in project.code_tasks
            if task["status"] == "OPEN" and all(task["origin"][key] == origin[key] for key in keys)
        ),
        None,
    )


def _set_task_status(task: dict[str, object], status: str, note: str | None, moment: str) -> None:
    if task["status"] != status:
        task["status"] = status
        task["closed_at"] = moment if status in CLOSED_STATUSES else None
    task["note"] = note


def _source_of(fields: _Fields) -> dict[str, object] | None:
    present, value = fields._get("source", True)
    if not present:
        return None
    location = (*fields.location, "source")
    if not isinstance(value, dict):
        fields.errors.append(_error(location, "model_attributes_type"))
        return None
    if "kind" not in value:
        fields.errors.append(_error(location, "union_tag_not_found"))
        return None
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in SOURCE_FIELDS:
        fields.errors.append(_error(location, "union_tag_invalid"))
        return None
    child = _Fields(value, SOURCE_FIELDS[kind], location=(*location, kind))
    source: dict[str, object] = {"kind": kind}
    if kind == "TEST_RUN":
        source["test_run_id"] = child.identifier("test_run_id")
    elif kind == "CODE_CHANGE":
        source["commit"] = child.pattern("commit", COMMIT_PATTERN)
    if kind != "OWNER":
        source["twin_id"] = child.identifier("twin_id")
        source["finding"] = child.whole("finding", minimum=0)
    fields.adopt(child)
    return source


def _owner_text(source: Mapping[str, object] | None, text: str | None) -> None:
    if source is not None and source["kind"] == "OWNER" and text is None:
        raise ValueError("a task written by the owner needs a text")


def _task_items(body: object) -> list[dict[str, object]]:
    fields = _Fields(body, TASK_FIELDS)
    items = fields.children("tasks", TASK_ITEM_FIELDS, minimum_items=1, maximum_items=MAX_TASKS)
    parsed = []
    for item in items or []:
        text = item.text("text", required=False, nullable=True, minimum=1, maximum=MAX_TASK_LENGTH)
        if text is not None:
            text = item.normalized("text", text, _single_line)
        source = _source_of(item)
        _model_rule(item, lambda source=source, text=text: _owner_text(source, text))
        fields.adopt(item)
        parsed.append({"text": text, "source": source})
    fields.check()
    return parsed


def _task_status_of(body: object) -> tuple[str, str | None]:
    fields = _Fields(body, TASK_STATUS_FIELDS)
    status = fields.choice("status", TASK_STATUSES)
    note = fields.text("note", required=False, nullable=True, maximum=MAX_TASK_NOTE_LENGTH)
    if note is not None:
        note = fields.normalized("note", note, _optional_line)
    fields.check()
    return str(status), note
