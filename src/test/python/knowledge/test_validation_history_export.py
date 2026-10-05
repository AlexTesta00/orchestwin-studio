from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.knowledge.archive import verify_folder
from orchestwin.knowledge.folder import build_knowledge_folder, folder_archive
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.project_import_service import import_record
from orchestwin.knowledge.stage_documents import stage_versions
from orchestwin.knowledge.validation_records import VALIDATION_DOCUMENT, preserve_import_history
from src.test.python.artifacts.design_fixtures import OWNER_ID
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources, sources_of
from src.test.python.knowledge.test_export import FakeQuery, load, loader
from src.test.python.knowledge.test_feedback_import import planned_record


@pytest.mark.parametrize("origin", [None, "learned_only", "omissions"])
def test_loader_reads_import_history_with_owner_scope_and_preserves_legacy_without_omissions(
    origin,
):
    sources = real_sources()
    record = None
    if origin is not None:
        record = planned_record(metadata=origin == "omissions")
        record = replace(record, project_id=sources.project_id, owner_user_id=OWNER_ID)
        if origin == "learned_only":
            record = replace(record, import_limits=("LEARNED_PROJECTION_NOT_RESTORED",))
    query = FakeQuery(record, "origin")
    validation = FakeQuery({"hypotheses": [], "outcomes": []}, "records")
    result = load(
        loader(sources, import_origin_query_service=query, validation_query_service=validation)
    )
    scope = {"owner_user_id": OWNER_ID, "project_id": sources.project_id}
    assert query.calls == validation.calls == [scope]
    exported = build_knowledge_folder(result, version_number=1, created_at=PUBLISHED_AT)
    if origin == "omissions":
        document = json.loads(exported.files[VALIDATION_DOCUMENT])
        assert document["hypotheses"] == document["outcomes"] == []
        assert document["omitted_sections"][0]["historical"] is True
        assert document["omitted_sections"][0]["origin"]["project_id"] == str(
            record.source_project_id
        )
        assert "FEEDBACK_CONTEXT_NOT_RESTORED" in document["limits"]
        assert verify_folder(exported.files).manifest["validation"]["hypotheses"] == 0
    else:
        baseline = build_knowledge_folder(
            load(loader(sources)), version_number=1, created_at=PUBLISHED_AT
        )
        assert exported.files == baseline.files
        assert exported.content_hash == baseline.content_hash
        assert VALIDATION_DOCUMENT not in exported.files


def test_export_and_reimport_preserve_original_omitted_references_without_restoring_history():
    record = planned_record(metadata=True)
    before = deepcopy(record.omitted_sections)
    sources = replace(real_sources(), validation_records=preserve_import_history({}, record))
    folder = build_knowledge_folder(sources, version_number=2, created_at=PUBLISHED_AT)
    document = json.loads(folder.files[VALIDATION_DOCUMENT])
    original = document["omitted_sections"][0]
    assert original["evaluation_run_id"] == record.omitted_sections[0]["evaluation_run_id"]
    assert original["references"] == record.omitted_sections[0]["references"]
    assert record.omitted_sections == before
    owner = uuid4()
    plan = plan_project_import(
        verify_folder(folder.files),
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=PUBLISHED_AT,
    )
    assert plan.evaluations == plan.finding_decisions == ()
    assert plan.validation_records["hypotheses"] == plan.validation_records["outcomes"] == []
    assert plan.omitted_sections[0] == original
    record2 = import_record(
        plan,
        record_id=uuid4(),
        owner_user_id=owner,
        content=folder_archive(folder).content,
        imported_at=PUBLISHED_AT,
    )
    imported_sources = sources_of(
        stage_versions(plan_documents(plan, owner_user_id=owner, created_at=PUBLISHED_AT)),
        project_id=plan.project_id,
        validation_records=preserve_import_history({"hypotheses": [], "outcomes": []}, record2),
    )
    second = build_knowledge_folder(imported_sources, version_number=1, created_at=PUBLISHED_AT)
    second_document = json.loads(second.files[VALIDATION_DOCUMENT])
    assert second_document["omitted_sections"] == document["omitted_sections"]
    assert second_document["limits"] == document["limits"]
    assert verify_folder(second.files).complete is True
