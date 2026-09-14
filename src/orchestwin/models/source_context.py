"""Lossless implementation content from the application's approved artifact views."""

from copy import deepcopy
from typing import Any

IMPLEMENTATION_VIEW = "SOURCE_SEMANTIC_CONTENT_V2"
IMPLEMENTATION_ARTIFACTS = ("requirements", "architecture", "design")


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
