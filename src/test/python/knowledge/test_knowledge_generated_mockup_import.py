from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.knowledge.archive import (
    MOCKUP_LOCATION,
    KnowledgeArchiveError,
    VerifiedFolder,
    verify_folder,
)
from orchestwin.knowledge.comparison import (
    comparable_documents,
    document_differences,
    entity_labels,
    view_differences,
)
from orchestwin.knowledge.folder import (
    DESIGN_CRITIQUES_TEXT,
    DESIGN_MOCKUPS_TEXT,
    KnowledgeFolder,
    build_knowledge_folder,
)
from orchestwin.knowledge.layout import STAGES, schema_document, stage_document
from orchestwin.knowledge.project_import import (
    ProjectImportPlan,
    defined_identities,
    plan_documents,
    plan_project_import,
)
from orchestwin.knowledge.project_import_service import ProjectImportError, ProjectImportService
from orchestwin.knowledge.stage_documents import stage_versions

from .knowledge_fixtures import PUBLISHED_AT, sources_of
from .test_knowledge_generated_mockup_support import (
    DASHBOARD,
    GUIDED_FORM,
    MOCKUPS,
    archive_of,
    design_snapshot,
    generated_folder,
    repacked,
)

NEW_PROJECT = UUID("11111111-1111-4111-8111-111111111111")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222222222")
NEW_OWNER = UUID("33333333-3333-4333-8333-333333333333")
OTHER_PROJECT = UUID("44444444-4444-4444-8444-444444444444")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
IDENTITY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MOCKUP_FILE = "design/mockup.html"
SAME_VIEWS = (
    MOCKUP_FILE,
    DESIGN_MOCKUPS_TEXT,
    DESIGN_CRITIQUES_TEXT,
    "design/tables/critiques.csv",
    schema_document("design"),
)


def plan(folder: VerifiedFolder, project_id: UUID = NEW_PROJECT) -> ProjectImportPlan:
    return plan_project_import(
        folder,
        project_id=project_id,
        brief_version_id=NEW_BRIEF,
        owner_user_id=NEW_OWNER,
        created_at=IMPORTED_AT,
    )


def imported_documents(imported: ProjectImportPlan) -> dict[str, dict[str, object]]:
    return plan_documents(imported, owner_user_id=NEW_OWNER, created_at=IMPORTED_AT)


def exported_again(imported: ProjectImportPlan) -> KnowledgeFolder:
    versions = stage_versions(imported_documents(imported))
    return build_knowledge_folder(
        sources_of(versions, project_id=imported.project_id),
        version_number=1,
        created_at=PUBLISHED_AT,
    )


def edited(change: Callable[[dict[str, object]], None], name: str = DASHBOARD) -> dict[str, str]:
    folder = generated_folder(name)
    design = design_snapshot(folder)
    change(design["package"])
    return repacked(folder, design)


def first_screen(package: dict[str, object]) -> dict[str, str]:
    return package["generated_mockup"]["mockup"]["screens"][0]


def appended(snippet: str) -> Callable[[dict[str, object]], None]:
    def change(package: dict[str, object]) -> None:
        screen = first_screen(package)
        screen["markup"] = screen["markup"] + snippet

    return change


def styled(rule: str) -> Callable[[dict[str, object]], None]:
    def change(package: dict[str, object]) -> None:
        mockup = package["generated_mockup"]["mockup"]
        mockup["styles"] = mockup["styles"] + rule

    return change


def mapped(update: Callable[[dict[str, str]], None]) -> Callable[[dict[str, object]], None]:
    def change(package: dict[str, object]) -> None:
        update(package["generated_mockup"]["requirement_ids_by_code"])

    return change


def requirement_id(code: str) -> str:
    requirements = json.loads(generated_folder(DASHBOARD).files[stage_document("requirements")])
    return next(
        item["id"] for item in requirements["specification"]["requirements"] if item["code"] == code
    )


def without(code: str) -> Callable[[dict[str, str]], None]:
    return lambda mapping: mapping.pop(code)


def plus(code: str) -> Callable[[dict[str, str]], None]:
    def update(mapping: dict[str, str]) -> None:
        mapping[code] = requirement_id(code)

    return update


def shared(first: str, second: str) -> Callable[[dict[str, str]], None]:
    def update(mapping: dict[str, str]) -> None:
        mapping[second] = mapping[first]

    return update


def refusal(files: dict[str, str]) -> KnowledgeArchiveError:
    with pytest.raises(KnowledgeArchiveError) as caught:
        verify_folder(files)
    return caught.value


@pytest.mark.parametrize("name", MOCKUPS)
def test_a_folder_with_a_generated_mockup_passes_verification(name: str) -> None:
    folder = generated_folder(name)

    verified = verify_folder(folder.files)

    assert verified.content_hash == folder.content_hash
    assert verified.documents["design"] == design_snapshot(folder)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (appended("<script>alert(1)</script>"), "ELEMENT_FORBIDDEN"),
        (appended("<SCRIPT>alert(1)</SCRIPT>"), "ELEMENT_FORBIDDEN"),
        (appended('<p onclick="alert(1)">Apri il registro</p>'), "ATTRIBUTE_FORBIDDEN"),
        (appended('<a href="https://example.invalid/x">Esci</a>'), "LINK_TARGET"),
        (appended("<marquee>Prestiti</marquee>"), "ELEMENT_FORBIDDEN"),
        (appended('<img src="https://example.invalid/x.png">'), "ELEMENT_FORBIDDEN"),
        (styled(".kpi{background:url(https://example.invalid/x.png)}"), "STYLES_FORBIDDEN"),
        (styled(".kpi{background:url( 'https://example.invalid/x.png' )}"), "STYLES_FORBIDDEN"),
        (styled("@import 'https://example.invalid/x.css';"), "STYLES_FORBIDDEN"),
        (mapped(without("REQ-001")), "REQUIREMENT_CODE_UNMAPPED"),
        (mapped(plus("REQ-007")), "REQUIREMENT_CODE_UNUSED"),
        (mapped(shared("REQ-001", "REQ-002")), "REQUIREMENT_ID_DUPLICATED"),
    ],
)
def test_a_folder_whose_mockup_breaks_a_rule_is_refused_and_names_the_design_document(
    change: Callable[[dict[str, object]], None], rule: str
) -> None:
    refused = refusal(edited(change))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: {rule}",
    )
    assert refused.detail.startswith("design: ")


def test_a_prototype_that_is_not_derived_from_the_mockup_is_refused() -> None:
    def reworded(package: dict[str, object]) -> None:
        element = package["prototype"]["screens"][0]["elements"][0]
        element["content"] = "Un altro testo"

    def dropped(package: dict[str, object]) -> None:
        package["prototype"]["transitions"].pop()

    for change in (reworded, dropped):
        refused = refusal(edited(change))
        assert (refused.code, refused.detail) == (
            "FOLDER_DOCUMENT_INVALID",
            f"{MOCKUP_LOCATION}: PROTOTYPE_NOT_DERIVED",
        )


def test_a_mockup_that_does_not_belong_to_the_selected_alternative_is_refused() -> None:
    def elsewhere(package: dict[str, object]) -> None:
        other = next(
            item["id"]
            for item in package["alternatives"]
            if item["id"] != package["owner_selected_alternative_id"]
        )
        package["generated_mockup"]["mockup"]["design_alternative_id"] = other

    def without_tokens(package: dict[str, object]) -> None:
        for item in package["alternatives"]:
            if item["id"] == package["owner_selected_alternative_id"]:
                del item["visual_language"]

    for change in (elsewhere, without_tokens):
        refused = refusal(edited(change))
        assert (refused.code, refused.detail) == (
            "FOLDER_DOCUMENT_INVALID",
            f"{MOCKUP_LOCATION}: SELECTED_ALTERNATIVE",
        )


def test_a_mockup_written_with_an_unknown_token_is_refused() -> None:
    refused = refusal(edited(styled(".kpi{color:var(--vl-color-unknown)}")))

    assert (refused.code, refused.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: STYLES_CUSTOM_PROPERTY",
    )


def test_a_refused_mockup_never_reaches_the_database() -> None:
    opened: list[bool] = []

    def session_factory():
        opened.append(True)
        raise AssertionError("the import must not reach the database")

    service = ProjectImportService(session_factory=session_factory, clock=lambda: IMPORTED_AT)
    content = archive_of(edited(appended("<script>alert(1)</script>")))

    with pytest.raises(ProjectImportError) as caught:
        asyncio.run(service.import_archive(owner_user_id=NEW_OWNER, content=content))

    assert (caught.value.code, caught.value.detail) == (
        "FOLDER_DOCUMENT_INVALID",
        f"{MOCKUP_LOCATION}: ELEMENT_FORBIDDEN",
    )
    assert opened == []


@pytest.mark.parametrize("name", MOCKUPS)
def test_import_rewrites_the_mockup_and_derives_its_prototype_again(name: str) -> None:
    folder = verify_folder(generated_folder(name).files)

    imported = plan(folder)
    package = imported.design.package
    bound = package.generated_mockup
    specification = imported.requirements.specification
    documents = imported_documents(imported)
    rewritten = json.dumps(documents)
    original = folder.documents["design"]["package"]
    defined = defined_identities(folder.documents)

    assert bound is not None and package.prototype is not None
    assert bound.design_alternative_id == package.owner_selected_alternative_id
    assert (
        str(bound.design_alternative_id)
        == imported.identities[original["owner_selected_alternative_id"]]
    )
    assert dict(bound.requirement_ids_by_code) == {
        item.code: item.id
        for item in specification.requirements
        if item.code in bound.requirement_codes
    }
    assert package.prototype == bound.prototype()
    assert (
        package.to_snapshot()["prototype"]["id"] == imported.identities[original["prototype"]["id"]]
    )
    assert set(imported.identities) == defined
    assert not [old for old in defined if old in rewritten]
    assert all(new in rewritten for new in imported.identities.values())
    assert design_package_from_snapshot(documents["design"]["package"]) == package
    assert plan(folder) == imported
    assert plan(folder, OTHER_PROJECT).design.content_hash != imported.design.content_hash


@pytest.mark.parametrize("name", MOCKUPS)
def test_every_derived_identifier_follows_its_code_through_the_import(name: str) -> None:
    folder = verify_folder(generated_folder(name).files)
    imported = plan(folder)
    before = folder.documents["design"]["package"]["prototype"]
    after = imported.design.package.to_snapshot()["prototype"]

    pairs = [
        (screen_before["id"], screen_after["id"])
        for screen_before, screen_after in zip(before["screens"], after["screens"], strict=True)
    ]
    pairs.extend(
        (element_before["id"], element_after["id"])
        for screen_before, screen_after in zip(before["screens"], after["screens"], strict=True)
        for element_before, element_after in zip(
            screen_before["elements"], screen_after["elements"], strict=True
        )
    )
    pairs.extend(
        (transition_before["id"], transition_after["id"])
        for transition_before, transition_after in zip(
            before["transitions"], after["transitions"], strict=True
        )
    )

    assert all(imported.identities[old] == new for old, new in pairs)
    assert len({new for _old, new in pairs}) == len(pairs)


@pytest.mark.parametrize("name", MOCKUPS)
def test_round_trip_of_a_folder_with_the_additions_loses_nothing(name: str) -> None:
    exported = generated_folder(name)
    source = verify_folder(exported.files)

    again = exported_again(plan(source))
    target = verify_folder(again.files)

    assert document_differences(source.documents, target.documents) == []
    assert comparable_documents(source.documents) == comparable_documents(target.documents)
    assert view_differences(source.files, again.files) == []
    for path in SAME_VIEWS:
        assert again.files[path] == exported.files[path], path
    assert len(again.files) == len(exported.files)
    assert again.content_hash != exported.content_hash
    assert (
        target.documents["design"]["package"]["owner_assertions"]
        == (source.documents["design"]["package"]["owner_assertions"])
    )


def test_the_comparison_names_the_derived_prototype_by_its_codes() -> None:
    folder = verify_folder(generated_folder(GUIDED_FORM).files)
    labels = entity_labels(folder.documents)
    package = folder.documents["design"]["package"]
    prototype = package["prototype"]
    screen = prototype["screens"][1]
    mapping = package["generated_mockup"]["requirement_ids_by_code"]

    assert labels[prototype["id"]] == "PRT-001"
    assert labels[screen["id"]] == f"PRT-001/{screen['code']}"
    assert labels[screen["elements"][0]["id"]] == (
        f"PRT-001/{screen['code']}/{screen['elements'][0]['code']}"
    )
    assert labels[prototype["transitions"][-1]["id"]] == (
        f"PRT-001/{prototype['transitions'][-1]['code']}"
    )
    assert all(labels[identifier] == code for code, identifier in mapping.items())
    assert labels[package["generated_mockup"]["mockup"]["design_alternative_id"]].startswith("DES-")
    comparable = comparable_documents(folder.documents)["design"]["package"]
    for key in ("prototype", "generated_mockup"):
        assert not IDENTITY.search(json.dumps(comparable[key])), key


def test_every_stage_of_the_imported_folder_keeps_its_place() -> None:
    folder = verify_folder(generated_folder(DASHBOARD).files)

    documents = imported_documents(plan(folder))

    assert list(documents) == list(STAGES)
    assert set(documents["design"]["package"]) == set(folder.documents["design"]["package"])
