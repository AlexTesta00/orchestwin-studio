from __future__ import annotations

import re
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.messages import text

from .support.terminal import link_folder, run_ut
from .support.transports import NoNetwork
from .test_api_design import Session, choose, choose_in_the_web, design_session, draw, propose

FIGURES = re.compile(r"USD|\d+ min\b")
NO_MODEL_END = (
    "The alternatives and what the twins think are shown above; whoever runs the Studio can "
    "connect a model.\n"
)
NO_MODEL_CHOSEN = {
    "en": (
        "This Studio has no model connected, so here the design cannot be changed and no other "
        "alternative can be chosen. Whoever runs the Studio can connect one.\n"
    ),
    "it": (
        "Questo Studio non ha un modello collegato, quindi qui il design non si può modificare "
        "e non si può scegliere un'altra alternativa. Chi gestisce lo Studio può collegarne "
        "uno.\n"
    ),
}


def ready(session: Session) -> None:
    propose(session)
    draw(session, "DES-001", "DES-002")


def posts(session: Session) -> list[str]:
    return [
        item.path
        for item in session.studio.requests
        if item.method == "POST" and not item.path.endswith("/auth/login")
    ]


def menu(output: str) -> list[str]:
    lines = output.splitlines()
    start = max(index for index, line in enumerate(lines) if line.startswith("What do you want"))
    return [line.strip()[3:] for line in lines[start + 1 :] if line.startswith("  ")]


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "The design comes after the requirements, which are not approved yet."),
        ("it", "Il design viene dopo i requisiti, che non sono ancora approvati."),
    ],
)
def test_before_the_requirements_the_design_waits(
    tmp_path: Path, language: str, sentence: str
) -> None:
    with design_session(tmp_path, through="twins", language=language) as session:
        run = session.ut("design", language=language)
        sent = posts(session)

    assert run.status == 1
    assert sentence in run.output
    assert "`ut init`" in run.output
    assert sent == []


def test_alternatives_without_mockups_are_offered_but_not_drawn(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        before = posts(session)
        run = session.ut("design", answers=["leave"])
        after = posts(session)

    assert run.status == 0, run.errors
    assert run.output.count("Mockup: not drawn yet.") == 2
    assert "What the twins think" in run.output
    assert menu(run.output) == [
        "Draw the missing mockups: DES-001, DES-002 (estimate 2.60-3.20 USD, about 10 min)",
        "Leave",
    ]
    assert "Go ahead with this spending?" not in run.output
    assert after == before


def test_ready_mockups_show_the_alternatives_and_the_menu(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        before = posts(session)
        run = session.ut("design", answers=["leave"])
        after = posts(session)

    assert run.status == 0, run.errors
    assert run.output.count("Mockup: ready.") == 2
    assert menu(run.output) == [
        "Open the previews in the browser",
        "Choose an alternative; right after, the twins review it (estimate 0.27-0.40 USD, "
        "about 2 min)",
        "Leave",
    ]
    assert run.opened == ()
    assert after == before


def test_the_budget_is_read_once_for_each_menu(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        once = session.ut("design", answers=["leave"])
        first = session.count("GET", "/model-runtime/budget")
        twice = session.ut("design", answers=["open", "leave"])
        second = session.count("GET", "/model-runtime/budget") - first

    assert once.status == 0 and twice.status == 0
    assert (first, second) == (1, 2)
    assert twice.output.count("(estimate 0.27-0.40 USD, about 2 min)") == 2


def test_without_a_model_the_guided_command_only_shows(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        before = session.writes()
        run = session.ut("design", answers=["choose", "1", "approve", "leave"])
        after = session.writes()
        budgets = session.count("GET", "/model-runtime/budget")

    assert run.status == 0, run.errors
    assert run.output.count("Design alternatives\n===================\n") == 1
    assert "What the twins think\n====================\n" in run.output
    assert run.output.endswith(NO_MODEL_END)
    assert "What do you want to do?" not in run.output
    assert FIGURES.search(run.output) is None
    assert after == before
    assert budgets == 1
    assert run.opened == ()


def test_without_a_model_show_says_what_cannot_be_done(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        alternatives = session.ut("design", "show")
        choose_in_the_web(session, "DES-003")
        chosen = session.ut("design", "show", language="it")
        before = session.writes()
        again = session.ut("design", "show")
        after = session.writes()

    assert alternatives.status == 0 and chosen.status == 0 and again.status == 0
    assert alternatives.output.endswith(NO_MODEL_END)
    assert "Design scelto\n=============\nVersione 2, non ancora approvata.\n" in chosen.output
    assert "Nessuna regola in vigore.\n" in chosen.output
    assert chosen.output.endswith(
        f"{NO_MODEL_CHOSEN['it']}Puoi approvare il design con `ut design approve`.\n"
    )
    assert "puoi aggiungerne" not in chosen.output
    assert after == before


def test_without_a_model_a_design_chosen_in_the_web_is_approved(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        choose_in_the_web(session, "DES-002")
        before = session.writes()
        run = session.ut("--yes", "design", answers=["approve", "leave"])
        after = session.writes()
        approved = session.project.approved("design")

    assert run.status == 0, run.errors
    assert "Chosen design\n=============\nVersion 2, not approved yet.\n" in run.output
    assert f"No rule in force.\n{NO_MODEL_CHOSEN['en']}\nWhat do you want to do?" in run.output
    assert menu(run.output.split("Design approved:")[0]) == [
        "Approve the design; then the knowledge folder appears in orchestwin/",
        "Leave",
    ]
    assert "Design approved: DES-002 “Operations dashboard: " in run.output
    assert run.output.endswith("version 2.\n")
    assert [path for path in after if path not in before] == [
        "/design/gate/submit",
        "/design/gate/decision",
        "/knowledge-packages",
    ]
    assert approved


def test_without_a_model_an_approved_design_offers_nothing_more(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design", hosted=False) as session:
        run = session.ut("design", answers=["leave"])
        writes = session.writes()

    assert run.status == 0, run.errors
    assert "Version 2, approved.\n" in run.output
    assert (
        f"{NO_MODEL_CHOSEN['en']}The knowledge folder has not been prepared yet: "
        "`ut package publish` creates it.\n"
    ) in run.output
    assert "What do you want to do?" not in run.output
    assert writes == []


def test_without_a_ceiling_no_menu_shows_a_figure(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=None) as session:
        propose(session)
        missing = session.ut("design", answers=["leave"])
        draw(session, "DES-001", "DES-002")
        choose(session, "DES-002")
        chosen = session.ut("design", answers=["leave"], language="it")
        shown = session.ut("design", "show")

    assert missing.status == 0 and chosen.status == 0 and shown.status == 0
    assert menu(missing.output) == ["Draw the missing mockups: DES-001, DES-002", "Leave"]
    assert menu(chosen.output.replace("Che cosa vuoi fare?", "What do you want to do?")) == [
        "Apri le anteprime nel browser",
        "Chiedi una modifica a parole; subito dopo i twin la rivedono",
        "Fai rivedere il design ai twin",
        "Approva il design; poi la cartella di conoscenza appare in orchestwin/",
        "Scegli un'altra alternativa; subito dopo i twin la rivedono",
        "Esci",
    ]
    for run in (missing, chosen, shown):
        assert FIGURES.search(run.output) is None


def test_show_without_a_ceiling_promises_no_estimate(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=None) as session:
        empty = session.ut("design", "show")
        propose(session)
        alternatives = session.ut("design", "show")

    assert empty.output.endswith(
        "The design does not exist yet. Launch `ut design` to prepare it.\n"
    )
    assert alternatives.output.endswith("Launch `ut design` to have the mockups drawn.\n")


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (
            "en",
            [
                "Draw the missing mockups: DES-001, DES-002 (Claude subscription, no credit "
                "spent, about 10 min)",
                "Leave",
            ],
        ),
        (
            "it",
            [
                "Disegna i mockup che mancano: DES-001, DES-002 (abbonamento di Claude, nessun "
                "credito speso, circa 10 min)",
                "Esci",
            ],
        ),
    ],
)
def test_on_the_subscription_the_menu_shows_the_time_without_an_amount(
    tmp_path: Path, language: str, expected: list[str]
) -> None:
    with design_session(tmp_path, language=language, billing="SUBSCRIPTION") as session:
        propose(session)
        run = session.ut("design", answers=["leave"], language=language)
        budgets = session.count("GET", "/model-runtime/budget")

    assert run.status == 0, run.errors
    assert menu(run.output.replace("Che cosa vuoi fare?", "What do you want to do?")) == expected
    assert "USD" not in run.output
    assert budgets == 1


def test_on_the_subscription_a_chosen_design_offers_its_steps_without_an_amount(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, billing="SUBSCRIPTION") as session:
        ready(session)
        choose(session, "DES-002")
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert menu(run.output) == [
        "Open the previews in the browser",
        "Ask for a change in words; right after, the twins review it (Claude subscription, no "
        "credit spent, about 9 min)",
        "Have the twins review the design (Claude subscription, no credit spent, about 2 min)",
        "Approve the design; then the knowledge folder appears in orchestwin/",
        "Choose another alternative; right after, the twins review it (Claude subscription, no "
        "credit spent, about 2 min)",
        "Leave",
    ]


@pytest.mark.parametrize("billing", ["MIXED", "API"])
def test_with_paid_routes_the_menu_shows_the_amount(tmp_path: Path, billing: str) -> None:
    with design_session(tmp_path, billing=billing) as session:
        propose(session)
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert menu(run.output) == [
        "Draw the missing mockups: DES-001, DES-002 (estimate 2.60-3.20 USD, about 10 min)",
        "Leave",
    ]


def test_a_budget_that_cannot_be_read_ends_the_guided_command(tmp_path: Path) -> None:
    with design_session(tmp_path, billing="SUBSCRIPTION") as session:
        ready(session)
        session.studio.fail_next(
            "GET",
            "/model-runtime/budget",
            status=500,
            body={"detail": {"code": "BUDGET_STORE_FAILED"}},
        )
        run = session.ut("design", answers=["leave"])

    assert run.status != 0
    assert "What do you want to do?" not in run.output


def test_on_the_subscription_show_promises_no_estimate_of_a_spending(tmp_path: Path) -> None:
    with design_session(tmp_path, billing="SUBSCRIPTION") as session:
        empty = session.ut("design", "show")
        propose(session)
        alternatives = session.ut("design", "show")

    assert empty.output.endswith(
        "The design does not exist yet. Launch `ut design` to prepare it.\n"
    )
    assert alternatives.output.endswith("Launch `ut design` to have the mockups drawn.\n")


def test_ready_mockups_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        ready(session)
        run = session.ut("design", answers=["3"], language="it")

    assert run.status == 0, run.errors
    assert "Alternative di design" in run.output
    assert menu(run.output.replace("Che cosa vuoi fare?", "What do you want to do?")) == [
        "Apri le anteprime nel browser",
        "Scegli un'alternativa; subito dopo i twin la rivedono (stima 0,27-0,40 USD, circa 2 min)",
        "Esci",
    ]


def test_a_chosen_design_shows_the_rules_and_the_last_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        version = choose(session, "DES-002")
        session.client().request(
            "POST",
            design_api.evaluations_path(session.project.id),
            body=design_api.evaluation_body(version, "en-US"),
        )
        before = posts(session)
        run = session.ut("design", answers=["leave"])
        after = posts(session)

    assert run.status == 0, run.errors
    assert "Chosen design\n=============\nVersion 2, not approved yet.\n" in run.output
    assert "No rule in force: you can add some when you ask for a change." in run.output
    assert "Review of the twins, version 2" in run.output
    assert "Design alternatives" not in run.output
    assert menu(run.output) == [
        "Open the previews in the browser",
        "Ask for a change in words; right after, the twins review it (estimate 1.12-1.73 USD, "
        "about 9 min)",
        "Approve the design; then the knowledge folder appears in orchestwin/",
        "Choose another alternative; right after, the twins review it (estimate 0.27-0.40 "
        "USD, about 2 min)",
        "Leave",
    ]
    assert after == before


def test_a_chosen_design_without_review_offers_one(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        choose(session, "DES-002")
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert "Have the twins review the design (estimate 0.27-0.40 USD, about 2 min)" in menu(
        run.output
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_an_approved_design_says_where_the_folder_is(tmp_path: Path, language: str) -> None:
    with design_session(tmp_path, language=language) as session:
        ready(session)
        choose(session, "DES-002")
        approval = session.ut("design", "approve", language=language)
        before = posts(session)
        run = session.ut("design", answers=["leave"], language=language)
        after = posts(session)
        folder = session.folder / "orchestwin"

    assert approval.status == 0, approval.errors
    assert run.status == 0, run.errors
    if language == "en":
        assert "Version 2, approved." in run.output
        assert f"The knowledge folder is in {folder}: version 1, " in run.output
        assert menu(run.output) == [
            "Open the previews in the browser",
            "Ask for a change in words; right after, the twins review it (estimate 1.12-1.73 "
            "USD, about 9 min)",
            "Leave",
        ]
    else:
        assert "Versione 2, approvata." in run.output
        assert f"La cartella di conoscenza è in {folder}: versione 1, " in run.output
    assert after == before


def test_a_design_approved_elsewhere_names_the_command_for_the_folder(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        run = session.ut("design", answers=["leave"])

    assert run.status == 0, run.errors
    assert (
        "The knowledge folder has not been prepared yet: `ut package publish` creates it."
        in run.output
    )


def test_the_guided_command_chooses_by_number_and_the_twins_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", answers=["2", "1", "leave"])
        design = session.project.current("design")
        first = session.alternative("DES-001")
        reviews = session.count("POST", "/design/evaluations")

    assert run.status == 0, run.errors
    assert "Which alternative do you choose?\n  1. DES-001 · Guided calculation\n" in run.output
    assert "You chose DES-001 “Guided calculation”" in run.output
    assert "Chosen: DES-001 “Guided calculation”, version 2, not approved yet." in run.output
    assert design is not None
    assert design["package"]["owner_selected_alternative_id"] == first
    assert reviews == 1


def test_the_guided_command_approves(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        choose(session, "DES-001")
        run = session.ut("design", answers=["approve", "leave"])
        approved = session.project.approved("design")

    assert run.status == 0, run.errors
    assert "Design approved: DES-001 “Guided calculation”, version 2." in run.output
    assert "Approved: DES-001 “Guided calculation”, version 2." in run.output
    assert approved


def test_a_closed_input_ends_the_guided_command(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design")

    assert run.status == 1
    assert run.errors == "The input closed while an answer was awaited: nothing else was done.\n"


def test_change_without_text_asks_for_it(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        choose(session, "DES-002")
        run = session.ut("design", "change", answers=["Bigger title", "", "y"])

    assert run.status == 0, run.errors
    assert "Write in words what you want to change in the chosen design." in run.output
    assert "You asked: “Bigger title”" in run.output


def test_show_tells_what_exists_without_generating(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        empty = session.ut("design", "show")
        ready(session)
        alternatives = session.ut("design", "show")
        version = choose(session, "DES-002")
        session.client().request(
            "POST",
            design_api.evaluations_path(session.project.id),
            body=design_api.evaluation_body(version, "en-US"),
        )
        before = posts(session)
        chosen = session.ut("design", "show", language="it")
        after = posts(session)

    assert empty.status == 0
    assert "The design does not exist yet." in empty.output
    assert alternatives.status == 0
    assert "Design alternatives" in alternatives.output
    assert "What the twins think" in alternatives.output
    assert alternatives.output.endswith(
        "Look at the previews with `ut design open`, then choose with `ut design choose CODE`.\n"
    )
    assert chosen.status == 0
    assert "Alternative di design" in chosen.output
    assert "Design scelto" in chosen.output
    assert "Revisione dei twin, versione 2" in chosen.output
    assert chosen.output.endswith(
        'Puoi chiedere una modifica con `ut design change "..."` oppure approvare con '
        "`ut design approve`.\n"
    )
    assert after == before


def test_the_choice_names_the_code_with_the_same_word_in_both_languages(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "show", language="it")

    assert run.status == 0, run.errors
    assert run.output.endswith(
        "Guarda le anteprime con `ut design open`, poi scegli con `ut design choose CODE`.\n"
    )
    assert [text("design.next_choose", language) for language in ("it", "en")] == [
        "Scegli un'alternativa con `ut design choose CODE`.",
        "Choose an alternative with `ut design choose CODE`.",
    ]


def test_show_while_a_mockup_is_drawn(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        version = propose(session)
        design_api.start_mockup(
            session.client(), session.project.id, version, session.alternative("DES-001")
        )
        before = posts(session)
        run = session.ut("design", "show")
        after = posts(session)

    assert run.status == 0, run.errors
    assert "In the Studio this is running: mockup of DES-001." in run.output
    assert run.output.endswith("Launch `ut design` to follow the running generation and go on.\n")
    assert after == before


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["show", "--rule", "x"], "--rule can be used only with `ut design change`.\n"),
        (
            ["show", "DES-001"],
            "`ut design show` takes no other text after the action: remove it and try again.\n",
        ),
        (
            ["DES-001"],
            None,
        ),
        (
            ["choose"],
            "Write which alternative you choose, for example `ut design choose DES-001`.\n",
        ),
    ],
)
def test_wrong_usage(tmp_path: Path, arguments: list[str], message: str | None) -> None:
    run = run_ut(["--lang", "en", "design", *arguments], tmp_path, transport=NoNetwork())

    assert run.status == 2
    if message is not None:
        assert run.errors == message
    else:
        assert "invalid choice" in run.errors


@pytest.mark.parametrize(
    ("language", "phrase"),
    [
        ("en", "what to do: show, open (the previews), choose (an alternative)"),
        ("it", "che cosa fare: show (mostra), open (apre le anteprime)"),
    ],
)
def test_the_help_is_translated(tmp_path: Path, language: str, phrase: str) -> None:
    run = run_ut(["--lang", language, "design", "--help"], tmp_path, transport=NoNetwork())

    assert run.status == 0
    assert " ".join(phrase.split()) in " ".join(run.output.split())
    assert "--rule TEXT" in run.output


def test_a_folder_that_is_not_linked(tmp_path: Path) -> None:
    run = run_ut(["--lang", "en", "design"], tmp_path, transport=NoNetwork())

    assert run.status == 6
    assert run.errors.startswith("This folder is not linked to a project of the Studio.")


def test_without_sign_in(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    run = run_ut(["--lang", "en", "design", "show"], tmp_path, transport=NoNetwork())

    assert run.status == 3
    assert run.errors.startswith("You are not signed in to the Studio")
