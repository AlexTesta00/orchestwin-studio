from __future__ import annotations

import json
from dataclasses import replace
from functools import cache
from uuid import UUID

from orchestwin.artifacts.design_packages import DesignExplorationPackage
from orchestwin.artifacts.visual_language import create_visual_language
from orchestwin.knowledge import documents
from orchestwin.knowledge.folder import KnowledgeFolder, build_knowledge_folder
from orchestwin.knowledge.layout import stage_document, stage_text
from orchestwin.knowledge.schema import validate_document
from orchestwin.models.design_systems import APPLE_HIG, system_direction

from .knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, sources_of
from .test_knowledge_directions import directed_folder, directed_package
from .test_knowledge_generated_mockup_support import real_versions

DESIGN_TEXT = stage_text("design")
DESIGN_DOCUMENT = stage_document("design")
CODES = ("DES-001", "DES-002", "DES-003")
SYSTEM_LINE = "Design system: Apple Human Interface Guidelines."
SYSTEM_ORIGIN = "Direction of the Apple Human Interface Guidelines design system."
MODEL_ORIGIN = (
    "Proposed by the model among {count} candidates; chosen by the Studio because it is far from "
    "the other."
)
THIRD_ID = UUID("00000000-0000-4000-8000-000000004503")


@cache
def three_package(system: bool = True) -> DesignExplorationPackage:
    package = directed_package()
    second = package.alternatives[1]
    visual = second.visual_language
    assert visual is not None
    language = create_visual_language(
        choices=visual.choices,
        product_name=visual.product_name,
        rationale=visual.rationale,
        twin_fit=visual.twin_fit,
        direction=system_direction(APPLE_HIG),
        design_system=APPLE_HIG,
    )
    if not system:
        language = replace(language, design_system=None)
    third = replace(
        second,
        id=THIRD_ID,
        code="DES-003",
        approach=None,
        title="System screens",
        workflows=tuple(
            replace(item, id=UUID(int=0x4510 + index))
            for index, item in enumerate(second.workflows)
        ),
        visual_language=language,
    )
    last = max(int(item.code.split("-")[1]) for item in package.critiques)
    copies = tuple(
        replace(
            item,
            id=UUID(int=0x4520 + index),
            code=f"CRQ-{last + index + 1:03d}",
            design_alternative_id=THIRD_ID,
        )
        for index, item in enumerate(
            item for item in package.critiques if item.design_alternative_id == second.id
        )
    )
    return replace(
        package,
        alternatives=(*package.alternatives, third),
        critiques=(*package.critiques, *copies),
    )


@cache
def three_folder(system: bool = True) -> KnowledgeFolder:
    versions = real_versions()
    package = three_package(system)
    design = replace(versions["design"], package=package, content_hash=package.content_hash)
    sources = sources_of({**versions, "design": design}, project_id=REAL_PROJECT_ID)
    return build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)


def sections(text: str) -> dict[str, str]:
    body = text.split("## Concerns")[0]
    parts = body.split("\n### ")[1:]
    return {part.split(":")[0]: part.rstrip() for part in parts}


def test_the_dossier_lists_the_three_alternatives_and_names_the_design_system_of_the_third() -> (
    None
):
    text = three_folder().files[DESIGN_TEXT]
    found = sections(text)

    assert list(found) == list(CODES)
    assert text.count(SYSTEM_LINE) == 1
    assert (
        "#### Visual language\n\n"
        f"{SYSTEM_LINE}\n\n"
        "Visual direction: Apple Human Interface Guidelines."
    ) in found["DES-003"]
    assert SYSTEM_ORIGIN in found["DES-003"]
    assert "Proposed by the model" not in found["DES-003"]
    for code in CODES[:2]:
        assert "Design system" not in found[code]
        assert "Proposed by the model among" in found[code]
        assert SYSTEM_ORIGIN not in found[code]


def test_without_the_design_system_every_other_byte_of_the_dossier_text_is_kept() -> None:
    with_system = three_folder().files[DESIGN_TEXT]
    without = three_folder(system=False).files[DESIGN_TEXT]
    directed = directed_folder().files[DESIGN_TEXT]

    assert "Design system" not in without
    assert "Design system" not in directed
    assert SYSTEM_ORIGIN not in without + directed
    third = sections(with_system)["DES-003"]
    assert (
        third.replace(f"{SYSTEM_LINE}\n\n", "", 1).replace(
            SYSTEM_ORIGIN, MODEL_ORIGIN.format(count=2), 1
        )
        == sections(without)["DES-003"]
    )
    assert with_system.split("## Concerns")[1] == without.split("## Concerns")[1]
    for code in CODES[:2]:
        assert sections(with_system)[code] == sections(without)[code] == sections(directed)[code]


def test_the_design_document_of_the_dossier_keeps_the_design_system_of_the_third_only() -> None:
    document = json.loads(three_folder().files[DESIGN_DOCUMENT])
    plain = json.loads(three_folder(system=False).files[DESIGN_DOCUMENT])

    validate_document("design", document)
    visuals = [item["visual_language"] for item in document["package"]["alternatives"]]
    assert [item.get("design_system") for item in visuals] == [None, None, "apple-hig"]
    assert ["design_system" in item for item in visuals] == [False, False, True]
    assert not any(
        "design_system" in item["visual_language"] for item in plain["package"]["alternatives"]
    )


def test_a_design_system_line_names_a_known_system_and_keeps_an_unknown_identifier() -> None:
    direction = system_direction(APPLE_HIG).to_snapshot()

    assert documents._design_system_lines("apple-hig") == [SYSTEM_LINE, ""]
    assert documents._design_system_lines("material") == ["Design system: material.", ""]
    assert documents._design_system_lines(None) == []
    assert documents._visual_direction_lines(direction, system="apple-hig")[-2] == SYSTEM_ORIGIN
    assert documents._visual_direction_lines(direction, system="material")[-2] == (
        "Direction of the material design system."
    )
    assert documents._visual_direction_lines(direction)[-2] == MODEL_ORIGIN.format(count=2)
