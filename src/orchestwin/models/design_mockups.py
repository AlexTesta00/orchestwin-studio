"""Model-authored visual drafts, bound to exact design and requirement identities."""

import re
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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


class MockupElementDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: PrototypeElementKind
    content: Text
    requirements: Annotated[tuple[str, ...], Field(min_length=1)]
    field_name: Annotated[str, Field(min_length=1, max_length=128)] | None
    required: bool
    options: tuple[Title, ...]
    target_screen: Annotated[str, Field(pattern=r"^SCR-[0-9]{3}$")] | None


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
