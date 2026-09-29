from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from orchestwin.artifacts.generated_mockups import (
    BLOCK_ELEMENTS,
    GeneratedMockup,
    GeneratedMockupError,
    MarkupElement,
    MarkupNode,
    MarkupText,
    screen_trees,
)
from orchestwin.artifacts.prototypes import (
    DeclarativePrototype,
    PrototypeElementKind,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)

MAX_CONTENT_LENGTH: Final = 4000
MAX_OUTCOME_LENGTH: Final = 2000
MAX_FIELD_NAME_LENGTH: Final = 128
PROTOTYPE_CODE: Final = "PRT-001"
ROW_SEPARATOR: Final = " · "
_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4"})
_TEXTS: Final = frozenset({"p", "blockquote", "figcaption", "summary", "legend", "caption"})
_STATUS_ELEMENTS: Final = frozenset({"output", "meter", "progress"})
_STATUS_ROLES: Final = frozenset({"status", "alert"})
_CHOICES: Final = frozenset({"checkbox", "radio"})
_SILENT: Final = frozenset({"svg", "select", "textarea"})
_FIELDS: Final = frozenset({PrototypeElementKind.TEXT_INPUT, PrototypeElementKind.SELECT})

Walk = Iterator[tuple[MarkupElement, tuple[int, ...], tuple[MarkupElement, ...]]]


@dataclass(frozen=True, slots=True)
class ElementPosition:
    screen_code: str
    path: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DerivedElement:
    code: str
    screen_code: str
    path: tuple[int, ...]
    node_name: str
    kind: PrototypeElementKind
    content: str
    accessible_name: str | None
    field_name: str | None
    required: bool
    options: tuple[str, ...]
    requirement_codes: tuple[str, ...]
    target_screen: str | None
    outcome: str | None

    @property
    def position(self) -> ElementPosition:
        return ElementPosition(self.screen_code, self.path)


@dataclass(frozen=True, slots=True)
class _Draft:
    screen_code: str
    path: tuple[int, ...]
    node_name: str
    kind: PrototypeElementKind
    content: str
    accessible_name: str | None
    field_name: str | None
    required: bool
    options: tuple[str, ...]
    requirement_codes: tuple[str, ...]
    target_screen: str | None
    outcome: str | None


def normalize(text: str) -> str:
    return " ".join(text.split())


def bounded(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip()


def _collect(nodes: Iterable[MarkupNode], parts: list[str]) -> None:
    after_element = False
    for node in nodes:
        if isinstance(node, MarkupText):
            parts.append(node.text)
            after_element = False
            continue
        if after_element:
            parts.append(" ")
        after_element = True
        if node.name in _SILENT or node.has("hidden"):
            continue
        if node.name == "br":
            parts.append(" ")
            continue
        block = node.name in BLOCK_ELEMENTS
        if block:
            parts.append(" ")
        _collect(node.children, parts)
        if block:
            parts.append(" ")


def nodes_text(nodes: Iterable[MarkupNode]) -> str:
    parts: list[str] = []
    _collect(nodes, parts)
    return normalize("".join(parts))


def node_text(node: MarkupElement) -> str:
    return nodes_text(node.children)


def walk_elements(
    nodes: Iterable[MarkupNode],
    path: tuple[int, ...] = (),
    ancestors: tuple[MarkupElement, ...] = (),
) -> Walk:
    index = 0
    for node in nodes:
        if isinstance(node, MarkupElement):
            current = (*path, index)
            index += 1
            yield node, current, ancestors
            yield from walk_elements(node.children, current, (*ancestors, node))


def locate(nodes: Sequence[MarkupNode], path: Sequence[int]) -> MarkupElement:
    children: Sequence[MarkupNode] = nodes
    current: MarkupElement | None = None
    for index in path:
        current = [node for node in children if isinstance(node, MarkupElement)][index]
        children = current.children
    assert current is not None
    return current


def first_role(node: MarkupElement) -> str:
    return (node.attribute("role") or "").split(" ")[0]


def requirement_codes_of(
    node: MarkupElement, ancestors: Sequence[MarkupElement]
) -> tuple[str, ...]:
    for item in (node, *reversed(ancestors)):
        value = item.attribute("data-req")
        if value:
            return tuple(value.split(" "))
    return ()


class ScreenIndex:
    def __init__(self, code: str, nodes: tuple[MarkupNode, ...]) -> None:
        self.code = code
        self.nodes = nodes
        self.ids: dict[str, MarkupElement] = {}
        self.labels: dict[str, list[MarkupElement]] = {}
        for node, _path, _ancestors in walk_elements(nodes):
            identifier = node.attribute("id")
            if identifier:
                self.ids[identifier] = node
            target = node.attribute("for") if node.name == "label" else None
            if target:
                self.labels.setdefault(target, []).append(node)

    def referenced_text(self, value: str | None) -> str:
        if not value:
            return ""
        return normalize(
            " ".join(node_text(self.ids[item]) for item in value.split() if item in self.ids)
        )

    def label(self, node: MarkupElement, ancestors: Sequence[MarkupElement]) -> str:
        labelled = self.referenced_text(node.attribute("aria-labelledby"))
        if labelled:
            return labelled
        aria = normalize(node.attribute("aria-label") or "")
        if aria:
            return aria
        identifier = node.attribute("id")
        if identifier:
            explicit = normalize(
                " ".join(node_text(label) for label in self.labels.get(identifier, ()))
            )
            if explicit:
                return explicit
        for ancestor in reversed(ancestors):
            if ancestor.name == "label":
                return node_text(ancestor)
        return ""


def _field_name(node: MarkupElement) -> str | None:
    for attribute in ("name", "id"):
        value = bounded(normalize(node.attribute(attribute) or ""), MAX_FIELD_NAME_LENGTH)
        if value:
            return value
    return None


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        item = bounded(normalize(value), MAX_CONTENT_LENGTH)
        if item and item not in result:
            result.append(item)
    return tuple(result)


def _choices(
    fieldset: MarkupElement, ancestors: tuple[MarkupElement, ...]
) -> list[tuple[MarkupElement, tuple[MarkupElement, ...]]]:
    found: list[tuple[MarkupElement, tuple[MarkupElement, ...]]] = []

    def visit(nodes: Iterable[MarkupNode], chain: tuple[MarkupElement, ...]) -> None:
        for node in nodes:
            if not isinstance(node, MarkupElement) or node.name == "fieldset":
                continue
            if node.name == "input" and (node.attribute("type") or "") in _CHOICES:
                found.append((node, chain))
            visit(node.children, (*chain, node))

    visit(fieldset.children, (*ancestors, fieldset))
    return found


class _Deriver:
    def __init__(self, screen: ScreenIndex) -> None:
        self.screen = screen

    def draft(
        self,
        node: MarkupElement,
        path: tuple[int, ...],
        kind: PrototypeElementKind,
        content: str,
        codes: Iterable[str],
        *,
        accessible_name: str = "",
        field_name: str | None = None,
        required: bool = False,
        options: tuple[str, ...] = (),
        target_screen: str | None = None,
        outcome: str | None = None,
    ) -> _Draft:
        return _Draft(
            screen_code=self.screen.code,
            path=path,
            node_name=node.name,
            kind=kind,
            content=bounded(content, MAX_CONTENT_LENGTH),
            accessible_name=bounded(accessible_name, MAX_CONTENT_LENGTH) or None,
            field_name=field_name,
            required=required,
            options=options,
            requirement_codes=tuple(sorted(set(codes))),
            target_screen=target_screen,
            outcome=outcome,
        )

    def classify(
        self, node: MarkupElement, path: tuple[int, ...], ancestors: tuple[MarkupElement, ...]
    ) -> _Draft | None:
        interactive = self.interactive(node, path, ancestors)
        if interactive is not None or node.name in {"a", "button", "input", "textarea", "select"}:
            return interactive
        if node.name == "fieldset" or any(item.name == "article" for item in ancestors):
            return None
        return self.passive(node, path, ancestors)

    def interactive(
        self, node: MarkupElement, path: tuple[int, ...], ancestors: tuple[MarkupElement, ...]
    ) -> _Draft | None:
        name = node.name
        codes = requirement_codes_of(node, ancestors)
        if name in {"a", "button"}:
            return self.action(node, path, codes)
        if name == "input" and (node.attribute("type") or "text") in _CHOICES:
            if any(item.name == "fieldset" for item in ancestors):
                return None
            label = self.screen.label(node, ancestors)
            return self.draft(
                node,
                path,
                PrototypeElementKind.SELECT,
                label or _field_name(node) or name,
                codes,
                accessible_name=label,
                field_name=_field_name(node),
                required=node.has("required"),
                options=_unique((label,)),
            )
        if name in {"input", "textarea"}:
            label = self.screen.label(node, ancestors)
            placeholder = normalize(node.attribute("placeholder") or "")
            return self.draft(
                node,
                path,
                PrototypeElementKind.TEXT_INPUT,
                label or placeholder or _field_name(node) or name,
                codes,
                accessible_name=label,
                field_name=_field_name(node),
                required=node.has("required"),
            )
        if name == "select":
            label = self.screen.label(node, ancestors)
            options = _unique(
                normalize(option.attribute("label") or "") or node_text(option)
                for option, _path, _chain in walk_elements(node.children)
                if option.name == "option"
            )
            return self.draft(
                node,
                path,
                PrototypeElementKind.SELECT,
                label or _field_name(node) or name,
                codes,
                accessible_name=label,
                field_name=_field_name(node),
                required=node.has("required"),
                options=options,
            )
        if name == "fieldset":
            return self.group(node, path, ancestors)
        return None

    def action(self, node: MarkupElement, path: tuple[int, ...], codes: Iterable[str]) -> _Draft:
        text = node_text(node)
        aria = normalize(node.attribute("aria-label") or "")
        href = node.attribute("href") if node.name == "a" else None
        target = None if href is None else href[1:]
        if target == self.screen.code and node.attribute("aria-current") == "page":
            target = None
        kind = (
            PrototypeElementKind.BUTTON
            if node.name == "button" or first_role(node) == "button"
            else PrototypeElementKind.LINK
        )
        content = text or aria or target or node.name
        return self.draft(
            node,
            path,
            kind,
            content,
            codes,
            accessible_name=aria or text,
            target_screen=target,
            outcome=None if target is None else bounded(content, MAX_OUTCOME_LENGTH),
        )

    def group(
        self, node: MarkupElement, path: tuple[int, ...], ancestors: tuple[MarkupElement, ...]
    ) -> _Draft | None:
        choices = _choices(node, ancestors)
        if not choices:
            return None
        options = _unique(self.screen.label(item, chain) for item, chain in choices)
        legend = next((child for child in node.elements if child.name == "legend"), None)
        content = (
            (node_text(legend) if legend is not None else "")
            or normalize(node.attribute("aria-label") or "")
            or self.screen.referenced_text(node.attribute("aria-labelledby"))
            or ROW_SEPARATOR.join(options)
        )
        names = [value for item, _chain in choices if (value := _field_name(item))]
        field_name = names[0] if names else _field_name(node)
        codes = [
            *requirement_codes_of(node, ancestors),
            *(code for item, chain in choices for code in requirement_codes_of(item, chain)),
        ]
        return self.draft(
            node,
            path,
            PrototypeElementKind.SELECT,
            content or field_name or node.name,
            codes,
            accessible_name=content,
            field_name=field_name,
            required=any(item.has("required") for item, _chain in choices),
            options=options,
        )

    def passive(
        self, node: MarkupElement, path: tuple[int, ...], ancestors: tuple[MarkupElement, ...]
    ) -> _Draft | None:
        name = node.name
        codes = requirement_codes_of(node, ancestors)
        if name == "article":
            return self.text(node, path, PrototypeElementKind.CARD, node_text(node), codes)
        if name in _STATUS_ELEMENTS or first_role(node) in _STATUS_ROLES:
            label = (
                self.screen.label(node, ancestors)
                if name in _STATUS_ELEMENTS
                else normalize(node.attribute("aria-label") or "")
            )
            return self.text(
                node,
                path,
                PrototypeElementKind.STATUS,
                node_text(node) or label,
                codes,
                accessible_name=label,
            )
        if name in _HEADINGS:
            return self.text(node, path, PrototypeElementKind.HEADING, node_text(node), codes)
        if name in _TEXTS:
            return self.text(node, path, PrototypeElementKind.TEXT, node_text(node), codes)
        if name == "dt":
            return self.term(node, path, ancestors, codes)
        if name == "dd":
            siblings = ancestors[-1].elements
            if any(sibling.name == "dt" for sibling in siblings[: path[-1]]):
                return None
            return self.text(node, path, PrototypeElementKind.TEXT, node_text(node), codes)
        if name == "li":
            return self.text(node, path, PrototypeElementKind.LIST, node_text(node), codes)
        if name == "tr":
            cells = [node_text(cell) for cell in node.elements]
            kind = (
                PrototypeElementKind.LIST
                if ancestors[-1].name == "tbody"
                else PrototypeElementKind.TEXT
            )
            return self.text(
                node, path, kind, ROW_SEPARATOR.join(cell for cell in cells if cell), codes
            )
        return None

    def term(
        self,
        node: MarkupElement,
        path: tuple[int, ...],
        ancestors: tuple[MarkupElement, ...],
        codes: Iterable[str],
    ) -> _Draft | None:
        definitions: list[str] = []
        for sibling in ancestors[-1].elements[path[-1] + 1 :]:
            if sibling.name == "dt":
                break
            if sibling.name == "dd" and (text := node_text(sibling)):
                definitions.append(text)
        term = node_text(node)
        head = term[:-1].rstrip() if term.endswith(":") else term
        joined = ROW_SEPARATOR.join(definitions)
        content = f"{head}: {joined}" if head and joined else head or term or joined
        return self.text(node, path, PrototypeElementKind.TEXT, content, codes)

    def text(
        self,
        node: MarkupElement,
        path: tuple[int, ...],
        kind: PrototypeElementKind,
        content: str,
        codes: Iterable[str],
        *,
        accessible_name: str = "",
    ) -> _Draft | None:
        if not content:
            return None
        return self.draft(node, path, kind, content, codes, accessible_name=accessible_name)


def derive_elements(mockup: GeneratedMockup) -> tuple[DerivedElement, ...]:
    trees = screen_trees(mockup)
    drafts: list[_Draft] = []
    for screen in mockup.screens:
        deriver = _Deriver(ScreenIndex(screen.code, trees[screen.code]))
        for node, path, ancestors in walk_elements(trees[screen.code]):
            draft = deriver.classify(node, path, ancestors)
            if draft is not None:
                drafts.append(draft)
    width = max(3, len(str(len(drafts))))
    elements: list[DerivedElement] = []
    for number, draft in enumerate(drafts, start=1):
        code = f"ELM-{number:0{width}d}"
        field_name = draft.field_name
        if draft.kind in _FIELDS and field_name is None:
            field_name = code.lower()
        elements.append(
            DerivedElement(
                code=code,
                screen_code=draft.screen_code,
                path=draft.path,
                node_name=draft.node_name,
                kind=draft.kind,
                content=draft.content,
                accessible_name=draft.accessible_name,
                field_name=field_name if draft.kind in _FIELDS else None,
                required=draft.required if draft.kind in _FIELDS else False,
                options=draft.options if draft.kind is PrototypeElementKind.SELECT else (),
                requirement_codes=draft.requirement_codes,
                target_screen=draft.target_screen,
                outcome=draft.outcome,
            )
        )
    return tuple(elements)


def element_positions(mockup: GeneratedMockup) -> dict[str, ElementPosition]:
    return {element.code: element.position for element in derive_elements(mockup)}


def _requirement_mapping(value: object) -> Mapping[str, UUID]:
    if not isinstance(value, Mapping) or not all(
        isinstance(code, str) and isinstance(identifier, UUID) for code, identifier in value.items()
    ):
        raise GeneratedMockupError(
            "REQUIREMENT_MAPPING", "requirement identifiers must map codes to UUIDs"
        )
    return value


def derive_prototype(
    mockup: GeneratedMockup, *, requirement_ids_by_code: Mapping[str, UUID]
) -> DeclarativePrototype:
    mapping = _requirement_mapping(requirement_ids_by_code)
    elements = derive_elements(mockup)
    missing = sorted(
        {code for element in elements for code in element.requirement_codes} - set(mapping)
    )
    if missing:
        raise GeneratedMockupError(
            "REQUIREMENT_MAPPING", f"no identifier for {', '.join(missing[:5])}"
        )
    namespace = mockup.design_alternative_id
    stem = mockup.content_hash

    def identifier(code: str) -> UUID:
        return uuid5(namespace, f"{stem}:{code}")

    screen_ids = {screen.code: identifier(screen.code) for screen in mockup.screens}
    built: dict[str, list] = {screen.code: [] for screen in mockup.screens}
    triggers = []
    for element in elements:
        item = create_prototype_element(
            element_id=identifier(element.code),
            code=element.code,
            kind=element.kind,
            content=element.content,
            accessible_name=element.accessible_name,
            requirement_ids={mapping[code] for code in element.requirement_codes},
            field_name=element.field_name,
            required=element.required,
            options=element.options,
        )
        built[element.screen_code].append(item)
        if element.target_screen is not None:
            triggers.append((element, item))
    width = max(3, len(str(len(triggers))))
    transitions = []
    for number, (element, item) in enumerate(triggers, start=1):
        code = f"TRN-{number:0{width}d}"
        assert element.target_screen is not None and element.outcome is not None
        transitions.append(
            create_prototype_transition(
                transition_id=identifier(code),
                code=code,
                source_screen_id=screen_ids[element.screen_code],
                trigger_element_id=item.id,
                target_screen_id=screen_ids[element.target_screen],
                outcome=element.outcome,
            )
        )
    screens = [
        create_prototype_screen(
            screen_id=screen_ids[screen.code],
            code=screen.code,
            title=screen.title,
            state=screen.state,
            elements=built[screen.code],
            requirement_ids={
                requirement for item in built[screen.code] for requirement in item.requirement_ids
            },
        )
        for screen in mockup.screens
    ]
    return create_declarative_prototype(
        prototype_id=identifier(PROTOTYPE_CODE),
        code=PROTOTYPE_CODE,
        title=mockup.title,
        design_alternative_id=namespace,
        entry_screen_id=screen_ids["SCR-001"],
        screens=screens,
        transitions=transitions,
        supported_viewports=tuple(PrototypeViewport),
    )


__all__ = [
    "MAX_CONTENT_LENGTH",
    "MAX_FIELD_NAME_LENGTH",
    "MAX_OUTCOME_LENGTH",
    "PROTOTYPE_CODE",
    "ROW_SEPARATOR",
    "DerivedElement",
    "ElementPosition",
    "ScreenIndex",
    "bounded",
    "derive_elements",
    "derive_prototype",
    "element_positions",
    "first_role",
    "locate",
    "node_text",
    "nodes_text",
    "normalize",
    "requirement_codes_of",
    "walk_elements",
]
