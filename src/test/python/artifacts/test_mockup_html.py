from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.mockup_html import (
    MOCKUP_HTML_FILE,
    mockup_html,
    render_evaluation_document,
    render_mockup_html,
)
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)
from orchestwin.artifacts.visual_catalog import LayoutArchetype, NavigationPattern

from . import design_fixtures


def dashboard_package():
    package = design_fixtures.design_package()
    prototype = replace(package.prototype, design_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID)
    return replace(
        package,
        owner_selected_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID,
        prototype=prototype,
    )


def test_html_mockup_applies_the_visual_language_and_links_the_screens():
    html = render_mockup_html(dashboard_package().to_snapshot())
    assert html.startswith("<!doctype html>")
    assert "<title>Reservation desk</title>" in html
    assert "--vl-color-primary:#" in html
    assert 'class="shell shell-DASHBOARD nav-SIDE_RAIL header-COMPACT_BAR' in html
    assert '<aside class="rail"' in html
    assert 'id="scr-001"' in html and 'id="scr-002"' in html
    assert '<a class="button" href="#scr-002">Save reservation</a>' in html
    assert 'name="guest_name" required' in html
    assert 'class="status status-ok" role="status">Reservation saved' in html
    assert '<div class="zone zone-tiles">' in html
    assert "<script" not in html


def test_html_mockup_escapes_model_content_and_is_deterministic():
    package = dashboard_package()
    prototype = package.prototype
    first = prototype.screens[0]
    hostile = create_prototype_element(
        element_id=first.elements[0].id,
        code=first.elements[0].code,
        kind=first.elements[0].kind,
        content='<img src=x onerror="alert(1)">',
        accessible_name='"quoted" & <b>',
        requirement_ids=first.elements[0].requirement_ids,
        field_name=first.elements[0].field_name,
        required=first.elements[0].required,
    )
    button = first.elements[1]
    hostile_button = create_prototype_element(
        element_id=button.id,
        code=button.code,
        kind=button.kind,
        content='<img src=x onerror="alert(1)">',
        accessible_name="Save",
        acceptance_criterion_ids=button.acceptance_criterion_ids,
    )
    screen = create_prototype_screen(
        screen_id=first.id,
        code=first.code,
        title="Title <script>",
        state=first.state,
        elements=(hostile, hostile_button),
        requirement_ids=first.requirement_ids,
        user_story_ids=first.user_story_ids,
        acceptance_criterion_ids=first.acceptance_criterion_ids,
    )
    prototype = replace(prototype, screens=(screen, prototype.screens[1]))
    snapshot = replace(package, prototype=prototype).to_snapshot()
    html = render_mockup_html(snapshot)
    assert "<img" not in html
    assert "&lt;img src=x onerror=" in html
    assert '"quoted" &amp; &lt;b&gt;' in html
    assert "Title &lt;script&gt;" in html
    assert "<script" not in html
    assert html == render_mockup_html(snapshot)


def test_html_mockup_falls_back_to_neutral_tokens_and_reports_a_missing_prototype():
    version = design_fixtures.design_version()
    html = mockup_html(version)
    assert "shell-SINGLE_CARD" in html
    assert "--vl-color-background:#" in html
    assert "<title>" in html
    empty = replace(version.package, owner_selected_alternative_id=None, prototype=None)
    text = render_mockup_html(empty.to_snapshot(), language="it")
    assert 'lang="it"' in text
    assert "No declarative prototype was recorded" in text
    assert MOCKUP_HTML_FILE == "design/mockup.html"


def test_guided_steps_render_a_stepper_and_focus_mode_stays_bare():
    package = dashboard_package()
    alternative = package.alternatives[1]
    language = alternative.visual_language
    guided_choices = replace(
        language.choices,
        archetype=LayoutArchetype.GUIDED_STEPS,
        navigation=NavigationPattern.TOP_BAR,
    )
    guided = replace(
        package,
        alternatives=(
            package.alternatives[0],
            replace(alternative, visual_language=replace(language, choices=guided_choices)),
        ),
    )
    html = render_mockup_html(guided.to_snapshot())
    assert '<nav class="stepper" aria-label="Steps">' in html
    assert '<nav class="links" aria-label="Screens">' in html
    assert '<div class="frame">' in html
    focus_choices = replace(
        language.choices, archetype=LayoutArchetype.FOCUS_MODE, navigation=NavigationPattern.NONE
    )
    focus = replace(
        package,
        alternatives=(
            package.alternatives[0],
            replace(alternative, visual_language=replace(language, choices=focus_choices)),
        ),
    )
    bare = render_mockup_html(focus.to_snapshot())
    assert "shell-FOCUS_MODE nav-NONE" in bare
    assert '<nav class="links"' not in bare
    assert '<aside class="rail"' not in bare


def test_evaluation_document_is_semantic_and_labels_every_control():
    html = render_evaluation_document(design_fixtures.design_package().to_snapshot(), language="it")
    assert html.startswith(
        '<!doctype html><html lang="it"><head><meta charset="utf-8">'
        "<title>Reservation flow prototype</title></head><body><header>"
        "<h1>Reservation flow prototype</h1>"
        "<p>Guide the receptionist through one decision at a time.</p></header><main>"
    )
    assert (
        '<section id="scr-001" data-state="DEFAULT" aria-labelledby="scr-001-title">'
        '<h2 id="scr-001-title">Create reservation</h2>'
        '<form id="scr-001-form" aria-labelledby="scr-001-title">'
        '<label for="elm-001">Guest name</label>'
        '<input type="text" id="elm-001" name="guest_name" required aria-required="true">'
        '<button type="button" id="elm-002" data-target="scr-002">Save reservation</button>'
        "</form></section>"
    ) in html
    assert (
        '<section id="scr-002" data-state="SUCCESS" aria-labelledby="scr-002-title">'
        '<h2 id="scr-002-title">Reservation confirmation</h2>'
        '<p id="elm-003" role="status">Reservation saved</p></section></main></body></html>'
    ) in html
    assert "scr-002-form" not in html
    assert 'data-role="visual-language"' not in html
    assert "<style" not in html and "<script" not in html and "class=" not in html


def test_evaluation_document_marks_error_alerts_and_names_every_element_kind():
    package = dashboard_package()
    prototype = package.prototype
    requirements = prototype.screens[0].requirement_ids

    def element(ordinal, kind, content, **options):
        return create_prototype_element(
            element_id=UUID(int=600 + ordinal),
            code=f"ELM-{ordinal:03d}",
            kind=kind,
            content=content,
            **options,
        )

    def control(ordinal, kind, content, name, **options):
        return element(
            ordinal, kind, content, accessible_name=name, requirement_ids=requirements, **options
        )

    back = control(19, PrototypeElementKind.LINK, "Back", "Back")
    error = create_prototype_screen(
        screen_id=UUID(int=650),
        code="SCR-003",
        title="Booking error",
        state=PrototypeScreenState.ERROR,
        elements=(
            element(11, PrototypeElementKind.HEADING, "Check the dates"),
            control(
                12,
                PrototypeElementKind.SELECT,
                "Room type",
                "Room type",
                field_name="room",
                options=("Single", "Double"),
            ),
            control(13, PrototypeElementKind.BUTTON, "Retry", "Retry the booking"),
            control(14, PrototypeElementKind.LINK, "Help", "Help"),
            element(15, PrototypeElementKind.STATUS, "The dates overlap."),
            element(16, PrototypeElementKind.LIST, "Arrival · Departure"),
            element(17, PrototypeElementKind.CARD, "Two nights"),
            element(18, PrototypeElementKind.TEXT, "Fix the dates."),
            back,
        ),
        requirement_ids=requirements,
    )
    leave = create_prototype_transition(
        transition_id=UUID(int=660),
        code="TRN-002",
        source_screen_id=error.id,
        trigger_element_id=back.id,
        target_screen_id=prototype.entry_screen_id,
        outcome="The reservation form opens again.",
    )
    snapshot = replace(
        package,
        prototype=replace(
            prototype,
            screens=(*prototype.screens, error),
            transitions=(*prototype.transitions, leave),
        ),
    ).to_snapshot()
    html = render_evaluation_document(snapshot)
    assert '<html lang="und">' in html
    assert "<title>Reservation desk</title>" in html and "<h1>Reservation desk</h1>" in html
    assert '<p data-role="visual-language">archetype: DASHBOARD; hue_family: EMERALD;' in html
    assert "navigation: SIDE_RAIL" in html
    assert (
        '<section id="scr-003" data-state="ERROR" aria-labelledby="scr-003-title">'
        '<h2 id="scr-003-title">Booking error</h2>'
        '<form id="scr-003-form" aria-labelledby="scr-003-title">'
        '<h3 id="elm-011">Check the dates</h3>'
        '<label for="elm-012">Room type</label><select id="elm-012" name="room">'
        "<option>Single</option><option>Double</option></select>"
        '<button type="button" id="elm-013" aria-label="Retry the booking">Retry</button>'
        '<a id="elm-014" aria-disabled="true">Help</a>'
        '<p id="elm-015" role="alert">The dates overlap.</p>'
        '<ul id="elm-016"><li>Arrival · Departure</li></ul>'
        '<article id="elm-017">Two nights</article>'
        '<p id="elm-018">Fix the dates.</p>'
        '<a id="elm-019" href="#scr-001">Back</a></form></section>'
    ) in html
    assert html == render_evaluation_document(snapshot)


def test_evaluation_document_shortens_and_escapes_model_text():
    package = design_fixtures.design_package()
    prototype = package.prototype
    first = prototype.screens[0]
    field = replace(
        first.elements[0],
        content="Guest <b>name</b> " + "x" * 50,
        accessible_name='Guest "name" & <i>more</i> ' + "y" * 50,
    )
    button = replace(first.elements[1], content="Save <now> " + "z" * 50)
    snapshot = replace(
        package,
        prototype=replace(
            prototype,
            screens=(replace(first, elements=(field, button)), prototype.screens[1]),
        ),
    ).to_snapshot()
    html = render_evaluation_document(snapshot, max_content=20)
    assert "<p>Guide the reception…</p>" in html
    assert '<label for="elm-001">Guest "name" &amp; &lt;i&gt;m…</label>' in html
    assert (
        '<button type="button" id="elm-002" data-target="scr-002" '
        'aria-label="Save reservation">Save &lt;now&gt; zzzzzzzz…</button>'
    ) in html
    assert "<i>" not in html and "<now>" not in html and "<b>" not in html
    full = render_evaluation_document(snapshot)
    assert "z" * 50 + "</button>" in full
    with pytest.raises(ValueError, match="requires a prototype"):
        render_evaluation_document(
            replace(package, owner_selected_alternative_id=None, prototype=None).to_snapshot()
        )
