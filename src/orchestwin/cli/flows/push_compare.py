from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import brief as brief_api
from orchestwin.cli.api import modeling as modeling_api
from orchestwin.cli.api import team as team_api
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.shapes import mapping_or_empty as _mapping

PUSHABLE: Final[Mapping[str, str]] = {
    "brief/brief.json": "brief",
    "team/team.json": "team",
    "twins/twins.json": "twins",
    "requirements/requirements.json": "requirements",
    "design/design.json": "design",
}
CONTENT_KEYS: Final[Mapping[str, str]] = {
    "brief": "brief",
    "team": "proposal",
    "twins": "snapshot",
    "requirements": "specification",
    "design": "package",
}
EXCLUDED: Final = frozenset({knowledge.MANIFEST_NAME, knowledge.GITATTRIBUTES})
STEP: Final = "pushable"
DERIVED: Final = "derived"
UNKNOWN: Final = "unknown"
CHANGED: Final = "changed"
ADDED: Final = "added"
DELETED: Final = "deleted"
SIGNS: Final[Mapping[str, str]] = {ADDED: "+", DELETED: "-", CHANGED: "~"}
IDENTITY_KEYS: Final = ("code", "agent_id", "twin_id", "id")
CONTEXT_REFERENCES: Final = (
    ("project_brief", "project_brief_reference"),
    ("agent_team", "agent_team_reference"),
    ("user_modeling", "user_modeling_reference"),
)
TWIN_LIST: Final = "twin_versions"


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    change: str
    kind: str

    @property
    def stage(self) -> str | None:
        return PUSHABLE.get(self.path)


def compared(base: Mapping[str, str], here: Mapping[str, str]) -> list[FileChange]:
    found: list[FileChange] = []
    for path in sorted((set(base) | set(here)) - EXCLUDED):
        before, after = base.get(path), here.get(path)
        if before is not None and after is not None and _lines(before) == _lines(after):
            continue
        change = ADDED if before is None else DELETED if after is None else CHANGED
        kind = STEP if path in PUSHABLE else DERIVED if before is not None else UNKNOWN
        found.append(FileChange(path, change, kind))
    return found


def content_of(stage: str, path: str, text: str | None) -> Mapping[str, object]:
    key = CONTENT_KEYS[stage]
    invalid = CliError(
        "PUSH_DOCUMENT_INVALID", status=USAGE_STATUS, values={"path": path, "key": key}
    )
    if text is None:
        raise invalid
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise invalid from None
    content = document.get(key) if isinstance(document, dict) else None
    if not isinstance(content, dict):
        raise invalid
    return content


def differences(
    new: Mapping[str, object], old: Mapping[str, object] | None
) -> list[tuple[str, str]]:
    before = {} if old is None else old
    found: list[tuple[str, str]] = []
    for key in [*new, *(name for name in before if name not in new)]:
        if key not in before:
            found.append((SIGNS[ADDED], key))
        elif key not in new:
            found.append((SIGNS[DELETED], key))
        elif new[key] != before[key]:
            found.extend(item_changes(key, before[key], new[key]) or [(SIGNS[CHANGED], key)])
    return found


def item_changes(key: str, old: object, new: object) -> list[tuple[str, str]]:
    before, after = identified(old), identified(new)
    if before is None or after is None:
        return []
    found: list[tuple[str, str]] = []
    for identity, item in after.items():
        if identity not in before:
            found.append((SIGNS[ADDED], f"{key} {identity}"))
        elif before[identity] != item:
            found.append((SIGNS[CHANGED], f"{key} {identity}"))
    found.extend(
        (SIGNS[DELETED], f"{key} {identity}") for identity in before if identity not in after
    )
    return found


def identified(value: object) -> dict[str, object] | None:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        return None
    if not value:
        return {}
    for name in IDENTITY_KEYS:
        keys = [item.get(name) for item in value]
        if all(isinstance(key, str) and key for key in keys) and len(set(keys)) == len(keys):
            return dict(zip((str(key) for key in keys), value, strict=True))
    return None


def brief_view(content: Mapping[str, object]) -> dict[str, object]:
    fields = content.get("fields")
    view = dict(fields) if isinstance(fields, Mapping) else {}
    view["unknown_fields"] = content.get("unknown_fields")
    return view


def brief_body(content: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    fields = content.get("fields")
    values = fields if isinstance(fields, Mapping) else {}
    body: dict[str, object] = {name: values.get(name) for name in brief_api.FIELDS}
    marked = content.get("unknown_fields")
    unknown = [
        name
        for name in (marked if isinstance(marked, list) else [])
        if isinstance(name, str) and name in brief_api.FIELDS
    ]
    body["unknown_fields"] = sorted({name for name in unknown if body.get(name) in (None, "", [])})
    ignored = [str(name) for name in values if name not in brief_api.FIELDS]
    return body, ignored


def member_agents(content: Mapping[str, object]) -> list[str]:
    members = content.get("members")
    if not isinstance(members, list):
        return []
    return team_api.ordered(
        str(item["agent_id"])
        for item in members
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    )


def grounded(package: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    grounding = _mapping(current.get("package")).get("grounding")
    if not isinstance(grounding, Mapping):
        return dict(package)
    return {**package, "grounding": grounding}


def api_specification(specification: Mapping[str, object]) -> dict[str, object]:
    body = {key: value for key, value in specification.items() if key != "context"}
    governed = specification.get("context")
    if not isinstance(governed, Mapping):
        return body
    for name, key in CONTEXT_REFERENCES:
        body[key] = governed.get(name)
    catalog = governed.get("catalog")
    catalog = catalog if isinstance(catalog, Mapping) else {}
    body["catalog_version"] = catalog.get("version")
    body["catalog_content_hash"] = catalog.get("content_hash")
    return body


def changed_keys(new: Mapping[str, object], old: Mapping[str, object], *, skip: str) -> list[str]:
    return [
        key
        for key in [*new, *(name for name in old if name not in new)]
        if key != skip and new.get(key) != old.get(key)
    ]


def replacement(name: str, observation: Mapping[str, object]) -> dict[str, object]:
    return {
        "field": name,
        **{key: observation[key] for key in modeling_api.REPLACEMENT_KEYS if key in observation},
    }


def twins_by_id(snapshot: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    items = snapshot.get(TWIN_LIST)
    return {
        str(item["twin_id"]): item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping) and isinstance(item.get("twin_id"), str)
    }


def observations_of(profile: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    items = profile.get("observations")
    return {
        str(item["observation_key"]): item
        for item in (items if isinstance(items, list) else [])
        if isinstance(item, Mapping) and isinstance(item.get("observation_key"), str)
    }


def same_content(item: FileChange, written: bytes, text: str) -> bool:
    try:
        found = written.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if _lines(found) == _lines(text):
        return True
    stage = item.stage
    if stage is None:
        return False
    key = CONTENT_KEYS[stage]
    try:
        old, new = json.loads(found), json.loads(text)
    except (ValueError, RecursionError):
        return False
    return isinstance(old, dict) and isinstance(new, dict) and old.get(key) == new.get(key)


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n")
