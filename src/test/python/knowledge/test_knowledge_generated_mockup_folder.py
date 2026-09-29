from __future__ import annotations

import csv
import hashlib
import io
import json
import re

import pytest
from jsonschema import Draft202012Validator

from orchestwin.artifacts.generated_mockup_document import (
    CONTENT_SECURITY_POLICY,
    mockup_document,
)
from orchestwin.knowledge.archive import (
    MAX_ARCHIVE_ENTRIES,
    MAX_ARCHIVE_SIZE,
    MAX_ENTRY_SIZE,
    read_verified_folder,
)
from orchestwin.knowledge.folder import (
    DESIGN_CRITIQUES_TEXT,
    DESIGN_MOCKUPS_TEXT,
    build_knowledge_folder,
    folder_archive,
    folder_content_hash,
)
from orchestwin.knowledge.layout import (
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    schema_document,
    stage_text,
)
from orchestwin.knowledge.schema import (
    SCHEMA_NAMES,
    KnowledgeSchemaError,
    has_design_additions,
    knowledge_schemas,
    schema_files,
    schema_name_for_path,
    validate_document,
    validate_files,
)
from orchestwin.knowledge.tables import CRITIQUE_VERDICT_COLUMNS, TABLE_COLUMNS

from .knowledge_fixtures import PUBLISHED_AT, real_sources
from .test_knowledge_generated_mockup_support import (
    ASSERTIONS,
    DASHBOARD,
    LARGE,
    MOCKUPS,
    REAL_DESIGN_SCHEMA_DIGEST,
    REAL_FOLDER_CONTENT_HASH,
    VERDICTS,
    design_snapshot,
    generated_folder,
    generated_package,
    selected_alternative,
)

MOCKUP_FILE = "design/mockup.html"
CRITIQUES_TABLE = "design/tables/critiques.csv"
ADDITION_DEFINITIONS = {"BoundGeneratedMockup", "GeneratedMockup", "GeneratedMockupScreen"}
TAG = re.compile(r"<[a-zA-Z][^>]*>")
HANDLER = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
LINK = re.compile(r'href="([^"]*)"')
SECTION = re.compile(r'<section class="ot-screen" id="(SCR-[0-9]{3})"([^>]*)>')


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def derived_elements(name: str) -> int:
    prototype = generated_package(name).prototype
    assert prototype is not None
    return sum(len(screen.elements) for screen in prototype.screens)


def sections(document: str) -> dict[str, tuple[str, str]]:
    parts = SECTION.split(document)
    return {parts[index]: (parts[index + 1], parts[index + 2]) for index in range(1, len(parts), 3)}


def test_a_folder_without_additions_keeps_every_byte_and_its_content_hash() -> None:
    sources = real_sources()
    folder = build_knowledge_folder(sources, version_number=3, created_at=PUBLISHED_AT)
    design = folder.files[schema_document("design")]

    assert not has_design_additions(sources.payload("design"))
    assert folder.content_hash == REAL_FOLDER_CONTENT_HASH
    assert digest(design) == REAL_DESIGN_SCHEMA_DIGEST
    assert {path: folder.files[path] for path in schema_files()} == schema_files()
    assert ADDITION_DEFINITIONS.isdisjoint(json.loads(design)["$defs"])
    assert "verdict" not in json.loads(design)["$defs"]["DesignCritique"]["properties"]
    assert rows(folder.files[CRITIQUES_TABLE])[0].keys() == set(TABLE_COLUMNS[CRITIQUES_TABLE])
    assert "## Owner assertions" not in folder.files[stage_text("design")]
    assert "Verdict:" not in folder.files[DESIGN_CRITIQUES_TEXT]


@pytest.mark.parametrize("name", MOCKUPS)
def test_every_file_of_a_folder_with_the_additions_is_listed_hashed_and_valid(name: str) -> None:
    folder = generated_folder(name)
    plain = build_knowledge_folder(real_sources(), version_number=1, created_at=PUBLISHED_AT)
    manifest = json.loads(folder.files[KNOWLEDGE_MANIFEST])

    assert folder.entries == plain.entries
    assert manifest["schema_version"] == 2
    assert manifest == folder.manifest
    assert set(manifest["files"]) == set(folder.files) - {KNOWLEDGE_INDEX, KNOWLEDGE_MANIFEST}
    for path, value in manifest["files"].items():
        assert value == digest(folder.files[path])
    assert manifest["package"]["content_hash"] == folder_content_hash(folder.files)
    assert folder.content_hash != plain.content_hash
    assert manifest["views"]["design"]["mockups"] == [
        {"path": MOCKUP_FILE, "title": "Static mockup of the selected alternative"}
    ]
    validate_files(folder.files)
    for path, text in folder.files.items():
        schema = schema_name_for_path(path)
        if schema is None:
            continue
        published = Draft202012Validator(json.loads(folder.files[schema_document(schema)]))
        payload = json.loads(text)
        assert [error.message for error in published.iter_errors(payload)] == [], path
        validate_document(schema, payload)


@pytest.mark.parametrize("name", MOCKUPS)
def test_the_manifest_names_every_element_of_the_derived_prototype(name: str) -> None:
    identifiers = generated_folder(name).manifest["identifiers"]
    prototype = generated_package(name).prototype
    assert prototype is not None

    elements = [entry for entry in identifiers if entry["kind"] == "PROTOTYPE_ELEMENT"]

    assert len(elements) == derived_elements(name)
    assert [entry["code"] for entry in elements] == [
        element.code for screen in prototype.screens for element in screen.elements
    ]
    assert {entry["id"] for entry in elements} == {
        str(element.id) for screen in prototype.screens for element in screen.elements
    }


def test_the_design_document_carries_the_mockup_the_assertions_and_the_verdicts() -> None:
    folder = generated_folder(DASHBOARD)
    package = generated_package(DASHBOARD)
    snapshot = design_snapshot(folder)["package"]
    assert package.generated_mockup is not None

    assert snapshot == package.to_snapshot()
    assert snapshot["generated_mockup"] == package.generated_mockup.to_snapshot()
    assert snapshot["owner_assertions"] == list(ASSERTIONS)
    assert [
        (item.get("verdict"), item.get("quote")) for item in snapshot["critiques"][: len(VERDICTS)]
    ] == list(VERDICTS)
    assert all("verdict" not in item for item in snapshot["critiques"][len(VERDICTS) :])
    assert snapshot["prototype"] == package.generated_mockup.prototype().to_snapshot()


def test_the_published_design_schema_describes_the_additions_only_when_they_travel() -> None:
    extended = json.loads(generated_folder(DASHBOARD).files[schema_document("design")])
    base = knowledge_schemas()["design"]
    critique = extended["$defs"]["DesignCritique"]
    package = extended["$defs"]["DesignPackageSnapshot"]["properties"]

    Draft202012Validator.check_schema(extended)
    assert extended == knowledge_schemas(design_additions=True)["design"]
    assert extended["$id"] == base["$id"] == "urn:orchestwin:knowledge-folder:2:design"
    assert set(extended["$defs"]) - set(base["$defs"]) == ADDITION_DEFINITIONS
    assert critique["dependentRequired"] == {"quote": ["verdict"], "verdict": ["quote"]}
    assert {critique["properties"][name]["maxLength"] for name in ("verdict", "quote")} == {60, 240}
    assert package["owner_assertions"]["maxItems"] == 20
    assert package["generated_mockup"] == {
        "$ref": "#/$defs/BoundGeneratedMockup",
        "description": package["generated_mockup"]["description"],
    }
    for name in SCHEMA_NAMES:
        if name != "design":
            assert knowledge_schemas(design_additions=True)[name] == knowledge_schemas()[name]
    added = [
        *(extended["$defs"][name]["properties"].values() for name in ADDITION_DEFINITIONS),
        [critique["properties"]["verdict"], critique["properties"]["quote"]],
        [package["generated_mockup"], package["owner_assertions"]],
    ]
    assert all(item["description"].strip() for group in added for item in group)


@pytest.mark.parametrize(
    ("name", "options", "expected"),
    [
        (None, {"assertions": (), "verdicts": ()}, False),
        (None, {"assertions": ASSERTIONS, "verdicts": ()}, True),
        (None, {"assertions": (), "verdicts": VERDICTS}, True),
        (DASHBOARD, {"assertions": (), "verdicts": ()}, True),
    ],
)
def test_each_addition_alone_selects_the_schema_that_describes_it(
    name: str | None, options: dict[str, tuple], expected: bool
) -> None:
    folder = generated_folder(name, **options)
    package = design_snapshot(folder)["package"]
    schema = json.loads(folder.files[schema_document("design")])

    assert has_design_additions(package) is expected
    assert (set(schema["$defs"]) >= ADDITION_DEFINITIONS) is expected
    published = schema_files(design_additions=expected)
    assert folder.files[schema_document("design")] == published[schema_document("design")]
    validate_files(folder.files)


def test_a_document_with_half_a_verdict_or_empty_additions_breaks_the_schema() -> None:
    document = design_snapshot(generated_folder(DASHBOARD))
    critique = document["package"]["critiques"][0]
    validator = Draft202012Validator(knowledge_schemas(design_additions=True)["design"])
    broken = [
        {**critique, "quote": None},
        {key: value for key, value in critique.items() if key != "quote"},
        {**critique, "verdict": "v" * 61},
    ]

    for item in broken:
        payload = json.loads(json.dumps(document))
        payload["package"]["critiques"][0] = item
        with pytest.raises(KnowledgeSchemaError) as caught:
            validate_document("design", payload)
        assert caught.value.code == "DOCUMENT_INVALID"
        assert caught.value.location.startswith("package.critiques[0]")
        assert not validator.is_valid(payload)
    for key, value in (("owner_assertions", []), ("generated_mockup", None)):
        payload = json.loads(json.dumps(document))
        payload["package"][key] = value
        with pytest.raises(KnowledgeSchemaError) as caught:
            validate_document("design", payload)
        assert caught.value.location == f"package.{key}"
        assert not validator.is_valid(payload)


def test_the_design_text_lists_the_owner_assertions_in_their_order() -> None:
    text = generated_folder(DASHBOARD).files[stage_text("design")]
    without_mockup = generated_folder(None, verdicts=()).files[stage_text("design")]

    assert text.index("## Owner assertions") < text.index("## Alternatives")
    assert "\n1. Il pulsante principale resta in alto a destra.\n" in text
    assert "\n2. La tabella dei prestiti mostra sempre la data di scadenza.\n" in text
    assert "Generated mockup: Registro prestiti della Biblioteca" in text
    assert "3 screens written as HTML and CSS for DES-002" in text
    assert "## Owner assertions" in without_mockup
    assert "Generated mockup:" not in without_mockup


def test_the_critiques_show_verdict_and_quote_where_they_show_the_critique() -> None:
    folder = generated_folder(DASHBOARD)
    text = folder.files[DESIGN_CRITIQUES_TEXT]
    table = rows(folder.files[CRITIQUES_TABLE])
    header = folder.files[CRITIQUES_TABLE].splitlines()[0].split(",")
    snapshot = design_snapshot(folder)["package"]["critiques"]
    with_verdict = {item["code"]: item for item in snapshot if "verdict" in item}

    assert header == [*TABLE_COLUMNS[CRITIQUES_TABLE], *CRITIQUE_VERDICT_COLUMNS]
    assert len(with_verdict) == len(VERDICTS)
    for verdict, quote in VERDICTS:
        assert f"Verdict: {verdict}\n\n> {quote}\n" in text
    for row in table:
        expected = with_verdict.get(row["code"], {})
        assert (row["verdict"], row["quote"]) == (
            expected.get("verdict", ""),
            expected.get("quote", ""),
        )
    assert {row["code"] for row in table} == {item["code"] for item in snapshot}
    assert text.count("Verdict: ") == len(VERDICTS)


@pytest.mark.parametrize("name", MOCKUPS)
def test_the_mockup_file_is_the_sandboxed_document_of_the_generated_mockup(name: str) -> None:
    folder = generated_folder(name)
    package = generated_package(name)
    alternative = selected_alternative(package)
    assert package.generated_mockup is not None and alternative.visual_language is not None

    expected = mockup_document(
        package.generated_mockup.mockup,
        tokens=dict(alternative.visual_language.tokens),
        language="it",
    )

    assert folder.files[MOCKUP_FILE] == expected
    assert folder.manifest["project"]["language"] == "it"
    assert 'class="ot-pin"' not in expected


@pytest.mark.parametrize("name", MOCKUPS)
def test_the_mockup_file_opens_offline_with_every_screen_reachable(name: str) -> None:
    document = generated_folder(name).files[MOCKUP_FILE]
    lowered = document.lower()
    screens = sections(document)
    links = {code: set(LINK.findall(body)) for code, (_attributes, body) in screens.items()}

    assert document.startswith('<!doctype html><html lang="it">')
    assert f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">' in (
        document
    )
    assert "default-src 'none'" in CONTENT_SECURITY_POLICY
    for forbidden in ("<script", "<link", "<img", "<iframe", "<object", "<embed", "<base"):
        assert forbidden not in lowered
    for forbidden in ("://", "url(", "@import", "javascript:", " src=", "srcdoc"):
        assert forbidden not in lowered
    assert not [tag for tag in TAG.findall(document) if HANDLER.search(tag)]
    assert lowered.count("</style") == 1
    assert list(screens) == [f"SCR-{index:03d}" for index in range(1, len(screens) + 1)]
    assert [
        code for code, (attributes, _body) in screens.items() if "data-entry" in attributes
    ] == ["SCR-001"]
    assert all(link.startswith("#SCR-") for targets in links.values() for link in targets)
    reached = {"SCR-001"}
    frontier = ["SCR-001"]
    while frontier:
        for link in links[frontier.pop()]:
            target = link.removeprefix("#")
            assert target in screens
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    assert reached == set(screens)
    assert document.count("data-elm=") == derived_elements(name)
    assert ".ot-screen:target{display:block}" in document


def test_a_folder_with_two_hundred_fifty_derived_elements_stays_within_the_archive_limits() -> None:
    folder = generated_folder(LARGE)
    archive = folder_archive(folder)
    verified = read_verified_folder(archive.content)

    assert derived_elements(LARGE) == 250
    assert len(folder.files) < MAX_ARCHIVE_ENTRIES
    assert len(archive.content) < MAX_ARCHIVE_SIZE
    assert max(len(text.encode("utf-8")) for text in folder.files.values()) < MAX_ENTRY_SIZE // 16
    assert verified.content_hash == folder.content_hash
    assert (
        verified.documents["design"]["package"]["generated_mockup"]
        == (design_snapshot(folder)["package"]["generated_mockup"])
    )
    assert folder.files[DESIGN_MOCKUPS_TEXT].count("| ELM-") == 250
