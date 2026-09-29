from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.commands.init import Journey
from orchestwin.cli.flows import init_brief
from orchestwin.cli.flows.answers import Answers

from .support.fake_studio import FakeStudio
from .support.terminal import (
    PROJECT_ID,
    command_context,
    link_folder,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport
from .test_init_command import (
    DIALOGUE,
    IDEA,
    NAME,
    fake_project,
    posted,
    saved_step,
    sign_in,
    start,
    ut,
)

UNTIL_BRIEF = ("--until", "brief")
QUIET_START = start()[:-1]
DIALOGUE_PATH = f"{API}/projects/{PROJECT_ID}/brief-dialogue"


def test_an_empty_answer_and_a_question_mark_mean_unknown(tmp_path: Path) -> None:
    answers = [*QUIET_START, "", "?", "Work out the tip fast", "", "Enter the bill", "", "1", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=answers)

        assert run.status == 0, run.errors
        assert posted(studio, "/brief-dialogue/answers") == [
            {"kind": "UNKNOWN", "expected_turn_count": 1},
            {"kind": "UNKNOWN", "expected_turn_count": 2},
            {"kind": "ITEM_LIST", "items": ["Work out the tip fast"], "expected_turn_count": 3},
            {"kind": "ITEM_LIST", "items": ["Enter the bill"], "expected_turn_count": 4},
        ]
    assert "Proposals of the model for the points you did not decide: 4." in run.output
    assert '- an empty answer or ? means "I do not know, propose it yourself";' in run.output


@pytest.mark.parametrize("word", ["/fine", "/done", "/DONE"])
def test_done_composes_the_brief_with_what_was_said(tmp_path: Path, word: str) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, DIALOGUE[0], word, "1", "1"])

        assert run.status == 0, run.errors
        assert len(posted(studio, "/brief-dialogue/answers")) == 1
        assert posted(studio, "/brief-dialogue/synthesis") == [{"expected_turn_count": 2}]
        brief = fake_project(studio, tmp_path).current("brief")["brief"]
        assert brief["problem"] == DIALOGUE[0]
        assert "target_users" in brief["unknown_fields"]
    assert 'Step "Brief" approved (version 3).' in run.output


@pytest.mark.parametrize(("word", "language"), [("/esci", "it"), ("/quit", "en"), ("/QUIT", "it")])
def test_quit_leaves_and_the_next_launch_resumes_from_the_same_question(
    tmp_path: Path, word: str, language: str
) -> None:
    with FakeStudio(language=language) as studio:
        sign_in(studio, tmp_path)

        first = ut(
            tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, DIALOGUE[0], word], language=language
        )
        second = ut(tmp_path, *UNTIL_BRIEF, answers=[*DIALOGUE[1:], "1", "1"], language=language)

        assert (first.status, second.status) == (0, 0), second.errors
        assert saved_step(tmp_path, "brief")["version"]["version_number"] == 3
    left = {
        "it": "Ti fermi qui: il dialogo resta aperto nello Studio.",
        "en": "You stop here: the dialogue stays open in the Studio.",
    }
    question = {"it": "Domanda 2:", "en": "Question 2:"}
    assert left[language] in first.output
    assert question[language] in second.output
    assert question[language].replace("2", "1") not in second.output


def test_the_dialogue_that_is_not_available_asks_the_essential_points(tmp_path: Path) -> None:
    answers = [
        *QUIET_START,
        "Nessuno sa quanto lasciare di mancia.",
        "Camerieri",
        "",
        "?",
        "Inserire il conto",
        "",
        "1",
    ]
    with FakeStudio(language="it", hosted=False) as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=answers, language="it")

        assert run.status == 0, run.errors
        [body] = posted(studio, "/brief-versions")
        assert body["name"] == NAME
        assert body["description"] == IDEA
        assert body["problem"] == "Nessuno sa quanto lasciare di mancia."
        assert body["target_users"] == ["Camerieri"]
        assert body["goals"] is None
        assert body["functional_requirements"] == ["Inserire il conto"]
        assert "goals" in body["unknown_fields"]
        assert "domain" in body["unknown_fields"]
        assert posted(studio, "/brief-dialogue/answers") == []
        assert fake_project(studio, tmp_path).approved("brief")
    assert "(BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED)" in run.output
    assert "Domanda 1: Quale problema risolve il progetto?" in run.output
    assert "Domanda 4: Che cosa deve permettere di fare il prodotto?" in run.output


def test_proposals_are_decided_one_by_one(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, *DIALOGUE, "2", "y", "n", "y", "1"])

        assert run.status == 0, run.errors
        assert posted(studio, "/reject") == [
            {"reason": "Not accepted by the owner of the project with ut init."}
        ]
        assert posted(studio, "/accept") == [{}, {}]
        brief = fake_project(studio, tmp_path).current("brief")["brief"]
        assert brief["non_functional_requirements"] is None
        assert brief["definition_of_done"] is not None
    assert "Do you accept proposal 2 (Expected qualities)? [Y/n]" in run.output
    assert "Proposals accepted: 2; discarded: 1. The brief is at version 4." in run.output
    assert "Open points, still to decide: Context" in run.output


def test_no_proposal_is_accepted(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, *DIALOGUE, "3", "1"])

        assert run.status == 0, run.errors
        assert len(posted(studio, "/reject")) == 3
        assert posted(studio, "/accept") == []
    assert "Proposals accepted: 0; discarded: 3. The brief is at version 2." in run.output
    assert "What it must do, Expected qualities" in run.output


def test_points_of_the_brief_are_corrected_before_the_approval(tmp_path: Path) -> None:
    answers = [
        *QUIET_START,
        *DIALOGUE,
        "1",
        "2",
        "3",
        "Splitting the bill takes too long.",
        "2",
        "4",
        "?",
        "2",
        "3",
        "",
        "1",
    ]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)

        run = ut(tmp_path, *UNTIL_BRIEF, answers=answers)

        assert run.status == 0, run.errors
        brief = fake_project(studio, tmp_path).current("brief")
        assert brief["version_number"] == 5
        assert brief["brief"]["problem"] == "Splitting the bill takes too long."
        assert brief["brief"]["goals"] is None
        assert "goals" in brief["brief"]["unknown_fields"]
        assert saved_step(tmp_path, "brief")["version"] == brief
    assert "Correction saved: the brief is at version 4." in run.output
    assert "Correction saved: the brief is at version 5." in run.output
    assert "No correction: the brief stays as it was." in run.output


def test_a_brief_with_missing_points_is_not_approved(tmp_path: Path) -> None:
    refusal = {
        "status": "BRIEF_INCOMPLETE",
        "gate": None,
        "events": [],
        "missing_fields": ["budget"],
        "issue": None,
    }
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next(
            "POST", "/projects/{project_id}/gates/project-brief/submit", status=409, body=refusal
        )

        run = ut(tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, *DIALOGUE, "1", "1", "1"])

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).approved("brief")
    assert "To approve the brief these points are still missing: Budget." in run.output


def test_a_dialogue_changed_elsewhere_is_read_again(tmp_path: Path) -> None:
    answers = [*QUIET_START, DIALOGUE[0], *DIALOGUE, "1", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next(
            "POST",
            "/projects/{project_id}/brief-dialogue/answers",
            status=409,
            body={"detail": {"code": "BRIEF_DIALOGUE_CHANGED"}},
        )

        run = ut(tmp_path, *UNTIL_BRIEF, answers=answers)

        assert run.status == 0, run.errors
        assert fake_project(studio, tmp_path).approved("brief")
    assert "The project changed in the meantime" in run.output
    assert "(BRIEF_DIALOGUE_CHANGED)" in run.output
    assert run.output.count("Question 1: Which problem does the project solve?") == 2


def test_a_failed_turn_of_the_dialogue_is_tried_again_after_asking(tmp_path: Path) -> None:
    answers = [*QUIET_START, DIALOGUE[0], "y", *DIALOGUE, "1", "1"]
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next(
            "POST",
            "/projects/{project_id}/brief-dialogue/answers",
            status=503,
            body={"detail": {"code": "PROVIDER_UNAVAILABLE", "stage": "MODEL_PROPOSAL"}},
        )

        run = ut(tmp_path, *UNTIL_BRIEF, answers=answers)

        assert run.status == 0, run.errors
    assert (
        "Dialogue of the brief: the model did not give a valid result (PROVIDER_UNAVAILABLE)."
        in run.output
    )
    assert "Try once more? It is a new generation, about 0.09 USD. [Y/n]" in run.output


def test_a_failed_turn_of_the_dialogue_without_a_second_try(tmp_path: Path) -> None:
    with FakeStudio(language="en") as studio:
        sign_in(studio, tmp_path)
        studio.fail_next(
            "POST",
            "/projects/{project_id}/brief-dialogue/answers",
            status=503,
            body={"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}},
        )

        run = ut(tmp_path, *UNTIL_BRIEF, answers=[*QUIET_START, DIALOGUE[0], "n"])

    assert run.status == 1
    assert (
        "Dialogue of the brief: the generation did not succeed (TIMEOUT). What you approved is "
        "saved" in run.errors
    )


def converse_journey(tmp_path: Path, transport: ScriptedTransport, answers: list[str]) -> Journey:
    store_session(tmp_path)
    folder = link_folder(tmp_path / "project")
    bundle = terminal(tmp_path, transport=transport, answers=answers)
    context = command_context(bundle.environment)
    return Journey(context, context.client(), folder, script=None, until=None, idea=None)


def dialogue_state(turns: list[dict[str, object]], status: str = "OPEN") -> dict[str, object]:
    return {
        "status": "BRIEF_QUESTION_ASKED",
        "snapshot": {
            "status": status,
            "essential_fields": [
                "description",
                "problem",
                "goals",
                "target_users",
                "functional_requirements",
            ],
            "turns": turns,
        },
        "progress": {
            "questions_asked": len(turns),
            "question_limit": 20,
            "open_essential_fields": [],
        },
        "brief_version": None,
        "assumptions": [],
    }


OPTIONAL_TURN = {
    "ordinal": 5,
    "field": "domain",
    "answer_type": "TEXT",
    "question": "In which setting is it used?",
    "answer": None,
}
COMPOSED = {"id": "brief-3", "version_number": 3, "content_hash": "h3", "brief": {}}


def test_with_no_essential_point_open_the_person_chooses_to_compose(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST",
        f"{DIALOGUE_PATH}/synthesis",
        status=201,
        body={**dialogue_state([], status="SYNTHESIZED"), "brief_version": COMPOSED},
    )
    journey = converse_journey(tmp_path, transport, ["2"])
    state = dialogue_state([{**OPTIONAL_TURN, "ordinal": 1}])

    found = init_brief.converse(journey, state)

    assert found == COMPOSED
    assert transport.requests("POST")[0].json() == {"expected_turn_count": 1}
    transport.assert_done()


def test_with_no_essential_point_open_the_person_answers_more(tmp_path: Path) -> None:
    answered = {**OPTIONAL_TURN, "ordinal": 1, "answer": {"kind": "TEXT", "text": "Pizzerias"}}
    transport = (
        ScriptedTransport()
        .expect(
            "POST", f"{DIALOGUE_PATH}/answers", status=201, body=dialogue_state([answered], "READY")
        )
        .expect(
            "POST",
            f"{DIALOGUE_PATH}/synthesis",
            status=201,
            body={**dialogue_state([answered], "SYNTHESIZED"), "brief_version": COMPOSED},
        )
    )
    journey = converse_journey(tmp_path, transport, ["1", "Pizzerias"])
    state = dialogue_state([{**OPTIONAL_TURN, "ordinal": 1}])

    found = init_brief.converse(journey, state)

    assert found == COMPOSED
    posts = [request.json() for request in transport.requests("POST")]
    assert posts == [
        {"kind": "TEXT", "text": "Pizzerias", "expected_turn_count": 1},
        {"expected_turn_count": 1},
    ]
    transport.assert_done()


def test_an_answers_file_composes_when_no_essential_point_is_open(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect(
        "POST",
        f"{DIALOGUE_PATH}/synthesis",
        status=201,
        body={**dialogue_state([], status="SYNTHESIZED"), "brief_version": COMPOSED},
    )
    journey = converse_journey(tmp_path, transport, [])
    journey.script = Answers(path="answers.json", answers={"domain": "Pizzerias"})
    state = dialogue_state([{**OPTIONAL_TURN, "ordinal": 3}])

    found = init_brief.converse(journey, state)

    assert found == COMPOSED
    assert [request.json() for request in transport.requests("POST")] == [
        {"expected_turn_count": 1}
    ]
    transport.assert_done()
