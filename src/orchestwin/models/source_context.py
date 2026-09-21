"""Lossless implementation content from the application's approved artifact views."""

import re
from collections import Counter
from copy import deepcopy
from typing import Any

IMPLEMENTATION_VIEW = "SOURCE_SEMANTIC_CONTENT_V3_REFERENCES"
IMPLEMENTATION_ARTIFACTS = ("requirements", "architecture", "design")


def implementation_work_order(contract: dict[str, Any]) -> dict[str, Any]:
    """Repeat exact business statements near the task, retaining the complete view.

    Example names in pinned launchers must not become the application's goal.
    This reading aid carries verbatim statements and their source locations;
    every original field remains in ``implementation_contract``.
    """
    requirements = contract["content"].get("requirements", {})
    fields = {
        "requirements": ("code", "kind", "priority", "title", "statement"),
        "acceptance_criteria": ("code", "statement", "verification_method"),
        "scenarios": ("code", "title", "preconditions", "trigger", "steps", "expected_outcome"),
        "definition_of_done": (
            "code",
            "applicability",
            "condition",
            "statement",
            "verification_method",
        ),
    }
    return {
        "role": "Verbatim approved business data; the complete implementation contract also applies.",
        "statements": [
            {
                "source": f"implementation_contract.content.requirements.{category}[{index}]",
                **{key: deepcopy(item[key]) for key in keys if key in item},
            }
            for category, keys in fields.items()
            for index, item in enumerate(requirements.get(category, []))
        ]
        + [
            {
                "source": f"implementation_contract.content.design.prototype.screens[{screen_index}].elements[{element_index}]",
                **deepcopy(element),
            }
            for screen_index, screen in enumerate(
                contract["content"].get("design", {}).get("prototype", {}).get("screens", [])
            )
            for element_index, element in enumerate(screen.get("elements", []))
            if element.get("required") is True and element.get("field_name")
        ],
    }


def implementation_contract(context: dict[str, Any]) -> dict[str, Any]:
    """Preserve semantic identifiers, references and nested decision context.

    The API already selects the approved implementation view of each artifact.
    Field names alone cannot distinguish metadata from behavior: ``code`` can be
    an acceptance criterion, ``context`` an ADR and ``target_screen_id`` an edge.
    Keep the complete selected content and leave exact version references in the
    parent request. Copies prevent a file step from changing subsequent inputs.
    """
    return {
        "view": IMPLEMENTATION_VIEW,
        **(
            {"reference_aliases": deepcopy(context["reference_aliases"])}
            if "reference_aliases" in context
            else {}
        ),
        "content": {
            name: deepcopy(context[name]["content"])
            for name in IMPLEMENTATION_ARTIFACTS
            if name in context
        },
    }


def compact_implementation_references(context: dict[str, Any]) -> dict[str, Any]:
    """Losslessly intern repeated UUIDs/hashes in approved content, never business text.

    Exact artifact and provenance bindings outside ``content`` stay untouched.
    The dictionary travels with every model request so all relationships resolve.
    """
    counts: Counter[str] = Counter()
    strings: set[str] = set()
    pattern = re.compile(r"(?:[0-9a-f]{64}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\Z")

    def is_reference(key):
        return key == "id" or key.endswith(("_id", "_ids", "_hash"))

    def visit(value, key="", aliases=None):
        if isinstance(value, dict):
            return {name: visit(item, name, aliases) for name, item in value.items()}
        if isinstance(value, list):
            return [visit(item, key, aliases) for item in value]
        if isinstance(value, str):
            if aliases is None:
                strings.add(value)
                if is_reference(key) and pattern.fullmatch(value):
                    counts[value] += 1
            elif is_reference(key):
                return aliases.get(value, value)
        return value

    for name in IMPLEMENTATION_ARTIFACTS:
        if name in context:
            visit(context[name]["content"])
    aliases = {}
    for value, count in sorted(counts.items()):
        if count > 1:
            alias = f"@reference-{len(aliases) + 1}"
            while alias in strings:
                alias += "_"
            aliases[value] = alias
    result = deepcopy(context)
    if aliases:
        for name in IMPLEMENTATION_ARTIFACTS:
            if name in result:
                result[name]["content"] = visit(result[name]["content"], aliases=aliases)
                result[name]["content_encoding"] = "REFERENCE_DICTIONARY_V1"
        result["reference_aliases"] = {alias: value for value, alias in aliases.items()}
    return result
