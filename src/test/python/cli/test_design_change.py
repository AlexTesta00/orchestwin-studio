from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import design_change

from .test_api_design import (
    Session,
    choose,
    design_session,
    draw,
    finish_job,
    propose,
    start_iteration,
    without_drawing,
)

ITERATIONS = "/design/iterations/jobs"
EVALUATIONS = "/design/evaluations"
NOT_REVIEWED = (
    "The change stays applied in version 3, but the twins did not review it, for the reason "
    "given. Once the reason is solved, launch `ut design review` to have the review done.\n"
)
NO_MODEL_CHANGE = {
    "en": (
        "On this Studio the design cannot be changed in words: it has no model connected, and "
        "a change needs one. Nothing changed; whoever runs the Studio can connect one.\n"
    ),
    "it": (
        "Su questo Studio il design non si può modificare a parole: non ha un modello "
        "collegato, e la modifica ne ha bisogno. Non è cambiato nulla; chi gestisce lo Studio "
        "può collegarne uno.\n"
    ),
}


def chosen(session: Session) -> None:
    propose(session)
    draw(session, "DES-001", "DES-002")
    choose(session, "DES-002")


def rules(session: Session) -> list[str]:
    design = session.project.current("design")
    assert design is not None
    return list(design["package"]["owner_assertions"])


def version_number(session: Session) -> int:
    design = session.project.current("design")
    assert design is not None
    return int(design["version_number"])


def reviews(session: Session) -> int:
    return session.count("POST", EVALUATIONS)


def applied_html(session: Session) -> str:
    document = design_api.mockup_document(
        session.client(),
        session.project.id,
        session.alternative("DES-002"),
        source=design_api.APPLIED,
    )
    assert document is not None
    return str(document["html"])


def test_two_changes_are_applied_and_reviewed_keeping_the_rule_in_force(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        first = session.ut(
            "design",
            "change",
            "Make the main button larger",
            "--rule",
            "The total stays visible",
            answers=["y"],
        )
        after_first = reviews(session)
        before = applied_html(session)
        second = session.ut(
            "design",
            "change",
            "Use a larger title",
            "--rule",
            "Keep the dark theme",
            answers=["y"],
        )
        bodies = [json.loads(item.body) for item in session.requests("POST", ITERATIONS)]
        reviewed = [json.loads(item.body) for item in session.requests("POST", EVALUATIONS)]
        in_force = rules(session)
        number = version_number(session)
        versions = {item["version_number"]: item["id"] for item in session.project.designs}
        index = (session.previews / "index.html").read_text(encoding="utf-8")
        saved = (session.previews / "DES-002-before.html").read_bytes()

    assert first.status == 0, first.errors
    assert second.status == 0, second.errors
    assert (
        "I am about to ask the model to change the chosen design: “Make the main button "
        "larger”. Right after, the twins review the new version.\nThese rules will stay in "
        "force afterwards too:\n- The total stays visible\n" in first.output
    )
    assert "Estimate: 1.12-1.73 USD, about 9 min." in first.output
    assert first.output.count("Go ahead with this spending? [Y/n]") == 1
    assert "Change applied: the design is now at version 3, to be approved." in first.output
    assert "You asked: “Make the main button larger”\nWhat changed:\n- " in first.output
    assert "Estimate: 0.27-0.40 USD, about 2 min." in first.output
    assert "Review of the twins, version 3" in first.output
    assert "Compared with the previous review" not in first.output
    assert "Change applied: the design is now at version 4, to be approved." in second.output
    assert (
        "Rules in force, which every change must respect:\n- The total stays visible\n"
        "- Keep the dark theme\n" in second.output
    )
    assert "Review of the twins, version 4" in second.output
    assert "Compared with the previous review of the twins:\nSolved (1):\n" in second.output
    assert "Still open (2):\n" in second.output and "New: none.\n" in second.output
    assert "Pizzeria owner · Major: The main button is at the bottom" in second.output
    assert after_first == 1
    assert [body["design_version_id"] for body in reviewed] == [versions[3], versions[4]]
    assert [body["assertions"] for body in bodies] == [
        ["The total stays visible"],
        ["Keep the dark theme"],
    ]
    assert in_force == ["The total stays visible", "Keep the dark theme"]
    assert number == 4
    assert saved == before.encode("utf-8")
    assert 'href="DES-002-before.html">Before the change (version 3)</a>' in index
    assert 'href="DES-002.html">After the change (version 4)</a>' in index
    assert "Change requested: “Use a larger title”" in index
    assert second.opened == (session.uri("index.html"),)


def test_a_change_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        chosen(session)
        run = session.ut("design", "change", "Titolo più grande", answers=["s"], language="it")
        started = reviews(session)

    assert run.status == 0, run.errors
    assert "Stima: 1,12-1,73 USD, circa 9 min." in run.output
    assert "Modifica applicata: il design è ora alla versione 3, da approvare." in run.output
    assert "Avevi chiesto: «Titolo più grande»" in run.output
    assert "Nessuna regola in vigore" in run.output
    assert "Revisione dei twin, versione 3" in run.output
    assert started == 1


def test_without_a_ceiling_a_change_is_reviewed_and_shows_no_figure(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=None) as session:
        chosen(session)
        run = session.ut("design", "change", "Bigger title")
        number = version_number(session)
        started = reviews(session)

    assert run.status == 0, run.errors
    assert re.search(r"USD|\d+ min\b", run.output) is None
    assert "Go ahead with this spending?" not in run.output
    assert "I am about to ask the twins to review the chosen design." in run.output
    assert "Review of the twins, version 3" in run.output
    assert (number, started) == (3, 1)


def test_a_change_equal_to_the_design_changes_nothing_and_is_not_reviewed(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.ut("design", "change", "Bigger button", answers=["y"])
        run = session.ut("design", "change", "Bigger button again", answers=["y"])
        number = version_number(session)
        started = reviews(session)

    assert run.status == 0, run.errors
    assert (
        "The result of the change is identical to the current design: nothing changed and "
        "the design stays at version 3." in run.output
    )
    assert "Review of the twins" not in run.output
    assert (number, started) == (3, 1)


def test_a_refused_change_spends_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", "change", "Bigger button", answers=["n"])
        started = (session.count("POST", ITERATIONS), reviews(session))

    assert run.status == 5
    assert "Estimate: 1.12-1.73 USD, about 9 min." in run.output
    assert run.output.count("Go ahead with this spending? [Y/n]") == 1
    assert started == (0, 0)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["x" * 1001], "The change is too long: 1001 characters, at most 1000."),
        (["Bigger\x07button"], "The change contains control characters"),
        (["Bigger", "--rule", "r" * 301], "is not valid: at most 300 characters"),
        (
            ["Bigger", *(item for number in range(6) for item in ("--rule", f"Rule {number}"))],
            "You can add at most 5 rules with each change; nothing was spent.",
        ),
    ],
)
def test_a_change_that_cannot_be_sent_is_refused_before_spending(
    tmp_path: Path, arguments: list[str], message: str
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", "change", *arguments)
        started = session.count("POST", ITERATIONS)

    assert run.status == 2
    assert message in run.errors
    assert "Go ahead with this spending?" not in run.output
    assert started == 0


def test_the_request_is_normalized_and_the_rules_are_counted() -> None:
    found = design_change.request_of(
        "  Bigger\n  button ", ["Keep it", " Keep  it ", "", "Other"], ["Old"]
    )

    assert found == design_change.ChangeRequest(text="Bigger button", rules=("Keep it", "Other"))
    assert design_change.request_of("x", ["Old"], ["Old"]).rules == ("Old",)
    with pytest.raises(CliError) as full:
        design_change.request_of("x", ["New"], [f"Rule {number}" for number in range(20)])
    assert full.value.code == "TOO_MANY_RULES"
    assert full.value.values == {"limit": 20, "count": 20}
    with pytest.raises(CliError) as empty:
        design_change.request_of("   ", [], [])
    assert empty.value.code == "CHANGE_EMPTY"


def test_a_change_needs_a_chosen_design(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        run = session.ut("design", "change", "Bigger button")

    assert run.status == 1
    assert run.output == (
        "To ask for a change, choose an alternative first, for example with "
        "`ut design choose DES-001`.\n"
    )


@pytest.mark.parametrize(("language", "through"), [("en", "design"), ("it", "requirements")])
def test_without_a_model_changes_in_words_are_not_available(
    tmp_path: Path, language: str, through: str
) -> None:
    with design_session(tmp_path, through=through, hosted=False, language=language) as session:
        if through == "requirements":
            propose(session)
        before = session.writes()
        run = session.ut("design", "change", "Bigger button", language=language)
        after = session.writes()

    assert run.status == 1
    assert run.output == NO_MODEL_CHANGE[language]
    assert after == before


def test_a_model_that_cannot_iterate_offers_no_change_in_words(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        without_drawing(session)
        run = session.ut("design", "change", "Bigger button")
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.output == (
        "With the model of this Studio changes in words are not available, or the chosen "
        "design has no mockup drawn by the model.\n"
    )
    assert started == 0


def test_a_rejected_change_leaves_the_design_as_it_was(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_job("ITERATION", code="MOCKUP_REJECTED", rejected=True)
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        number = version_number(session)
        started = reviews(session)

    assert run.status == 1
    assert run.errors == (
        "The result did not pass the checks of the Studio: the screen fails the check "
        "(MOCKUP_REJECTED). The design did not change; asking again is a new expense.\n"
    )
    assert (number, started) == (2, 0)


def test_a_change_cut_because_too_long(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_job("ITERATION", code="INCOMPLETE_OUTPUT")
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        started = reviews(session)

    assert run.status == 1
    assert run.errors.startswith(
        "The generation was stopped because it was too long (INCOMPLETE_OUTPUT)."
    )
    assert started == 0


def test_a_lost_change_starts_no_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.lose_job("ITERATION")
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        number = version_number(session)
        started = reviews(session)

    assert run.status == 1
    assert run.errors.startswith("The generation was lost, perhaps because the Studio restarted.")
    assert (number, started) == (2, 0)


def test_the_review_fails_after_the_change_was_applied(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=503,
            body={"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}},
        )
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        number = version_number(session)

    assert run.status == 1
    assert "Change applied: the design is now at version 3, to be approved." in run.output
    assert run.errors == (
        "On this Studio the twins cannot review the design: no model is connected for the "
        "review (DESIGN_REVIEWER_NOT_CONFIGURED). The design stays as it is; whoever runs the "
        "Studio can connect one.\n"
    )
    assert run.output.endswith(NOT_REVIEWED)
    assert number == 3


def test_a_review_that_breaks_after_the_change_keeps_the_change(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=500,
            body={"detail": {"code": "UNEXPECTED_FAILURE"}},
        )
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        number = version_number(session)

    assert run.status == 1
    assert run.output.endswith(NOT_REVIEWED)
    assert run.errors == ("The Studio answered with an error (status 500, UNEXPECTED_FAILURE).\n")
    assert number == 3


def test_while_a_change_runs_no_second_change_starts(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        start_iteration(session, "Bigger title")
        run = session.ut("design", "change", "Another change")
        started = session.count("POST", ITERATIONS)

    assert run.status == 1
    assert run.output == (
        "In the Studio this is running: change of the design. Wait for it to finish: "
        "`ut design` follows it, then you can go on.\n"
    )
    assert started == 1


def test_a_running_change_is_followed_applied_and_reviewed(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        start_iteration(session, "Bigger title", ["Keep the total visible"])
        run = session.ut("design", answers=["leave"])
        started = (session.count("POST", ITERATIONS), reviews(session))
        in_force = rules(session)

    assert run.status == 0, run.errors
    assert (
        "In the Studio this is already running: change of the design. I start nothing new: "
        "I follow it." in run.output
    )
    assert "Change applied: the design is now at version 3, to be approved." in run.output
    assert "You asked: “Bigger title”" in run.output
    assert "Review of the twins, version 3" in run.output
    assert started == (1, 1)
    assert in_force == ["Keep the total visible"]


def test_a_finished_change_applied_from_the_menu_is_then_reviewed(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        job = start_iteration(session, "Bigger title")
        finish_job(session.client(), design_api.iteration_job_path(session.project.id, job))
        run = session.ut("design", answers=["apply", "leave"])
        started = (session.count("POST", ITERATIONS), reviews(session))
        number = version_number(session)

    assert run.status == 0, run.errors
    assert "A change you asked for is ready but not applied yet: “Bigger title”." in run.output
    assert "Apply the change you asked for: “Bigger title” (no spending)" in run.output
    assert "Change applied: the design is now at version 3, to be approved." in run.output
    assert "Estimate: 0.27-0.40 USD, about 2 min." in run.output
    assert "Review of the twins, version 3" in run.output
    assert "Go ahead with this spending?" not in run.output
    assert (started, number) == ((1, 1), 3)


def test_the_guided_change_asks_the_text_and_the_rules_then_reviews(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut(
            "design",
            answers=[
                "change",
                "Bigger title",
                "",
                "Keep the total visible",
                "Keep it dark",
                "",
                "y",
                "leave",
            ],
        )
        in_force = rules(session)
        started = reviews(session)

    assert run.status == 0, run.errors
    assert "Write in words what you want to change in the chosen design." in run.output
    assert (
        "Ask for a change in words; right after, the twins review it (estimate 1.12-1.73 USD, "
        "about 9 min)" in run.output
    )
    assert "Review of the twins, version 3" in run.output
    assert "Have the twins review the design" not in run.output.split("Review of the twins")[-1]
    assert in_force == ["Keep the total visible", "Keep it dark"]
    assert started == 1


def test_an_empty_change_in_the_guided_command_spends_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", answers=["change", "", "leave"])
        started = session.count("POST", ITERATIONS)

    assert run.status == 0
    assert "No change requested: nothing was spent." in run.output
    assert started == 0


def test_a_refusal_in_the_guided_command_goes_back_to_the_menu(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut("design", answers=["change", "Bigger title", "", "", "n", "leave"])
        started = (session.count("POST", ITERATIONS), reviews(session))

    assert run.status == 0
    assert run.errors == "No generation started: the spending was not confirmed.\n"
    assert run.output.count("What do you want to do?") == 2
    assert started == (0, 0)


def test_the_design_changed_before_the_change_was_applied(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/design/revisions/{diff_id}/decision",
            status=409,
            body={"detail": {"code": "CONTEXT_CHANGED"}},
        )
        run = session.ut("design", "change", "Bigger button", answers=["y"])
        number = version_number(session)
        started = reviews(session)

    assert run.status == 1
    assert run.errors.startswith("In the meantime the design changed")
    assert run.output.endswith("Chosen: DES-002 “Single card”, version 2, not approved yet.\n")
    assert (number, started) == (2, 0)


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_design_behind_the_new_requirements_names_the_gesture(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, through="design", language=language) as session:
        session.project.seed_requirements_change()
        run = session.ut("--yes", "design", "change", "Bigger button", language=language)
        guided = session.ut(
            "--yes",
            "design",
            answers=["leave"],
            language=language,
        )
        number = version_number(session)
        started = reviews(session)

    assert run.status == 1
    assert run.errors == messages.text("design.behind", language) + "\n"
    assert "`ut sections update`" in run.errors
    assert guided.status == 0, guided.errors
    assert guided.errors == ""
    assert messages.text("design.behind", language) in guided.output
    assert messages.text("design.menu_update_sections", language) in guided.output
    assert messages.text("design.menu_change", language) not in guided.output
    assert (number, started) == (2, 0)


def test_a_design_that_cites_a_removed_requirement_says_why_it_cannot_follow(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, through="design") as session:
        session.project.seed_requirement_removed()
        run = session.ut("--yes", "design", "change", "Bigger button")
        sections = session.project.sections()

    design = next(item for item in sections["sections"] if item["key"] == "DESIGN")
    assert run.status == 1
    assert (
        run.errors
        == messages.text(
            "design.recovery_requirement_removed", "en", codes=", ".join(design["codes"])
        )
        + "\n"
    )
    assert "`ut design regenerate`" in run.errors
    assert "ut sections update" not in run.errors
    assert "ut design change" not in run.errors
    assert "ask for a change" not in run.errors
