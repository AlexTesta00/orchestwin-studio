from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from orchestwin.artifacts.why_runtime import _mockup_package

from . import design_fixtures
from .test_visual_directions import directed_language


def test_a_stored_mockup_package_reads_null_keys_of_its_visual_languages_as_absent() -> None:
    language = design_fixtures.visual_language()
    fixture = design_fixtures.design_package()
    package = replace(
        fixture,
        alternatives=tuple(
            replace(item, visual_language=item.visual_language or directed_language(language))
            for item in fixture.alternatives
        ),
    )
    snapshot = package.to_snapshot()
    stored = deepcopy(snapshot)
    for item in stored["alternatives"]:
        item["visual_language"]["design_system"] = None
    stored["alternatives"][1]["visual_language"]["direction"] = None

    restored = _mockup_package(stored)

    assert [item.visual_language.design_system for item in restored.alternatives] == [None, None]
    assert restored == package == _mockup_package(snapshot)
    assert restored.to_snapshot() == snapshot
