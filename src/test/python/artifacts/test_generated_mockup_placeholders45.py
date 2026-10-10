from __future__ import annotations

import re

import pytest

from orchestwin.artifacts.generated_mockup_document import PLACEHOLDER_RULES, mockup_document
from orchestwin.artifacts.generated_mockup_repair import ICON_UNKNOWN, PLACEHOLDER_EMPTIED
from orchestwin.artifacts.generated_mockup_review import review_generated_mockup
from orchestwin.artifacts.generated_mockup_structure import derive_elements
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    GeneratedMockupError,
    MarkupElement,
    generated_mockup_from_snapshot,
    is_placeholder,
    parse_markup,
    serialize_markup,
)
from orchestwin.artifacts.visual_icons import (
    FALLBACK_ICON,
    PICTURE_TONES,
    icon_body,
    mockup_resources,
)

from .test_generated_mockup_document import assert_safe, style_of
from .test_generated_mockup_repair import (
    RANDOM_CODES,
    built,
    notes,
    repair,
    safe_markup,
    with_snippet,
)
from .test_generated_mockup_support import (
    BASE_CODES,
    BASE_FIRST,
    BASE_SECOND,
    LIGHT_TOKENS,
    TOKEN_NAMES,
    build,
    with_first,
)
from .test_generated_mockups import TreeFactory, merge

SCREEN_CODES = frozenset({"SCR-001", "SCR-002"})
NAMES = ("search", "check", "x", "star", "package", "image")
SEEDS = range(60)
FLAT_PICTURE = '<rect width="400" height="300" style="fill:color-mix(in srgb, '
DRESSED_FIRST = BASE_FIRST.replace(
    '<a href="#SCR-002">Invia promemoria</a>',
    '<a href="#SCR-002"><svg data-icon="send" aria-hidden="true"></svg>Invia promemoria</a>',
).replace(
    "</main>",
    '<svg data-picture="book-open" data-tone="accent" role="img" aria-label="Copertina"></svg>'
    "</main>",
)
DRESSED_SECOND = BASE_SECOND.replace(
    "<h1>Promemoria inviato</h1>",
    '<h1><svg data-icon="check-circle-2" aria-hidden="true"></svg>Promemoria inviato</h1>',
)
HOSTILE_PLACEHOLDERS = [
    '<svg data-icon="search" onload="alert(1)"><script>alert(1)</script></svg>',
    '<svg data-picture="javascript:alert(1)" data-tone="</style>"></svg>',
    '<svg data-icon="../../etc/passwd" style="background:url(https://example.org/x)"></svg>',
    '<svg data-picture="image" data-tone="primary;stroke:url(#x)">'
    "<foreignObject><p>x</p></foreignObject></svg>",
    '<svg data-icon="x" data-icon="search" aria-hidden="true"></svg>',
    "<svg data-icon='search'><use href='#x'></use>",
    '<svg data-picture="image" data-tone="accent" id="ot-pic-1" class="ot-picture"></svg>',
    '<svg data-icon="search" xlink:href="javascript:x"></svg>',
    '<svg data-icon="search"><svg data-picture="image"><script>x</script></svg></svg>',
]


class PlaceholderFactory(TreeFactory):
    def icon(self) -> MarkupElement:
        roll = self.random.random()
        if roll < 0.4:
            name = self.random.choice(NAMES)
            return self.element("svg", (), ("aria-hidden", "true"), ("data-icon", name))
        if roll < 0.8:
            extra = [("data-picture", self.random.choice(NAMES)), ("role", "img")]
            if self.random.random() < 0.5:
                extra.append(("data-tone", self.random.choice(PICTURE_TONES)))
            return self.element("svg", (), *extra)
        return super().icon()


def described(mockup: GeneratedMockup) -> list[tuple[object, ...]]:
    return [
        (
            element.code,
            element.screen_code,
            element.path,
            element.node_name,
            element.kind,
            element.content,
            element.accessible_name,
            element.target_screen,
        )
        for element in derive_elements(mockup)
    ]


def test_only_an_svg_with_an_icon_or_a_picture_is_a_placeholder() -> None:
    assert is_placeholder(MarkupElement("svg", (("data-icon", "search"),), ()))
    assert is_placeholder(
        MarkupElement("svg", (("data-picture", "image"), ("data-tone", "accent")), ())
    )
    assert not is_placeholder(MarkupElement("svg", (("viewbox", "0 0 1 1"),), ()))
    assert not is_placeholder(MarkupElement("span", (("data-icon", "search"),), ()))


def test_placeholders_are_neither_derived_elements_nor_controls() -> None:
    plain = build()
    dressed = build(DRESSED_FIRST, DRESSED_SECOND)
    plain_report = review_generated_mockup(plain, tokens=LIGHT_TOKENS, requirement_codes=BASE_CODES)
    report = review_generated_mockup(dressed, tokens=LIGHT_TOKENS, requirement_codes=BASE_CODES)

    assert described(dressed) == described(plain)
    assert all(element.node_name != "svg" for element in derive_elements(dressed))
    assert [screen.control_count for screen in report.screens] == [
        screen.control_count for screen in plain_report.screens
    ]


def test_a_labelled_picture_and_a_hidden_icon_are_not_exposed_decorations() -> None:
    dressed = build(DRESSED_FIRST, DRESSED_SECOND)
    report = review_generated_mockup(dressed, tokens=LIGHT_TOKENS, requirement_codes=BASE_CODES)
    exposed = review_generated_mockup(
        with_first('<svg data-icon="star"></svg>'),
        tokens=LIGHT_TOKENS,
        requirement_codes=BASE_CODES,
    )

    assert not [issue for issue in report.issues if issue.code == "DECORATIVE_ICON_EXPOSED"]
    assert [
        (issue.screen_code, issue.detail)
        for issue in exposed.issues
        if issue.code == "DECORATIVE_ICON_EXPOSED"
    ] == [("SCR-001", "svg 1")]


def test_a_mockup_with_placeholders_keeps_its_snapshot_and_its_hash() -> None:
    mockup = build(DRESSED_FIRST, DRESSED_SECOND)
    snapshot = mockup.to_snapshot()
    restored = generated_mockup_from_snapshot(snapshot, token_names=TOKEN_NAMES)
    first, second = snapshot["screens"]
    loose = first["markup"].replace('data-icon="send"', "data-icon='send'")

    assert restored == mockup
    assert restored.content_hash == mockup.content_hash
    with pytest.raises(GeneratedMockupError) as error:
        generated_mockup_from_snapshot(
            {**snapshot, "screens": [{**first, "markup": loose}, second]},
            token_names=TOKEN_NAMES,
        )
    assert error.value.code == "SNAPSHOT_NOT_CANONICAL"


def test_every_name_and_tone_given_to_the_model_is_accepted_by_the_validator() -> None:
    resources = mockup_resources()
    icons = "".join(
        f'<svg data-icon="{name}" aria-hidden="true"></svg>' for name in resources["icons"]
    )
    pictures = "".join(
        f'<svg data-picture="image" data-tone="{tone}" role="img" aria-label="Foto"></svg>'
        for tone in resources["tones"]
    )
    nodes = parse_markup(icons + pictures, screen_code="SCR-001", screen_codes=SCREEN_CODES)

    assert len(nodes) == len(resources["icons"]) + len(resources["tones"])
    assert all(isinstance(node, MarkupElement) and is_placeholder(node) for node in nodes)


def test_the_random_trees_hold_both_kinds_of_placeholder() -> None:
    markups = [serialize_markup(merge(PlaceholderFactory(seed).flow(4))) for seed in SEEDS]

    assert sum(markup.count("data-icon=") for markup in markups) >= 10
    assert sum(markup.count("data-picture=") for markup in markups) >= 10
    assert sum(markup.count("data-tone=") for markup in markups) >= 5


@pytest.mark.parametrize("seed", SEEDS)
def test_random_trees_with_placeholders_survive_parsing_repair_and_composition(
    seed: int,
) -> None:
    nodes = merge(PlaceholderFactory(seed).flow(4))
    markup = serialize_markup(nodes)
    wrapped = '<main data-req="REQ-001">' + markup + "</main>"

    assert parse_markup(markup, screen_code="SCR-001", screen_codes=SCREEN_CODES) == nodes
    result = repair(wrapped, codes=RANDOM_CODES)
    assert result.markups[0] == wrapped
    assert result.notes == ()
    document = mockup_document(build(wrapped), tokens=LIGHT_TOKENS, language="it")
    body = document.split('<body class="ot-mockup">', 1)[1]
    placeholders = "data-icon=" in markup or "data-picture=" in markup
    assert_safe(document)
    assert body.count(FLAT_PICTURE) == markup.count("data-picture=")
    assert "gradient" not in body.lower()
    assert body.count("ot-icon") == markup.count("data-icon=")
    assert (PLACEHOLDER_RULES in style_of(document)) is placeholders


@pytest.mark.parametrize("snippet", HOSTILE_PLACEHOLDERS)
def test_hostile_placeholders_are_either_rejected_or_safe(snippet: str) -> None:
    result = with_snippet(snippet)
    try:
        mockup = built(result)
    except GeneratedMockupError:
        return
    for screen in mockup.screens:
        safe_markup(screen.markup)
    document = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it")
    identifiers = re.findall(r' id="([^"]+)"', document)

    assert_safe(document)
    assert "javascript" not in document.lower()
    assert "example.org" not in document
    assert len(identifiers) == len(set(identifiers))


def test_a_repaired_answer_reaches_the_document_with_its_placeholders_filled() -> None:
    result = with_snippet(
        '<svg data-icon="magnifier" viewBox="0 0 24 24"><path d="M0 0"></path></svg>'
    )
    document = mockup_document(built(result), tokens=LIGHT_TOKENS, language="it")

    assert notes(result) == [
        (ICON_UNKNOWN, "SCR-001", "magnifier"),
        (PLACEHOLDER_EMPTIED, "SCR-001", FALLBACK_ICON),
    ]
    assert f'viewBox="0 0 24 24">{icon_body(FALLBACK_ICON)}</svg>' in document
    assert PLACEHOLDER_RULES in style_of(document)
