import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.provided_prototypes import (
    provided_prototype_from_payload,
    provided_prototype_from_snapshot,
)
from orchestwin.knowledge.archive import KnowledgeArchiveError, VerifiedFolder, verify_folder
from orchestwin.knowledge.folder import (
    build_knowledge_folder,
    file_digests,
    folder_content_hash,
    json_text,
)
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.why import WHY_DOCUMENT, normalized_why
from orchestwin.knowledge.workflow_inputs import (
    DECISIONS_DOCUMENT,
    PROTOTYPES_DOCUMENT,
    read_workflow_inputs,
)
from orchestwin.why import build_why_document
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_LIMITS,
    create_workflow_decision,
    decision_content_hash,
    workflow_records,
)
from src.test.python.artifacts.test_provided_prototypes36 import input_payload
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from src.test.python.knowledge.test_project_import import (
    IMPORTED_AT,
    NEW_BRIEF,
    NEW_OWNER,
    NEW_PROJECT,
)


def version_reference(version):
    return {
        "artifact_id": str(version.id),
        "version_number": version.version_number,
        "content_hash": version.content_hash,
    }


def workflow_sources(*, history=False, approved=True, resolved=False):
    base = real_sources()
    first = provided_prototype_from_payload(
        input_payload() | {"declared_origin": "Figma desktop"},
        prototype_id=UUID(int=360001),
        code="PRT-001",
        project_id=base.project_id,
        version_number=1,
        based_on_version_number=None,
        definition_reference=version_reference(base.requirements),
        requirement_ids_by_code={
            item.code: item.id for item in base.requirements.specification.requirements
        },
        created_at=PUBLISHED_AT,
    )
    prototypes = [first]
    if history:
        prototypes.append(
            replace(
                first,
                version_number=2,
                based_on_version_number=1,
                declared_origin="Figma updated prototype",
            )
        )
    context = {
        key: version_reference(value)
        for key, value in (
            ("BRIEF", base.brief),
            ("TEAM", base.team),
            ("USER_TWINS", base.modeling),
            ("REQUIREMENTS", base.requirements),
        )
    }
    first_decision = create_workflow_decision(
        decision_id=UUID(int=360010),
        project_id=base.project_id,
        sequence=1,
        target="EVIDENCE",
        action="DECLARE_MISSING",
        reason="No empirical interviews are available.",
        base_context=context,
        recorded_at=PUBLISHED_AT,
    )
    decisions = [first_decision]
    if resolved:
        decisions.append(
            create_workflow_decision(
                decision_id=UUID(int=360011),
                project_id=base.project_id,
                sequence=2,
                target="EVIDENCE",
                action="RESOLVE_MISSING",
                reason="Owner corrected the declaration; no empirical source is added by this action.",
                base_context=context | {"DESIGN": version_reference(first)},
                recorded_at=PUBLISHED_AT,
            )
        )
    current = prototypes[-1].to_snapshot()
    return replace(
        base,
        design=None,
        design_gate=None,
        workflow_inputs=workflow_records(
            base.project_id, decisions, [item.to_snapshot() for item in prototypes]
        ),
        provided_design={
            "source": "PROVIDED_PROTOTYPE",
            "approved": approved,
            "prototype": current,
        },
    )


def exported(**options):
    return build_knowledge_folder(
        workflow_sources(**options), version_number=1, created_at=PUBLISHED_AT
    )


def imported(folder):
    return plan_project_import(
        verify_folder(folder.files),
        project_id=NEW_PROJECT,
        brief_version_id=NEW_BRIEF,
        owner_user_id=NEW_OWNER,
        created_at=IMPORTED_AT,
    )


def changed_package(folder, *, change):
    files = deepcopy(folder.files)
    manifest = deepcopy(folder.manifest)
    change(files, manifest)
    manifest["files"] = file_digests(
        {
            path: text
            for path, text in files.items()
            if path not in {"orchestwin.json", "ORCHESTWIN.md"}
        }
    )
    manifest["package"]["content_hash"] = folder_content_hash(files)
    files["orchestwin.json"] = json_text(manifest)
    return files


def test_supplied_design_dossier_exports_both_records_and_truthful_partial_progress():
    folder = exported()
    assert DECISIONS_DOCUMENT in folder.files and PROTOTYPES_DOCUMENT in folder.files
    entry = folder.manifest["workflow_inputs"]
    assert entry["limits"] == list(PROVIDED_PROTOTYPE_LIMITS)
    payload = json.loads(folder.files[PROTOTYPES_DOCUMENT])
    item = payload["prototypes"][0]
    assert item["declared_origin"] == "Figma desktop"
    assert payload["approved_prototype"] == entry["approved_prototype"]
    assert item["mockup"]["mockup"]["screens"] == input_payload()["mockup"]["screens"]
    verified = verify_folder(folder.files)
    assert verified.present_stages == ("brief", "team", "twins", "requirements")
    assert not verified.complete and verified.pending_stage == "design"
    assert "design/design.json" not in folder.files
    assert read_workflow_inputs(verified)["prototypes"] == [item]


def test_absent_and_empty_workflow_metadata_keep_legacy_files_schemas_and_hash_exact():
    sources = real_sources()
    legacy = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    empty = build_knowledge_folder(
        replace(sources, workflow_inputs=workflow_records(sources.project_id)),
        version_number=1,
        created_at=PUBLISHED_AT,
    )
    assert empty.files == legacy.files and empty.content_hash == legacy.content_hash
    assert "workflow_inputs" not in legacy.manifest
    assert DECISIONS_DOCUMENT not in legacy.files and PROTOTYPES_DOCUMENT not in legacy.files
    assert (
        "workflow_inputs"
        not in json.loads(legacy.files["schema/manifest.schema.json"])["properties"]
    )
    assert (
        "workflow_records" not in json.loads(legacy.files["schema/why.schema.json"])["properties"]
    )
    assert read_workflow_inputs(verify_folder(legacy.files))["prototypes"] == []


def test_four_approved_stages_and_exact_prototype_are_importable_without_forging_design():
    folder = exported()
    plan = imported(folder)
    assert plan.design is None
    assert set(plan_documents(plan, owner_user_id=NEW_OWNER, created_at=IMPORTED_AT)) == {
        "brief",
        "team",
        "twins",
        "requirements",
    }
    assert "OWNER_WORKFLOW_APPROVALS_NOT_RESTORED" in plan.import_limits
    original = read_workflow_inputs(verify_folder(folder.files))
    mapped = plan.workflow_inputs["prototypes"][0]
    assert mapped["id"] == plan.identities[original["prototypes"][0]["id"]]
    assert mapped["definition_reference"] == version_reference(plan.requirements)
    assert mapped["declared_origin"] == "Figma desktop"
    assert mapped["original_reference"]["content_hash"] == original["prototypes"][0]["content_hash"]
    assert mapped["content_hash"] != mapped["original_reference"]["content_hash"]
    assert provided_prototype_from_snapshot(mapped).to_snapshot() == mapped
    assert not any(key.startswith("gate") or "approval" in key for key in mapped)


def test_unapproved_supplied_design_does_not_make_a_partial_folder_importable():
    with pytest.raises(KnowledgeArchiveError) as caught:
        imported(exported(approved=False))
    assert caught.value.code == "FOLDER_INCOMPLETE"


def test_import_keeps_history_origin_hashes_and_rebinds_each_design_context_to_its_real_version():
    folder = exported(history=True, resolved=True)
    plan = imported(folder)
    old = read_workflow_inputs(verify_folder(folder.files))
    records = plan.workflow_inputs
    assert [item["version_number"] for item in records["prototypes"]] == [1, 2]
    assert [item["based_on_version_number"] for item in records["prototypes"]] == [None, 1]
    for before, after in zip(old["prototypes"], records["prototypes"], strict=True):
        assert after["original_reference"]["content_hash"] == before["content_hash"]
        assert after["original_reference"]["version_number"] == before["version_number"]
        assert after["id"] == plan.identities[before["id"]]
        assert after["content_hash"] == plan.hashes[before["content_hash"]]
    context = records["decisions"][1]["base_context"]["DESIGN"]
    assert context == version_reference(provided_prototype_from_snapshot(records["prototypes"][0]))
    for before, after in zip(old["decisions"], records["decisions"], strict=True):
        assert after["sequence"] == before["sequence"]
        assert after["origin_reference"]["content_hash"] == before["content_hash"]
        assert after["content_hash"] == decision_content_hash(after)
    derived = build_why_document(
        project_id=str(plan.project_id),
        stages=plan_documents(plan, owner_user_id=NEW_OWNER, created_at=IMPORTED_AT),
        workflow_inputs=records,
    )
    expected = json.loads(folder.files[WHY_DOCUMENT])
    assert normalized_why(
        expected, identities=plan.identities, hashes=plan.hashes
    ) == normalized_why(derived)


@pytest.mark.parametrize(
    "case", ("record_hash", "approval_hash", "definition", "unsafe", "manifest_schema")
)
def test_dossier_rejects_record_and_approval_tampering_even_with_new_file_digests(case):
    folder = exported()

    def tamper(files, manifest):
        payload = json.loads(files[PROTOTYPES_DOCUMENT])
        item = payload["prototypes"][0]
        if case == "record_hash":
            item["content_hash"] = "f" * 64
        elif case == "approval_hash":
            payload["approved_prototype"]["content_hash"] = "f" * 64
            manifest["workflow_inputs"]["approved_prototype"] = payload["approved_prototype"]
        elif case == "definition":
            item["definition_reference"]["content_hash"] = "f" * 64
            item["content_hash"] = decision_content_hash(item)
            payload["approved_prototype"]["content_hash"] = item["content_hash"]
            manifest["workflow_inputs"]["approved_prototype"] = payload["approved_prototype"]
        elif case == "unsafe":
            item["mockup"]["mockup"]["screens"][0]["markup"] += "<script>fetch('/private')</script>"
            item["content_hash"] = decision_content_hash(item)
        else:
            manifest["workflow_inputs"]["schema_version"] = True
        files[PROTOTYPES_DOCUMENT] = json_text(payload)

    changed = changed_package(folder, change=tamper)
    with pytest.raises(KnowledgeArchiveError, match="FOLDER_DOCUMENT_INVALID"):
        read_workflow_inputs(
            VerifiedFolder(
                manifest=json.loads(changed["orchestwin.json"]), documents={}, files=changed
            )
        )
    with pytest.raises(KnowledgeArchiveError):
        verify_folder(changed)


def test_workflow_reader_rejects_undeclared_files_and_missing_pair():
    folder = exported()
    manifest = deepcopy(folder.manifest)
    manifest.pop("workflow_inputs")
    with pytest.raises(KnowledgeArchiveError, match="FOLDER_TAMPERED"):
        read_workflow_inputs(VerifiedFolder(manifest=manifest, documents={}, files=folder.files))
    files = dict(folder.files)
    files.pop(PROTOTYPES_DOCUMENT)
    with pytest.raises(KnowledgeArchiveError, match="FOLDER_DOCUMENT_INVALID"):
        read_workflow_inputs(VerifiedFolder(manifest=folder.manifest, documents={}, files=files))
