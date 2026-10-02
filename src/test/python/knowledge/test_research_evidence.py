from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.knowledge.archive import KnowledgeArchiveError, verify_folder
from orchestwin.knowledge.folder import build_knowledge_folder
from orchestwin.knowledge.project_import import _Rewriter, plan_project_import
from orchestwin.knowledge.research_evidence import EVIDENCE_DOCUMENT, EVIDENCE_TEXT
from orchestwin.knowledge.schema import KnowledgeSchemaError, validate_document
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import HumanGateType

from .knowledge_fixtures import PUBLISHED_AT, approved_gate, real_sources
from .test_export import FakeQuery, load, loader

SOURCE_ID = "d3333333-3333-4333-8333-333333333333"
NEW_PROJECT = UUID("e1111111-1111-4111-8111-111111111111")
NEW_OWNER = UUID("e2222222-2222-4222-8222-222222222222")
NEW_BRIEF = UUID("e3333333-3333-4333-8333-333333333333")


def evidence_document(sources=None):
    sources = sources or real_sources()
    twin = sources.modeling.snapshot.twin_versions[0]
    quote = f"Synthetic literal {twin.twin_id}\n{twin.content_hash}"
    original = f"Unexported synthetic preface.\n{quote}\nUnexported synthetic ending."
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    start = original.index(quote)
    return {
        "kind": "orchestwin.research-evidence",
        "schema_version": 1,
        "project_id": str(sources.project_id),
        "evidence": [
            {
                "id": SOURCE_ID,
                "code": "EVD-001",
                "version": 2,
                "title": "Synthetic source",
                "source_kind": "OWNER_INPUT",
                "source_ref": "synthetic-test",
                "context": "Nonempirical test",
                "method": "Synthetic fixture",
                "collected_at": None,
                "limitations": "No real participants or human validation",
                "empirical": False,
                "content_hash": digest,
                "character_count": len(original),
                "byte_count": len(original.encode("utf-8")),
                "created_at": PUBLISHED_AT.isoformat(),
                "status": "ACTIVE",
                "retired_at": None,
                "retired_reason": None,
                "text_available": True,
            }
        ],
        "citations": [
            {
                "twin_id": str(twin.twin_id),
                "twin_version": twin.version_number,
                "field": "goals",
                "effect": "SUPPORTS",
                "status": "ACTIVE",
                "citation": {
                    "source_id": SOURCE_ID,
                    "source_version": 2,
                    "content_hash": digest,
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                    "start_line": 2,
                    "end_line": 3,
                },
            }
        ],
    }


def test_legacy_files_and_hashes_are_identical_without_evidence():
    sources = real_sources()
    first = build_knowledge_folder(sources, version_number=3, created_at=PUBLISHED_AT)
    second = build_knowledge_folder(
        replace(sources, research_evidence={"evidence": [], "citations": []}),
        version_number=3,
        created_at=PUBLISHED_AT,
    )
    assert first.files == second.files
    assert first.content_hash == second.content_hash
    assert EVIDENCE_DOCUMENT not in first.files
    assert "schema/evidence.schema.json" not in first.files


def test_folder_exports_exact_excerpts_and_provenance_without_original_body():
    sources = real_sources()
    document = evidence_document(sources)
    folder = build_knowledge_folder(
        replace(sources, research_evidence=document), version_number=3, created_at=PUBLISHED_AT
    )
    assert json.loads(folder.files[EVIDENCE_DOCUMENT]) == document
    assert "Unexported synthetic preface" not in "".join(folder.files.values())
    assert "Unexported synthetic ending" not in "".join(folder.files.values())
    assert (
        "senza documenti originali" in folder.files[EVIDENCE_TEXT]
        or "without original" in folder.files[EVIDENCE_TEXT]
    )
    assert verify_folder(folder.files).project_id == str(sources.project_id)


def test_import_remaps_source_links_but_preserves_quote_and_source_version_hash():
    sources = real_sources()
    document = evidence_document(sources)
    folder = build_knowledge_folder(
        replace(sources, research_evidence=document), version_number=3, created_at=PUBLISHED_AT
    )
    plan = plan_project_import(
        verify_folder(folder.files),
        project_id=NEW_PROJECT,
        brief_version_id=NEW_BRIEF,
        owner_user_id=NEW_OWNER,
        created_at=PUBLISHED_AT,
    )
    imported = plan.research_evidence
    source = imported["evidence"][0]
    citation = imported["citations"][0]["citation"]
    assert source["id"] == plan.identities[SOURCE_ID] != SOURCE_ID
    assert source["text_available"] is False
    assert source["version"] == citation["source_version"] == 2
    assert source["content_hash"] == document["evidence"][0]["content_hash"]
    assert source["imported_from"]["source_id"] == SOURCE_ID
    assert citation["quote"] == document["citations"][0]["citation"]["quote"]
    assert citation["source_id"] == source["id"]
    assert imported["citations"][0]["imported_from"] == {
        "project_id": document["project_id"],
        "twin_id": document["citations"][0]["twin_id"],
        "twin_version": document["citations"][0]["twin_version"],
        "status": "ACTIVE",
    }
    assert (
        imported["citations"][0]["twin_id"] == plan.identities[document["citations"][0]["twin_id"]]
    )
    rewriter = _Rewriter(
        identities=plan.identities,
        owner_user_id=NEW_OWNER,
        created_at=PUBLISHED_AT,
        evidence_ids=frozenset({SOURCE_ID}),
    )
    reference = {
        "source_kind": "OWNER_INPUT",
        "source_id": SOURCE_ID,
        "source_version": 2,
        "content_hash": source["content_hash"],
        "locator": "characters 2:3",
        "summary": "Synthetic source",
    }
    assert rewriter.rewrite(reference) == {**reference, "source_id": source["id"]}


@pytest.mark.parametrize(
    "mutation", ["original_text", "wrong_hash", "wrong_span", "retired_active"]
)
def test_schema_rejects_leaked_text_or_unreconstructible_citations(mutation):
    document = evidence_document()
    if mutation == "original_text":
        document["evidence"][0]["text"] = "Never export this body."
    elif mutation == "wrong_hash":
        document["citations"][0]["citation"]["content_hash"] = "a" * 64
    elif mutation == "wrong_span":
        document["citations"][0]["citation"]["end"] += 1
    else:
        document["evidence"][0].update(status="RETIRED", retired_at=PUBLISHED_AT.isoformat())
    with pytest.raises(KnowledgeSchemaError):
        validate_document("evidence", document)


def test_archive_rejects_undeclared_evidence_even_when_digest_is_listed():
    sources = real_sources()
    folder = build_knowledge_folder(
        replace(sources, research_evidence=evidence_document(sources)),
        version_number=3,
        created_at=PUBLISHED_AT,
    )
    files = copy.deepcopy(folder.files)
    manifest = json.loads(files["orchestwin.json"])
    del manifest["research_evidence"]
    files["orchestwin.json"] = json.dumps(manifest)
    with pytest.raises(KnowledgeArchiveError, match="FOLDER_TAMPERED"):
        verify_folder(files)


def test_export_stops_at_changed_context_and_names_omitted_items():
    sources = real_sources()
    previous = sources.modeling.snapshot.twin_versions[1]
    twin = replace(
        previous,
        id=NEW_OWNER,
        version_number=previous.version_number + 1,
        based_on_version_number=previous.version_number,
    )
    snapshot = replace(
        sources.modeling.snapshot, twin_versions=(sources.modeling.snapshot.twin_versions[0], twin)
    )
    modeling = replace(
        sources.modeling,
        id=NEW_BRIEF,
        version_number=sources.modeling.version_number + 1,
        based_on_version_number=sources.modeling.version_number,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
    )
    gate = approved_gate(
        modeling, HumanGateType.USER_MODELING, user_modeling_artifact_reference(modeling), 9900
    )
    updated = replace(sources, modeling=modeling, modeling_gate=gate)
    exported = load(
        loader(updated, evidence_query_service=FakeQuery(evidence_document(sources), "current"))
    )
    assert exported.present_stages == ("brief", "team", "twins")
    omitted = exported.research_evidence["omitted_sections"]
    assert [item["stage"] for item in omitted] == ["requirements", "design"]
    assert omitted[0]["reason"] == "USER_TWINS_CHANGED"
    assert omitted[0]["affected_codes"]["scenarios"]
    assert omitted[0]["affected_codes"]["requirements"]
    folder = build_knowledge_folder(exported, version_number=4, created_at=PUBLISHED_AT)
    assert "requirements/requirements.json" not in folder.files
    assert "design/design.json" not in folder.files
    assert "omitted_sections" in folder.files[EVIDENCE_DOCUMENT]
    assert verify_folder(folder.files).present_stages == exported.present_stages
