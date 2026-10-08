from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import design_change, design_state, review
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import text
from orchestwin.models.design_change import TARGETED_CHANGE_TEXTS

from .support.fake_studio import SCOPED_FINDINGS
from .support.terminal import command_context, run_ut, terminal
from .support.transports import NoNetwork
from .test_api_design import Session, design_session, draw, propose
from .test_design_change import (
    EVALUATIONS,
    ITERATIONS,
    applied_html,
    chosen,
    reviews,
    version_number,
)

DOCUMENTS = "/projects/{project_id}/design/mockups/document"
LINK = {"en": "Split the bill", "it": "Dividi il conto"}
AMOUNT = {"en": "Amount", "it": "Importo"}
TITLES = {"en": ("Tip calculator", "Split bill"), "it": ("Calcolo mancia", "Conto diviso")}
SCREENS = "SCR-001 “Tip calculator”, SCR-002 “Split bill”"
LONG_TEXT = "long " * 40
LONG_MARKUP = "x " * 1500
DOCUMENT = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Sample</title>'
    "<style>.card{color:red}</style></head><body>"
    '<p data-elm="ELM-900">Outside every screen</p>'
    '<section class="ot-screen" id="SCR-001" aria-label="First  screen" data-entry>'
    '<h1 data-elm="ELM-001">Fish &amp; chips</h1>'
    '<p data-elm="ELM-002">One<br>two<span hidden>secret</span><svg><g></g></svg></p>'
    '<label for="name">Your name</label><input data-elm="ELM-003" id="name" type="text">'
    '<label>Note <textarea data-elm="ELM-004" placeholder="Write"></textarea></label>'
    '<select data-elm="ELM-005"><option>One</option><option selected>Two</option></select>'
    '<button data-elm="ELM-006" aria-label="Close" type="button"><svg></svg></button>'
    '<span id="caption">Total due</span>'
    '<output data-elm="ELM-007" aria-labelledby="caption"></output>'
    '<input data-elm="ELM-008" placeholder="Search" type="search">'
    '<ul><li data-elm="ELM-009">A<b>B</b></li><li data-elm="ELM-009">Again</li></ul>'
    f'<p data-elm="ELM-010">{LONG_TEXT}</p>'
    "</section>"
    '<section class="ot-screen" id="SCR-002" aria-label="Second">'
    '<div data-elm="ELM-011"><a data-elm="ELM-012" href="#SCR-001">Back</a></div>'
    f'<p data-elm="ELM-014">{LONG_MARKUP}</p>'
    '<div data-elm="ELM-015"></div>'
    "</section>"
    '<section id="SCR-003"></section>'
    '<section id="intro"><p data-elm="ELM-013">Not a screen</p></section>'
    "</body></html>"
)
OLD_MOCKUP = (
    '<!doctype html><html lang="en"><body class="ot-mockup">'
    '<section class="ot-screen" id="SCR-001" aria-label="Old screen" data-entry>'
    "<main><h1>Old mockup</h1><p>Drawn before the elements had codes.</p></main>"
    "</section></body></html>"
)


def said(key: str, language: str = "en", **values: object) -> str:
    return text(key, language, **values)


def bodies(session: Session) -> list[dict[str, object]]:
    return [json.loads(item.body) for item in session.requests("POST", ITERATIONS)]


def evaluations(session: Session) -> list[dict[str, object]]:
    return [json.loads(item.body) for item in session.requests("POST", EVALUATIONS)]


def flat(output: str) -> str:
    return " ".join(output.split())


def prefixed(output: str) -> list[str]:
    return re.findall(r"^- (ELM-[0-9]{3}): ", output, re.MULTILINE)


def marked(run: dict[str, Any]) -> list[str]:
    return [
        str(finding["element_code"])
        for response in run["responses"]
        for finding in response["findings"]
        if "element_code" in finding
    ]


def posts(session: Session) -> list[str]:
    return [
        item.path
        for item in session.studio.requests
        if item.method == "POST" and not item.path.endswith("/auth/login")
    ]


def code_of(html: str, content: str) -> str:
    found = re.search(rf'data-elm="(ELM-[0-9]{{3}})"[^>]*>{re.escape(content)}<', html)
    assert found is not None, content
    return found[1]


def field_of(html: str, identifier: str) -> str:
    found = re.search(rf'data-elm="(ELM-[0-9]{{3}})" id="{identifier}"', html)
    assert found is not None, identifier
    return found[1]


def link_markup(html: str, code: str) -> str:
    found = re.search(rf'<a [^>]*data-elm="{code}"[^>]*>[^<]*</a>', html)
    assert found is not None, code
    return found[0]


def screen_markup(html: str, screen: str) -> str:
    found = re.search(rf'<section [^>]*id="{screen}"[^>]*>.*?</section>', html, re.DOTALL)
    assert found is not None, screen
    return found[0]


def row(output: str, code: str, kind: str, content: str) -> bool:
    pattern = rf"^{code} +{re.escape(kind)} +{re.escape(content)}$"
    return re.search(pattern, output, re.MULTILINE) is not None


def listed_codes(output: str) -> list[str]:
    return re.findall(r"^(ELM-[0-9]{3}) ", output, re.MULTILINE)


def chosen_title(session: Session) -> str:
    design = session.project.current("design")
    assert design is not None
    return next(
        str(item["title"])
        for item in design["package"]["alternatives"]
        if item["code"] == "DES-002"
    )


def new_twins(session: Session) -> None:
    session.project.seed_perspective_change("SECURITY_REVIEWER")
    client = session.client()
    client.post(f"{session.base}/user-modeling/context-alignment")
    client.post(f"{session.base}/user-modeling/gate/submit")
    client.post(f"{session.base}/user-modeling/gate/decision", {"action": "APPROVE"})


def states(session: Session) -> dict[str, str]:
    return {str(item["key"]): str(item["state"]) for item in session.project.sections()["sections"]}


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_change_aimed_at_an_element_sends_its_target_and_names_it_before_the_confirmation(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        html = applied_html(session)
        code = code_of(html, LINK[language])
        run = session.ut(
            "design",
            "change",
            "Make it larger",
            "--screen",
            "scr-001",
            "--element",
            code.lower(),
            answers=["y"],
            language=language,
        )
        sent = bodies(session)
        listed = design_api.iterations(session.client(), session.project.id)
        started = reviews(session)
        number = version_number(session)

    target = {
        "screen_code": "SCR-001",
        "element_code": code,
        "label": LINK[language],
        "html": link_markup(html, code),
    }
    aimed = said(
        "design.target_element", language, element=code, screen="SCR-001", text=LINK[language]
    )
    about = said("design.about_change", language, request="Make it larger")
    listed_line = TARGETED_CHANGE_TEXTS[language]["element"].format(element=code, screen="SCR-001")
    assert run.status == 0, run.errors
    assert [body["target"] for body in sent] == [target]
    assert run.output.count(f"{aimed}\n") == 1
    assert f"{aimed}\n{about}\n" in run.output
    assert run.output.index(aimed) < run.output.index(said("costs.confirm", language))
    assert f"{said('design.change_list', language)}\n- {listed_line}\n" in run.output
    assert run.output.count(f"- {listed_line}\n") == 1
    assert [item["target"] for item in listed] == [target]
    assert said("design.review_heading", language, version=3) in run.output
    assert (started, number) == (1, 3)


def test_a_change_aimed_at_a_screen_sends_its_title_and_its_markup(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        html = applied_html(session)
        run = session.ut(
            "design", "change", "Use a calmer colour", "--screen", "SCR-002", answers=["y"]
        )
        sent = bodies(session)
        started = reviews(session)

    markup = screen_markup(html, "SCR-002")
    expected = markup if len(markup) <= 2048 else markup[:2048].rstrip()
    aimed = said("design.target_screen", screen="SCR-002", text="Split bill")
    assert run.status == 0, run.errors
    assert [body["target"] for body in sent] == [
        {"screen_code": "SCR-002", "label": "Split bill", "html": expected}
    ]
    assert run.output.index(aimed) < run.output.index(said("costs.confirm"))
    assert f"- {TARGETED_CHANGE_TEXTS['en']['screen'].format(screen='SCR-002')}\n" in run.output
    assert started == 1


@pytest.mark.parametrize(
    ("arguments", "key", "values", "language"),
    [
        (["change", "Bigger", "--element", "ELM-012"], "DESIGN_ELEMENT_NEEDS_SCREEN", {}, "en"),
        (["change", "Bigger", "--element", "ELM-012"], "DESIGN_ELEMENT_NEEDS_SCREEN", {}, "it"),
        (
            ["change", "Bigger", "--screen", "SCR-2"],
            "DESIGN_SCREEN_CODE_INVALID",
            {"code": "SCR-2"},
            "en",
        ),
        (
            ["change", "Bigger", "--screen", "SCR-0002"],
            "DESIGN_SCREEN_CODE_INVALID",
            {"code": "SCR-0002"},
            "en",
        ),
        (
            ["change", "Bigger", "--screen", "Schermata 2"],
            "DESIGN_SCREEN_CODE_INVALID",
            {"code": "Schermata 2"},
            "it",
        ),
        (
            ["change", "Bigger", "--screen", "SCR-002", "--element", "ELM-12"],
            "DESIGN_ELEMENT_CODE_INVALID",
            {"code": "ELM-12"},
            "en",
        ),
        (
            ["change", "Bigger", "--screen", "SCR-002", "--element", "SCR-012"],
            "DESIGN_ELEMENT_CODE_INVALID",
            {"code": "SCR-012"},
            "it",
        ),
        (
            ["show", "--elements", "SCR-1"],
            "DESIGN_SCREEN_CODE_INVALID",
            {"code": "SCR-1"},
            "en",
        ),
    ],
)
def test_codes_that_are_not_codes_are_refused_before_the_studio_is_asked(
    tmp_path: Path, arguments: list[str], key: str, values: dict[str, str], language: str
) -> None:
    run = run_ut(["--lang", language, "design", *arguments], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == said(f"design.errors.{key}", language, **values) + "\n"
    assert run.output == ""


@pytest.mark.parametrize(
    ("arguments", "key"),
    [
        (["show", "--screen", "SCR-002"], "design.usage_target"),
        (["review", "--no-review"], "design.usage_target"),
        (["--element", "ELM-012"], "design.usage_target"),
        (["choose", "DES-001", "--screen", "SCR-001"], "design.usage_target"),
        (["change", "Bigger", "--elements"], "design.usage_elements"),
        (["--elements", "SCR-002"], "design.usage_elements"),
        (["open", "--elements"], "design.usage_elements"),
    ],
)
def test_the_options_of_a_target_go_only_with_their_action(
    tmp_path: Path, arguments: list[str], key: str
) -> None:
    run = run_ut(["--lang", "en", "design", *arguments], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.errors == said(key) + "\n"


def test_a_screen_or_an_element_missing_from_the_mockup_lists_the_screens_and_spends_nothing(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        link = code_of(applied_html(session), "Split the bill")
        screen = session.ut("design", "change", "Bigger", "--screen", "SCR-009", answers=["y"])
        element = session.ut(
            "design", "change", "Bigger", "--screen", "SCR-002", "--element", link, answers=["y"]
        )
        absent = session.ut(
            "design", "change", "Bigger", "--screen", "SCR-001", "--element", "ELM-999"
        )
        started = (session.count("POST", ITERATIONS), reviews(session))

    assert (screen.status, element.status, absent.status) == (2, 2, 2)
    assert screen.errors == (
        said("design.errors.DESIGN_TARGET_NOT_FOUND", screen="SCR-009", screens=SCREENS) + "\n"
    )
    assert element.errors == (
        said(
            "design.errors.DESIGN_TARGET_NOT_FOUND.ELEMENT",
            screen="SCR-002",
            element=link,
            screens=SCREENS,
        )
        + "\n"
    )
    assert "`ut design show --elements SCR-001`" in absent.errors
    for run in (screen, element, absent):
        assert said("costs.confirm") not in run.output
        assert run.output == ""
    assert started == (0, 0)


def test_without_text_the_target_is_named_before_the_change_is_asked(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        link = code_of(applied_html(session), "Split the bill")
        asked = session.ut(
            "design",
            "change",
            "--screen",
            "SCR-001",
            "--element",
            link,
            answers=["Make it larger", "", "y"],
        )
        wrong = session.ut("design", "change", "--screen", "SCR-001", "--element", "ELM-999")
        sent = bodies(session)

    aimed = said("design.target_element", element=link, screen="SCR-001", text="Split the bill")
    question = said("design.change_ask")
    assert asked.status == 0, asked.errors
    assert asked.output.index(aimed) < asked.output.index(question)
    assert [(body["request"], body["target"]["element_code"]) for body in sent] == [
        ("Make it larger", link)
    ]
    assert wrong.status == 2
    assert wrong.errors.startswith(
        said(
            "design.errors.DESIGN_TARGET_NOT_FOUND.ELEMENT",
            screen="SCR-001",
            element="ELM-999",
            screens=SCREENS,
        )
    )
    assert question not in wrong.output


def test_without_review_the_change_is_estimated_alone_and_the_review_is_left_for_later(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        link = code_of(applied_html(session), "Split the bill")
        aimed = session.ut(
            "design",
            "change",
            "Make it larger",
            "--screen",
            "SCR-001",
            "--element",
            link,
            "--no-review",
            answers=["y"],
        )
        plain = session.ut(
            "design",
            "change",
            "Use a larger title",
            "--rule",
            "Keep the dark theme",
            "--no-review",
            answers=["y"],
        )
        sent = bodies(session)
        started = reviews(session)
        number = version_number(session)

    assert aimed.status == 0, aimed.errors
    assert plain.status == 0, plain.errors
    assert said("design.about_change_alone", request="Make it larger") in aimed.output
    assert said("design.about_change", request="Make it larger") not in aimed.output
    assert "Estimate: 0.85-1.33 USD, about 7 min." in aimed.output
    assert aimed.output.count(said("costs.confirm")) == 1
    assert aimed.output.endswith(said("design.change_review_later", version=3) + "\n")
    assert plain.output.endswith(said("design.change_review_later", version=4) + "\n")
    assert said("design.review_about") not in aimed.output + plain.output
    assert ["target" in body for body in sent] == [True, False]
    assert (started, number) == (0, 4)


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_review_after_a_change_aimed_at_an_element_looks_at_that_element_first(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        code = code_of(applied_html(session), LINK[language])
        run = session.ut(
            "design",
            "change",
            "Make it larger",
            "--screen",
            "SCR-001",
            "--element",
            code,
            answers=["y"],
            language=language,
        )
        sent = evaluations(session)
        [scoped] = session.project.runs
        number = version_number(session)

    finding = said(
        "design.finding_placed",
        language,
        weight=said("design.weight_observation", language),
        summary=SCOPED_FINDINGS[language][0],
        place=said(
            "design.place_element", language, screen=TITLES[language][0], element=LINK[language]
        ),
    )
    firsts = [response["findings"][0] for response in scoped["responses"]]
    assert run.status == 0, run.errors
    assert [body.get("scope") for body in sent] == [
        {"screen_code": "SCR-001", "element_code": code}
    ]
    assert (sent[0]["design_version_id"], scoped["design_version_number"], number) == (
        scoped["design_version_id"],
        3,
        3,
    )
    assert len(firsts) == 2
    assert [item["element_code"] for item in firsts] == [code, code]
    assert flat(run.output).count(flat(f"- {code}: {finding}")) == 2
    assert prefixed(run.output) == marked(scoped)
    assert said("design.comparison_heading", language) not in run.output


def test_the_review_after_a_change_aimed_at_a_screen_looks_at_that_screen_first(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        run = session.ut(
            "design", "change", "Use a calmer colour", "--screen", "SCR-002", answers=["y"]
        )
        sent = evaluations(session)
        [scoped] = session.project.runs

    finding = said(
        "design.finding_placed",
        weight=said("design.weight_observation"),
        summary=SCOPED_FINDINGS["en"][0],
        place=said("design.place_screen", screen=TITLES["en"][1]),
    )
    firsts = [response["findings"][0] for response in scoped["responses"]]
    assert run.status == 0, run.errors
    assert [body.get("scope") for body in sent] == [{"screen_code": "SCR-002"}]
    assert [(item["anchor_key"], "element_code" in item) for item in firsts] == [
        ("SCR-002", False),
        ("SCR-002", False),
    ]
    assert flat(run.output).count(flat(f"- {finding}")) == 2
    assert prefixed(run.output) == marked(scoped)


def test_only_the_review_that_follows_a_targeted_change_is_scoped(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        code = code_of(applied_html(session), LINK["en"])
        aimed = session.ut(
            "design",
            "change",
            "Make it larger",
            "--screen",
            "SCR-001",
            "--element",
            code,
            "--no-review",
            answers=["y"],
        )
        whole = session.ut("design", "review")
        plain = session.ut(
            "design",
            "change",
            "Use a larger title",
            "--rule",
            "Keep the dark theme",
            answers=["y"],
        )
        sent = evaluations(session)
        runs = list(session.project.runs)
        number = version_number(session)

    assert (aimed.status, whole.status, plain.status, number) == (0, 0, 0, 4)
    assert ["scope" in body for body in sent] == [False, False]
    assert [marked(item) for item in runs] == [[], []]
    assert prefixed(whole.output) == prefixed(plain.output) == []
    assert SCOPED_FINDINGS["en"][0] not in flat(whole.output + plain.output)
    assert said("design.comparison_heading") in plain.output


def test_a_scope_that_the_studio_refuses_leaves_the_change_applied_and_names_the_review(
    tmp_path: Path,
) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        code = code_of(applied_html(session), LINK["en"])
        session.studio.fail_next(
            "POST",
            "/projects/{project_id}" + EVALUATIONS,
            status=422,
            body={"detail": {"code": "DESIGN_EVALUATION_SCOPE_INVALID"}},
        )
        run = session.ut(
            "design",
            "change",
            "Make it larger",
            "--screen",
            "SCR-001",
            "--element",
            code,
            answers=["y"],
        )
        sent = evaluations(session)
        number = version_number(session)
        runs = list(session.project.runs)

    assert run.status == 1
    assert [body.get("scope") for body in sent] == [
        {"screen_code": "SCR-001", "element_code": code}
    ]
    assert said("design.change_applied", version=3) in run.output
    assert run.output.endswith(said("design.change_not_reviewed", version=3) + "\n")
    assert run.errors == (
        said("errors.API_FAILURE", http_status=422, code="DESIGN_EVALUATION_SCOPE_INVALID") + "\n"
    )
    assert (number, runs) == (3, [])


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_elements_lists_code_type_and_text_of_every_screen_in_the_order_of_the_document(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language) as session:
        chosen(session)
        html = applied_html(session)
        title = chosen_title(session)
        before = posts(session)
        run = session.ut("design", "show", "--elements", language=language)
        after = posts(session)

    first, second = TITLES[language]
    codes = re.findall(r'data-elm="(ELM-[0-9]{3})"', html)
    heading = said("design.elements_heading", language, code="DES-002", title=title)
    assert run.status == 0, run.errors
    assert f"{heading}\n{'=' * len(heading)}\n" in run.output
    assert listed_codes(run.output) == codes
    assert run.output.index(f"SCR-001 · {first}\n") < run.output.index(f"SCR-002 · {second}\n")
    assert row(run.output, code_of(html, LINK[language]), "a", LINK[language])
    assert row(run.output, field_of(html, "amount"), "input", AMOUNT[language])
    assert row(run.output, field_of(html, "tip"), "select", "10%")
    assert run.output.endswith(
        said("design.elements_next", language, screen="SCR-001", element=codes[0]) + "\n"
    )
    assert after == before


def test_show_elements_of_one_screen_lists_only_that_screen(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        html = applied_html(session)
        run = session.ut("design", "show", "--elements", " scr-002 ")
        unknown = session.ut("design", "show", "--elements", "SCR-007")

    codes = re.findall(r'data-elm="(ELM-[0-9]{3})"', screen_markup(html, "SCR-002"))
    assert run.status == 0, run.errors
    assert codes
    assert listed_codes(run.output) == codes
    assert "SCR-002 · Split bill\n" in run.output
    assert "SCR-001 · " not in run.output
    assert run.output.endswith(
        said("design.elements_next", screen="SCR-002", element=codes[0]) + "\n"
    )
    assert unknown.status == 2
    assert unknown.errors == (
        said("design.errors.DESIGN_TARGET_NOT_FOUND", screen="SCR-007", screens=SCREENS) + "\n"
    )


def test_a_mockup_without_marked_elements_has_none_to_point_at(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        chosen(session)
        session.studio.fail_next("GET", DOCUMENTS, status=200, body={"html": OLD_MOCKUP}, times=20)
        run = session.ut("design", "show", "--elements")
        aimed = session.ut(
            "design", "change", "Bigger", "--screen", "SCR-001", "--element", "ELM-001"
        )
        started = session.count("POST", ITERATIONS)

    assert run.status == 0, run.errors
    assert run.output.endswith(said("design.elements_none") + "\n")
    assert listed_codes(run.output) == []
    assert aimed.status == 2
    assert aimed.errors == (
        said(
            "design.errors.DESIGN_TARGET_NOT_FOUND.ELEMENT",
            screen="SCR-001",
            element="ELM-001",
            screens="SCR-001 “Old screen”",
        )
        + "\n"
    )
    assert started == 0


def test_show_elements_needs_a_chosen_design(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        run = session.ut("design", "show", "--elements")

    assert run.status == 1
    assert run.output.endswith(said("design.elements_needs_choice") + "\n")


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_definition_behind_the_new_twins_names_ut_sections_update_for_every_action(
    tmp_path: Path, language: str
) -> None:
    actions = (
        [],
        ["show"],
        ["show", "--elements"],
        ["open"],
        ["change", "Bigger button"],
        ["review"],
        ["approve"],
        ["choose", "DES-001"],
        ["regenerate"],
    )
    with design_session(tmp_path, through="design", language=language) as session:
        new_twins(session)
        found = states(session)
        before = posts(session)
        runs = [session.ut("design", *arguments, language=language) for arguments in actions]
        after = posts(session)

    behind = said("design.definition_behind", language)
    assert (found["USER_TWINS"], found["REQUIREMENTS"]) == ("FINE", "TO_UPDATE")
    assert "`ut sections update`" in behind
    for arguments, run in zip(actions, runs, strict=True):
        assert run.status == 1, arguments
        assert run.output.endswith(behind + "\n"), arguments
        assert said("design.requirements_pending", language) not in run.output, arguments
    assert after == before


def test_a_definition_that_cannot_follow_the_new_twins_by_itself_says_why(tmp_path: Path) -> None:
    with design_session(tmp_path, through="design") as session:
        new_twins(session)
        session.client().post(
            f"{session.base}/requirements/change-requests", {"request": "Add the encore"}
        )
        found = sections_api.sections_of(session.project.sections())
        run = session.ut("design", "show")

    assert found is not None
    definition = found.section(sections_api.REQUIREMENTS)
    assert definition is not None and definition.blocked == sections_api.REVISION_PENDING
    context = command_context(terminal(tmp_path / "words", transport=NoNetwork()).environment)
    lines = sections_command.blocked_lines(context, found)
    assert run.status == 1
    assert lines
    assert run.output.endswith(said("design.definition_blocked", blocked=" ".join(lines)) + "\n")
    assert said("sections.reason_revision_pending") in run.output
    assert "`ut sections update`" not in run.output


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_help_names_the_options_and_the_show_action_names_elements(
    tmp_path: Path, language: str
) -> None:
    run = run_ut(["--lang", language, "design", "--help"], tmp_path, transport=NoNetwork())
    flat = " ".join(run.output.split())

    assert run.status == 0
    for option in ("--screen SCREEN", "--element ELEMENT", "--no-review", "--elements [SCREEN]"):
        assert option in run.output
    assert "show --elements" in flat
    assert " ".join(said("design.option_no_review", language).split()) in flat


def test_the_mockup_is_read_into_screens_and_elements_like_the_page_shows_them() -> None:
    screens = design_state.mockup_screens(DOCUMENT)

    assert [(item.code, item.title, item.label) for item in screens] == [
        ("SCR-001", "First screen", "First screen"),
        ("SCR-002", "Second", "Second"),
        ("SCR-003", "", "SCR-003"),
    ]
    first, second, third = screens
    assert [(item.code, item.kind, item.text) for item in first.elements] == [
        ("ELM-001", "h1", "Fish & chips"),
        ("ELM-002", "p", "One two"),
        ("ELM-003", "input", "Your name"),
        ("ELM-004", "textarea", "Note"),
        ("ELM-005", "select", "Two"),
        ("ELM-006", "button", "Close"),
        ("ELM-007", "output", "Total due"),
        ("ELM-008", "input", "Search"),
        ("ELM-009", "li", "AB"),
        ("ELM-010", "p", ("long " * 24).strip()),
    ]
    assert [(item.code, item.kind, item.text) for item in second.elements] == [
        ("ELM-011", "div", "Back"),
        ("ELM-012", "a", "Back"),
        ("ELM-014", "p", ("x " * 60).strip()),
        ("ELM-015", "div", ""),
    ]
    assert third.elements == ()
    assert first.element("ELM-001").html == '<h1 data-elm="ELM-001">Fish &amp; chips</h1>'
    assert first.element("ELM-003").html == '<input data-elm="ELM-003" id="name" type="text">'
    assert first.element("ELM-009").html == '<li data-elm="ELM-009">A<b>B</b></li>'
    assert second.element("ELM-011").html == (
        '<div data-elm="ELM-011"><a data-elm="ELM-012" href="#SCR-001">Back</a></div>'
    )
    long_markup = f'<p data-elm="ELM-014">{LONG_MARKUP}</p>'
    assert second.element("ELM-014").html == long_markup[:2048].rstrip()
    assert len(second.element("ELM-014").html) <= 2048
    assert all(len(item.text) <= 120 for screen in screens for item in screen.elements)
    assert second.element("ELM-015").label == "ELM-015"
    assert third.html == '<section id="SCR-003"></section>'
    assert design_state.document_screens(None) == ()
    assert design_state.document_screens({"html": 3}) == ()
    assert design_state.mockup_screens(OLD_MOCKUP)[0].elements == ()


def test_the_target_comes_from_the_screen_and_the_element_of_the_mockup(tmp_path: Path) -> None:
    context = command_context(terminal(tmp_path, transport=NoNetwork()).environment)
    document = {"html": DOCUMENT}

    assert design_change.aim_of(" scr-002 ", "elm-012") == design_change.Aim("SCR-002", "ELM-012")
    assert design_change.aim_of(None, None) is None
    assert design_change.target_of(context, document, design_change.Aim("SCR-002", "ELM-012")) == {
        "screen_code": "SCR-002",
        "element_code": "ELM-012",
        "label": "Back",
        "html": '<a data-elm="ELM-012" href="#SCR-001">Back</a>',
    }
    assert design_change.target_of(context, document, design_change.Aim("SCR-003")) == {
        "screen_code": "SCR-003",
        "label": "SCR-003",
        "html": '<section id="SCR-003"></section>',
    }
    empty = design_change.target_of(context, document, design_change.Aim("SCR-002", "ELM-015"))
    assert empty["label"] == "ELM-015"
    with pytest.raises(CliError) as missing:
        design_change.target_of(context, document, design_change.Aim("SCR-001", "ELM-012"))
    assert missing.value.code == "DESIGN_TARGET_NOT_FOUND"
    assert missing.value.status == 2
    assert dict(missing.value.values) == {
        "screen": "SCR-001",
        "element": "ELM-012",
        "reason": "ELEMENT",
        "screens": "SCR-001 “First screen”, SCR-002 “Second”, SCR-003",
    }


def test_the_iteration_body_carries_the_target_only_when_there_is_one() -> None:
    version = {"id": "v", "content_hash": "h", "version_number": 3}
    target = {"screen_code": "SCR-002", "label": "Split bill", "html": "<section></section>"}

    assert design_api.iteration_body(version, "Bigger button", (), target) == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "request": "Bigger button",
        "assertions": [],
        "target": target,
    }
    assert "target" not in design_api.iteration_body(version, "Bigger button", ())


def test_the_review_body_carries_the_scope_of_the_target_only_when_there_is_one() -> None:
    version = {"id": "v", "content_hash": "h", "version_number": 3}
    element = {
        "screen_code": "SCR-002",
        "element_code": "ELM-012",
        "label": "Back",
        "html": '<a data-elm="ELM-012" href="#SCR-001">Back</a>',
    }
    screen = {"screen_code": "SCR-002", "label": "Split bill", "html": "<section></section>"}

    assert design_api.evaluation_body(version, "it-IT") == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "locale": "it-IT",
    }
    assert design_change.scope_of(None) is None
    assert design_change.scope_of(element) == {"screen_code": "SCR-002", "element_code": "ELM-012"}
    assert design_change.scope_of(screen) == {"screen_code": "SCR-002"}
    assert design_api.evaluation_body(version, "en-US", design_change.scope_of(element)) == {
        "design_version_id": "v",
        "design_content_hash": "h",
        "locale": "en-US",
        "scope": {"screen_code": "SCR-002", "element_code": "ELM-012"},
    }
    assert design_api.evaluation_body(version, "en-US", design_change.scope_of(screen))[
        "scope"
    ] == {"screen_code": "SCR-002"}


@pytest.mark.parametrize(
    ("language", "lines"),
    [
        (
            "en",
            (
                "- ELM-001: Observation: Clearer now (screen “Start”, element “Go”)",
                "- Minor: Small (screen “Start”)",
                "- ELM-009: Major: Gone (screen “Start”)",
            ),
        ),
        (
            "it",
            (
                "- ELM-001: Osservazione: Clearer now (schermata «Start», elemento «Go»)",
                "- Lieve: Small (schermata «Start»)",
                "- ELM-009: Importante: Gone (schermata «Start»)",
            ),
        ),
    ],
)
def test_the_findings_that_name_an_element_start_with_its_code(
    tmp_path: Path, language: str, lines: tuple[str, ...]
) -> None:
    bundle = terminal(tmp_path, transport=UrlTransport())
    context = command_context(bundle.environment, language=language)
    version = {
        "package": {
            "grounding": {"user_twin_references": [{"twin_id": "t1", "name": "Anna"}]},
            "prototype": {
                "screens": [
                    {
                        "code": "SCR-001",
                        "title": "Start",
                        "elements": [{"code": "ELM-001", "content": "Go"}],
                    }
                ]
            },
        }
    }
    run = {
        "design_version_number": 5,
        "responses": [
            {
                "twin_id": "t1",
                "findings": [
                    {
                        "severity": "observation",
                        "summary": "Clearer now",
                        "anchor_key": "SCR-001/ELM-001",
                        "element_code": "ELM-001",
                    },
                    {"severity": "minor", "summary": "Small", "anchor_key": "SCR-001"},
                    {
                        "severity": "major",
                        "summary": "Gone",
                        "anchor_key": "SCR-001/ELM-009",
                        "element_code": "ELM-009",
                    },
                ],
            }
        ],
    }

    review.show_review(context, run, version)

    assert bundle.output.endswith("Anna\n" + "".join(f"{line}\n" for line in lines) + "\n")
