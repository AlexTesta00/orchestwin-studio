from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from orchestwin.cli.api import twin_chat
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.flows.twin_conversation import (
    HISTORY_TURNS,
    model_failure,
    normalized_question,
)
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio
from .support.terminal import (
    PROJECT_ID,
    TEST_PASSWORD,
    Run,
    command_context,
    link_folder,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport

EMAIL = "owner@example.com"
TURNS = "/projects/{project_id}/user-twins/{twin_id}/conversation/turns"
BASE = f"{API}/projects/{PROJECT_ID}"
TWIN_ID = "5d2c0a9e-0000-4000-8000-000000000007"
CONVERSATION = f"{BASE}/user-twins/{TWIN_ID}/conversation"


def sign_in(tmp_path: Path, studio: FakeStudio) -> None:
    studio.add_account(EMAIL, TEST_PASSWORD)
    run = run_ut(
        ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
        tmp_path,
        transport=UrlTransport(),
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.errors


def seeded(tmp_path: Path, studio: FakeStudio) -> FakeProject:
    sign_in(tmp_path, studio)
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="twins")
    link_folder(
        tmp_path / "project", project_id=project.id, name=project.name, studio=studio.address
    )
    return project


def ut(tmp_path: Path, *arguments: str, answers: Sequence[str] = ()) -> Run:
    return run_ut(list(arguments), tmp_path, transport=UrlTransport(), answers=answers)


def first_twin(project: FakeProject) -> Mapping[str, object]:
    snapshot = project.current("twins")
    assert snapshot is not None
    return snapshot["snapshot"]["twin_versions"][0]


def recorded_replies(
    tmp_path: Path, project: FakeProject, version: Mapping[str, object]
) -> list[str]:
    client = command_context(terminal(tmp_path, transport=UrlTransport()).environment).client()
    found = twin_chat.conversation(client, project.id, str(version["twin_id"]))
    return [twin_chat.turn_reply(turn) for turn in twin_chat.turns(found, str(version["id"]))]


def turn_bodies(studio: FakeStudio) -> list[dict[str, object]]:
    return [
        json.loads(request.body.decode("utf-8"))
        for request in studio.requests
        if request.method == "POST" and request.path.endswith("/conversation/turns")
    ]


def test_the_history_shows_at_most_the_last_three_turns(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        for question in ("One?", "Two?", "Three?", "Four?"):
            assert ut(tmp_path, "twins", "ask", "1", question).status == 0
        run = ut(tmp_path, "twins", "ask", "1", answers=["/esci"])
        bodies = turn_bodies(studio)
        version = first_twin(project)
        replies = recorded_replies(tmp_path, project, version)

    name = str(version["profile"]["name"])
    assert HISTORY_TURNS == 3
    assert len(replies) == 4
    assert run.status == 0
    assert run.output.splitlines()[:11] == [
        f"Earlier conversation with {name} (questions shown: 3):",
        "You: Two?",
        f"{name}:",
        replies[1],
        "You: Three?",
        f"{name}:",
        replies[2],
        "You: Four?",
        f"{name}:",
        replies[3],
        "",
    ]
    assert [body["expected_turn_count"] for body in bodies] == [0, 1, 2, 3]


def test_a_changed_conversation_is_read_again_and_the_talk_goes_on(tmp_path: Path) -> None:
    changed = {"detail": {"code": "TWIN_CONVERSATION_CHANGED"}}
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        assert ut(tmp_path, "twins", "ask", "1", "Before?").status == 0
        studio.fail_next("POST", TURNS, status=409, body=changed)
        talk = ut(tmp_path, "--lang", "it", "twins", "ask", "1", answers=["Ora?", "Ora?"])
        studio.fail_next("POST", TURNS, status=409, body=changed)
        single = ut(tmp_path, "twins", "ask", "1", "Again?")
        bodies = turn_bodies(studio)
        version = first_twin(project)
        replies = recorded_replies(tmp_path, project, version)

    name = str(version["profile"]["name"])
    lines = talk.output.splitlines()
    assert len(replies) == 2
    assert talk.status == 0
    assert talk.errors == (
        f"Nel frattempo la conversazione con {name} è cambiata, forse dalla pagina dello "
        "Studio: ho letto di nuovo le ultime domande. Fai di nuovo la tua domanda.\n"
    )
    assert lines[:5] == [
        f"Conversazione precedente con {name} (domande mostrate: 1):",
        "Tu: Before?",
        f"{name}:",
        replies[0],
        "",
    ]
    assert lines[-7:] == [
        "Tu: ",
        "Tu: ",
        f"{name}:",
        replies[1],
        "",
        "Tu: ",
        "Conversazione finita: domande e risposte restano salvate nello Studio.",
    ]
    assert talk.output.count("Stima:") == 1
    assert single.status == 1
    assert single.errors == (
        "The conversation changed in the meantime, perhaps from the page of the Studio. Launch "
        "the command again to ask the question.\n"
    )
    assert [body["expected_turn_count"] for body in bodies] == [0, 1, 1, 2]


def test_a_full_conversation_stops_with_its_reason(tmp_path: Path) -> None:
    full = {"detail": {"code": "TWIN_CONVERSATION_FULL"}}
    with FakeStudio(language="en", twins=1) as studio:
        seeded(tmp_path, studio)
        studio.fail_next("POST", TURNS, status=409, body=full)
        talk = ut(tmp_path, "twins", "ask", "1", answers=["More?", "Never sent"])
        studio.fail_next("POST", TURNS, status=409, body=full)
        italian = ut(tmp_path, "--lang", "it", "twins", "ask", "1", "Ancora?")

    assert talk.status == 1
    assert talk.errors == (
        "This conversation is full: the twin takes no more questions. You can go on with the "
        "other twins of the project.\n"
    )
    assert "Conversation ended" not in talk.output
    assert italian.status == 1
    assert italian.errors.startswith("Questa conversazione è piena: il twin non accetta")


def test_a_question_that_is_too_long_is_never_sent(tmp_path: Path) -> None:
    long_question = "parola " * 200
    with FakeStudio(language="en", twins=1) as studio:
        project = seeded(tmp_path, studio)
        single = ut(tmp_path, "twins", "ask", "1", long_question)
        talk = ut(tmp_path, "--lang", "it", "twins", "ask", "1", answers=[long_question, "Breve?"])
        bodies = turn_bodies(studio)
        spent = studio.project(project.id).spent_microusd

    assert single.status == 1
    assert single.errors == (
        "The question is too long: at most 1000 characters. Shorten it and launch the command "
        "again.\n"
    )
    assert talk.status == 0
    assert (
        "La domanda è troppo lunga: al massimo 1000 caratteri. Accorciala e riprova." in talk.output
    )
    assert [body["question"] for body in bodies] == ["Breve?"]
    assert spent == 30_000


def test_a_studio_without_the_chat_model_says_who_can_connect_it(tmp_path: Path) -> None:
    with FakeStudio(language="en", twins=1, hosted=False) as studio:
        seeded(tmp_path, studio)
        run = ut(tmp_path, "twins", "ask", "1", "Hello?")
        italian = ut(tmp_path, "--lang", "it", "twins", "ask", "1", answers=["Ciao?"])

    assert run.status == 1
    assert "Estimate" not in run.output
    assert run.errors == (
        "The model that plays the twins is not connected to the Studio. Ask whoever runs the "
        "Studio to connect it, then try again.\n"
    )
    assert italian.status == 1
    assert italian.errors.startswith("Il modello che dà voce ai twin non è collegato allo Studio.")


def scripted_twins(transport: ScriptedTransport, *, version_id: str) -> ScriptedTransport:
    twin = {
        "id": version_id,
        "twin_id": TWIN_ID,
        "version_number": 2,
        "profile": {"name": "Cameriere del turno serale", "observations": []},
    }
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/readiness",
        body={"snapshot_exists": True, "approved_current_snapshot": True},
    )
    transport.expect(
        "GET",
        f"{BASE}/user-modeling/snapshots/current",
        body={"id": "snapshot-2", "snapshot": {"twin_versions": [twin]}},
    )
    return transport


def test_a_twin_that_changed_starts_a_new_conversation(tmp_path: Path) -> None:
    old = {
        "twin_version_id": "old-version",
        "turns": [{"question": "Vecchia?", "reply": "Vecchia risposta."}],
    }
    recorded = {
        "twin_version_id": "new-version",
        "turns": [{"question": "Nuova?", "reply": "Nuova risposta."}],
    }
    transport = scripted_twins(ScriptedTransport(), version_id="new-version")
    transport.expect("GET", CONVERSATION, body={"snapshot": old})
    transport.expect("GET", f"{API}/model-runtime/budget", status=404, body={"detail": "x"})
    transport.expect(
        "POST",
        f"{CONVERSATION}/turns",
        status=201,
        body={"status": "TWIN_TURN_RECORDED", "snapshot": recorded},
    )
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    run = run_ut(
        ["--lang", "it", "twins", "ask", "1"],
        tmp_path,
        transport=transport,
        answers=["Nuova?", "/esci"],
    )

    assert run.status == 0
    assert run.output.splitlines()[:2] == [
        "Il twin Cameriere del turno serale è cambiato dall'ultima conversazione: ne comincia "
        "una nuova.",
        "Le risposte dei twin sono simulate dal modello: sono ipotesi da valutare, non opinioni "
        "di persone reali.",
    ]
    assert "Vecchia" not in run.output
    assert "Nuova risposta." in run.output
    assert transport.requests("POST")[0].json() == {"question": "Nuova?", "expected_turn_count": 0}
    transport.assert_done()


def test_one_earlier_turn_is_counted_after_a_label(tmp_path: Path) -> None:
    earlier = {
        "twin_version_id": "version-1",
        "turns": [{"question": "Come va?", "reply": "Bene, grazie."}],
    }
    transport = scripted_twins(ScriptedTransport(), version_id="version-1")
    transport.expect("GET", CONVERSATION, body={"snapshot": earlier})
    transport.expect("GET", f"{API}/model-runtime/budget", status=404, body={"detail": "x"})
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "ask", "1"], tmp_path, transport=transport, answers=["/quit"])

    assert run.status == 0
    assert run.output.splitlines()[:5] == [
        "Earlier conversation with Cameriere del turno serale (questions shown: 1):",
        "You: Come va?",
        "Cameriere del turno serale:",
        "Bene, grazie.",
        "",
    ]
    assert transport.requests("POST") == []
    transport.assert_done()


def test_a_studio_that_stops_answering_during_a_talk_stops_the_command(tmp_path: Path) -> None:
    transport = scripted_twins(ScriptedTransport(), version_id="version-1")
    transport.expect(
        "GET", CONVERSATION, status=404, body={"detail": {"code": "TWIN_CONVERSATION_NOT_FOUND"}}
    )
    transport.expect("GET", f"{API}/model-runtime/budget", status=404, body={"detail": "x"})
    transport.expect("POST", f"{CONVERSATION}/turns", unreachable=True, sent=True)
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "ask", "1"], tmp_path, transport=transport, answers=["Hello?"])

    assert run.status == 4
    assert run.errors == (
        "The Studio at http://127.0.0.1:8000 does not answer. Check that it is running, then "
        "try again.\n"
    )
    assert len(transport.requests("POST")) == 1
    transport.assert_done()


def test_a_twin_that_left_the_project_is_explained(tmp_path: Path) -> None:
    transport = scripted_twins(ScriptedTransport(), version_id="version-1")
    transport.expect(
        "GET", CONVERSATION, status=404, body={"detail": {"code": "TWIN_CONVERSATION_NOT_FOUND"}}
    )
    transport.expect("GET", f"{API}/model-runtime/budget", status=404, body={"detail": "x"})
    transport.expect(
        "POST",
        f"{CONVERSATION}/turns",
        status=404,
        body={"detail": {"code": "USER_TWIN_NOT_FOUND"}},
    )
    store_session(tmp_path)
    link_folder(tmp_path / "project")

    run = run_ut(["twins", "ask", "cam", "Hello?"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.errors == (
        "This twin is no longer among the twins of the project: see the updated list with "
        "`ut twins`.\n"
    )
    transport.assert_done()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            ApiFailure(
                "INVALID_TWIN_CHAT_OUTPUT",
                http_status=502,
                detail={"code": "INVALID_TWIN_CHAT_OUTPUT", "stage": "MODEL_PROPOSAL"},
            ),
            True,
        ),
        (
            ApiFailure(
                "PROVIDER_UNAVAILABLE",
                http_status=503,
                detail={"code": "PROVIDER_UNAVAILABLE", "stage": "MODEL_PROPOSAL"},
            ),
            True,
        ),
        (
            ApiFailure(
                "REAL_MODEL_RUNTIME_UNAVAILABLE",
                http_status=503,
                detail={"code": "REAL_MODEL_RUNTIME_UNAVAILABLE", "stage": "MODEL_RUNTIME"},
            ),
            True,
        ),
        (
            ApiFailure(
                "GENERATION_BUDGET_EXCEEDED",
                http_status=402,
                detail={"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"},
            ),
            False,
        ),
        (
            ApiFailure(
                "GENERATION_BUDGET_UNAVAILABLE",
                http_status=503,
                detail={"code": "GENERATION_BUDGET_UNAVAILABLE", "stage": "MODEL_PROPOSAL"},
            ),
            False,
        ),
        (
            ApiFailure(
                "TWIN_CONVERSATION_CHANGED",
                http_status=409,
                detail={"code": "TWIN_CONVERSATION_CHANGED"},
            ),
            False,
        ),
        (ApiFailure("invalid_request", http_status=422, detail="invalid_request"), False),
    ],
)
def test_only_a_failure_of_the_model_lets_the_question_be_asked_again(
    failure: ApiFailure, expected: bool
) -> None:
    assert model_failure(failure) is expected


def test_questions_are_sent_with_plain_spaces() -> None:
    assert normalized_question("  Come\n lavori\t di sera?  ") == "Come lavori di sera?"
    assert normalized_question("   ") == ""
