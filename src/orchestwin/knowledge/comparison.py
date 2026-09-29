from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Final

from orchestwin.knowledge.layout import STAGES

HASH_MARK: Final = "<hash>"
TIME_MARK: Final = "<time>"
USER_MARK: Final = "<user>"
VERSION_MARK: Final = "<version>"
REVISION_MARK: Final = "<revision>"
PROJECT_LABEL: Final = "project"
_IDENTITY: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HASH: Final = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_VIEW_SUFFIXES: Final = (".csv", ".mmd")


def _is_identity(value: object) -> bool:
    return isinstance(value, str) and _IDENTITY.fullmatch(value) is not None


def entity_labels(documents: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    labels: dict[str, str] = {}

    def name(identity: object, label: str) -> None:
        if _is_identity(identity):
            labels.setdefault(str(identity), label)

    def visit(node: object, scope: tuple[str, ...]) -> None:
        if isinstance(node, Mapping):
            inner = scope
            profile = node.get("profile")
            if isinstance(profile, Mapping) and "name" in profile:
                kind = "persona" if "persona_id" in node else "twin"
                name(node.get(f"{kind}_id"), f"{kind}:{profile['name']}")
                name(node.get("id"), f"{kind}-version:{profile['name']}")
            elif "id" in node and isinstance(node.get("code"), str):
                inner = (*scope, node["code"])
                name(node["id"], "/".join(inner))
            for value in node.values():
                visit(value, inner)
        elif isinstance(node, list):
            for item in node:
                visit(item, scope)

    present = [stage for stage in STAGES if stage in documents]
    for stage in present:
        document = documents[stage]
        name(document.get("project_id"), PROJECT_LABEL)
        name(document.get("id"), f"version:{stage}")
    for stage in present:
        visit(documents[stage], ())
    return labels


def _sorted(items: list[object]) -> list[object]:
    if not items:
        return items
    if all(isinstance(item, str) for item in items):
        return items
    if not all(isinstance(item, Mapping) for item in items):
        return items
    keys = {frozenset(item) for item in items}
    if len(keys) != 1:
        return items
    fields = next(iter(keys))
    if {"twin_id", "name"} <= fields and "profile" not in fields and "statement" not in fields:
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if {"kind", "source_id", "locator"} <= fields:
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if "profile" in fields and ("twin_id" in fields or "persona_id" in fields):
        return sorted(items, key=lambda item: json.dumps(item["profile"], sort_keys=True))
    return items


def comparable(node: object, labels: Mapping[str, str], key: str | None = None) -> object:
    if isinstance(node, Mapping):
        result: dict[str, object] = {}
        for name, value in node.items():
            if name == "based_on_version_number":
                continue
            if name == "created_by_user_id":
                result[name] = USER_MARK
            elif name == "created_at":
                result[name] = TIME_MARK
            elif name == "version_number":
                result[name] = VERSION_MARK
            elif name == "revision_kind":
                result[name] = REVISION_MARK
            elif name == "source_version":
                result[name] = None if value is None else VERSION_MARK
            else:
                result[name] = comparable(value, labels, name)
        return result
    if isinstance(node, list):
        items = [comparable(item, labels, key) for item in node]
        if key is not None and key.endswith("_ids"):
            return sorted(items, key=str)
        return _sorted(items)
    if isinstance(node, str):
        named = _IDENTITY.sub(lambda match: labels.get(match[0], match[0]), node)
        return _HASH.sub(HASH_MARK, named)
    return node


def comparable_documents(
    documents: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    labels = entity_labels(documents)
    return {stage: comparable(documents[stage], labels) for stage in STAGES if stage in documents}


def comparable_views(files: Mapping[str, str]) -> dict[str, str]:
    return {
        path: content for path, content in sorted(files.items()) if path.endswith(_VIEW_SUFFIXES)
    }


def document_differences(
    original: Mapping[str, Mapping[str, object]],
    imported: Mapping[str, Mapping[str, object]],
) -> list[str]:
    differences: list[str] = []

    def compare(left: object, right: object, path: str) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for name in sorted(set(left) | set(right)):
                if name not in left or name not in right:
                    differences.append(f"{path}.{name}: present on one side only")
                else:
                    compare(left[name], right[name], f"{path}.{name}")
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                differences.append(f"{path}: {len(left)} items against {len(right)}")
                return
            for index, (one, other) in enumerate(zip(left, right, strict=True)):
                compare(one, other, f"{path}[{index}]")
        elif left != right:
            differences.append(f"{path}: {left!r} against {right!r}")

    compare(comparable_documents(original), comparable_documents(imported), "folder")
    return differences


def view_differences(original: Mapping[str, str], imported: Mapping[str, str]) -> list[str]:
    left = comparable_views(original)
    right = comparable_views(imported)
    return [path for path in sorted(set(left) | set(right)) if left.get(path) != right.get(path)]


__all__ = [
    "HASH_MARK",
    "PROJECT_LABEL",
    "REVISION_MARK",
    "TIME_MARK",
    "USER_MARK",
    "VERSION_MARK",
    "comparable",
    "comparable_documents",
    "comparable_views",
    "document_differences",
    "entity_labels",
    "view_differences",
]
