from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from orchestwin.artifacts.bound_mockups import (
    BoundGeneratedMockup,
    bound_mockup_from_snapshot,
    create_bound_mockup,
    markup_requirement_codes,
)
from orchestwin.artifacts.generated_mockup_structure import derive_prototype
from orchestwin.artifacts.generated_mockups import GeneratedMockupError

from .test_generated_mockup_support import (
    BASE_FIRST,
    BASE_SECOND,
    FIXTURES,
    TOKEN_NAMES,
    build,
    fixture_codes,
    fixture_mockup,
    fixture_tokens,
    requirement_ids,
)

WRAPPED_FIRST = '<div class="shell" data-req="REQ-009 REQ-001">' + BASE_FIRST + "</div>"


def bound(name: str) -> BoundGeneratedMockup:
    return create_bound_mockup(
        mockup=fixture_mockup(name),
        requirement_ids_by_code=requirement_ids(fixture_codes(name)),
    )


def stored(value: BoundGeneratedMockup) -> dict[str, object]:
    return json.loads(value.canonical_json())


def raises(code: str):
    return pytest.raises(GeneratedMockupError, match=f"^{code}: ")


@pytest.mark.parametrize("name", FIXTURES)
def test_markup_requirement_codes_are_every_code_named_by_data_req(name: str) -> None:
    assert markup_requirement_codes(fixture_mockup(name)) == tuple(sorted(fixture_codes(name)))
    assert markup_requirement_codes(build()) == ("REQ-001", "REQ-002")
    assert markup_requirement_codes(build(WRAPPED_FIRST)) == ("REQ-001", "REQ-002", "REQ-009")


@pytest.mark.parametrize("name", FIXTURES)
def test_bound_mockup_sorts_the_map_by_code_and_derives_the_prototype_of_the_contract(
    name: str,
) -> None:
    mockup = fixture_mockup(name)
    identifiers = requirement_ids(fixture_codes(name))
    reversed_map = dict(sorted(identifiers.items(), reverse=True))

    value = create_bound_mockup(mockup=mockup, requirement_ids_by_code=reversed_map)

    assert value.mockup == mockup
    assert value.requirement_ids_by_code == tuple(sorted(identifiers.items()))
    assert value.requirement_codes == tuple(sorted(identifiers))
    assert value.requirement_ids == tuple(identifiers[code] for code in sorted(identifiers))
    assert value.design_alternative_id == mockup.design_alternative_id
    assert value.prototype() == derive_prototype(mockup, requirement_ids_by_code=identifiers)
    assert value.prototype() == value.prototype()
    assert value.prototype().design_alternative_id == mockup.design_alternative_id


def test_bound_mockup_accepts_the_pairs_it_stores() -> None:
    value = bound(FIXTURES[0])

    again = create_bound_mockup(
        mockup=value.mockup,
        requirement_ids_by_code=reversed(value.requirement_ids_by_code),
    )

    assert again == value
    assert again.content_hash == value.content_hash


@pytest.mark.parametrize("name", FIXTURES)
def test_bound_mockup_snapshot_names_every_code_with_its_identifier(name: str) -> None:
    value = bound(name)
    identifiers = requirement_ids(fixture_codes(name))

    snapshot = value.to_snapshot()

    assert set(snapshot) == {"mockup", "requirement_ids_by_code"}
    assert snapshot["mockup"] == value.mockup.to_snapshot()
    assert snapshot["requirement_ids_by_code"] == {
        code: str(identifier) for code, identifier in sorted(identifiers.items())
    }
    assert list(snapshot["requirement_ids_by_code"]) == sorted(identifiers)
    assert len(value.content_hash) == 64
    assert value.canonical_json() == bound(name).canonical_json()


@pytest.mark.parametrize("name", FIXTURES)
def test_bound_mockup_round_trips_through_its_stored_snapshot(name: str) -> None:
    value = bound(name)

    restored = bound_mockup_from_snapshot(stored(value), token_names=fixture_tokens(name))

    assert restored == value
    assert restored.content_hash == value.content_hash
    assert restored.to_snapshot() == value.to_snapshot()
    assert restored.prototype() == value.prototype()


def test_a_code_of_the_markup_without_an_identifier_is_rejected() -> None:
    identifiers = requirement_ids(("REQ-001",))

    with raises("REQUIREMENT_CODE_UNMAPPED") as error:
        create_bound_mockup(mockup=build(), requirement_ids_by_code=identifiers)

    assert "REQ-002" in error.value.detail


def test_a_code_named_only_by_a_container_still_needs_an_identifier() -> None:
    mockup = build(WRAPPED_FIRST)

    with raises("REQUIREMENT_CODE_UNMAPPED"):
        create_bound_mockup(
            mockup=mockup,
            requirement_ids_by_code=requirement_ids(("REQ-001", "REQ-002")),
        )

    value = create_bound_mockup(
        mockup=mockup,
        requirement_ids_by_code=requirement_ids(("REQ-001", "REQ-002", "REQ-009")),
    )
    used = {
        requirement
        for screen in value.prototype().screens
        for element in screen.elements
        for requirement in element.requirement_ids
    }

    assert value.requirement_codes == ("REQ-001", "REQ-002", "REQ-009")
    assert requirement_ids(("REQ-009",))["REQ-009"] not in used


def test_an_identifier_without_a_use_in_the_markup_is_rejected() -> None:
    identifiers = requirement_ids(("REQ-001", "REQ-002", "REQ-007"))

    with raises("REQUIREMENT_CODE_UNUSED") as error:
        create_bound_mockup(mockup=build(), requirement_ids_by_code=identifiers)

    assert "REQ-007" in error.value.detail


def test_two_codes_cannot_name_the_same_requirement() -> None:
    shared = uuid4()

    with raises("REQUIREMENT_ID_DUPLICATED"):
        create_bound_mockup(
            mockup=build(),
            requirement_ids_by_code={"REQ-001": shared, "REQ-002": shared},
        )


@pytest.mark.parametrize(
    "mapping",
    (
        {"REQ-001": "a3c1f2de-0000-4000-8000-000000000001"},
        {1: UUID(int=1)},
        [("REQ-001",)],
        "REQ-001",
    ),
)
def test_the_factory_rejects_maps_that_do_not_pair_codes_with_uuids(mapping: object) -> None:
    with raises("REQUIREMENT_MAPPING"):
        create_bound_mockup(mockup=build(), requirement_ids_by_code=mapping)


def test_the_constructor_protects_order_uniqueness_types_and_the_mockup() -> None:
    mockup = build()
    first, second = requirement_ids(("REQ-001", "REQ-002")).values()

    for entries in (
        (("REQ-002", second), ("REQ-001", first)),
        (("REQ-001", first), ("REQ-001", second), ("REQ-002", uuid4())),
        (("REQ-001", str(first)), ("REQ-002", second)),
        [("REQ-001", first), ("REQ-002", second)],
        (("REQ-001", first, "extra"), ("REQ-002", second)),
    ):
        with raises("REQUIREMENT_MAPPING"):
            BoundGeneratedMockup(mockup=mockup, requirement_ids_by_code=entries)

    with raises("MOCKUP_INVALID"):
        BoundGeneratedMockup(
            mockup=mockup.to_snapshot(),
            requirement_ids_by_code=(("REQ-001", first), ("REQ-002", second)),
        )

    assert BoundGeneratedMockup(
        mockup=mockup,
        requirement_ids_by_code=(("REQ-001", first), ("REQ-002", second)),
    ) == create_bound_mockup(
        mockup=mockup, requirement_ids_by_code={"REQ-002": second, "REQ-001": first}
    )


@pytest.mark.parametrize(
    "change",
    (
        lambda payload: {key: value for key, value in payload.items() if key != "mockup"},
        lambda payload: {**payload, "screens": []},
        lambda payload: {**payload, "mockup": "markup"},
        lambda payload: {**payload, "requirement_ids_by_code": [["REQ-001", "x"]]},
        lambda payload: {
            **payload,
            "requirement_ids_by_code": {
                **payload["requirement_ids_by_code"],
                "REQ-001": 7,
            },
        },
    ),
)
def test_snapshot_reading_rejects_an_unexpected_shape(change) -> None:
    payload = change(stored(bound(FIXTURES[0])))

    with raises("SNAPSHOT_INVALID"):
        bound_mockup_from_snapshot(payload, token_names=fixture_tokens(FIXTURES[0]))


def test_snapshot_reading_requires_identifiers_in_their_stored_form() -> None:
    name = FIXTURES[0]
    payload = stored(bound(name))
    codes = payload["requirement_ids_by_code"]
    upper = {**codes, "REQ-001": codes["REQ-001"].upper()}
    braces = {**codes, "REQ-001": "{" + codes["REQ-001"] + "}"}
    broken = {**codes, "REQ-001": "not-a-uuid"}

    for mapping in (upper, braces):
        with raises("SNAPSHOT_NOT_CANONICAL"):
            bound_mockup_from_snapshot(
                {**payload, "requirement_ids_by_code": mapping},
                token_names=fixture_tokens(name),
            )

    with raises("REQUIREMENT_MAPPING"):
        bound_mockup_from_snapshot(
            {**payload, "requirement_ids_by_code": broken},
            token_names=fixture_tokens(name),
        )


def test_snapshot_reading_validates_the_mockup_like_the_output_of_a_model() -> None:
    name = FIXTURES[0]
    payload = stored(bound(name))
    mockup = payload["mockup"]
    screens = mockup["screens"]
    unsafe_markup = {
        **payload,
        "mockup": {
            **mockup,
            "screens": [
                {**screens[0], "markup": screens[0]["markup"] + "<script>alert(1)</script>"},
                *screens[1:],
            ],
        },
    }
    unsafe_styles = {
        **payload,
        "mockup": {**mockup, "styles": mockup["styles"] + ".x{background:url(evil.png)}"},
    }
    upper_case = screens[0]["markup"].replace("<h1", "<H1").replace("</h1>", "</H1>")
    not_stored = {
        **payload,
        "mockup": {
            **mockup,
            "screens": [{**screens[0], "markup": upper_case}, *screens[1:]],
        },
    }

    assert upper_case != screens[0]["markup"]

    with raises("ELEMENT_FORBIDDEN"):
        bound_mockup_from_snapshot(unsafe_markup, token_names=fixture_tokens(name))

    with raises("STYLES_FORBIDDEN"):
        bound_mockup_from_snapshot(unsafe_styles, token_names=fixture_tokens(name))

    with raises("SNAPSHOT_NOT_CANONICAL"):
        bound_mockup_from_snapshot(not_stored, token_names=fixture_tokens(name))


def test_snapshot_reading_checks_the_token_names_it_is_given() -> None:
    name = FIXTURES[0]
    payload = stored(bound(name))
    names = frozenset(fixture_tokens(name)) - {"--vl-color-primary"}

    with raises("STYLES_CUSTOM_PROPERTY"):
        bound_mockup_from_snapshot(payload, token_names=names)


def test_snapshot_reading_rejects_codes_that_the_markup_does_not_name() -> None:
    name = FIXTURES[0]
    payload = stored(bound(name))
    extra = {**payload["requirement_ids_by_code"], "REQ-042": str(uuid4())}
    missing = dict(payload["requirement_ids_by_code"])
    del missing["REQ-003"]

    with raises("REQUIREMENT_CODE_UNUSED"):
        bound_mockup_from_snapshot(
            {**payload, "requirement_ids_by_code": extra},
            token_names=fixture_tokens(name),
        )

    with raises("REQUIREMENT_CODE_UNMAPPED"):
        bound_mockup_from_snapshot(
            {**payload, "requirement_ids_by_code": missing},
            token_names=fixture_tokens(name),
        )


def test_the_prototype_of_a_mockup_that_failed_the_review_raises() -> None:
    untraced = BASE_SECOND.replace("</main>", '</main><button type="button">Esporta</button>')
    value = create_bound_mockup(
        mockup=build(BASE_FIRST, untraced),
        requirement_ids_by_code=requirement_ids(("REQ-001", "REQ-002")),
    )

    with pytest.raises(ValueError, match="traceability"):
        value.prototype()


def test_equal_inputs_give_equal_bound_mockups_with_equal_hashes() -> None:
    first = create_bound_mockup(
        mockup=build(token_names=TOKEN_NAMES),
        requirement_ids_by_code=requirement_ids(("REQ-001", "REQ-002")),
    )
    second = create_bound_mockup(
        mockup=build(token_names=TOKEN_NAMES),
        requirement_ids_by_code=requirement_ids(("REQ-002", "REQ-001")),
    )

    assert first == second
    assert hash(first) == hash(second)
    assert first.content_hash == second.content_hash
