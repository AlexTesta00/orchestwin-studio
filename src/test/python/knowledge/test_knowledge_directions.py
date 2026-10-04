from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import replace
from functools import cache

import pytest
from jsonschema import Draft202012Validator

from orchestwin.artifacts.design_packages import DesignExplorationPackage
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.generated_mockup_document import (
    CONTENT_SECURITY_POLICY,
    mockup_document,
)
from orchestwin.artifacts.visual_catalog import FontFamily
from orchestwin.artifacts.visual_directions import (
    DIRECTION_AXES,
    DIRECTION_AXIS_VALUES,
    HABITUAL_AXES,
    VisualDirection,
)
from orchestwin.artifacts.visual_fonts import (
    BUNDLED_FONTS,
    FONT_FILE_HASHES,
    bundled_families,
    font_faces,
)
from orchestwin.artifacts.visual_language import create_visual_language
from orchestwin.knowledge import documents
from orchestwin.knowledge import schema as schema_module
from orchestwin.knowledge.archive import (
    KnowledgeArchiveError,
    read_verified_folder,
    verify_folder,
)
from orchestwin.knowledge.comparison import document_differences, view_differences
from orchestwin.knowledge.folder import (
    KnowledgeFolder,
    build_knowledge_folder,
    file_digests,
    folder_archive,
    folder_content_hash,
    json_text,
)
from orchestwin.knowledge.layout import (
    KNOWLEDGE_MANIFEST,
    STAGES,
    schema_document,
    stage_document,
    stage_text,
)
from orchestwin.knowledge.schema import (
    SCHEMA_NAMES,
    KnowledgeSchemaError,
    has_design_additions,
    has_direction_additions,
    knowledge_schemas,
    schema_files,
    schema_name_for_path,
    validate_document,
    validate_files,
)
from orchestwin.knowledge.tables import DIRECTION_DIMENSIONS, design_tables
from orchestwin.knowledge.why import WHY_DOCUMENT, folder_why, normalized_why
from orchestwin.why import build_why_document, explain_why
from src.test.python.artifacts.test_visual_directions import (
    CONCEPT,
    RULES,
    axes,
    directed_language,
)
from src.test.python.artifacts.test_visual_directions import direction as visual_direction

from .knowledge_fixtures import PUBLISHED_AT, REAL_PROJECT_ID, real_sources, sources_of
from .test_knowledge_generated_mockup_import import exported_again, imported_documents, plan
from .test_knowledge_generated_mockup_support import (
    DASHBOARD,
    design_snapshot,
    generated_folder,
    generated_package,
    real_versions,
    repacked,
    selected_alternative,
)
from .test_tables import package as table_package
from .test_tables import records
from .test_tables import specification as table_specification

MOCKUP_DESIGN_SCHEMA_DIGEST = "87af8d8d070865b040b244a187669e8c173ef955533068f13f754eedf176f23e"
MOCKUP_FOLDER_CONTENT_HASH = "ee5706dcb9b0a748d2d3b33f2c92d3a641be32786473e60208844ce9b6b5eebc"
DESIGN_SCHEMA = schema_document("design")
WHY_SCHEMA = "schema/why.schema.json"
VISUAL_LANGUAGE_TABLE = "design/tables/visual-language.csv"
MOCKUP_FILE = "design/mockup.html"
FACE_SOURCE = re.compile(r"url\(data:font/woff2;base64,([A-Za-z0-9+/]+={0,2})\)")
FACE_FAMILIES = ("IBM Plex Mono", "Libre Franklin")
EXTERNAL_REFERENCES = (
    "url(",
    "://",
    "@import",
    "javascript:",
    " src=",
    "srcdoc",
    "<link",
    "<script",
    "<img",
    "<iframe",
    "<object",
    "<embed",
    "<base",
)
PLAIN_HEADING = "#### Visual language\n\nProduct name: "
INTERNAL_CODE = re.compile(r"\b[A-Z]{2,}(?:_[A-Z]+)*\b")
DIRECTION_DEFINITIONS = {
    "VisualDirection",
    "DirectionAxes",
    "DirectionLayout",
    "DirectionShape",
    "DirectionType",
    "DirectionColour",
    "DirectionDensity",
}
DIRECTION_KEYS = [
    "name",
    "concept",
    "rules",
    "axes",
    "typicality",
    "candidates",
    "vocabulary_version",
]
BANDS_CONCEPT = (
    "Full-width bands of soft tints, one purpose each, like the sections of a timetable. It "
    "suits volunteers who scan the list quickly while they stand at the entrance."
)
BANDS_RULES = (
    "Every screen is a stack of bands that span the window, each band with one purpose.",
    "Groups sit on soft tints of the primary colour and never have a border around them.",
    "The main action is a pill-shaped button at the end of the first band.",
)
PRINTED = visual_direction()
BANDS = visual_direction(
    name="Soft bands",
    concept=BANDS_CONCEPT,
    rules=BANDS_RULES,
    axes=axes("BANDS", "PILL", "READING", "TINTED", "COMFORTABLE"),
    typicality=4,
    candidates=6,
)
PRINTED_POSITIONS = (
    "Layout: Editorial page. Shapes: Square corners and rules. Type: Very large titles. "
    "Colour: Almost monochrome. Density: Spacious."
)
BANDS_POSITIONS = (
    "Layout: Bands. Shapes: Pills. Type: Reading. Colour: Tinted surfaces. Density: Comfortable."
)
WORDS = {
    "layout": (
        "Layout",
        {
            "PANELS": "Panels",
            "BANDS": "Bands",
            "EDITORIAL": "Editorial page",
            "STAGE": "Stage",
            "WORKBENCH": "Workbench",
            "MOSAIC": "Mosaic",
        },
    ),
    "shape": (
        "Shapes",
        {
            "ROUNDED_OUTLINE": "Rounded outlines",
            "SQUARE_RULES": "Square corners and rules",
            "HEAVY_FRAME": "Heavy frames",
            "SOFT_FILL": "Filled surfaces",
            "PILL": "Pills",
        },
    ),
    "type": (
        "Type",
        {
            "EVEN": "Restrained scale",
            "DISPLAY": "Very large titles",
            "CAPS_LABELS": "Upper-case labels",
            "READING": "Reading",
        },
    ),
    "colour": (
        "Colour",
        {
            "ACCENT_ONLY": "Colour on the action only",
            "FIELDS": "Fields of colour",
            "INK": "Almost monochrome",
            "TINTED": "Tinted surfaces",
        },
    ),
    "density": (
        "Density",
        {"COMPACT": "Compact", "COMFORTABLE": "Comfortable", "SPACIOUS": "Spacious"},
    ),
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@cache
def directed_package(name: str | None = None, *, second: bool = True) -> DesignExplorationPackage:
    package = real_versions()["design"].package if name is None else generated_package(name)
    chosen = (PRINTED, BANDS if second else None)
    return replace(
        package,
        alternatives=tuple(
            item
            if value is None
            else replace(item, visual_language=directed_language(item.visual_language, value))
            for item, value in zip(package.alternatives, chosen, strict=True)
        ),
    )


@cache
def directed_folder(name: str | None = None, *, second: bool = True) -> KnowledgeFolder:
    versions = real_versions()
    package = directed_package(name, second=second)
    design = replace(versions["design"], package=package, content_hash=package.content_hash)
    sources = sources_of({**versions, "design": design}, project_id=REAL_PROJECT_ID)
    return build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)


@cache
def plain_folder() -> KnowledgeFolder:
    return build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)


@cache
def bundled_folder() -> tuple[DesignExplorationPackage, KnowledgeFolder]:
    package = generated_package(DASHBOARD)
    selected = selected_alternative(package)
    visual = selected.visual_language
    language = create_visual_language(
        choices=replace(visual.choices, heading_family=FontFamily.GROTESQUE_SANS),
        product_name=visual.product_name,
        rationale=visual.rationale,
        twin_fit=visual.twin_fit,
        direction=BANDS,
    )
    package = replace(
        package,
        alternatives=tuple(
            replace(item, visual_language=language)
            if item.id == selected.id
            else replace(item, visual_language=directed_language(item.visual_language, PRINTED))
            for item in package.alternatives
        ),
    )
    versions = real_versions()
    design = replace(versions["design"], package=package, content_hash=package.content_hash)
    sources = sources_of({**versions, "design": design}, project_id=REAL_PROJECT_ID)
    return package, build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)


def why_alternatives(folder: KnowledgeFolder) -> dict[str, dict[str, object]]:
    nodes = json.loads(folder.files[WHY_DOCUMENT])["nodes"]
    return {node["code"]: node for node in nodes if node["kind"] == "DESIGN_ALTERNATIVE"}


def retraced(folder: KnowledgeFolder, design: dict[str, object]) -> dict[str, str]:
    files = repacked(folder, design)
    manifest = json.loads(files[KNOWLEDGE_MANIFEST])
    stages = {stage: json.loads(files[stage_document(stage)]) for stage in STAGES}
    why = folder_why(project_id=manifest["project"]["id"], documents=stages, files=files)
    files[WHY_DOCUMENT] = json_text(why)
    manifest["files"] = file_digests({path: files[path] for path in manifest["files"]})
    manifest["package"]["content_hash"] = folder_content_hash(files)
    files[KNOWLEDGE_MANIFEST] = json_text(manifest)
    return files


def tampered(change: Callable[[dict[str, object]], None]) -> dict[str, object]:
    design = design_snapshot(directed_folder())
    change(design["package"]["alternatives"][0]["visual_language"])
    return design


def first_direction(
    update: Callable[[dict[str, object]], object],
) -> Callable[[dict[str, object]], None]:
    def change(visual: dict[str, object]) -> None:
        update(visual["direction"])

    return change


def text_block(value: VisualDirection, positions: str) -> str:
    return "\n".join(
        [
            "#### Visual language",
            "",
            f"Visual direction: {value.name}.",
            "",
            value.concept,
            "",
            positions,
            "",
            *(f"- {rule}" for rule in value.rules),
            "",
            f"Proposed by the model among {value.candidates} candidates; chosen by the Studio "
            "because it is far from the other.",
            "",
            "Product name: ",
        ]
    )


def test_a_design_without_directions_keeps_every_byte_of_its_folder() -> None:
    folder = generated_folder(DASHBOARD)
    plain = plain_folder()

    assert not has_direction_additions(design_snapshot(folder)["package"])
    assert not has_direction_additions(design_snapshot(plain)["package"])
    assert digest(schema_files(design_additions=True)[DESIGN_SCHEMA]) == MOCKUP_DESIGN_SCHEMA_DIGEST
    assert digest(folder.files[DESIGN_SCHEMA]) == MOCKUP_DESIGN_SCHEMA_DIGEST
    assert folder.content_hash == MOCKUP_FOLDER_CONTENT_HASH
    for current in (folder, plain):
        schema = json.loads(current.files[DESIGN_SCHEMA])
        assert DIRECTION_DEFINITIONS.isdisjoint(schema["$defs"])
        assert "direction" not in schema["$defs"]["VisualLanguage"]["properties"]
        assert "Visual direction" not in current.files[stage_text("design")]
        assert "direction_" not in current.files[VISUAL_LANGUAGE_TABLE]
        assert not any(
            "direction" in node["declared_context"] for node in why_alternatives(current).values()
        )


def test_every_schema_but_the_design_schema_ignores_the_directions() -> None:
    for design in (False, True):
        extended = knowledge_schemas(design_additions=design, direction_additions=True)
        base = knowledge_schemas(design_additions=design)
        for name in SCHEMA_NAMES:
            if name != "design":
                assert extended[name] == base[name]
        assert set(extended["design"]["$defs"]) - set(base["design"]["$defs"]) == (
            DIRECTION_DEFINITIONS
        )
    assert knowledge_schemas(direction_additions=True, only_why=True) == knowledge_schemas(
        only_why=True
    )


def test_a_folder_with_directions_publishes_the_schema_that_describes_them() -> None:
    folder = directed_folder()
    package = design_snapshot(folder)["package"]
    published = json.loads(folder.files[DESIGN_SCHEMA])
    definitions = published["$defs"]
    direction = definitions["VisualDirection"]
    properties = direction["properties"]
    language = definitions["VisualLanguage"]["properties"]

    Draft202012Validator.check_schema(published)
    assert has_direction_additions(package)
    assert not has_design_additions(package)
    assert folder.files[DESIGN_SCHEMA] == schema_files(direction_additions=True)[DESIGN_SCHEMA]
    assert set(definitions) - set(knowledge_schemas()["design"]["$defs"]) == DIRECTION_DEFINITIONS
    assert language["direction"] == {
        "$ref": "#/$defs/VisualDirection",
        "description": language["direction"]["description"],
    }
    assert "direction" not in definitions["VisualLanguage"]["required"]
    assert direction["required"] == DIRECTION_KEYS
    assert direction["additionalProperties"] is False
    assert definitions["DirectionAxes"]["required"] == list(DIRECTION_AXES)
    assert definitions["DirectionAxes"]["additionalProperties"] is False
    assert (properties["name"]["maxLength"], properties["concept"]["maxLength"]) == (60, 400)
    assert (properties["rules"]["minItems"], properties["rules"]["maxItems"]) == (3, 5)
    assert properties["rules"]["items"]["maxLength"] == 240
    assert (properties["typicality"]["minimum"], properties["typicality"]["maximum"]) == (0, 100)
    assert (properties["candidates"]["minimum"], properties["candidates"]["maximum"]) == (2, 20)
    assert properties["vocabulary_version"]["minimum"] == 1
    for axis, values in DIRECTION_AXIS_VALUES.items():
        reference = definitions["DirectionAxes"]["properties"][axis]["$ref"]
        assert reference == f"#/$defs/{values.__name__}"
        assert definitions[values.__name__]["enum"] == [item.value for item in values]
        assert getattr(schema_module, values.__name__) is values
    described = [
        language["direction"],
        *properties.values(),
        *definitions["DirectionAxes"]["properties"].values(),
    ]
    assert all(item["description"].strip() for item in described)
    assert folder.files[WHY_SCHEMA] == plain_folder().files[WHY_SCHEMA]
    assert folder.entries == plain_folder().entries


def test_the_schema_bounds_of_a_direction_are_those_of_the_domain() -> None:
    validator = Draft202012Validator(knowledge_schemas(direction_additions=True)["design"])
    document = design_snapshot(directed_folder())
    visual = document["package"]["alternatives"][0]["visual_language"]

    for typicality, candidates in ((0, 2), (100, 20)):
        value = replace(PRINTED, typicality=typicality, candidates=candidates)
        visual["direction"] = value.to_snapshot()
        validate_document("design", document)
        assert validator.is_valid(document)
    for changes in ({"typicality": 101}, {"typicality": -1}, {"candidates": 1}, {"candidates": 21}):
        with pytest.raises(ValueError):
            replace(PRINTED, **changes)
        visual["direction"] = {**PRINTED.to_snapshot(), **changes}
        with pytest.raises(KnowledgeSchemaError):
            validate_document("design", document)
        assert not validator.is_valid(document)


@pytest.mark.parametrize(
    ("name", "second"), [(None, True), (None, False), (DASHBOARD, True)], ids=str
)
def test_every_document_of_a_folder_with_directions_matches_its_published_schema(
    name: str | None, second: bool
) -> None:
    folder = directed_folder(name, second=second)
    package = design_snapshot(folder)["package"]
    published = schema_files(
        design_additions=has_design_additions(package), direction_additions=True
    )

    validate_files(folder.files)
    assert has_design_additions(package) is (name is not None)
    assert folder.files[DESIGN_SCHEMA] == published[DESIGN_SCHEMA]
    for path, text in folder.files.items():
        schema = schema_name_for_path(path)
        if schema is None:
            continue
        validator = Draft202012Validator(json.loads(folder.files[schema_document(schema)]))
        payload = json.loads(text)
        assert [error.message for error in validator.iter_errors(payload)] == [], path
        validate_document(schema, payload)


def test_the_design_document_carries_each_direction_as_its_snapshot() -> None:
    package = design_snapshot(directed_folder(second=False))["package"]
    first, second = package["alternatives"]

    assert package == directed_package(second=False).to_snapshot()
    assert first["visual_language"]["direction"] == PRINTED.to_snapshot()
    assert set(first["visual_language"]["direction"]) == set(DIRECTION_KEYS)
    assert "direction" not in second["visual_language"]
    assert second == real_versions()["design"].package.to_snapshot()["alternatives"][1]


def test_verification_accepts_the_directions_and_rebuilds_the_same_package() -> None:
    folder = directed_folder()
    verified = verify_folder(folder.files)
    rebuilt = design_package_from_snapshot(verified.documents["design"]["package"])

    assert rebuilt == directed_package()
    assert rebuilt.content_hash == verified.documents["design"]["content_hash"]
    assert rebuilt.content_hash == directed_package().content_hash
    assert rebuilt.content_hash != real_versions()["design"].package.content_hash
    assert [item.visual_language.direction for item in rebuilt.alternatives] == [PRINTED, BANDS]
    assert read_verified_folder(folder_archive(folder).content).content_hash == folder.content_hash


@pytest.mark.parametrize(
    ("name", "second"), [(None, True), (None, False), (DASHBOARD, True)], ids=str
)
def test_import_keeps_the_directions_through_a_round_trip(name: str | None, second: bool) -> None:
    exported = directed_folder(name, second=second)
    source = verify_folder(exported.files)

    imported = plan(source)
    stages = imported_documents(imported)
    again = exported_again(imported)
    target = verify_folder(again.files)
    derived = build_why_document(
        project_id=str(imported.project_id),
        stages=stages,
        evidence=imported.research_evidence,
        evaluations=[
            {
                "runs": [item.to_snapshot() for item in imported.evaluations],
                "decisions": [item.to_snapshot() for item in imported.finding_decisions],
            }
        ],
    )

    assert [item.visual_language.direction for item in imported.design.package.alternatives] == [
        PRINTED,
        BANDS if second else None,
    ]
    assert design_package_from_snapshot(stages["design"]["package"]) == imported.design.package
    assert document_differences(source.documents, target.documents) == []
    assert view_differences(source.files, again.files) == []
    for path in (DESIGN_SCHEMA, WHY_SCHEMA, VISUAL_LANGUAGE_TABLE):
        assert again.files[path] == exported.files[path], path
    assert normalized_why(
        json.loads(exported.files[WHY_DOCUMENT]),
        identities=imported.identities,
        hashes=imported.hashes,
    ) == normalized_why(derived)


def test_the_mockup_of_a_directed_design_embeds_its_bundled_faces_and_nothing_external() -> None:
    package, folder = bundled_folder()
    language = selected_alternative(package).visual_language
    tokens = dict(language.tokens)
    document = folder.files[MOCKUP_FILE]
    faces = FACE_SOURCE.findall(document)
    decoded = [hashlib.sha256(base64.b64decode(face, validate=True)).hexdigest() for face in faces]
    recorded = [
        FONT_FILE_HASHES[BUNDLED_FONTS[family].file_name(weight)]
        for family in FACE_FAMILIES
        for weight in BUNDLED_FONTS[family].weights
    ]
    outside = FACE_SOURCE.sub("", document).lower()
    mockup = package.generated_mockup

    assert language.choices.heading_family is FontFamily.GROTESQUE_SANS
    assert language.direction == BANDS
    assert tokens["--vl-font-heading"].startswith('"Libre Franklin", ')
    assert bundled_families(tokens) == FACE_FAMILIES
    assert mockup is not None
    assert document == mockup_document(mockup.mockup, tokens=tokens, language="it")
    assert f"<style>{font_faces(tokens)}:root{{" in document
    assert f'content="{CONTENT_SECURITY_POLICY}"' in document
    assert "font-src data:" in CONTENT_SECURITY_POLICY
    assert document.count("@font-face") == len(faces) == len(recorded) == 5
    assert decoded == recorded
    assert [item for item in EXTERNAL_REFERENCES if item in outside] == []
    assert "://" not in document


def test_a_folder_with_bundled_faces_passes_verification_and_import_with_its_hash() -> None:
    package, folder = bundled_folder()
    verified = verify_folder(folder.files)
    archived = read_verified_folder(folder_archive(folder).content)
    rebuilt = design_package_from_snapshot(archived.documents["design"]["package"])

    imported = plan(archived)
    again = exported_again(imported)
    target = verify_folder(again.files)

    assert verified.content_hash == archived.content_hash == folder.content_hash
    assert verified.documents == archived.documents
    assert rebuilt == package
    assert rebuilt.content_hash == package.content_hash
    assert rebuilt.content_hash == archived.documents["design"]["content_hash"]
    assert imported.origin.package_content_hash == folder.content_hash
    assert imported.design is not None
    assert [
        (item.visual_language.direction, item.visual_language.tokens)
        for item in imported.design.package.alternatives
    ] == [
        (item.visual_language.direction, item.visual_language.tokens)
        for item in package.alternatives
    ]
    assert again.files[MOCKUP_FILE] == folder.files[MOCKUP_FILE]
    assert document_differences(archived.documents, target.documents) == []


@pytest.mark.parametrize(
    ("change", "location"),
    [
        (
            first_direction(lambda value: value["axes"].update(layout="NEON")),
            "direction.axes.layout",
        ),
        (
            first_direction(lambda value: value["axes"].update(motion="CALM")),
            "direction.axes.motion",
        ),
        (first_direction(lambda value: value.update(mood="calm")), "direction.mood"),
        (first_direction(lambda value: value.pop("candidates")), "direction.candidates"),
        (first_direction(lambda value: value.update(candidates=True)), "direction.candidates"),
        (first_direction(lambda value: value.update(typicality=101)), "direction.typicality"),
        (first_direction(lambda value: value.update(rules=list(RULES[:2]))), "direction.rules"),
        (first_direction(lambda value: value.update(name="n" * 61)), "direction.name"),
        (
            first_direction(lambda value: value.update(vocabulary_version=0)),
            "direction.vocabulary_version",
        ),
        (lambda visual: visual.update(direction=None), "direction"),
    ],
)
def test_verification_refuses_a_malformed_direction(
    change: Callable[[dict[str, object]], None], location: str
) -> None:
    design = tampered(change)
    validator = Draft202012Validator(knowledge_schemas(direction_additions=True)["design"])

    with pytest.raises(KnowledgeArchiveError) as caught:
        verify_folder(retraced(directed_folder(), design))

    assert caught.value.code == "FOLDER_DOCUMENT_INVALID"
    assert caught.value.detail == f"design: package.alternatives[0].visual_language.{location}"
    assert not validator.is_valid(design)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            first_direction(lambda value: value.update(name=f" {value['name']}")),
            "visual direction name must be normalized",
        ),
        (
            first_direction(lambda value: value.update(concept=f"{value['concept']} ")),
            "visual direction concept must be normalized",
        ),
        (
            first_direction(lambda value: value.update(rules=[*value["rules"][:2], "A  rule."])),
            "visual direction rule must be normalized",
        ),
    ],
)
def test_the_import_refuses_a_direction_that_is_not_in_its_stored_form(
    change: Callable[[dict[str, object]], None], message: str
) -> None:
    verified = verify_folder(retraced(directed_folder(), tampered(change)))

    with pytest.raises(KnowledgeArchiveError) as refused:
        plan(verified)

    assert (refused.value.code, refused.value.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"design: {message}",
    )


def test_a_direction_renamed_after_the_export_breaks_the_why_of_the_folder() -> None:
    design = tampered(first_direction(lambda value: value.update(name="Another register")))

    with pytest.raises(KnowledgeArchiveError) as caught:
        verify_folder(repacked(directed_folder(), design))

    assert (caught.value.code, caught.value.detail) == ("FOLDER_TAMPERED", WHY_DOCUMENT)


def test_the_design_text_shows_the_direction_right_after_the_visual_language_heading() -> None:
    text = directed_folder().files[stage_text("design")]
    printed = text_block(PRINTED, PRINTED_POSITIONS)
    bands = text_block(BANDS, BANDS_POSITIONS)
    blocks = [part.split("Product name: ", 1)[0] for part in text.split("Visual direction: ")[1:]]

    assert text.index("### DES-001") < text.index(printed) < text.index("### DES-002")
    assert text.index("### DES-002") < text.index(bands) < text.index("## Concerns")
    assert len(blocks) == 2
    assert PLAIN_HEADING not in text
    assert [INTERNAL_CODE.findall(block) for block in blocks] == [[], []]


def test_a_design_text_shows_only_the_directions_that_exist() -> None:
    directed = directed_folder(second=False).files[stage_text("design")]
    plain = plain_folder().files[stage_text("design")]
    before, after = directed.split(text_block(PRINTED, PRINTED_POSITIONS))
    hashes = (real_versions()["design"].content_hash, directed_package(second=False).content_hash)
    second = directed.replace(hashes[1], hashes[0]).split("### DES-002", 1)[1]
    first = plain.split("### DES-001", 1)[1].split("### DES-002", 1)[0]

    assert directed.count("Visual direction: ") == 1
    assert directed.count(PLAIN_HEADING) == 1
    assert plain.count(PLAIN_HEADING) == 2
    assert PLAIN_HEADING not in before
    assert second == plain.split("### DES-002", 1)[1]
    assert after.split("### DES-002", 1)[0] == first.split(PLAIN_HEADING, 1)[1]


@pytest.mark.parametrize("axis", DIRECTION_AXES)
def test_every_axis_value_is_written_with_the_english_words_of_the_contract(axis: str) -> None:
    label, words = WORDS[axis]

    assert list(words) == [item.value for item in DIRECTION_AXIS_VALUES[axis]]
    for item in DIRECTION_AXIS_VALUES[axis]:
        value = visual_direction(axes=replace(HABITUAL_AXES, **{axis: item}))
        lines = documents._visual_direction_lines(value.to_snapshot())
        expected = " ".join(
            f"{WORDS[name][0]}: {WORDS[name][1][getattr(value.axes, name).value]}."
            for name in DIRECTION_AXES
        )
        assert lines[4] == expected
        assert f"{label}: {words[item.value]}." in lines[4]
        assert INTERNAL_CODE.findall(lines[4]) == []
    assert documents._visual_direction_lines(None) == []


def test_the_visual_language_table_adds_the_direction_only_to_directed_alternatives() -> None:
    folder = directed_folder(second=False)
    table = folder.files[VISUAL_LANGUAGE_TABLE]
    rows = records(table)
    plain = records(plain_folder().files[VISUAL_LANGUAGE_TABLE])
    first = [row for row in plain if row["alternative"] == "DES-001"]
    added = [row for row in rows if row["dimension"].startswith("direction_")]

    assert DIRECTION_DIMENSIONS == (
        "direction_name",
        "direction_layout",
        "direction_shape",
        "direction_type",
        "direction_colour",
        "direction_density",
    )
    assert table.splitlines()[0] == "alternative,dimension,value"
    assert added == [
        {"alternative": "DES-001", "dimension": dimension, "value": value}
        for dimension, value in zip(
            DIRECTION_DIMENSIONS,
            ("Printed register", "EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS"),
            strict=True,
        )
    ]
    assert rows[len(first) : len(first) + len(added)] == added
    assert [row for row in rows if row not in added] == plain
    for path, text in plain_folder().files.items():
        if path.startswith("design/tables/") and path != VISUAL_LANGUAGE_TABLE:
            assert folder.files[path] == text, path


def test_a_direction_name_never_becomes_a_spreadsheet_formula() -> None:
    snapshot = table_package()
    snapshot["alternatives"][1]["visual_language"]["direction"] = visual_direction(
        name="=Printed register"
    ).to_snapshot()

    tables = design_tables(snapshot, table_specification())
    plain = design_tables(table_package(), table_specification())

    assert "\nDES-002,direction_name,'=Printed register\n" in tables[VISUAL_LANGUAGE_TABLE]
    assert tables[VISUAL_LANGUAGE_TABLE].startswith(plain[VISUAL_LANGUAGE_TABLE])
    assert {path: text for path, text in tables.items() if path != VISUAL_LANGUAGE_TABLE} == {
        path: text for path, text in plain.items() if path != VISUAL_LANGUAGE_TABLE
    }


def test_the_why_declares_the_direction_only_of_a_directed_alternative() -> None:
    folder = directed_folder(second=False)
    nodes = why_alternatives(folder)
    plain = why_alternatives(plain_folder())
    first, second = nodes["DES-001"], nodes["DES-002"]
    document = json.loads(folder.files[WHY_DOCUMENT])

    answer = explain_why(document, first["key"])

    assert first["declared_context"]["direction"] == {
        "name": "Printed register",
        "concept": CONCEPT,
        "axes": {
            "layout": "EDITORIAL",
            "shape": "SQUARE_RULES",
            "type": "DISPLAY",
            "colour": "INK",
            "density": "SPACIOUS",
        },
        "candidates": 5,
        "origin": "MODEL",
        "selected_by": "STUDIO",
    }
    assert {
        key: value for key, value in first["declared_context"].items() if key != "direction"
    } == plain["DES-001"]["declared_context"]
    assert second["declared_context"] == plain["DES-002"]["declared_context"]
    assert "direction" not in second["declared_context"]
    assert answer["declared_context"] == first["declared_context"]
    assert answer["target"]["declared_context"]["direction"]["name"] == "Printed register"


def test_both_alternatives_declare_their_own_direction_in_the_why() -> None:
    nodes = why_alternatives(directed_folder())
    names = {code: node["declared_context"]["direction"]["name"] for code, node in nodes.items()}

    assert names == {"DES-001": "Printed register", "DES-002": "Soft bands"}
    assert nodes["DES-002"]["declared_context"]["direction"]["candidates"] == 6
    assert nodes["DES-002"]["declared_context"]["direction"]["axes"] == BANDS.axes.to_snapshot()
