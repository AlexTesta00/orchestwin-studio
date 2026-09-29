from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from orchestwin.artifacts.design_discussion import DiscussionStatus
from orchestwin.artifacts.design_finding_validations import create_finding_validation
from orchestwin.knowledge.feedback import (
    DISCUSSIONS_KIND,
    INSIGHTS_KIND,
    REVIEWS_KIND,
    current_decisions,
    feedback_documents,
    feedback_markdown,
    feedback_summary,
    twin_names,
)
from orchestwin.knowledge.layout import (
    FEEDBACK_DISCUSSIONS,
    FEEDBACK_INSIGHTS,
    FEEDBACK_REVIEWS,
)
from orchestwin.knowledge.sources import KnowledgeFeedback, knowledge_feedback
from src.test.python.artifacts.design_fixtures import design_version
from src.test.python.artifacts.test_design_evaluation import TWIN_A, TWIN_B

from .knowledge_fixtures import (
    ALIGNED_COMMIT,
    RUN_ONE,
    RUN_TWO,
    applications,
    change_run,
    discussions,
    evaluation_runs,
    sources,
    state_sources,
    validations,
)


def test_feedback_keeps_runs_in_time_order_and_only_approved_discussions() -> None:
    first, second = evaluation_runs()

    feedback = knowledge_feedback(
        runs=(second, first),
        validations=reversed(validations()),
        discussions=discussions(),
        applications=applications(),
    )

    assert [run.id for run in feedback.runs] == [RUN_ONE, RUN_TWO]
    assert [item.sequence_number for item in feedback.validations] == [1, 2, 1]
    assert [item.twin_id for item in feedback.validations] == [TWIN_A, TWIN_A, TWIN_B]
    assert [item.status for item in feedback.discussions] == [DiscussionStatus.APPROVED]
    assert len(feedback.applications) == 1
    assert not feedback.is_empty
    assert KnowledgeFeedback().is_empty


def test_decisions_on_runs_outside_the_feedback_are_left_out() -> None:
    first, _ = evaluation_runs()
    known = validations()[0]
    stray = create_finding_validation(
        evaluation_run_id=UUID(int=42),
        twin_id=known.twin_id,
        finding_id=known.finding_id,
        sequence_number=1,
        project_id=known.project_id,
        owner_user_id=known.owner_user_id,
        decision=known.decision,
        note=None,
        decided_at=known.decided_at,
    )

    feedback = knowledge_feedback(runs=(first,), validations=(stray, known))

    assert feedback.validations == (known,)


def test_feedback_documents_hold_the_exact_records() -> None:
    package = sources()
    design = design_version()

    documents = feedback_documents(package)

    assert list(documents) == [FEEDBACK_REVIEWS, FEEDBACK_DISCUSSIONS, FEEDBACK_INSIGHTS]
    reviews = documents[FEEDBACK_REVIEWS]
    assert reviews["schema_version"] == 3
    assert {document["schema_version"] for document in documents.values()} == {3}
    assert reviews["kind"] == REVIEWS_KIND
    assert reviews["project_id"] == str(package.project_id)
    assert reviews["design"] == {
        "version_id": str(design.id),
        "version_number": design.version_number,
        "content_hash": design.content_hash,
    }
    assert reviews["runs"] == [run.to_snapshot() for run in package.feedback.runs]
    assert reviews["decisions"] == [item.to_snapshot() for item in package.feedback.validations]
    talks = documents[FEEDBACK_DISCUSSIONS]
    assert talks["kind"] == DISCUSSIONS_KIND
    assert talks["discussions"] == [item.to_snapshot() for item in package.feedback.discussions]
    assert [item["status"] for item in talks["discussions"]] == ["APPROVED"]
    insights = documents[FEEDBACK_INSIGHTS]
    assert insights["kind"] == INSIGHTS_KIND
    assert insights["applications"] == [
        item.to_snapshot() for item in package.feedback.applications
    ]


def test_current_decision_of_a_finding_is_its_latest_one() -> None:
    decisions = current_decisions(sources())

    assert set(decisions) == {
        (str(RUN_ONE), str(TWIN_A), "UTF-001"),
        (str(RUN_ONE), str(TWIN_B), "UTF-001"),
    }
    assert decisions[(str(RUN_ONE), str(TWIN_A), "UTF-001")]["decision"] == "OWNER_CONFIRMED"
    assert decisions[(str(RUN_ONE), str(TWIN_B), "UTF-001")]["decision"] == "OWNER_DISMISSED"


def test_summary_counts_reviews_findings_decisions_discussions_and_insights() -> None:
    assert feedback_summary(sources()) == {
        "reviews": 2,
        "findings": 4,
        "decisions": 2,
        "discussions": 1,
        "insights": 1,
    }
    assert feedback_summary(sources(with_feedback=False)) == {
        "reviews": 0,
        "findings": 0,
        "decisions": 0,
        "discussions": 0,
        "insights": 0,
    }


def test_twin_names_come_from_the_approved_snapshot() -> None:
    package = sources()

    assert twin_names(package) == {
        str(version.twin_id): version.profile.name
        for version in package.modeling.snapshot.twin_versions
    }


def test_feedback_text_shows_findings_with_the_owner_decisions() -> None:
    text = feedback_markdown(sources())

    assert text.startswith("# Twin feedback\n")
    assert (
        "This folder holds 2 reviews with 4 findings, 2 owner decisions, "
        "1 approved discussion and 1 applied insight."
    ) in text
    assert text.count("### Review of design version") == 2
    assert "(the design approved in this folder)" in text
    assert f"#### {TWIN_A}" in text
    assert (
        "| UTF-001 | moderate | Comprehensibility | SCR-001 Guest name | The field lacks help. "
        "| Add a visible label. | confirmed by the owner |"
    ) in text
    assert "| dismissed by the owner |" in text
    assert "| not decided |" in text
    assert "Evidence gaps:" in text


def test_feedback_text_reports_rounds_reactions_and_synthesis_of_discussions() -> None:
    text = feedback_markdown(sources())

    assert text.count("### Discussion on design version") == 1
    assert "#### Round 1" in text
    assert "#### Round 2" in text
    assert "Owner's note: Concentratevi sul compito principale." in text
    assert "- Ada (Concern): " in text
    assert "  - To Bruno (Partly): Capisco, ma al banco serve rapidità." in text
    assert "  - Proposal: Accorciare il modulo di prenotazione." in text
    assert "Agreements:\n- Il flusso di prenotazione è chiaro." in text
    assert "Conflicts:\n- Densità della dashboard" in text
    assert "- PRP-001 for the design: Accorciare il modulo." in text
    assert "Questions for the owner:\n- Serve una modalità per utenti esperti?" in text


def test_feedback_text_lists_the_applied_insights() -> None:
    text = feedback_markdown(sources())

    assert "## Applied insights" in text
    assert "| Applied on | Source | Twin | Target | Item | Text |" in text
    assert "| Synthetic finding |" in text
    assert "| Requirements v2 | REQ-004 | The guest name field lacks help text. |" in text


def test_feedback_text_without_records_says_so() -> None:
    text = feedback_markdown(sources(with_feedback=False))

    assert (
        "This folder holds 0 reviews with 0 findings, 0 owner decisions, "
        "0 approved discussions and 0 applied insights."
    ) in text
    assert "## Reviews\n\nnot provided.\n" in text
    assert "## Approved discussions\n\nnot provided.\n" in text
    assert "## Applied insights\n\nnot provided.\n" in text
    assert text.endswith(
        "## Critiques on the code changes\n\nNo code change has been reviewed yet.\n"
    )


def test_feedback_text_ends_with_one_paragraph_for_every_critique_run_on_the_code() -> None:
    first = change_run()
    second = {
        **change_run(),
        "id": "00000000-0000-4000-8000-00000000d002",
        "commit": ALIGNED_COMMIT,
        "reviewed_at": "2026-09-28T09:40:00+00:00",
        "alignment": {
            **change_run()["alignment"],
            "status": "DESIGN_OUTDATED",
            "design_request": "Aggiungere un filtro per sede nella lista",
            "code_tasks": [],
        },
    }
    package = sources(state=replace(state_sources(), runs=(first, second)))

    section = feedback_markdown(package).split("## Critiques on the code changes\n\n", 1)[1]
    paragraphs = [item for item in section.split("\n\n") if item.strip()]

    assert len(paragraphs) == 2
    assert paragraphs[0].startswith(
        "Commit `4f2a9c1`, reviewed on 2026-09-28 11:30+00:00 against requirements version 2 "
        "and design version 4, alternative DES-002: the code departs from the approved "
        "requirements or design (CODE_DRIFT). Il controllo del nome vuoto non segue il "
        "requisito REQ-003."
    )
    assert (
        "Addetti all'accoglienza: the change raises a concern (CONCERN), 2 findings. "
        "Il messaggio per il nome vuoto compare solo dopo il salvataggio."
    ) in paragraphs[0]
    assert "Organizzatori volontari: the change is fine (FINE), 1 finding." in paragraphs[0]
    assert paragraphs[0].endswith(
        "Tasks proposed for the code: Mostrare il messaggio di errore accanto al campo del nome."
    )
    assert paragraphs[1].startswith("Commit `9d8e7f6`, reviewed on 2026-09-28 09:40+00:00")
    assert "the design should get a new version (DESIGN_OUTDATED)" in paragraphs[1]
    assert "Design change request: Aggiungere un filtro per sede nella lista." in paragraphs[1]
    assert "Tasks proposed" not in paragraphs[1]
    assert "\n" not in paragraphs[0].strip()


def test_feedback_counts_are_zero_while_the_design_is_not_approved() -> None:
    package = replace(sources(), design=None, design_gate=None)

    assert package.present_stages == ("brief", "team", "twins", "requirements")
    assert set(feedback_summary(package).values()) == {0}
