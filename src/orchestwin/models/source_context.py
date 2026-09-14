"""Lossless implementation content from the application's approved artifact views."""

from copy import deepcopy
from typing import Any

IMPLEMENTATION_VIEW = "SOURCE_SEMANTIC_CONTENT_V2"
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
        "definition_of_done": ("code", "applicability", "condition", "statement"),
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
        "content": {
            name: deepcopy(context[name]["content"])
            for name in IMPLEMENTATION_ARTIFACTS
            if name in context
        },
    }
