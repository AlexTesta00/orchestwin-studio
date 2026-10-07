from __future__ import annotations

import copy
from typing import Any

import pytest

from orchestwin.cli.flows import design_delta
from orchestwin.cli.flows.design_delta import DeltaLine, DesignDelta, compare, english

QUADRO = "00000000-0000-4000-8000-0000000000a1"
RIVISTA = "00000000-0000-4000-8000-0000000000a2"
TWIN = "00000000-0000-4000-8000-0000000000b1"
CONTRACT_FIELDS = (
    "title",
    "summary",
    "information_architecture",
    "steps",
    "state",
    "kind",
    "content",
    "accessible_name",
    "options",
    "field_name",
    "required",
    "product_name",
    "direction",
    "palette",
    "choices",
    "tokens",
    "trigger",
    "source",
    "target",
    "outcome",
    "markup",
)
SCREENS = (
    (
        "SCR-001",
        "Pronta al primo conto",
        "EMPTY",
        (
            ("ELM-001", "STATUS", "0", None),
            ("ELM-002", "BUTTON", "AC", "azzera tutto"),
            ("ELM-003", "BUTTON", "1", "1"),
        ),
    ),
    (
        "SCR-002",
        "Il meno resta acceso",
        "DEFAULT",
        (
            ("ELM-004", "STATUS", "19", None),
            ("ELM-005", "BUTTON", "-", "meno"),
            ("ELM-006", "BUTTON", "=", "uguale"),
        ),
    ),
    (
        "SCR-003",
        "Fa 15",
        "SUCCESS",
        (("ELM-007", "STATUS", "15", None), ("ELM-008", "BUTTON", "AC", "azzera tutto")),
    ),
)
TRANSITIONS = (
    ("TRN-001", "1", "SCR-001", "ELM-003", "SCR-002"),
    ("TRN-002", "=", "SCR-002", "ELM-006", "SCR-003"),
    ("TRN-003", "AC", "SCR-003", "ELM-008", "SCR-001"),
)
STYLES = ".quadro { display: grid; gap: var(--vl-gap); color: var(--vl-color-text); }"
SEVEN = ("ELM-001", "BUTTON", "7", "sette")
EIGHT = ("ELM-002", "BUTTON", "8", "otto")
NINE = ("ELM-003", "BUTTON", "9", "nove")


def identifier(version: str, code: str) -> str:
    return f"{version}-{code.lower()}"


def element(version: str, code: str, kind: str, content: str, name: str | None) -> dict[str, Any]:
    return {
        "id": identifier(version, code),
        "code": code,
        "kind": kind,
        "content": content,
        "accessible_name": name,
        "options": [],
        "field_name": None,
        "required": False,
        "requirement_ids": [],
        "user_story_ids": [],
        "acceptance_criterion_ids": [],
    }


def transition(
    version: str, code: str, outcome: str, source: str, trigger: str, target: str
) -> dict[str, Any]:
    return {
        "id": identifier(version, code),
        "code": code,
        "outcome": outcome,
        "source_screen_id": identifier(version, source),
        "trigger_element_id": identifier(version, trigger),
        "target_screen_id": identifier(version, target),
    }


def prototype(version: str) -> dict[str, Any]:
    return {
        "id": identifier(version, "PRT-001"),
        "code": "PRT-001",
        "title": "Calcolatrice Quadro",
        "design_alternative_id": QUADRO,
        "entry_screen_id": identifier(version, "SCR-001"),
        "supported_viewports": ["DESKTOP", "MOBILE"],
        "screens": [
            {
                "id": identifier(version, code),
                "code": code,
                "title": title,
                "state": state,
                "elements": [element(version, *item) for item in items],
                "requirement_ids": [],
                "user_story_ids": [],
                "acceptance_criterion_ids": [],
            }
            for code, title, state, items in SCREENS
        ],
        "transitions": [transition(version, *item) for item in TRANSITIONS],
    }


def markup(title: str) -> str:
    return f'<div class="quadro"><h1 class="titolo">{title}</h1><p>Conto pronto</p></div>'


def mockup() -> dict[str, Any]:
    return {
        "mockup": {
            "contract_version": 1,
            "design_alternative_id": QUADRO,
            "title": "Calcolatrice Quadro",
            "styles": STYLES,
            "screens": [
                {"code": code, "title": title, "state": state, "markup": markup(title)}
                for code, title, state, _ in SCREENS
            ],
        },
        "requirement_ids_by_code": {},
    }


def workflow(code: str, title: str, *steps: str) -> dict[str, Any]:
    return {
        "id": identifier("flow", code),
        "code": code,
        "title": title,
        "steps": list(steps),
        "requirement_ids": [],
        "user_story_ids": [],
    }


def visual(
    name: str, concept: str, layout: str, primary: str, hue: str, gap: str
) -> dict[str, Any]:
    return {
        "catalog_version": 1,
        "product_name": name,
        "rationale": f"La direzione serve a chi apre {name}.",
        "direction": {
            "name": name,
            "concept": concept,
            "axes": {
                "layout": layout,
                "shape": "HEAVY_FRAME",
                "type": "DISPLAY",
                "colour": "FIELDS",
                "density": "SPACIOUS",
            },
            "rules": ["Il display occupa un terzo dell'altezza."],
            "typicality": 6,
            "candidates": 5,
            "vocabulary_version": 1,
        },
        "palette": {"primary": primary, "background": "#020202"},
        "choices": {"archetype": "FOCUS_MODE", "hue_family": hue},
        "tokens": {"--vl-color-primary": primary, "--vl-gap": gap},
        "twin_fit": [],
    }


def alternatives() -> list[dict[str, Any]]:
    return [
        {
            "id": QUADRO,
            "code": "DES-001",
            "title": "Quadro strumenti",
            "summary": "Calcolatrice a schermo intero con il display incorniciato.",
            "rationale": "Lettura a colpo d'occhio.",
            "information_architecture": ["Display in alto", "Tastiera a quattro colonne"],
            "workflows": [
                workflow(
                    "FLOW-001",
                    "Conto in catena con il solo pollice",
                    "Digita 12",
                    "Premi +",
                    "Digita 7",
                ),
                workflow("FLOW-002", "Apertura senza rete", "Apri la pagina", "Fai un conto"),
            ],
            "visual_language": visual(
                "Calcolatrice Quadro",
                "Il display è il tassello più grande.",
                "MOSAIC",
                "#ffbb69",
                "AMBER",
                "24px",
            ),
        },
        {
            "id": RIVISTA,
            "code": "DES-002",
            "title": "Pagina di rivista",
            "summary": "Calcolatrice intatta sul telefono, pagina calma su computer.",
            "rationale": "Nessuna sorpresa per chi arriva da iPhone.",
            "information_architecture": ["Calcolatrice al centro", "Note a margine"],
            "workflows": [
                workflow("FLOW-001", "Conto rapido sul telefono", "Digita 12", "Premi +"),
                workflow("FLOW-003", "Conto con la tastiera fisica", "Digita 12", "Premi Invio"),
            ],
            "visual_language": visual(
                "Calcolatrice Rivista",
                "Una pagina calma e ariosa.",
                "EDITORIAL",
                "#1d4ed8",
                "BLUE",
                "16px",
            ),
        },
    ]


def critique(code: str, number: int, alternative: str, verdict: str) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-4000-8000-0000000000c{number}",
        "code": code,
        "kind": "SYNTHETIC_USER_TWIN",
        "design_alternative_id": alternative,
        "user_twin_reference": {"twin_id": TWIN, "name": "Chi passa da iPhone"},
        "verdict": verdict,
        "quote": f"{verdict}: i tasti sono al posto giusto.",
        "concerns": [],
    }


def concern(code: str, number: int, summary: str) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-4000-8000-0000000000e{number}",
        "code": code,
        "summary": summary,
        "mitigation": "Misurare il contrasto prima di pubblicare.",
        "requirement_ids": [],
        "design_alternative_ids": [QUADRO, RIVISTA],
    }


def package(version: str = "v1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project_id": "00000000-0000-4000-8000-000000000001",
        "alternatives": alternatives(),
        "owner_selected_alternative_id": QUADRO,
        "recommended_alternative_id": RIVISTA,
        "prototype": prototype(version),
        "generated_mockup": mockup(),
        "critiques": [
            critique("CRQ-001", 1, QUADRO, "Riconoscibile"),
            critique("CRQ-002", 2, RIVISTA, "Familiare"),
        ],
        "concerns": [concern("DRK-001", 1, "Il contrasto dei tasti grigi è basso.")],
        "open_questions": ["Quale hosting gratuito con HTTPS verrà usato?"],
        "grounding": {
            "requirement_ids": ["00000000-0000-4000-8000-0000000000d1"],
            "catalog": {"version": 1},
        },
    }


def line(
    kind: str,
    subject: str,
    code: str | None,
    title: str | None,
    *,
    screen: str | None = None,
    fields: tuple[str, ...] = (),
    before: str | None = None,
    after: str | None = None,
) -> DeltaLine:
    return DeltaLine(
        kind=kind,
        subject=subject,
        code=code,
        title=title,
        screen=screen,
        fields=fields,
        before=before,
        after=after,
    )


def screen_of(document: dict[str, Any], code: str) -> dict[str, Any]:
    return next(item for item in document["prototype"]["screens"] if item["code"] == code)


def about(delta: DesignDelta, subject: str) -> list[DeltaLine]:
    return [item for item in delta.lines if item.subject == subject]


def put(document: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    for key in path[:-1]:
        document = document[key]
    document[path[-1]] = value


def keypad(*items: tuple[str, str, str, str | None]) -> dict[str, Any]:
    return {
        "prototype": {
            "screens": [
                {
                    "id": identifier("v1", "SCR-001"),
                    "code": "SCR-001",
                    "title": "Tastiera",
                    "state": "DEFAULT",
                    "elements": [element("v1", *item) for item in items],
                }
            ],
            "transitions": [],
        }
    }


def renumbered_keys(version: str) -> list[dict[str, Any]]:
    return [
        element(version, "ELM-017", "STATUS", "15", None),
        element(version, "ELM-018", "BUTTON", "AC", "azzera tutto"),
    ]


def test_equal_packages_have_no_differences_even_with_new_identifiers_and_spaces() -> None:
    target = package("v2")
    screen_of(target, "SCR-001")["title"] = "Pronta  al primo\nconto "
    target["alternatives"][0]["workflows"][0]["steps"][0] = "  Digita\t12 "
    target["generated_mockup"]["mockup"]["screens"][0]["markup"] = markup(
        "Pronta al primo conto"
    ).replace(" ", "\n    ")

    delta = compare(package("v1"), target)

    assert delta == DesignDelta(lines=(), other=0, from_code="DES-001", to_code="DES-001")
    assert delta.empty is True


def test_a_new_chosen_alternative_comes_first_and_the_two_alternatives_are_compared() -> None:
    target = package()
    target["owner_selected_alternative_id"] = RIVISTA

    delta = compare(package(), target)

    assert delta.lines == (
        line(
            "CHANGE", "SELECTION", "DES-002", "Pagina di rivista", before="DES-001", after="DES-002"
        ),
        line(
            "CHANGE",
            "ALTERNATIVE",
            "DES-002",
            "Pagina di rivista",
            fields=("title", "summary", "information_architecture"),
        ),
        line(
            "CHANGE", "WORKFLOW", "FLOW-001", "Conto rapido sul telefono", fields=("title", "steps")
        ),
        line("REMOVE", "WORKFLOW", "FLOW-002", "Apertura senza rete"),
        line("ADD", "WORKFLOW", "FLOW-003", "Conto con la tastiera fisica"),
        line(
            "CHANGE",
            "VISUAL",
            None,
            None,
            fields=("product_name", "direction", "palette", "choices", "tokens"),
        ),
    )
    assert (delta.from_code, delta.to_code, delta.other) == ("DES-001", "DES-002", 0)
    assert english(delta.lines[0]) == (
        "Chosen alternative: DES-002 «Pagina di rivista» instead of DES-001"
    )


def test_the_chosen_alternative_falls_back_to_the_recommended_one_and_then_to_the_first() -> None:
    recommended = package()
    del recommended["owner_selected_alternative_id"]
    first = package()
    first["owner_selected_alternative_id"] = "00000000-0000-4000-8000-0000000000ff"
    first["recommended_alternative_id"] = None

    delta = compare(recommended, first)

    assert (delta.from_code, delta.to_code) == ("DES-002", "DES-001")
    assert delta.lines[0] == line(
        "CHANGE", "SELECTION", "DES-001", "Quadro strumenti", before="DES-002", after="DES-001"
    )
    assert delta.other == 1


def test_screens_added_removed_and_changed() -> None:
    target = package()
    screens = target["prototype"]["screens"]
    screens[0]["state"] = "DEFAULT"
    screens[1]["title"] = "Il meno resta evidenziato"
    del screens[2]
    screens.append(
        {
            "id": identifier("v1", "SCR-004"),
            "code": "SCR-004",
            "title": "Non si divide per zero",
            "state": "ERROR",
            "elements": [element("v1", "ELM-009", "STATUS", "Impossibile", None)],
        }
    )

    delta = compare(package(), target)

    assert about(delta, "SCREEN") == [
        line("CHANGE", "SCREEN", "SCR-001", "Pronta al primo conto", fields=("state",)),
        line("CHANGE", "SCREEN", "SCR-002", "Il meno resta evidenziato", fields=("title",)),
        line("REMOVE", "SCREEN", "SCR-003", "Fa 15"),
        line("ADD", "SCREEN", "SCR-004", "Non si divide per zero"),
    ]
    assert about(delta, "ELEMENT") == []
    assert about(delta, "TRANSITION") == [
        line("CHANGE", "TRANSITION", "TRN-002", "=", fields=("target",)),
        line("CHANGE", "TRANSITION", "TRN-003", "AC", fields=("trigger", "source")),
    ]
    assert [english(item) for item in about(delta, "SCREEN")] == [
        "Screen SCR-001 «Pronta al primo conto»: changed (state)",
        "Screen SCR-002 «Il meno resta evidenziato»: changed (title)",
        "Screen SCR-003 «Fa 15»: removed",
        "Screen SCR-004 «Non si divide per zero»: added",
    ]


def test_elements_added_removed_and_changed_carry_their_screen() -> None:
    target = package()
    first = screen_of(target, "SCR-001")["elements"]
    first[0].update(options=["12", "19"], field_name="conto", required=True)
    first[1].update(content="C", accessible_name="cancella")
    second = screen_of(target, "SCR-002")["elements"]
    del second[0]
    second.append(element("v1", "ELM-009", "BUTTON", "%", "percentuale"))
    second.append(element("v1", "ELM-010", "LINK", " ", "Cronologia"))

    delta = compare(package(), target)

    assert delta.lines == (
        line(
            "CHANGE",
            "ELEMENT",
            "ELM-001",
            "0",
            screen="SCR-001",
            fields=("options", "field_name", "required"),
        ),
        line(
            "CHANGE",
            "ELEMENT",
            "ELM-002",
            "C",
            screen="SCR-001",
            fields=("content", "accessible_name"),
        ),
        line("REMOVE", "ELEMENT", "ELM-004", "19", screen="SCR-002"),
        line("ADD", "ELEMENT", "ELM-009", "%", screen="SCR-002"),
        line("ADD", "ELEMENT", "ELM-010", "Cronologia", screen="SCR-002"),
    )
    assert english(delta.lines[1]) == (
        "Screen SCR-001: element ELM-002 «C» changed (content, accessible name)"
    )
    assert english(delta.lines[3]) == "Screen SCR-002: element ELM-009 «%» added"


def test_a_transition_is_compared_by_the_codes_its_identifiers_point_to() -> None:
    target = package("v2")
    moves = target["prototype"]["transitions"]
    moves[0].update(trigger_element_id=identifier("v2", "ELM-002"), outcome="AC")
    moves[1]["target_screen_id"] = identifier("v2", "SCR-001")
    del moves[2]
    moves.append(transition("v2", "TRN-004", "%", "SCR-003", "ELM-008", "SCR-002"))

    delta = compare(package("v1"), target)

    assert delta.lines == (
        line("CHANGE", "TRANSITION", "TRN-001", "AC", fields=("trigger", "outcome")),
        line("CHANGE", "TRANSITION", "TRN-002", "=", fields=("target",)),
        line("REMOVE", "TRANSITION", "TRN-003", "AC"),
        line("ADD", "TRANSITION", "TRN-004", "%"),
    )
    assert english(delta.lines[1]) == "Transition TRN-002 «=»: changed (target)"


def test_identifiers_that_resolve_to_nothing_give_at_most_a_line() -> None:
    lost = transition("v9", "TRN-009", "?", "SCR-009", "ELM-099", "SCR-009")
    base = package()
    base["prototype"]["transitions"].append(copy.deepcopy(lost))
    target = package()
    target["prototype"]["transitions"].append(lost)
    target["prototype"]["transitions"][0]["trigger_element_id"] = "sconosciuto"

    delta = compare(base, target)

    assert delta.lines == (line("CHANGE", "TRANSITION", "TRN-001", "1", fields=("trigger",)),)


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (
            (
                SEVEN,
                EIGHT,
                ("ELM-003", "BUTTON", "⌫", "cancella l'ultima cifra"),
                ("ELM-004", "BUTTON", "9", "nove"),
            ),
            [line("ADD", "ELEMENT", "ELM-003", "⌫", screen="SCR-001")],
        ),
        (
            (SEVEN, EIGHT, ("ELM-003", "BUTTON", "Nove", "nove")),
            [line("CHANGE", "ELEMENT", "ELM-003", "Nove", screen="SCR-001", fields=("content",))],
        ),
        (
            (SEVEN, ("ELM-002", "BUTTON", "9", "nove")),
            [line("REMOVE", "ELEMENT", "ELM-002", "8", screen="SCR-001")],
        ),
        (
            (SEVEN, EIGHT, ("ELM-003", "LINK", "9", "nove")),
            [
                line("ADD", "ELEMENT", "ELM-003", "9", screen="SCR-001"),
                line("REMOVE", "ELEMENT", "ELM-003", "9", screen="SCR-001"),
            ],
        ),
    ],
)
def test_elements_are_paired_by_what_they_show_before_their_codes(
    after: tuple[tuple[str, str, str, str | None], ...], expected: list[DeltaLine]
) -> None:
    delta = compare(keypad(SEVEN, EIGHT, NINE), keypad(*after))

    assert list(delta.lines) == expected


def test_each_element_is_paired_once() -> None:
    twice = keypad(SEVEN, ("ELM-002", "BUTTON", "7", "sette"), ("ELM-003", "BUTTON", "8", "otto"))
    once = keypad(SEVEN, ("ELM-002", "BUTTON", "8", "otto"))

    removed = compare(twice, once)
    added = compare(once, twice)

    assert removed.lines == (line("REMOVE", "ELEMENT", "ELM-002", "7", screen="SCR-001"),)
    assert added.lines == (line("ADD", "ELEMENT", "ELM-002", "7", screen="SCR-001"),)


@pytest.mark.parametrize(
    ("code", "outcome", "expected"),
    [
        ("TRN-009", "AC", ()),
        (
            "TRN-003",
            "Azzera",
            (line("CHANGE", "TRANSITION", "TRN-003", "Azzera", fields=("outcome",)),),
        ),
    ],
)
def test_renumbered_elements_leave_the_transitions_they_trigger_alone(
    code: str, outcome: str, expected: tuple[DeltaLine, ...]
) -> None:
    target = package("v2")
    screen_of(target, "SCR-003")["elements"] = renumbered_keys("v2")
    target["prototype"]["transitions"][2] = transition(
        "v2", code, outcome, "SCR-003", "ELM-018", "SCR-001"
    )

    delta = compare(package("v1"), target)

    assert (delta.lines, delta.other) == (expected, 0)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("TRN-002", [line("CHANGE", "TRANSITION", "TRN-002", "=", fields=("target",))]),
        (
            "TRN-005",
            [
                line("REMOVE", "TRANSITION", "TRN-002", "="),
                line("ADD", "TRANSITION", "TRN-005", "="),
            ],
        ),
    ],
)
def test_a_transition_that_leads_elsewhere_changes_only_under_the_same_code(
    code: str, expected: list[DeltaLine]
) -> None:
    target = package()
    target["prototype"]["transitions"][1] = transition(
        "v1", code, "=", "SCR-002", "ELM-006", "SCR-001"
    )

    assert list(compare(package(), target).lines) == expected


def test_a_mockup_screen_inserted_before_the_others_is_one_addition() -> None:
    target = package()
    screens = target["generated_mockup"]["mockup"]["screens"]
    screens[1]["code"], screens[2]["code"] = "SCR-003", "SCR-004"
    screens.insert(
        1,
        {"code": "SCR-002", "title": "Parziale", "state": "DEFAULT", "markup": markup("Parziale")},
    )

    assert compare(package(), target).lines == (line("ADD", "MOCKUP", "SCR-002", "Parziale"),)


def test_a_workflow_added_and_one_changed() -> None:
    target = package()
    flows = target["alternatives"][0]["workflows"]
    flows[0]["steps"].append("Premi = e leggi 19")
    flows.append(workflow("FLOW-003", "Divisione per zero", "Digita 15", "Dividi per 0"))

    delta = compare(package(), target)

    assert delta.lines == (
        line(
            "CHANGE",
            "WORKFLOW",
            "FLOW-001",
            "Conto in catena con il solo pollice",
            fields=("steps",),
        ),
        line("ADD", "WORKFLOW", "FLOW-003", "Divisione per zero"),
    )
    assert delta.other == 0
    assert english(delta.lines[1]) == "Workflow FLOW-003 «Divisione per zero»: added"


@pytest.mark.parametrize(
    ("changes", "fields"),
    [
        (
            [(("palette", "primary"), "#ff9f1c"), (("tokens", "--vl-color-primary"), "#ff9f1c")],
            ("palette", "tokens"),
        ),
        ([(("product_name",), "Calcolatrice Ambra")], ("product_name",)),
        ([(("direction", "concept"), "Il display resta sobrio.")], ("direction",)),
        ([(("direction", "axes", "layout"), "BANDS")], ("direction",)),
        ([(("choices", "hue_family"), "TEAL")], ("choices",)),
        (
            [
                (("direction", "rules"), ["Una regola nuova."]),
                (("rationale",), "Una ragione nuova."),
            ],
            (),
        ),
    ],
)
def test_the_visual_language_changes_in_a_single_line(
    changes: list[tuple[tuple[str, ...], object]], fields: tuple[str, ...]
) -> None:
    target = package()
    for path, value in changes:
        put(target["alternatives"][0]["visual_language"], path, value)

    delta = compare(package(), target)

    assert delta.lines == ((line("CHANGE", "VISUAL", None, None, fields=fields),) if fields else ())


def test_a_redrawn_mockup_and_new_styles() -> None:
    target = package()
    drawn = target["generated_mockup"]["mockup"]
    drawn["screens"][0]["markup"] = markup("Pronta").replace("Conto pronto", "0")
    drawn["screens"][1]["state"] = "SUCCESS"
    del drawn["screens"][2]
    drawn["screens"].append(
        {"code": "SCR-006", "title": "Scientifica", "state": "DEFAULT", "markup": markup("Sci")}
    )
    drawn["styles"] = STYLES.replace("grid", "flex")

    delta = compare(package(), target)

    assert delta.lines == (
        line("CHANGE", "MOCKUP", "SCR-001", "Pronta al primo conto", fields=("markup",)),
        line("CHANGE", "MOCKUP", "SCR-002", "Il meno resta acceso", fields=("state",)),
        line("REMOVE", "MOCKUP", "SCR-003", "Fa 15"),
        line("ADD", "MOCKUP", "SCR-006", "Scientifica"),
        line("CHANGE", "STYLES", None, None),
    )
    assert [english(item) for item in delta.lines] == [
        "Mockup of screen SCR-001 «Pronta al primo conto»: redrawn",
        "Mockup of screen SCR-002 «Il meno resta acceso»: redrawn",
        "Mockup of screen SCR-003 «Fa 15»: removed",
        "Mockup of screen SCR-006 «Scientifica»: added",
        "Mockup styles: changed",
    ]


def test_other_counts_what_needs_no_work_in_the_code() -> None:
    target = package()
    target["critiques"].reverse()
    target["critiques"][0]["verdict"] = "Non la riconosce"
    target["concerns"].append(concern("DRK-002", 2, "La virgola è piccola."))
    target["open_questions"].append("Serve anche la modalità scientifica?")
    target["recommended_alternative_id"] = QUADRO
    target["grounding"]["requirement_ids"].append("00000000-0000-4000-8000-0000000000d2")
    target["alternatives"][1]["summary"] = "Una pagina ancora più calma."

    delta = compare(package(), target)

    assert delta.lines == ()
    assert delta.empty is True
    assert delta.other == 6


def test_other_matches_objects_by_identifier_or_by_code() -> None:
    target = package()
    target["critiques"][0]["id"] = "00000000-0000-4000-8000-0000000000c9"
    target["critiques"][1]["code"] = "CRQ-009"
    target["alternatives"][1]["id"] = "00000000-0000-4000-8000-0000000000a9"

    delta = compare(package(), target)

    assert delta.lines == ()
    assert delta.other == 3


def test_lines_follow_the_order_of_the_contract() -> None:
    target = package("v2")
    target["owner_selected_alternative_id"] = RIVISTA
    screen_of(target, "SCR-001")["elements"][2]["accessible_name"] = "uno"
    second = screen_of(target, "SCR-002")
    second["title"] = "Il meno resta evidenziato"
    second["elements"][1]["content"] = "meno"
    screen_of(target, "SCR-003")["elements"].extend(
        [
            element("v2", "ELM-1000", "BUTTON", "C", "cancella"),
            element("v2", "ELM-999", "BUTTON", "%", "percentuale"),
        ]
    )
    target["prototype"]["transitions"][0]["outcome"] = "Digita 1"
    target["generated_mockup"]["mockup"]["screens"][2]["markup"] = markup("Fa 15!")
    target["generated_mockup"]["mockup"]["styles"] += " .tasto { min-height: 52px; }"
    unchanged = copy.deepcopy(target)

    delta = compare(package("v1"), target)

    assert [(item.subject, item.code, item.screen) for item in delta.lines] == [
        ("SELECTION", "DES-002", None),
        ("ALTERNATIVE", "DES-002", None),
        ("WORKFLOW", "FLOW-001", None),
        ("WORKFLOW", "FLOW-002", None),
        ("WORKFLOW", "FLOW-003", None),
        ("VISUAL", None, None),
        ("ELEMENT", "ELM-003", "SCR-001"),
        ("SCREEN", "SCR-002", None),
        ("ELEMENT", "ELM-005", "SCR-002"),
        ("ELEMENT", "ELM-999", "SCR-003"),
        ("ELEMENT", "ELM-1000", "SCR-003"),
        ("TRANSITION", "TRN-001", None),
        ("MOCKUP", "SCR-003", None),
        ("STYLES", None, None),
    ]
    assert design_delta.FIELDS == CONTRACT_FIELDS
    assert all(set(item.fields) <= set(CONTRACT_FIELDS) for item in delta.lines)
    assert all((item.before, item.after) == (None, None) for item in delta.lines[1:])
    assert target == unchanged


def test_long_titles_are_cut_at_eighty_characters() -> None:
    target = package()
    first = screen_of(target, "SCR-001")
    first["title"] = "Pronta " * 20
    first["elements"][1]["content"] = "Azzera\n" * 30
    exact = "Fa " * 26 + "15"
    screen_of(target, "SCR-003")["title"] = exact

    delta = compare(package(), target)

    cut = "Pronta " * 11 + "Pr…"
    assert delta.lines == (
        line("CHANGE", "SCREEN", "SCR-001", cut, fields=("title",)),
        line(
            "CHANGE",
            "ELEMENT",
            "ELM-002",
            "Azzera " * 11 + "Az…",
            screen="SCR-001",
            fields=("content",),
        ),
        line("CHANGE", "SCREEN", "SCR-003", exact, fields=("title",)),
    )
    assert (len(cut), len(exact)) == (80, 80)


def test_packages_without_prototype_or_mockup() -> None:
    full = package()
    bare = package()
    del bare["prototype"]
    bare["generated_mockup"] = None
    screens = ("SCR-001", "SCR-002", "SCR-003")
    transitions = ("TRN-001", "TRN-002", "TRN-003")

    def kinds(kind: str) -> list[tuple[str, str, str | None]]:
        return [
            *((kind, "SCREEN", code) for code in screens),
            *((kind, "TRANSITION", code) for code in transitions),
            *((kind, "MOCKUP", code) for code in screens),
            ("CHANGE", "STYLES", None),
        ]

    added = compare(bare, full)
    removed = compare(full, bare)

    assert [(item.kind, item.subject, item.code) for item in added.lines] == kinds("ADD")
    assert [(item.kind, item.subject, item.code) for item in removed.lines] == kinds("REMOVE")
    assert [item.title for item in about(added, "TRANSITION")] == ["1", "=", "AC"]
    assert compare(bare, copy.deepcopy(bare)) == DesignDelta(
        lines=(), other=0, from_code="DES-001", to_code="DES-001"
    )


@pytest.mark.parametrize(
    "strange",
    [
        {},
        {
            "alternatives": "DES-001",
            "prototype": [],
            "generated_mockup": "mockup",
            "critiques": {"CRQ-001": {}},
        },
        {
            "alternatives": [None, 3, {"code": 7, "workflows": "FLOW-001", "visual_language": []}],
            "owner_selected_alternative_id": 12,
            "recommended_alternative_id": ["DES-001"],
        },
        {
            "prototype": {
                "screens": [
                    None,
                    {"code": None},
                    {
                        "code": "SCR-001",
                        "id": 4,
                        "elements": [1, {"code": "ELM-001", "options": "a"}],
                    },
                ],
                "transitions": [
                    {"code": "TRN-001", "source_screen_id": 4, "trigger_element_id": None},
                    "TRN-002",
                ],
            }
        },
        {"generated_mockup": {"mockup": {"screens": {"SCR-001": {}}, "styles": 12}}},
        {
            "alternatives": [
                {
                    "id": QUADRO,
                    "code": "DES-001",
                    "title": None,
                    "information_architecture": [None, 2],
                    "visual_language": {"direction": "Quadro", "palette": [1]},
                }
            ],
            "concerns": [None, "DRK-001"],
            "open_questions": "Quale hosting?",
            "grounding": [],
        },
    ],
)
def test_unexpected_shapes_give_no_exception(strange: dict[str, Any]) -> None:
    for base, target in ((strange, package()), (package(), strange)):
        delta = compare(base, target)
        assert all(english(item) for item in delta.lines)

    same = compare(strange, copy.deepcopy(strange))

    assert (same.empty, same.other) == (True, 0)


@pytest.mark.parametrize(
    ("delta_line", "text"),
    [
        (
            line(
                "CHANGE",
                "SELECTION",
                "DES-002",
                "Pagina di rivista",
                before="DES-001",
                after="DES-002",
            ),
            "Chosen alternative: DES-002 «Pagina di rivista» instead of DES-001",
        ),
        (
            line("CHANGE", "SELECTION", "DES-001", "Quadro strumenti", after="DES-001"),
            "Chosen alternative: DES-001 «Quadro strumenti»",
        ),
        (
            line(
                "CHANGE",
                "ALTERNATIVE",
                "DES-001",
                "Quadro strumenti",
                fields=("summary", "information_architecture"),
            ),
            "Alternative DES-001 «Quadro strumenti»: changed (summary, information architecture)",
        ),
        (
            line("ADD", "WORKFLOW", "WFL-003", "Divisione per zero"),
            "Workflow WFL-003 «Divisione per zero»: added",
        ),
        (
            line("REMOVE", "WORKFLOW", "FLOW-002", "Apertura senza rete"),
            "Workflow FLOW-002 «Apertura senza rete»: removed",
        ),
        (
            line("CHANGE", "VISUAL", None, None, fields=("palette", "tokens")),
            "Visual language: changed (palette, tokens)",
        ),
        (
            line("CHANGE", "VISUAL", None, None, fields=("product_name", "direction")),
            "Visual language: changed (product name, direction)",
        ),
        (
            line("CHANGE", "SCREEN", "SCR-003", "Fa 15", fields=("title",)),
            "Screen SCR-003 «Fa 15»: changed (title)",
        ),
        (line("ADD", "SCREEN", "SCR-009", None), "Screen SCR-009: added"),
        (
            line(
                "CHANGE",
                "ELEMENT",
                "ELM-004",
                "AC",
                screen="SCR-001",
                fields=("content", "accessible_name"),
            ),
            "Screen SCR-001: element ELM-004 «AC» changed (content, accessible name)",
        ),
        (
            line("ADD", "ELEMENT", "ELM-031", "%", screen="SCR-002"),
            "Screen SCR-002: element ELM-031 «%» added",
        ),
        (
            line("REMOVE", "ELEMENT", "ELM-032", "Cronologia", screen="SCR-002"),
            "Screen SCR-002: element ELM-032 «Cronologia» removed",
        ),
        (
            line("CHANGE", "ELEMENT", "ELM-007", None, fields=("field_name", "required")),
            "Element ELM-007: changed (field name, required)",
        ),
        (
            line("CHANGE", "TRANSITION", "TRN-002", "=", fields=("target",)),
            "Transition TRN-002 «=»: changed (target)",
        ),
        (
            line("CHANGE", "MOCKUP", "SCR-001", "Pronta al primo conto", fields=("markup",)),
            "Mockup of screen SCR-001 «Pronta al primo conto»: redrawn",
        ),
        (
            line("ADD", "MOCKUP", "SCR-006", "Scientifica"),
            "Mockup of screen SCR-006 «Scientifica»: added",
        ),
        (line("CHANGE", "STYLES", None, None), "Mockup styles: changed"),
    ],
)
def test_english_says_each_difference_in_one_line(delta_line: DeltaLine, text: str) -> None:
    assert english(delta_line) == text


def test_a_delta_is_empty_only_without_lines() -> None:
    styles = line("CHANGE", "STYLES", None, None)

    assert DesignDelta(lines=(), other=4, from_code="DES-001", to_code="DES-001").empty is True
    assert DesignDelta(lines=(styles,), other=0, from_code=None, to_code=None).empty is False
