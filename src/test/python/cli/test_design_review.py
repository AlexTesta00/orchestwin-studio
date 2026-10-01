from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli import folder as local_folder
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.flows import review
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.project import ProjectFolder
from orchestwin.knowledge.folder import folder_archive

from .support.folders import stage_folder
from .support.terminal import command_context, run_ut, terminal
from .test_api_design import Session, choose, choose_in_the_web, design_session, draw, propose
from .test_design_generate import Unreachable

EVALUATIONS = "/design/evaluations"
NOT_AVAILABLE = {
    "en": (
        "I am about to ask the twins to review the chosen design.\n"
        "The twins are reviewing the design...\n"
        "The twins are reviewing the design: not completed after 9 s.\n",
        "On this Studio the twins cannot review the design: neither a model nor an automatic "
        "check for the review is connected (DESIGN_EVALUATOR_NOT_CONFIGURED). The design stays "
        "as it is; whoever runs the Studio can connect one.\n",
    ),
    "it": (
        "Adesso chiedo ai twin di rivedere il design scelto.\n"
        "I twin rivedono il design...\n"
        "I twin rivedono il design: non completato dopo 9 s.\n",
        "Su questo Studio i twin non possono rivedere il design: non c'è né un modello né un "
        "controllo automatico per la revisione (DESIGN_EVALUATOR_NOT_CONFIGURED). Il design "
        "resta com'è; chi gestisce lo Studio può collegarne uno.\n",
    ),
}


def chosen(session: Session) -> None:
    propose(session)
    draw(session, "DES-001", "DES-002")
    choose(session, "DES-002")


def test_the_review_shows_each_twin_with_the_weight_and_the_screen(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", "review")

    assert run.status == 0, run.errors
    assert run.output == (
        "I am about to ask the twins to review the chosen design.\n"
        "Estimate: 0.27-0.40 USD, about 2 min. Credit left in the Studio: 56.65 USD.\n"
        "The twins are reviewing the design...\n"
        "The twins are reviewing the design: done in 9 s.\n"
        "\n"
        "Review of the twins, version 2\n"
        "==============================\n"
        "Pizzeria owner\n"
        "- Major: The main button is at the bottom: at the table I look for it every\n"
        "  time. (screen “Tip calculator”, element “Split the bill”)\n"
        "- Minor: The result is written small on the phone. (screen “Split bill”, element\n"
        "  “Example: 3 people, 12.65 euros each.”)\n"
        "Evening shift waiter\n"
        "- Moderate: I cannot see how to split the bill among several people. (screen\n"
        "  “Tip calculator”)\n"
        "\n"
    )


def test_the_review_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        chosen(session)
        run = session.ut("design", "review", language="it")

    assert run.status == 0, run.errors
    assert "Adesso chiedo ai twin di rivedere il design scelto." in run.output
    assert "Revisione dei twin, versione 2" in run.output
    assert "- Importante: Il pulsante principale è in fondo" in run.output
    assert "(schermata “Calcolo mancia”, elemento “Dividi il conto”)" in run.output


def test_an_italian_folder_asks_the_studio_for_italian_from_an_english_terminal(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        project = ProjectFolder(session.folder)
        project.update_link(language="en")
        local_folder.unpack(
            folder_archive(stage_folder(through="design", language="it")).content,
            project.knowledge,
        )
        before = session.count("POST", EVALUATIONS)
        run = session.ut("design", "review")
        evaluations = session.requests("POST", EVALUATIONS)[before:]

    assert run.status == 0, run.errors
    assert [json.loads(item.body)["locale"] for item in evaluations] == ["it-IT"]
    assert run.output.startswith("I am about to ask the twins to review the chosen design.")


def test_the_review_needs_a_chosen_design(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        run = session.ut("design", "review")
        started = session.count("POST", EVALUATIONS)

    assert run.status == 1
    assert run.output.startswith("The twins review the chosen design: choose an alternative")
    assert started == 0


def test_without_a_design_there_is_nothing_to_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        run = session.ut("design", "review")

    assert run.status == 1
    assert run.output.startswith("The design does not exist yet, so the twins have nothing")


def test_a_running_review_is_followed_instead_of_starting_another(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        client = session.client()
        version = design_api.current(client, session.project.id)
        assert version is not None
        reply = client.request(
            "POST",
            design_api.evaluations_path(session.project.id),
            body=design_api.evaluation_body(version, "en-US"),
            prefer_async=True,
        )
        run = session.ut("design", "review")
        started = session.count("POST", EVALUATIONS)

    assert reply.status == 202
    assert run.status == 0, run.errors
    assert (
        "A review of the twins is already running in the Studio: I start no other one, I "
        "follow it." in run.output
    )
    assert "Review of the twins, version 2" in run.output
    assert started == 1


def test_the_guided_command_follows_a_running_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        client = session.client()
        version = design_api.current(client, session.project.id)
        assert version is not None
        client.request(
            "POST",
            design_api.evaluations_path(session.project.id),
            body=design_api.evaluation_body(version, "en-US"),
            prefer_async=True,
        )
        run = session.ut("design", answers=["leave"])
        started = session.count("POST", EVALUATIONS)

    assert run.status == 0, run.errors
    assert (
        "In the Studio this is already running: review of the twins. I start nothing new: I "
        "follow it." in run.output
    )
    assert run.output.count("Review of the twins, version 2") == 1
    assert "Chosen: DES-002 “Single card”, version 2, not approved yet." in run.output
    assert started == 1


def test_the_review_after_a_change_is_compared_with_the_previous_one(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.ut("design", "review")
        change = session.ut(
            "design", "change", "Bigger button", "--rule", "Keep the total", answers=["y"]
        )
        again = session.ut("design", "review")
        started = session.count("POST", EVALUATIONS)

    assert change.status == 0, change.errors
    assert "Review of the twins, version 3" in change.output
    assert (
        "Compared with the previous review of the twins: "
        "Solved (1): "
        "- Pizzeria owner · Major: The main button is at the bottom: at the table I look for "
        "it every time. (screen “Tip calculator”, element “Split the bill”) "
        "Still open (2): "
        "- Pizzeria owner · Minor: The result is still a little small on the phone. (screen "
        "“Split bill”, element “Example: 3 people, 12.65 euros each.”) "
        "- Evening shift waiter · Moderate: I cannot see how to split the bill among several "
        "people. (screen “Tip calculator”) "
        "New: none." in " ".join(change.output.split())
    )
    assert again.status == 0, again.errors
    assert (
        "The twins have already reviewed this version of the design: I do not start another "
        "review, here is theirs." in again.output
    )
    assert "Review of the twins, version 3" in again.output
    assert started == 2


def test_a_version_already_reviewed_is_not_reviewed_again(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        choice = session.ut("design", "choose", "DES-002")
        run = session.ut("design", "review", language="it")
        guided = session.ut("design", answers=["leave"])
        started = session.count("POST", EVALUATIONS)

    assert choice.status == 0 and run.status == 0 and guided.status == 0
    assert "I twin hanno già rivisto questa versione del design" in run.output
    assert "Revisione dei twin, versione 2" in run.output
    assert "Estimate" not in run.output and "Stima" not in run.output
    assert "Have the twins review the design" not in guided.output
    assert started == 1


def test_review_errors_use_the_sentences_of_the_design_for_every_command(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=409,
            body={"detail": {"code": "DESIGN_CONTEXT_CHANGED"}},
        )
        bundle = terminal(tmp_path, transport=UrlTransport())
        context = command_context(bundle.environment)
        status = review.run_review(context, context.client(), ProjectFolder(session.folder))

    assert status == 1
    assert bundle.errors == (
        "In the meantime the design changed, perhaps in the web interface, so the twins did "
        "not review it. Launch the review again for the new version.\n"
    )


def test_generic_failures_of_the_review_are_left_to_the_calling_command(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=503,
            body={"detail": {"code": "SOMETHING_ELSE"}},
        )
        bundle = terminal(tmp_path, transport=UrlTransport())
        context = command_context(bundle.environment)
        with pytest.raises(ApiFailure) as failure:
            review.run_review(context, context.client(), ProjectFolder(session.folder))

    assert failure.value.code == "SOMETHING_ELSE"
    assert bundle.errors == ""


def test_a_reviewer_that_is_not_configured(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=503,
            body={"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}},
        )
        run = session.ut("design", "review")

    assert run.status == 1
    assert run.errors == (
        "On this Studio the twins cannot review the design: no model is connected for the "
        "review (DESIGN_REVIEWER_NOT_CONFIGURED). The design stays as it is; whoever runs the "
        "Studio can connect one.\n"
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_studio_without_a_review_says_so_and_ends_with_one(tmp_path: Path, language: str) -> None:
    with design_session(tmp_path, hosted=False, language=language) as session:
        propose(session)
        choose_in_the_web(session, "DES-001")
        run = session.ut("design", "review", language=language)
        again = session.ut("design", "review", language=language)
        started = session.requests("POST", EVALUATIONS)
        runs = session.project.runs

    output, errors = NOT_AVAILABLE[language]
    assert run.status == 1 and again.status == 1
    assert run.output == output
    assert run.errors == errors
    assert again.errors == errors
    assert [item.headers.get("prefer") for item in started] == ["respond-async"] * 2
    assert runs == []


def test_a_lost_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.lose_job("DESIGN_EVALUATION")
        run = session.ut("design", "review")

    assert run.status == 1
    assert run.errors.startswith("The generation was lost, perhaps because the Studio restarted.")


def test_the_studio_stops_answering_during_the_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = run_ut(
            ["--lang", "en", "design", "review"],
            tmp_path,
            transport=Unreachable("/generation-jobs/"),
        )
        address = session.studio.address

    assert run.status == 4
    assert run.errors == (
        f"The Studio at {address} stopped answering during: The twins are reviewing the "
        "design. If the generation had started it goes on in the Studio: when the Studio "
        "answers again, launch the same command and it finds it.\n"
    )


def test_no_review_starts_without_a_gesture(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        guided = session.ut("design", answers=["y", "leave"])
        before_choice = session.count("POST", EVALUATIONS)
        choice = session.ut("design", "choose", "DES-002")
        after_choice = session.count("POST", EVALUATIONS)
        others = [
            session.ut("design", "show"),
            session.ut("design", "open"),
            session.ut("design", "open", "DES-001"),
            session.ut("design", answers=["leave"]),
            session.ut("design", answers=["open", "leave"]),
        ]
        at_the_end = session.count("POST", EVALUATIONS)

    assert guided.status == 0 and choice.status == 0
    assert [run.status for run in others] == [0, 0, 0, 0, 0]
    assert (before_choice, after_choice, at_the_end) == (0, 1, 1)


def test_findings_without_a_known_screen_keep_their_place_as_written(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)
    version = {
        "package": {
            "grounding": {"user_twin_references": [{"twin_id": "t1", "name": "Anna"}]},
            "prototype": {
                "screens": [
                    {
                        "code": "SCR-001",
                        "title": "Start",
                        "elements": [{"code": "ELM-001", "content": "Go"}],
                    }
                ]
            },
        }
    }
    run = {
        "design_version_number": 4,
        "responses": [
            {
                "twin_id": "t1",
                "findings": [
                    {"severity": "critical", "summary": "Hard", "anchor_key": "SCR-001/ELM-001"},
                    {"severity": "minor", "summary": "Small", "location": "SCR-001 top"},
                    {"severity": "odd", "summary": "Where", "location": "Footer area"},
                ],
            },
            {"twin_id": "t2", "findings": []},
        ],
    }

    review.show_review(context, run, version)

    assert bundle.output == (
        "\n"
        "Review of the twins, version 4\n"
        "==============================\n"
        "Anna\n"
        "- Critical: Hard (screen “Start”, element “Go”)\n"
        "- Minor: Small (screen “Start”)\n"
        "- odd: Where (Footer area)\n"
        "Twin\n"
        "- No observation.\n"
        "\n"
    )
