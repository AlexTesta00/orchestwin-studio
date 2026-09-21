"""Model-authored visual drafts, bound to exact design and requirement identities."""

import re
from typing import Annotated, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)
from orchestwin.models.design_drafts import requirement_code_map
from orchestwin.models.requirements_drafts import Text, Title


def _element_schema(schema):
    """Keep existing primitive invariants enforceable before token sampling."""
    fields = {PrototypeElementKind.TEXT_INPUT, PrototypeElementKind.SELECT}
    actions = {PrototypeElementKind.BUTTON, PrototypeElementKind.LINK}
    schema["anyOf"] = []
    for kind in PrototypeElementKind:
        schema["anyOf"].append(
            {
                "properties": {
                    "kind": {"const": kind.value},
                    "field_name": {"type": "string", "pattern": r"\S"}
                    if kind in fields
                    else {"type": "null"},
                    "required": {} if kind in fields else {"const": False},
                    "options": {"minItems": 1}
                    if kind is PrototypeElementKind.SELECT
                    else {"maxItems": 0},
                    "target_screen": {"type": "string"} if kind in actions else {"type": "null"},
                }
            }
        )


class MockupElementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_element_schema)
    kind: PrototypeElementKind
    content: Text
    requirements: Annotated[tuple[str, ...], Field(min_length=1)]
    field_name: Annotated[str, Field(min_length=1, max_length=128)] | None
    required: bool
    options: tuple[Title, ...]
    target_screen: Annotated[str, Field(pattern=r"^SCR-[0-9]{3}$")] | None

    @model_validator(mode="after")
    def validate_primitive(self) -> Self:
        is_field = self.kind in {PrototypeElementKind.TEXT_INPUT, PrototypeElementKind.SELECT}
        is_action = self.kind in {PrototypeElementKind.BUTTON, PrototypeElementKind.LINK}
        if is_field and (self.field_name is None or not self.field_name.strip()):
            raise ValueError("prototype input elements require a field name")
        if not is_field and self.field_name is not None:
            raise ValueError("non-input prototype elements must not define a field name")
        if self.required and not is_field:
            raise ValueError("only prototype input elements may be required")
        if self.kind is PrototypeElementKind.SELECT and not self.options:
            raise ValueError("SELECT prototype elements require options")
        if self.kind is not PrototypeElementKind.SELECT and self.options:
            raise ValueError("only SELECT prototype elements may define options")
        if is_action != (self.target_screen is not None):
            raise ValueError("mockup actions require a declared destination")
        return self


class MockupScreenDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str = Field(pattern=r"^SCR-[0-9]{3}$")
    title: Title
    state: PrototypeScreenState
    elements: Annotated[tuple[MockupElementDraft, ...], Field(min_length=2, max_length=14)]


class MockupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: Title
    screens: Annotated[tuple[MockupScreenDraft, ...], Field(min_length=2, max_length=4)]


def bind_mockup(draft, alternative, requirements):
    """Validate an actual UI and its navigation; never manufacture missing controls."""
    codes = [screen.code for screen in draft.screens]
    if len(codes) != len(set(codes)) or codes != sorted(codes):
        raise ValueError("mockup screen codes must be unique and ordered")
    refs = requirement_code_map(requirements.specification)
    allowed = {item.code for item in requirements.specification.requirements}
    screen_ids = {code: uuid4() for code in codes}
    screens, transitions = [], []
    ordinal = 0
    for screen in draft.screens:
        elements = []
        for item in screen.elements:
            if screen.state is PrototypeScreenState.SUCCESS and re.match(
                r"(?:errore|error|failed|fallito|impossibile)\b",
                item.content.strip(),
                re.IGNORECASE,
            ):
                raise ValueError("a success screen must not display an error state")
            if not set(item.requirements) <= allowed:
                raise ValueError("unknown mockup requirement")
            ordinal += 1
            element = create_prototype_element(
                element_id=uuid4(),
                code=f"ELM-{ordinal:03d}",
                kind=item.kind,
                content=item.content,
                accessible_name=item.content
                if item.kind
                in {
                    PrototypeElementKind.TEXT_INPUT,
                    PrototypeElementKind.SELECT,
                    PrototypeElementKind.BUTTON,
                    PrototypeElementKind.LINK,
                }
                else None,
                requirement_ids=[refs[code] for code in item.requirements],
                field_name=item.field_name,
                required=item.required,
                options=item.options,
            )
            elements.append(element)
            is_action = item.kind in {PrototypeElementKind.BUTTON, PrototypeElementKind.LINK}
            if is_action != (item.target_screen is not None):
                raise ValueError("mockup actions require a declared destination")
            if item.target_screen is not None:
                if item.target_screen not in screen_ids:
                    raise ValueError("unknown mockup destination")
                transitions.append(
                    create_prototype_transition(
                        transition_id=uuid4(),
                        code=f"TRN-{len(transitions) + 1:03d}",
                        source_screen_id=screen_ids[screen.code],
                        trigger_element_id=element.id,
                        target_screen_id=screen_ids[item.target_screen],
                        outcome=item.content,
                    )
                )
        screens.append(
            create_prototype_screen(
                screen_id=screen_ids[screen.code],
                code=screen.code,
                title=screen.title,
                state=screen.state,
                elements=elements,
                requirement_ids={ref for element in elements for ref in element.requirement_ids},
            )
        )
    if not transitions:
        raise ValueError("a visual mockup requires an actionable flow")
    reachable = {screens[0].id}
    while True:
        expanded = reachable | {
            x.target_screen_id for x in transitions if x.source_screen_id in reachable
        }
        if expanded == reachable:
            break
        reachable = expanded
    if reachable != set(screen_ids.values()):
        raise ValueError("mockup contains unreachable screens")
    return create_declarative_prototype(
        prototype_id=uuid4(),
        code="PRT-001",
        title=draft.title,
        design_alternative_id=alternative.id,
        entry_screen_id=screens[0].id,
        screens=screens,
        transitions=transitions,
        supported_viewports=tuple(PrototypeViewport),
    )
