from __future__ import annotations

import pytest

from orchestwin.artifacts.generated_mockup_review import (
    MockupIssue,
    MockupIssueSeverity,
    MockupReport,
    contrast_floor,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockups import create_generated_mockup
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.artifacts.visual_color import contrast_ratio

from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_CODES,
    BASE_FIRST,
    BASE_SECOND,
    BASE_STYLES,
    DARK_TOKENS,
    FIXTURES,
    HIGH_CONTRAST_TOKENS,
    LIGHT_TOKENS,
    TOKEN_NAMES,
    build,
    fixture_codes,
    fixture_mockup,
    fixture_tokens,
    screen_payloads,
    with_first,
)

ERROR = MockupIssueSeverity.ERROR
WARNING = MockupIssueSeverity.WARNING
BOTH_MODES = pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS], ids=["light", "dark"])
LINK = '<a href="#SCR-002">Invia promemoria</a>'
ROW = "<tr><td>Sara Galli</td><td>Lessico famigliare</td><td>7 ottobre</td></tr>"
RETURN = '<a href="#SCR-001">Torna al registro</a>'
HEADING = "<h1>Prestiti della settimana</h1>"
UNTITLED = BASE_FIRST.replace(HEADING, "<p>Prestiti della settimana</p>")
FULL_TABLE = BASE_FIRST.replace(ROW, ROW * 4)
REPEATING = (
    "repeating-linear-gradient(45deg, var(--vl-color-surface) 0 8px, "
    "var(--vl-color-surface-alt) 8px 16px)"
)
SEVERITIES = [
    (
        "NO_TRANSITION",
        lambda: build(
            BASE_FIRST.replace(LINK, "<p>Invia promemoria</p>"),
            BASE_SECOND.replace(RETURN, "<p>Fine</p>"),
        ),
        ERROR,
    ),
    (
        "UNREACHABLE_SCREEN",
        lambda: build(BASE_FIRST.replace(LINK, "<p>Invia promemoria</p>")),
        ERROR,
    ),
    (
        "SCREEN_TOO_EMPTY",
        lambda: build(
            second='<main data-req="REQ-002"><h1>Fatto</h1><p>Ok.</p>'
            '<a href="#SCR-001">Indietro</a></main>'
        ),
        ERROR,
    ),
    ("PLACEHOLDER_TEXT", lambda: with_first("<p>Lorem ipsum</p>"), ERROR),
    (
        "UNTRACED_SCREEN",
        lambda: build(second=BASE_SECOND.replace(' data-req="REQ-002"', "")),
        ERROR,
    ),
    (
        "UNTRACED_CONTROL",
        lambda: build(
            BASE_FIRST.replace('<main data-req="REQ-001">', "<main>").replace(
                "<h1>", '<h1 data-req="REQ-001">'
            )
        ),
        ERROR,
    ),
    ("DATED_BACKGROUND", lambda: build(styles=".hero{background:" + REPEATING + "}"), ERROR),
    ("TABLE_TOO_SHORT", lambda: build(BASE_FIRST.replace(ROW, "")), ERROR),
    ("TABLE_TOO_SHORT", build, WARNING),
    (
        "SELECT_TOO_SHORT",
        lambda: build(BASE_FIRST.replace("<option>In ritardo</option>", "")),
        WARNING,
    ),
    ("EMPTY_CELL", lambda: build(BASE_FIRST.replace("<td>3 ottobre</td>", "<td></td>")), WARNING),
    (
        "HEADING_LEVEL_SKIPPED",
        lambda: build(second=BASE_SECOND.replace("h2>", "h3>")),
        WARNING,
    ),
    ("HEADING_COUNT", lambda: build(UNTITLED), WARNING),
    ("HEADING_COUNT", lambda: with_first("<h1>Secondo titolo</h1>"), WARNING),
    ("SELF_LINK", lambda: with_first('<a href="#SCR-001">Aggiorna</a>'), WARNING),
    (
        "TABLE_WITHOUT_HEADERS",
        lambda: build(BASE_FIRST.replace('<th scope="col">', "<td>").replace("</th>", "</td>")),
        WARNING,
    ),
    ("UNLABELLED_CONTROL", lambda: with_first('<input name="q" type="search">'), WARNING),
    ("UNNAMED_ACTION", lambda: with_first('<a href="#SCR-002"></a>'), WARNING),
    ("UNKNOWN_REQUIREMENT", lambda: with_first('<p data-req="REQ-099">Nota</p>'), WARNING),
]


def review(mockup=None, *, tokens=LIGHT_TOKENS, codes=BASE_CODES, threshold=4.5) -> MockupReport:
    return review_generated_mockup(
        build() if mockup is None else mockup,
        tokens=tokens,
        requirement_codes=codes,
        text_contrast_threshold=threshold,
    )


def found(report: MockupReport, code: str) -> list[MockupIssue]:
    return [issue for issue in report.issues if issue.code == code]


def with_styles(styles: str, **options: object) -> MockupReport:
    return review(build(styles=BASE_STYLES + styles), **options)


def ratio(tokens: dict[str, str], first: str, second: str) -> float:
    return contrast_ratio(tokens[f"--vl-color-{first}"], tokens[f"--vl-color-{second}"])


def test_baseline_passes_the_review_with_only_the_warning_of_its_short_table() -> None:
    report = review()
    assert report.issues == (
        MockupIssue("TABLE_TOO_SHORT", WARNING, "SCR-001", "table 1 has 3 rows"),
    )
    assert report.is_acceptable is True
    assert report.covered_requirement_codes == ("REQ-001", "REQ-002")
    first, second = report.screens
    assert first.screen_code == "SCR-001"
    assert (first.element_count, first.control_count, first.link_count) == (28, 1, 1)
    assert first.text_length >= 150
    assert first.requirement_codes == ("REQ-001",)
    assert (second.element_count, second.control_count, second.link_count) == (9, 0, 1)
    assert second.requirement_codes == ("REQ-002",)


@pytest.mark.parametrize("name", FIXTURES)
def test_fixtures_pass_the_review_in_their_own_light_and_dark_tokens(name: str) -> None:
    mockup = fixture_mockup(name)
    codes = fixture_codes(name)
    for tokens in (fixture_tokens(name), LIGHT_TOKENS, DARK_TOKENS):
        report = review(mockup, tokens=tokens, codes=codes)
        assert report.issues == (), [issue.to_snapshot() for issue in report.issues]
        assert report.is_acceptable
        assert report.covered_requirement_codes == tuple(sorted(codes))


def test_fixture_summaries_count_elements_controls_links_and_text() -> None:
    report = review(fixture_mockup(FIXTURES[0]), codes=fixture_codes(FIXTURES[0]))
    first = report.screens[0]
    assert first.control_count == 3
    assert first.link_count == 9
    assert first.element_count > 120
    assert first.text_length > 900
    assert [screen.screen_code for screen in report.screens] == ["SCR-001", "SCR-002", "SCR-003"]


def test_screens_that_cannot_be_reached_and_mockups_without_links_are_errors() -> None:
    first = BASE_FIRST.replace(LINK, "<p>Invia promemoria</p>")
    second = BASE_SECOND.replace('<a href="#SCR-001">Torna al registro</a>', "<p>Fine</p>")
    report = review(build(first, second))
    assert [(issue.code, issue.screen_code) for issue in found(report, "NO_TRANSITION")] == [
        ("NO_TRANSITION", None)
    ]
    assert [issue.screen_code for issue in found(report, "UNREACHABLE_SCREEN")] == ["SCR-002"]
    third = BASE_SECOND.replace("REQ-002", "REQ-001")
    report = review(build(extra=[third]), codes=BASE_CODES)
    assert [issue.screen_code for issue in found(report, "UNREACHABLE_SCREEN")] == ["SCR-003"]
    assert not found(report, "NO_TRANSITION")
    assert all(
        issue.severity is ERROR
        for issue in report.issues
        if issue.code in {"UNREACHABLE_SCREEN", "NO_TRANSITION"}
    )
    assert not found(review(), "UNREACHABLE_SCREEN")


def test_links_to_their_own_screen_need_the_current_page_marker() -> None:
    report = review(with_first('<a href="#SCR-001">Aggiorna</a>'))
    assert [issue.screen_code for issue in found(report, "SELF_LINK")] == ["SCR-001"]
    report = review(with_first('<a href="#SCR-001" aria-current="page">Registro</a>'))
    assert not found(report, "SELF_LINK")


def test_unknown_requirement_codes_are_warnings() -> None:
    report = review(with_first('<p data-req="REQ-099 REQ-001">Nota</p>'))
    issues = found(report, "UNKNOWN_REQUIREMENT")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [("SCR-001", WARNING)]
    assert "REQ-099" in issues[0].detail
    assert not found(review(), "UNKNOWN_REQUIREMENT")


def test_controls_and_screens_must_be_traced_to_requirements() -> None:
    untraced = BASE_FIRST.replace('<main data-req="REQ-001">', "<main>").replace(
        "<h1>", '<h1 data-req="REQ-001">'
    )
    report = review(build(untraced))
    assert len(found(report, "UNTRACED_CONTROL")) == 2
    assert not found(report, "UNTRACED_SCREEN")
    traced = untraced.replace(LINK, '<a href="#SCR-002" data-req="REQ-001">Invia</a>').replace(
        "<select ", '<select data-req="REQ-001" '
    )
    assert not found(review(build(traced)), "UNTRACED_CONTROL")
    bare = BASE_SECOND.replace(' data-req="REQ-002"', "")
    report = review(build(second=bare))
    assert [issue.screen_code for issue in found(report, "UNTRACED_SCREEN")] == ["SCR-002"]
    hidden = bare.replace(
        "<p>Puoi tornare", '<p>Nota <span data-req="REQ-002">interna</span>. Puoi tornare'
    )
    assert [
        issue.screen_code for issue in found(review(build(second=hidden)), "UNTRACED_SCREEN")
    ] == ["SCR-002"]


@pytest.mark.parametrize(
    "snippet",
    [
        '<input name="q" type="search">',
        '<input name="q" type="search" placeholder="Cerca">',
        '<select name="x"><option>Uno</option><option>Due</option></select>',
        '<textarea name="t">Nota</textarea>',
        '<meter value="1">1</meter>',
        '<progress value="1" max="3">1</progress>',
        '<label for="i1"></label><input id="i1" name="q">',
        '<input name="q" aria-label=" ">',
        '<p id="e1"></p><input name="q" aria-labelledby="e1">',
    ],
)
def test_form_controls_need_a_label(snippet: str) -> None:
    issues = found(review(with_first(snippet)), "UNLABELLED_CONTROL")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [("SCR-001", WARNING)]


@pytest.mark.parametrize(
    "snippet",
    [
        '<label for="i1">Cerca</label><input id="i1" name="q">',
        '<label>Cerca <input name="q"></label>',
        '<input name="q" aria-label="Cerca">',
        '<p id="e1">Cerca</p><input name="q" aria-labelledby="e1">',
        '<label for="m1">Occupazione</label><meter id="m1" value="1">1</meter>',
    ],
)
def test_labelled_form_controls_pass(snippet: str) -> None:
    assert not found(review(with_first(snippet)), "UNLABELLED_CONTROL")


def test_links_and_buttons_need_a_name() -> None:
    report = review(
        with_first(
            '<a href="#SCR-002"></a><button type="button"><svg viewBox="0 0 1 1" '
            'aria-hidden="true"><path d="M0 0"></path></svg></button>'
        )
    )
    assert len(found(report, "UNNAMED_ACTION")) == 2
    report = review(
        with_first(
            '<a href="#SCR-002" aria-label="Avanti"></a><button type="button" '
            'aria-label="Chiudi"><svg viewBox="0 0 1 1" aria-hidden="true"><path d="M0 0">'
            "</path></svg></button>"
        )
    )
    assert not found(report, "UNNAMED_ACTION")


def test_tables_need_header_cells() -> None:
    table = BASE_FIRST.replace('<th scope="col">', "<td>").replace("</th>", "</td>")
    assert len(found(review(build(table)), "TABLE_WITHOUT_HEADERS")) == 1
    assert not found(review(), "TABLE_WITHOUT_HEADERS")


def test_every_screen_has_exactly_one_main_heading() -> None:
    missing = BASE_FIRST.replace("<h1>Prestiti della settimana</h1>", "<h2>Prestiti</h2>")
    assert [issue.screen_code for issue in found(review(build(missing)), "HEADING_COUNT")] == [
        "SCR-001"
    ]
    double = BASE_FIRST.replace("</main>", "<h1>Secondo titolo</h1></main>")
    assert len(found(review(build(double)), "HEADING_COUNT")) == 1
    assert not found(review(), "HEADING_COUNT")


@pytest.mark.parametrize(
    ("first", "detail"),
    [
        (FULL_TABLE.replace(HEADING, "<p>Prestiti della settimana</p>"), "0 main headings"),
        (FULL_TABLE.replace("</main>", "<h1>Secondo titolo</h1></main>"), "2 main headings"),
    ],
    ids=["missing", "double"],
)
def test_a_wrong_number_of_main_headings_is_a_warning_that_keeps_the_mockup(
    first: str, detail: str
) -> None:
    report = review(build(first))
    assert report.issues == (MockupIssue("HEADING_COUNT", WARNING, "SCR-001", detail),)
    assert report.is_acceptable is True


def test_screens_need_enough_text_and_derived_elements() -> None:
    short = (
        '<main data-req="REQ-002"><h1>Fatto</h1><p>Ok.</p><ul><li>A</li><li>B</li></ul>'
        '<p>C</p><a href="#SCR-001">Indietro</a></main>'
    )
    assert [
        issue.screen_code for issue in found(review(build(second=short)), "SCREEN_TOO_EMPTY")
    ] == ["SCR-002"]
    sparse = (
        '<main data-req="REQ-002"><h1>Fatto</h1><p>'
        + "Il promemoria è stato inviato a tutti i lettori con prestiti in scadenza. " * 4
        + '</p><a href="#SCR-001">Indietro</a></main>'
    )
    assert len(found(review(build(second=sparse)), "SCREEN_TOO_EMPTY")) == 1
    assert not found(review(), "SCREEN_TOO_EMPTY")


def test_tables_below_three_rows_are_errors_and_below_six_rows_warnings() -> None:
    short = BASE_FIRST.replace(ROW, "")
    assert [issue.severity for issue in found(review(build(short)), "TABLE_TOO_SHORT")] == [ERROR]
    assert [issue.severity for issue in found(review(), "TABLE_TOO_SHORT")] == [WARNING]
    assert not found(review(build(BASE_FIRST.replace(ROW, ROW * 4))), "TABLE_TOO_SHORT")
    empty_state = build(short, states=(PrototypeScreenState.EMPTY, PrototypeScreenState.SUCCESS))
    assert not found(review(empty_state), "TABLE_TOO_SHORT")


def test_data_cells_need_text_or_a_control() -> None:
    empty = BASE_FIRST.replace("<td>3 ottobre</td>", "<td> </td>")
    assert len(found(review(build(empty)), "EMPTY_CELL")) == 1
    control = BASE_FIRST.replace(
        "<td>3 ottobre</td>",
        '<td><button type="button" aria-label="Rinnova"><svg viewBox="0 0 1 1" '
        'aria-hidden="true"><path d="M0 0"></path></svg></button></td>',
    )
    assert not found(review(build(control)), "EMPTY_CELL")


@pytest.mark.parametrize(
    ("options", "short"),
    [
        ("<option>Tutti</option>", True),
        ("<option>Tutti</option><option> </option>", True),
        ('<option value="a"></option><option value="b"></option>', True),
        ("<option>Tutti</option><option>In ritardo</option>", False),
        ('<option label="Tutti"></option><option>In ritardo</option>', False),
    ],
)
def test_selects_need_two_options_with_text(options: str, short: bool) -> None:
    markup = BASE_FIRST.replace("<option>Tutti</option><option>In ritardo</option>", options)
    assert bool(found(review(build(markup)), "SELECT_TOO_SHORT")) is short


@pytest.mark.parametrize(
    ("text", "placeholder"),
    [
        ("Lorem ipsum dolor", True),
        ("dolor sit amet", True),
        ("Placeholder text", True),
        ("Testo di esempio", True),
        ("To" + "Do: completare", True),
        ("Data tbd", True),
        ("Codice XXX-123", True),
        ("foo bar", True),
        ("Foo  Bar", True),
        ("todos los días", False),
        ("Taglia xxxl", False),
        ("Foobar", False),
        ("Esempio di testo", False),
        ("tbdx", False),
    ],
)
def test_placeholder_text_is_an_error(text: str, placeholder: bool) -> None:
    report = review(with_first(f"<p>{text}</p>"))
    assert bool(found(report, "PLACEHOLDER_TEXT")) is placeholder
    report = review(with_first(f'<input name="q" aria-label="Cerca" placeholder="{text}">'))
    assert bool(found(report, "PLACEHOLDER_TEXT")) is placeholder


def test_placeholder_titles_are_reported_on_their_screen_and_on_the_mockup() -> None:
    report = review(build(title="Lorem ipsum"))
    assert [issue.screen_code for issue in found(report, "PLACEHOLDER_TEXT")] == [None]
    payload = screen_payloads((BASE_FIRST, BASE_SECOND), titles=("Registro", "Testo di esempio"))
    mockup = create_generated_mockup(
        design_alternative_id=ALTERNATIVE_ID,
        title="Registro",
        styles=BASE_STYLES,
        screens=payload,
        token_names=TOKEN_NAMES,
    )
    issues = found(review(mockup), "PLACEHOLDER_TEXT")
    assert [(issue.screen_code, issue.detail) for issue in issues] == [
        ("SCR-002", "testo di esempio")
    ]


@BOTH_MODES
def test_low_contrast_between_declared_text_and_background_is_an_error(
    tokens: dict[str, str],
) -> None:
    report = with_styles(
        ".chip{color:var(--vl-color-primary-soft);background:var(--vl-color-surface)}",
        tokens=tokens,
    )
    issues = found(report, "LOW_CONTRAST")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, ERROR)]
    assert ".chip" in issues[0].detail
    assert f"{ratio(tokens, 'primary-soft', 'surface'):.2f}" in issues[0].detail
    mixed = with_styles(
        ".chip{color:color-mix(in srgb, var(--vl-color-surface) 90%, var(--vl-color-text));"
        "background-color:var(--vl-color-surface)}",
        tokens=tokens,
    )
    assert len(found(mixed, "LOW_CONTRAST")) == 1


@BOTH_MODES
def test_readable_pairs_translucent_backgrounds_and_keyframes_pass(
    tokens: dict[str, str],
) -> None:
    report = with_styles(
        ".a{color:var(--vl-color-text);background:var(--vl-color-surface)}"
        ".b{color:var(--vl-color-on-primary);background:var(--vl-color-primary)}"
        ".c{color:var(--vl-color-danger);background:var(--vl-color-danger-soft)}"
        ".d{color:var(--vl-color-primary-soft);"
        "background:color-mix(in srgb, var(--vl-color-primary) 20%, transparent)}"
        "@keyframes x{from{color:var(--vl-color-primary-soft);"
        "background:var(--vl-color-surface)}}",
        tokens=tokens,
    )
    assert not found(report, "LOW_CONTRAST")


def test_contrast_threshold_follows_the_mode() -> None:
    styles = ".m{color:var(--vl-color-text-muted);background:var(--vl-color-surface)}"
    light = with_styles(styles, threshold=7.0)
    expected = ratio(LIGHT_TOKENS, "text-muted", "surface") < 7.0
    assert bool(found(light, "LOW_CONTRAST")) is expected
    strict = with_styles(styles, tokens=HIGH_CONTRAST_TOKENS, threshold=7.0)
    assert not found(strict, "LOW_CONTRAST")


@pytest.mark.parametrize(("code", "mockup", "severity"), SEVERITIES)
def test_the_severity_of_each_issue_follows_the_harm_it_does(code, mockup, severity) -> None:
    issues = found(review(mockup()), code)
    assert issues
    assert {issue.severity for issue in issues} == {severity}


def test_the_contrast_floor_depends_on_the_threshold_of_the_mode() -> None:
    assert contrast_floor(4.5) == 3.0
    assert contrast_floor(7.0) == 4.5
    assert contrast_floor(2.0) == 2.0


@pytest.mark.parametrize(
    ("tokens", "threshold", "rule", "code", "severity"),
    [
        (
            LIGHT_TOKENS,
            4.5,
            ".a{color:var(--vl-color-accent);background:var(--vl-color-surface-alt)}",
            "LOW_CONTRAST",
            WARNING,
        ),
        (
            LIGHT_TOKENS,
            4.5,
            ".a{color:var(--vl-color-primary-soft);background:var(--vl-color-surface)}",
            "LOW_CONTRAST",
            ERROR,
        ),
        (LIGHT_TOKENS, 4.5, ".a{color:var(--vl-color-accent)}", "UNREADABLE_TEXT_COLOUR", WARNING),
        (
            LIGHT_TOKENS,
            4.5,
            ".a{color:var(--vl-color-on-primary)}",
            "UNREADABLE_TEXT_COLOUR",
            ERROR,
        ),
        (
            LIGHT_TOKENS,
            7.0,
            ".a{color:var(--vl-color-primary);background:var(--vl-color-background)}",
            "LOW_CONTRAST",
            WARNING,
        ),
        (
            LIGHT_TOKENS,
            7.0,
            ".a{color:var(--vl-color-accent);background:var(--vl-color-surface-alt)}",
            "LOW_CONTRAST",
            ERROR,
        ),
        (
            HIGH_CONTRAST_TOKENS,
            7.0,
            ".a{color:var(--vl-color-border);background:var(--vl-color-surface-alt)}",
            "LOW_CONTRAST",
            WARNING,
        ),
        (
            HIGH_CONTRAST_TOKENS,
            7.0,
            ".a{color:var(--vl-color-primary-soft);background:var(--vl-color-surface)}",
            "LOW_CONTRAST",
            ERROR,
        ),
    ],
)
def test_contrast_below_the_floor_is_an_error_and_above_it_a_warning(
    tokens: dict[str, str], threshold: float, rule: str, code: str, severity: MockupIssueSeverity
) -> None:
    issues = found(with_styles(rule, tokens=tokens, threshold=threshold), code)
    assert [issue.severity for issue in issues] == [severity]


@BOTH_MODES
def test_text_colours_unreadable_on_every_background_are_errors(tokens: dict[str, str]) -> None:
    report = with_styles(".ghost{color:var(--vl-color-primary-soft)}", tokens=tokens)
    issues = found(report, "UNREADABLE_TEXT_COLOUR")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, ERROR)]
    assert ".ghost" in issues[0].detail
    alone = with_styles(".ink{color:var(--vl-color-on-primary)}", tokens=tokens)
    assert len(found(alone, "UNREADABLE_TEXT_COLOUR")) == 1
    with_band = with_styles(
        ".band{background:var(--vl-color-primary);color:var(--vl-color-on-primary)}"
        ".ink{color:var(--vl-color-on-primary)}",
        tokens=tokens,
    )
    assert not found(with_band, "UNREADABLE_TEXT_COLOUR")
    muted = with_styles(
        ".m{color:var(--vl-color-text-muted);background:transparent}", tokens=tokens
    )
    assert not found(muted, "UNREADABLE_TEXT_COLOUR")


@BOTH_MODES
def test_a_text_colour_readable_on_one_candidate_is_accepted(tokens: dict[str, str]) -> None:
    report = with_styles(
        ".button{background:var(--vl-color-primary);color:var(--vl-color-on-primary)}"
        ".note{color:var(--vl-color-text-muted)}"
        ".label{color:var(--vl-color-danger)}",
        tokens=tokens,
    )
    assert not found(report, "UNREADABLE_TEXT_COLOUR")


def weak(tokens: dict[str, str], role: str) -> bool:
    return max(ratio(tokens, role, "background"), ratio(tokens, role, "surface")) < 3.0


@BOTH_MODES
@pytest.mark.parametrize(
    "rule",
    [
        "input{border:1px solid var(--vl-color-border)}",
        "select{border-color:var(--vl-color-border)}",
        ".form textarea{border-bottom:2px solid var(--vl-color-border)}",
        "button.secondary:hover{border:1px solid var(--vl-color-border)}",
        ".field > input[type=search]{border-color:var(--vl-color-border)}",
        "p,textarea{border:1px solid var(--vl-color-border)}",
    ],
)
def test_weak_borders_on_form_controls_are_warnings(tokens: dict[str, str], rule: str) -> None:
    assert weak(tokens, "border")
    issues = found(with_styles(rule, tokens=tokens), "WEAK_CONTROL_BORDER")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, WARNING)]
    selector = rule.split("{", 1)[0]
    assert selector in issues[0].detail
    expected = max(ratio(tokens, "border", "background"), ratio(tokens, "border", "surface"))
    assert f"{expected:.2f}" in issues[0].detail


@BOTH_MODES
@pytest.mark.parametrize(
    "rule",
    [
        "input{border:1px solid var(--vl-color-text-muted)}",
        ".field{border:1px solid var(--vl-color-border)}",
        ".input-like{border:1px solid var(--vl-color-border)}",
        "input{border-color:transparent}",
        "button{border:0}",
        "select{border:1px solid currentColor}",
        "input{outline:1px solid var(--vl-color-border)}",
    ],
)
def test_strong_or_unrelated_borders_are_not_reported(tokens: dict[str, str], rule: str) -> None:
    report = with_styles(rule, tokens=tokens)
    assert not found(report, "WEAK_CONTROL_BORDER")
    assert report.is_acceptable


@pytest.mark.parametrize(
    "declaration",
    [
        "background:repeating-linear-gradient(45deg, var(--vl-color-surface) 0 8px, "
        "var(--vl-color-surface-alt) 8px 16px)",
        "background-image:repeating-radial-gradient(var(--vl-color-surface), "
        "var(--vl-color-surface-alt) 10px)",
        "background:repeating-conic-gradient(var(--vl-color-surface) 0 25%, "
        "var(--vl-color-surface-alt) 0 50%)",
        "background-image:conic-gradient(var(--vl-color-primary), var(--vl-color-accent))",
        "--m-bg:conic-gradient(var(--vl-color-primary), var(--vl-color-accent))",
    ],
)
def test_dated_backgrounds_are_errors(declaration: str) -> None:
    issues = found(with_styles(".hero{" + declaration + "}"), "DATED_BACKGROUND")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, ERROR)]


def test_plain_gradients_are_not_dated_backgrounds() -> None:
    report = with_styles(
        ".hero{background:linear-gradient(160deg, var(--vl-color-primary-soft), "
        "var(--vl-color-background) 60%)}"
        ".spot{background-image:radial-gradient(var(--vl-color-surface), transparent)}"
    )
    assert not found(report, "DATED_BACKGROUND")


def test_skipped_heading_levels_are_warnings() -> None:
    skipped = BASE_SECOND.replace("<h2>Prossimi passi</h2>", "<h3>Prossimi passi</h3>")
    issues = found(review(build(second=skipped)), "HEADING_LEVEL_SKIPPED")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [("SCR-002", WARNING)]
    ordered = BASE_SECOND.replace(
        "<h2>Prossimi passi</h2>", "<h2>Prossimi passi</h2><h3>Oggi</h3><h2>Domani</h2>"
    )
    assert not found(review(build(second=ordered)), "HEADING_LEVEL_SKIPPED")


def test_short_lists_outside_navigation_are_warnings() -> None:
    report = review(with_first("<ul><li>Solo</li></ul>"))
    assert [issue.severity for issue in found(report, "LIST_TOO_SHORT")] == [WARNING]
    report = review(with_first('<nav aria-label="Menu"><ul><li>Solo</li></ul></nav>'))
    assert not found(report, "LIST_TOO_SHORT")


def test_empty_containers_are_warnings_except_for_controls_and_fillers() -> None:
    report = review(with_first('<div class="spacer"></div><p> </p>'))
    assert [issue.severity for issue in found(report, "EMPTY_CONTAINER")] == [WARNING, WARNING]
    report = review(
        with_first(
            '<hr><br><input name="q" aria-label="Cerca"><progress aria-label="Avanzamento">'
            '</progress><meter aria-label="Livello"></meter><textarea name="t" aria-label="Nota">'
            '</textarea><svg viewBox="0 0 1 1" aria-hidden="true"><path d="M0 0"></path></svg>'
        )
    )
    assert not found(report, "EMPTY_CONTAINER")


def test_icons_are_hidden_or_named() -> None:
    icon = '<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>'
    report = review(with_first(f"<p>{icon} Stato</p>"))
    assert [issue.severity for issue in found(report, "DECORATIVE_ICON_EXPOSED")] == [WARNING]
    hidden = icon.replace("<svg ", '<svg aria-hidden="true" ')
    named = icon.replace("<svg ", '<svg role="img" aria-label="Stato" ')
    assert not found(
        review(with_first(f"<p>{hidden} {named} Stato</p>")), "DECORATIVE_ICON_EXPOSED"
    )


@pytest.mark.parametrize("role", ["primary", "accent", "success", "danger"])
def test_strong_backgrounds_without_text_colour_are_warnings(role: str) -> None:
    for property_name in ("background", "background-color"):
        report = with_styles(f".band{{{property_name}:var(--vl-color-{role})}}")
        issues = found(report, "BACKGROUND_WITHOUT_TEXT_COLOUR")
        assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, WARNING)]
    report = with_styles(
        f".band{{background:var(--vl-color-{role});color:var(--vl-color-on-primary)}}"
        f".soft{{background:var(--vl-color-{role}-soft)}}".replace("accent-soft", "surface")
    )
    assert not found(report, "BACKGROUND_WITHOUT_TEXT_COLOUR")


def test_styles_without_a_width_media_query_are_warnings() -> None:
    for styles in ("", "@media (prefers-reduced-motion:reduce){main{margin:0}}"):
        issues = found(review(build(styles=styles)), "NO_RESPONSIVE_RULE")
        assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, WARNING)]
    for styles in (
        "@media (min-width:40em){main{margin:0}}",
        "@media screen and (max-width:600px){main{margin:0}}",
    ):
        assert not found(review(build(styles=styles)), "NO_RESPONSIVE_RULE")


def test_a_mockup_with_only_default_states_is_a_warning() -> None:
    same = build(states=(PrototypeScreenState.DEFAULT, PrototypeScreenState.DEFAULT))
    issues = found(review(same), "SINGLE_STATE")
    assert [(issue.screen_code, issue.severity) for issue in issues] == [(None, WARNING)]
    assert review(same).is_acceptable is True
    assert not found(review(), "SINGLE_STATE")


def test_issues_are_ordered_by_screen_and_code_and_the_review_is_deterministic() -> None:
    first = BASE_FIRST.replace(LINK, '<a href="#SCR-001">Aggiorna</a>').replace(
        "<h1>Prestiti della settimana</h1>", ""
    )
    second = (
        BASE_SECOND.replace(' data-req="REQ-002"', "")
        .replace("<h1>", "<h3>")
        .replace("</h1>", "</h3>")
    )
    mockup = build(first, second, styles=".x{background:var(--vl-color-primary)}")
    report = review(mockup)
    keys = [(issue.screen_code or "", issue.code, issue.detail) for issue in report.issues]
    assert keys == sorted(keys)
    assert report.issues[0].screen_code is None
    assert {issue.screen_code for issue in report.issues} == {None, "SCR-001", "SCR-002"}
    assert report == review(mockup)
    assert report.is_acceptable is False
    snapshot = report.to_snapshot()
    assert snapshot["is_acceptable"] is False
    assert snapshot["issues"][0] == report.issues[0].to_snapshot()
    assert set(snapshot["screens"][0]) == {
        "screen_code",
        "element_count",
        "control_count",
        "link_count",
        "text_length",
        "requirement_codes",
    }
