from __future__ import annotations

import csv
import io
import re
from collections import Counter

import pytest

from orchestwin.knowledge.diagrams import (
    design_diagrams,
    design_traceability_diagram,
    screen_map_diagram,
)
from orchestwin.knowledge.folder import DESIGN_MOCKUPS_TEXT
from orchestwin.knowledge.tables import TABLE_COLUMNS, design_tables

from .diagram_fixtures import ELEMENT_THREE, SCREEN_ONE, SCREEN_TWO, TRICKY
from .diagram_fixtures import package as declarative_package
from .test_knowledge_generated_mockup_support import (
    DASHBOARD,
    GUIDED_FORM,
    LARGE,
    MOCKUPS,
    generated_folder,
    generated_package,
    real_versions,
)

SCREENS_TABLE = "design/tables/screens.csv"
TRANSITIONS_TABLE = "design/tables/transitions.csv"
SCREEN_MAP = "design/diagrams/screen-map.mmd"
EDGE = re.compile(r"^  (SCR[0-9]{3}) --> (SCR[0-9]{3}): (.*)$")
ENTITY = re.compile(r"#(?:[a-z]+|\d+);")
FORBIDDEN = set('"#<>&`{}[]()|;:%\\')


def snapshots(name: str) -> tuple[dict[str, object], dict[str, object]]:
    specification = real_versions()["requirements"].specification.to_snapshot()
    return generated_package(name).to_snapshot(), specification


def edges(source: str) -> list[tuple[str, str, str]]:
    return [match.groups() for line in source.splitlines() if (match := EDGE.match(line))]


def pairs(package: dict[str, object]) -> Counter[tuple[str, str]]:
    prototype = package["prototype"]
    codes = {screen["id"]: screen["code"].replace("-", "") for screen in prototype["screens"]}
    return Counter(
        (codes[item["source_screen_id"]], codes[item["target_screen_id"]])
        for item in prototype["transitions"]
    )


def table(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def number(code: str) -> int:
    return int(code.split("-", 1)[1])


@pytest.mark.parametrize("name", MOCKUPS)
def test_the_screen_map_draws_one_edge_for_the_links_between_two_screens(name: str) -> None:
    package, _specification = snapshots(name)
    counted = pairs(package)

    diagram = screen_map_diagram(package, locale="en")
    assert diagram is not None
    drawn = edges(diagram.source)

    assert [(source, target) for source, target, _label in drawn] == list(counted)
    for source, target, label in drawn:
        links = counted[(source, target)]
        if links > 1:
            assert label.startswith(f"{links} links<br/>")
        else:
            assert re.match(r"ELM-[0-9]{3} ", label)
    assert f"through {sum(counted.values())} transitions" in diagram.description


def test_the_screen_map_of_the_dashboard_names_the_first_two_outcomes() -> None:
    package, _specification = snapshots(DASHBOARD)

    english = screen_map_diagram(package, locale="en")
    italian = screen_map_diagram(package, locale="it")
    assert english is not None and italian is not None

    assert "  SCR001 --> SCR002: 7 links<br/>Solleciti<br/>Sollecita i 9 ritardi" in (
        english.source.splitlines()
    )
    assert "  SCR001 --> SCR003: ELM-007 Esiti degli invii" in english.source.splitlines()
    assert "  SCR001 --> SCR002: 7 collegamenti<br/>Solleciti<br/>Sollecita i 9 ritardi" in (
        italian.source.splitlines()
    )
    assert len(edges(english.source)) == 6
    assert english.source == generated_folder(DASHBOARD).files[SCREEN_MAP]


def test_a_declarative_prototype_keeps_one_edge_for_every_transition() -> None:
    package = declarative_package()
    package["prototype"]["transitions"].append(
        {
            "code": "TRN-003",
            "source_screen_id": SCREEN_TWO,
            "target_screen_id": SCREEN_ONE,
            "trigger_element_id": ELEMENT_THREE,
            "outcome": TRICKY,
        }
    )
    grouped = {**package, "generated_mockup": {"mockup": {}, "requirement_ids_by_code": {}}}

    separate = screen_map_diagram(package, locale="it")
    together = screen_map_diagram(grouped, locale="it")
    assert separate is not None and together is not None

    assert [(source, target) for source, target, _label in edges(separate.source)] == [
        ("SCR001", "SCR002"),
        ("SCR002", "SCR001"),
        ("SCR002", "SCR001"),
    ]
    assert [(source, target) for source, target, _label in edges(together.source)] == [
        ("SCR001", "SCR002"),
        ("SCR002", "SCR001"),
    ]
    label = edges(together.source)[1][2]
    assert label.startswith("2 collegamenti<br/>Torna all'inserimento<br/>")
    assert not FORBIDDEN & set(ENTITY.sub("", label.replace("<br/>", " ")))
    assert separate.description == together.description


def test_repeated_outcomes_are_named_once_in_a_grouped_edge() -> None:
    package = declarative_package()
    package["prototype"]["transitions"].append(
        {
            "code": "TRN-003",
            "source_screen_id": SCREEN_TWO,
            "target_screen_id": SCREEN_ONE,
            "trigger_element_id": ELEMENT_THREE,
            "outcome": "torna ALL'inserimento",
        }
    )
    grouped = {**package, "generated_mockup": {"mockup": {}, "requirement_ids_by_code": {}}}

    diagram = screen_map_diagram(grouped, locale="en")
    assert diagram is not None

    assert edges(diagram.source)[1][2] == "2 links<br/>Torna all'inserimento"


@pytest.mark.parametrize("name", MOCKUPS)
def test_every_grouped_label_is_escaped(name: str) -> None:
    package, specification = snapshots(name)

    for locale in ("it", "en"):
        for diagram in design_diagrams(package, specification, locale=locale):
            for _source, _target, label in edges(diagram.source):
                assert not FORBIDDEN & set(ENTITY.sub("", label.replace("<br/>", " ")))


@pytest.mark.parametrize("name", MOCKUPS)
def test_design_traceability_links_the_requirements_to_the_derived_screens(name: str) -> None:
    package, specification = snapshots(name)
    bound = generated_package(name).generated_mockup
    prototype = generated_package(name).prototype
    assert bound is not None and prototype is not None
    codes = {item["id"]: item["code"] for item in specification["requirements"]}

    diagram = design_traceability_diagram(package, specification, locale="en")
    assert diagram is not None
    lines = set(diagram.source.splitlines())

    drawn = set()
    for screen in prototype.screens:
        for identifier in screen.requirement_ids:
            code = codes[str(identifier)]
            assert f"  {code.replace('-', '')} --> {screen.code.replace('-', '')}" in lines
            drawn.add(code)
    assert drawn == set(bound.requirement_codes)
    assert f"{len(prototype.screens)} screens of alternative DES-002" in diagram.description


@pytest.mark.parametrize("name", MOCKUPS)
def test_the_tables_of_screens_and_transitions_follow_the_codes(name: str) -> None:
    package, specification = snapshots(name)
    prototype = generated_package(name).prototype
    assert prototype is not None
    tables = design_tables(package, specification)
    screens = table(tables[SCREENS_TABLE])
    transitions = table(tables[TRANSITIONS_TABLE])
    elements = [element for screen in prototype.screens for element in screen.elements]

    assert list(screens[0]) == list(TABLE_COLUMNS[SCREENS_TABLE])
    assert [row["element"] for row in screens] == [element.code for element in elements]
    assert [number(row["element"]) for row in screens] == list(range(1, len(elements) + 1))
    assert [row["screen"] for row in screens] == [
        screen.code for screen in prototype.screens for _element in screen.elements
    ]
    assert [row["code"] for row in transitions] == [item.code for item in prototype.transitions]
    assert [number(row["code"]) for row in transitions] == list(
        range(1, len(prototype.transitions) + 1)
    )
    triggers = {str(element.id): element.code for element in elements}
    assert [row["trigger"] for row in transitions] == [
        triggers[str(item.trigger_element_id)] for item in prototype.transitions
    ]
    assert all(row["requirements"] for row in screens)
    assert tables == {
        path: text
        for path, text in generated_folder(name).files.items()
        if path.startswith("design/tables/")
    }


def test_two_hundred_fifty_elements_keep_their_order_in_every_view() -> None:
    folder = generated_folder(LARGE)
    screens = table(folder.files[SCREENS_TABLE])
    text = folder.files[DESIGN_MOCKUPS_TEXT]
    listed = re.findall(r"^\| (ELM-[0-9]+) \|", text, flags=re.MULTILINE)

    assert len(screens) == 250
    assert [row["element"] for row in screens] == [f"ELM-{index:03d}" for index in range(1, 251)]
    assert listed == [row["element"] for row in screens]
    assert re.findall(r"^- (TRN-[0-9]+):", text, flags=re.MULTILINE) == [
        f"TRN-{index:03d}" for index in range(1, 6)
    ]
    assert text.index("## SCR-001") < text.index("## SCR-005") < text.index("## Transitions")


@pytest.mark.parametrize("name", (DASHBOARD, GUIDED_FORM))
def test_the_text_of_the_mockups_says_where_the_derived_elements_come_from(name: str) -> None:
    text = generated_folder(name).files[DESIGN_MOCKUPS_TEXT]
    plain = generated_folder(None).files[DESIGN_MOCKUPS_TEXT]

    assert "derived from the HTML of the generated mockup in `mockup.html`" in text
    assert "`data-elm`" in text
    assert "derived from the HTML" not in plain
