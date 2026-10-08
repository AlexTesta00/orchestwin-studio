from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

ADD: Final = "ADD"
REMOVE: Final = "REMOVE"
CHANGE: Final = "CHANGE"
SELECTION: Final = "SELECTION"
ALTERNATIVE: Final = "ALTERNATIVE"
WORKFLOW: Final = "WORKFLOW"
VISUAL: Final = "VISUAL"
SCREEN: Final = "SCREEN"
ELEMENT: Final = "ELEMENT"
TRANSITION: Final = "TRANSITION"
MOCKUP: Final = "MOCKUP"
STYLES: Final = "STYLES"
ALTERNATIVE_FIELDS: Final = ("title", "summary", "information_architecture")
WORKFLOW_FIELDS: Final = ("title", "steps")
SCREEN_FIELDS: Final = ("title", "state")
ELEMENT_FIELDS: Final = ("kind", "content", "accessible_name", "options", "field_name", "required")
VISUAL_FIELDS: Final = ("product_name", "direction", "palette", "choices", "tokens")
TRANSITION_FIELDS: Final = ("trigger", "source", "target", "outcome")
MOCKUP_FIELDS: Final = ("title", "state", "markup")
FIELDS: Final = tuple(
    dict.fromkeys(
        (
            *ALTERNATIVE_FIELDS,
            *WORKFLOW_FIELDS,
            *SCREEN_FIELDS,
            *ELEMENT_FIELDS,
            *VISUAL_FIELDS,
            *TRANSITION_FIELDS,
            *MOCKUP_FIELDS,
        )
    )
)
TITLE_KEYS: Final = ("title",)
ELEMENT_TITLE_KEYS: Final = ("content", "accessible_name")
TRANSITION_TITLE_KEYS: Final = ("outcome",)
TRIGGER_KEYS: Final = ("kind", "content", "accessible_name")
KIND_ORDER: Final = (CHANGE, ADD, REMOVE)
DIRECTION_KEYS: Final = ("concept", "axes")
CHOICE_KEYS: Final = ("owner_selected_alternative_id", "recommended_alternative_id")
IDENTITY_KEYS: Final = ("id", "code")
OTHER_LISTS: Final = ("critiques", "concerns", "open_questions")
OTHER_VALUES: Final = ("recommended_alternative_id", "grounding")
TITLE_LIMIT: Final = 80
ELLIPSIS: Final = "…"
NUMBERS: Final = re.compile(r"([0-9]+)")
CHOSEN_TEXT: Final = "Chosen alternative:"
INSTEAD_TEXT: Final = "instead of"
ELEMENT_TEXT: Final = "element"
REDRAWN_TEXT: Final = "redrawn"
SUBJECT_TEXTS: Final[Mapping[str, str]] = MappingProxyType(
    {
        ALTERNATIVE: "Alternative",
        WORKFLOW: "Workflow",
        VISUAL: "Visual language",
        SCREEN: "Screen",
        ELEMENT: "Element",
        TRANSITION: "Transition",
        MOCKUP: "Mockup of screen",
        STYLES: "Mockup styles",
    }
)
KIND_TEXTS: Final[Mapping[str, str]] = MappingProxyType(
    {ADD: "added", REMOVE: "removed", CHANGE: "changed"}
)


@dataclass(frozen=True, slots=True)
class DeltaLine:
    kind: str
    subject: str
    code: str | None
    title: str | None
    screen: str | None
    fields: tuple[str, ...]
    before: str | None
    after: str | None


@dataclass(frozen=True, slots=True)
class DesignDelta:
    lines: tuple[DeltaLine, ...]
    other: int
    from_code: str | None
    to_code: str | None

    @property
    def empty(self) -> bool:
        return not self.lines


def compare(base: Mapping[str, object], target: Mapping[str, object]) -> DesignDelta:
    before, after = _mapping(base), _mapping(target)
    old, new = _chosen(before), _chosen(after)
    from_code, to_code = _text(old.get("code")), _text(new.get("code"))
    lines: list[DeltaLine] = []
    if from_code != to_code:
        lines.append(
            DeltaLine(
                kind=CHANGE,
                subject=SELECTION,
                code=to_code,
                title=_title(new.get("title")),
                screen=None,
                fields=(),
                before=from_code,
                after=to_code,
            )
        )
    lines.extend(_change(ALTERNATIVE, to_code or from_code, old, new, ALTERNATIVE_FIELDS))
    lines.extend(_lines(WORKFLOW, old.get("workflows"), new.get("workflows"), WORKFLOW_FIELDS))
    lines.extend(_change(VISUAL, None, _visual(old), _visual(new), VISUAL_FIELDS, titles=()))
    old_prototype = _mapping(before.get("prototype"))
    new_prototype = _mapping(after.get("prototype"))
    lines.extend(_screen_lines(old_prototype, new_prototype))
    lines.extend(
        _matched(
            TRANSITION,
            _moves(old_prototype),
            _moves(new_prototype),
            TRANSITION_FIELDS,
            titles=TRANSITION_TITLE_KEYS,
        )
    )
    old_mockup, new_mockup = _mockup(before), _mockup(after)
    lines.extend(
        _matched(MOCKUP, old_mockup.get("screens"), new_mockup.get("screens"), MOCKUP_FIELDS)
    )
    if _normal(old_mockup.get("styles")) != _normal(new_mockup.get("styles")):
        lines.append(
            DeltaLine(
                kind=CHANGE,
                subject=STYLES,
                code=None,
                title=None,
                screen=None,
                fields=(),
                before=None,
                after=None,
            )
        )
    return DesignDelta(
        lines=tuple(lines),
        other=_other(before, after, (old, new)),
        from_code=from_code,
        to_code=to_code,
    )


def english(line: DeltaLine) -> str:
    if line.subject == SELECTION:
        text = _joined(CHOSEN_TEXT, _named(line.after or line.code, line.title))
        return text if line.before is None else _joined(text, INSTEAD_TEXT, line.before)
    named = _named(line.code, line.title)
    what = _what(line)
    if line.subject == ELEMENT and line.screen:
        return _joined(f"{SUBJECT_TEXTS[SCREEN]} {line.screen}:", ELEMENT_TEXT, named, what)
    subject = SUBJECT_TEXTS.get(line.subject, line.subject.capitalize())
    return f"{_joined(subject, named)}: {what}"


def _what(line: DeltaLine) -> str:
    if line.kind == CHANGE and line.subject == MOCKUP:
        return REDRAWN_TEXT
    word = KIND_TEXTS.get(line.kind, KIND_TEXTS[CHANGE])
    fields = ", ".join(name.replace("_", " ") for name in line.fields)
    return f"{word} ({fields})" if fields else word


def _named(code: str | None, title: str | None) -> str:
    return _joined(code, f"«{title}»" if title else None)


def _joined(*parts: str | None) -> str:
    return " ".join(part for part in parts if part)


def _screen_lines(before: Mapping[str, object], after: Mapping[str, object]) -> list[DeltaLine]:
    lines: list[DeltaLine] = []
    for code, old, new in _entries(before.get("screens"), after.get("screens")):
        lines.extend(_change(SCREEN, code, old, new, SCREEN_FIELDS))
        if old is not None and new is not None:
            lines.extend(
                _matched(
                    ELEMENT,
                    old.get("elements"),
                    new.get("elements"),
                    ELEMENT_FIELDS,
                    kinded=True,
                    titles=ELEMENT_TITLE_KEYS,
                    screen=code,
                )
            )
    return lines


def _lines(
    subject: str,
    before: object,
    after: object,
    names: Sequence[str],
    *,
    titles: Sequence[str] = TITLE_KEYS,
    screen: str | None = None,
) -> list[DeltaLine]:
    return [
        line
        for code, old, new in _entries(before, after)
        for line in _change(subject, code, old, new, names, titles=titles, screen=screen)
    ]


def _matched(
    subject: str,
    before: object,
    after: object,
    names: Sequence[str],
    *,
    kinded: bool = False,
    titles: Sequence[str] = TITLE_KEYS,
    screen: str | None = None,
) -> list[DeltaLine]:
    old, new = _coded(before), _coded(after)
    left, right = sorted(old, key=_order), sorted(new, key=_order)
    marks = {code: _mark(item, names) for code, item in new.items()}
    for code in list(left):
        mark = _mark(old[code], names)
        partner = next((other for other in right if marks[other] == mark), None)
        if partner is not None:
            left.remove(code)
            right.remove(partner)
    paired = [
        code
        for code in left
        if code in right
        and (not kinded or _normal(old[code].get("kind")) == _normal(new[code].get("kind")))
    ]
    entries = [
        *((code, old[code], new[code]) for code in paired),
        *((code, None, new[code]) for code in right if code not in paired),
        *((code, old[code], None) for code in left if code not in paired),
    ]
    lines = [
        line
        for code, first, second in entries
        for line in _change(subject, code, first, second, names, titles=titles, screen=screen)
    ]
    return sorted(lines, key=lambda line: (_order(line.code or ""), KIND_ORDER.index(line.kind)))


def _mark(item: Mapping[str, object], names: Sequence[str]) -> tuple[object, ...]:
    return tuple(_normal(item.get(name)) for name in names)


def _change(
    subject: str,
    code: str | None,
    old: Mapping[str, object] | None,
    new: Mapping[str, object] | None,
    names: Sequence[str],
    *,
    titles: Sequence[str] = TITLE_KEYS,
    screen: str | None = None,
) -> list[DeltaLine]:
    fields: tuple[str, ...] = ()
    if old is None:
        kind = ADD
    elif new is None:
        kind = REMOVE
    else:
        kind = CHANGE
        fields = tuple(name for name in names if _normal(old.get(name)) != _normal(new.get(name)))
        if not fields:
            return []
    return [
        DeltaLine(
            kind=kind,
            subject=subject,
            code=code,
            title=_title_of(new, titles) or _title_of(old, titles),
            screen=screen,
            fields=fields,
            before=None,
            after=None,
        )
    ]


def _entries(
    before: object, after: object
) -> list[tuple[str, Mapping[str, object] | None, Mapping[str, object] | None]]:
    old, new = _coded(before), _coded(after)
    return [
        (code, old.get(code), new.get(code)) for code in sorted(old.keys() | new.keys(), key=_order)
    ]


def _coded(value: object) -> dict[str, Mapping[str, object]]:
    found: dict[str, Mapping[str, object]] = {}
    for item in _mappings(value):
        code = _text(item.get("code"))
        if code is not None:
            found.setdefault(code, item)
    return found


def _order(code: str) -> tuple[tuple[int | str, ...], str]:
    parts = NUMBERS.split(code)
    return tuple(int(part) if index % 2 else part for index, part in enumerate(parts)), code


def _chosen(package: Mapping[str, object]) -> Mapping[str, object]:
    alternatives = _mappings(package.get("alternatives"))
    for name in CHOICE_KEYS:
        wanted = _text(package.get(name))
        for item in alternatives:
            if wanted is not None and _text(item.get("id")) == wanted:
                return item
    return alternatives[0] if alternatives else {}


def _visual(alternative: Mapping[str, object]) -> Mapping[str, object]:
    visual = _mapping(alternative.get("visual_language"))
    direction = _mapping(visual.get("direction"))
    return {
        **{name: visual.get(name) for name in VISUAL_FIELDS},
        "direction": {name: direction.get(name) for name in DIRECTION_KEYS},
    }


def _moves(prototype: Mapping[str, object]) -> list[Mapping[str, object]]:
    screens: dict[str, object] = {}
    triggers: dict[str, object] = {}
    for screen in _mappings(prototype.get("screens")):
        _remember(screens, screen.get("id"), _text(screen.get("code")))
        for element in _mappings(screen.get("elements")):
            mark = _normal({name: element.get(name) for name in TRIGGER_KEYS})
            _remember(triggers, element.get("id"), mark)
    return [
        {
            "code": item.get("code"),
            "trigger": _resolved(triggers, item.get("trigger_element_id")),
            "source": _resolved(screens, item.get("source_screen_id")),
            "target": _resolved(screens, item.get("target_screen_id")),
            "outcome": item.get("outcome"),
        }
        for item in _mappings(prototype.get("transitions"))
    ]


def _remember(found: dict[str, object], identifier: object, value: object) -> None:
    key = _text(identifier)
    if key is not None and value is not None:
        found.setdefault(key, value)


def _resolved(found: Mapping[str, object], identifier: object) -> object:
    key = _text(identifier)
    return None if key is None else found.get(key)


def _mockup(package: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(_mapping(package.get("generated_mockup")).get("mockup"))


def _other(
    before: Mapping[str, object],
    after: Mapping[str, object],
    chosen: Sequence[Mapping[str, object]],
) -> int:
    count = sum(_differences(before.get(name), after.get(name)) for name in OTHER_LISTS)
    count += sum(
        1 for name in OTHER_VALUES if _normal(before.get(name)) != _normal(after.get(name))
    )
    return count + _differences(_unchosen(before, chosen), _unchosen(after, chosen))


def _unchosen(
    package: Mapping[str, object], chosen: Sequence[Mapping[str, object]]
) -> list[Mapping[str, object]]:
    return [
        item
        for item in _mappings(package.get("alternatives"))
        if not any(_same(item, other) for other in chosen)
    ]


def _same(first: Mapping[str, object], second: Mapping[str, object]) -> bool:
    return any(
        (key := _text(first.get(name))) is not None and key == _text(second.get(name))
        for name in IDENTITY_KEYS
    )


def _differences(before: object, after: object) -> int:
    left = [_normal(item) for item in _sequence(before)]
    right = [_normal(item) for item in _sequence(after)]
    for item in list(left):
        if item in right:
            left.remove(item)
            right.remove(item)
    count = 0
    for name in IDENTITY_KEYS:
        for item in list(left):
            key = _identity(item, name)
            partner = next(
                (other for other in right if key is not None and _identity(other, name) == key),
                None,
            )
            if partner is not None:
                left.remove(item)
                right.remove(partner)
                count += 1
    return count + len(left) + len(right)


def _identity(item: object, name: str) -> object:
    return item.get(name) if isinstance(item, dict) else None


def _normal(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()) or None
    if isinstance(value, Mapping):
        found = {
            str(key): normal for key, item in value.items() if (normal := _normal(item)) is not None
        }
        return found or None
    if isinstance(value, list | tuple):
        return tuple(_normal(item) for item in value) or None
    return value


def _title_of(item: Mapping[str, object] | None, keys: Sequence[str]) -> str | None:
    if item is None:
        return None
    return next((title for key in keys if (title := _title(item.get(key))) is not None), None)


def _title(value: object) -> str | None:
    text = _text(value)
    if text is None or len(text) <= TITLE_LIMIT:
        return text
    return text[: TITLE_LIMIT - 1].rstrip() + ELLIPSIS


def _mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None
