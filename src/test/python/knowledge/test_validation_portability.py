from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.knowledge.archive import KnowledgeArchiveError, verify_folder
from orchestwin.knowledge.folder import (
    build_knowledge_folder,
    file_digests,
    folder_content_hash,
    json_text,
)
from orchestwin.knowledge.project_import import plan_documents, plan_project_import
from orchestwin.knowledge.validation_records import VALIDATION_DOCUMENT
from orchestwin.knowledge.why import normalized_why
from orchestwin.validation import validation_overview
from orchestwin.why import build_why_document
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from src.test.python.knowledge.validation_fixtures import validation_sources


def test_empty_validation_preserves_every_legacy_file_and_hash():
    sources = real_sources()
    original = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    empty = build_knowledge_folder(
        replace(sources, validation_records={"hypotheses": [], "outcomes": []}),
        version_number=1,
        created_at=PUBLISHED_AT,
    )
    assert empty.files == original.files
    assert empty.content_hash == original.content_hash
    assert VALIDATION_DOCUMENT not in empty.files
    assert "validation" not in empty.manifest


@pytest.mark.parametrize(
    "human,retired,version", [(False, False, 1), (True, False, 2), (True, True, 2)]
)
def test_records_travel_with_exact_version_quote_source_hash_and_derived_state(
    human, retired, version
):
    sources = validation_sources(human=human, retired=retired, version=version)
    folder = build_knowledge_folder(sources, version_number=1, created_at=PUBLISHED_AT)
    verified = verify_folder(folder.files)
    records = json.loads(folder.files[VALIDATION_DOCUMENT])
    owner = uuid4()
    plan = plan_project_import(
        verified,
        project_id=uuid4(),
        brief_version_id=uuid4(),
        owner_user_id=owner,
        created_at=PUBLISHED_AT,
    )
    incoming, outcome = records["hypotheses"][0], records["outcomes"][0]
    mapped, result = (
        plan.validation_records["hypotheses"][0],
        plan.validation_records["outcomes"][0],
    )
    assert mapped["id"] != incoming["id"]
    assert mapped["version_number"] == version
    assert mapped["based_on_version_number"] == incoming["based_on_version_number"]
    assert mapped["content_hash"] != incoming["content_hash"]
    assert result["hypothesis_content_hash"] == mapped["content_hash"]
    assert result["citation"]["quote"] == outcome["citation"]["quote"]
    assert (
        result["evidence_content_hash"]
        == result["citation"]["content_hash"]
        == outcome["evidence_content_hash"]
    )
    assert result["citation"]["source_version"] == outcome["citation"]["source_version"]
    derived = build_why_document(
        project_id=str(plan.project_id),
        stages=plan_documents(plan, owner_user_id=owner, created_at=PUBLISHED_AT),
        evidence=plan.research_evidence,
        hypotheses=plan.validation_records["hypotheses"],
        outcomes=plan.validation_records["outcomes"],
    )
    assert normalized_why(
        json.loads(folder.files["traceability/why.json"]),
        identities=plan.identities,
        hashes=plan.hashes,
    ) == normalized_why(derived)
    overview = validation_overview(
        document=derived,
        hypotheses=plan.validation_records["hypotheses"],
        outcomes=plan.validation_records["outcomes"],
        evidence=plan.research_evidence,
    )
    assert overview["hypotheses"][0]["state"] == (
        "CONFIRMED" if human and not retired else "TO_VERIFY"
    )
    assert overview["outcomes"][0]["effective_status"] == ("RETIRED" if retired else "ACTIVE")
    assert "Unexported synthetic preface" not in "".join(folder.files.values())
    if version > 1:
        assert "HYPOTHESIS_HISTORY_PARTIAL" in records["limits"]


def test_partial_dossier_omits_unavailable_historical_context_instead_of_reanchoring():
    sources = validation_sources()
    partial = replace(
        sources, requirements=None, requirements_gate=None, design=None, design_gate=None
    )
    folder = build_knowledge_folder(partial, version_number=1, created_at=PUBLISHED_AT)
    records = json.loads(folder.files[VALIDATION_DOCUMENT])
    assert records["hypotheses"] == records["outcomes"] == []
    assert {item["reason"] for item in records["omitted_sections"]} == {
        "VALIDATION_REFERENCE_UNAVAILABLE",
        "VALIDATION_HYPOTHESIS_UNAVAILABLE",
    }
    assert verify_folder(folder.files).complete is False


@pytest.mark.parametrize("tamper", ["hash", "project", "quote", "reference"])
def test_validation_import_rejects_tampering_even_with_recomputed_file_digests(tamper):
    folder = build_knowledge_folder(validation_sources(), version_number=1, created_at=PUBLISHED_AT)
    files = deepcopy(folder.files)
    records = json.loads(files[VALIDATION_DOCUMENT])
    if tamper == "hash":
        records["hypotheses"][0]["content_hash"] = "f" * 64
    elif tamper == "project":
        records["outcomes"][0]["project_id"] = str(uuid4())
    elif tamper == "quote":
        records["outcomes"][0]["citation"]["quote"] += "invented"
    else:
        records["outcomes"][0]["hypothesis_content_hash"] = "f" * 64
    files[VALIDATION_DOCUMENT] = json_text(records)
    manifest = deepcopy(folder.manifest)
    manifest["files"] = file_digests(
        {
            path: text
            for path, text in files.items()
            if path not in {"orchestwin.json", "ORCHESTWIN.md"}
        }
    )
    manifest["package"]["content_hash"] = folder_content_hash(files)
    files["orchestwin.json"] = json_text(manifest)
    with pytest.raises(KnowledgeArchiveError):
        verify_folder(files)
