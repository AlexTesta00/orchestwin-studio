from __future__ import annotations

from random import Random

import pytest

from orchestwin.artifacts.generated_mockup_repair import (
    STYLE_DECLARATION_REMOVED,
    STYLE_REST_REMOVED,
    STYLE_RULE_REMOVED,
    repair_styles,
)
from orchestwin.artifacts.generated_mockup_styles import (
    GeneratedMockupError,
    parse_style_sheet,
)

from .test_generated_mockup_document import HOSTILE_STYLES
from .test_generated_mockup_support import (
    BASE_STYLES,
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN,
    FIXTURES,
    HTML_COMMENT_OPEN,
    TOKEN_NAMES,
    fixture_data,
    fixture_tokens,
)

REPEATING = (
    "repeating-linear-gradient(45deg, var(--vl-color-surface) 0 8px, "
    "var(--vl-color-surface-alt) 8px 16px)"
)
FORBIDDEN_TEXT = ("url(", "\\", "</style", "javascript:", "@import", "expression(", "<")


def comment(text: str) -> str:
    return CSS_COMMENT_OPEN + text + CSS_COMMENT_CLOSE


def repaired(styles: str) -> tuple[str, list[tuple[str, str | None, str]]]:
    text, notes = repair_styles(styles, token_names=TOKEN_NAMES)
    return text, [(note.code, note.screen_code, note.detail) for note in notes]


def accepted(styles: str) -> None:
    parse_style_sheet(styles, token_names=TOKEN_NAMES)


@pytest.mark.parametrize(
    "styles",
    [
        BASE_STYLES,
        "",
        comment(" intestazione ") + "main{margin:0}\r\np{padding:0 " + comment("x") + " auto}",
        "@media (min-width:600px){@supports (display:grid){@layer x{p{margin:0}}}}",
        "@keyframes pulse{from{opacity:0}50%{opacity:.5}to{opacity:1}}",
        "main{--m-gap:calc(var(--vl-gap) * 2)}p{margin:var(--m-gap)}",
        ".hero{background:linear-gradient(160deg, var(--vl-color-primary-soft), "
        "var(--vl-color-background) 60%)}",
    ],
)
def test_a_valid_style_sheet_comes_back_byte_for_byte(styles: str) -> None:
    text, notes = repair_styles(styles, token_names=TOKEN_NAMES)
    assert text is styles
    assert notes == ()


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixture_style_sheets_come_back_byte_for_byte(name: str) -> None:
    styles = str(fixture_data(name)["styles"])
    text, notes = repair_styles(styles, token_names=frozenset(fixture_tokens(name)))
    assert text is styles
    assert notes == ()


@pytest.mark.parametrize(
    ("declaration", "name"),
    [
        ("color:#fff", "color"),
        ("color:rgb(0,0,0)", "color"),
        ("color:hsl(0 0% 0%)", "color"),
        ("color:red", "color"),
        ("background-color:black", "background-color"),
        ("border:1px solid navy", "border"),
        ("box-shadow:0 0 2px gray", "box-shadow"),
        ("color:color-mix(in oklch, var(--vl-color-primary) 50%, var(--vl-color-text))", "color"),
        ("background:url(https://example.org/x.png)", "background"),
        ("background:URL( 'x.png' )", "background"),
        ("background-image:image-set('x.png' 1x)", "background-image"),
        ("width:expression(alert(1))", "width"),
        ("padding:env(safe-area-inset-top)", "padding"),
        ("content:'\\61'", "content"),
        ("content:'</style>'", "content"),
        ("content:'javascript:x'", "content"),
        ("color:attr(data-color)", "color"),
        ("behavior:url(x)", "behavior"),
        ("-moz-binding:x", "-moz-binding"),
        ("font-family:Arial", "font-family"),
        ("font:12px 'Inter'", "font"),
        ("z-index:5000", "z-index"),
        ("--vl-color-primary:var(--vl-color-accent)", "--vl-color-primary"),
        ("--foo:1px", "--foo"),
        ("margin:var(--m-undefined)", "margin"),
        ("margin:var(--vl-unknown-token)", "margin"),
        ("COLOR:var(--vl-color-text)", "COLOR"),
        ("margin_top:0", "margin_top"),
        ("margin", "margin"),
        ("margin:", "margin"),
        ("margin:0 !important!important", "margin"),
        ("background-image:image('x.png')", "background-image"),
        ("@apply px-4", "@apply px-4"),
    ],
)
def test_declarations_that_the_strict_rules_refuse_are_removed(declaration: str, name: str) -> None:
    text, notes = repaired("p{margin:0;" + declaration + ";padding:var(--vl-space)}")
    assert text == "p{margin:0;padding:var(--vl-space)}"
    assert notes == [(STYLE_DECLARATION_REMOVED, None, name)]
    accepted(text)


def test_an_open_parenthesis_holds_the_rest_of_its_block_like_in_a_browser() -> None:
    text, notes = repaired("p{margin:0;margin:calc(1px;padding:var(--vl-space)}main{margin:0}")
    assert text == "p{margin:0;}main{margin:0}"
    assert notes == [(STYLE_DECLARATION_REMOVED, None, "margin")]
    accepted(text)


@pytest.mark.parametrize(
    "selector",
    [
        "html",
        "body",
        "html body .card",
        ":root",
        ":host",
        ".ot-pin",
        ".card .ot-screen",
        "#SCR-001",
        "[data-elm]",
        "[class]",
        "& .card",
        "p:is(html *)",
        "a[href",
    ],
)
def test_rules_whose_selector_the_strict_rules_refuse_are_removed(selector: str) -> None:
    text, notes = repaired(selector + "{margin:0}main{padding:0}")
    assert text == "main{padding:0}"
    assert notes == [(STYLE_RULE_REMOVED, None, selector)]
    accepted(text)


@pytest.mark.parametrize(
    ("rule", "name"),
    [
        ("@import 'x.css';", "@import"),
        ("@IMPORT url(x.css);", "@import"),
        ("@charset 'utf-8';", "@charset"),
        ("@font-face{font-family:x;src:url(x.woff)}", "@font-face"),
        ("@namespace svg url(x);", "@namespace"),
        ("@page{margin:0}", "@page"),
        ("@property --m-x{syntax:'<length>'}", "@property"),
        ("@counter-style x{system:cyclic}", "@counter-style"),
        ("@-webkit-keyframes x{to{opacity:1}}", "@-webkit-keyframes"),
        ("@scope (.card){p{margin:0}}", "@scope"),
        ("@media screen;", "@media"),
        ("@keyframes x;", "@keyframes"),
        ("@media attr(x){p{margin:0}}", "@media"),
    ],
)
def test_at_rules_that_are_not_allowed_are_removed(rule: str, name: str) -> None:
    text, notes = repaired(rule + "main{margin:0}")
    assert text == "main{margin:0}"
    assert notes == [(STYLE_RULE_REMOVED, None, name)]
    accepted(text)


def test_allowed_at_rules_keep_their_content_and_lose_only_what_is_refused() -> None:
    text, notes = repaired(
        "@media (max-width:600px){main{color:red;padding:0}html{margin:0}}"
        "@supports (display:grid){p{display:grid;color:#000}}"
    )
    assert (
        text
        == "@media (max-width:600px){main{padding:0}}@supports (display:grid){p{display:grid;}}"
    )
    assert notes == [
        (STYLE_DECLARATION_REMOVED, None, "color (2)"),
        (STYLE_RULE_REMOVED, None, "html"),
    ]
    accepted(text)


def test_keyframes_keep_their_valid_steps() -> None:
    text, notes = repaired("@keyframes pulse{from{opacity:0}p{opacity:1}to{opacity:1;color:red}}")
    assert text == "@keyframes pulse{from{opacity:0}to{opacity:1;}}"
    assert notes == [
        (STYLE_DECLARATION_REMOVED, None, "color"),
        (STYLE_RULE_REMOVED, None, "p"),
    ]
    accepted(text)


@pytest.mark.parametrize(
    ("declaration", "name"),
    [
        ("background:" + REPEATING, "background"),
        (
            "background-image:repeating-radial-gradient(var(--vl-color-surface), transparent)",
            "background-image",
        ),
        (
            "background:conic-gradient(var(--vl-color-primary), var(--vl-color-accent))",
            "background",
        ),
        (
            "--m-bg:repeating-conic-gradient(var(--vl-color-surface) 0 25%, transparent 0 50%)",
            "--m-bg",
        ),
    ],
)
def test_dated_backgrounds_are_removed_before_the_review_sees_them(
    declaration: str, name: str
) -> None:
    styles = ".hero{" + declaration + ";color:var(--vl-color-text)}"
    accepted(styles)
    text, notes = repaired(styles)
    assert text == ".hero{color:var(--vl-color-text)}"
    assert notes == [(STYLE_DECLARATION_REMOVED, None, name)]


def test_a_plain_gradient_is_not_a_dated_background() -> None:
    styles = ".hero{background:linear-gradient(var(--vl-color-primary), transparent)}"
    assert repair_styles(styles, token_names=TOKEN_NAMES) == (styles, ())


def test_uses_of_a_removed_custom_property_are_removed_too() -> None:
    text, notes = repaired(
        "main{--m-tint:#fff;--m-gap:4px;--m-soft:var(--m-tint)}"
        "p{color:var(--m-soft);margin:var(--m-gap)}"
    )
    assert text == "main{--m-gap:4px;}p{margin:var(--m-gap)}"
    assert notes == [
        (STYLE_DECLARATION_REMOVED, None, "--m-soft"),
        (STYLE_DECLARATION_REMOVED, None, "--m-tint"),
        (STYLE_DECLARATION_REMOVED, None, "color"),
    ]
    accepted(text)


def test_rules_and_at_rules_left_without_content_are_removed() -> None:
    text, notes = repaired("p{color:red}@media (max-width:1px){p{color:red}}main{margin:0}a{}")
    assert text == "main{margin:0}a{}"
    assert notes == [(STYLE_DECLARATION_REMOVED, None, "color (2)")]


def test_comments_leave_with_the_repair_and_never_join_two_tokens() -> None:
    text, notes = repaired(
        comment(" a ") + "p{color:red;" + comment(" b ") + "margin:0 " + comment("") + "auto}"
    )
    assert text == "p{margin:0 auto}"
    assert notes == [(STYLE_DECLARATION_REMOVED, None, "color")]
    joined, notes = repaired("p{color:red}main{mar" + comment("x") + "gin:0;padding:0}")
    assert joined == "main{padding:0}"
    assert (STYLE_DECLARATION_REMOVED, None, "mar/*x*/gin") in notes


@pytest.mark.parametrize(
    ("styles", "kept", "rest"),
    [
        ("main{margin:0}p{margin:0", "main{margin:0}", "p{margin:0"),
        ("main{margin:0}" + CSS_COMMENT_OPEN + " senza fine", "main{margin:0}", "/* senza fine"),
        ("main{margin:0}p{content:'x}", "main{margin:0}", "p{content:'x}"),
        (
            "main{margin:0}@media (min-width:1px){p{margin:0}",
            "main{margin:0}",
            "@media (min-width:1px){p{margin:0}",
        ),
    ],
)
def test_the_rest_of_a_sheet_that_cannot_be_read_is_removed_with_a_note(
    styles: str, kept: str, rest: str
) -> None:
    text, notes = repaired(styles)
    assert text == kept
    assert notes == [(STYLE_REST_REMOVED, None, rest)]
    accepted(text)


@pytest.mark.parametrize(
    ("styles", "kept", "notes"),
    [
        ("color:red;main{margin:0}", "main{margin:0}", [(STYLE_RULE_REMOVED, None, "color:red")]),
        ("}main{margin:0}}", "main{margin:0}", []),
        (";main{margin:0};", "main{margin:0}", []),
        ("main{margin:0}-->", "main{margin:0}", [(STYLE_RULE_REMOVED, None, "-->")]),
        (
            "main{margin:0}" + HTML_COMMENT_OPEN,
            "main{margin:0}",
            [(STYLE_RULE_REMOVED, None, "<!--")],
        ),
        ("main{margin:0}\x00p{margin:0}", "main{margin:0}", [(STYLE_RULE_REMOVED, None, "?p")]),
        (".a{margin:0;.b{margin:0}}", ".a{margin:0;}", [(STYLE_RULE_REMOVED, None, ".b")]),
        (
            "p{@media (min-width:1px){margin:0}}main{margin:0}",
            "main{margin:0}",
            [(STYLE_RULE_REMOVED, None, "@media (min-width:1px)")],
        ),
    ],
)
def test_pieces_that_are_not_rules_are_removed(
    styles: str, kept: str, notes: list[tuple[str, str | None, str]]
) -> None:
    text, found = repaired(styles)
    assert text == kept
    assert found == notes
    accepted(text)


def test_at_rules_nested_deeper_than_the_contract_allows_are_removed() -> None:
    styles = "@media (min-width:1px){" * 17 + "p{margin:0}" + "}" * 17 + "main{margin:0}"
    text, notes = repaired(styles)
    assert text == "main{margin:0}"
    assert notes == [(STYLE_RULE_REMOVED, None, "@media")]
    accepted(text)


MESSY = [
    "p{color:red;margin:0}html{margin:0}",
    "@import 'x';" + comment(" c ") + "main{--m-a:#fff;padding:var(--m-a)}",
    "@media (max-width:1px){p{color:red}}main{margin:0}p{margin:0",
    ".hero{background:" + REPEATING + "}",
    "}color:red;main{margin:0;.b{margin:0}}",
]


@pytest.mark.parametrize("styles", MESSY)
def test_the_repair_of_a_repaired_sheet_changes_nothing(styles: str) -> None:
    text, _notes = repair_styles(styles, token_names=TOKEN_NAMES)
    accepted(text)
    assert repair_styles(text, token_names=TOKEN_NAMES) == (text, ())


def check_safe(styles: str) -> None:
    text, _notes = repair_styles(styles, token_names=TOKEN_NAMES)
    try:
        accepted(text)
    except GeneratedMockupError:
        return
    lowered = text.lower()
    for construct in FORBIDDEN_TEXT:
        assert construct not in lowered


@pytest.mark.parametrize("styles", HOSTILE_STYLES)
def test_hostile_style_sheets_are_either_rejected_or_free_of_everything_forbidden(
    styles: str,
) -> None:
    check_safe(styles)


def test_random_hostile_style_sheets_are_repaired_into_sheets_the_strict_rules_accept() -> None:
    generator = Random(20260928)
    pieces = [*HOSTILE_STYLES, *MESSY, BASE_STYLES, "p{color:var(--vl-color-text)}"]
    for _ in range(300):
        styles = "".join(generator.choice(pieces) for _ in range(generator.randint(1, 6)))
        text, _notes = repair_styles(styles, token_names=TOKEN_NAMES)
        accepted(text)
        assert repair_styles(text, token_names=TOKEN_NAMES) == (text, ())
        for construct in FORBIDDEN_TEXT:
            assert construct not in text.lower()
