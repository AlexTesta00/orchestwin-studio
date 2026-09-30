from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from orchestwin.cli.api import twin_chat
from orchestwin.cli.flows.twin_selection import Twin, twins_from
from orchestwin.cli.folder import IGNORED_NAMES

MANIFEST: Final = "orchestwin.json"
FOLDER_KIND: Final = "orchestwin.knowledge-folder"
STATE_KIND: Final = "orchestwin.project-state"
SCHEMA_VERSIONS: Final = (2, 3)
STATE_SCHEMA: Final = 3
STAGES: Final = ("brief", "team", "twins", "requirements", "design")
STATE_DOCUMENT: Final = "state/state.json"
CHANGES_DOCUMENT: Final = "twins/feedback/changes.json"
REVIEWS_DOCUMENT: Final = "twins/feedback/reviews.json"
TESTS_DOCUMENT: Final = "twins/feedback/tests.json"
TESTS_KIND: Final = "orchestwin.test-reviews"
MARKDOWN_SUFFIX: Final = ".md"
FOLDER_MISSING: Final = "FOLDER_MISSING"
FOLDER_UNREADABLE: Final = "FOLDER_UNREADABLE"
FOLDER_SCHEMA_UNSUPPORTED: Final = "FOLDER_SCHEMA_UNSUPPORTED"
UNSAFE_CHARACTERS: Final = ("\\", ":", "\0")
UNSAFE_PARTS: Final = frozenset({"", ".", ".."})


class FolderProblem(Exception):
    def __init__(self, code: str, /, **values: object) -> None:
        super().__init__(code)
        self.code = code
        self.values: Mapping[str, object] = MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class Screen:
    identifier: str
    code: str
    title: str
    elements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Transition:
    code: str
    source: str | None
    target: str | None
    trigger: str | None
    outcome: str | None

    def document(self) -> dict[str, object]:
        return {
            "code": self.code,
            "from": self.source,
            "to": self.target,
            "trigger": self.trigger,
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class DesignView:
    version_number: int | None
    chosen: Mapping[str, object] | None
    alternatives: tuple[Mapping[str, object], ...]
    screens: tuple[Screen, ...]
    transitions: tuple[Transition, ...]

    def screen(self, code: str) -> Screen | None:
        wanted = code.strip().upper()
        return next((screen for screen in self.screens if screen.code.upper() == wanted), None)

    def moves(self, code: str) -> tuple[Transition, ...]:
        return tuple(
            transition
            for transition in self.transitions
            if code in (transition.source, transition.target)
        )


@dataclass(frozen=True, slots=True)
class Knowledge:
    root: Path
    manifest: Mapping[str, object]
    schema_version: int
    version_number: int | None
    approved: tuple[str, ...]
    pending: str | None

    @property
    def complete(self) -> bool:
        return self.pending is None

    def read(self, relative: str) -> object | None:
        path = inside(self.root, relative)
        if path is None:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        if not path.is_file():
            return None
        return _json(path, relative)

    def document(self, relative: str, *, required: bool = True) -> Mapping[str, object] | None:
        found = self.read(relative)
        if found is None and not required:
            return None
        if not isinstance(found, dict):
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return found

    def stage(self, stage: str) -> Mapping[str, object] | None:
        if stage not in self.approved:
            return None
        entry = _mapping(_mapping(self.manifest.get("stages")).get(stage))
        return self.document(_text(entry.get("document")) or f"{stage}/{stage}.json")

    def state(self) -> Mapping[str, object] | None:
        if self.schema_version < STATE_SCHEMA:
            return None
        relative = _text(_mapping(self.manifest.get("state")).get("document")) or STATE_DOCUMENT
        document = self.document(relative)
        if document is None or document.get("kind") != STATE_KIND:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return document

    def change_runs(self) -> list[Mapping[str, object]]:
        if self.schema_version < STATE_SCHEMA:
            return []
        feedback = _mapping(self.manifest.get("feedback"))
        document = self.document(_text(feedback.get("changes")) or CHANGES_DOCUMENT)
        return [] if document is None else mappings(document.get("runs"))

    def test_runs(self) -> tuple[Mapping[str, object], ...]:
        if self.schema_version < STATE_SCHEMA:
            return ()
        declared = _text(_mapping(self.manifest.get("feedback")).get("tests"))
        relative = declared or TESTS_DOCUMENT
        document = self.document(relative, required=declared is not None)
        if document is None:
            return ()
        if document.get("kind") != TESTS_KIND:
            raise FolderProblem(FOLDER_UNREADABLE, path=relative)
        return tuple(mappings(document.get("runs")))

    def design_reviews(self) -> int:
        relative = _text(_mapping(self.manifest.get("feedback")).get("reviews_document"))
        if relative is None:
            if "design" not in self.approved:
                return 0
            relative = REVIEWS_DOCUMENT
        document = self.document(relative, required=False)
        return 0 if document is None else len(mappings(document.get("runs")))

    def twins(self) -> tuple[Twin, ...] | None:
        document = self.stage("twins")
        return None if document is None else twins_from(twin_chat.twin_versions(document))


def load(root: Path) -> Knowledge:
    path = root / MANIFEST
    if not path.is_file():
        raise FolderProblem(FOLDER_MISSING)
    manifest = _json(path, MANIFEST)
    if not isinstance(manifest, dict):
        raise FolderProblem(FOLDER_UNREADABLE, path=MANIFEST)
    version = manifest.get("schema_version")
    if (
        manifest.get("kind") != FOLDER_KIND
        or not _integer(version)
        or version not in SCHEMA_VERSIONS
    ):
        raise FolderProblem(FOLDER_SCHEMA_UNSUPPORTED, version=str(version))
    stages = _mapping(manifest.get("stages"))
    progress = manifest.get("progress")
    if version >= STATE_SCHEMA and isinstance(progress, Mapping):
        listed = progress.get("approved")
        names = (
            {item for item in listed if isinstance(item, str)}
            if isinstance(listed, list)
            else set()
        )
        approved = tuple(stage for stage in STAGES if stage in names)
        declared = progress.get("pending")
    else:
        approved = tuple(stage for stage in STAGES if isinstance(stages.get(stage), Mapping))
        declared = None
    pending = (
        declared
        if declared in STAGES and declared not in approved
        else next((stage for stage in STAGES if stage not in approved), None)
    )
    number = _mapping(manifest.get("package")).get("version_number")
    return Knowledge(
        root=root,
        manifest=manifest,
        schema_version=version,
        version_number=number if _integer(number) else None,
        approved=approved,
        pending=pending,
    )


def test_runs(root: Path) -> tuple[Mapping[str, object], ...]:
    return load(root).test_runs()


def requirements_view(document: Mapping[str, object]) -> dict[str, object]:
    specification = _mapping(document.get("specification"))
    requirements = mappings(specification.get("requirements"))
    codes = {
        str(item.get("id")): code for item in requirements if (code := _text(item.get("code")))
    }
    return {
        "version_number": _number(document.get("version_number")),
        "requirements": [
            {
                "code": _text(item.get("code")),
                "title": _text(item.get("title")),
                "statement": _text(item.get("statement")),
                "kind": _text(item.get("kind")),
                "priority": _text(item.get("priority")),
            }
            for item in requirements
        ],
        "user_stories": [
            {
                "code": _text(item.get("code")),
                "goal": _text(item.get("goal")),
                "benefit": _text(item.get("benefit")),
                "requirement_codes": _codes(item.get("requirement_ids"), codes),
            }
            for item in mappings(specification.get("user_stories"))
        ],
        "acceptance_criteria": [
            {
                "code": _text(item.get("code")),
                "statement": _text(item.get("statement")),
                "requirement_codes": _codes(item.get("requirement_ids"), codes),
                "verification_method": _text(item.get("verification_method")),
            }
            for item in mappings(specification.get("acceptance_criteria"))
        ],
    }


def select_codes(
    view: Mapping[str, object], codes: Sequence[str]
) -> tuple[dict[str, object], list[str]]:
    wanted = {code.upper() for code in codes}
    requirements = [item for item in mappings(view.get("requirements"))]
    chosen = {item.get("code") for item in requirements if item.get("code") in wanted}

    def picked(item: Mapping[str, object]) -> bool:
        cited = item.get("requirement_codes")
        cited_codes = set(cited) if isinstance(cited, list) else set()
        return item.get("code") in wanted or bool(chosen & cited_codes)

    stories = [item for item in mappings(view.get("user_stories")) if picked(item)]
    criteria = [item for item in mappings(view.get("acceptance_criteria")) if picked(item)]
    known = {
        item.get("code")
        for group in ("requirements", "user_stories", "acceptance_criteria")
        for item in mappings(view.get(group))
    }
    unknown: list[str] = []
    for code in codes:
        if code.upper() not in known and code.upper() not in unknown:
            unknown.append(code.upper())
    selected = {
        **view,
        "requirements": [item for item in requirements if item.get("code") in chosen],
        "user_stories": stories,
        "acceptance_criteria": criteria,
    }
    return selected, unknown


def design_view(document: Mapping[str, object]) -> DesignView:
    package = _mapping(document.get("package"))
    alternatives = tuple(mappings(package.get("alternatives")))
    selected = package.get("owner_selected_alternative_id")
    chosen = next(
        (
            item
            for item in alternatives
            if selected is not None and str(item.get("id")) == str(selected)
        ),
        None,
    )
    prototype = _mapping(package.get("prototype"))
    screens = _prototype_screens(prototype)
    if not screens:
        mockup = _mapping(_mapping(package.get("generated_mockup")).get("mockup"))
        screens = tuple(
            Screen(identifier="", code=code, title=_text(item.get("title")) or "", elements=())
            for item in mappings(mockup.get("screens"))
            if (code := _text(item.get("code")))
        )
    return DesignView(
        version_number=_number(document.get("version_number")),
        chosen=chosen,
        alternatives=alternatives,
        screens=screens,
        transitions=_transitions(prototype),
    )


def markdown_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    found: list[str] = []
    for directory, children, names in os.walk(root):
        children.sort()
        for name in sorted(names):
            path = Path(directory) / name
            if (
                name in IGNORED_NAMES
                or not name.endswith(MARKDOWN_SUFFIX)
                or path.is_symlink()
                or not path.is_file()
            ):
                continue
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def markdown_text(root: Path, relative: str) -> str | None:
    if not relative.endswith(MARKDOWN_SUFFIX):
        return None
    path = inside(root, relative)
    if path is None or path.is_symlink() or not path.is_file():
        return None
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def inside(root: Path, relative: str) -> Path | None:
    if not relative or any(character in relative for character in UNSAFE_CHARACTERS):
        return None
    parts = relative.split("/")
    if any(part in UNSAFE_PARTS for part in parts):
        return None
    candidate = root.joinpath(*parts)
    try:
        resolved = candidate.resolve()
        base = root.resolve()
    except (OSError, RuntimeError):
        return None
    return candidate if resolved.is_relative_to(base) else None


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def first_line(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def label(element: Mapping[str, object]) -> str | None:
    for name in ("accessible_name", "content"):
        found = element.get(name)
        if isinstance(found, str) and found.split():
            return " ".join(found.split())
    return None


def _prototype_screens(prototype: Mapping[str, object]) -> tuple[Screen, ...]:
    screens: list[Screen] = []
    for item in mappings(prototype.get("screens")):
        code = _text(item.get("code"))
        if code is None:
            continue
        labels = tuple(
            found for element in mappings(item.get("elements")) if (found := label(element))
        )
        screens.append(
            Screen(
                identifier=str(item.get("id") or ""),
                code=code,
                title=_text(item.get("title")) or "",
                elements=labels,
            )
        )
    return tuple(screens)


def _transitions(prototype: Mapping[str, object]) -> tuple[Transition, ...]:
    screens: dict[str, str] = {}
    elements: dict[str, str | None] = {}
    for item in mappings(prototype.get("screens")):
        code = _text(item.get("code"))
        if code is not None:
            screens[str(item.get("id"))] = code
        for element in mappings(item.get("elements")):
            elements[str(element.get("id"))] = label(element)
    found: list[Transition] = []
    for item in mappings(prototype.get("transitions")):
        code = _text(item.get("code"))
        if code is None:
            continue
        found.append(
            Transition(
                code=code,
                source=screens.get(str(item.get("source_screen_id"))),
                target=screens.get(str(item.get("target_screen_id"))),
                trigger=elements.get(str(item.get("trigger_element_id"))),
                outcome=_text(item.get("outcome")),
            )
        )
    return tuple(found)


def _json(path: Path, relative: str) -> object:
    try:
        return json.loads(path.read_bytes().decode("utf-8"), parse_constant=_refuse_constant)
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise FolderProblem(FOLDER_UNREADABLE, path=relative) from None


def _codes(value: object, codes: Mapping[str, str]) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [codes[str(item)] for item in value if str(item) in codes]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _number(value: object) -> int | None:
    return value if _integer(value) else None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _refuse_constant(value: str) -> object:
    raise ValueError(f"{value} is not JSON")
