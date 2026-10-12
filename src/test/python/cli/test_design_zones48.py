from __future__ import annotations

import re
from pathlib import Path

import pytest

from orchestwin.artifacts.generated_mockup_structure import node_text
from orchestwin.artifacts.generated_mockups import parse_markup
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import design_change, design_state
from orchestwin.models.design_change import TARGETED_CHANGE_TEXTS

from .support.terminal import command_context, run_ut, terminal
from .support.transports import NoNetwork
from .test_api_design import Session, design_session
from .test_design_change import ITERATIONS, chosen
from .test_design_target43 import bodies, evaluations, said

TITLE = {"en": "Tip calculator", "it": "Calcolo mancia"}
MAIN = {"en": "Calculation", "it": "Calcolo"}
FORM = {"en": "Bill and tip", "it": "Conto e mancia"}
AGAIN = {"en": "Split it again", "it": "Dividi di nuovo"}
SCR001 = [
    (0, "ZON-001"),
    (2, "ELM-001"),
    (2, "ELM-002"),
    (2, "ELM-003"),
    (0, "ZON-002"),
    (2, "ELM-004"),
    (2, "ELM-005"),
    (2, "ELM-006"),
    (0, "ZON-003"),
    (2, "ELM-007"),
    (2, "ZON-004"),
    (4, "ELM-008"),
    (4, "ELM-009"),
    (4, "ELM-010"),
    (2, "ZON-005"),
    (4, "ELM-011"),
    (4, "ELM-012"),
    (4, "ELM-013"),
    (4, "ELM-014"),
]
SCR002 = [
    (0, "ELM-015"),
    (0, "ELM-016"),
    (0, "ZON-006"),
    (2, "ELM-017"),
    (2, "ELM-018"),
    (2, "ELM-019"),
    (0, "ELM-020"),
    (0, "ELM-021"),
]
DOCUMENT = (
    '<!doctype html><html lang="en"><body class="ot-mockup">'
    '<section class="ot-screen" id="SCR-001" aria-label="Start">'
    '<header data-ot-zone="ZON-001"><h2>Shop</h2>'
    '<a data-elm="ELM-001" href="#SCR-001">Home</a><a data-elm="ELM-002">Cart</a></header>'
    '<span id="hint">Your basket</span>'
    '<main data-ot-zone="ZON-002" aria-labelledby="hint">'
    '<form data-ot-zone="ZON-003" aria-label="Search the shop">'
    '<input data-elm="ELM-003" placeholder="Bread"><button data-elm="ELM-004">Go</button>'
    "</form>"
    '<fieldset data-ot-zone="ZON-004"><legend>Size</legend>'
    '<p data-elm="ELM-005">Small</p><p data-elm="ELM-006">Large</p></fieldset>'
    '<ul data-ot-zone="ZON-005"><li data-elm="ELM-007">One</li>'
    '<li data-elm="ELM-008">Two</li></ul>'
    '<div data-ot-zone="ZON-006"><svg></svg></div>'
    "</main></section>"
    '<section class="ot-screen" id="SCR-002" aria-label="End">'
    '<p data-elm="ELM-009">Done</p></section></body></html>'
)
INLINE = (
    ('<a href="#SCR-001">a</a><span>Via Padova</span>', "a Via Padova"),
    ("<span>Carrello</span><svg></svg><span>vuoto</span>", "Carrello vuoto"),
    ("Totale: <strong>12</strong>€", "Totale: 12€"),
    ("One<br>two<span hidden>secret</span>", "One two"),
    ("<ul><li>One</li><li>Two</li></ul>", "One Two"),
    ("A<b>B</b>", "AB"),
)


def zoned(session: Session) -> None:
    session.studio.landmarks = True
    chosen(session)


def listed(output: str) -> list[tuple[int, str]]:
    return [
        (len(found[1]), found[2])
        for found in re.finditer(r"^( *)((?:ELM|ZON)-[0-9]{3}) ", output, re.MULTILINE)
    ]


def row(output: str, indent: int, code: str, kind: str, content: str) -> bool:
    pattern = rf"^ {{{indent}}}{code} +{re.escape(kind)} +{re.escape(content)}$"
    return re.search(pattern, output, re.MULTILINE) is not None


def zone_document(session: Session) -> str:
    document = design_api.mockup_document(
        session.client(),
        session.project.id,
        session.alternative("DES-002"),
        source=design_api.APPLIED,
        zones=True,
    )
    assert document is not None
    return str(document["html"])


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_elements_lists_the_zones_and_indents_the_parts_under_the_zone_that_holds_them(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        zoned(session)
        run = session.ut("design", "show", "--elements", language=language)
        sent = [item.query for item in session.requests("GET", "/design/mockups/document")]

    zone = said("design.elements_zone_type", language, count=3)
    large = said("design.elements_zone_type", language, count=8)
    assert run.status == 0, run.errors
    assert listed(run.output) == [*SCR001, *SCR002]
    assert row(run.output, 0, "ZON-001", zone, TITLE[language])
    assert row(run.output, 2, "ELM-001", "h1", TITLE[language])
    assert row(run.output, 0, "ZON-003", large, MAIN[language])
    assert row(run.output, 2, "ZON-004", zone, FORM[language])
    assert row(run.output, 4, "ELM-012", "button", AGAIN[language])
    assert "zones=true" in sent[-1]
    assert run.output.endswith(
        said("design.elements_next", language, screen="SCR-001", element="ZON-001") + "\n"
    )


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_change_aimed_at_a_zone_sends_its_code_and_label_and_the_review_looks_at_it(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        zoned(session)
        html = zone_document(session)
        run = session.ut(
            "design",
            "change",
            "Make the bar darker",
            "--screen",
            "SCR-001",
            "--element",
            "zon-001",
            answers=["y"],
            language=language,
        )
        sent = bodies(session)
        reviewed = evaluations(session)

    aimed = said(
        "design.target_zone", language, zone="ZON-001", screen="SCR-001", text=TITLE[language]
    )
    line = TARGETED_CHANGE_TEXTS[language]["element"].format(element="ZON-001", screen="SCR-001")
    assert 'data-ot-zone="ZON-001"' in html
    assert run.status == 0, run.errors
    assert [body["target"] for body in sent] == [
        {"screen_code": "SCR-001", "element_code": "ZON-001", "label": TITLE[language]}
    ]
    assert run.output.index(aimed) < run.output.index(said("costs.confirm", language))
    assert f"- {line}\n" in run.output
    assert [body["scope"] for body in reviewed] == [
        {"screen_code": "SCR-001", "element_code": "ZON-001"}
    ]


def test_several_parts_are_sent_in_the_order_of_the_page_and_reviewed_together(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        zoned(session)
        run = session.ut(
            "design",
            "change",
            "Make them stand out",
            "--screen",
            "SCR-001",
            "--element",
            "ELM-012",
            "--element",
            "ZON-004",
            answers=["y"],
        )
        sent = bodies(session)
        reviewed = evaluations(session)
        [scoped] = session.project.runs

    parts = [
        {"element_code": "ZON-004", "label": FORM["en"]},
        {"element_code": "ELM-012", "label": AGAIN["en"]},
    ]
    listed_parts = ", ".join(
        said("design.screen_item", code=item["element_code"], title=item["label"]) for item in parts
    )
    line = TARGETED_CHANGE_TEXTS["en"]["parts"].format(
        elements="ZON-004 and ELM-012", screen="SCR-001"
    )
    first = scoped["responses"][0]["findings"][0]
    assert run.status == 0, run.errors
    assert [body["target"] for body in sent] == [{"screen_code": "SCR-001", "elements": parts}]
    assert said("design.target_parts", parts=listed_parts, screen="SCR-001") in run.output
    assert f"- {line}\n" in run.output
    assert [body["scope"] for body in reviewed] == [
        {"screen_code": "SCR-001", "element_codes": ["ZON-004", "ELM-012"]}
    ]
    assert (first["anchor_key"], "element_code" in first) == ("SCR-001", False)


@pytest.mark.parametrize(
    ("codes", "key", "values"),
    [
        (["ELM-001", " elm-001 "], "DESIGN_ELEMENT_CODE_REPEATED", {"code": "ELM-001"}),
        (["ZON-002", "ELM-001", "ZON-002"], "DESIGN_ELEMENT_CODE_REPEATED", {"code": "ZON-002"}),
        (
            [f"ELM-{number:03d}" for number in range(1, 10)],
            "DESIGN_ELEMENT_TOO_MANY",
            {"count": 9, "limit": 8},
        ),
        (["ZON-12"], "DESIGN_ELEMENT_CODE_INVALID", {"code": "ZON-12"}),
        (["ELM-0000001"], "DESIGN_ELEMENT_CODE_INVALID", {"code": "ELM-0000001"}),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_repeated_or_too_many_parts_are_refused_before_the_studio_is_asked(
    tmp_path: Path, codes: list[str], key: str, values: dict[str, object], language: str
) -> None:
    elements = [item for code in codes for item in ("--element", code)]
    arguments = ["--lang", language, "design", "change", "Bigger", "--screen", "SCR-001"]
    run = run_ut([*arguments, *elements], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == said(f"design.errors.{key}", language, **values) + "\n"
    assert run.output == ""


def test_a_part_missing_from_the_screen_is_named_and_nothing_is_spent(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        zoned(session)
        run = session.ut(
            "design",
            "change",
            "Bigger",
            "--screen",
            "SCR-002",
            "--element",
            "ELM-017",
            "--element",
            "ZON-001",
        )
        started = session.count("POST", ITERATIONS)

    assert run.status == 2
    assert run.errors.startswith(
        said(
            "design.errors.DESIGN_TARGET_NOT_FOUND.ELEMENT",
            screen="SCR-002",
            element="ZON-001",
            screens="SCR-001 “Tip calculator”, SCR-002 “Split bill”",
        )
    )
    assert started == 0


def test_the_zones_of_the_page_are_read_with_their_label_parts_and_depth() -> None:
    first, second = design_state.mockup_screens(DOCUMENT)
    found = {item.code: item for item in first.elements}

    assert [(item.code, item.kind, item.depth) for item in first.elements] == [
        ("ZON-001", "zone", 0),
        ("ELM-001", "a", 1),
        ("ELM-002", "a", 1),
        ("ZON-002", "zone", 0),
        ("ZON-003", "zone", 1),
        ("ELM-003", "input", 2),
        ("ELM-004", "button", 2),
        ("ZON-004", "zone", 1),
        ("ELM-005", "p", 2),
        ("ELM-006", "p", 2),
        ("ZON-005", "zone", 1),
        ("ELM-007", "li", 2),
        ("ELM-008", "li", 2),
        ("ZON-006", "zone", 1),
    ]
    assert [(code, found[code].text) for code in ("ZON-001", "ZON-002", "ZON-003")] == [
        ("ZON-001", "Shop"),
        ("ZON-002", "Your basket"),
        ("ZON-003", "Search the shop"),
    ]
    assert (found["ZON-004"].text, found["ZON-005"].text) == ("Size", "One Two")
    assert (found["ZON-006"].text, found["ZON-006"].label) == ("", "ZON-006")
    assert found["ZON-002"].holds == tuple(f"ELM-00{number}" for number in range(3, 9))
    assert found["ZON-001"].holds == ("ELM-001", "ELM-002")
    assert found["ZON-003"].zone and not found["ELM-003"].zone
    assert found["ELM-003"].holds == ()
    assert [(item.code, item.depth) for item in second.elements] == [("ELM-009", 0)]


@pytest.mark.parametrize(("markup", "label"), INLINE)
def test_the_texts_inside_a_part_are_kept_apart_like_the_studio_keeps_them(
    markup: str, label: str
) -> None:
    (screen,) = design_state.mockup_screens(
        '<section class="ot-screen" id="SCR-001" aria-label="Cart">'
        f'<div data-elm="ELM-001">{markup}</div><div data-ot-zone="ZON-001">{markup}</div>'
        f'<span id="where">{markup}</span>'
        '<div data-ot-zone="ZON-002" aria-labelledby="where"></div></section>'
    )
    (studio,) = parse_markup(
        f"<div>{markup}</div>", screen_code="SCR-001", screen_codes=("SCR-001",)
    )

    assert node_text(studio) == label
    assert [(item.code, item.label) for item in screen.elements] == [
        ("ELM-001", label),
        ("ZON-001", label),
        ("ZON-002", label),
    ]


def test_a_zone_or_several_parts_make_the_target_and_the_scope_of_the_review(
    tmp_path: Path,
) -> None:
    context = command_context(terminal(tmp_path, transport=NoNetwork()).environment)
    document = {"html": DOCUMENT}
    zone = design_change.target_of(context, document, design_change.Aim("SCR-001", ("ZON-003",)))
    parts = design_change.target_of(
        context, document, design_change.Aim("SCR-001", ("ELM-007", "ZON-001"))
    )
    element = design_change.target_of(context, document, design_change.Aim("SCR-001", ("ELM-004",)))

    assert design_change.aim_of("scr-001", [" zon-003 ", "elm-001"]) == design_change.Aim(
        "SCR-001", ("ZON-003", "ELM-001")
    )
    assert design_change.aim_of("SCR-001", None) == design_change.Aim("SCR-001")
    assert zone == {"screen_code": "SCR-001", "element_code": "ZON-003", "label": "Search the shop"}
    assert parts == {
        "screen_code": "SCR-001",
        "elements": [
            {"element_code": "ZON-001", "label": "Shop"},
            {"element_code": "ELM-007", "label": "One"},
        ],
    }
    assert element["html"] == '<button data-elm="ELM-004">Go</button>'
    assert design_change.scope_of(zone) == {"screen_code": "SCR-001", "element_code": "ZON-003"}
    assert design_change.scope_of(parts) == {
        "screen_code": "SCR-001",
        "element_codes": ["ZON-001", "ELM-007"],
    }
    with pytest.raises(CliError) as missing:
        design_change.target_of(context, document, design_change.Aim("SCR-002", ("ZON-001",)))
    assert (missing.value.code, missing.value.values["element"]) == (
        "DESIGN_TARGET_NOT_FOUND",
        "ZON-001",
    )


def test_the_iteration_body_carries_the_parts_and_the_opinion_only_when_there_are_some() -> None:
    version = {"id": "v", "content_hash": "h"}
    target = {"screen_code": "SCR-001", "elements": [{"element_code": "ZON-001", "label": "A"}]}

    assert design_api.iteration_body(version, "Bigger", (), target, "o-1") == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "request": "Bigger",
        "assertions": [],
        "target": target,
        "opinion_id": "o-1",
    }
    assert "opinion_id" not in design_api.iteration_body(version, "Bigger", (), target)
    assert design_api.opinion_body(version, "Bigger", target, "it-IT") == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "request": "Bigger",
        "target": target,
        "locale": "it-IT",
    }
    assert design_api.opinions_path("p") == "/projects/p/design/opinions"
