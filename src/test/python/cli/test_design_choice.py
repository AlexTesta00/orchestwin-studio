from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api

from .test_api_design import (
    DECLARATIVE,
    Session,
    choose,
    choose_in_the_web,
    design_session,
    draw,
    propose,
    prototype_package,
    without_drawing,
)

REVISIONS = "/design/revisions"
DECISION = "/decision"
EVALUATIONS = "/design/evaluations"
NO_MODEL_CHOICE = {
    "en": (
        "On this Studio no alternative can be chosen: it has no model connected, and the "
        "choice needs one to prepare the prototype of the alternative. Nothing changed; "
        "whoever runs the Studio can connect one.\n"
    ),
    "it": (
        "Su questo Studio non si può scegliere un'alternativa: non ha un modello collegato, e "
        "la scelta ne ha bisogno per preparare il prototipo dell'alternativa. Non è cambiato "
        "nulla; chi gestisce lo Studio può collegarne uno.\n"
    ),
}
NO_MODEL_APPROVAL = (
    "The design cannot be approved yet: an alternative must be chosen first, and on this "
    "Studio the choice needs a model that is not connected. Whoever runs the Studio can "
    "connect one.\n"
)


def ready(session: Session) -> None:
    propose(session)
    draw(session, "DES-001", "DES-002")


def selected(session: Session) -> str | None:
    design = session.project.current("design")
    assert design is not None
    return design["package"]["owner_selected_alternative_id"]


def test_a_choice_applies_the_mockup_and_the_twins_review_it(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "choose", "DES-002")
        chosen = selected(session)
        second = session.alternative("DES-002")
        evaluations = session.requests("POST", EVALUATIONS)
        revisions = session.count("POST", REVISIONS)
        decisions = session.count("POST", DECISION)

    assert run.status == 0, run.errors
    assert "You chose DES-002 “Single card”: the design is now at version 2." in run.output
    assert "I am about to ask the twins to review the chosen design." in run.output
    assert "Estimate: 0.27-0.40 USD, about 2 min. Credit left in the Studio: 56.65 USD." in (
        run.output
    )
    assert "Go ahead with this spending?" not in run.output
    assert "Review of the twins, version 2" in run.output
    assert "(screen “Tip calculator”, element “Split the bill”)" in run.output
    assert "SCR-00" not in run.output
    assert chosen == second
    assert (revisions, decisions) == (1, 1)
    assert [json.loads(item.body)["locale"] for item in evaluations] == ["en-US"]


def test_a_choice_by_number_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        ready(session)
        run = session.ut("design", "choose", "1", language="it")
        chosen = selected(session)
        first = session.alternative("DES-001")
        evaluations = session.requests("POST", EVALUATIONS)

    assert run.status == 0, run.errors
    assert "Hai scelto DES-001 “Calcolo guidato”: il design è ora alla versione 2." in run.output
    assert "Revisione dei twin, versione 2" in run.output
    assert "schermata “Importo del conto”" in run.output
    assert chosen == first
    assert [json.loads(item.body)["locale"] for item in evaluations] == ["it-IT"]


def test_a_code_in_lower_case_is_understood(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "choose", "des-001")
        chosen = selected(session)
        first = session.alternative("DES-001")

    assert run.status == 0, run.errors
    assert chosen == first


def test_an_unknown_code_names_the_codes_that_exist(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "choose", "DES-009")
        revisions = session.count("POST", REVISIONS)

    assert run.status == 2
    assert run.errors == (
        "The alternative DES-009 does not exist. Write one of these codes, or its number: "
        "DES-001, DES-002.\n"
    )
    assert revisions == 0


def test_choosing_the_chosen_alternative_again_changes_nothing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.ut("design", "choose", "DES-002")
        run = session.ut("design", "choose", "DES-002")
        evaluations = session.count("POST", EVALUATIONS)
        revisions = session.count("POST", REVISIONS)

    assert run.status == 0
    assert run.output == (
        "DES-002 “Single card” is already the chosen alternative: nothing changed.\n"
    )
    assert (evaluations, revisions) == (1, 1)


@pytest.mark.parametrize(
    ("budget", "ending"),
    [
        (60.0, "it offers it in its menu, with its estimate.\n"),
        (None, "it offers it in its menu.\n"),
    ],
)
def test_without_a_mockup_an_alternative_cannot_be_chosen(
    tmp_path: Path, budget: float | None, ending: str
) -> None:
    with design_session(tmp_path, budget_usd=budget) as session:
        propose(session)
        draw(session, "DES-001")
        run = session.ut("design", "choose", "DES-002")
        mockups = session.count("POST", "/design/mockups/jobs")
        revisions = session.count("POST", REVISIONS)

    assert run.status == 1
    assert run.output == (
        "DES-002 has no mockup yet, and without a mockup it cannot be chosen. Launch "
        f"`ut design`: {ending}"
    )
    assert (mockups, revisions) == (1, 0)


def test_another_alternative_can_be_chosen_after_the_first(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.ut("design", "choose", "DES-002")
        run = session.ut("design", "choose", "DES-001")
        design = session.project.current("design")
        first = session.alternative("DES-001")
        evaluations = session.count("POST", EVALUATIONS)

    assert run.status == 0, run.errors
    assert "You chose DES-001 “Guided calculation”: the design is now at version 3." in run.output
    assert design is not None
    package = design["package"]
    assert package["owner_selected_alternative_id"] == first
    assert package["prototype"]["design_alternative_id"] == first
    assert package["generated_mockup"]["mockup"]["design_alternative_id"] == first
    assert evaluations == 2


def test_a_waiting_proposal_of_the_same_choice_is_decided(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        result = session.project.mockups[session.alternative("DES-002")]
        design_api.propose_revision(session.client(), session.project.id, result["package"])
        run = session.ut("design", "choose", "DES-002")
        revisions = session.count("POST", REVISIONS)
        decisions = session.count("POST", DECISION)
        chosen = selected(session)
        second = session.alternative("DES-002")

    assert run.status == 0, run.errors
    assert (revisions, decisions) == (2, 1)
    assert chosen == second


def test_a_waiting_proposal_made_elsewhere_stops_the_choice(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        result = session.project.mockups[session.alternative("DES-001")]
        design_api.propose_revision(session.client(), session.project.id, result["package"])
        run = session.ut("design", "choose", "DES-002")
        evaluations = session.count("POST", EVALUATIONS)

    assert run.status == 1
    assert run.errors.startswith(
        "The Studio already holds a proposed change of the design waiting for a decision"
    )
    assert evaluations == 0


def test_a_choice_where_the_model_prepares_only_the_prototype(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        version = propose(session)
        without_drawing(session)
        first = session.alternative("DES-001")
        session.studio.fail_next(
            "POST",
            DECLARATIVE,
            status=200,
            body={
                "status": "MOCKUP_GENERATED",
                "generation_id": "00000000-0000-4000-8000-00000000000a",
                "design_version_id": version["id"],
                "design_content_hash": version["content_hash"],
                "package": prototype_package(session, "DES-001"),
                "approach": None,
                "changes": [],
                "warnings": [],
                "cost_microusd": None,
            },
        )
        run = session.ut("design", "choose", "DES-001")
        chosen = selected(session)
        declarative = session.count("POST", f"{session.base}/design/mockups")
        reviews = session.count("POST", EVALUATIONS)

    priced = [line for line in run.output.splitlines() if re.search(r"USD|\d+ min\b", line)]
    assert run.status == 0, run.errors
    assert (
        "To apply the choice I prepare the prototype of DES-001.\n"
        "Preparing the prototype of DES-001...\n"
        "Preparing the prototype of DES-001: done in 0 s.\n" in run.output
    )
    assert "You chose DES-001 “Guided calculation”: the design is now at version 2." in run.output
    assert "Review of the twins, version 2" in run.output
    assert chosen == first
    assert (declarative, reviews) == (1, 1)
    assert [line.split(" USD", 1)[0] for line in priced] == ["Estimate: 0.27-0.40"]


@pytest.mark.parametrize("language", ["en", "it"])
def test_without_a_model_no_alternative_can_be_chosen(tmp_path: Path, language: str) -> None:
    with design_session(tmp_path, hosted=False, language=language) as session:
        propose(session)
        run = session.ut("design", "choose", "1", language=language)
        chosen = selected(session)
        writes = session.writes()

    assert run.status == 1
    assert run.output == NO_MODEL_CHOICE[language]
    assert run.errors == ""
    assert chosen is None
    assert writes == ["/design/proposals"]


def test_a_studio_that_cannot_prepare_the_prototype_refuses_the_choice(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        without_drawing(session)
        session.studio.fail_next(
            "POST",
            DECLARATIVE,
            status=503,
            body={"detail": {"code": "REAL_MOCKUP_MODEL_NOT_CONFIGURED"}},
        )
        run = session.ut("design", "choose", "DES-001")
        chosen = selected(session)
        revisions = session.count("POST", REVISIONS)

    assert run.status == 1
    assert run.output == (
        "To apply the choice I prepare the prototype of DES-001.\n"
        "Preparing the prototype of DES-001...\n"
        "Preparing the prototype of DES-001: not completed after 0 s.\n"
        f"{NO_MODEL_CHOICE['en']}"
    )
    assert chosen is None
    assert revisions == 0


def test_without_a_model_only_a_design_chosen_in_the_web_can_be_approved(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        refused = session.ut("design", "approve")
        refused_writes = session.writes()
        choose_in_the_web(session, "DES-002")
        approval = session.ut("design", "approve")
        approved = session.project.approved("design")
        folder = session.folder / "orchestwin"

    assert refused.status == 1
    assert refused.output == NO_MODEL_APPROVAL
    assert refused_writes == ["/design/proposals"]
    assert approval.status == 0, approval.errors
    assert approval.output.startswith("Design approved: DES-002 “Operations dashboard: ")
    assert f"The knowledge folder is in {folder}: version 1, " in approval.output
    assert approved
    assert (folder / "ORCHESTWIN.md").is_file()


def test_a_review_that_cannot_run_after_a_choice_ends_with_one(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.studio.fail_job(
            "DESIGN_EVALUATION", code="DESIGN_EVALUATOR_NOT_CONFIGURED", status=503
        )
        run = session.ut("design", "choose", "DES-002")
        chosen = selected(session)
        second = session.alternative("DES-002")
        runs = session.project.runs

    assert run.status == 1
    assert "You chose DES-002 “Single card”: the design is now at version 2." in run.output
    assert "The twins are reviewing the design: not completed after 9 s.\n" in run.output
    assert run.errors == (
        "On this Studio the twins cannot review the design: neither a model nor an automatic "
        "check for the review is connected (DESIGN_EVALUATOR_NOT_CONFIGURED). The design stays "
        "as it is; whoever runs the Studio can connect one.\n"
    )
    assert run.output.endswith(
        "The choice stays applied in version 2, but the twins did not review it, for the "
        "reason given. Once the reason is solved, launch `ut design review` to have the review "
        "done.\n"
    )
    assert chosen == second
    assert runs == []


def test_the_approval_brings_the_knowledge_folder(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        version = choose(session, "DES-002")
        run = session.ut("design", "approve")
        approved = session.project.approved("design")
        decisions = session.requests("POST", "/design/gate/decision")
        submissions = session.count("POST", "/design/gate/submit")
        folder = session.folder / "orchestwin"

    step = json.loads((session.folder / ".orchestwin" / "steps" / "design.json").read_text("utf-8"))
    assert run.status == 0, run.errors
    assert (
        "Design approved: DES-002 “Single card”, version 2. Now I prepare the knowledge folder."
        in run.output
    )
    assert f"The knowledge folder is in {folder}: version 1, " in run.output
    assert "Inside you find ORCHESTWIN.md, to be read first" in run.output
    assert (folder / "ORCHESTWIN.md").is_file()
    assert approved
    assert submissions == 1
    assert [json.loads(item.body) for item in decisions] == [{"action": "APPROVE"}]
    assert step["stage"] == "design"
    assert step["version"]["id"] == version["id"]
    assert step["gate"]["status"] == "APPROVED"


def test_the_approval_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        ready(session)
        choose(session, "DES-001")
        run = session.ut("design", "approve", language="it")

    assert run.status == 0, run.errors
    assert "Design approvato: DES-001 “Calcolo guidato”, versione 2." in run.output
    assert "Dentro trovi ORCHESTWIN.md, da leggere per primo" in run.output


def test_an_approval_needs_a_choice(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        run = session.ut("design", "approve")
        submissions = session.count("POST", "/design/gate/submit")

    assert run.status == 1
    assert run.output == (
        "Before approving, choose an alternative, for example with `ut design choose DES-001`.\n"
    )
    assert submissions == 0


def test_an_approved_design_is_not_approved_again(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        run = session.ut("design", "approve")
        submissions = session.count("POST", "/design/gate/submit")

    assert run.status == 0
    assert run.output == (
        "The design is already approved: DES-002 “Single card”, version 2.\n"
        "The knowledge folder has not been prepared yet: `ut package publish` creates it.\n"
    )
    assert submissions == 0


def test_when_the_publication_fails_the_approval_stays(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        choose(session, "DES-002")
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=503,
            body={"detail": {"code": "KNOWLEDGE_PACKAGE_UNAVAILABLE"}},
        )
        run = session.ut("design", "approve")
        approved = session.project.approved("design")

    assert run.status == 1
    assert (
        "The design stays approved, but the knowledge folder was not prepared now: "
        "`ut package publish` completes the work." in run.output
    )
    assert run.errors == (
        "The Studio answered with an error (status 503, KNOWLEDGE_PACKAGE_UNAVAILABLE).\n"
    )
    assert approved
    assert (session.folder / ".orchestwin" / "steps" / "design.json").is_file()
    assert not (session.folder / "orchestwin").exists()


def test_the_design_changed_in_the_meantime(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        ready(session)
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}/design/revisions/{diff_id}/decision",
            status=409,
            body={"detail": {"code": "CONTEXT_CHANGED"}},
        )
        run = session.ut("design", "choose", "DES-002")
        evaluations = session.count("POST", EVALUATIONS)

    assert run.status == 1
    assert run.errors == (
        "In the meantime the design changed, perhaps in the web interface: nothing was "
        "applied. I read the state again: check it and try again.\n"
    )
    assert run.output.endswith(
        "Mockups ready: DES-001, DES-002. No alternative has been chosen yet.\n"
    )
    assert evaluations == 0
