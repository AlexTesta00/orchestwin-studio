from __future__ import annotations

import csv
import hashlib
import io
import json
from copy import deepcopy
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.knowledge.archive import verify_folder
from orchestwin.knowledge.comparison import document_differences, view_differences
from orchestwin.knowledge.diagrams import requirements_traceability_diagram
from orchestwin.knowledge.documents import requirements_markdown
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.layout import table_document
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.schema import KnowledgeSchemaError, knowledge_schemas, validate_document
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.tables import requirements_tables
from orchestwin.projects.requirements_persistence import specification_from_snapshot

from .knowledge_fixtures import (
    OWNER_ID,
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    real_documents,
    real_sources,
    schema_two_files,
    sources_of,
)

NEED_ID = "00000000-0000-4000-8000-000000009201"
NEW_PROJECT = UUID("11111111-1111-4111-8111-111111119201")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222229201")


def definition_documents(schema_version: int = 2):
    documents = real_documents()
    if schema_version == 1:
        return documents
    specification = documents["requirements"]["specification"]
    actors = {item["actor"]["twin_id"] for item in specification["scenarios"]}
    for index, twin in enumerate(specification["user_twin_references"], 1):
        if twin["twin_id"] not in actors:
            scenario = deepcopy(specification["scenarios"][0])
            scenario.update(
                id=str(UUID(int=9202 + index)),
                code=f"SCN-{len(specification['scenarios']) + 1:03d}",
                actor=twin,
                title=f"Accoglienza per {twin['name']}",
            )
            specification["scenarios"].append(scenario)
    source = deepcopy(specification["requirements"][0]["sources"][0])
    external = {
        "kind": "SYSTEM_ARTIFACT",
        "source_id": "https://example.org/owner-material",
        "source_version": 7,
        "content_hash": documents["twins"]["content_hash"],
        "locator": f"historical:{specification['scenarios'][0]['actor']['twin_id']}",
    }
    specification["schema_version"] = 2
    specification["needs"] = [
        {
            "id": NEED_ID,
            "code": "NED-001",
            "title": "Accogliere senza perdere la lista",
            "statement": "Tenere riconoscibili gli ospiti durante l'accoglienza.",
            "scenario_ids": sorted(
                (item["id"] for item in specification["scenarios"]),
                key=lambda value: UUID(value).hex,
            ),
            "sources": [source, external],
        }
    ]
    for scenario in specification["scenarios"]:
        scenario.update(
            context="Durante l'accoglienza al workshop.",
            goal="Riconoscere l'ospite e ritrovarlo nella lista.",
            criticalities=["Un nome può essere condiviso da più ospiti."],
            sources=[source, external],
        )
    for item in (*specification["requirements"], *specification["user_stories"]):
        item["need_ids"] = [NEED_ID]
    bound = specification_from_snapshot(specification)
    previous = documents["requirements"]["content_hash"]
    documents["requirements"]["specification"] = bound.to_snapshot()
    documents["requirements"]["content_hash"] = bound.content_hash
    design = json.loads(json.dumps(documents["design"]).replace(previous, bound.content_hash))
    package = design_package_from_snapshot(design["package"])
    design["content_hash"] = package.content_hash
    documents["design"] = design
    return documents


def definition_folder(schema_version: int = 2):
    sources = sources_of(
        stage_versions(definition_documents(schema_version)), project_id=REAL_PROJECT_ID
    )
    return build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)


def test_historical_definition_keeps_its_snapshot_and_content_hash() -> None:
    document = real_documents()["requirements"]
    bound = specification_from_snapshot(document["specification"])
    assert bound.schema_version == 1
    assert bound.to_snapshot() == document["specification"]
    assert bound.content_hash == "d5627be28efc71464c9e8c27787e2251e387a6b7f63f4f5bfe01197862e18c2a"
    assert table_document("requirements", "needs") not in requirements_tables(bound.to_snapshot())
    sources = real_sources()
    text = requirements_markdown(sources.requirements, sources.requirements_gate)
    assert (
        hashlib.sha256(text.encode()).hexdigest()
        == "4d10f9e3ee0699e398127dc04399aedd786c0a4e8dd3a203337120be8f00c5c7"
    )


@pytest.mark.parametrize("folder_version", [2, 3])
@pytest.mark.parametrize("definition_version", [1, 2])
def test_both_folder_formats_import_both_definition_versions_without_losing_the_chain(
    folder_version: int, definition_version: int
) -> None:
    folder = definition_folder(definition_version)
    files = schema_two_files(folder.files) if folder_version == 2 else folder.files
    verified = verify_folder(files)
    imported = plan_project_import(
        verified,
        project_id=NEW_PROJECT,
        brief_version_id=NEW_BRIEF,
        owner_user_id=OWNER_ID,
        created_at=PUBLISHED_AT,
    )
    after = plan_documents(imported, owner_user_id=OWNER_ID, created_at=PUBLISHED_AT)
    assert imported.origin.schema_version == folder_version
    assert imported.requirements.specification.schema_version == definition_version
    assert document_differences(verified.documents, after) == []
    again = build_knowledge_folder(
        sources_of(stage_versions(after), project_id=NEW_PROJECT),
        version_number=1,
        created_at=PUBLISHED_AT,
    )
    assert view_differences(folder.files, again.files) == []
    assert (
        verify_folder(again.files).documents["requirements"]["content_hash"]
        == imported.requirements.content_hash
    )
    if definition_version == 2:
        before = verified.documents["requirements"]["specification"]
        rewritten = after["requirements"]["specification"]
        need = rewritten["needs"][0]
        assert need["id"] == imported.identities[NEED_ID]
        assert need["scenario_ids"] == sorted(
            (imported.identities[item] for item in before["needs"][0]["scenario_ids"]),
            key=lambda value: UUID(value).hex,
        )
        assert all(
            item["need_ids"] == [need["id"]]
            for item in (*rewritten["requirements"], *rewritten["user_stories"])
        )
        external_before = next(
            source
            for source in before["needs"][0]["sources"]
            if source["kind"] == "SYSTEM_ARTIFACT"
        )
        external_after = next(
            source for source in need["sources"] if source["kind"] == "SYSTEM_ARTIFACT"
        )
        assert external_after == external_before
        assert rewritten["scenarios"][0]["sources"] == need["sources"]


def test_needs_table_and_diagram_follow_the_actual_links() -> None:
    specification = definition_documents()["requirements"]["specification"]
    tables = requirements_tables(specification)
    needs = list(csv.DictReader(io.StringIO(tables[table_document("requirements", "needs")])))
    assert len(needs) == 1
    assert needs[0]["code"] == "NED-001"
    assert needs[0]["scenario_ids"] == "; ".join(
        item["code"] for item in specification["scenarios"]
    )
    assert "https://example.org/owner-material" in needs[0]["sources"]
    for name in ("requirements", "user-stories"):
        assert all(
            row["need_ids"] == "NED-001"
            for row in csv.DictReader(io.StringIO(tables[table_document("requirements", name)]))
        )
    graph = requirements_traceability_diagram(specification).source
    assert 'NED001["NED-001' in graph
    assert '|"participates in"|' in graph
    assert '|"reveals"| NED001' in graph
    assert 'NED001 -->|"motivates"| REQ001' in graph
    assert 'NED001 -->|"motivates"| USR001' in graph


@pytest.mark.parametrize(
    "language,words",
    [
        (
            "it",
            ("Definizione", "Scenari", "Bisogni", "Storie", "Requisiti funzionali", "Criticità"),
        ),
        (
            "en",
            (
                "Definition",
                "Scenarios",
                "Needs",
                "User stories",
                "Functional requirements",
                "Potential difficulties",
            ),
        ),
    ],
)
def test_definition_text_is_localized_and_keeps_details_and_navigation(
    language: str, words: tuple[str, ...]
) -> None:
    documents = definition_documents()
    sources = sources_of(stage_versions(documents), project_id=REAL_PROJECT_ID)
    text = requirements_markdown(sources.requirements, sources.requirements_gate, locale=language)
    specification = documents["requirements"]["specification"]
    assert all(word in text for word in words)
    assert (
        text.index(f"## {words[1]}")
        < text.index(f"## {words[2]}")
        < text.index(f"## {words[3]}")
        < text.index(f"## {words[4]}")
    )
    assert "](\u0023ned-001)" in text
    for scenario in specification["scenarios"]:
        assert scenario["context"] in text
        assert scenario["goal"] in text
        assert scenario["criticalities"][0] in text
    for risk in specification["risks"]:
        assert (
            risk["likelihood"] in text and risk["impact"] in text and risk["review_status"] in text
        )
    for item in specification["definition_of_done"]:
        assert item["applicability"] in text
    for criterion in specification["acceptance_criteria"]:
        assert criterion["verification_method"] in text
        assert all(
            f"](#{next(story['code'].lower() for story in specification['user_stories'] if story['id'] == identifier)})"
            in text
            for identifier in criterion["user_story_ids"]
        )


def test_published_schema_distinguishes_legacy_and_enriched_definitions() -> None:
    schema = knowledge_schemas()["requirements"]
    validator = Draft202012Validator(schema)
    assert "RequirementsSpecificationSnapshot2" in schema["$defs"]
    for version in (1, 2):
        document = definition_documents(version)["requirements"]
        validate_document("requirements", document)
        assert validator.is_valid(document)
    invalid = definition_documents()["requirements"]
    invalid["specification"]["schema_version"] = 1
    assert not validator.is_valid(invalid)
    with pytest.raises(KnowledgeSchemaError):
        validate_document("requirements", invalid)
