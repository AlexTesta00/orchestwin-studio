from __future__ import annotations

import pytest

from orchestwin.artifacts.generated_mockup_styles import (
    MAX_BLOCK_DEPTH,
    MAX_NESTING,
    GeneratedMockupError,
    normalize_styles,
    parse_style_sheet,
    tokenize_styles,
)

from .test_generated_mockup_support import (
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN,
    HTML_COMMENT_OPEN,
    TOKEN_NAMES,
    build,
)


def rejects(styles: str, code: str) -> GeneratedMockupError:
    with pytest.raises(GeneratedMockupError) as error:
        build(styles=styles)
    assert error.value.code == code, error.value.detail
    return error.value


def accepts(styles: str) -> str:
    return build(styles=styles).styles


def comment(text: str) -> str:
    return CSS_COMMENT_OPEN + text + CSS_COMMENT_CLOSE


def test_tokenizer_understands_strings_blocks_functions_and_comments() -> None:
    tokens = tokenize_styles('.a>b{content:"x;}";width:calc(1px + 2%)}' + comment(" c "))
    kinds = [token.kind for token in tokens]
    assert kinds == [
        "delim",
        "ident",
        "delim",
        "ident",
        "{",
        "ident",
        "colon",
        "string",
        "semicolon",
        "ident",
        "colon",
        "function",
        "dimension",
        "whitespace",
        "delim",
        "whitespace",
        "percentage",
        ")",
        "}",
        "comment",
    ]
    assert tokens[7].value == "x;}"
    assert tokens[11].value == "calc"


def test_comments_are_removed_and_never_join_two_tokens() -> None:
    styles = (
        comment(" intestazione ")
        + "main{margin:0}\n"
        + comment("")
        + "p{margin:0 "
        + comment("x")
        + " auto}"
    )
    assert normalize_styles(styles) == "main{margin:0}\np{margin:0  auto}"
    assert accepts(styles) == "main{margin:0}\np{margin:0  auto}"
    rejects("main{mar" + comment("x") + "gin:0}", "STYLES_COMMENT")
    rejects("main{margin:1px" + comment("x") + "2px}", "STYLES_COMMENT")
    rejects("main{margin:0}" + CSS_COMMENT_OPEN + " senza fine", "STYLES_SYNTAX")


@pytest.mark.parametrize(
    "styles",
    [
        "p{content:'\\61'}",
        "p\\{color:var(--vl-color-text)}",
        "p{background:url(x.png)}",
        "p{background:URL(x.png)}",
        "p{background:Url( 'x.png' )}",
        "p{background:url (x.png)}",
        "p{background:URL\t(x.png)}",
        "p{background:u" + CSS_COMMENT_OPEN + "x" + CSS_COMMENT_CLOSE + "rl(x.png)}",
        "p{background:url" + CSS_COMMENT_OPEN + "x" + CSS_COMMENT_CLOSE + "(x.png)}",
        "p{background-image:image-set('x.png' 1x)}",
        "p{background-image:-webkit-image-set('x.png' 1x)}",
        "p{background-image:src('x.png')}",
        "p{width:expression(alert(1))}",
        "p{width:ExPrEsSiOn(alert(1))}",
        "p{color:attr(data-color)}",
        "p{width:attr(data-width px)}",
        "p{padding:env(safe-area-inset-top)}",
        "p::after{content:'</style>'}",
        "p{content:'a<b'}",
        "p{content:'javascript:alert(1)'}",
        "p{content:'JavaScript:x'}",
        "p{behavior:x}",
        "p{-ms-behavior:x}",
        "p{BEHAVIOR:x}",
        "p{margin:0;behavior:none}",
        "@media (min-width:1px){p{behavior:x}}",
        "p{-moz-binding:x}",
        "@import 'x.css';",
        "@IMPORT 'x.css';",
        "@font-face{font-family:x}",
        "@namespace svg x;",
        "@charset 'utf-8';",
        "@document url-prefix(x){p{margin:0}}",
        "@page{margin:0}",
        "@property --m-x{syntax:'<length>'}",
        "@counter-style x{system:cyclic}",
        "@font-feature-values x{@swash{a:1}}",
        comment(" url(x) ") + "p{margin:0}",
    ],
)
def test_forbidden_constructs_are_rejected_anywhere(styles: str) -> None:
    rejects(styles, "STYLES_FORBIDDEN")


def test_nesting_is_bounded_so_hostile_styles_always_end_in_a_mockup_error() -> None:
    assert MAX_NESTING == 32
    assert MAX_BLOCK_DEPTH == 16
    assert accepts("p{width:" + "calc(" * 32 + "1px" + ")" * 32 + "}")
    rejects("p{width:" + "calc(" * 33 + "1px" + ")" * 33 + "}", "STYLES_SYNTAX")
    rejects("p{width:" + "calc(" * 5000 + "1px" + ")" * 5000 + "}", "STYLES_SYNTAX")
    rejects("p" + "[" * 40 + "{margin:0}", "STYLES_SYNTAX")
    nested = "@media (min-width:1px){" * 16 + "p{margin:0}" + "}" * 16
    assert accepts(nested) == nested
    rejects("@media (min-width:1px){" * 17 + "p{margin:0}" + "}" * 17, "STYLES_SYNTAX")
    rejects("@media (min-width:1px){" * 2400 + "p{margin:0}" + "}" * 2400, "STYLES_SYNTAX")


def test_scroll_and_overscroll_behavior_are_ordinary_properties() -> None:
    styles = (
        "main{scroll-behavior:smooth;overscroll-behavior:contain;"
        "overscroll-behavior-y:none;transition-behavior:allow-discrete}"
        "p::after{content:'behavior'}"
    )
    assert accepts(styles) == styles


def test_attr_is_accepted_only_inside_the_content_property() -> None:
    assert accepts("p::after{content:attr(data-req)}") == "p::after{content:attr(data-req)}"
    assert accepts("p::before{content:'- ' counter(item) '.'}")


@pytest.mark.parametrize(
    "styles",
    [
        "@media (min-width:600px){p{margin:0}}",
        "@MEDIA screen and (max-width:600px){p{margin:0}}",
        "@supports (display:grid){p{display:grid}}",
        "@supports selector(:has(a)){p{margin:0}}",
        "@keyframes pulse{from{opacity:0}50%{opacity:.5}to{opacity:1}}",
        "@container card (min-width:400px){p{margin:0}}",
        "@layer base, theme;",
        "@layer base{p{margin:0}}",
        "@layer{p{margin:0}}",
        "@media (min-width:600px){@supports (display:grid){@layer x{p{margin:0}}}}",
        "@media (min-width:600px){@keyframes spin{to{transform:rotate(1turn)}}}",
    ],
)
def test_allowed_at_rules_are_accepted(styles: str) -> None:
    assert accepts(styles) == styles


@pytest.mark.parametrize(
    "styles",
    [
        "@scope (.card){p{margin:0}}",
        "@starting-style{p{opacity:0}}",
        "@-webkit-keyframes x{to{opacity:1}}",
        "@viewport{width:device-width}",
        "@layer x{@page{margin:0}}",
        "@media screen;",
        "@keyframes x;",
        "p{@media (min-width:1px){margin:0}}",
        "@custom-media --narrow (max-width:30em);",
    ],
)
def test_other_at_rules_are_rejected(styles: str) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        build(styles=styles)
    assert error.value.code in {"STYLES_AT_RULE", "STYLES_FORBIDDEN", "STYLES_SYNTAX"}


@pytest.mark.parametrize(
    "selector",
    [
        "html",
        "HTML",
        "body",
        "html body .card",
        ":root",
        ":ROOT",
        ":host",
        ":host(.card)",
        ":host-context(.card)",
        ":scope",
        ".ot-pin",
        ".OT-pin",
        ".card .ot-screen",
        "#SCR-001",
        "#scr-001",
        "[data-elm]",
        "[DATA-ELM]",
        "[data-ot]",
        "[data-ot-x]",
        "[data-entry]",
        "[class~=ot-screen]",
        "[class]",
        "[id=SCR-001]",
        "[id]",
        ":not(body)",
        "p:is(html *)",
        "& .card",
        ".card &",
        ".body",
    ],
)
def test_selectors_never_reach_the_studio_scaffolding(selector: str) -> None:
    rejects(selector + "{margin:0}", "STYLES_SELECTOR")


@pytest.mark.parametrize(
    "selector",
    [
        ".card",
        "main > section",
        ".a:hover",
        "a[aria-current=page]",
        "section:not(.x)",
        ".html-note",
        "li+li::before",
        "tr:nth-child(2n+1) td",
        "input[type='search']",
        "*",
    ],
)
def test_ordinary_selectors_are_accepted(selector: str) -> None:
    assert accepts(selector + "{margin:0}")


def test_custom_properties_are_mockup_properties_and_var_names_known_ones() -> None:
    assert accepts(
        "main{--m-gap:calc(var(--vl-gap) * 2);--m-tint:var(--vl-color-primary-soft)}"
        "p{margin:var(--m-gap);background:var(--m-tint);padding:var(--m-gap, 4px)}"
    )
    assert accepts("p{margin:var(--vl-space)}")
    for styles in (
        "main{--vl-color-primary:var(--vl-color-accent)}",
        "main{--vl-new:1px}",
        "main{--foo:1px}",
        "main{--M-gap:1px}",
        "p{margin:var(--m-undefined)}",
        "p{margin:var(--vl-unknown-token)}",
        "p{margin:var(--foo)}",
        "p{margin:var(gap)}",
        "p{margin:var()}",
    ):
        rejects(styles, "STYLES_CUSTOM_PROPERTY")


def test_unknown_tokens_are_only_checked_when_token_names_are_given() -> None:
    sheet = parse_style_sheet("p{margin:var(--vl-unknown-token)}")
    assert sheet.rules[0].selector == "p"
    with pytest.raises(GeneratedMockupError) as error:
        parse_style_sheet("p{margin:var(--vl-unknown-token)}", token_names=TOKEN_NAMES)
    assert error.value.code == "STYLES_CUSTOM_PROPERTY"


@pytest.mark.parametrize(
    "declaration",
    [
        "color:#fff",
        "color:#FFF",
        "background:#123456",
        "border-color:#12345678",
        "grid-area:#a",
        "color:rgb(0,0,0)",
        "color:RGBA(0,0,0,.5)",
        "color:hsl(0 0% 0%)",
        "color:hsla(0,0%,0%,1)",
        "color:hwb(0 0% 0%)",
        "color:lab(50% 0 0)",
        "color:lch(50% 0 0)",
        "color:oklab(50% 0 0)",
        "color:oklch(50% 0 0)",
        "color:color(srgb 1 0 0)",
        "color:device-cmyk(0 0 0 1)",
        "color:light-dark(var(--vl-color-text), var(--vl-color-background))",
        "color:red",
        "color:Red",
        "background:WHITE",
        "background-color:black",
        "background-image:linear-gradient(red, var(--vl-color-primary))",
        "border:1px solid black",
        "border-top:1px solid navy",
        "outline:2px solid navy",
        "outline-color:teal",
        "box-shadow:0 0 2px gray",
        "text-shadow:0 1px silver",
        "fill:gold",
        "stroke:teal",
        "caret-color:blue",
        "accent-color:green",
        "text-decoration:underline orange",
        "text-decoration-color:orange",
        "column-rule:1px solid tan",
        "scrollbar-color:lime aqua",
        "--m-accent:crimson",
        "-webkit-text-fill-color:red",
        "filter:drop-shadow(0 0 2px black)",
        "mask-image:linear-gradient(black, transparent)",
        "color:Canvas",
        "color:CanvasText",
        "color:color-mix(in oklch, var(--vl-color-primary) 50%, var(--vl-color-text))",
        "color:color-mix(in srgb, red 50%, var(--vl-color-text))",
        "color:color-mix(in srgb, var(--vl-color-primary) 150%, var(--vl-color-text))",
        "color:color-mix(in srgb var(--vl-color-primary), var(--vl-color-text))",
        "color:color-mix(in srgb, var(--vl-space), var(--vl-color-text))",
    ],
)
def test_colours_come_only_from_the_tokens(declaration: str) -> None:
    rejects("p{" + declaration + "}", "STYLES_COLOUR")


@pytest.mark.parametrize(
    "declaration",
    [
        "color:var(--vl-color-text)",
        "background:transparent",
        "color:currentColor",
        "color:currentcolor",
        "color:inherit",
        "border:1px solid var(--vl-color-border)",
        "background:color-mix(in srgb, var(--vl-color-primary) 20%, transparent)",
        "background:color-mix(in srgb, var(--vl-color-primary), var(--vl-color-surface) 30%)",
        "background-image:linear-gradient(90deg, var(--vl-color-primary), var(--vl-color-accent))",
        "background:radial-gradient(circle at top, var(--vl-color-primary-soft), transparent 60%)",
        "box-shadow:var(--vl-shadow)",
        "box-shadow:0 1px 0 var(--vl-color-border), var(--vl-shadow)",
        "transition:background-color .2s ease",
        "grid-template-areas:'red blue'",
        "list-style:none",
        "outline:none",
        "text-decoration:underline",
        "filter:drop-shadow(0 1px 2px var(--vl-color-border))",
    ],
)
def test_token_colours_and_colour_free_values_are_accepted(declaration: str) -> None:
    assert accepts("p{" + declaration + "}")


@pytest.mark.parametrize(
    ("declaration", "valid"),
    [
        ("font-family:var(--vl-font-heading)", True),
        ("font-family:var(--vl-font-body)", True),
        ("font-family:inherit", True),
        ("font-family:monospace", True),
        ("font-family:serif", True),
        ("font-family:sans-serif", True),
        ("font-family:system-ui", True),
        ("font-family:var(--vl-font-body), sans-serif", True),
        ("font:inherit", True),
        ("font:700 1rem/1.4 var(--vl-font-body)", True),
        ("font:italic small-caps 600 var(--vl-size-body)/var(--vl-line-height) serif", True),
        ("font-family:'Comic Sans MS'", False),
        ("font-family:Arial", False),
        ("font-family:cursive", False),
        ("font-family:var(--m-font)", False),
        ("font-family:var(--vl-color-text)", False),
        ("font-family:inherit, serif", False),
        ("font:12px Papyrus", False),
        ("font:12px 'Inter'", False),
        ("font:12px var(--m-font)", False),
    ],
)
def test_font_families_come_only_from_the_tokens_or_generic_names(
    declaration: str, valid: bool
) -> None:
    styles = "main{--m-font:x}p{" + declaration + "}"
    if valid:
        assert accepts(styles)
    else:
        rejects(styles, "STYLES_FONT")


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("999", True),
        ("-5", True),
        ("0", True),
        ("auto", True),
        ("inherit", True),
        ("1000", False),
        ("99999", False),
        ("calc(1)", False),
        ("var(--m-z)", False),
        ("10.5", False),
        ("1e3", False),
    ],
)
def test_z_index_stays_below_the_pins(value: str, valid: bool) -> None:
    styles = "main{--m-z:1}p{position:relative;z-index:" + value + "}"
    if valid:
        assert accepts(styles)
    else:
        rejects(styles, "STYLES_Z_INDEX")


def test_fixed_and_sticky_positions_are_accepted() -> None:
    assert accepts("header{position:fixed;top:0}nav{position:sticky;top:0}")


@pytest.mark.parametrize(
    "styles",
    [
        "p{margin:0",
        "p{margin:0}}",
        "p{margin:calc(1px}",
        "p{margin:(1px}",
        "p[title{margin:0}",
        "p{content:'x}",
        'p{content:"x}',
        "p{content:'a\nb'}",
        "p{margin:0}-->",
        "p{margin:0}" + HTML_COMMENT_OPEN,
        ".a{.b{margin:0}}",
        "p{margin:{0}}",
        "p{margin:0!ie}",
        "p{margin:0 !important!important}",
        "p{margin:;}",
        "p{margin}",
        "p{margin 0}",
        ";p{margin:0}",
        "p;{margin:0}",
        "{margin:0}",
        "p{margin:0}@media (min-width:1px)",
        "@media (min-width:1px{p{margin:0}}",
        "p{margin:0;}}",
        "@keyframes x{p{opacity:0}}",
        "@keyframes x{from{opacity:0}}}",
    ],
)
def test_unbalanced_or_malformed_styles_are_rejected(styles: str) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        build(styles=styles)
    assert error.value.code in {"STYLES_SYNTAX", "STYLES_FORBIDDEN", "STYLES_SELECTOR"}


@pytest.mark.parametrize(
    "styles",
    ["p{COLOR:var(--vl-color-text)}", "p{Margin:0}", "p{margin_top:0}", "p{-webkit-:0}"],
)
def test_property_names_are_lower_case_identifiers(styles: str) -> None:
    rejects(styles, "STYLES_PROPERTY")


@pytest.mark.parametrize("styles", ["p{1margin:0}", "p{-:0}", "p{:0}", "p{'margin':0}"])
def test_declarations_start_with_an_identifier(styles: str) -> None:
    rejects(styles, "STYLES_SYNTAX")


@pytest.mark.parametrize(
    "value",
    [
        "image('x.png')",
        "cross-fade(var(--vl-color-text), transparent)",
        "-webkit-cross-fade(var(--vl-color-text), transparent, 50%)",
        "element(#a)",
        "paint(worklet)",
        "unknown(1)",
    ],
)
def test_functions_outside_the_known_list_are_rejected(value: str) -> None:
    rejects("p{background-image:" + value + "}", "STYLES_FUNCTION")


def test_known_functions_are_accepted() -> None:
    assert accepts(
        "p{width:min(100%, 40rem);height:max(2rem, 10vh);margin:clamp(1rem, 2vw, 3rem);"
        "grid-template-columns:repeat(auto-fit, minmax(12rem, 1fr));"
        "transform:translate(1px, 2px) rotate(3deg) scale(1.1);"
        "transition:opacity .2s cubic-bezier(.2, 0, 0, 1);animation-timing-function:steps(4)}"
    )


@pytest.mark.parametrize("character", ["\x00", "\x0c", "\x01", "\x7f", "\x85", "\ud800"])
def test_control_characters_are_rejected_in_styles(character: str) -> None:
    rejects("p{margin:0}" + character, "STYLES_CONTROL_CHARACTER")


def test_line_breaks_are_normalized_and_important_is_kept() -> None:
    assert accepts("p{margin:0 !important}\r\np{padding:0}\rp{gap:0}") == (
        "p{margin:0 !important}\np{padding:0}\np{gap:0}"
    )


def test_parsed_sheet_exposes_rules_declarations_keyframes_and_media() -> None:
    sheet = parse_style_sheet(
        ".card, .panel{color:var(--vl-color-text);background:var(--vl-color-surface) !important}"
        "@media (max-width:600px){.card{padding:var(--vl-space)}}"
        "@keyframes fade{from{opacity:0}to{opacity:1}}",
        token_names=TOKEN_NAMES,
    )
    assert [rule.selector for rule in sheet.rules] == [".card, .panel", ".card", "from", "to"]
    assert [rule.in_keyframes for rule in sheet.rules] == [False, False, True, True]
    first = sheet.rules[0]
    assert [declaration.name for declaration in first.declarations] == ["color", "background"]
    assert first.declarations[1].important is True
    assert first.declarations[0].important is False
    assert sheet.media_conditions == ("(max-width:600px)",)
