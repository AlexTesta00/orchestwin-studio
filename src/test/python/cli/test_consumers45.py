from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.flows import design_choice, design_generate, design_state, review
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import known, text
from orchestwin.cli.views import directions
from orchestwin.cli.views import why as why_view

from .support.fake_studio import FakeStudio
from .support.terminal import command_context, terminal
from .test_api_design import design_session, draw, propose
from .test_console import console_for

WIDE = {"COLUMNS": "200"}
MOCKUP_JOBS = "/design/mockups/jobs"
CODES = ("DES-001", "DES-002", "DES-003")
APPLE = "apple-hig"
APPLE_AXES = {
    "layout": "PANELS",
    "shape": "SOFT_FILL",
    "type": "EVEN",
    "colour": "ACCENT_ONLY",
    "density": "COMFORTABLE",
}
APPLE_DIRECTION = {
    "name": "Apple Human Interface Guidelines",
    "concept": "Clear panels on a light grey ground.",
    "rules": ["One.", "Two.", "Three."],
    "axes": APPLE_AXES,
    "typicality": 50,
    "candidates": 2,
    "vocabulary_version": 1,
}
SYSTEM_LINES = {
    "en": "  Design system: Apple Human Interface Guidelines",
    "it": "  Sistema di design: Apple Human Interface Guidelines",
}
DIRECTION_LINES = {
    "en": "  Visual direction: Apple Human Interface Guidelines (Panels, Filled surfaces, "
    "Restrained scale, Colour on the action only, Comfortable)",
    "it": "  Direzione visiva: Apple Human Interface Guidelines (Pannelli, Superfici piene, "
    "Scala contenuta, Colore solo sull'azione, Comoda)",
}
CHOSEN = {
    "en": "You chose DES-003 “Clear panels”: the design is now at version 4.",
    "it": "Hai scelto DES-003 «Clear panels»: il design è ora alla versione 4.",
}
SYSTEM_TITLES = {"en": "iPhone-style calculation", "it": "Calcolo in stile iPhone"}
WHY_ORIGINS = {
    "en": (
        "Direction of the Apple Human Interface Guidelines design system.",
        "Proposed by the model among 2 candidates; chosen by the Studio because it is far from "
        "the other.",
    ),
    "it": (
        "Direzione del sistema di design Apple Human Interface Guidelines.",
        "Proposta dal modello fra 2 candidate; scelta dallo Studio perché lontana dall'altra.",
    ),
}
ABSENT = object()


class Prices:
    def modelless(self, state: design_state.DesignState) -> bool:
        return False

    def shown(self) -> bool:
        return False


def visual(direction: object = None, system: object = ABSENT) -> dict[str, object]:
    found: dict[str, object] = {
        "product_name": "Easy tip",
        "choices": {
            "archetype": "SINGLE_CARD",
            "hue_family": "COBALT",
            "color_mode": "LIGHT",
            "tone": "CALM",
            "heading_family": "HUMANIST_SANS",
        },
    }
    if direction is not None:
        found["direction"] = direction
    if system is not ABSENT:
        found["design_system"] = system
    return found


def three_state(
    system: object = APPLE, documents: tuple[str, ...] = CODES
) -> design_state.DesignState:
    alternatives = [
        {"id": "a1", "code": "DES-001", "title": "Guided", "summary": "Two steps."},
        {"id": "a2", "code": "DES-002", "title": "Single card", "summary": "One card."},
        {
            "id": "a3",
            "code": "DES-003",
            "title": "Clear panels",
            "summary": "Like an app of the system.",
            "visual_language": visual(APPLE_DIRECTION, system),
        },
    ]
    package = {
        "alternatives": alternatives,
        "critiques": [],
        "recommended_alternative_id": "a2",
        "owner_selected_alternative_id": None,
        "prototype": None,
    }
    identifiers = {item["code"]: item["id"] for item in alternatives}
    return design_state.DesignState(
        project_id="p",
        project_name="Tip",
        stage="DESIGN",
        version={"id": "v", "version_number": 3, "content_hash": "h", "package": package},
        capabilities=design_api.Capabilities(True, True, True, "model"),
        documents={identifiers[code]: {"html": "<p>drawn</p>"} for code in documents},
    )


def shown(tmp_path: Path, state: design_state.DesignState, language: str) -> list[str]:
    bundle = terminal(tmp_path, transport=UrlTransport(), language=language, variables=WIDE)
    context = command_context(bundle.environment, language=language)
    design_state.show_alternatives(context, state)
    return bundle.output.splitlines()


def drawn_codes(session, requests) -> list[str]:
    names = {session.alternative(code): code for code in CODES}
    return [names[json.loads(item.body)["alternative_id"]] for item in requests]


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_lists_the_three_alternatives_and_names_the_design_system_once(
    tmp_path: Path, language: str
) -> None:
    lines = shown(tmp_path, three_state(), language)

    headings = [line for line in lines if line.startswith("DES-")]
    assert [line.split(" · ")[0] for line in headings] == list(CODES)
    assert lines.count(SYSTEM_LINES[language]) == 1
    direction = lines.index(DIRECTION_LINES[language])
    assert lines[direction + 1] == SYSTEM_LINES[language]
    assert lines.index(next(line for line in lines if line.startswith("DES-003"))) < direction
    assert APPLE not in "\n".join(lines)


@pytest.mark.parametrize("system", [ABSENT, None, "", "material", 42])
def test_without_a_known_design_system_no_line_is_printed(tmp_path: Path, system: object) -> None:
    lines = shown(tmp_path, three_state(system), "en")

    kept = system if system == "material" else None
    assert DIRECTION_LINES["en"] in lines
    assert not any("Design system" in line for line in lines)
    assert three_state(system).alternatives[2].design_system == kept


def test_the_three_codes_are_found_offered_and_drawn_together() -> None:
    state = three_state(documents=("DES-001",))
    third = state.alternatives[2]

    assert [item.code for item in state.alternatives] == list(CODES)
    assert third.design_system == APPLE
    assert state.find("DES-003") == state.find("des-003") == state.find("3") == third
    assert state.find("4") is None
    assert [item.code for item in state.missing_mockups()] == ["DES-002", "DES-003"]
    assert [item.code for item in three_state().choosable()] == list(CODES)
    assert design_generate.pair(state.alternatives) == state.alternatives


@pytest.mark.parametrize("language", ["en", "it"])
def test_choose_names_the_design_system_of_the_chosen_alternative(
    tmp_path: Path, language: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(design_choice, "mockup_result", lambda *items: {"package": {}})
    monkeypatch.setattr(design_choice, "apply_package", lambda *items: {"version_number": 4})
    monkeypatch.setattr(review, "review_after", lambda *items, **values: 0)
    state = three_state()
    bundle = terminal(tmp_path, transport=UrlTransport(), language=language, variables=WIDE)
    context = command_context(bundle.environment, language=language)

    status = design_choice.choose(context, None, None, state, state.alternatives[2], Prices())
    first = design_choice.choose(context, None, None, state, state.alternatives[0], Prices())

    assert status == first == 0
    lines = bundle.output.splitlines()
    assert lines[:2] == [CHOSEN[language], SYSTEM_LINES[language]]
    assert lines[2].startswith(CHOSEN[language].split(" DES-")[0] + " DES-001")
    assert lines.count(SYSTEM_LINES[language]) == 1


def test_every_design_system_has_its_name_in_both_languages() -> None:
    assert dict(directions.SYSTEM_KEYS) == {APPLE: "design.system_apple_hig"}
    for key in directions.SYSTEM_KEYS.values():
        assert known(key)
        assert text(key, "it") == text(key, "en") == "Apple Human Interface Guidelines"
    for identifier in (None, "", "material", "constructor", 42):
        assert directions.system_name(lambda key: key, identifier) is None


@pytest.mark.parametrize("language", ["en", "it"])
def test_why_says_that_a_direction_of_a_design_system_comes_from_the_system(
    tmp_path: Path, language: str
) -> None:
    console, bundle = console_for(tmp_path, language=language)
    system, model = WHY_ORIGINS[language]
    declared = {**APPLE_DIRECTION, "origin": "MODEL", "selected_by": "STUDIO"}

    lines = why_view.direction_lines(console, {**declared, "design_system": APPLE})
    unknown = why_view.direction_lines(console, {**declared, "design_system": "material"})
    plain = why_view.direction_lines(console, declared)

    assert lines[-1] == unknown[-1] == system
    assert plain[-1] == model
    assert lines[:-1] == unknown[:-1] == plain[:-1]
    assert bundle.output == ""


def test_a_design_system_needs_the_directions_of_the_fake_studio() -> None:
    with pytest.raises(ValueError, match="needs the directions"):
        FakeStudio(design_system=True)


def test_the_first_design_with_a_design_system_draws_the_three_mockups(tmp_path: Path) -> None:
    with design_session(tmp_path, directions=True, design_system=True) as session:
        run = session.ut("design", answers=["y", "leave"])
        drawn = drawn_codes(session, session.requests("POST", MOCKUP_JOBS))
        files = sorted(item.name for item in session.previews.iterdir())

    assert run.status == 0, run.errors
    assert "then I have their mockups drawn at the same time" in run.output
    assert "two alternatives" not in run.output
    assert "Ready: mockup of DES-003." in run.output
    assert run.output.splitlines().count(SYSTEM_LINES["en"]) == 1
    assert drawn == list(CODES)
    assert files == ["DES-001.html", "DES-002.html", "DES-003.html", "index.html"]


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_and_choose_take_the_third_code_of_a_studio_with_a_design_system(
    tmp_path: Path, language: str
) -> None:
    with design_session(
        tmp_path, language=language, directions=True, design_system=True
    ) as session:
        propose(session)
        draw(session, *CODES)
        listed = session.ut("design", "show", language=language, variables=WIDE)
        chosen = session.ut("design", "choose", "DES-003", language=language, variables=WIDE)
        design = session.project.current("design")
        third = session.alternative("DES-003")

    assert listed.status == 0, listed.errors
    lines = listed.output.splitlines()
    start = lines.index(text("design.alternatives_heading", language))
    end = lines.index(text("design.distance_heading", language))
    assert [line.split(" · ")[0] for line in lines[start:end] if line.startswith("DES-")] == list(
        CODES
    )
    direction = lines.index(DIRECTION_LINES[language], start, end)
    assert lines[direction + 1] == SYSTEM_LINES[language]
    assert lines.count(SYSTEM_LINES[language]) == 1
    pairs = [line.split(":")[0] for line in lines[end:] if line.count("DES-") == 2]
    assert pairs == ["DES-001 · DES-002", "DES-001 · DES-003", "DES-002 · DES-003"]
    assert any(line.split()[-3:] == list(CODES) for line in lines[end:])
    assert chosen.status == 0, chosen.errors
    title = SYSTEM_TITLES[language]
    said = text("design.chosen", language, code="DES-003", title=title, version=2)
    answer = chosen.output.splitlines()
    assert answer[answer.index(said) + 1] == SYSTEM_LINES[language]
    assert design is not None
    assert design["package"]["owner_selected_alternative_id"] == third
    visuals = [item["visual_language"] for item in design["package"]["alternatives"]]
    assert [item.get("design_system") for item in visuals] == [None, None, APPLE]
