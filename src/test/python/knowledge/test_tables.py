from __future__ import annotations

import csv
import io
import re
from copy import deepcopy

import pytest

from orchestwin.knowledge.tables import (
    TABLE_COLUMNS,
    design_tables,
    knowledge_tables,
    requirements_tables,
)
from src.test.python.artifacts.design_fixtures import design_version, requirements_version


def identity(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
REQUIREMENT_PATHS = [
    "requirements/tables/requirements.csv",
    "requirements/tables/user-stories.csv",
    "requirements/tables/acceptance-criteria.csv",
    "requirements/tables/scenarios.csv",
    "requirements/tables/risks.csv",
    "requirements/tables/definition-of-done.csv",
]
DESIGN_PATHS = [
    "design/tables/alternatives.csv",
    "design/tables/workflows.csv",
    "design/tables/visual-language.csv",
    "design/tables/palette.csv",
    "design/tables/critiques.csv",
    "design/tables/concerns.csv",
]
PROTOTYPE_PATHS = ["design/tables/screens.csv", "design/tables/transitions.csv"]
TRICKY = 'Nome, cognome e "soprannome"\ndell\'ospite,\r\n  su due righe\tcon tab '
TRICKY_CELL = 'Nome, cognome e "soprannome" dell\'ospite, su due righe con tab'
FORMULA_PREFIXES = ("=", "+", "-", "@")
HYPERLINK = '=HYPERLINK("https://example.com/x","Apri")'
RECEPTION = "Addetti all'accoglienza"
VOLUNTEERS = "Organizzatori volontari"
TWIN_IDS = {RECEPTION: identity(1), VOLUNTEERS: identity(2)}
REQ_ONE = identity(101)
REQ_TWO = identity(102)
REQ_THREE = identity(103)
STORY_ONE = identity(201)
STORY_TWO = identity(202)
CRITERION_ONE = identity(301)
CRITERION_TWO = identity(302)
ALTERNATIVE_ONE = identity(701)
ALTERNATIVE_TWO = identity(702)
SCREEN_ONE = identity(801)
SCREEN_TWO = identity(802)
SCREEN_THREE = identity(803)
ELEMENT_ONE = identity(901)
ELEMENT_TWO = identity(902)
ELEMENT_THREE = identity(903)
UNKNOWN = identity(999)


def twin(name: str) -> dict[str, object]:
    return {"twin_id": TWIN_IDS[name], "version_number": 1, "content_hash": "a" * 64, "name": name}


def specification() -> dict[str, object]:
    return {
        "user_twin_references": [twin(RECEPTION), twin(VOLUNTEERS)],
        "requirements": [
            {
                "id": REQ_ONE,
                "code": "REQ-001",
                "title": "Aggiunta ospite",
                "statement": "Inserire il nome di un ospite e aggiungerlo alla lista",
                "kind": "FUNCTIONAL",
                "priority": "MUST",
                "user_twin_references": [twin(RECEPTION), twin(VOLUNTEERS)],
            },
            {
                "id": REQ_TWO,
                "code": "REQ-002",
                "title": "Lista sempre leggibile",
                "statement": TRICKY,
                "kind": "NON_FUNCTIONAL",
                "priority": "SHOULD",
                "user_twin_references": [twin(VOLUNTEERS)],
            },
            {
                "id": REQ_THREE,
                "code": "REQ-003",
                "title": "Nessun backend",
                "statement": "Applicazione web statica senza backend",
                "kind": "CONSTRAINT",
                "priority": "MUST",
                "user_twin_references": [],
            },
        ],
        "user_stories": [
            {
                "id": STORY_ONE,
                "code": "USR-001",
                "user_twin_reference": twin(RECEPTION),
                "goal": "Aggiungere ospiti per nome",
                "benefit": "Gestire la lista durante l'evento",
                "requirement_ids": [REQ_ONE],
            },
            {
                "id": STORY_TWO,
                "code": "USR-002",
                "user_twin_reference": twin(VOLUNTEERS),
                "goal": "Vedere la lista aggiornata",
                "benefit": "Accogliere gli ospiti senza attese",
                "requirement_ids": [REQ_TWO, REQ_ONE],
            },
        ],
        "acceptance_criteria": [
            {
                "id": CRITERION_ONE,
                "code": "AC-001",
                "statement": "L'applicazione aggiunge un ospite e rifiuta i nomi vuoti",
                "verification_method": "DEMONSTRATION",
                "requirement_ids": [REQ_ONE],
                "user_story_ids": [STORY_TWO, STORY_ONE],
            },
            {
                "id": CRITERION_TWO,
                "code": "AC-002",
                "statement": "La lista resta leggibile con cento ospiti",
                "verification_method": "MANUAL_REVIEW",
                "requirement_ids": [REQ_TWO],
                "user_story_ids": [],
            },
        ],
        "scenarios": [
            {
                "id": identity(401),
                "code": "SCN-001",
                "title": "Aggiunta di tre ospiti",
                "actor": twin(RECEPTION),
                "preconditions": ["La lista è vuota", "L'app è aperta"],
                "trigger": "Arriva il primo ospite",
                "steps": ["Inserire il nome", "Premere Aggiungi"],
                "expected_outcome": "L'ospite compare nella lista",
                "requirement_ids": [REQ_TWO, REQ_ONE],
                "acceptance_criterion_ids": [CRITERION_ONE],
            }
        ],
        "risks": [
            {
                "id": identity(501),
                "code": "RSK-001",
                "summary": "Nomi duplicati",
                "likelihood": "POSSIBLE",
                "impact": "HIGH",
                "mitigation": "Segnalare i nomi già presenti",
                "requirement_ids": [REQ_ONE],
                "review_status": "PROPOSED",
            }
        ],
        "definition_of_done": [
            {
                "id": identity(601),
                "code": "DOD-001",
                "statement": "Un volontario aggiunge tre ospiti e li vede in lista",
                "verification_method": "DEMONSTRATION",
                "applicability": "REQUIRED",
                "condition": None,
                "requirement_ids": [REQ_ONE, REQ_TWO],
            },
            {
                "id": identity(602),
                "code": "DOD-002",
                "statement": "La lista viene stampata",
                "verification_method": "INSPECTION",
                "applicability": "CONDITIONAL",
                "condition": "Se l'evento supera cento ospiti",
                "requirement_ids": [REQ_TWO],
            },
        ],
    }


def workflow(
    number: int, code: str, title: str, steps: list[str], requirements: list[str]
) -> dict[str, object]:
    return {
        "id": identity(number),
        "code": code,
        "title": title,
        "steps": steps,
        "requirement_ids": requirements,
        "user_story_ids": [STORY_ONE],
    }


def critique(
    number: int,
    code: str,
    alternative: str,
    name: str,
    confidence: float,
    texts: dict[str, list[str]],
) -> dict[str, object]:
    return {
        "id": identity(number),
        "code": code,
        "kind": "SYNTHETIC_USER_TWIN",
        "design_alternative_id": alternative,
        "user_twin_reference": twin(name),
        **texts,
        "confidence": confidence,
        "epistemic_status": "MODEL_INFERRED",
        "human_validation": "REQUIRED",
    }


def element(
    element_id: str,
    code: str,
    kind: str,
    content: str,
    *,
    accessible_name: str | None = None,
    field_name: str | None = None,
    required: bool = False,
    options: tuple[str, ...] = (),
    requirements: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "id": element_id,
        "code": code,
        "kind": kind,
        "content": content,
        "accessible_name": accessible_name,
        "requirement_ids": list(requirements),
        "user_story_ids": [],
        "acceptance_criterion_ids": [],
        "field_name": field_name,
        "required": required,
        "options": list(options),
    }


def screen(
    screen_id: str,
    code: str,
    title: str,
    state: str,
    elements: list[dict[str, object]],
    requirements: list[str],
) -> dict[str, object]:
    return {
        "id": screen_id,
        "code": code,
        "title": title,
        "state": state,
        "elements": elements,
        "requirement_ids": requirements,
        "user_story_ids": [],
        "acceptance_criterion_ids": [],
    }


def transition(
    number: int, code: str, source: str, trigger: str, target: str, outcome: str
) -> dict[str, object]:
    return {
        "id": identity(number),
        "code": code,
        "source_screen_id": source,
        "trigger_element_id": trigger,
        "target_screen_id": target,
        "outcome": outcome,
    }


def visual_language() -> dict[str, object]:
    return {
        "catalog_version": 1,
        "choices": {"tone": "CALM", "archetype": "DASHBOARD", "color_mode": "DARK"},
        "product_name": "Lista ospiti",
        "rationale": "Una scheda scura e calma per la serata",
        "palette": {"primary": "#0f766e", "background": "#101418", "accent": "#b45309"},
        "tokens": {"--vl-gap": "16px"},
        "twin_fit": [],
    }


def package() -> dict[str, object]:
    return {
        "alternatives": [
            {
                "id": ALTERNATIVE_ONE,
                "code": "DES-001",
                "title": "Lista ospiti a passi guidati",
                "summary": "Un passo alla volta",
                "rationale": "Riduce gli errori dei volontari",
                "requirement_ids": [REQ_TWO, REQ_ONE],
                "user_story_ids": [STORY_ONE],
                "acceptance_criterion_ids": [CRITERION_ONE],
                "user_twin_references": [twin(VOLUNTEERS), twin(RECEPTION)],
                "workflows": [
                    workflow(
                        1001,
                        "FLOW-001",
                        "Aggiunta di un ospite",
                        ["Inserire il nome", "Premere Aggiungi", "Vedere la lista"],
                        [REQ_ONE, REQ_TWO],
                    )
                ],
            },
            {
                "id": ALTERNATIVE_TWO,
                "code": "DES-002",
                "approach": "DASHBOARD_FIRST",
                "title": "Lista ospiti a scheda unica",
                "summary": "Tutto in una scheda",
                "rationale": "Più veloce per chi è esperto",
                "requirement_ids": [REQ_ONE],
                "user_story_ids": [STORY_TWO, STORY_ONE],
                "acceptance_criterion_ids": [CRITERION_TWO, CRITERION_ONE],
                "user_twin_references": [twin(RECEPTION)],
                "workflows": [
                    workflow(1002, "FLOW-001", "Aggiunta rapida", ["Inserire il nome"], [REQ_ONE]),
                    workflow(1003, "FLOW-002", "Consultazione", [], [REQ_TWO]),
                ],
                "visual_language": visual_language(),
            },
        ],
        "critiques": [
            critique(
                1101,
                "CRQ-001",
                ALTERNATIVE_ONE,
                RECEPTION,
                0.7,
                {
                    "suggested_changes": ["Mostrare un contatore"],
                    "questions": ["Serve la ricerca?"],
                    "unmet_needs": [],
                    "strengths": ["Il compito principale è chiaro", "Pochi campi"],
                    "accessibility_observations": ["Etichette sempre visibili"],
                    "trust_concerns": [],
                    "concerns": ["Troppi passi per gli esperti"],
                },
            ),
            critique(
                1102,
                "CRQ-002",
                ALTERNATIVE_TWO,
                VOLUNTEERS,
                0.55,
                {"concerns": ["Scheda affollata"], "strengths": ["Tutto a colpo d'occhio"]},
            ),
        ],
        "recommended_alternative_id": ALTERNATIVE_TWO,
        "owner_selected_alternative_id": ALTERNATIVE_ONE,
        "prototype": {
            "id": identity(1200),
            "code": "PRT-001",
            "title": "Lista ospiti",
            "design_alternative_id": ALTERNATIVE_ONE,
            "entry_screen_id": SCREEN_ONE,
            "screens": [
                screen(
                    SCREEN_ONE,
                    "SCR-001",
                    "Aggiungi ospite",
                    "DEFAULT",
                    [
                        element(
                            ELEMENT_ONE,
                            "ELM-001",
                            "TEXT_INPUT",
                            "Nome",
                            accessible_name="Nome dell'ospite",
                            field_name="guest_name",
                            required=True,
                            requirements=(REQ_TWO, REQ_ONE),
                        ),
                        element(ELEMENT_TWO, "ELM-002", "BUTTON", "Aggiungi"),
                    ],
                    [REQ_ONE],
                ),
                screen(
                    SCREEN_TWO,
                    "SCR-002",
                    "Lista aggiornata",
                    "SUCCESS",
                    [
                        element(
                            ELEMENT_THREE,
                            "ELM-003",
                            "SELECT",
                            "Ordina per",
                            field_name="order",
                            options=("Nome", "Arrivo"),
                            requirements=(REQ_TWO,),
                        )
                    ],
                    [],
                ),
                screen(SCREEN_THREE, "SCR-003", "Nessun ospite", "EMPTY", [], [REQ_THREE]),
            ],
            "transitions": [
                transition(
                    1301,
                    "TRN-001",
                    SCREEN_ONE,
                    ELEMENT_TWO,
                    SCREEN_TWO,
                    "L'ospite compare nella lista",
                ),
                transition(
                    1302, "TRN-002", SCREEN_TWO, ELEMENT_THREE, SCREEN_ONE, "Torna all'inserimento"
                ),
            ],
            "supported_viewports": ["DESKTOP", "MOBILE"],
        },
        "concerns": [
            {
                "id": identity(1400),
                "code": "DRK-001",
                "summary": "Gli esperti potrebbero trovare lento il flusso guidato",
                "mitigation": "Tenere visibili le scorciatoie",
                "requirement_ids": [REQ_ONE],
                "design_alternative_ids": [ALTERNATIVE_TWO, ALTERNATIVE_ONE],
            }
        ],
        "open_questions": [],
    }


def all_tables() -> dict[str, str]:
    return knowledge_tables(specification=specification(), package=package())


def cells(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def records(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def rows_of(path: str) -> list[dict[str, str]]:
    return records(all_tables()[path])


def malformed_tables(tables: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for path, text in tables.items():
        header, *body = cells(text)
        if header != list(TABLE_COLUMNS[path]):
            problems.append(f"{path}: header")
        if any(len(row) != len(header) for row in body):
            problems.append(f"{path}: row width")
        if not text.endswith("\n") or text.endswith("\n\n"):
            problems.append(f"{path}: trailing newline")
    return problems


def identifiers_in(tables: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (path, cell)
        for path, text in tables.items()
        for row in cells(text)
        for cell in row
        if UUID_PATTERN.search(cell)
    ]


def test_a_project_with_a_mockup_has_every_table_in_the_declared_order() -> None:
    tables = all_tables()

    assert list(tables) == [*REQUIREMENT_PATHS, *DESIGN_PATHS, *PROTOTYPE_PATHS]
    assert list(TABLE_COLUMNS) == list(tables)
    assert tables == {
        **requirements_tables(specification()),
        **design_tables(package(), specification()),
    }


def test_a_project_without_design_has_only_the_requirements_tables() -> None:
    tables = knowledge_tables(specification=specification(), package=None)

    assert list(tables) == REQUIREMENT_PATHS
    assert tables == requirements_tables(specification())


def test_a_design_without_mockup_has_no_screen_or_transition_table() -> None:
    snapshot = package()
    snapshot["prototype"] = None

    tables = knowledge_tables(specification=specification(), package=snapshot)

    assert list(tables) == [*REQUIREMENT_PATHS, *DESIGN_PATHS]
    assert list(design_tables(snapshot, specification())) == DESIGN_PATHS


def test_every_table_has_the_declared_header_and_rows_as_wide_as_the_header() -> None:
    tables = all_tables()

    assert malformed_tables(tables) == []
    assert all(len(cells(text)) > 1 for text in tables.values())


def test_no_cell_contains_an_identifier_when_every_reference_resolves() -> None:
    assert identifiers_in(all_tables()) == []


def test_a_requirement_row_lists_the_items_that_reference_it() -> None:
    rows = rows_of("requirements/tables/requirements.csv")

    assert rows[0] == {
        "code": "REQ-001",
        "title": "Aggiunta ospite",
        "kind": "FUNCTIONAL",
        "priority": "MUST",
        "statement": "Inserire il nome di un ospite e aggiungerlo alla lista",
        "twins": "Addetti all'accoglienza; Organizzatori volontari",
        "user_stories": "USR-001; USR-002",
        "acceptance_criteria": "AC-001",
        "scenarios": "SCN-001",
        "risks": "RSK-001",
        "definition_of_done": "DOD-001",
    }
    assert [
        (
            row["user_stories"],
            row["acceptance_criteria"],
            row["scenarios"],
            row["risks"],
            row["definition_of_done"],
        )
        for row in rows[1:]
    ] == [("USR-002", "AC-002", "SCN-001", "", "DOD-001; DOD-002"), ("", "", "", "", "")]


def test_stories_and_criteria_link_each_other_by_code() -> None:
    stories = rows_of("requirements/tables/user-stories.csv")
    criteria = rows_of("requirements/tables/acceptance-criteria.csv")

    assert [
        (row["code"], row["twin"], row["requirements"], row["acceptance_criteria"])
        for row in stories
    ] == [
        ("USR-001", RECEPTION, "REQ-001", "AC-001"),
        ("USR-002", VOLUNTEERS, "REQ-001; REQ-002", "AC-001"),
    ]
    assert [
        (row["code"], row["requirements"], row["user_stories"], row["scenarios"])
        for row in criteria
    ] == [("AC-001", "REQ-001", "USR-001; USR-002", "SCN-001"), ("AC-002", "REQ-002", "", "")]


def test_scenario_steps_are_numbered_and_multi_valued_cells_use_semicolons() -> None:
    assert rows_of("requirements/tables/scenarios.csv") == [
        {
            "code": "SCN-001",
            "title": "Aggiunta di tre ospiti",
            "actor": RECEPTION,
            "trigger": "Arriva il primo ospite",
            "preconditions": "La lista è vuota; L'app è aperta",
            "steps": "1. Inserire il nome; 2. Premere Aggiungi",
            "expected_outcome": "L'ospite compare nella lista",
            "requirements": "REQ-001; REQ-002",
            "acceptance_criteria": "AC-001",
        }
    ]


def test_text_with_commas_quotes_and_newlines_survives_a_csv_round_trip() -> None:
    text = requirements_tables(specification())["requirements/tables/requirements.csv"]

    assert records(text)[1]["statement"] == TRICKY_CELL
    assert '"Nome, cognome e ""soprannome"" dell\'ospite, su due righe con tab"' in text
    assert text.count("\n") == 4
    assert "\r" not in text
    assert "\t" not in text


def test_list_items_are_normalized_before_they_are_joined() -> None:
    snapshot = specification()
    snapshot["scenarios"][0]["steps"] = [TRICKY, "  Premere\nAggiungi "]

    text = requirements_tables(snapshot)["requirements/tables/scenarios.csv"]

    assert records(text)[0]["steps"] == f"1. {TRICKY_CELL}; 2. Premere Aggiungi"
    assert text.count("\n") == 2


@pytest.mark.parametrize(
    ("title", "cell"),
    [
        (HYPERLINK, f"'{HYPERLINK}"),
        ("- Aggiunta ospite", "'- Aggiunta ospite"),
        ("+39 055 123456", "'+39 055 123456"),
        ("@nome", "'@nome"),
        ("   =1+1", "'=1+1"),
        ("\t\r\n=1+1", "'=1+1"),
        ("Aggiunta ospite", "Aggiunta ospite"),
        ("Ospiti = invitati + accompagnatori", "Ospiti = invitati + accompagnatori"),
    ],
)
def test_a_cell_that_a_spreadsheet_would_run_as_a_formula_is_written_as_text(
    title: str, cell: str
) -> None:
    snapshot = specification()
    snapshot["requirements"][0]["title"] = title

    text = requirements_tables(snapshot)["requirements/tables/requirements.csv"]

    assert records(text)[0]["title"] == cell


def test_no_cell_of_any_table_starts_like_a_formula() -> None:
    requirements_snapshot = specification()
    requirements_snapshot["risks"][0]["summary"] = "-1 posto a tavola"
    requirements_snapshot["scenarios"][0]["preconditions"] = ["=A1", "-B2"]
    requirements_snapshot["scenarios"][0]["steps"] = ["=SOMMA(A1:A3)"]
    design_snapshot = package()
    design_snapshot["alternatives"][0]["workflows"][0]["steps"][0] = "+39 055 123456"
    design_snapshot["critiques"][0]["strengths"] = ["@organizzatori"]
    design_snapshot["prototype"]["screens"][0]["elements"][1]["content"] = HYPERLINK

    tables = knowledge_tables(specification=requirements_snapshot, package=design_snapshot)

    assert [
        cell
        for text in tables.values()
        for row in cells(text)
        for cell in row
        if cell.startswith(FORMULA_PREFIXES)
    ] == []
    assert malformed_tables(tables) == []
    risk = records(tables["requirements/tables/risks.csv"])[0]
    scenario = records(tables["requirements/tables/scenarios.csv"])[0]
    workflow_step = records(tables["design/tables/workflows.csv"])[0]
    strength = records(tables["design/tables/critiques.csv"])[0]
    button = records(tables["design/tables/screens.csv"])[1]
    trigger = records(tables["design/tables/transitions.csv"])[0]
    assert risk["summary"] == "'-1 posto a tavola"
    assert (scenario["preconditions"], scenario["steps"]) == ("'=A1; -B2", "1. =SOMMA(A1:A3)")
    assert workflow_step["step"] == "'+39 055 123456"
    assert (strength["aspect"], strength["text"]) == ("strengths", "'@organizzatori")
    assert button["content"] == trigger["trigger_content"] == f"'{HYPERLINK}"


def test_booleans_are_written_yes_or_no_and_null_is_written_empty() -> None:
    tables = all_tables()
    alternatives = records(tables["design/tables/alternatives.csv"])
    screens = records(tables["design/tables/screens.csv"])
    done = records(tables["requirements/tables/definition-of-done.csv"])

    assert [(row["selected"], row["recommended"]) for row in alternatives] == [
        ("yes", "no"),
        ("no", "yes"),
    ]
    assert [(row["element"], row["entry"], row["required"]) for row in screens] == [
        ("ELM-001", "yes", "yes"),
        ("ELM-002", "yes", "no"),
        ("ELM-003", "no", "no"),
        ("", "no", ""),
    ]
    assert (screens[1]["accessible_name"], screens[1]["field_name"]) == ("", "")
    assert [row["condition"] for row in done] == ["", "Se l'evento supera cento ospiti"]


def test_alternatives_resolve_their_references_and_list_the_twins_by_name() -> None:
    rows = rows_of("design/tables/alternatives.csv")

    assert rows[0] == {
        "code": "DES-001",
        "title": "Lista ospiti a passi guidati",
        "selected": "yes",
        "recommended": "no",
        "archetype": "",
        "product_name": "",
        "summary": "Un passo alla volta",
        "rationale": "Riduce gli errori dei volontari",
        "requirements": "REQ-001; REQ-002",
        "user_stories": "USR-001",
        "acceptance_criteria": "AC-001",
        "twins": "Addetti all'accoglienza; Organizzatori volontari",
        "workflows": "FLOW-001",
    }
    assert (rows[1]["user_stories"], rows[1]["acceptance_criteria"], rows[1]["workflows"]) == (
        "USR-001; USR-002",
        "AC-001; AC-002",
        "FLOW-001; FLOW-002",
    )


def test_workflows_sharing_a_code_stay_distinguishable_by_alternative() -> None:
    rows = rows_of("design/tables/workflows.csv")

    assert [
        (row["alternative"], row["code"], row["title"], row["step_number"], row["step"])
        for row in rows
    ] == [
        ("DES-001", "FLOW-001", "Aggiunta di un ospite", "1", "Inserire il nome"),
        ("DES-001", "FLOW-001", "Aggiunta di un ospite", "2", "Premere Aggiungi"),
        ("DES-001", "FLOW-001", "Aggiunta di un ospite", "3", "Vedere la lista"),
        ("DES-002", "FLOW-001", "Aggiunta rapida", "1", "Inserire il nome"),
        ("DES-002", "FLOW-002", "Consultazione", "", ""),
    ]
    assert [(row["requirements"], row["user_stories"]) for row in rows] == [
        ("REQ-001; REQ-002", "USR-001"),
        ("REQ-001; REQ-002", "USR-001"),
        ("REQ-001; REQ-002", "USR-001"),
        ("REQ-001", "USR-001"),
        ("REQ-002", "USR-001"),
    ]


def test_an_alternative_without_visual_language_has_no_visual_rows() -> None:
    tables = all_tables()
    alternatives = records(tables["design/tables/alternatives.csv"])

    assert [(row["archetype"], row["product_name"]) for row in alternatives] == [
        ("", ""),
        ("DASHBOARD", "Lista ospiti"),
    ]
    assert records(tables["design/tables/visual-language.csv"]) == [
        {"alternative": "DES-002", "dimension": "archetype", "value": "DASHBOARD"},
        {"alternative": "DES-002", "dimension": "color_mode", "value": "DARK"},
        {"alternative": "DES-002", "dimension": "tone", "value": "CALM"},
    ]
    assert records(tables["design/tables/palette.csv"]) == [
        {"alternative": "DES-002", "role": "accent", "colour": "#b45309"},
        {"alternative": "DES-002", "role": "background", "colour": "#101418"},
        {"alternative": "DES-002", "role": "primary", "colour": "#0f766e"},
    ]


def test_visual_tables_keep_only_their_header_when_no_alternative_has_a_visual_language() -> None:
    snapshot = package()
    snapshot["alternatives"][1]["visual_language"] = None

    tables = design_tables(snapshot, specification())

    assert tables["design/tables/visual-language.csv"] == "alternative,dimension,value\n"
    assert tables["design/tables/palette.csv"] == "alternative,role,colour\n"
    assert records(tables["design/tables/alternatives.csv"])[1]["archetype"] == ""


def test_critiques_have_one_row_per_text_in_the_order_of_the_aspects() -> None:
    rows = rows_of("design/tables/critiques.csv")

    assert [
        (row["code"], row["alternative"], row["twin"], row["aspect"], row["text"]) for row in rows
    ] == [
        ("CRQ-001", "DES-001", RECEPTION, "strengths", "Il compito principale è chiaro"),
        ("CRQ-001", "DES-001", RECEPTION, "strengths", "Pochi campi"),
        ("CRQ-001", "DES-001", RECEPTION, "concerns", "Troppi passi per gli esperti"),
        (
            "CRQ-001",
            "DES-001",
            RECEPTION,
            "accessibility_observations",
            "Etichette sempre visibili",
        ),
        ("CRQ-001", "DES-001", RECEPTION, "questions", "Serve la ricerca?"),
        ("CRQ-001", "DES-001", RECEPTION, "suggested_changes", "Mostrare un contatore"),
        ("CRQ-002", "DES-002", VOLUNTEERS, "strengths", "Tutto a colpo d'occhio"),
        ("CRQ-002", "DES-002", VOLUNTEERS, "concerns", "Scheda affollata"),
    ]
    assert [row["confidence"] for row in rows] == ["0.7"] * 6 + ["0.55"] * 2
    assert {(row["epistemic_status"], row["human_validation"]) for row in rows} == {
        ("MODEL_INFERRED", "REQUIRED")
    }


def test_concerns_name_their_alternatives_and_requirements_by_code() -> None:
    assert rows_of("design/tables/concerns.csv") == [
        {
            "code": "DRK-001",
            "summary": "Gli esperti potrebbero trovare lento il flusso guidato",
            "mitigation": "Tenere visibili le scorciatoie",
            "alternatives": "DES-001; DES-002",
            "requirements": "REQ-001",
        }
    ]


def test_screens_have_one_row_per_element_and_one_row_for_a_screen_without_elements() -> None:
    rows = rows_of("design/tables/screens.csv")

    assert rows[0] == {
        "screen": "SCR-001",
        "title": "Aggiungi ospite",
        "state": "DEFAULT",
        "entry": "yes",
        "element": "ELM-001",
        "kind": "TEXT_INPUT",
        "content": "Nome",
        "accessible_name": "Nome dell'ospite",
        "field_name": "guest_name",
        "required": "yes",
        "options": "",
        "requirements": "REQ-001; REQ-002",
    }
    assert [
        (row["screen"], row["element"], row["kind"], row["options"], row["requirements"])
        for row in rows[1:3]
    ] == [
        ("SCR-001", "ELM-002", "BUTTON", "", "REQ-001"),
        ("SCR-002", "ELM-003", "SELECT", "Nome; Arrivo", "REQ-002"),
    ]
    assert rows[3] == {
        "screen": "SCR-003",
        "title": "Nessun ospite",
        "state": "EMPTY",
        "entry": "no",
        "element": "",
        "kind": "",
        "content": "",
        "accessible_name": "",
        "field_name": "",
        "required": "",
        "options": "",
        "requirements": "REQ-003",
    }


def test_transitions_name_their_screens_and_trigger_by_code() -> None:
    assert rows_of("design/tables/transitions.csv") == [
        {
            "code": "TRN-001",
            "source": "SCR-001",
            "target": "SCR-002",
            "trigger": "ELM-002",
            "trigger_content": "Aggiungi",
            "outcome": "L'ospite compare nella lista",
        },
        {
            "code": "TRN-002",
            "source": "SCR-002",
            "target": "SCR-001",
            "trigger": "ELM-003",
            "trigger_content": "Ordina per",
            "outcome": "Torna all'inserimento",
        },
    ]


def test_an_unknown_reference_is_written_as_the_raw_identifier() -> None:
    snapshot = package()
    snapshot["concerns"][0]["requirement_ids"] = [REQ_ONE, UNKNOWN]
    snapshot["prototype"]["transitions"][0]["trigger_element_id"] = UNKNOWN

    tables = design_tables(snapshot, specification())

    assert records(tables["design/tables/concerns.csv"])[0]["requirements"] == (
        f"{UNKNOWN}; REQ-001"
    )
    first = records(tables["design/tables/transitions.csv"])[0]
    assert (first["trigger"], first["trigger_content"]) == (UNKNOWN, "")


def test_an_empty_collection_yields_a_table_with_only_its_header() -> None:
    snapshot = specification()
    snapshot["risks"] = []

    tables = requirements_tables(snapshot)

    assert tables["requirements/tables/risks.csv"] == (
        "code,summary,likelihood,impact,mitigation,review_status,requirements\n"
    )
    assert records(tables["requirements/tables/requirements.csv"])[0]["risks"] == ""


def test_tables_are_deterministic_and_leave_the_snapshots_untouched() -> None:
    requirements_snapshot = specification()
    design_snapshot = package()

    first = knowledge_tables(specification=requirements_snapshot, package=design_snapshot)
    second = knowledge_tables(
        specification=deepcopy(requirements_snapshot), package=deepcopy(design_snapshot)
    )

    assert first == second
    assert requirements_snapshot == specification()
    assert design_snapshot == package()


def test_the_domain_snapshots_produce_all_fourteen_tables() -> None:
    tables = knowledge_tables(
        specification=requirements_version().specification.to_snapshot(),
        package=design_version().package.to_snapshot(),
    )

    assert list(tables) == list(TABLE_COLUMNS)
    assert len(tables) == 14
    assert malformed_tables(tables) == []
    assert identifiers_in(tables) == []
    alternatives = records(tables["design/tables/alternatives.csv"])
    assert [
        (row["code"], row["selected"], row["recommended"], row["archetype"], row["product_name"])
        for row in alternatives
    ] == [
        ("DES-001", "yes", "yes", "", ""),
        ("DES-002", "no", "no", "DASHBOARD", "Reservation desk"),
    ]
    assert {row["alternative"] for row in records(tables["design/tables/palette.csv"])} == {
        "DES-002"
    }
    assert records(tables["design/tables/transitions.csv"]) == [
        {
            "code": "TRN-001",
            "source": "SCR-001",
            "target": "SCR-002",
            "trigger": "ELM-002",
            "trigger_content": "Save reservation",
            "outcome": "The confirmation screen becomes visible.",
        }
    ]
