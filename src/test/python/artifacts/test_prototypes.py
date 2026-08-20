"""Tests for trusted declarative prototype artifacts."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
ALTERNATIVE_ID = UUID("00000000-0000-4000-8000-000000000040")
ENTRY_SCREEN_ID = UUID("00000000-0000-4000-8000-000000000050")
SUCCESS_SCREEN_ID = UUID("00000000-0000-4000-8000-000000000051")
INPUT_ID = UUID("00000000-0000-4000-8000-000000000060")
BUTTON_ID = UUID("00000000-0000-4000-8000-000000000061")
STATUS_ID = UUID("00000000-0000-4000-8000-000000000062")
TRANSITION_ID = UUID("00000000-0000-4000-8000-000000000070")
PROTOTYPE_ID = UUID("00000000-0000-4000-8000-000000000080")


def input_element():
    """Create one traceable required text input."""
    return create_prototype_element(
        element_id=INPUT_ID,
        code="ELM-001",
        kind=PrototypeElementKind.TEXT_INPUT,
        content=" Guest name ",
        accessible_name="Guest name",
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
        field_name="guest_name",
        required=True,
    )


def button_element():
    """Create one traceable navigation button."""
    return create_prototype_element(
        element_id=BUTTON_ID,
        code="ELM-002",
        kind=PrototypeElementKind.BUTTON,
        content="Save reservation",
        accessible_name="Save reservation",
        acceptance_criterion_ids=(CRITERION_ID,),
    )


def entry_screen():
    """Create the prototype entry screen."""
    return create_prototype_screen(
        screen_id=ENTRY_SCREEN_ID,
        code="SCR-001",
        title="Create reservation",
        state=PrototypeScreenState.DEFAULT,
        elements=(button_element(), input_element()),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )


def success_screen():
    """Create one successful outcome screen."""
    status = create_prototype_element(
        element_id=STATUS_ID,
        code="ELM-003",
        kind=PrototypeElementKind.STATUS,
        content="Reservation saved",
    )

    return create_prototype_screen(
        screen_id=SUCCESS_SCREEN_ID,
        code="SCR-002",
        title="Reservation confirmation",
        state=PrototypeScreenState.SUCCESS,
        elements=(status,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )


def transition():
    """Create one declared navigation transition."""
    return create_prototype_transition(
        transition_id=TRANSITION_ID,
        code="TRN-001",
        source_screen_id=ENTRY_SCREEN_ID,
        trigger_element_id=BUTTON_ID,
        target_screen_id=SUCCESS_SCREEN_ID,
        outcome="The confirmation screen becomes visible.",
    )


def prototype():
    """Create one complete trusted prototype."""
    return create_declarative_prototype(
        prototype_id=PROTOTYPE_ID,
        code="PRT-001",
        title="Reservation workflow prototype",
        design_alternative_id=ALTERNATIVE_ID,
        entry_screen_id=ENTRY_SCREEN_ID,
        screens=(success_screen(), entry_screen()),
        transitions=(transition(),),
        supported_viewports=(
            PrototypeViewport.MOBILE,
            PrototypeViewport.DESKTOP,
        ),
    )


def test_prototype_is_canonical_navigable_and_content_hashable() -> None:
    """Create a stable data-only prototype graph."""
    value = prototype()

    assert tuple(screen.code for screen in value.screens) == (
        "SCR-001",
        "SCR-002",
    )
    assert value.screens[0].elements == (
        input_element(),
        button_element(),
    )
    assert value.supported_viewports == (
        PrototypeViewport.DESKTOP,
        PrototypeViewport.MOBILE,
    )
    assert len(value.content_hash) == 64


def test_interactive_element_requires_accessible_name_and_traceability() -> None:
    """Reject controls that a trusted renderer cannot expose accessibly."""
    with pytest.raises(ValueError, match="accessible name"):
        create_prototype_element(
            element_id=BUTTON_ID,
            code="ELM-002",
            kind=PrototypeElementKind.BUTTON,
            content="Save",
            requirement_ids=(REQUIREMENT_ID,),
        )

    with pytest.raises(ValueError, match="require traceability"):
        create_prototype_element(
            element_id=BUTTON_ID,
            code="ELM-002",
            kind=PrototypeElementKind.BUTTON,
            content="Save",
            accessible_name="Save",
        )


def test_select_requires_options_and_input_field_name() -> None:
    """Protect the declared shape of form controls."""
    with pytest.raises(ValueError, match="options must not be empty"):
        create_prototype_element(
            element_id=INPUT_ID,
            code="ELM-001",
            kind=PrototypeElementKind.SELECT,
            content="Room type",
            accessible_name="Room type",
            requirement_ids=(REQUIREMENT_ID,),
            field_name="room_type",
        )

    with pytest.raises(ValueError, match="require a field name"):
        create_prototype_element(
            element_id=INPUT_ID,
            code="ELM-001",
            kind=PrototypeElementKind.TEXT_INPUT,
            content="Guest name",
            accessible_name="Guest name",
            requirement_ids=(REQUIREMENT_ID,),
        )


def test_transition_requires_existing_screens_and_interactive_source_element() -> None:
    """Reject invalid navigation edges in the declarative graph."""
    value = prototype()
    unknown_screen = UUID("00000000-0000-4000-8000-000000000099")

    with pytest.raises(ValueError, match="existing screens"):
        replace(
            value,
            transitions=(replace(transition(), target_screen_id=unknown_screen),),
        )

    non_interactive_trigger = create_prototype_element(
        element_id=BUTTON_ID,
        code="ELM-002",
        kind=PrototypeElementKind.HEADING,
        content="Reservation details",
    )
    source = replace(
        entry_screen(),
        elements=(input_element(), non_interactive_trigger),
    )

    with pytest.raises(ValueError, match="interactive trigger"):
        replace(
            value,
            screens=(source, success_screen()),
        )


def test_prototype_element_identities_are_unique_across_screens() -> None:
    """Prevent ambiguous element references across the prototype graph."""
    value = prototype()
    duplicate = create_prototype_element(
        element_id=INPUT_ID,
        code="ELM-004",
        kind=PrototypeElementKind.STATUS,
        content="Duplicate status",
    )
    invalid_success = replace(
        success_screen(),
        elements=(duplicate,),
    )

    with pytest.raises(ValueError, match=r"across screens.*identities"):
        replace(
            value,
            screens=(entry_screen(), invalid_success),
        )


def test_equal_prototypes_have_equal_snapshots_and_hashes() -> None:
    """Keep declarative output reproducible."""
    first = prototype()
    second = prototype()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
