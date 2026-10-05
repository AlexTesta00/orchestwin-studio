from __future__ import annotations

import re

import pytest

from orchestwin.knowledge.diagrams import (
    DiagramKind,
    DiagramStage,
    design_diagrams,
    design_traceability_diagram,
    project_diagrams,
    requirement_diagram,
    requirements_traceability_diagram,
    screen_map_diagram,
    use_case_diagram,
    workflow_diagram,
)
from src.test.python.artifacts.design_fixtures import design_version, requirements_version

from .diagram_fixtures import ALTERNATIVE_TWO, TRICKY, package, specification

ENTITY = re.compile(r"#(?:[a-z]+|\d+);")
QUOTED = re.compile(r'"([^"\n]*)"')
FORBIDDEN = set('"#<>&`{}[]()|;:%\\')
ESCAPED_TRICKY = (
    "Nome #quot;vero#quot; #lt;b#gt;x#lt;/b#gt; #amp; 50#37; #35;1#59; #91;a#93; "
    "#40;b#41; #123;c#125; #124; #59; #58; perché #96;sì#96; #92; fine"
)


def all_diagrams(locale: str = "it"):
    return project_diagrams(
        specification=specification(),
        package=package(),
        system_name="Lista ospiti workshop",
        locale=locale,
    )


def unescaped(text: str) -> str:
    return ENTITY.sub("", text.replace("<br/>", " "))


def test_project_diagrams_cover_both_stages_with_stable_keys_and_paths() -> None:
    diagrams = all_diagrams()

    assert [(item.key, item.kind, item.stage, item.subject) for item in diagrams] == [
        ("requirements/use-cases", DiagramKind.USE_CASES, DiagramStage.REQUIREMENTS, None),
        ("requirements/requirements", DiagramKind.REQUIREMENTS, DiagramStage.REQUIREMENTS, None),
        (
            "requirements/traceability",
            DiagramKind.REQUIREMENTS_TRACEABILITY,
            DiagramStage.REQUIREMENTS,
            None,
        ),
        ("design/des-001-workflows", DiagramKind.WORKFLOWS, DiagramStage.DESIGN, "DES-001"),
        ("design/des-002-workflows", DiagramKind.WORKFLOWS, DiagramStage.DESIGN, "DES-002"),
        ("design/screen-map", DiagramKind.SCREEN_MAP, DiagramStage.DESIGN, "DES-001"),
        (
            "design/traceability",
            DiagramKind.DESIGN_TRACEABILITY,
            DiagramStage.DESIGN,
            "DES-001",
        ),
    ]
    assert [item.path for item in diagrams] == [
        "requirements/diagrams/use-cases.mmd",
        "requirements/diagrams/requirements.mmd",
        "requirements/diagrams/traceability.mmd",
        "design/diagrams/des-001-workflows.mmd",
        "design/diagrams/des-002-workflows.mmd",
        "design/diagrams/screen-map.mmd",
        "design/diagrams/traceability.mmd",
    ]
    assert all_diagrams() == diagrams
    assert diagrams[0].to_snapshot() == {
        "key": "requirements/use-cases",
        "stage": "requirements",
        "kind": "USE_CASES",
        "subject": None,
        "title": diagrams[0].title,
        "description": diagrams[0].description,
        "path": "requirements/diagrams/use-cases.mmd",
        "source": diagrams[0].source,
    }


def test_project_without_design_has_only_the_requirements_diagrams() -> None:
    diagrams = project_diagrams(
        specification=specification(), package=None, system_name="Lista ospiti workshop"
    )

    assert [item.stage for item in diagrams] == [DiagramStage.REQUIREMENTS] * 3


@pytest.mark.parametrize("locale", ["it", "en"])
def test_every_generated_text_is_escaped(locale: str) -> None:
    for diagram in all_diagrams(locale):
        assert diagram.source.endswith("\n")
        assert "\t" not in diagram.source
        for line in diagram.source.splitlines():
            if line.strip().startswith(("accTitle:", "accDescr:")):
                content = line.split(":", 1)[1]
                assert not FORBIDDEN & set(content), (diagram.key, line)
                continue
            for label in QUOTED.findall(line):
                assert not FORBIDDEN & set(unescaped(label)), (diagram.key, line)
            if diagram.kind is DiagramKind.SCREEN_MAP and "-->" in line and ": " in line:
                label = line.split(": ", 1)[1]
                assert not FORBIDDEN & set(unescaped(label)), (diagram.key, line)


def test_tricky_text_is_kept_through_entity_codes() -> None:
    diagram = requirement_diagram(specification())

    assert f'text: "{ESCAPED_TRICKY}"' in diagram.source
    assert TRICKY not in diagram.source


def test_use_case_diagram_links_each_twin_to_the_goals_of_its_stories() -> None:
    diagram = use_case_diagram(specification(), system_name="Lista ospiti workshop", locale="it")

    assert diagram.source.splitlines()[0] == "usecase-beta"
    assert '  actor T1("Addetti all\'accoglienza")' in diagram.source
    assert '  actor T2("Organizzatori volontari")' in diagram.source
    assert '  systemBoundary SYSTEM["Lista ospiti workshop"]' in diagram.source
    assert '    USR001("USR-001 Aggiungere ospiti per nome")' in diagram.source
    assert "  T1 --> USR001" in diagram.source
    assert "  T2 --> USR002" in diagram.source
    assert "T1 --> USR002" not in diagram.source
    assert diagram.title == "Casi d'uso"
    assert diagram.description == (
        "Diagramma dei casi d'uso di Lista ospiti workshop: 2 attori e 2 casi d'uso. "
        "Ogni caso d'uso è l'obiettivo di una storia utente."
    )


def test_use_case_diagram_without_stories_keeps_the_actors() -> None:
    snapshot = specification()
    snapshot["user_stories"] = []

    diagram = use_case_diagram(snapshot, system_name="Lista", locale="en")

    assert "actor T1" in diagram.source
    assert "-->" not in diagram.source
    assert diagram.description.startswith("Use case diagram of Lista: 2 actors and 0 use cases.")


def test_requirement_diagram_maps_kind_risk_and_verification() -> None:
    source = requirement_diagram(specification(), locale="en").source

    assert source.splitlines()[0] == "requirementDiagram"
    assert '  functionalRequirement "REQ-001 Aggiunta ospite" {' in source
    assert '  designConstraint "REQ-003 Nessun backend" {' in source
    assert re.search(r'\n  requirement "REQ-002 [^"]+" \{', source)
    first = source.split('functionalRequirement "REQ-001 Aggiunta ospite" {')[1].split("}")[0]
    assert 'id: "REQ-001"' in first
    assert "risk: High" in first
    assert "verifymethod: Demonstration" in first
    third = source.split('designConstraint "REQ-003 Nessun backend" {')[1].split("}")[0]
    assert "risk:" not in third
    assert "verifymethod:" not in third
    assert '    type: "acceptance criterion"' in source
    assert '    type: "usage scenario"' in source
    assert '  "SCN-001 Aggiunta di tre ospiti" - verifies -> "REQ-001 Aggiunta ospite"' in source
    assert source.count(" - verifies -> ") == 2


def test_requirements_traceability_follows_twins_stories_requirements_and_checks() -> None:
    diagram = requirements_traceability_diagram(specification(), locale="it")
    source = diagram.source

    assert source.splitlines()[0] == "flowchart LR"
    for group in ("TWINS", "STORIES", "REQUIREMENTS", "CRITERIA", "SCENARIOS", "RISKS", "DONE"):
        assert f"  subgraph {group}[" in source
    for edge in (
        "  T1 --> USR001",
        "  T2 --> USR002",
        "  USR001 --> REQ001",
        "  USR002 --> REQ002",
        "  REQ001 --> AC001",
        "  USR001 --> AC001",
        '  AC001 -.->|"esercitato da"| SCN001',
        '  REQ001 -.->|"esercitato da"| SCN001',
        '  RSK001 -.->|"riguarda"| REQ001',
        '  DOD001 -.->|"regola"| REQ002',
    ):
        assert edge in source.splitlines()
    assert diagram.description == (
        "Tracciabilità da 2 user twin, attraverso 2 storie utente, a 3 requisiti, "
        "1 criterio di accettazione e 1 scenario d'uso, con 1 rischio e "
        "1 condizione di completamento."
    )


def test_empty_collections_leave_no_empty_group() -> None:
    snapshot = specification()
    snapshot["risks"] = []
    snapshot["scenarios"] = []

    source = requirements_traceability_diagram(snapshot).source

    assert "subgraph RISKS" not in source
    assert "subgraph SCENARIOS" not in source
    assert "exercised by" not in source


def test_workflow_diagram_orders_the_steps_and_names_the_covered_requirements() -> None:
    alternative = package()["alternatives"][0]

    diagram = workflow_diagram(alternative, specification(), locale="it")
    lines = diagram.source.splitlines()

    assert lines[0] == "flowchart TD"
    assert '  subgraph FLOW001["FLOW-001 · Aggiunta di un ospite"]' in lines
    assert '    FLOW001S0(["Inizio"])' in lines
    assert '    FLOW001S1["1. Inserire il nome"]' in lines
    assert '    FLOW001E(["Fine"])' in lines
    assert [line.strip() for line in lines if " --> " in line] == [
        "FLOW001S0 --> FLOW001S1",
        "FLOW001S1 --> FLOW001S2",
        "FLOW001S2 --> FLOW001S3",
        "FLOW001S3 --> FLOW001E",
    ]
    assert '  FLOW001R[/"Copre REQ-001, REQ-002"/]' in lines
    assert "  FLOW001E -.-> FLOW001R" in lines
    assert diagram.description == (
        "Flusso di attività dell'alternativa DES-001, Lista ospiti a passi guidati: "
        "1 flusso e 3 passi. Ogni flusso è seguito dai requisiti che copre."
    )


def test_workflows_with_the_same_code_in_two_alternatives_get_distinct_diagrams() -> None:
    diagrams = [
        item
        for item in design_diagrams(package(), specification())
        if item.kind is DiagramKind.WORKFLOWS
    ]

    assert [item.key for item in diagrams] == [
        "design/des-001-workflows",
        "design/des-002-workflows",
    ]
    assert diagrams[0].source != diagrams[1].source


def test_long_steps_are_wrapped_on_word_boundaries() -> None:
    alternative = package()["alternatives"][1]
    alternative["workflows"][0]["steps"] = [
        "L'utente inserisce l'importo del conto e conferma con il pulsante principale"
    ]

    source = workflow_diagram(alternative, specification()).source

    assert (
        "    FLOW001S1[\"1. L'utente inserisce l'importo<br/>del conto e conferma con il"
        '<br/>pulsante principale"]'
    ) in source


def test_screen_map_starts_from_the_entry_screen_and_names_each_trigger() -> None:
    diagram = screen_map_diagram(package(), locale="it")

    assert diagram is not None
    lines = diagram.source.splitlines()
    assert lines[0] == "stateDiagram-v2"
    assert "  direction LR" in lines
    assert '  state "SCR-001 · Aggiungi ospite<br/>predefinito · 1 elemento" as SCR001' in lines
    assert "  [*] --> SCR001" in lines
    assert "  SCR001 --> SCR002: ELM-001 Aggiungi" in lines
    back = next(line for line in lines if line.startswith("  SCR002 --> SCR001: "))
    assert back.endswith("<br/>Torna all'inserimento")
    assert "successo · 2 elementi" in diagram.source
    assert diagram.description == (
        "Navigazione fra 2 schermate del mockup dell'alternativa DES-001 attraverso "
        "2 transizioni, a partire da SCR-001."
    )


def test_package_without_prototype_has_no_screen_map() -> None:
    snapshot = package()
    snapshot["prototype"] = None

    assert screen_map_diagram(snapshot) is None
    diagrams = design_diagrams(snapshot, specification())
    assert [item.kind for item in diagrams] == [
        DiagramKind.WORKFLOWS,
        DiagramKind.WORKFLOWS,
        DiagramKind.DESIGN_TRACEABILITY,
    ]
    assert "subgraph SCREENS" not in diagrams[-1].source


def test_design_traceability_marks_the_requirements_that_nothing_covers() -> None:
    diagram = design_traceability_diagram(package(), specification(), locale="it")

    assert diagram is not None
    lines = diagram.source.splitlines()
    assert "  FLOW001 --> REQ001" in lines
    assert "  FLOW001 --> REQ002" in lines
    assert "  REQ001 --> SCR001" in lines
    assert "  REQ002 --> SCR002" in lines
    assert "  classDef gap stroke-dasharray:6 4" in lines
    assert "  class REQ003 gap" in lines
    assert diagram.description == (
        "Copertura di 3 requisiti da parte di 1 flusso e 2 schermate dell'alternativa "
        "DES-001. 1 requisito non è coperto."
    )


def test_design_traceability_without_gaps_says_so() -> None:
    snapshot = specification()
    snapshot["requirements"] = snapshot["requirements"][:2]
    snapshot["definition_of_done"] = []

    diagram = design_traceability_diagram(package(), snapshot, locale="en")

    assert diagram is not None
    assert "classDef" not in diagram.source
    assert diagram.description.endswith("Every requirement is covered.")


def test_design_traceability_follows_the_owner_choice_when_no_mockup_exists() -> None:
    snapshot = package()
    snapshot["prototype"] = None
    snapshot["owner_selected_alternative_id"] = ALTERNATIVE_TWO

    diagram = design_traceability_diagram(snapshot, specification())

    assert diagram is not None
    assert diagram.subject == "DES-002"


def test_unknown_locale_falls_back_to_english() -> None:
    diagram = use_case_diagram(specification(), system_name="Lista", locale="de")

    assert diagram.title == "Use cases"


def test_real_snapshots_of_the_domain_produce_every_diagram() -> None:
    diagrams = project_diagrams(
        specification=requirements_version().specification.to_snapshot(),
        package=design_version().package.to_snapshot(),
        system_name="Studio",
        locale="en",
    )

    assert {item.kind for item in diagrams} == set(DiagramKind)
    assert all(item.source.strip() for item in diagrams)
