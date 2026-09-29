from __future__ import annotations

import json
import re
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.mockup_html import (
    MOCKUP_HTML_FILE,
    PAGE_WIDTH_PIXELS,
    UNDETERMINED_LANGUAGE,
    generated_mockup_html,
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
from orchestwin.artifacts.visual_catalog import (
    RETIRED_VISUAL_VALUES,
    VISUAL_CATALOG_CONTENT_HASH,
    BackgroundTreatment,
    DesignTone,
    FontFamily,
    LayoutArchetype,
    NavigationPattern,
    VisualChoices,
)
from orchestwin.artifacts.visual_language import create_visual_language
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.schema import validate_files
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources

from . import design_fixtures
from .test_design_package_extension import GUEST_LIST_DESIGN, fixture_package

KIND = PrototypeElementKind
INTERACTIVE = frozenset({KIND.TEXT_INPUT, KIND.SELECT, KIND.BUTTON, KIND.LINK})
FIELDS = frozenset({KIND.TEXT_INPUT, KIND.SELECT})
PATTERNS = ("radial-gradient", "repeating-linear-gradient", "background-size", "background-image")


def dashboard_package():
    package = design_fixtures.design_package()
    prototype = replace(package.prototype, design_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID)
    return replace(
        package,
        owner_selected_alternative_id=design_fixtures.ALTERNATIVE_TWO_ID,
        prototype=prototype,
    )


def styled(package, **changes):
    first, second = package.alternatives
    language = second.visual_language
    choices = replace(language.choices, **changes)
    return replace(
        package,
        alternatives=(first, replace(second, visual_language=replace(language, choices=choices))),
    )


def element(ordinal, kind, content, **options):
    if kind in INTERACTIVE:
        options = {
            "accessible_name": content,
            "requirement_ids": (design_fixtures.REQUIREMENT_ID,),
            **options,
        }
    if kind in FIELDS:
        options = {"field_name": f"field_{ordinal}", **options}
    return create_prototype_element(
        element_id=UUID(int=700 + ordinal),
        code=f"ELM-{ordinal:03d}",
        kind=kind,
        content=content,
        **options,
    )


def with_screen(package, *elements, title="Reservation desk overview"):
    prototype = package.prototype
    first = prototype.screens[0]
    screen = create_prototype_screen(
        screen_id=first.id,
        code=first.code,
        title=title,
        state=PrototypeScreenState.DEFAULT,
        elements=elements,
        requirement_ids=first.requirement_ids,
        user_story_ids=first.user_story_ids,
    )
    return replace(
        package,
        prototype=replace(prototype, screens=(screen, prototype.screens[1]), transitions=()),
    )


def entry_section(html):
    return html.split('<section class="screen" id="scr-001"')[1].split("</section>")[0]


def render(package, *elements, title="Reservation desk overview"):
    return entry_section(
        render_mockup_html(with_screen(package, *elements, title=title).to_snapshot())
    )


def single_card():
    return styled(
        dashboard_package(),
        archetype=LayoutArchetype.SINGLE_CARD,
        navigation=NavigationPattern.NONE,
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
    assert (
        '<nav class="stepper" aria-label="Steps"><a href="#scr-001">1. Create reservation</a>'
        '<a href="#scr-002">2. Reservation confirmation</a></nav>'
    ) in html
    assert '<nav class="links" aria-label="Screens"><a href="#scr-001">Create reservation</a>' in (
        html
    )
    assert 'class="frame"' not in html
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


def test_the_folder_file_of_a_generated_mockup_is_its_sandboxed_document():
    package = fixture_package()
    version = design_fixtures.design_version(package=package)
    selected = next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )
    assert package.generated_mockup is not None and selected.visual_language is not None
    expected = mockup_document(
        package.generated_mockup.mockup,
        tokens=dict(selected.visual_language.tokens),
        language="it",
    )

    assert mockup_html(version, language="it") == expected
    assert generated_mockup_html(package, language="it") == expected
    assert mockup_html(version).startswith(f'<!doctype html><html lang="{UNDETERMINED_LANGUAGE}">')
    assert UNDETERMINED_LANGUAGE == "und"
    assert "<script" not in expected.lower()
    assert "shell-" not in expected


def test_a_declarative_mockup_keeps_its_rendering_whatever_the_language():
    version = design_fixtures.design_version()
    expected = render_mockup_html(version.package.to_snapshot())

    assert mockup_html(version) == expected
    assert mockup_html(version, language="it") == expected
    with pytest.raises(ValueError, match="requires a generated mockup"):
        generated_mockup_html(version.package, language="it")


@pytest.mark.parametrize("background", list(BackgroundTreatment))
def test_no_background_draws_a_pattern(background):
    html = render_mockup_html(styled(dashboard_package(), background=background).to_snapshot())

    assert f" bg-{background.value} " in html
    assert [pattern for pattern in PATTERNS if pattern in html] == []
    assert html.count("linear-gradient(") == 1
    assert (
        ".bg-GRADIENT{background:linear-gradient(180deg,var(--vl-color-primary-soft),"
        "var(--vl-color-background) 440px)}"
    ) in html
    retired = ",".join(
        f".bg-{item.value}"
        for item in BackgroundTreatment
        if item in RETIRED_VISUAL_VALUES["background"]
    )
    assert f".bg-TINTED,{retired}{{background:var(--vl-color-surface-alt)}}" in html


def test_the_content_panel_is_as_wide_as_a_product_page_and_centred_when_short():
    html = render_mockup_html(dashboard_package().to_snapshot())

    assert PAGE_WIDTH_PIXELS == 1100
    assert ".shell{--page:1100px;" in html
    assert re.search(r"\.shell\{[^}]*min-height:100vh", html)
    assert re.search(r"\.layout\{[^}]*align-content:center[^}]*max-width:calc\(var\(--page\)", html)
    assert re.search(r"\bmain\{[^}]*background:var\(--vl-color-surface\)", html)
    assert '<div class="layout"><aside class="rail" aria-label="Screens">' in html
    assert "</aside><main><section" in html


def test_the_fields_of_a_form_sit_in_two_columns_only_when_there_are_more_than_three():
    fields = [element(10 + index, KIND.TEXT_INPUT, f"Field {index}") for index in range(4)]
    button = element(20, KIND.BUTTON, "Save")

    three = render(single_card(), *fields[:3], button)
    four = render(single_card(), *fields, button)

    assert '<div class="zone zone-main"><label>Field 0' in three
    assert "two-columns" not in three
    assert '<div class="zone zone-main two-columns"><label>Field 0' in four
    assert four.count("<label>") == 4


def test_lists_are_vertical_with_one_item_for_each_row():
    html = render(
        dashboard_package(),
        element(10, KIND.HEADING, "Recent guests"),
        element(11, KIND.LIST, "1. Mario Rossi 2. Luigi Bianchi 3. Giulia Neri"),
        element(12, KIND.LIST, "Anna Verdi"),
        element(13, KIND.TEXT, "Updated today"),
        element(14, KIND.LIST, "Esempio: 1. Marco 2. Sofia"),
        element(15, KIND.LIST, "1. Only one item, room 2.50 per night"),
    )

    assert (
        '<h2>Recent guests</h2><ul class="list"><li>1. Mario Rossi</li><li>2. Luigi Bianchi</li>'
        "<li>3. Giulia Neri</li><li>Anna Verdi</li></ul><p>Updated today</p>"
        '<ul class="list"><li>Esempio:</li><li>1. Marco</li><li>2. Sofia</li>'
        "<li>1. Only one item, room 2.50 per night</li></ul>"
    ) in html
    assert "<ul><li>" not in html


def test_cards_of_the_same_screen_sit_in_a_grid():
    html = render(
        single_card(),
        element(10, KIND.CARD, "Room 101"),
        element(11, KIND.CARD, "Room 102"),
        element(12, KIND.TEXT, "Two more rooms free tomorrow."),
        element(13, KIND.CARD, "Room 103"),
    )

    assert (
        '<div class="cards"><div class="card">Room 101</div><div class="card">Room 102</div>'
        '</div><p>Two more rooms free tomorrow.</p><div class="cards"><div class="card">'
        "Room 103</div></div>"
    ) in html


def test_a_label_is_never_repeated_as_a_paragraph_before_its_field():
    html = render(
        single_card(),
        element(10, KIND.TEXT, "Importo del conto (€)"),
        element(11, KIND.TEXT_INPUT, "Importo del conto"),
        element(12, KIND.TEXT, "Titolo del libro:"),
        element(13, KIND.TEXT_INPUT, "Titolo", accessible_name="Titolo del libro"),
        element(14, KIND.TEXT, "Inserisci la distanza in chilometri:"),
        element(15, KIND.SELECT, "Chilometri", options=("5", "10")),
        element(16, KIND.TEXT, "Chilometri"),
        element(17, KIND.BUTTON, "Calcola"),
    )

    assert "(€)" not in html and "Titolo del libro:" not in html
    assert '<label>Importo del conto<input type="text" name="field_11">' in html
    assert '<label>Titolo del libro<input type="text" name="field_13">' in html
    assert "<p>Inserisci la distanza in chilometri:</p><label>Chilometri<select" in html
    assert "</label><p>Chilometri</p>" in html


def test_headings_that_repeat_the_screen_title_or_the_product_name_are_not_drawn():
    html = render(
        dashboard_package(),
        element(10, KIND.HEADING, "Reservation  Desk"),
        element(11, KIND.HEADING, "reservation desk overview."),
        element(12, KIND.HEADING, "Today"),
        element(13, KIND.TEXT, "Reservation desk"),
    )

    assert '<h1 class="title">Reservation desk overview</h1>' in html
    assert html.count("<h2>") == 1
    assert "<h2>Today</h2><p>Reservation desk</p>" in html


def test_label_and_value_paragraphs_become_rows_of_a_summary():
    html = render(
        single_card(),
        element(10, KIND.TEXT, "Importo del conto:"),
        element(11, KIND.TEXT, "Esempio: 50,00 €"),
        element(12, KIND.TEXT, "Mancia :"),
        element(13, KIND.TEXT, "7,50 €"),
        element(14, KIND.TEXT, "Totale:"),
        element(15, KIND.TEXT, "Percentuale:"),
        element(16, KIND.TEXT, "15%"),
    )

    assert (
        '<dl class="pairs"><div class="pair"><dt>Importo del conto</dt><dd>Esempio: 50,00 €'
        '</dd></div><div class="pair"><dt>Mancia</dt><dd>7,50 €</dd></div></dl>'
        '<p>Totale:</p><dl class="pairs"><div class="pair"><dt>Percentuale</dt><dd>15%</dd>'
        "</div></dl>"
    ) in html


def test_a_dashboard_tile_carries_the_short_figure_that_follows_it():
    note = "A long paragraph that explains the notes of the day in detail."
    tiles = (
        element(10, KIND.STATUS, "Guests registered"),
        element(11, KIND.TEXT, "Example: 12"),
        element(12, KIND.CARD, "Waiting list"),
        element(13, KIND.TEXT, "Example: 3"),
        element(14, KIND.CARD, "Notes"),
        element(15, KIND.TEXT, note),
    )

    html = render(dashboard_package(), *tiles)
    single = render(single_card(), *tiles)

    assert (
        '<div class="zone zone-tiles"><p class="status status-ok" role="status">'
        '<span class="tile-label">Guests registered</span><span class="figure">Example: 12'
        '</span></p><div class="card"><span class="tile-label">Waiting list</span>'
        '<span class="figure">Example: 3</span></div><div class="card">Notes</div></div>'
    ) in html
    assert f'<div class="zone zone-main"><p>{note}</p></div>' in html
    assert 'class="figure"' not in single
    assert "<p>Example: 12</p>" in single


def test_list_and_detail_sit_side_by_side_only_when_both_sides_have_content():
    package = styled(
        dashboard_package(),
        archetype=LayoutArchetype.LIST_DETAIL,
        navigation=NavigationPattern.TOP_BAR,
    )

    stacked = render(
        package,
        element(10, KIND.LIST, "Loan one"),
        element(11, KIND.LIST, "Loan two"),
        element(12, KIND.BUTTON, "New loan"),
    )
    split = render(
        package,
        element(10, KIND.LIST, "Loan one"),
        element(11, KIND.TEXT, "Select a loan to see it."),
        element(12, KIND.BUTTON, "New loan"),
    )

    assert 'class="split"' not in stacked
    assert stacked.index('<ul class="list">') < stacked.index("New loan")
    assert '<div class="split"><div class="zone zone-aside"><ul class="list">' in split


def test_a_stored_design_with_a_background_no_longer_offered_is_read_rendered_and_exported():
    stored = json.loads(GUEST_LIST_DESIGN.read_text(encoding="utf-8"))
    sources = real_sources()
    version = sources.design
    package = version.package
    selected = next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )

    assert selected.visual_language.choices.background is BackgroundTreatment.STRIPES
    assert selected.visual_language.choices.background in RETIRED_VISUAL_VALUES["background"]
    assert selected.visual_language.catalog_content_hash == VISUAL_CATALOG_CONTENT_HASH
    assert design_package_from_snapshot(stored["package"]).to_snapshot() == stored["package"]
    assert version.content_hash == stored["content_hash"]
    assert snapshot_content_hash(stored["package"]) == stored["content_hash"]
    html = mockup_html(version)
    assert " bg-STRIPES " in html
    assert [pattern for pattern in PATTERNS if pattern in html] == []
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    assert folder.files[MOCKUP_HTML_FILE] == html
    validate_files(folder.files)


@pytest.mark.parametrize(
    ("background", "heading", "tone"),
    [
        (BackgroundTreatment.DOTS, FontFamily.SCRIPT, DesignTone.ARTISANAL),
        (BackgroundTreatment.GRID, FontFamily.MONOSPACE, DesignTone.TECHNICAL),
        (BackgroundTreatment.STRIPES, FontFamily.SCRIPT, DesignTone.WARM),
    ],
)
def test_designs_built_with_values_no_longer_offered_keep_their_hash_and_render(
    background, heading, tone
):
    package = dashboard_package()
    first, second = package.alternatives
    original = second.visual_language
    choices = replace(original.choices, background=background, heading_family=heading, tone=tone)
    language = create_visual_language(
        choices=choices,
        product_name=original.product_name,
        rationale=original.rationale,
        twin_fit=original.twin_fit,
    )
    built = replace(package, alternatives=(first, replace(second, visual_language=language)))
    snapshot = json.loads(json.dumps(built.to_snapshot()))

    loaded = design_package_from_snapshot(snapshot)
    html = mockup_html(design_fixtures.design_version(package=loaded))

    stored_choices = snapshot["alternatives"][1]["visual_language"]["choices"]
    assert VisualChoices.from_snapshot(stored_choices) == choices
    assert loaded == built
    assert loaded.content_hash == built.content_hash == snapshot_content_hash(snapshot)
    assert language.catalog_content_hash == VISUAL_CATALOG_CONTENT_HASH
    assert f" bg-{background.value} " in html
    assert [pattern for pattern in PATTERNS if pattern in html] == []
    assert render_evaluation_document(snapshot).count("<section") == 2
