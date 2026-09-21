import pytest

from orchestwin.web_execution.journeys import derive_static_journey, sample_value


def element(code, kind, content, **extra):
    return {
        "id": f"id-{code}",
        "code": code,
        "kind": kind,
        "content": content,
        "accessible_name": None,
        **extra,
    }


def prototype(*, back=True, inputs=1, transition=True):
    entry_elements = [element("ELM-001", "HEADING", "Aggiungi un ospite")]
    for index in range(inputs):
        entry_elements.append(
            element(
                f"ELM-10{index}",
                "TEXT_INPUT",
                f"Campo {index}",
                field_name="guest_name" if index == 0 else f"field_{index}",
                required=True,
            )
        )
    entry_elements.append(element("ELM-003", "BUTTON", "Aggiungi"))
    target_elements = [
        element("ELM-006", "HEADING", "Ospite aggiunto"),
        element("ELM-007", "TEXT", "Esempio: 1. Mario Rossi"),
        element("ELM-008", "LINK", "Torna"),
    ]
    transitions = []
    if transition:
        transitions.append(
            {"trigger_element_id": "id-ELM-003", "source_screen_id": "s1", "target_screen_id": "s2"}
        )
    if back:
        transitions.append(
            {"trigger_element_id": "id-ELM-008", "source_screen_id": "s2", "target_screen_id": "s1"}
        )
    return {
        "entry_screen_id": "s1",
        "screens": [
            {"id": "s1", "code": "SCR-001", "title": "Inserimento", "elements": entry_elements},
            {"id": "s2", "code": "SCR-002", "title": "Conferma", "elements": target_elements},
        ],
        "transitions": transitions,
    }


def kinds(result):
    return [step["action"]["kind"] for step in result["steps"]]


def test_journey_with_return_transition_fills_activates_by_keyboard_and_returns():
    result = derive_static_journey(prototype())
    assert result["status"] == "DERIVED"
    assert kinds(result) == [
        "fill",
        "press",
        "expect_not_text",
        "expect_contains",
        "click",
        "expect_text",
    ]
    actions = result["browser_interactions"][0]["actions"]
    assert actions[0] == {"kind": "fill", "selector": "#ELM-100", "value": "Giulia Verdi"}
    assert actions[1] == {"kind": "press", "selector": "#ELM-003", "value": "Enter"}
    assert actions[2] == {
        "kind": "expect_not_text",
        "selector": "#ELM-007",
        "value": "Esempio: 1. Mario Rossi",
    }
    assert actions[3] == {
        "kind": "expect_contains",
        "selector": "#ELM-007",
        "value": "Giulia Verdi",
    }
    assert actions[4] == {"kind": "click", "selector": "#ELM-008", "value": None}
    assert actions[5] == {
        "kind": "expect_text",
        "selector": "#ELM-001",
        "value": "Aggiungi un ospite",
    }
    assert result["steps"][4]["screen_code"] == "SCR-002"
    assert result["steps"][5]["element_label"] == "Aggiungi un ospite"
    assert (
        result["declared_routes"] == [] and result["browser_interactions"][0]["route_id"] == "root"
    )


def test_journey_without_return_uses_field_focus_as_pointer_check():
    result = derive_static_journey(prototype(back=False))
    assert kinds(result) == [
        "click",
        "expect_text",
        "fill",
        "press",
        "expect_not_text",
        "expect_contains",
    ]
    assert result["browser_interactions"][0]["actions"][0]["selector"] == "#ELM-100"


def test_journey_respects_the_eight_action_limit_by_dropping_the_contains_check():
    result = derive_static_journey(prototype(inputs=4))
    assert result["status"] == "DERIVED"
    assert len(result["steps"]) == 8
    assert "expect_contains" not in kinds(result)
    assert derive_static_journey(prototype(inputs=5))["reason"] == "TOO_MANY_ENTRY_INPUTS"


def test_journey_is_not_derivable_without_an_entry_transition():
    assert (
        derive_static_journey(prototype(transition=False))["reason"] == "ENTRY_TRANSITION_MISSING"
    )


@pytest.mark.parametrize(
    "kind,field_name,content,options,expected",
    [
        ("TEXT_INPUT", "guest_name", "Nome ospite", (), "Giulia Verdi"),
        ("TEXT_INPUT", "email", "E-mail", (), "giulia.verdi@example.com"),
        ("TEXT_INPUT", "amount", "Importo", (), "12"),
        ("TEXT_INPUT", "start_date", "Data inizio", (), "2026-10-01"),
        ("SELECT", "mode", "Operazione", ("Area", "Perimetro"), "Area"),
    ],
)
def test_sample_values_follow_the_field_meaning(kind, field_name, content, options, expected):
    assert (
        sample_value(element("ELM-1", kind, content, field_name=field_name, options=options))
        == expected
    )
