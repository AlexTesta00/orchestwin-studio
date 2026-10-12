from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.artifacts.colour_names import COLOUR_NAME_KEYS
from orchestwin.cli.flows import design_state
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages.design import COLOUR_WORDS

from .support.terminal import command_context, terminal
from .test_api_design import Session, design_session
from .test_design_change import chosen
from .test_design_target43 import flat, said

TEXT = {
    "code": "TEXT_COLOUR_REPLACED",
    "selector": ".topbar a",
    "property": "color",
    "before": {"value": "var(--vl-color-primary)", "hex": "#0a84ff", "ratio": 2.13, "name": "blue"},
    "after": {"token": "--vl-color-on-primary", "hex": "#FFFFFF", "ratio": 4.04, "name": "white"},
    "background": {"hex": "#FF3B30", "name": "red", "inherited": False},
    "threshold": 4.5,
    "large_text": False,
    "count": 1,
}
BORDER = {
    "code": "CONTROL_BORDER_REPLACED",
    "selector": "input",
    "property": "border-color",
    "before": {"value": "#c7c7cc", "hex": "#C7C7CC", "ratio": 1.52, "name": "grey"},
    "after": {"token": "--vl-color-text-muted", "hex": "#8E8E93", "ratio": 3.17, "name": "grey"},
    "background": {"hex": "#FFFFFF", "name": "white", "inherited": True},
    "threshold": 3.0,
    "large_text": False,
    "count": 3,
}
UNNAMED = {
    **TEXT,
    "before": {**TEXT["before"], "ratio": 4.47, "name": "mauve"},
    "background": {"hex": "#fff8e1"},
}
LINES = {
    "it": (
        "Testo della regola «.topbar a»: blu #0A84FF su rosso #FF3B30, 2,1:1, sotto il minimo di "
        "4,5:1; lo Studio l'ha sostituito con bianco #FFFFFF, 4,0:1.",
        "Bordo dei controlli della regola «input»: grigio #C7C7CC su sfondo ereditato bianco "
        "#FFFFFF, 1,5:1, sotto il minimo di 3:1; sostituito con grigio #8E8E93, 3,1:1 (3 regole).",
        "Testo della regola «.topbar a»: #0A84FF su #FFF8E1, 4,4:1, sotto il minimo di 4,5:1; "
        "lo Studio l'ha sostituito con bianco #FFFFFF, 4,0:1.",
    ),
    "en": (
        "Text of the rule “.topbar a”: blue #0A84FF on red #FF3B30, 2.1:1, below the minimum of "
        "4.5:1; the Studio replaced it with white #FFFFFF, 4.0:1.",
        "Border of the controls of the rule “input”: grey #C7C7CC on the inherited background "
        "white #FFFFFF, 1.5:1, below the minimum of 3:1; replaced with grey #8E8E93, 3.1:1 "
        "(3 rules).",
        "Text of the rule “.topbar a”: #0A84FF on #FFF8E1, 4.4:1, below the minimum of 4.5:1; "
        "the Studio replaced it with white #FFFFFF, 4.0:1.",
    ),
}
LATEST = "/projects/{project_id}/design/mockups"


def corrected(session: Session, *corrections: dict[str, object]) -> None:
    session.studio.corrections = corrections


@pytest.mark.parametrize("language", ["it", "en"])
def test_each_correction_is_one_sentence_with_colours_ratios_and_threshold_in_words(
    tmp_path: Path, language: str
) -> None:
    environment = terminal(tmp_path, transport=UrlTransport()).environment
    context = command_context(environment, language=language)
    lines = [design_state.correction_line(context, item) for item in (TEXT, BORDER, UNNAMED)]

    assert lines == list(LINES[language])
    assert not any("→" in line or "var(--vl" in line or "_REPLACED" in line for line in lines)


def test_the_colour_words_are_the_twelve_keys_of_the_studio() -> None:
    assert tuple(COLOUR_WORDS) == COLOUR_NAME_KEYS


@pytest.mark.parametrize("language", ["it", "en"])
def test_after_a_change_the_corrections_follow_what_changed(tmp_path: Path, language: str) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        corrected(session, TEXT, BORDER)
        run = session.ut(
            "design", "change", "Make the bar red", "--no-review", answers=["y"], language=language
        )

    output = flat(run.output)
    heading = said("design.corrections_heading", language)
    assert run.status == 0, run.errors
    assert flat(f"{heading} - {LINES[language][0]} - {LINES[language][1]}") in output
    assert output.index(said("design.change_list", language)) < output.index(heading)
    assert output.index(heading) < output.index(flat(said("design.rules_none", language)))
    assert run.output.count(heading) == 1


def test_show_lists_the_corrections_of_the_version_that_is_applied_now(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        corrected(session, TEXT)
        chosen(session)
        first = session.ut("design", "show")
        corrected(session, BORDER)
        changed = session.ut(
            "design", "change", "Use a calmer colour", "--no-review", answers=["y"]
        )
        session.studio.fail_next("GET", LATEST, status=404, body={"detail": "Not Found"}, times=5)
        second = session.ut("design", "show")

    heading = said("design.corrections_heading")
    text, border, _ = LINES["en"]
    assert (first.status, changed.status, second.status) == (0, 0, 0)
    assert flat(f"{said('design.chosen_waiting', version=2)} {heading} - {text}") in flat(
        first.output
    )
    assert flat(f"{said('design.chosen_waiting', version=3)} {heading} - {border}") in flat(
        second.output
    )
    assert flat(text) not in flat(second.output)


def test_without_corrections_no_heading_is_written(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        changed = session.ut(
            "design", "change", "Use a calmer colour", "--no-review", answers=["y"]
        )
        shown = session.ut("design", "show")

    assert (changed.status, shown.status) == (0, 0)
    assert said("design.corrections_heading") not in changed.output + shown.output
