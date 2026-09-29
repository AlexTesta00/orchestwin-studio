from __future__ import annotations

import email
from pathlib import Path

import pytest

from orchestwin.cli.api import imports, twin_chat
from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import ApiFailure
from orchestwin.twins.conversations import MAX_QUESTION_CHARACTERS

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport, Sent

BASE = f"{API}/projects/{PROJECT_ID}"
TWIN_ID = "5d2c0a9e-0000-4000-8000-000000000007"
VERSION_ID = "5d2c0a9e-0000-4000-8000-000000000008"
OLD_VERSION_ID = "5d2c0a9e-0000-4000-8000-000000000009"
CONVERSATION = f"{BASE}/user-twins/{TWIN_ID}/conversation"
ARCHIVE = b"PK-archive-bytes-not-real"


def client_for(tmp_path: Path, transport: ScriptedTransport) -> StudioClient:
    store_session(tmp_path)
    return command_context(terminal(tmp_path, transport=transport).environment).client()


def turn(ordinal: int, question: str, reply: str) -> dict[str, object]:
    return {"ordinal": ordinal, "question": question, "reply": reply, "insights": []}


def conversation(version_id: str, *turns: dict[str, object]) -> dict[str, object]:
    return {
        "id": "conversation-1",
        "twin_id": TWIN_ID,
        "twin_version_id": version_id,
        "twin_name": "Cameriere del turno serale",
        "turns": list(turns),
    }


def form_parts(sent: Sent) -> dict[str, tuple[str | None, bytes]]:
    head = f"Content-Type: {sent.header('content-type')}\r\n\r\n".encode("ascii")
    message = email.message_from_bytes(head + (sent.body or b""))
    parts: dict[str, tuple[str | None, bytes]] = {}
    for part in message.get_payload():
        name = part.get_param("name", header="content-disposition")
        parts[str(name)] = (part.get_filename(), part.get_payload(decode=True))
    return parts


def test_the_question_limit_is_the_one_of_the_studio() -> None:
    assert twin_chat.QUESTION_LIMIT == MAX_QUESTION_CHARACTERS


def test_the_paths_of_the_twin_routes() -> None:
    assert twin_chat.modeling_path("p-1") == "/projects/p-1/user-modeling"
    assert twin_chat.conversation_path("p-1", "t-1") == "/projects/p-1/user-twins/t-1/conversation"
    assert imports.IMPORTS_PATH == "/project-imports"


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"snapshot_exists": True, "approved_current_snapshot": True}, True),
        ({"snapshot_exists": True, "approved_current_snapshot": False}, False),
        ({"snapshot_exists": False, "approved_current_snapshot": False}, False),
        ({"snapshot_exists": True, "approved_current_snapshot": "yes"}, False),
        ({}, False),
    ],
)
def test_the_twins_are_approved_only_when_the_current_snapshot_is(
    document: dict[str, object], expected: bool
) -> None:
    assert twin_chat.approved(document) is expected


def test_readiness_is_read_and_a_wrong_answer_is_refused(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={"snapshot_exists": True, "approved_current_snapshot": True},
    )
    transport.expect("GET", f"{BASE}/user-modeling/readiness", body=["not", "a", "document"])
    client = client_for(tmp_path, transport)

    assert twin_chat.approved(twin_chat.readiness(client, PROJECT_ID))
    with pytest.raises(ApiFailure) as caught:
        twin_chat.readiness(client, PROJECT_ID)
    assert caught.value.code == "API_FAILURE"
    transport.assert_done()


def test_the_current_snapshot_and_its_twins(tmp_path: Path) -> None:
    good = {"id": TWIN_ID, "twin_id": TWIN_ID, "profile": {"name": "Cameriere"}}
    transport = ScriptedTransport()
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/snapshots/current",
        body={"id": "snapshot-1", "snapshot": {"twin_versions": [good, "wrong", 3]}},
    )
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/snapshots/current",
        status=404,
        body={"detail": {"code": "USER_MODELING_SNAPSHOT_NOT_FOUND"}},
    )
    client = client_for(tmp_path, transport)

    found = twin_chat.current_snapshot(client, PROJECT_ID)

    assert twin_chat.twin_versions(found) == [good]
    assert twin_chat.current_snapshot(client, PROJECT_ID) is None
    assert twin_chat.twin_versions(None) == []
    assert twin_chat.twin_versions({"snapshot": {"twin_versions": "wrong"}}) == []
    transport.assert_done()


def test_the_conversation_and_the_turns_of_the_current_twin_version(tmp_path: Path) -> None:
    first = turn(1, "Come lavori?", "Di sera, al tavolo.")
    transport = ScriptedTransport()
    transport.expect("GET", CONVERSATION, body={"snapshot": conversation(VERSION_ID, first)})
    transport.expect(
        "GET",
        CONVERSATION,
        status=404,
        body={"detail": {"code": "TWIN_CONVERSATION_NOT_FOUND"}},
    )
    client = client_for(tmp_path, transport)

    found = twin_chat.conversation(client, PROJECT_ID, TWIN_ID)

    assert twin_chat.turns(found, VERSION_ID) == [first]
    assert twin_chat.turns(found, OLD_VERSION_ID) == []
    assert twin_chat.turns(found) == [first]
    assert twin_chat.turn_question(first) == "Come lavori?"
    assert twin_chat.turn_reply(first) == "Di sera, al tavolo."
    assert twin_chat.turn_reply({"reply": None}) == ""
    assert twin_chat.conversation(client, PROJECT_ID, TWIN_ID) is None
    assert twin_chat.turns(None) == []
    transport.assert_done()


def test_a_question_sends_the_text_and_the_turns_already_there(tmp_path: Path) -> None:
    recorded = conversation(VERSION_ID, turn(1, "Come lavori?", "Di sera."))
    transport = ScriptedTransport()
    transport.expect(
        "POST",
        f"{CONVERSATION}/turns",
        status=201,
        body={"status": twin_chat.TURN_STATUS, "snapshot": recorded},
    )
    client = client_for(tmp_path, transport)

    answer = twin_chat.ask(client, PROJECT_ID, TWIN_ID, "Come lavori?", expected_turn_count=0)

    assert answer == recorded
    sent = transport.requests("POST")[0]
    assert sent.json() == {"question": "Come lavori?", "expected_turn_count": 0}
    assert sent.header("prefer") is None
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (409, {"detail": {"code": "TWIN_CONVERSATION_CHANGED"}}, "TWIN_CONVERSATION_CHANGED"),
        (
            502,
            {"detail": {"code": "INVALID_TWIN_CHAT_OUTPUT", "stage": "MODEL_PROPOSAL"}},
            "INVALID_TWIN_CHAT_OUTPUT",
        ),
        (201, {"status": "TWIN_TURN_RECORDED"}, "API_FAILURE"),
    ],
)
def test_a_refused_question_raises_the_code_of_the_studio(
    tmp_path: Path, status: int, body: dict[str, object], code: str
) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{CONVERSATION}/turns", status=status, body=body
    )
    client = client_for(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        twin_chat.ask(client, PROJECT_ID, TWIN_ID, "Domanda?", expected_turn_count=2)

    assert caught.value.code == code
    assert caught.value.http_status == status
    transport.assert_done()


def imported_answer(name: str = "Calcolo mancia") -> dict[str, object]:
    return {
        "project": {"id": "new-project", "display_name": name, "mode": "GREENFIELD_GENERATION"},
        "origin": {"project_id": "old-project", "project_name": "Origine", "package_version": 2},
        "stages": {},
        "twins": [],
        "imported_at": "2026-09-29T09:00:00Z",
        "approval_required": ["brief", "team", "twins", "requirements", "design"],
    }


def test_the_import_sends_the_archive_and_the_name_in_a_form(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{API}/project-imports", status=201, body=imported_answer("Nuovo nome")
    )
    client = client_for(tmp_path, transport)

    document = imports.import_project(
        client, ARCHIVE, file_name="cartella.zip", display_name="Nuovo nome"
    )

    sent = transport.requests("POST")[0]
    assert sent.header("content-type").startswith("multipart/form-data; boundary=")
    assert sent.header("authorization") == "Bearer test-access-not-real"
    assert form_parts(sent) == {
        "display_name": (None, b"Nuovo nome"),
        "archive": ("cartella.zip", ARCHIVE),
    }
    assert imports.imported_project(document)["display_name"] == "Nuovo nome"
    assert imports.imported_origin(document)["package_version"] == 2
    assert imports.approval_required(document) == (
        "brief",
        "team",
        "twins",
        "requirements",
        "design",
    )
    transport.assert_done()


def test_the_import_without_a_name_sends_only_the_archive(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{API}/project-imports", status=201, body=imported_answer()
    )
    client = client_for(tmp_path, transport)

    imports.import_project(client, ARCHIVE, file_name="orchestwin.zip")

    assert form_parts(transport.requests("POST")[0]) == {"archive": ("orchestwin.zip", ARCHIVE)}
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (
            413,
            {"detail": {"code": "FOLDER_ARCHIVE_TOO_LARGE", "location": None}},
            "FOLDER_ARCHIVE_TOO_LARGE",
        ),
        (
            422,
            {"detail": {"code": "PROJECT_NAME_INVALID", "location": "display_name"}},
            "PROJECT_NAME_INVALID",
        ),
        (201, {"project": {"display_name": "Senza id"}}, "API_FAILURE"),
    ],
)
def test_a_refused_import_raises_the_code_of_the_studio(
    tmp_path: Path, status: int, body: dict[str, object], code: str
) -> None:
    transport = ScriptedTransport().expect(
        "POST", f"{API}/project-imports", status=status, body=body
    )
    client = client_for(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        imports.import_project(client, ARCHIVE, file_name="cartella.zip")

    assert caught.value.code == code
    transport.assert_done()


def test_the_parts_of_an_import_answer_survive_a_wrong_shape() -> None:
    assert imports.imported_project({"project": "wrong"}) == {}
    assert imports.imported_origin({}) == {}
    assert imports.approval_required({"approval_required": "brief"}) == ()
    assert imports.approval_required({"approval_required": ["brief", 3]}) == ("brief",)
