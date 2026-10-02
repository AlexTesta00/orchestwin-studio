from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.knowledge import state

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, NoNetwork, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"
COMMIT = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
RUN_ID = "00000000-0000-4000-8000-00000000e001"
TWIN_ID = "00000000-0000-4000-8000-0000000000b1"
OTHER_TWIN = "00000000-0000-4000-8000-0000000000b2"
CREATED = "2026-09-29T16:48:37+00:00"
FINDING = "On the page I still cannot find what requirement REQ-003 asks for."
NO_ORIGIN = {
    "commit": None,
    "test_run_id": None,
    "twin_id": None,
    "twin_name": None,
    "finding": None,
}


def task(
    code: str,
    origin: dict[str, object],
    *,
    status: str = "OPEN",
    criteria: tuple[str, ...] = (),
    text: str = "Show the message.",
) -> dict[str, object]:
    return {
        "code": code,
        "text": text,
        "about": {"requirements": [], "screens": [], "criteria": list(criteria)},
        "origin": origin,
        "from_commit": origin.get("commit"),
        "created_at": CREATED,
        "status": status,
        "closed_at": None if status == "OPEN" else CREATED,
        "note": None,
    }


OWNER_TASK = task("TSK-004", {"kind": "OWNER", **NO_ORIGIN})
VERDICT_TASK = task("TSK-001", {"kind": "CODE_CHANGE", **NO_ORIGIN, "commit": COMMIT})
CHANGE_TASK = task(
    "TSK-002",
    {
        "kind": "CODE_CHANGE",
        **NO_ORIGIN,
        "commit": COMMIT,
        "twin_id": TWIN_ID,
        "twin_name": "Pizzeria owner",
        "finding": FINDING,
    },
)
TEST_TASK = task(
    "TSK-003",
    {
        "kind": "TEST_RUN",
        **NO_ORIGIN,
        "test_run_id": RUN_ID,
        "twin_id": TWIN_ID,
        "twin_name": "Pizzeria owner",
        "finding": "Criterion AC-001 should be tried on a phone too.",
    },
    criteria=("AC-001", "AC-002"),
)
OLD_TASK = {
    "code": "TSK-005",
    "text": "Replace the free field of the percentage with three buttons.",
    "about": {"requirements": ["REQ-001"], "screens": ["SCR-001"]},
    "from_commit": COMMIT,
    "created_at": CREATED,
    "status": "OPEN",
}


def client_for(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment).client()


def test_the_words_and_the_limits_follow_the_studio() -> None:
    assert tasks_api.TASK_STATUSES == state.TASK_STATUSES
    assert tasks_api.TASK_ORIGINS == state.TASK_ORIGINS
    assert tasks_api.MAX_TASKS == state.MAX_TASKS
    assert tasks_api.MAX_TASK_LENGTH == state.MAX_TASK_LENGTH
    assert tasks_api.MAX_TASK_NOTE_LENGTH == state.MAX_TASK_NOTE_LENGTH
    assert tasks_api.MAX_FINDING_LENGTH == state.MAX_FINDING_LENGTH
    assert (tasks_api.OPEN, tasks_api.DONE, tasks_api.DROPPED) == state.TASK_STATUSES
    assert (tasks_api.CODE_CHANGE, tasks_api.TEST_RUN, tasks_api.OWNER) == state.TASK_ORIGINS


def test_the_paths_and_the_bodies() -> None:
    assert tasks_api.tasks_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/code-tasks"
    assert tasks_api.list_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/code-tasks?status=open"
    assert tasks_api.list_path(PROJECT_ID, every=True).endswith("/code-tasks?status=all")
    assert tasks_api.status_path(PROJECT_ID, "TSK-004") == (
        f"/projects/{PROJECT_ID}/code-tasks/TSK-004/status"
    )
    assert tasks_api.owner_item("Write the help.") == {
        "text": "Write the help.",
        "source": {"kind": "OWNER"},
    }
    source = tasks_api.run_source(RUN_ID, TWIN_ID, 1)
    assert source == {"kind": "TEST_RUN", "test_run_id": RUN_ID, "twin_id": TWIN_ID, "finding": 1}
    assert tasks_api.change_source(COMMIT, TWIN_ID, 0) == {
        "kind": "CODE_CHANGE",
        "commit": COMMIT,
        "twin_id": TWIN_ID,
        "finding": 0,
    }
    assert tasks_api.finding_item(source) == {"text": None, "source": source}
    assert tasks_api.status_body("DONE", "fixed") == {"status": "DONE", "note": "fixed"}
    assert tasks_api.status_body("OPEN") == {"status": "OPEN", "note": None}


def test_the_tasks_are_read_open_or_all(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{BASE}/code-tasks?status=open", body={"items": [OWNER_TASK, 3]})
    transport.expect("GET", f"{BASE}/code-tasks?status=all", body={"items": [OLD_TASK]})
    transport.expect("GET", f"{BASE}/code-tasks?status=open", body={"nothing": True})
    client = client_for(tmp_path, transport)

    assert tasks_api.tasks(client, PROJECT_ID) == [OWNER_TASK]
    assert tasks_api.tasks(client, PROJECT_ID, every=True) == [OLD_TASK]
    assert tasks_api.tasks(client, PROJECT_ID) == []
    transport.assert_done()


def test_creating_answers_the_document_and_a_refusal_carries_its_values(tmp_path: Path) -> None:
    created = {"status": "CREATED", "created": 1, "tasks": [OWNER_TASK], "alignment": {}}
    transport = ScriptedTransport()
    transport.expect("POST", f"{BASE}/code-tasks", status=201, body=created)
    transport.expect(
        "POST",
        f"{BASE}/code-tasks",
        status=422,
        body={"detail": {"code": "TASK_SOURCE_INVALID", "index": 1}},
    )
    transport.expect(
        "POST",
        f"{BASE}/code-tasks",
        status=404,
        body={"detail": {"code": "TEST_RUN_NOT_FOUND"}},
    )
    client = client_for(tmp_path, transport)
    items = [tasks_api.owner_item("Write the help.")]

    answered = tasks_api.create(client, PROJECT_ID, items)
    with pytest.raises(ApiFailure) as invalid:
        tasks_api.create(client, PROJECT_ID, items)
    with pytest.raises(ApiFailure) as missing:
        tasks_api.create(client, PROJECT_ID, items, run=RUN_ID)

    assert answered == (201, created)
    assert transport.sent[0].json() == {"tasks": items}
    assert (invalid.value.code, invalid.value.http_status, invalid.value.status) == (
        "TASK_SOURCE_INVALID",
        422,
        1,
    )
    assert (invalid.value.values["index"], invalid.value.values["number"]) == (1, 2)
    assert (missing.value.code, missing.value.values["run"]) == ("TEST_RUN_NOT_FOUND", RUN_ID)


def test_many_findings_are_created_ten_at_a_time(tmp_path: Path) -> None:
    items = [
        tasks_api.finding_item(tasks_api.run_source(RUN_ID, TWIN_ID, index)) for index in range(12)
    ]
    first = {"status": "CREATED", "created": 10, "tasks": [TEST_TASK] * 10}
    second = {"status": "CREATED", "created": 1, "tasks": [TEST_TASK, OWNER_TASK]}
    transport = ScriptedTransport()
    transport.expect("POST", f"{BASE}/code-tasks", status=201, body=first)
    transport.expect("POST", f"{BASE}/code-tasks", status=201, body=second)
    client = client_for(tmp_path, transport)

    count, created = tasks_api.create_all(client, PROJECT_ID, items)

    assert count == 11
    assert len(created) == 12
    assert [len(request.json()["tasks"]) for request in transport.sent] == [10, 2]
    assert transport.sent[1].json()["tasks"][1]["source"]["finding"] == 11


def test_a_change_of_status_answers_the_task_and_a_missing_task_is_named(tmp_path: Path) -> None:
    updated = {"status": "UPDATED", "task": {**OWNER_TASK, "status": "DONE"}, "alignment": {}}
    transport = ScriptedTransport()
    transport.expect("POST", f"{BASE}/code-tasks/TSK-004/status", body=updated)
    transport.expect(
        "POST",
        f"{BASE}/code-tasks/TSK-009/status",
        status=404,
        body={"detail": {"code": "CODE_TASK_NOT_FOUND"}},
    )
    client = client_for(tmp_path, transport)

    document = tasks_api.set_status(client, PROJECT_ID, "TSK-004", "DONE", note="fixed")
    with pytest.raises(ApiFailure) as missing:
        tasks_api.set_status(client, PROJECT_ID, "TSK-009", "DROPPED")

    assert tasks_api.changed_task(document) == updated["task"]
    assert transport.sent[0].json() == {"status": "DONE", "note": "fixed"}
    assert transport.sent[1].json() == {"status": "DROPPED", "note": None}
    assert (missing.value.code, missing.value.values["task"]) == ("CODE_TASK_NOT_FOUND", "TSK-009")


def test_the_readers_of_an_answer() -> None:
    assert tasks_api.created_count({"created": 2, "tasks": []}) == 2
    assert tasks_api.created_count({"created": True, "tasks": [OWNER_TASK]}) == 1
    assert tasks_api.created_tasks({"tasks": [OWNER_TASK, "noise"]}) == [OWNER_TASK]
    assert tasks_api.changed_task({"task": "noise"}) is None
    assert tasks_api.code_of({"detail": "invalid_request"}) == "invalid_request"
    assert tasks_api.code_of({"detail": {"code": ""}}) is None
    assert tasks_api.code_of(None) is None
    assert tasks_api.failure(502, "Bad Gateway").code == "API_FAILURE"
    assert "index" not in tasks_api.failure(422, {"detail": {"code": "X", "index": -1}}).values


def test_the_readers_accept_a_task_of_sprint_26() -> None:
    assert tasks_api.origin_of(OLD_TASK) == {"kind": "CODE_CHANGE", **NO_ORIGIN, "commit": COMMIT}
    assert tasks_api.origin_of({"code": "TSK-006"})["commit"] is None
    assert tasks_api.criteria_of(OLD_TASK) == ()
    assert tasks_api.criteria_of(TEST_TASK) == ("AC-001", "AC-002")
    assert tasks_api.task_status(OLD_TASK) == "OPEN"
    assert tasks_api.task_status({"status": "LATER"}) == ""
    assert tasks_api.task_code({"text": "no code"}) == "-"
    assert tasks_api.task_text({"text": "  two\n lines "}) == "two lines"
    assert tasks_api.open_tasks([OLD_TASK, {**OWNER_TASK, "status": "DONE"}]) == [OLD_TASK]


@pytest.mark.parametrize(
    ("value", "valid", "normal"),
    [
        ("TSK-004", True, "TSK-004"),
        (" tsk-123456 ", True, "TSK-123456"),
        ("TSK-12", False, "TSK-12"),
        ("TSK-1234567", False, "TSK-1234567"),
        ("task-004", False, "TASK-004"),
        ("", False, ""),
    ],
)
def test_the_codes_of_the_tasks(value: str, valid: bool, normal: str) -> None:
    assert tasks_api.valid_code(value) is valid
    assert tasks_api.normal_code(value) == normal


def test_the_text_of_a_task_from_a_finding_follows_the_studio() -> None:
    assert tasks_api.finding_text(FINDING, "Show the requirement.") == "Show the requirement."
    assert tasks_api.finding_text(FINDING, "   ") == FINDING
    assert tasks_api.finding_text("  a   b  ") == "a b"
    long = "word " * 80
    cut = tasks_api.finding_text(long)
    assert len(cut) == 300
    assert cut.endswith("…")
    assert cut[:-1] == cut[:-1].rstrip()


def test_a_finding_is_already_a_task_when_an_open_task_has_its_origin() -> None:
    def same(item: dict[str, object], **changes: str) -> bool:
        wanted = {
            "kind": "CODE_CHANGE",
            "subject": COMMIT,
            "twin_id": TWIN_ID,
            "finding": FINDING,
            **changes,
        }
        return tasks_api.same_finding(item, **wanted)

    assert same(CHANGE_TASK)
    assert same(CHANGE_TASK, subject=COMMIT.upper(), finding=f"  {FINDING.replace(' ', '  ')} ")
    assert not same(CHANGE_TASK, twin_id=OTHER_TWIN)
    assert not same(CHANGE_TASK, finding="Another finding.")
    assert not same(CHANGE_TASK, subject="1" * 40)
    assert not same(CHANGE_TASK, subject="")
    assert not same({**CHANGE_TASK, "status": "DONE"})
    assert not same(VERDICT_TASK, finding="")
    assert not same(TEST_TASK, finding=str(TEST_TASK["origin"]["finding"]))
    assert tasks_api.same_finding(
        TEST_TASK,
        kind="TEST_RUN",
        subject=RUN_ID,
        twin_id=TWIN_ID,
        finding="Criterion AC-001 should be tried on a phone too.",
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_origin_in_words(tmp_path: Path, language: str) -> None:
    context = command_context(
        terminal(tmp_path, transport=NoNetwork()).environment, language=language
    )

    def said(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    assert tasks_api.origin_text(context, OWNER_TASK) == said("tasks.origin_owner")
    assert tasks_api.origin_text(context, VERDICT_TASK) == said(
        "tasks.origin_verdict", commit="4f2a9c1"
    )
    assert tasks_api.origin_text(context, OLD_TASK) == said(
        "tasks.origin_verdict", commit="4f2a9c1"
    )
    assert tasks_api.origin_text(context, CHANGE_TASK) == said(
        "tasks.origin_commit", twin="Pizzeria owner", commit="4f2a9c1"
    )
    assert tasks_api.origin_text(context, TEST_TASK) == said(
        "tasks.origin_test", twin="Pizzeria owner"
    )
    assert tasks_api.origin_text(context, TEST_TASK, {RUN_ID: "2026-09-29"}) == said(
        "tasks.origin_test_named", twin="Pizzeria owner", run="2026-09-29"
    )
    nameless = {**CHANGE_TASK, "origin": {**CHANGE_TASK["origin"], "twin_name": None}}
    assert tasks_api.origin_text(context, nameless, {COMMIT: "4f2a9c1 Add"}) == said(
        "tasks.origin_commit", twin=said("tasks.origin_some_twin"), commit="4f2a9c1 Add"
    )
