from __future__ import annotations

import hashlib

from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_structure import nodes_text
from orchestwin.artifacts.generated_mockups import screen_trees
from orchestwin.models.output_language import dominant_language


def mockup_document_hashes(package) -> dict[str, str]:
    bound = package.generated_mockup
    if bound is None:
        return {}
    alternative = next(
        (item for item in package.alternatives if item.id == bound.design_alternative_id), None
    )
    if alternative is None or alternative.visual_language is None:
        return {}
    mockup = bound.mockup
    trees = screen_trees(mockup)
    language = (
        dominant_language(nodes_text(trees[screen.code]) for screen in mockup.screens) or "en"
    )
    return {
        screen.code: hashlib.sha256(
            mockup_document(
                mockup,
                tokens=alternative.visual_language.token_values,
                language=language,
                entry_screen=screen.code,
            ).encode("utf-8")
        ).hexdigest()
        for screen in mockup.screens
    }


__all__ = ["mockup_document_hashes"]
