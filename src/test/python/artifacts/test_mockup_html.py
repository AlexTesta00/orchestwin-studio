from __future__ import annotations

from dataclasses import replace

from orchestwin.artifacts.mockup_html import MOCKUP_HTML_FILE, mockup_html, render_mockup_html
from orchestwin.artifacts.prototypes import create_prototype_element, create_prototype_screen
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
