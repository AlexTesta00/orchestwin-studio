from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.artifacts.visual_catalog import (
    ColorMode,
    DesignTone,
    FontFamily,
    HueFamily,
    LayoutArchetype,
)
from orchestwin.cli.api import design as design_api
from orchestwin.cli.flows import design_state
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import FILES, LANGUAGES, MESSAGES, known
from orchestwin.cli.project import ProjectFolder

from .support.terminal import command_context, terminal
from .test_api_design import (
    Session,
    choose,
    choose_in_the_web,
    design_session,
    draw,
    finish_job,
    propose,
    start_iteration,
)
from .test_messages import code_strings, key_used, raised_codes, studio_source

CATALOG = {
    "archetype": LayoutArchetype,
    "hue_family": HueFamily,
    "color_mode": ColorMode,
    "tone": DesignTone,
    "heading_family": FontFamily,
}
LABELS = {
    "strengths": "Strengths",
    "concerns": "Concerns",
    "unmet_needs": "Unmet needs",
    "accessibility_observations": "Accessibility",
    "trust_concerns": "Trust",
    "questions": "Questions",
    "suggested_changes": "Suggested changes",
}
MIXED = {
    "alternatives": [
        {"id": "a1", "code": "DES-001", "title": "One", "summary": ""},
        {"id": "a2", "code": "DES-002", "title": "Two", "summary": ""},
    ],
    "critiques": [
        {
            "design_alternative_id": "a1",
            "user_twin_reference": {"twin_id": "t1", "name": "Anna"},
            "verdict": "Clear",
            "quote": "I like it.",
        },
        {
            "design_alternative_id": "a2",
            "user_twin_reference": {"twin_id": "t1", "name": "Anna"},
            "verdict": None,
            "quote": None,
            "concerns": ["Too dense.", "Small text"],
            "questions": [" "],
        },
        {
            "design_alternative_id": "a2",
            "user_twin_reference": {"twin_id": "t2", "name": "Bruno"},
            "verdict": "Busy",
            "quote": None,
        },
        {
            "design_alternative_id": "a1",
            "user_twin_reference": {"twin_id": "t2", "name": "Bruno"},
            "verdict": None,
            "quote": None,
        },
    ],
}


def flat(text: str) -> str:
    return " ".join(text.split())


def read(session: Session) -> design_state.DesignState:
    return design_state.read_state(session.client(), ProjectFolder(session.folder))


def test_before_the_requirements_only_the_project_is_read(tmp_path: Path) -> None:
    with design_session(tmp_path, through="twins") as session:
        state = read(session)
        paths = [item.path for item in session.studio.requests if item.method == "GET"]

    assert state.kind == design_state.REQUIREMENTS_PENDING
    assert state.stage == "REQUIREMENTS"
    assert not any("/design" in path for path in paths)


def test_without_a_design_the_capabilities_are_read(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        state = read(session)

    assert state.kind == design_state.NO_DESIGN
    assert state.generated and state.capabilities.iterations
    assert state.alternatives == () and state.chosen is None


def test_a_running_mockup_is_found_and_no_document_is_read(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        client = session.client()
        version = propose(session)
        first = session.alternative("DES-001")
        reply = design_api.start_mockup(client, session.project.id, version, first)
        state = read(session)
        documents = session.count("GET", "/design/mockups/document")

    assert reply.status == 202
    assert state.kind == design_state.JOB_RUNNING
    assert [(job["operation"], job["alternative_id"]) for job in state.running] == [
        ("MOCKUP", first)
    ]
    assert documents == 0


def test_alternatives_without_mockups(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        state = read(session)

    assert state.kind == design_state.NO_MOCKUPS
    assert [item.code for item in state.missing_mockups()] == ["DES-001", "DES-002"]
    assert state.choosable() == ()
    assert [item.code for item in state.alternatives if item.recommended] == ["DES-002"]


def test_one_mockup_ready_and_one_missing(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001")
        state = read(session)

    assert state.kind == design_state.MOCKUPS_READY
    assert [item.code for item in state.missing_mockups()] == ["DES-002"]
    assert [item.code for item in state.choosable()] == ["DES-001"]


def test_a_chosen_design_reads_the_applied_mockup_and_the_last_review(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        version = choose(session, "DES-002")
        before = read(session)
        client = session.client()
        reply = client.request(
            "POST",
            design_api.evaluations_path(session.project.id),
            body=design_api.evaluation_body(version, "en-US"),
        )
        after = read(session)
        sources = [
            item.query.rsplit("source=", 1)[1]
            for item in session.requests("GET", "/design/mockups/document")
        ]

    assert reply.status == 201
    assert before.kind == design_state.CHOSEN
    assert before.chosen is not None and before.chosen.code == "DES-002"
    assert before.applied_mockup == before.chosen.id
    assert before.changeable
    assert before.review is None
    assert [item.code for item in before.choosable()] == ["DES-001"]
    assert after.review is not None and after.review["design_version_id"] == version["id"]
    assert sources[-2:] == ["latest", "applied"]


def test_an_approved_design(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        state = read(session)

    assert state.kind == design_state.APPROVED
    assert state.approved and state.version_number == 2
    assert state.chosen is not None and state.chosen.code == "DES-002"


def test_without_generated_mockups_every_alternative_can_be_chosen(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        state = read(session)
        documents = session.count("GET", "/design/mockups/document")

    assert state.kind == design_state.MOCKUPS_READY
    assert not state.generated
    assert state.missing_mockups() == ()
    assert [item.code for item in state.choosable()] == ["DES-001", "DES-002", "DES-003"]
    assert [item.code for item in state.alternatives if item.recommended] == ["DES-001"]
    assert documents == 0


def test_a_design_chosen_in_the_web_without_a_model_cannot_be_changed(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        choose_in_the_web(session, "DES-002")
        state = read(session)
        iterations = session.count("GET", "/design/iterations")
        evaluations = session.count("GET", "/design/evaluations")

    assert state.kind == design_state.CHOSEN
    assert state.chosen is not None and state.chosen.code == "DES-002"
    assert state.applied_mockup is None
    assert not state.changeable
    assert state.review is None and state.pending_change is None
    assert [item.code for item in state.choosable()] == ["DES-001", "DES-003"]
    assert (iterations, evaluations) == (0, 1)


def test_a_finished_change_that_was_not_applied_is_pending(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-002")
        choose(session, "DES-002")
        job = start_iteration(session, "Bigger title", ["Keep the total visible"])
        finish_job(session.client(), design_api.iteration_job_path(session.project.id, job))
        state = read(session)

    assert state.kind == design_state.CHOSEN
    assert state.pending_change is not None
    assert state.pending_change["request"] == "Bigger title"
    assert state.rules == ()


def test_an_alternative_is_found_by_code_in_any_case_or_by_number(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        state = read(session)

    assert state.find("des-002") == state.find("DES-002") == state.find("2")
    assert state.find(" DES-001 ") == state.find("1")
    assert state.find("3") is None and state.find("DES-009") is None and state.find("") is None


@pytest.mark.parametrize(("dimension", "catalog"), list(CATALOG.items()))
def test_every_visual_choice_of_the_catalog_has_words_in_both_languages(
    dimension: str, catalog: type
) -> None:
    for value in catalog:
        entry = MESSAGES.get(f"design.visual_{dimension}_{value.value}")
        assert entry is not None, value
        assert all(entry[language] for language in LANGUAGES)


def test_keys_built_at_run_time_exist() -> None:
    keys = [
        *(f"design.next_{kind.lower()}" for kind in design_state.KINDS[2:]),
        *(f"design.weight_{severity}" for severity in ("critical", "major", "moderate")),
        "design.weight_minor",
        "design.weight_observation",
    ]

    assert [key for key in keys if not known(key)] == []


def test_the_alternatives_and_the_twins_in_italian(tmp_path: Path) -> None:
    with design_session(tmp_path, language="it") as session:
        propose(session)
        state = read(session)
    bundle = terminal(tmp_path, transport=UrlTransport(), language="it")
    context = command_context(bundle.environment, language="it")

    design_state.show_alternatives(context, state)
    design_state.show_verdicts(context, state)

    lines = bundle.output.splitlines()
    assert lines[:9] == [
        "",
        "Alternative di design",
        "=====================",
        "DES-001 · Calcolo guidato",
        "  Due passi: prima l'importo, poi il risultato.",
        "  Prodotto: Mancia facile",
        "  Aspetto: impaginazione a passi guidati, tinta ottanio, modalità chiara, tono",
        "  caloroso, titoli con carattere senza grazie umanistico.",
        "  Mockup: non ancora disegnato.",
    ]
    assert "DES-002 · Scheda unica (consigliata dal modello)" in lines
    table = lines.index("Cosa pensano i twin") + 2
    assert lines[table].split() == ["Twin", "DES-001", "DES-002"]
    row = next(line for line in lines if line.startswith("Titolare della pizzeria "))
    assert [part.strip() for part in row.split("  ") if part.strip()] == [
        "Titolare della pizzeria",
        "Chiaro al tavolo",
        "Tutto a portata di mano",
    ]
    assert "- Titolare della pizzeria: “Vedo subito dove inserire l'importo.”" in lines


def test_critiques_without_verdicts_show_what_each_twin_wrote(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        state = read(session)
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)

    design_state.show_verdicts(context, state)

    output = bundle.output
    lines = output.splitlines()
    titles = [f"{item.code} · {item.title}" for item in state.alternatives]
    assert lines[:3] == ["What the twins think", "====================", titles[0]]
    assert [line for line in lines if line in titles] == titles
    assert "see below" not in output
    assert not any(line.startswith("----") for line in lines)
    blocks = [flat(part) for part in output.rstrip("\n").split("\n\n")]
    assert len(blocks) == len(state.alternatives)
    for alternative, block in zip(state.alternatives, blocks, strict=True):
        critiques = [item for item in state.verdicts if item.alternative_id == alternative.id]
        assert [item.twin_name for item in critiques] == ["Pizzeria owner", "Evening shift waiter"]
        for critique in critiques:
            assert f" {critique.twin_name} - " in block
            assert [name for name, _texts in critique.points] == list(LABELS)
            for name, texts in critique.points:
                assert flat(f"{LABELS[name]}: {texts[0]}") in block
                assert all(flat(text) in block for text in texts[1:])
    assert "The guided workflow direction" in blocks[0]
    assert "The guided workflow direction" not in blocks[1]


def test_the_table_holds_only_the_verdicts_that_exist(tmp_path: Path) -> None:
    state = design_state.DesignState(
        project_id="p",
        project_name="Tip",
        stage="DESIGN",
        version={"id": "v", "version_number": 1, "package": MIXED},
    )
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)

    design_state.show_verdicts(context, state)

    assert bundle.output == (
        "What the twins think\n"
        "====================\n"
        "Twin   DES-001  DES-002\n"
        "-----  -------  ---------\n"
        "Anna   Clear    see below\n"
        "Bruno  -        Busy\n"
        "\n"
        "DES-001\n"
        "- Anna: “I like it.”\n"
        "\n"
        "DES-002 · Two\n"
        "  Anna\n"
        "  - Concerns: Too dense. Small text\n"
        "\n"
    )


def test_long_texts_of_the_model_wrap_at_the_width_of_the_terminal(tmp_path: Path) -> None:
    with design_session(tmp_path, hosted=False) as session:
        propose(session)
        state = read(session)
    bundle = terminal(tmp_path, transport=UrlTransport(), variables={"COLUMNS": "44"})
    context = command_context(bundle.environment)

    design_state.show_alternatives(context, state)
    design_state.show_verdicts(context, state)

    lines = bundle.output.splitlines()
    text = flat(bundle.output)
    assert context.console.width == 44
    assert max(len(line) for line in lines) <= 44
    for alternative in state.alternatives:
        assert flat(alternative.summary) in text
        assert flat(f"{alternative.code} · {alternative.title}") in text
    assert any(line.startswith("    ") for line in lines)


def test_every_key_of_the_design_is_used() -> None:
    literals, prefixes = code_strings()
    raised = {code for _, code in raised_codes()}
    studio = studio_source()

    def used(key: str) -> bool:
        if not key.startswith("design.errors."):
            return key_used(key, literals, prefixes, raised, studio)
        code, _, reason = key.removeprefix("design.errors.").partition(".")
        return all(
            name in literals or name in raised or f'"{name}"' in studio
            for name in (code, reason)
            if name
        )

    assert [key for key in FILES["design"] if not used(key)] == []


def test_an_unknown_visual_value_is_written_in_plain_words(tmp_path: Path) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment)

    assert design_state.visual_word(context, "tone", "BRAND_NEW_TONE") == "brand new tone"
    assert design_state.visual_word(context, "tone", None) == "-"
    assert design_state.visual_word(context, "tone", "WARM") == "warm"
