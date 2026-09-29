from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.twin_selection import (
    Twin,
    choice_label,
    folded,
    matching,
    observation_values,
    select,
    twins_from,
)

from .support.terminal import Terminal, command_context, terminal
from .support.transports import NoNetwork


def text_value(text: str | None) -> dict[str, object]:
    return {"kind": "TEXT", "text": text, "items": [], "reason": None}


def items_value(*items: str) -> dict[str, object]:
    return {"kind": "ITEMS", "text": None, "items": list(items), "reason": None}


def version(
    number: int,
    name: str,
    *,
    role: str | None = None,
    goals: Sequence[str] = (),
) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    if role is not None:
        observations.append({"observation_key": "user_twin.role", "value": text_value(role)})
    if goals:
        observations.append({"observation_key": "user_twin.goals", "value": items_value(*goals)})
    return {
        "id": f"version-{number}",
        "twin_id": f"twin-{number}",
        "version_number": number,
        "profile": {"name": name, "observations": observations},
    }


TWINS = twins_from(
    [
        version(1, "Niccolò Rossi", role="Cameriere", goals=["Chiudere il conto in fretta"]),
        version(2, "Élodie Martin", role="Turista"),
        version(3, "Anna", role="Anna"),
        version(4, "Anna Maria Bianchi", role="Cassiera"),
        version(5, "Andrea Neri"),
    ]
)


def bundle(tmp_path: Path, answers: Sequence[str] = ()) -> Terminal:
    return terminal(tmp_path, transport=NoNetwork(), answers=answers)


def names(found: Sequence[Twin]) -> list[str]:
    return [twin.name for twin in found]


def test_twins_are_numbered_in_the_order_of_the_studio() -> None:
    assert [(twin.number, twin.name) for twin in TWINS] == [
        (1, "Niccolò Rossi"),
        (2, "Élodie Martin"),
        (3, "Anna"),
        (4, "Anna Maria Bianchi"),
        (5, "Andrea Neri"),
    ]
    first = TWINS[0]
    assert (first.twin_id, first.version_id, first.version_number) == (
        "twin-1",
        "version-1",
        1,
    )
    assert first.role == "Cameriere"
    assert first.wants == "Chiudere il conto in fretta"
    assert TWINS[4].role is None
    assert TWINS[4].wants is None


def test_entries_that_are_not_twins_are_skipped_and_names_are_tidied() -> None:
    found = twins_from(
        [
            {"twin_id": "twin-a", "profile": {"name": "  Mario   Verdi  "}},
            {"twin_id": "twin-b", "profile": {"name": "   "}},
            {"twin_id": "", "profile": {"name": "Senza id"}},
            {"twin_id": "twin-c", "profile": "wrong"},
            {"twin_id": "twin-d", "profile": {"name": "Luisa", "observations": "wrong"}},
            {"twin_id": "twin-e", "version_number": True, "profile": {"name": "Carla"}},
        ]
    )

    assert [(twin.number, twin.name) for twin in found] == [
        (1, "Mario Verdi"),
        (2, "Luisa"),
        (3, "Carla"),
    ]
    assert found[1].observations == ()
    assert found[2].version_number is None
    assert found[0].version_id == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (text_value("  Al tavolo  "), ("Al tavolo",)),
        (text_value("   "), ()),
        (items_value("Uno", " ", "Due "), ("Uno", "Due")),
        ({"kind": "UNKNOWN", "text": None, "items": [], "reason": None}, ()),
        ({"kind": "ABSTAINED", "text": None, "items": [], "reason": "no data"}, ()),
        ({"kind": "ITEMS", "items": "wrong"}, ()),
        ("wrong", ()),
    ],
)
def test_the_values_of_an_observation(value: object, expected: tuple[str, ...]) -> None:
    assert observation_values({"observation_key": "user_twin.goals", "value": value}) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Niccolò", "niccolo"),
        ("ÉLODIE", "elodie"),
        ("  Anna   Maria ", "anna maria"),
        ("Straße", "strasse"),
        ("Café", "cafe"),
    ],
)
def test_names_are_compared_without_case_accents_or_extra_spaces(text: str, expected: str) -> None:
    assert folded(text) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", ["Niccolò Rossi"]),
        (" 2 ", ["Élodie Martin"]),
        ("nicco", ["Niccolò Rossi"]),
        ("NICCOLÒ", ["Niccolò Rossi"]),
        ("elo", ["Élodie Martin"]),
        ("Èlodie m", ["Élodie Martin"]),
        ("anna", ["Anna"]),
        ("anna m", ["Anna Maria Bianchi"]),
        ("an", ["Anna", "Anna Maria Bianchi", "Andrea Neri"]),
        ("rossi", []),
        ("9", []),
        ("", []),
        ("   ", []),
    ],
)
def test_a_twin_is_matched_by_number_or_by_the_beginning_of_its_name(
    value: str, expected: list[str]
) -> None:
    assert names(matching(TWINS, value)) == expected


def test_a_number_out_of_the_list_is_read_as_the_beginning_of_a_name() -> None:
    found = twins_from([version(1, "Mario"), version(2, "3D Designer")])

    assert names(matching(found, "3")) == ["3D Designer"]
    assert names(matching(found, "2")) == ["3D Designer"]


def test_a_single_match_is_chosen_without_questions(tmp_path: Path) -> None:
    console = bundle(tmp_path)

    chosen = select(command_context(console.environment), TWINS, "élodie")

    assert chosen is not None and chosen.name == "Élodie Martin"
    assert console.output == ""


def test_more_than_one_match_asks_which_one_in_english(tmp_path: Path) -> None:
    console = bundle(tmp_path, answers=["3"])

    chosen = select(command_context(console.environment), TWINS, "an")

    assert chosen is not None and chosen.name == "Andrea Neri"
    assert console.output.splitlines() == [
        'More than one twin matches "an": which one do you mean?',
        "  1. Anna",
        "  2. Anna Maria Bianchi - Cassiera",
        "  3. Andrea Neri",
        "Write the number of your choice: ",
    ]


def test_more_than_one_match_asks_which_one_in_italian(tmp_path: Path) -> None:
    console = bundle(tmp_path, answers=["7", "2"])

    chosen = select(command_context(console.environment, language="it"), TWINS, "AN")

    assert chosen is not None and chosen.name == "Anna Maria Bianchi"
    assert console.output.splitlines()[0] == "Più twin corrispondono a «AN»: quale intendi?"
    assert "Scegli uno dei numeri dell'elenco." in console.output


def test_no_match_gives_nothing_and_asks_nothing(tmp_path: Path) -> None:
    console = bundle(tmp_path)

    assert select(command_context(console.environment), TWINS, "zeta") is None
    assert console.output == ""


def test_a_closed_input_while_choosing_stops_the_command(tmp_path: Path) -> None:
    console = bundle(tmp_path)

    with pytest.raises(CliError) as caught:
        select(command_context(console.environment), TWINS, "an")

    assert caught.value.code == "INPUT_CLOSED"


def test_the_label_of_a_choice_adds_the_role_only_when_it_says_more() -> None:
    assert choice_label(TWINS[0]) == "Niccolò Rossi - Cameriere"
    assert choice_label(TWINS[2]) == "Anna"
    assert choice_label(TWINS[4]) == "Andrea Neri"
