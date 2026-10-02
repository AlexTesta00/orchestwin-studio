from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid5

import pytest

from orchestwin.agents.proposals import TeamProposalRevisionKind
from orchestwin.knowledge.archive import KnowledgeArchiveError, VerifiedFolder, verify_folder
from orchestwin.knowledge.comparison import (
    comparable_documents,
    document_differences,
    entity_labels,
    view_differences,
)
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.project_import import (
    IMPORTED_VERSION_NUMBER,
    defined_identities,
    folder_origin,
    plan_documents,
    plan_project_import,
)
from orchestwin.knowledge.stage_documents import StageDocumentError, stage_versions

from .knowledge_fixtures import (
    PUBLISHED_AT,
    REAL_PROJECT_ID,
    real_documents,
    real_sources,
    sources_of,
)

NEW_PROJECT = UUID("11111111-1111-4111-8111-111111111111")
NEW_BRIEF = UUID("22222222-2222-4222-8222-222222222222")
NEW_OWNER = UUID("33333333-3333-4333-8333-333333333333")
IMPORTED_AT = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
IDENTITY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def verified() -> VerifiedFolder:
    folder = build_knowledge_folder(real_sources(), version_number=3, created_at=PUBLISHED_AT)
    return verify_folder(folder.files)


def plan(folder: VerifiedFolder | None = None, **changes):
    values = {
        "project_id": NEW_PROJECT,
        "brief_version_id": NEW_BRIEF,
        "owner_user_id": NEW_OWNER,
        "created_at": IMPORTED_AT,
    }
    values.update(changes)
    return plan_project_import(verified() if folder is None else folder, **values)


def imported_documents(imported) -> dict[str, dict[str, object]]:
    return plan_documents(imported, owner_user_id=NEW_OWNER, created_at=IMPORTED_AT)


def test_stage_documents_read_back_as_the_approved_versions() -> None:
    documents = real_documents()

    versions = stage_versions(documents)

    assert list(versions) == list(STAGES)
    assert {stage: version.project_id for stage, version in versions.items()} == dict.fromkeys(
        STAGES, REAL_PROJECT_ID
    )
    assert versions["brief"].brief.to_snapshot() == documents["brief"]["brief"]
    assert versions["team"].proposal.to_snapshot() == documents["team"]["proposal"]
    assert versions["twins"].snapshot.to_snapshot() == documents["twins"]["snapshot"]
    assert (
        versions["requirements"].specification.to_snapshot()
        == documents["requirements"]["specification"]
    )
    assert versions["design"].package.to_snapshot() == documents["design"]["package"]
    for stage, version in versions.items():
        assert version.content_hash == documents[stage]["content_hash"]
        assert version.version_number == documents[stage]["version_number"]


@pytest.mark.parametrize("stage", STAGES)
def test_stage_document_with_a_wrong_hash_or_a_missing_field_is_rejected(stage: str) -> None:
    documents = real_documents()
    tampered = {**documents, stage: {**documents[stage], "content_hash": "f" * 64}}
    incomplete = {
        **documents,
        stage: {key: value for key, value in documents[stage].items() if key != "created_at"},
    }

    with pytest.raises(StageDocumentError) as wrong:
        stage_versions(tampered)
    with pytest.raises(StageDocumentError) as missing:
        stage_versions(incomplete)

    assert wrong.value.stage == stage
    assert missing.value.stage == stage


def test_origin_names_the_project_and_the_package_the_folder_came_from() -> None:
    folder = verified()

    origin = folder_origin(folder)

    assert origin.to_snapshot() == {
        "project_id": str(REAL_PROJECT_ID),
        "project_name": "Lista ospiti workshop",
        "package_version": 3,
        "package_content_hash": folder.content_hash,
        "schema_version": 3,
    }
    assert plan(folder).origin == origin


def test_plan_recreates_every_stage_as_version_one_of_the_new_project() -> None:
    imported = plan()

    assert imported.project_id == NEW_PROJECT
    assert imported.project_name == "Lista ospiti workshop"
    assert imported.brief_version_id == NEW_BRIEF
    for version in (imported.team, imported.modeling, imported.requirements, imported.design):
        assert version.project_id == NEW_PROJECT
        assert version.version_number == IMPORTED_VERSION_NUMBER
        assert version.based_on_version_number is None
        assert version.created_by_user_id == NEW_OWNER
        assert version.created_at == IMPORTED_AT
    assert imported.team.revision_kind is TeamProposalRevisionKind.PROPOSER_GENERATED
    for version in (*imported.personas, *imported.twins):
        assert version.project_id == NEW_PROJECT
        assert version.version_number == 1
        assert version.based_on_version_number is None
        assert version.created_by_user_id == NEW_OWNER
    assert len(imported.twins) == len(imported.personas) == 2


def test_references_between_the_stages_point_to_the_new_versions() -> None:
    imported = plan()
    specification = imported.requirements.specification
    grounding = imported.design.package.grounding
    modeling = imported.modeling

    assert imported.team.proposal.to_snapshot()["brief_version"] == {
        "id": str(NEW_BRIEF),
        "version_number": 1,
        "content_hash": imported.brief.content_hash,
    }
    assert modeling.snapshot.project_brief_reference.artifact_id == NEW_BRIEF
    assert modeling.snapshot.agent_team_reference.artifact_id == imported.team.id
    assert modeling.snapshot.agent_team_reference.content_hash == imported.team.content_hash
    assert specification.project_brief_reference.artifact_id == NEW_BRIEF
    assert specification.agent_team_reference.content_hash == imported.team.content_hash
    assert specification.user_modeling_reference.artifact_id == modeling.id
    assert specification.user_modeling_reference.content_hash == modeling.content_hash
    assert {reference.twin_id for reference in specification.user_twin_references} == {
        twin.twin_id for twin in imported.twins
    }
    assert {reference.content_hash for reference in specification.user_twin_references} == {
        twin.content_hash for twin in imported.twins
    }
    assert grounding.requirements_reference.artifact_id == imported.requirements.id
    assert grounding.requirements_reference.version_number == 1
    assert grounding.requirements_reference.content_hash == imported.requirements.content_hash
    assert grounding.user_modeling_reference.content_hash == modeling.content_hash


def test_every_identity_of_the_source_is_replaced_and_external_ones_are_kept() -> None:
    folder = verified()
    imported = plan(folder)
    original = json.dumps(folder.documents)
    rewritten = json.dumps(imported_documents(imported))
    defined = defined_identities(folder.documents)
    external = set(IDENTITY.findall(original)) - defined

    assert set(imported.identities) == defined
    assert imported.identities[str(REAL_PROJECT_ID)] == str(NEW_PROJECT)
    assert imported.identities[folder.documents["brief"]["id"]] == str(NEW_BRIEF)
    assert not [old for old in defined if old in rewritten]
    assert all(new in rewritten for new in imported.identities.values())
    requirement = folder.documents["requirements"]["specification"]["requirements"][0]["id"]
    assert imported.identities[requirement] == str(uuid5(NEW_PROJECT, requirement))
    owner = folder.documents["brief"]["created_by_user_id"]
    assert external - {owner}
    assert all(identity in rewritten for identity in external - {owner})
    assert owner not in rewritten
    assert str(NEW_OWNER) in rewritten


def test_hashes_follow_the_new_content_in_dependency_order() -> None:
    folder = verified()
    imported = plan(folder)
    rewritten = json.dumps(imported_documents(imported))

    assert imported.brief.content_hash == folder.documents["brief"]["content_hash"]
    assert folder.documents["brief"]["content_hash"] not in imported.hashes
    for stage, version in (
        ("team", imported.team),
        ("twins", imported.modeling),
        ("requirements", imported.requirements),
        ("design", imported.design),
    ):
        old = folder.documents[stage]["content_hash"]
        assert imported.hashes[old] == version.content_hash
        assert old not in rewritten
    assert len(imported.hashes) == 4 + len(imported.personas) + len(imported.twins)


def test_plan_is_deterministic_and_changes_with_the_new_project() -> None:
    folder = verified()

    first = plan(folder)
    second = plan(folder)
    elsewhere = plan(folder, project_id=UUID("44444444-4444-4444-8444-444444444444"))

    assert first == second
    assert elsewhere.requirements.id != first.requirements.id
    assert elsewhere.design.content_hash != first.design.content_hash


def test_import_loses_nothing_but_identities_hashes_versions_and_dates() -> None:
    folder = verified()
    imported = plan(folder)
    documents = imported_documents(imported)

    assert document_differences(folder.documents, documents) == []
    assert comparable_documents(folder.documents) == comparable_documents(documents)


def test_folder_exported_again_from_the_imported_project_has_the_same_views() -> None:
    folder = verified()
    versions = stage_versions(imported_documents(plan(folder)))
    again = build_knowledge_folder(
        sources_of(versions, project_id=NEW_PROJECT),
        version_number=1,
        created_at=PUBLISHED_AT,
    )

    assert view_differences(folder.files, again.files) == []
    assert (
        document_differences(
            folder.documents,
            {stage: json.loads(again.files[f"{stage}/{stage}.json"]) for stage in STAGES},
        )
        == []
    )
    assert again.content_hash != folder.content_hash


def test_comparison_notices_a_changed_text_a_lost_item_and_a_changed_view() -> None:
    folder = verified()
    documents = imported_documents(plan(folder))
    reworded = json.loads(json.dumps(documents))
    reworded["requirements"]["specification"]["requirements"][0]["statement"] = "Altro testo"
    shorter = json.loads(json.dumps(documents))
    shorter["design"]["package"]["alternatives"][0]["advantages"].pop()
    views = {**folder.files, "requirements/tables/requirements.csv": "code\nREQ-001\n"}

    changed = document_differences(folder.documents, reworded)
    lost = document_differences(folder.documents, shorter)

    assert len(changed) == 1
    assert changed[0].startswith("folder.requirements.specification.requirements[0].statement: ")
    assert lost == ["folder.design.package.alternatives[0].advantages: 2 items against 1"]
    assert view_differences(folder.files, views) == ["requirements/tables/requirements.csv"]


def test_reading_and_comparing_cover_only_the_stages_that_are_present() -> None:
    documents = {
        stage: document
        for stage, document in real_documents().items()
        if stage in ("brief", "team", "twins")
    }
    changed = json.loads(json.dumps(documents))
    changed["team"]["proposal"]["members"].pop()

    assert list(stage_versions(documents)) == ["brief", "team", "twins"]
    assert list(comparable_documents(documents)) == ["brief", "team", "twins"]
    assert document_differences(documents, documents) == []
    assert document_differences(documents, changed)[0].startswith("folder.team.proposal.members: ")
    assert entity_labels(documents)[str(REAL_PROJECT_ID)] == "project"


def test_labels_name_entities_by_code_and_twins_by_name() -> None:
    documents = real_documents()
    labels = entity_labels(documents)
    design = documents["design"]["package"]
    alternative = design["alternatives"][0]
    twin = documents["twins"]["snapshot"]["twin_versions"][0]

    assert labels[str(REAL_PROJECT_ID)] == "project"
    assert labels[documents["requirements"]["id"]] == "version:requirements"
    assert labels[alternative["id"]] == alternative["code"]
    assert labels[alternative["workflows"][0]["id"]] == (
        f"{alternative['code']}/{alternative['workflows'][0]['code']}"
    )
    assert labels[twin["twin_id"]] == f"twin:{twin['profile']['name']}"
    assert labels[twin["id"]] == f"twin-version:{twin['profile']['name']}"
    assert labels[design["prototype"]["screens"][0]["elements"][0]["id"]].count("/") == 2


def test_plan_needs_a_timezone_aware_time_and_every_stage() -> None:
    folder = verified()
    partial = VerifiedFolder(
        manifest=folder.manifest,
        documents={
            stage: document for stage, document in folder.documents.items() if stage != "design"
        },
        files=folder.files,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        plan(folder, created_at=datetime(2026, 9, 28, 9, 0))
    with pytest.raises(KnowledgeArchiveError) as error:
        plan(partial)

    assert error.value.code == "FOLDER_DOCUMENT_MISSING"


def test_stage_that_the_domain_refuses_stops_the_plan() -> None:
    folder = verified()
    documents = json.loads(json.dumps(folder.documents))
    documents["requirements"]["specification"]["requirements"][0]["code"] = "REQ-999"
    broken = VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)

    with pytest.raises(KnowledgeArchiveError) as error:
        plan(broken)

    assert error.value.code == "FOLDER_DOCUMENT_INVALID"
    assert error.value.detail.startswith("requirements: ")


def test_team_edited_by_the_owner_becomes_the_first_version_of_the_new_project() -> None:
    folder = verified()
    documents = json.loads(json.dumps(folder.documents))
    documents["team"].update(
        revision_kind="OWNER_EDITED", version_number=2, based_on_version_number=1
    )
    edited = VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)

    imported = plan(edited)

    assert imported.team.revision_kind is TeamProposalRevisionKind.PROPOSER_GENERATED
    assert imported.team.version_number == IMPORTED_VERSION_NUMBER
    assert imported.team.based_on_version_number is None
    assert imported.team.content_hash == plan(folder).team.content_hash
    assert document_differences(documents, imported_documents(imported)) == []


def test_stage_that_names_another_project_stops_the_plan() -> None:
    folder = verified()
    documents = json.loads(json.dumps(folder.documents))
    documents["team"]["proposal"]["project_id"] = "99999999-9999-4999-8999-999999999999"
    foreign = VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)

    with pytest.raises(KnowledgeArchiveError) as error:
        plan(foreign)

    assert error.value.code in {"FOLDER_DOCUMENT_INVALID", "FOLDER_INCONSISTENT"}


def test_stage_without_its_content_stops_the_plan() -> None:
    folder = verified()
    documents = json.loads(json.dumps(folder.documents))
    del documents["twins"]["snapshot"]["twin_versions"]
    incomplete = VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)

    with pytest.raises(KnowledgeArchiveError) as error:
        plan(incomplete)

    assert error.value.code == "FOLDER_DOCUMENT_INVALID"


def test_folder_whose_stages_do_not_refer_to_each_other_is_refused() -> None:
    folder = verified()
    documents = json.loads(json.dumps(folder.documents))
    grounding = documents["design"]["package"]["grounding"]
    grounding["requirements_reference"]["artifact_id"] = "99999999-9999-4999-8999-999999999999"
    inconsistent = VerifiedFolder(manifest=folder.manifest, documents=documents, files=folder.files)

    with pytest.raises(KnowledgeArchiveError) as error:
        plan(inconsistent)

    assert (error.value.code, error.value.detail) == ("FOLDER_INCONSISTENT", "DESIGN_OUTDATED")
