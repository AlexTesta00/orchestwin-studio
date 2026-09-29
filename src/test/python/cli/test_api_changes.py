from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.folder import StateSummary
from orchestwin.knowledge import state

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

BASE = f"{API}/projects/{PROJECT_ID}"
COMMIT = "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46"
ALIGNED = "9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e"
CHANGE = {
    "commit": COMMIT,
    "parent": ALIGNED,
    "committed_at": "2026-09-28T11:00:00+00:00",
    "author": "Alex Testa",
    "message": "Controllo del nome vuoto",
    "files": [{"path": "src/app.js", "kind": "MODIFIED", "added": 12, "removed": 3}],
    "recorded_at": "2026-09-28T11:05:00+00:00",
    "review": {
        "run_id": "00000000-0000-4000-8000-00000000d001",
        "reviewed_at": "2026-09-28T11:30:00+00:00",
        "verdict": "CODE_DRIFT",
        "summary": "Il controllo non segue REQ-003.",
    },
    "decision": {"kind": "CODE_TASKS", "decided_at": "2026-09-28T11:40:00+00:00", "note": None},
}
ALIGNMENT = {
    "project_id": PROJECT_ID,
    "reference": {
        "requirements": {"version_id": "r", "version_number": 2, "content_hash": "hr"},
        "design": {
            "version_id": "d",
            "version_number": 4,
            "content_hash": "hd",
            "alternative_code": "DES-002",
        },
    },
    "aligned": {
        "commit": ALIGNED,
        "decided_at": "2026-09-28T10:00:00+00:00",
        "requirements_version_number": 2,
        "design_version_number": 4,
    },
    "pending_changes": 1,
    "latest_change": CHANGE,
    "tasks": [
        {"code": "TSK-001", "text": "Mostrare il messaggio", "status": "OPEN"},
        {"code": "TSK-002", "text": "Chiuso", "status": "DONE"},
    ],
    "review_available": True,
}


def client_for(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport)
    return command_context(bundle.environment).client()


def test_the_constants_follow_the_studio() -> None:
    assert changes_api.VERDICTS == state.VERDICTS
    assert changes_api.DECISIONS == state.DECISIONS
    assert changes_api.CRITIQUE_VERDICTS == state.CRITIQUE_VERDICTS
    assert changes_api.SEVERITIES == state.SEVERITIES
    assert changes_api.MAX_TASKS == state.MAX_TASKS
    assert changes_api.MAX_TASK_LENGTH == state.MAX_TASK_LENGTH
    assert changes_api.MAX_NOTE_LENGTH == state.MAX_NOTE_LENGTH
    assert changes_api.MAX_DESIGN_REQUEST == state.MAX_DESIGN_REQUEST_LENGTH
    assert changes_api.MAX_REQUIREMENTS_REQUEST == state.MAX_REQUIREMENTS_REQUEST_LENGTH
    assert changes_api.NO_REVIEW_MODEL == "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"


def test_the_paths_and_the_body_of_a_review() -> None:
    assert changes_api.changes_path(PROJECT_ID) == f"/projects/{PROJECT_ID}/code-changes"
    assert changes_api.review_path(PROJECT_ID, COMMIT) == (
        f"/projects/{PROJECT_ID}/code-changes/{COMMIT}/reviews"
    )
    assert changes_api.decision_path(PROJECT_ID, COMMIT) == (
        f"/projects/{PROJECT_ID}/code-changes/{COMMIT}/decision"
    )
    assert changes_api.review_body("it-IT", False) == {"locale": "it-IT", "again": False}
    assert changes_api.review_body("en-US", 1) == {"locale": "en-US", "again": True}


def test_the_alignment_and_its_parts(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", f"{BASE}/alignment", body=ALIGNMENT)

    document = changes_api.alignment(client_for(tmp_path, transport), PROJECT_ID)

    assert changes_api.reference(document, "design")["alternative_code"] == "DES-002"
    assert changes_api.reference({"reference": {"design": None}}, "design") is None
    assert changes_api.aligned(document)["commit"] == ALIGNED
    assert [task["code"] for task in changes_api.open_tasks(document)] == ["TSK-001"]
    assert changes_api.pending_count(document) == 1
    assert changes_api.review_available(document) is True
    assert changes_api.verdict_of(CHANGE) == "CODE_DRIFT"
    assert changes_api.decision_of(CHANGE) == "CODE_TASKS"
    assert changes_api.verdict_of({"review": None}) is None
    transport.assert_done()


def test_recording_tells_a_new_change_from_one_already_recorded(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{BASE}/code-changes", status=201, body={"status": "RECORDED", "change": CHANGE}
    )
    transport.expect(
        "POST",
        f"{BASE}/code-changes",
        status=200,
        body={"status": "ALREADY_RECORDED", "change": CHANGE},
    )
    client = client_for(tmp_path, transport)
    body = {"commit": COMMIT, "message": "Controllo del nome vuoto"}

    first = changes_api.record(client, PROJECT_ID, body)
    second = changes_api.record(client, PROJECT_ID, body)

    assert first == (201, {"status": "RECORDED", "change": CHANGE})
    assert second[0] == 200
    assert second[1]["status"] == changes_api.ALREADY_RECORDED
    assert transport.sent[0].json() == body


def test_a_refused_record_raises_with_the_code_of_the_studio(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST",
        f"{BASE}/code-changes",
        status=422,
        body={"detail": "invalid_request", "errors": [{"loc": ["body", "diff"], "type": "x"}]},
    )

    with pytest.raises(ApiFailure) as caught:
        changes_api.record(client_for(tmp_path, transport), PROJECT_ID, {"commit": COMMIT})

    assert (caught.value.code, caught.value.http_status) == ("invalid_request", 422)


def test_lists_single_changes_and_reviews(tmp_path: Path) -> None:
    run = {"id": "run-1", "commit": COMMIT}
    transport = ScriptedTransport()
    transport.expect("GET", f"{BASE}/code-changes", body={"items": [CHANGE]})
    transport.expect("GET", f"{BASE}/code-changes?pending=true", body={"items": []})
    transport.expect("GET", f"{BASE}/code-changes/{COMMIT}", body={**CHANGE, "diff": "+a"})
    transport.expect(
        "GET",
        f"{BASE}/code-changes/{ALIGNED}",
        status=404,
        body={"detail": {"code": "CODE_CHANGE_NOT_FOUND"}},
    )
    transport.expect("GET", f"{BASE}/code-changes/{COMMIT}/reviews", body={"items": [run]})
    client = client_for(tmp_path, transport)

    assert changes_api.changes(client, PROJECT_ID) == [CHANGE]
    assert changes_api.changes(client, PROJECT_ID, pending=True) == []
    assert changes_api.change(client, PROJECT_ID, COMMIT)["diff"] == "+a"
    assert changes_api.change(client, PROJECT_ID, ALIGNED) is None
    assert changes_api.reviews(client, PROJECT_ID, COMMIT) == [run]
    transport.assert_done()


def test_a_decision_sends_clean_tasks_and_no_blank_note(tmp_path: Path) -> None:
    answer = {"status": "DECIDED", "change": CHANGE, "alignment": ALIGNMENT}
    transport = ScriptedTransport()
    transport.expect("POST", f"{BASE}/code-changes/{COMMIT}/decision", body=answer)
    transport.expect("POST", f"{BASE}/code-changes/{COMMIT}/decision", body=answer)
    client = client_for(tmp_path, transport)

    decided = changes_api.decide(
        client,
        PROJECT_ID,
        COMMIT,
        changes_api.CODE_TASKS,
        note="   ",
        tasks=["  Mostrare   il messaggio ", "", "   ", "Aggiungere un test"],
    )
    changes_api.decide(client, PROJECT_ID, COMMIT, changes_api.DISMISSED, note=" covered by x ")

    assert decided == answer
    assert transport.sent[0].json() == {
        "kind": "CODE_TASKS",
        "note": None,
        "tasks": ["Mostrare il messaggio", "Aggiungere un test"],
    }
    assert transport.sent[1].json() == {"kind": "DISMISSED", "note": "covered by x", "tasks": []}


def test_the_summary_of_the_development(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{BASE}/alignment", body=ALIGNMENT)
    transport.expect("GET", f"{BASE}/code-changes", body={"items": [CHANGE, CHANGE]})
    transport.expect("GET", f"{BASE}/alignment", status=404, body={"detail": "Not Found"})
    transport.expect(
        "GET", f"{BASE}/alignment", status=503, body={"detail": {"code": "DATABASE_UNAVAILABLE"}}
    )
    transport.expect("GET", f"{BASE}/alignment", status=403, body={"detail": {"code": "FORBIDDEN"}})
    client = client_for(tmp_path, transport)

    assert changes_api.summary(client, PROJECT_ID) == StateSummary(
        changes=2, pending_changes=1, aligned_commit=ALIGNED, open_tasks=1
    )
    assert changes_api.summary(client, PROJECT_ID) is None
    assert changes_api.summary(client, PROJECT_ID) is None
    with pytest.raises(ApiFailure):
        changes_api.summary(client, PROJECT_ID)


def test_the_codes_of_an_answer() -> None:
    assert changes_api.code_of({"detail": {"code": "CODE_CHANGE_REVIEW_EXISTS"}}) == (
        "CODE_CHANGE_REVIEW_EXISTS"
    )
    assert changes_api.code_of({"detail": "invalid_request"}) == "invalid_request"
    assert changes_api.code_of({"status": "REVIEWED"}) is None
    assert changes_api.code_of("text") is None
    failure = changes_api.failure(409, {"detail": {"code": "CODE_CHANGE_AMBIGUOUS"}})
    assert (failure.code, failure.http_status, failure.status) == ("CODE_CHANGE_AMBIGUOUS", 409, 1)
    assert changes_api.failure(502, None).code == "API_FAILURE"
    run = {"alignment": {"status": "ALIGNED"}}
    assert changes_api.run_status(run) == "ALIGNED"
    assert changes_api.run_alignment({}) == {}
