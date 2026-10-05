from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from pathlib import Path

import pytest

from orchestwin.cli import jobs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import design_generate
from orchestwin.cli.flows.design_state import Alternative
from orchestwin.cli.http import Reply, UrlTransport, unreachable
from orchestwin.cli.main import main

from .support.fake_studio import RecordedRequest
from .support.terminal import command_context, run_ut, terminal
from .test_api_design import DESIGNER, Session, design_session, propose, without_drawing

PROPOSALS = "/design/proposals"
MOCKUP_JOBS = "/design/mockups/jobs"
FIGURES = re.compile(r"USD|\d+ min\b")
NO_MODEL = (
    "This Studio has no model connected, so it cannot draw the mockups or prepare the "
    "prototype of an alternative: choosing an alternative and approving the design need one. "
    "The alternatives and what the twins think are shown above; whoever runs the Studio can "
    "connect a model.\n"
)
REFUSALS = {
    ("UX_DESIGNER_REQUIRED", "en"): (
        "The design alternatives were not prepared: in the approved perspectives of this "
        "project User experience (UX) is not fully applied (UX_DESIGNER_REQUIRED). It can "
        "happen with perspectives approved before 29 September 2026. Prepare the perspectives "
        "again and approve them in the web Studio, then launch `ut design` again.\n"
    ),
    ("UX_DESIGNER_REQUIRED", "it"): (
        "Le alternative di design non sono state preparate: nelle prospettive approvate di "
        "questo progetto l'Esperienza d'uso (UX) non è applicata per intero "
        "(UX_DESIGNER_REQUIRED). Può succedere con le prospettive approvate prima del 29 "
        "settembre 2026. Prepara di nuovo le prospettive e approvale nello Studio web, poi "
        "rilancia `ut design`.\n"
    ),
    ("GROUNDED_INPUT_REQUIRED", "en"): (
        "The design alternatives were not prepared: the approved steps do not give the model "
        "enough facts to work on (GROUNDED_INPUT_REQUIRED). Add details to the brief in the web "
        "Studio, for example who will use the product and what it must let them do, then "
        "launch `ut design` again.\n"
    ),
    ("GROUNDED_INPUT_REQUIRED", "it"): (
        "Le alternative di design non sono state preparate: i passi approvati non danno al "
        "modello abbastanza fatti su cui lavorare (GROUNDED_INPUT_REQUIRED). Aggiungi dettagli "
        "al brief nello Studio web, per esempio chi userà il prodotto e che cosa deve permettere "
        "di fare, poi rilancia `ut design`.\n"
    ),
    ("INVALID_PROVIDER_OUTPUT", "en"): (
        "The design alternatives were not prepared: the model gave an answer that cannot be "
        "used (INVALID_PROVIDER_OUTPUT). Nothing changed; launching `ut design` again is a new "
        "generation.\n"
    ),
    ("INVALID_PROVIDER_OUTPUT", "it"): (
        "Le alternative di design non sono state preparate: il modello ha dato una risposta "
        "che non si può usare (INVALID_PROVIDER_OUTPUT). Non è cambiato nulla; rilanciare "
        "`ut design` è una nuova generazione.\n"
    ),
    (None, "en"): (
        "The model could not prepare the design alternatives from the approved steps, and the "
        "Studio gave no reason (PROPOSAL_REJECTED). Nothing changed; you can launch `ut design` "
        "again, and a new attempt is a new generation.\n"
    ),
    (None, "it"): (
        "Il modello non è riuscito a preparare le alternative di design a partire dai passi "
        "approvati, e lo Studio non ha indicato il motivo (PROPOSAL_REJECTED). Non è cambiato "
        "nulla; puoi rilanciare `ut design`, e un nuovo tentativo è una nuova generazione.\n"
    ),
}


def refusal(reason: str | None) -> dict[str, object]:
    detail: dict[str, object] = {"code": "PROPOSAL_REJECTED"}
    if reason is not None:
        detail["proposal_issue"] = reason
    return {"detail": detail}


def alternative_ids(requests: list[RecordedRequest]) -> list[str]:
    return [json.loads(item.body)["alternative_id"] for item in requests]


def codes(session: Session, identifiers: list[str]) -> list[str]:
    names = {session.alternative(code): code for code in ("DES-001", "DES-002")}
    return [names[identifier] for identifier in identifiers]


def alternative(code: str, *, recommended: bool = False, number: int = 1) -> Alternative:
    return Alternative(
        id=f"id-{code}",
        code=code,
        number=number,
        title=code,
        summary="",
        product_name=None,
        choices={},
        recommended=recommended,
    )


class Unreachable:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.inner = UrlTransport()

    def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> Reply:
        if method == "GET" and self.marker in url:
            raise unreachable(url, sent=False)
        return self.inner.send(method, url, headers=headers, body=body, timeout=timeout)


def test_the_first_design_asks_once_draws_two_mockups_and_opens_the_previews(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        run = session.ut("design", answers=["y", "leave"])
        proposals = session.requests("POST", PROPOSALS)
        mockups = session.requests("POST", MOCKUP_JOBS)
        drawn = codes(session, alternative_ids(mockups))
        files = sorted(item.name for item in session.previews.iterdir())

    assert run.status == 0, run.errors
    assert run.output.count("Go ahead with this spending? [Y/n]") == 1
    assert (
        "Estimate: 2.91-3.74 USD, about 13 min. Credit left in the Studio: 60.00 USD." in run.output
    )
    assert "Preparing the design alternatives: done in 9 s." in run.output
    assert "Drawing the mockups: done in 9 s." in run.output
    assert "Ready: mockup of DES-001.\nReady: mockup of DES-002.\n" in run.output
    assert "Mockup: not drawn yet." not in run.output
    assert [item.headers.get("prefer") for item in proposals] == ["respond-async"]
    assert drawn == ["DES-001", "DES-002"]
    assert files == ["DES-001.html", "DES-002.html", "index.html"]
    assert run.opened == (session.uri("index.html"),)
    assert "  1. Open the previews in the browser\n" in run.output
    assert "  3. Leave\n" in run.output


def test_the_first_design_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        run = session.ut("design", answers=["s", "3"], language="it")
        mockups = session.count("POST", MOCKUP_JOBS)

    assert run.status == 0, run.errors
    assert "Design di Calcolo mancia" in run.output
    assert (
        "Stima: 2,91-3,74 USD, circa 13 min. Credito rimasto nello Studio: 60,00 USD." in run.output
    )
    assert "Vado avanti con questa spesa? [S/n]" in run.output
    assert "Pronto: mockup di DES-001." in run.output
    assert "Mockup pronti: DES-001, DES-002. Nessuna alternativa è ancora scelta." in run.output
    assert mockups == 2


def test_yes_skips_the_question(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        run = session.ut("--yes", "design", answers=["leave"])

    assert run.status == 0
    assert "Spending confirmed with --yes." in run.output
    assert "Go ahead with this spending?" not in run.output


def test_a_refused_spending_starts_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        run = session.ut("design", answers=["n"])
        posts = [item for item in session.studio.requests if item.method == "POST"]

    assert run.status == 5
    assert run.errors == "No generation started: the spending was not confirmed.\n"
    assert [item.path for item in posts] == ["/api/v1/auth/login"]


def test_a_ceiling_reached_while_drawing_keeps_the_other_mockup(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=2.0) as session:
        run = session.ut("design", answers=["y", "leave"])
        files = sorted(item.name for item in session.previews.iterdir())

    assert run.status == 0, run.errors
    assert "The estimate is above the credit left" in run.output
    assert "Ready: mockup of DES-001." in run.output
    assert (
        "Not done: mockup of DES-002. The Studio reached a spending ceiling "
        "(GENERATION_BUDGET_EXCEEDED); whoever runs the Studio can raise it." in run.output
    )
    assert files == ["DES-001.html", "index.html"]


def test_a_ceiling_already_reached_stops_before_any_mockup(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=0.45) as session:
        run = session.ut("design", answers=["y"])
        jobs_started = [job for job in session.project.jobs() if job["operation"] == "MOCKUP"]

    assert run.status == 5
    assert "Design alternatives" in run.output
    assert run.errors.startswith("The Studio reached a spending ceiling")
    assert jobs_started == []
    assert run.opened == ()


def test_a_rejected_mockup_can_be_drawn_again_with_a_new_gesture(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_job("MOCKUP", code="MOCKUP_REJECTED", rejected=True)
        run = session.ut("design", answers=["y", "mockups", "y", "leave"])
        drawn = codes(session, alternative_ids(session.requests("POST", MOCKUP_JOBS)))

    assert run.status == 0, run.errors
    assert "Drawing the mockups: not completed after 9 s.\n" in run.output
    assert "Drawing the mockup of DES-001: done in 9 s.\n" in run.output
    assert (
        "Discarded: mockup of DES-001. The result did not pass the checks of the Studio "
        "(MOCKUP_REJECTED); nothing changed.\n- the screen fails the check\n" in run.output
    )
    assert (
        "The other alternatives remain usable. Drawing DES-001 again is a new expense "
        "(1.30-1.60 USD, about 10 min): `ut design` offers it in its menu." in run.output
    )
    assert "Draw the missing mockups: DES-001 (estimate 1.30-1.60 USD, about 10 min)" in run.output
    assert run.output.count("Go ahead with this spending?") == 2
    assert drawn == ["DES-001", "DES-002", "DES-001"]
    assert len(run.opened) == 2


@pytest.mark.parametrize(
    ("language", "line"),
    [
        (
            "en",
            "This generation runs on the Claude subscription: it spends no credit. Estimated "
            "time: about 13 min.",
        ),
        (
            "it",
            "Questa generazione usa l'abbonamento di Claude: non spende credito. Tempo stimato: "
            "circa 13 min.",
        ),
    ],
)
def test_on_the_subscription_the_first_design_starts_without_a_question(
    tmp_path: Path, language: str, line: str
) -> None:
    with design_session(tmp_path, language=language, billing="SUBSCRIPTION") as session:
        run = session.ut("design", answers=["leave"], language=language)
        mockups = session.count("POST", MOCKUP_JOBS)

    assert run.status == 0, run.errors
    assert line in run.output.splitlines()
    assert "USD" not in run.output
    assert "[Y/n]" not in run.output and "[S/n]" not in run.output
    assert mockups == 2


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        (
            "en",
            "The other alternatives remain usable. Drawing DES-001 again runs on the Claude "
            "subscription and spends no credit (about 10 min): `ut design` offers it in its menu.",
        ),
        (
            "it",
            "Le altre alternative restano utilizzabili. Disegnare di nuovo DES-001 usa "
            "l'abbonamento di Claude e non spende credito (circa 10 min): `ut design` te lo "
            "propone nel menu.",
        ),
    ],
)
def test_on_the_subscription_a_rejected_mockup_is_offered_again_without_an_amount(
    tmp_path: Path, language: str, sentence: str
) -> None:
    with design_session(tmp_path, language=language, billing="SUBSCRIPTION") as session:
        session.studio.fail_job("MOCKUP", code="MOCKUP_REJECTED", rejected=True)
        run = session.ut("design", answers=["leave"], language=language)

    assert run.status == 0, run.errors
    assert sentence in run.output
    assert "USD" not in run.output


@pytest.mark.parametrize("billing", ["MIXED", "API"])
def test_with_paid_routes_a_rejected_mockup_names_its_amount(tmp_path: Path, billing: str) -> None:
    with design_session(tmp_path, billing=billing) as session:
        session.studio.fail_job("MOCKUP", code="MOCKUP_REJECTED", rejected=True)
        run = session.ut("design", answers=["y", "leave"])

    assert run.status == 0, run.errors
    assert run.output.count("Go ahead with this spending? [Y/n]") == 1
    assert (
        "The other alternatives remain usable. Drawing DES-001 again is a new expense "
        "(1.30-1.60 USD, about 10 min): `ut design` offers it in its menu." in run.output
    )


def test_a_lost_mockup_is_said_and_offered_again(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.lose_job("MOCKUP")
        run = session.ut("design", answers=["y", "leave"])

    assert run.status == 0, run.errors
    assert (
        "Lost: mockup of DES-001, perhaps because the Studio restarted. Nothing changed."
        in run.output
    )
    assert "Ready: mockup of DES-002." in run.output
    assert "Draw the missing mockups: DES-001" in run.output


def test_a_busy_studio_is_asked_again_fifteen_seconds_later(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + MOCKUP_JOBS,
            status=429,
            body={"detail": {"code": "TOO_MANY_GENERATIONS"}},
            times=2,
        )
        run = session.ut("design", answers=["y", "leave"])
        attempts = session.count("POST", MOCKUP_JOBS)

    assert run.status == 0, run.errors
    assert (
        "Too many generations are already running in the Studio: I wait 15 seconds and try "
        "again (attempt 2 of 8)." in run.output
    )
    assert "(attempt 3 of 8)" in run.output
    assert attempts == 4
    assert run.slept >= 30


def test_a_studio_busy_for_eight_attempts_stops_without_spending(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + MOCKUP_JOBS,
            status=429,
            body={"detail": {"code": "TOO_MANY_GENERATIONS"}},
            times=16,
        )
        run = session.ut("design", answers=["y"])
        attempts = session.count("POST", MOCKUP_JOBS)

    assert run.status == 1
    assert "(attempt 8 of 8)" in run.output
    assert "(attempt 9 of 8)" not in run.output
    assert run.errors.startswith("Too many generations are running in the Studio: I tried 8")
    assert attempts == 16


def test_ctrl_c_while_drawing_then_the_command_finds_the_mockups(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        bundle = terminal(tmp_path, transport=UrlTransport(), answers=["y"])

        def interrupting(seconds: float) -> None:
            if session.count("POST", MOCKUP_JOBS) == 2:
                raise KeyboardInterrupt
            bundle.clock.sleep(seconds)

        environment = dataclasses.replace(bundle.environment, sleep=interrupting)
        status = main(["--lang", "en", "design"], environment=environment)
        running = [job["status"] for job in session.project.jobs() if job["operation"] == "MOCKUP"]
        again = session.ut("design", answers=["leave"])
        started = session.count("POST", MOCKUP_JOBS)
        files = sorted(item.name for item in session.previews.iterdir())

    assert status == 130
    assert bundle.errors == (
        "Interrupted. Drawing the mockups: the generation goes on in the Studio; launching "
        "the command again finds it.\n"
    )
    assert running == ["RUNNING", "RUNNING"]
    assert again.status == 0, again.errors
    assert (
        "In the Studio this is already running: mockup of DES-001, mockup of DES-002. I start "
        "nothing new: I follow it." in again.output
    )
    assert "Ready: mockup of DES-001.\nReady: mockup of DES-002.\n" in again.output
    assert "Go ahead with this spending?" not in again.output
    assert "Design alternatives" in again.output
    assert again.opened == (session.uri("index.html"),)
    assert started == 2
    assert files == ["DES-001.html", "DES-002.html", "index.html"]


def test_a_running_proposal_is_followed_and_nothing_else_starts(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        reply = session.client().request(
            "POST", design_api.proposals_path(session.project.id), prefer_async=True
        )
        run = session.ut("design", answers=["leave"])
        proposals = session.count("POST", PROPOSALS)
        mockups = session.count("POST", MOCKUP_JOBS)

    assert reply.status == 202
    assert run.status == 0, run.errors
    assert "In the Studio this is already running: design alternatives." in run.output
    assert "Design alternatives\n===================" in run.output
    assert "Draw the missing mockups: DES-001, DES-002 (estimate 2.60-3.20 USD" in run.output
    assert (proposals, mockups) == (1, 0)


@pytest.mark.parametrize(
    ("hosted", "ending"),
    [
        (False, "When you want to try again, launch `ut design` again.\n"),
        (True, "launch `ut design` again: it shows you the estimate first.\n"),
    ],
)
def test_a_followed_proposal_that_fails_is_not_started_again(
    tmp_path: Path, hosted: bool, ending: str
) -> None:
    with design_session(tmp_path, hosted=hosted) as session:
        session.studio.fail_job("DESIGN_PROPOSAL", code="TIMEOUT")
        reply = session.client().request(
            "POST", design_api.proposals_path(session.project.id), prefer_async=True
        )
        run = session.ut("design")
        proposals = session.count("POST", PROPOSALS)

    assert reply.status == 202
    assert run.status == 1
    assert "Waiting for the running generation to end: not completed after 9 s." in run.output
    assert (
        "Cut: design alternatives. The generation was stopped because it was too long "
        "(TIMEOUT); nothing changed." in run.output
    )
    assert run.output.endswith(ending)
    assert "The design alternatives were not prepared." in run.output
    assert proposals == 1


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_followed_proposal_refused_for_the_team_says_why_once(
    tmp_path: Path, language: str
) -> None:
    with design_session(
        tmp_path, hosted=False, team_without=[DESIGNER], language=language
    ) as session:
        reply = session.client().request(
            "POST", design_api.proposals_path(session.project.id), prefer_async=True
        )
        run = session.ut("design", language=language)
        proposals = session.count("POST", PROPOSALS)

    assert reply.status == 202
    assert run.status == 1
    assert run.output.endswith(REFUSALS[("UX_DESIGNER_REQUIRED", language)])
    assert run.output.count("UX_DESIGNER_REQUIRED") == 1
    assert run.errors == ""
    assert proposals == 1


def test_the_studio_stops_answering_while_the_mockups_are_drawn(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        run = run_ut(
            ["--lang", "en", "design"],
            tmp_path,
            transport=Unreachable(MOCKUP_JOBS + "/"),
            answers=["y"],
        )
        again = session.ut("design", answers=["leave"])
        started = session.count("POST", MOCKUP_JOBS)
        address = session.studio.address

    assert run.status == 4
    assert run.errors == (
        f"The Studio at {address} stopped answering during: Drawing the "
        "mockups. If the generation had started it goes on in the Studio: when the Studio "
        "answers again, launch the same command and it finds it.\n"
    )
    assert again.status == 0, again.errors
    assert "Ready: mockup of DES-002." in again.output
    assert started == 2


def test_a_proposal_cut_because_too_long_is_said(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        session.studio.fail_job("DESIGN_PROPOSAL", code="TIMEOUT")
        run = session.ut("design", answers=["y"])
        mockups = session.count("POST", MOCKUP_JOBS)

    assert run.status == 1
    assert "Preparing the design alternatives: not completed after 9 s.\n" in run.output
    assert run.errors == (
        "The generation was stopped because it took too long (TIMEOUT). The design did not "
        "change; trying again is a new expense.\n"
    )
    assert mockups == 0


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_proposal_refused_because_the_team_has_no_designer(tmp_path: Path, language: str) -> None:
    with design_session(
        tmp_path, hosted=False, team_without=[DESIGNER], language=language
    ) as session:
        run = session.ut("design", language=language)
        proposals = session.requests("POST", PROPOSALS)
        design = session.project.current("design")

    assert run.status == 1
    assert run.errors == REFUSALS[("UX_DESIGNER_REQUIRED", language)]
    ended = "not completed after 9 s." if language == "en" else "non completato dopo 9 s."
    assert ended in run.output
    assert [item.headers.get("prefer") for item in proposals] == ["respond-async"]
    assert design is None


@pytest.mark.parametrize(
    ("reason", "language"),
    [
        ("GROUNDED_INPUT_REQUIRED", "en"),
        ("GROUNDED_INPUT_REQUIRED", "it"),
        ("INVALID_PROVIDER_OUTPUT", "en"),
        ("INVALID_PROVIDER_OUTPUT", "it"),
        (None, "en"),
        (None, "it"),
    ],
)
def test_a_refused_proposal_says_the_reason_in_words(
    tmp_path: Path, reason: str | None, language: str
) -> None:
    with design_session(tmp_path, hosted=False, language=language) as session:
        session.studio.fail_next(
            "POST", "/projects/{project_id}" + PROPOSALS, status=409, body=refusal(reason)
        )
        run = session.ut("design", language=language)

    assert run.status == 1
    assert run.errors == REFUSALS[(reason, language)]
    assert "PROPOSAL_REJECTED" not in run.output


def test_a_refusal_without_reason_inside_the_job_gives_the_generic_sentence(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, hosted=False) as session:
        session.studio.fail_job("DESIGN_PROPOSAL", code="PROPOSAL_REJECTED", status=409)
        run = session.ut("design")

    assert run.status == 1
    assert "Preparing the design alternatives: not completed after 9 s.\n" in run.output
    assert run.errors == REFUSALS[(None, "en")]


def test_the_first_design_without_a_model_only_shows_what_the_twins_think(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path, hosted=False) as session:
        run = session.ut("--yes", "design", answers=["choose", "1", "approve", "leave"])
        design = session.project.current("design")
        writes = session.writes()

    assert run.status == 0, run.errors
    assert design is not None
    package = design["package"]
    assert package["owner_selected_alternative_id"] is None
    assert "Go ahead with this spending?" not in run.output
    assert "Preparing the design alternatives: done in 9 s.\n" in run.output
    shown = " ".join(run.output.split())
    for alternative in package["alternatives"]:
        suffix = " (recommended by the model)" if alternative["code"] == "DES-001" else ""
        assert f"{alternative['code']} · {alternative['title']}{suffix}" in shown
    assert "What the twins think\n====================\nDES-001 · " in run.output
    assert "  - Strengths: The guided workflow direction keeps every" in run.output
    assert "see below" not in run.output and "\nTwin " not in run.output
    assert run.output.endswith(f"{NO_MODEL}The alternatives are ready; none has been chosen yet.\n")
    assert "What do you want to do?" not in run.output
    assert FIGURES.search(run.output) is None
    assert writes == [PROPOSALS]
    assert run.opened == ()
    assert not session.previews.exists()


def test_the_first_design_with_a_model_that_draws_no_mockup(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        without_drawing(session)
        run = session.ut("design", answers=["y", "leave"])
        mockups = session.count("POST", MOCKUP_JOBS)

    assert run.status == 0, run.errors
    assert "Estimate: 0.31-0.54 USD, about 3 min." in run.output
    assert run.output.count("Go ahead with this spending? [Y/n]") == 1
    assert "the mockup previews in the browser are not available" in run.output
    assert "This Studio has no model connected" not in run.output
    assert (
        "  1. Choose an alternative; right after, the twins review it (estimate 0.27-0.40 "
        "USD, about 2 min)\n" in run.output
    )
    assert "Open the previews" not in run.output
    assert mockups == 0
    assert run.opened == ()


def test_without_a_ceiling_the_first_design_shows_no_figure(tmp_path: Path) -> None:
    with design_session(tmp_path, budget_usd=None) as session:
        session.studio.fail_job("MOCKUP", code="MOCKUP_REJECTED", rejected=True)
        run = session.ut("design", answers=["leave"])
        started = session.count("POST", MOCKUP_JOBS)
        budgets = session.count("GET", "/model-runtime/budget")

    assert run.status == 0, run.errors
    assert FIGURES.search(run.output) is None
    assert "Go ahead with this spending?" not in run.output
    assert "Estimate" not in run.output
    assert "Ready: mockup of DES-002." in run.output
    assert (
        "The other alternatives remain usable. `ut design` offers in its menu to draw DES-001 "
        "again." in run.output
    )
    assert "  3. Draw the missing mockups: DES-001\n" in run.output
    assert started == 2
    assert budgets == 3


def test_following_stops_after_the_time_limit(tmp_path: Path) -> None:
    with design_session(tmp_path, job_polls=50) as session:
        version = propose(session)
        client = session.client()
        project_id = session.project.id
        reply = design_api.start_mockup(client, project_id, version, session.alternative("DES-001"))
        job = reply.json()
        bundle = terminal(tmp_path, transport=UrlTransport())
        context = command_context(bundle.environment)
        tracked = design_generate.Tracked(
            job_id=job["job_id"],
            operation="MOCKUP",
            address=design_api.mockup_job_path(project_id, job["job_id"]),
            name="mockup of DES-001",
            alternative_id=job["alternative_id"],
            job=job,
        )
        with pytest.raises(CliError) as stopped:
            design_generate.follow(
                context, context.client(), [tracked], label="Drawing", limit_seconds=5
            )

    assert stopped.value.code == "GENERATION_STILL_RUNNING"
    assert stopped.value.values == {"label": "Drawing", "job_id": job["job_id"]}
    assert bundle.clock.slept == 2 * jobs.POLL_SECONDS


def test_two_mockups_are_the_recommended_one_and_the_first_other() -> None:
    first, second, third = (
        alternative("DES-001", number=1),
        alternative("DES-002", number=2),
        alternative("DES-003", recommended=True, number=3),
    )

    assert design_generate.pair([first, second]) == (first, second)
    assert design_generate.pair([first, second, third]) == (first, third)
    assert design_generate.pair([third, first, second]) == (third, first)


def test_the_failure_of_an_answer_or_of_a_job_names_its_code() -> None:
    job = {"job_id": "j", "status": "FAILED", "failure": {"code": "TIMEOUT", "reasons": []}}

    assert design_generate.failure_of(502, job).code == "TIMEOUT"
    assert design_generate.failure_of(409, {"detail": {"code": "X_Y"}}).code == "X_Y"
    assert design_generate.failure_of(401, {"detail": "invalid_authentication"}).code == (
        "invalid_authentication"
    )
    assert design_generate.failure_of(500, "Internal Server Error").code == (
        "Internal Server Error"
    )
    assert design_generate.failure_of(500, None).code == "API_FAILURE"
    with pytest.raises(CliError) as changed:
        design_generate.raise_failure(ApiFailure("CONTEXT_CHANGED", http_status=409))
    assert changed.value.code == "DESIGN_CONTEXT_CHANGED"
    with pytest.raises(ApiFailure):
        design_generate.raise_failure(ApiFailure("OTHER", http_status=409))


def test_busy_answers_are_retried_at_most_eight_times(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)
    answers = iter([429, 429, 202])

    assert design_generate.retry_busy(context, lambda: next(answers), lambda value: value) == 202
    assert bundle.clock.slept == 30
    always = design_generate.retry_busy(context, lambda: 429, lambda value: value)
    assert always == 429
    assert bundle.clock.slept == 30 + 7 * 15
