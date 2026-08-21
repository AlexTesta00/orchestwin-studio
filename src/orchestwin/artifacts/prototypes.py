"""Declarative, non-executable prototype artifacts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    canonical_uuid_tuple,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)

_MAX_TITLE_LENGTH: Final = 200
_MAX_CONTENT_LENGTH: Final = 4000
_MAX_FIELD_NAME_LENGTH: Final = 128
_MAX_OUTCOME_LENGTH: Final = 2000


class PrototypeElementKind(StrEnum):
    """Trusted primitives supported by the prototype renderer."""

    HEADING = "HEADING"
    TEXT = "TEXT"
    TEXT_INPUT = "TEXT_INPUT"
    SELECT = "SELECT"
    BUTTON = "BUTTON"
    LINK = "LINK"
    LIST = "LIST"
    CARD = "CARD"
    STATUS = "STATUS"


class PrototypeViewport(StrEnum):
    """Viewport categories available in the trusted preview."""

    MOBILE = "MOBILE"
    TABLET = "TABLET"
    DESKTOP = "DESKTOP"


class PrototypeScreenState(StrEnum):
    """Representative state rendered by one prototype screen."""

    DEFAULT = "DEFAULT"
    EMPTY = "EMPTY"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


_INTERACTIVE_KINDS: Final = frozenset(
    {
        PrototypeElementKind.TEXT_INPUT,
        PrototypeElementKind.SELECT,
        PrototypeElementKind.BUTTON,
        PrototypeElementKind.LINK,
    }
)


class _CodedArtifact(Protocol):
    """Identity and display code shared by prototype collections."""

    id: UUID
    code: str


@dataclass(frozen=True, slots=True)
class PrototypeElement:
    """One trusted declarative element rendered by the frontend."""

    id: UUID
    code: str
    kind: PrototypeElementKind
    content: str
    accessible_name: str | None
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    field_name: str | None = None
    required: bool = False
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect accessibility, input shape, and traceability."""
        validate_display_code(
            self.code,
            prefix="ELM",
            label="prototype element code",
        )

        if (
            normalize_required_text(
                self.content,
                label="prototype element content",
                maximum_length=_MAX_CONTENT_LENGTH,
            )
            != self.content
        ):
            raise ValueError("prototype element content must be normalized")

        normalized_accessible_name = normalize_optional_text(
            self.accessible_name,
            label="prototype element accessible name",
            maximum_length=_MAX_CONTENT_LENGTH,
        )

        if normalized_accessible_name != self.accessible_name:
            raise ValueError("prototype element accessible name must be normalized")

        normalized_field_name = normalize_optional_text(
            self.field_name,
            label="prototype field name",
            maximum_length=_MAX_FIELD_NAME_LENGTH,
        )

        if normalized_field_name != self.field_name:
            raise ValueError("prototype field name must be normalized")

        for values, label in (
            (self.requirement_ids, "prototype element requirement IDs"),
            (self.user_story_ids, "prototype element user-story IDs"),
            (
                self.acceptance_criterion_ids,
                "prototype element acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=False,
            ):
                raise ValueError(f"{label} must use canonical order")

        if self.options != normalize_text_items(
            self.options,
            label="prototype element options",
            maximum_item_length=_MAX_CONTENT_LENGTH,
            require_items=self.kind is PrototypeElementKind.SELECT,
        ):
            raise ValueError("prototype element options must be normalized")

        is_interactive = self.kind in _INTERACTIVE_KINDS

        if is_interactive and self.accessible_name is None:
            raise ValueError("interactive prototype elements require an accessible name")

        if is_interactive and not (
            self.requirement_ids or self.user_story_ids or self.acceptance_criterion_ids
        ):
            raise ValueError("interactive prototype elements require traceability")

        is_field = self.kind in {
            PrototypeElementKind.TEXT_INPUT,
            PrototypeElementKind.SELECT,
        }

        if is_field and self.field_name is None:
            raise ValueError("prototype input elements require a field name")

        if not is_field and self.field_name is not None:
            raise ValueError("non-input prototype elements must not define a field name")

        if self.kind is not PrototypeElementKind.SELECT and self.options:
            raise ValueError("only SELECT prototype elements may define options")

        if self.required and not is_field:
            raise ValueError("only prototype input elements may be required")

    @property
    def is_interactive(self) -> bool:
        """Return whether the element may trigger user interaction."""
        return self.kind in _INTERACTIVE_KINDS

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic element snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "kind": self.kind.value,
            "content": self.content,
            "accessible_name": self.accessible_name,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "field_name": self.field_name,
            "required": self.required,
            "options": list(self.options),
        }


@dataclass(frozen=True, slots=True)
class PrototypeScreen:
    """One traceable screen in a declarative prototype."""

    id: UUID
    code: str
    title: str
    state: PrototypeScreenState
    elements: tuple[PrototypeElement, ...]
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect screen identity, element order, and traceability."""
        validate_display_code(
            self.code,
            prefix="SCR",
            label="prototype screen code",
        )

        if (
            normalize_required_text(
                self.title,
                label="prototype screen title",
                maximum_length=_MAX_TITLE_LENGTH,
            )
            != self.title
        ):
            raise ValueError("prototype screen title must be normalized")

        if self.elements != _canonical_elements(self.elements):
            raise ValueError("prototype screen elements must use canonical code order")

        for values, label in (
            (self.requirement_ids, "prototype screen requirement IDs"),
            (self.user_story_ids, "prototype screen user-story IDs"),
            (
                self.acceptance_criterion_ids,
                "prototype screen acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=False,
            ):
                raise ValueError(f"{label} must use canonical order")

        if not (self.requirement_ids or self.user_story_ids or self.acceptance_criterion_ids):
            raise ValueError("prototype screens require traceability")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic screen snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "state": self.state.value,
            "elements": [element.to_snapshot() for element in self.elements],
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
        }


@dataclass(frozen=True, slots=True)
class PrototypeTransition:
    """One declared navigation transition between prototype screens."""

    id: UUID
    code: str
    source_screen_id: UUID
    trigger_element_id: UUID
    target_screen_id: UUID
    outcome: str

    def __post_init__(self) -> None:
        """Protect identity and normalized expected outcome."""
        validate_display_code(
            self.code,
            prefix="TRN",
            label="prototype transition code",
        )

        if (
            normalize_required_text(
                self.outcome,
                label="prototype transition outcome",
                maximum_length=_MAX_OUTCOME_LENGTH,
            )
            != self.outcome
        ):
            raise ValueError("prototype transition outcome must be normalized")

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        """Return deterministic transition ordering metadata."""
        return (
            self.code,
            self.source_screen_id.hex,
            self.trigger_element_id.hex,
            self.target_screen_id.hex,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic transition snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "source_screen_id": str(self.source_screen_id),
            "trigger_element_id": str(self.trigger_element_id),
            "target_screen_id": str(self.target_screen_id),
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class DeclarativePrototype:
    """Trusted data-only prototype with no generated executable code."""

    id: UUID
    code: str
    title: str
    design_alternative_id: UUID
    entry_screen_id: UUID
    screens: tuple[PrototypeScreen, ...]
    transitions: tuple[PrototypeTransition, ...]
    supported_viewports: tuple[PrototypeViewport, ...]

    def __post_init__(self) -> None:
        """Protect graph integrity and deterministic prototype state."""
        validate_display_code(
            self.code,
            prefix="PRT",
            label="prototype code",
        )

        if (
            normalize_required_text(
                self.title,
                label="prototype title",
                maximum_length=_MAX_TITLE_LENGTH,
            )
            != self.title
        ):
            raise ValueError("prototype title must be normalized")

        expected_screens = _canonical_screens(self.screens)

        if self.screens != expected_screens:
            raise ValueError("prototype screens must use canonical code order")

        expected_transitions = _canonical_transitions(self.transitions)

        if self.transitions != expected_transitions:
            raise ValueError("prototype transitions must use canonical code order")

        expected_viewports = tuple(
            sorted(
                set(self.supported_viewports),
                key=lambda viewport: viewport.value,
            )
        )

        if not expected_viewports:
            raise ValueError("prototype requires at least one supported viewport")

        if self.supported_viewports != expected_viewports:
            raise ValueError("prototype viewports must be unique and canonically ordered")

        all_elements = tuple(element for screen in self.screens for element in screen.elements)
        _require_unique_artifacts(
            all_elements,
            label="prototype elements across screens",
        )

        screens_by_id = {screen.id: screen for screen in self.screens}

        if self.entry_screen_id not in screens_by_id:
            raise ValueError("prototype entry screen must reference an existing screen")

        for transition in self.transitions:
            source = screens_by_id.get(transition.source_screen_id)

            if source is None or transition.target_screen_id not in screens_by_id:
                raise ValueError("prototype transitions must reference existing screens")

            trigger = next(
                (
                    element
                    for element in source.elements
                    if element.id == transition.trigger_element_id
                ),
                None,
            )

            if trigger is None:
                raise ValueError("prototype transition trigger must belong to its source screen")

            if not trigger.is_interactive:
                raise ValueError("prototype transitions require an interactive trigger element")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic prototype snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "design_alternative_id": str(self.design_alternative_id),
            "entry_screen_id": str(self.entry_screen_id),
            "screens": [screen.to_snapshot() for screen in self.screens],
            "transitions": [transition.to_snapshot() for transition in self.transitions],
            "supported_viewports": [viewport.value for viewport in self.supported_viewports],
        }

    def canonical_json(self) -> str:
        """Serialize this prototype deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this prototype."""
        return snapshot_content_hash(self.to_snapshot())


def _canonical_elements(
    values: Iterable[PrototypeElement],
) -> tuple[PrototypeElement, ...]:
    """Return unique elements in stable code order."""
    elements = tuple(values)

    if not elements:
        raise ValueError("prototype screen elements must not be empty")

    _require_unique_artifacts(elements, label="prototype screen elements")
    return tuple(sorted(elements, key=lambda element: element.code))


def _canonical_screens(
    values: Iterable[PrototypeScreen],
) -> tuple[PrototypeScreen, ...]:
    """Return unique screens in stable code order."""
    screens = tuple(values)

    if not screens:
        raise ValueError("prototype screens must not be empty")

    _require_unique_artifacts(screens, label="prototype screens")
    return tuple(sorted(screens, key=lambda screen: screen.code))


def _canonical_transitions(
    values: Iterable[PrototypeTransition],
) -> tuple[PrototypeTransition, ...]:
    """Return unique transitions in stable code order."""
    transitions = tuple(values)
    _require_unique_artifacts(transitions, label="prototype transitions")
    return tuple(sorted(transitions, key=lambda transition: transition.sort_key))


def _require_unique_artifacts(
    values: Sequence[_CodedArtifact],
    *,
    label: str,
) -> None:
    """Require prototype artifacts to expose unique id and code values."""
    ids = tuple(value.id for value in values)
    codes = tuple(value.code for value in values)

    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} identities must be unique")

    if len(codes) != len(set(codes)):
        raise ValueError(f"{label} codes must be unique")


def create_prototype_element(
    *,
    element_id: UUID,
    code: str,
    kind: PrototypeElementKind,
    content: str,
    accessible_name: str | None = None,
    requirement_ids: Iterable[UUID] = (),
    user_story_ids: Iterable[UUID] = (),
    acceptance_criterion_ids: Iterable[UUID] = (),
    field_name: str | None = None,
    required: bool = False,
    options: Iterable[str] = (),
) -> PrototypeElement:
    """Create a normalized trusted prototype element."""
    return PrototypeElement(
        id=element_id,
        code=code,
        kind=kind,
        content=normalize_required_text(
            content,
            label="prototype element content",
            maximum_length=_MAX_CONTENT_LENGTH,
        ),
        accessible_name=normalize_optional_text(
            accessible_name,
            label="prototype element accessible name",
            maximum_length=_MAX_CONTENT_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="prototype element requirement IDs",
            require_items=False,
        ),
        user_story_ids=canonical_uuid_tuple(
            user_story_ids,
            label="prototype element user-story IDs",
            require_items=False,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="prototype element acceptance-criterion IDs",
            require_items=False,
        ),
        field_name=normalize_optional_text(
            field_name,
            label="prototype field name",
            maximum_length=_MAX_FIELD_NAME_LENGTH,
        ),
        required=required,
        options=normalize_text_items(
            options,
            label="prototype element options",
            maximum_item_length=_MAX_CONTENT_LENGTH,
            require_items=kind is PrototypeElementKind.SELECT,
        ),
    )


def create_prototype_screen(
    *,
    screen_id: UUID,
    code: str,
    title: str,
    state: PrototypeScreenState,
    elements: Iterable[PrototypeElement],
    requirement_ids: Iterable[UUID] = (),
    user_story_ids: Iterable[UUID] = (),
    acceptance_criterion_ids: Iterable[UUID] = (),
) -> PrototypeScreen:
    """Create a normalized screen in canonical element order."""
    return PrototypeScreen(
        id=screen_id,
        code=code,
        title=normalize_required_text(
            title,
            label="prototype screen title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        state=state,
        elements=_canonical_elements(elements),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="prototype screen requirement IDs",
            require_items=False,
        ),
        user_story_ids=canonical_uuid_tuple(
            user_story_ids,
            label="prototype screen user-story IDs",
            require_items=False,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="prototype screen acceptance-criterion IDs",
            require_items=False,
        ),
    )


def create_prototype_transition(
    *,
    transition_id: UUID,
    code: str,
    source_screen_id: UUID,
    trigger_element_id: UUID,
    target_screen_id: UUID,
    outcome: str,
) -> PrototypeTransition:
    """Create a normalized declarative transition."""
    return PrototypeTransition(
        id=transition_id,
        code=code,
        source_screen_id=source_screen_id,
        trigger_element_id=trigger_element_id,
        target_screen_id=target_screen_id,
        outcome=normalize_required_text(
            outcome,
            label="prototype transition outcome",
            maximum_length=_MAX_OUTCOME_LENGTH,
        ),
    )


def create_declarative_prototype(
    *,
    prototype_id: UUID,
    code: str,
    title: str,
    design_alternative_id: UUID,
    entry_screen_id: UUID,
    screens: Iterable[PrototypeScreen],
    transitions: Iterable[PrototypeTransition],
    supported_viewports: Iterable[PrototypeViewport],
) -> DeclarativePrototype:
    """Create a data-only prototype with validated navigation."""
    return DeclarativePrototype(
        id=prototype_id,
        code=code,
        title=normalize_required_text(
            title,
            label="prototype title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        design_alternative_id=design_alternative_id,
        entry_screen_id=entry_screen_id,
        screens=_canonical_screens(screens),
        transitions=_canonical_transitions(transitions),
        supported_viewports=tuple(
            sorted(
                set(supported_viewports),
                key=lambda viewport: viewport.value,
            )
        ),
    )


__all__ = [
    "DeclarativePrototype",
    "PrototypeElement",
    "PrototypeElementKind",
    "PrototypeScreen",
    "PrototypeScreenState",
    "PrototypeTransition",
    "PrototypeViewport",
    "create_declarative_prototype",
    "create_prototype_element",
    "create_prototype_screen",
    "create_prototype_transition",
]
