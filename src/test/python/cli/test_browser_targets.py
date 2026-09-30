from __future__ import annotations

import pytest

from orchestwin.cli.browser import (
    BrowserError,
    Element,
    PageSnapshot,
    matches_text,
    normalized,
    resolve_target,
    snapshot_from_document,
)
from orchestwin.cli.browser import page as page_module
from orchestwin.cli.browser import snapshot as snapshot_module
from orchestwin.cli.browser import targets as targets_module
from orchestwin.cli.browser.bidi import KEYS as BIDI_KEYS
from orchestwin.cli.browser.cdp import KEYS as CDP_KEYS
from orchestwin.knowledge import state

from .support.browsers import element, elements, page_snapshot


def test_the_constants_match_the_constants_of_the_studio() -> None:
    assert page_module.TEST_ROLES == state.TEST_ROLES
    assert page_module.TEST_KEYS == state.TEST_KEYS
    assert page_module.MAX_DETAIL_LENGTH == state.MAX_STEP_DETAIL_LENGTH
    assert page_module.MAX_BROWSER_VERSION_LENGTH == state.MAX_BROWSER_VERSION_LENGTH
    assert targets_module.INTERACTIVE_ROLES == state.INTERACTIVE_ROLES
    assert snapshot_module.MAX_SNAPSHOT_ELEMENTS == state.MAX_SNAPSHOT_ELEMENTS
    assert snapshot_module.MAX_SNAPSHOT_TEXT_LENGTH == state.MAX_SNAPSHOT_TEXT_LENGTH
    assert snapshot_module.MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH == state.MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
    assert snapshot_module.MAX_SNAPSHOT_OPTIONS == state.MAX_SNAPSHOT_OPTIONS
    assert snapshot_module.MAX_TARGET_NAME_LENGTH == state.MAX_TARGET_NAME_LENGTH
    assert snapshot_module.MAX_VALUE_LENGTH == state.MAX_STEP_VALUE_LENGTH


def test_every_role_the_page_can_give_is_a_role_of_the_contract() -> None:
    given = {role for role in snapshot_module.ROLE_OF.values() if role}

    assert given <= set(state.TEST_ROLES)
    assert {"text", "listitem", "cell", "status"} <= given
    assert set(snapshot_module.FIRST_ROLES) <= set(state.TEST_ROLES)
    assert set(snapshot_module.LEAF_ROLES) <= set(state.TEST_ROLES)
    assert set(snapshot_module.BLOCK_ROLES) <= set(state.TEST_ROLES)
    assert set(snapshot_module.CONTENT_ROLES) <= set(state.TEST_ROLES)


def test_every_key_of_the_contract_can_be_pressed_in_both_protocols() -> None:
    assert set(state.TEST_KEYS) <= set(CDP_KEYS)
    assert set(state.TEST_KEYS) <= set(BIDI_KEYS)
    assert set(CDP_KEYS) == set(BIDI_KEYS)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Città   di\tPerù\n", "citta di peru"),
        ("ÉLAN VITAL", "elan vital"),
        ("Crème" + chr(0x00A0) + "brûlée", "creme brulee"),
        (chr(0xFB01) + "ne " + chr(0xFF21) + chr(0xFF22), "fine ab"),
        ("", ""),
    ],
)
def test_texts_are_compared_without_case_accents_or_extra_spaces(text: str, expected: str) -> None:
    assert normalized(text) == expected


def test_a_text_is_visible_when_it_is_inside_the_page_text() -> None:
    page_text = "Ordine   di Anna: Taglia GRANDE con regalo"

    assert matches_text(page_text, "anna: taglia grande")
    assert matches_text(page_text, "  Grande   con ")
    assert matches_text("Città di Perù", "citta di peru")
    assert not matches_text(page_text, "piccola")
    assert not matches_text(page_text, "Anna Taglia")


SNAPSHOT = page_snapshot(
    *elements(
        ("heading", "Nuovo ordine"),
        ("text", "Salva le modifiche prima di uscire"),
        ("button", "Salva bozza"),
        ("button", "Salva"),
        ("link", "Salvataggi precedenti"),
        ("textbox", "Nome"),
        ("text", "Nome del cliente"),
        ("textbox", "Nome del cliente"),
        ("combobox", "Città"),
        ("listitem", "Ordine 1"),
        ("button", ""),
        ("checkbox", "OK"),
    )
)


def resolved(target: dict[str, object], *, action: str | None = None) -> int | None:
    found = resolve_target(SNAPSHOT, target, action=action)
    return None if found is None else found.index


def test_an_equal_name_wins_over_a_name_that_only_starts_with_the_target() -> None:
    assert resolved({"role": "button", "name": "Salva"}) == 3
    assert resolved({"role": None, "name": "salva"}) == 3


def test_a_name_that_starts_with_the_target_wins_over_one_that_contains_it() -> None:
    assert resolved({"role": None, "name": "Salva le"}) == 1
    assert resolved({"role": "link", "name": "SALVATAGGI"}) == 4


def test_a_name_that_contains_the_target_is_the_third_choice() -> None:
    assert resolved({"role": None, "name": "modifiche prima"}) == 1
    assert resolved({"role": "button", "name": "bozza"}) == 2


def test_a_target_that_contains_the_name_is_the_last_choice() -> None:
    assert resolved({"role": "combobox", "name": "Città di residenza"}) == 8
    assert resolved({"role": "heading", "name": "Il nuovo ordine di oggi"}) == 0


def test_a_contained_name_needs_at_least_three_characters() -> None:
    assert resolved({"role": "checkbox", "name": "OK, accetto"}) is None
    assert resolved({"role": "textbox", "name": "Nome e cognome"}) == 5


def test_the_first_element_in_document_order_wins_within_a_rule() -> None:
    assert resolved({"role": None, "name": "Nome del cliente"}) == 6
    assert resolved({"role": "textbox", "name": "Nome del cliente"}) == 7


def test_the_role_filters_the_elements_and_accents_do_not_matter() -> None:
    assert resolved({"role": "combobox", "name": "citta"}) == 8
    assert resolved({"role": "textbox", "name": "Città"}) is None
    assert resolved({"role": "listitem", "name": "ordine 1"}) == 9


def test_the_action_chooses_the_roles_it_can_use() -> None:
    assert resolved({"role": None, "name": "Nome del cliente"}, action="TYPE") == 7
    assert resolved({"role": None, "name": "Nuovo ordine"}, action="CLICK") == 0
    assert resolved({"role": None, "name": "Ordine 1"}, action="CLICK") == 9
    assert resolved({"role": None, "name": "Città"}, action="SELECT") == 8
    assert resolved({"role": "textbox", "name": "Nome"}, action="SELECT") is None
    assert resolved({"role": None, "name": "Nuovo ordine"}, action="TYPE") is None
    assert resolved({"role": None, "name": "Nuovo ordine"}, action="CHECK") == 0


def test_the_actions_accept_the_roles_of_the_contract() -> None:
    click = targets_module.ACTION_ROLES["CLICK"]

    assert set(state.INTERACTIVE_ROLES) <= click
    assert {"text", "image", "listitem", "cell", "heading"} <= click
    assert {"alert", "status", "dialog", "progressbar"}.isdisjoint(click)
    assert targets_module.ACTION_ROLES["TYPE"] == {"textbox", "spinbutton", "combobox", "slider"}
    assert targets_module.ACTION_ROLES["SELECT"] == {"combobox"}


@pytest.mark.parametrize(
    "target",
    [
        {"role": "button", "name": ""},
        {"role": "button", "name": "   "},
        {"role": "menu", "name": "Salva"},
        {"role": None, "name": 3},
        {"role": None},
        {},
    ],
)
def test_a_target_that_is_not_valid_finds_nothing(target: dict[str, object]) -> None:
    assert resolve_target(SNAPSHOT, target) is None


def test_an_element_without_a_name_is_never_chosen() -> None:
    empty = page_snapshot(element(0, "button", ""), element(1, "button", "Invia"))

    assert resolve_target(empty, {"role": "button", "name": "Invia modulo"}) == empty.elements[1]
    assert resolve_target(empty, {"role": "button", "name": "zzz"}) is None


DOCUMENT: dict[str, object] = {
    "url": "http://127.0.0.1:8123/ordini?pagina=2",
    "title": "  Ordini \n aperti ",
    "text": "Ordini aperti  Nome   Taglia",
    "elements": [
        {
            "index": 0,
            "role": "heading",
            "name": "Ordini",
            "value": None,
            "state": None,
            "options": None,
        },
        {
            "index": 1,
            "role": "textbox",
            "name": " Nome ",
            "value": "Anna ",
            "state": None,
            "options": None,
        },
        {
            "index": 2,
            "role": "combobox",
            "name": "Taglia",
            "value": "Media",
            "state": "disabled",
            "options": ["Piccola", " Media ", ""],
        },
        {
            "index": 3,
            "role": "checkbox",
            "name": "Regalo",
            "value": None,
            "state": "checked",
            "options": None,
        },
    ],
}


def test_a_page_description_becomes_a_snapshot_and_back() -> None:
    snapshot = snapshot_from_document(DOCUMENT)

    assert snapshot == PageSnapshot(
        url="http://127.0.0.1:8123/ordini?pagina=2",
        title="Ordini aperti",
        text="Ordini aperti Nome Taglia",
        elements=(
            Element(0, "heading", "Ordini"),
            Element(1, "textbox", "Nome", value="Anna "),
            Element(
                2,
                "combobox",
                "Taglia",
                value="Media",
                state="disabled",
                options=("Piccola", "Media"),
            ),
            Element(3, "checkbox", "Regalo", state="checked"),
        ),
    )
    assert snapshot.document()["elements"][2] == {
        "index": 2,
        "role": "combobox",
        "name": "Taglia",
        "value": "Media",
        "state": "disabled",
        "options": ["Piccola", "Media"],
    }
    assert snapshot_from_document(snapshot.document()) == snapshot


def test_the_hidden_text_is_optional_collapsed_and_written_before_the_elements() -> None:
    older = snapshot_from_document(DOCUMENT)
    carried = snapshot_from_document({**DOCUMENT, "hidden_text": "  Totale \n nascosto "})

    assert older.hidden_text == ""
    assert carried.hidden_text == "Totale nascosto"
    assert (carried.url, carried.title, carried.text, carried.elements) == (
        older.url,
        older.title,
        older.text,
        older.elements,
    )
    assert list(carried.document()) == ["url", "title", "text", "hidden_text", "elements"]
    assert carried.document()["hidden_text"] == "Totale nascosto"
    assert snapshot_from_document(carried.document()) == carried
    assert PageSnapshot(url="u", title="t", text="x", elements=()).hidden_text == ""


def test_long_texts_are_cut_to_the_limits() -> None:
    document = {
        **DOCUMENT,
        "title": "t" * 500,
        "text": "w " * 5000,
        "hidden_text": "h " * 5000,
        "elements": [
            {
                "index": 0,
                "role": "combobox",
                "name": "n" * 300,
                "value": "v" * 300,
                "state": None,
                "options": [f"option {number}" for number in range(40)],
            }
        ],
    }

    snapshot = snapshot_from_document(document)

    assert len(snapshot.title) == state.MAX_TARGET_NAME_LENGTH
    assert len(snapshot.text) <= state.MAX_SNAPSHOT_TEXT_LENGTH
    assert len(snapshot.hidden_text) <= state.MAX_SNAPSHOT_HIDDEN_TEXT_LENGTH
    assert snapshot.hidden_text.startswith("h h ")
    only = snapshot.elements[0]
    assert len(only.name) == state.MAX_TARGET_NAME_LENGTH
    assert only.value is not None and len(only.value) == state.MAX_STEP_VALUE_LENGTH
    assert only.options is not None and len(only.options) == state.MAX_SNAPSHOT_OPTIONS


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"url": None}, "url is not text"),
        ({"hidden_text": None}, "hidden_text is not text"),
        ({"hidden_text": 3}, "hidden_text is not text"),
        ({"elements": {}}, "elements is not a list"),
        ({"elements": [{"index": 1, "role": "button", "name": "x"}]}, "has the index 1"),
        ({"elements": [{"index": True, "role": "button", "name": "x"}]}, "has the index True"),
        ({"elements": [{"index": 0, "role": "menu", "name": "x"}]}, "has the role 'menu'"),
        ({"elements": [{"index": 0, "role": "button", "name": 4}]}, "name is not text"),
        ({"elements": [{"index": 0, "role": "button", "name": "x", "value": 4}]}, "value"),
        ({"elements": [{"index": 0, "role": "button", "name": "x", "state": "on"}]}, "state"),
        (
            {"elements": [{"index": 0, "role": "button", "name": "x", "options": ["a"]}]},
            "not a combobox",
        ),
        (
            {"elements": [{"index": 0, "role": "combobox", "name": "x", "options": [1]}]},
            "not texts",
        ),
        ({"elements": ["x"]}, "is not an object"),
    ],
)
def test_a_page_description_that_breaks_the_contract_is_refused(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        snapshot_from_document({**DOCUMENT, **change})


def test_too_many_elements_are_refused() -> None:
    items = [
        {"index": number, "role": "text", "name": f"riga {number}"}
        for number in range(state.MAX_SNAPSHOT_ELEMENTS + 1)
    ]

    with pytest.raises(ValueError, match="more than 150 elements"):
        snapshot_from_document({**DOCUMENT, "elements": items})
    with pytest.raises(ValueError, match="not an object"):
        snapshot_from_document([])


def test_a_browser_error_carries_the_program_and_a_short_detail() -> None:
    error = BrowserError("ACTION_FAILED", program="Google Chrome", detail="x" * 1000)

    assert error.code == "ACTION_FAILED"
    assert error.status == 1
    assert error.program == "Google Chrome"
    assert len(error.detail) == state.MAX_STEP_DETAIL_LENGTH
    assert dict(error.values) == {"program": "Google Chrome", "detail": error.detail}
