from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.cli import folder as local_folder
from orchestwin.cli.api import design as design_api
from orchestwin.cli.flows import design_choice, design_state, previews
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.messages import text
from orchestwin.cli.views import why as why_view
from orchestwin.knowledge.folder import folder_archive
from orchestwin.why import explain_why

from .support.fake_studio import FakeStudio
from .support.terminal import START, command_context, link_folder, run_ut, terminal
from .test_api_design import EMAIL, PASSWORD, Session, design_session, draw, propose
from .test_console import console_for
from .test_mcp_knowledge import edit_json
from .test_mcp_protocol import call, initialize
from .test_mcp_server import messages, serve, signed_in, structured
from .test_mcp_tools import build, run
from .test_previews import ADDRESSES

DISTANCE = "/projects/{project_id}/design/distance"
WIDE = {"COLUMNS": "200"}
STAGES = ("brief", "team", "twins", "requirements", "design")
AXES = ("layout", "shape", "type", "colour", "density")
OTHER_VERSION = "00000000-0000-4000-8000-000000000000"
FIELDS = ("name", "concept", "rules", "axes")
FOLLOWED = {
    "layout": "FOLLOWED",
    "shape": "FOLLOWED",
    "type": "FOLLOWED",
    "colour": "FOLLOWED",
    "density": "NOT_CHECKED",
}
SHOWN = {
    "en": (
        "Look: guided steps layout, teal colour, light mode, warm tone, humanist sans headings. "
        "Visual direction: Reading sheet (Stage, Filled surfaces, Reading, Tinted surfaces, "
        "Spacious) Mockup: not drawn yet.",
        "Look: single card layout, cobalt colour, dark mode, essential tone, humanist sans "
        "headings. Visual direction: Till receipt (Workbench, Square corners and rules, "
        "Upper-case labels, Almost monochrome, Comfortable) Mockup: not drawn yet.",
    ),
    "it": (
        "Aspetto: impaginazione a passi guidati, tinta ottanio, modalità chiara, tono caloroso, "
        "titoli con carattere senza grazie umanistico. Direzione visiva: Foglio da lettura "
        "(Palcoscenico, Superfici piene, Da lettura, Superfici tinte, Ariosa) Mockup: non ancora "
        "disegnato.",
        "Aspetto: impaginazione a scheda unica, tinta cobalto, modalità scura, tono essenziale, "
        "titoli con carattere senza grazie umanistico. Direzione visiva: Scontrino di cassa "
        "(Banco di lavoro, Angoli vivi e filetti, Etichette maiuscole, Quasi monocromo, Comoda) "
        "Mockup: non ancora disegnato.",
    ),
}
HEADINGS = {
    "en": ("Distance between the alternatives", "What the twins think"),
    "it": ("Distanza fra le alternative", "Cosa pensano i twin"),
}
CAVEAT = {
    "en": "Measure computed by the Studio: it does not replace your judgement.",
    "it": "Misura calcolata dallo Studio: non sostituisce il tuo giudizio.",
}
VERDICT_LINES = {
    "en": {
        "FAR": [
            "They differ · 5 of 5 axes differ",
            "Declared choices 100/100 · Drawn style 80/100 · Structure of the screens 41/100",
        ],
        "CLOSE": [
            "Too close · 5 of 5 axes differ",
            "Declared choices 100/100 · Drawn style 30/100 · Structure of the screens 12/100",
            "The two alternatives look alike in drawn style. You can regenerate them.",
        ],
        "UNKNOWN": [
            "Complete measure when both mockups are ready · 5 of 5 axes differ",
            "Declared choices 100/100",
        ],
    },
    "it": {
        "FAR": [
            "Si distinguono · 5 assi diversi su 5",
            "Scelte dichiarate 100/100 · Stile disegnato 80/100 · Struttura delle schermate 41/100",
        ],
        "CLOSE": [
            "Troppo vicine · 5 assi diversi su 5",
            "Scelte dichiarate 100/100 · Stile disegnato 30/100 · Struttura delle schermate 12/100",
            "Le due alternative si somigliano nello stile disegnato. Puoi rigenerarle.",
        ],
        "UNKNOWN": [
            "Misura completa quando i due mockup sono pronti · 5 assi diversi su 5",
            "Scelte dichiarate 100/100",
        ],
    },
}
SCORES = {"FAR": (80, 41), "CLOSE": (30, 12), "UNKNOWN": (None, None)}
AXIS_LINES = {
    "en": "    Layout: Stage · Shapes: Filled surfaces · Type: Reading · Colour: Tinted surfaces · "
    "Density: Spacious",
    "it": "    Impianto: Palcoscenico · Forme: Superfici piene · Tipografia: Da lettura · Colore: "
    "Superfici tinte · Densità: Ariosa",
}
ORIGIN_LINES = {
    "en": "    Proposed by the model among 5 candidates; chosen by the Studio because it is far "
    "from the other.",
    "it": "    Proposta dal modello fra 5 candidate; scelta dallo Studio perché lontana dall'altra.",
}
NAME_LINES = {
    "en": "    Visual direction: Reading sheet",
    "it": "    Direzione visiva: Foglio da lettura",
}
DIRECTION = {
    "name": "Reading sheet",
    "concept": "One centred column.",
    "rules": ["One.", "Two.", "Three."],
    "axes": {
        "layout": "STAGE",
        "shape": "SOFT_FILL",
        "type": "READING",
        "colour": "TINTED",
        "density": "SPACIOUS",
    },
    "typicality": 8,
    "candidates": 5,
    "vocabulary_version": 1,
}
DIRECTION_LINES = {
    "en": (
        "  Visual direction: Reading sheet (Stage, Filled surfaces, Reading, Tinted surfaces, "
        "Spacious)",
        '<p class="muted">Visual direction: Reading sheet</p>',
    ),
    "it": (
        "  Direzione visiva: Reading sheet (Palcoscenico, Superfici piene, Da lettura, Superfici "
        "tinte, Ariosa)",
        '<p class="muted">Direzione visiva: Reading sheet</p>',
    ),
}
ABSENT = object()


def flat(value: str) -> str:
    return " ".join(value.split())


def report_of(session: Session) -> dict[str, object]:
    found = design_api.distance(session.client(), session.project.id)
    assert found is not None
    return copy.deepcopy(dict(found))


def measured(
    report: Mapping[str, object],
    verdict: str,
    *,
    styles: int | None,
    structure: int | None,
    adherence: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, object]:
    changed = copy.deepcopy(dict(report))
    pair = changed["pairs"][0]
    pair["verdict"] = verdict
    for name, score in (("styles", styles), ("structure", structure)):
        pair[name] = {"available": score is not None, "score": score, "differences": []}
    for item in changed["alternatives"]:
        axes = (adherence or {}).get(item["code"])
        item["adherence"] = {"available": axes is not None, "axes": dict(axes or {})}
    return changed


def answer_with(session: Session, body: object, status: int = 200) -> None:
    session.studio.fail_next("GET", DISTANCE, status=status, body=body)


def block(output: str, language: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(HEADINGS[language][0])
    return lines[start : lines.index("", start)]


def framed(language: str, lines: list[str]) -> list[str]:
    heading = HEADINGS[language][0]
    return [heading, "=" * len(heading), *lines, CAVEAT[language]]


def direction_view(alternative: Mapping[str, object]) -> dict[str, object]:
    direction = alternative["visual_language"]["direction"]
    return {name: direction[name] for name in FIELDS}


def directions_of(package: Mapping[str, object]) -> list[object]:
    return [item["visual_language"]["direction"] for item in package["alternatives"]]


def state_with(direction: object = ABSENT) -> design_state.DesignState:
    visual: dict[str, object] = {
        "product_name": "Easy tip",
        "choices": {
            "archetype": "GUIDED_STEPS",
            "hue_family": "TEAL",
            "color_mode": "LIGHT",
            "tone": "WARM",
            "heading_family": "HUMANIST_SANS",
        },
    }
    if direction is not ABSENT:
        visual["direction"] = direction
    package = {
        "alternatives": [
            {
                "id": "a1",
                "code": "DES-001",
                "title": "Guided",
                "summary": "Two steps.",
                "visual_language": visual,
            }
        ],
        "critiques": [],
        "recommended_alternative_id": "a1",
        "owner_selected_alternative_id": None,
        "prototype": None,
    }
    return design_state.DesignState(
        project_id="p",
        project_name="Tip",
        stage="DESIGN",
        version={"id": "v", "version_number": 1, "content_hash": "h", "package": package},
        capabilities=design_api.Capabilities(True, True, True, "model"),
        documents={"a1": {"html": "<p>one</p>"}},
    )


def rendered(tmp_path: Path, state: design_state.DesignState, language: str) -> tuple[str, str]:
    bundle = terminal(tmp_path, transport=UrlTransport(), language=language, variables=WIDE)
    context = command_context(bundle.environment, language=language)
    design_state.show_alternatives(context, state)
    return bundle.output, previews.index_html(context, state, {"a1": "DES-001.html"})


@pytest.mark.parametrize("language", ["en", "it"])
def test_show_names_each_direction_after_its_look_and_the_distance_after_the_alternatives(
    tmp_path: Path, language: str
) -> None:
    with design_session(tmp_path, language=language, directions=True) as session:
        propose(session)
        run = session.ut("design", "show", language=language)

    lines = run.output.splitlines()
    heading, verdicts = HEADINGS[language]
    assert run.status == 0, run.errors
    for expected in SHOWN[language]:
        assert expected in flat(run.output)
    assert block(run.output, language) == framed(language, VERDICT_LINES[language]["UNKNOWN"])
    assert lines[lines.index(heading) - 1] == ""
    assert lines.index(heading) + 6 == lines.index(verdicts)


def test_show_with_both_mockups_gives_the_measure_of_the_studio(tmp_path: Path) -> None:
    with design_session(tmp_path, directions=True) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        report = report_of(session)
        run = session.ut("design", "show", variables=WIDE)

    pair = report["pairs"][0]
    lines = block(run.output, "en")
    verdict = text(f"design.distance_{pair['verdict']}", "en")
    assert run.status == 0, run.errors
    assert lines[2] == f"{verdict} · 5 of 5 axes differ"
    assert lines[3] == (
        f"Declared choices 100/100 · Drawn style {pair['styles']['score']}/100 · "
        f"Structure of the screens {pair['structure']['score']}/100"
    )
    assert (text("design.distance_close", "en") in lines) is (pair["verdict"] == "CLOSE")
    for item in report["alternatives"]:
        axes = item["adherence"]["axes"]
        missed = [
            text(f"design.axis_{axis}", "en") for axis in AXES if axes[axis] == "NOT_FOLLOWED"
        ]
        warning = text("design.distance_adherence", "en", code=item["code"], axes=", ".join(missed))
        assert (warning in lines) is bool(missed)
    assert lines[-1] == CAVEAT["en"]


@pytest.mark.parametrize("language", ["en", "it"])
@pytest.mark.parametrize("verdict", ["FAR", "CLOSE", "UNKNOWN"])
def test_each_verdict_of_the_measure_has_its_words(
    tmp_path: Path, language: str, verdict: str
) -> None:
    styles, structure = SCORES[verdict]
    with design_session(tmp_path, language=language, directions=True) as session:
        propose(session)
        report = measured(report_of(session), verdict, styles=styles, structure=structure)
        answer_with(session, report)
        run = session.ut("design", "show", language=language, variables=WIDE)

    assert run.status == 0, run.errors
    assert block(run.output, language) == framed(language, VERDICT_LINES[language][verdict])


@pytest.mark.parametrize(
    ("language", "warning"),
    [
        ("en", "DES-001 · The mockup does not follow the direction on: Type, Colour"),
        ("it", "DES-001 · Il mockup non segue la direzione su: Tipografia, Colore"),
    ],
)
def test_the_axes_that_a_mockup_does_not_follow_are_named(
    tmp_path: Path, language: str, warning: str
) -> None:
    missed = {**FOLLOWED, "type": "NOT_FOLLOWED", "colour": "NOT_FOLLOWED"}
    with design_session(tmp_path, language=language, directions=True) as session:
        propose(session)
        report = measured(
            report_of(session),
            "FAR",
            styles=80,
            structure=41,
            adherence={"DES-001": missed, "DES-002": FOLLOWED},
        )
        answer_with(session, report)
        run = session.ut("design", "show", language=language, variables=WIDE)

    assert run.status == 0, run.errors
    assert block(run.output, language) == framed(
        language, [*VERDICT_LINES[language]["FAR"], warning]
    )


def test_with_more_than_one_pair_each_pair_names_its_codes(tmp_path: Path) -> None:
    unmeasured = {"available": False, "score": None, "differences": []}
    report = {
        "design_version_id": "v",
        "pairs": [
            {
                "first": "DES-001",
                "second": "DES-002",
                "declared": {"score": 80, "axes_different": 4},
                "styles": unmeasured,
                "structure": unmeasured,
                "verdict": "UNKNOWN",
            },
            {
                "first": "DES-001",
                "second": "DES-003",
                "declared": {"score": 100, "axes_different": 5},
                "styles": {"available": True, "score": 70, "differences": []},
                "structure": {"available": True, "score": 20, "differences": []},
                "verdict": "FAR",
            },
        ],
        "alternatives": [],
    }
    bundle = terminal(tmp_path, transport=UrlTransport(), variables=WIDE)
    context = command_context(bundle.environment)

    design_state.show_distance(context, replace(state_with(DIRECTION), distance=report))
    design_state.show_distance(context, replace(state_with(DIRECTION), distance={"pairs": []}))

    lines = [
        "DES-001 · DES-002: Complete measure when both mockups are ready · 4 of 5 axes differ",
        "Declared choices 80/100",
        "DES-001 · DES-003: They differ · 5 of 5 axes differ",
        "Declared choices 100/100 · Drawn style 70/100 · Structure of the screens 20/100",
    ]
    assert bundle.output.splitlines() == [*framed("en", lines), ""]


def test_without_a_report_nothing_is_said_about_the_distance(tmp_path: Path) -> None:
    with design_session(tmp_path, directions=True) as session:
        propose(session)
        report = report_of(session)
        before = session.count("GET", "/design/distance")
        runs = []
        for status, body in (
            (404, {"detail": "Not Found"}),
            (503, {"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}}),
            (200, b"not json"),
            (200, [report]),
            (200, {**report, "design_version_id": OTHER_VERSION}),
        ):
            answer_with(session, body, status)
            runs.append(session.ut("design", "show"))
        asked = session.count("GET", "/design/distance") - before

    assert asked == len(runs)
    assert [item.status for item in runs] == [0] * len(runs)
    assert len({item.output for item in runs}) == 1
    assert SHOWN["en"][0] in flat(runs[0].output)
    assert HEADINGS["en"][0] not in runs[0].output


def test_without_a_direction_show_asks_no_distance_and_prints_as_before(tmp_path: Path) -> None:
    with design_session(tmp_path) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        shown = session.ut("design", "show")
        answer_with(session, {"detail": "Not Found"}, 404)
        older = session.ut("design", "show")
        asked = session.count("GET", "/design/distance")
        missing = design_api.distance(session.client(), session.project.id)

    assert shown.status == older.status == 0
    assert shown.output == older.output
    assert asked == 0
    assert missing is None
    assert "Visual direction" not in shown.output
    assert HEADINGS["en"][0] not in shown.output


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_null_direction_reads_like_no_direction(tmp_path: Path, language: str) -> None:
    line, paragraph = DIRECTION_LINES[language]
    plain = rendered(tmp_path, state_with(), language)
    output, page = rendered(tmp_path, state_with(DIRECTION), language)
    lines = output.splitlines()
    position = lines.index(line)

    assert rendered(tmp_path, state_with(None), language) == plain
    assert rendered(tmp_path, state_with({"axes": DIRECTION["axes"]}), language) == plain
    assert [item.direction for item in state_with(None).alternatives] == [None]
    assert lines[position - 1].startswith(("  Look:", "  Aspetto:"))
    assert lines[:position] + lines[position + 1 :] == plain[0].splitlines()
    assert paragraph in page
    assert page.replace(paragraph, "") == plain[1]
    assert state_with(DIRECTION).alternatives[0].direction == design_state.Direction(
        name="Reading sheet", axes=DIRECTION["axes"]
    )


def test_the_axis_words_fall_back_to_plain_words_for_values_not_yet_known(tmp_path: Path) -> None:
    axes = {**DIRECTION["axes"], "layout": "BRAND_NEW", "density": None}

    output = rendered(tmp_path, state_with({**DIRECTION, "axes": axes}), "en")[0]

    assert (
        "Visual direction: Reading sheet (brand new, Filled surfaces, Reading, Tinted surfaces, -)"
    ) in output


@pytest.mark.parametrize(
    ("language", "words"),
    [
        ("en", ("Visual direction: Reading sheet", "Visual direction: Till receipt")),
        ("it", ("Direzione visiva: Foglio da lettura", "Direzione visiva: Scontrino di cassa")),
    ],
)
def test_the_preview_cards_name_the_direction_and_load_nothing(
    tmp_path: Path, language: str, words: tuple[str, str]
) -> None:
    with design_session(tmp_path, language=language, directions=True) as session:
        propose(session)
        draw(session, "DES-001", "DES-002")
        opened = session.ut("design", "open", language=language)
        client = session.client()
        documents = {
            code: design_api.mockup_document(client, session.project.id, session.alternative(code))
            for code in ("DES-001", "DES-002")
        }
        index = (session.previews / "index.html").read_text(encoding="utf-8")
        written = {code: (session.previews / f"{code}.html").read_bytes() for code in documents}

    assert opened.status == 0, opened.errors
    for word in words:
        assert f'<p class="muted">{word}</p>' in index
    assert "<script" not in index.lower()
    assert "http:" not in index and "https:" not in index and "url(" not in index
    assert sorted(ADDRESSES.findall(index)) == ["DES-001.html", "DES-002.html"]
    for code, document in documents.items():
        assert document is not None
        assert written[code] == str(document["html"]).encode("utf-8")


def test_the_name_of_a_direction_is_escaped_in_the_preview(tmp_path: Path) -> None:
    page = rendered(tmp_path, state_with({**DIRECTION, "name": "<b>Tip</b> & co"}), "en")[1]

    assert "Visual direction: &lt;b&gt;Tip&lt;/b&gt; &amp; co" in page
    assert "<b>" not in page


def test_mcp_gives_the_directions_of_a_folder_read_without_network(tmp_path: Path) -> None:
    studio = FakeStudio(language="en", directions=True)
    studio.add_account(EMAIL, PASSWORD)
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
    archive = folder_archive(studio._knowledge_folder(project, STAGES, 1, START)).content
    folder = link_folder(tmp_path / "project", project_id=project.id, language="en")
    local_folder.unpack(archive, folder.knowledge)
    package = project.current("design")["package"]
    manifest = json.loads((folder.knowledge / "orchestwin.json").read_text(encoding="utf-8"))
    tools, bundle = build(tmp_path)

    found = run(tools, "get_design")

    def without_directions(document: dict) -> None:
        for item in document["package"]["alternatives"]:
            item["visual_language"]["direction"] = None

    edit_json(folder.knowledge / manifest["stages"]["design"]["document"], without_directions)
    plain = run(tools, "get_design")

    assert found["alternatives"] == [
        {
            "code": item["code"],
            "title": item["title"],
            "chosen": item["id"] == package["owner_selected_alternative_id"],
            "direction": direction_view(item),
        }
        for item in package["alternatives"]
    ]
    assert [set(item) for item in plain["alternatives"]] == [{"code", "title", "chosen"}] * 2
    assert len(tools.definitions()) == 15
    assert bundle.environment.stderr.getvalue() == ""


def test_mcp_gives_the_directions_of_a_folder_published_by_the_studio(tmp_path: Path) -> None:
    with FakeStudio(language="en", directions=True) as studio:
        project = signed_in(tmp_path, studio, language="en")
        published = run_ut(["package", "publish"], tmp_path, transport=UrlTransport())
        package = project.current("design")["package"]
        answered = serve(tmp_path, initialize(), call(2, "get_design"))

    alternatives = structured(messages(answered)[2])["alternatives"]
    assert published.status == 0, published.errors
    assert [item["direction"] for item in alternatives] == [
        direction_view(item) for item in package["alternatives"]
    ]


@pytest.mark.parametrize("language", ["en", "it"])
def test_why_all_writes_the_direction_in_readable_lines(tmp_path: Path, language: str) -> None:
    with design_session(tmp_path, through="design", language=language, directions=True) as session:
        detailed = session.ut("why", "REQ-001", "--all", language=language)
        answered = session.ut("why", "REQ-001", "--json", language=language)
        expected = explain_why(session.studio._why_document(session.project), "REQ-001")

    lines = detailed.output.splitlines()
    position = lines.index(NAME_LINES[language])
    assert detailed.status == answered.status == 0, detailed.errors
    assert lines[position + 1 : position + 3] == [AXIS_LINES[language], ORIGIN_LINES[language]]
    assert not any('"direction": {' in line for line in lines)
    assert json.loads(answered.output) == expected
    assert any(
        node["declared_context"].get("direction", {}).get("candidates") == 5
        for node in expected["downstream"]
    )


def test_why_all_without_a_direction_writes_the_declared_context_as_before(
    tmp_path: Path,
) -> None:
    studio = FakeStudio(language="en")
    studio.add_account(EMAIL, PASSWORD)
    project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
    answer = explain_why(studio._why_document(project), "REQ-001")
    console, bundle = console_for(tmp_path)

    why_view.show(console, answer, details=True)

    lines = bundle.output.splitlines()
    nodes = [*answer["upstream"], *answer["downstream"], *answer["human_validation"]]
    assert nodes
    for node in nodes:
        assert json.dumps(node["declared_context"], ensure_ascii=True, sort_keys=True) in lines
    assert "Visual direction" not in bundle.output


def test_why_keeps_the_rest_of_the_declared_context_next_to_the_direction(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, language="it")
    declared = {
        "perspectives": [],
        "section": {"state": "FINE"},
        "direction": {**DIRECTION, "origin": "MODEL", "selected_by": "STUDIO"},
    }

    why_view.show_declared(console, declared)
    why_view.show_declared(console, {**declared, "direction": None})

    assert bundle.output.splitlines() == [
        '{"perspectives": [], "section": {"state": "FINE"}}',
        "    Direzione visiva: Reading sheet",
        AXIS_LINES["it"],
        ORIGIN_LINES["it"],
        '{"direction": null, "perspectives": [], "section": {"state": "FINE"}}',
    ]


def test_a_choice_and_a_change_send_the_directions_back_untouched(tmp_path: Path) -> None:
    with design_session(tmp_path, directions=True) as session:
        version = propose(session)
        draw(session, "DES-001", "DES-002")
        chosen = session.ut("design", "choose", "DES-001")
        changed = session.ut("design", "change", "Bigger title", answers=["y"])
        sent = [
            json.loads(item.body)["package"]
            for item in session.requests("POST", "/design/revisions")
        ]
        current = session.project.current("design")

    assert chosen.status == 0, chosen.errors
    assert changed.status == 0, changed.errors
    assert len(sent) == 2
    for package in [*sent, current["package"]]:
        assert directions_of(package) == directions_of(version["package"])
    assert all(isinstance(item, dict) for item in directions_of(version["package"]))


@pytest.mark.parametrize("direction", [ABSENT, None, DIRECTION], ids=["absent", "null", "object"])
@pytest.mark.parametrize("same", [True, False], ids=["same-version", "older-version"])
def test_the_package_of_a_choice_keeps_the_direction_as_it_came(
    direction: object, same: bool
) -> None:
    state = state_with(direction)
    alternative = state.alternatives[0]
    proposed = copy.deepcopy(dict(state.package))
    proposed["owner_selected_alternative_id"] = alternative.id
    proposed["prototype"] = {"design_alternative_id": alternative.id}
    result = {
        "design_version_id": "v" if same else "older",
        "design_content_hash": "h",
        "package": proposed,
    }

    package = design_choice.choice_package(state, alternative, result)

    visual = package["alternatives"][0]["visual_language"]
    assert package["alternatives"] == state.package["alternatives"]
    assert ("direction" in visual) is (direction is not ABSENT)
    assert visual.get("direction", ABSENT) == direction


def test_the_distance_is_read_or_is_none(tmp_path: Path) -> None:
    with design_session(tmp_path, directions=True) as session:
        client = session.client()
        project_id = session.project.id
        missing = design_api.distance(client, project_id)
        version = propose(session)
        found = design_api.distance(client, project_id)
        answers = []
        for status, body in (
            (503, {"detail": {"code": "DESIGN_QUERY_UNAVAILABLE"}}),
            (200, b"not json"),
            (200, b""),
            (200, ["not", "an", "object"]),
        ):
            answer_with(session, body, status)
            answers.append(design_api.distance(client, project_id))
        asked = session.requests("GET", "/design/distance")

    assert design_api.distance_path("p") == "/projects/p/design/distance"
    assert missing is None
    assert found is not None and found["design_version_id"] == version["id"]
    assert answers == [None, None, None, None]
    assert {item.path for item in asked} == {f"/api/v1/projects/{project_id}/design/distance"}
