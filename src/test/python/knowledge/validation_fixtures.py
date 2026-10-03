from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

from orchestwin.artifacts.human_validation import create_hypothesis, create_outcome
from orchestwin.knowledge.folder import content_files
from orchestwin.projects.research_evidence import (
    EvidenceSourceKind,
    EvidenceStatus,
    EvidenceVersion,
)
from orchestwin.validation import validation_candidates
from src.test.python.knowledge.knowledge_fixtures import PUBLISHED_AT, real_sources
from src.test.python.knowledge.test_research_evidence import evidence_document


def validation_sources(*, human=False, version=1, retired=False):
    sources = real_sources()
    evidence = evidence_document(sources)
    metadata = evidence["evidence"][0]
    if human:
        metadata.update(
            source_kind="EMPIRICAL_RESEARCH",
            empirical=True,
            context="Anonymized synthetic fixture for the human-session contract",
            method="Fabricated isolated fixture; no actual participant",
            limitations="No real session or empirical measurement was performed",
        )
    document = json.loads(
        content_files(replace(sources, research_evidence=evidence))["traceability/why.json"]
    )
    scenario = next(item for item in document["nodes"] if item["kind"] == "SCENARIO")
    actor_key = next(
        item["target"]
        for item in document["links"]
        if item["source"] == scenario["key"] and item["kind"] == "ACTOR"
    )
    candidate = next(
        item
        for item in validation_candidates(document)
        if any(twin["key"] == actor_key for twin in item["twin_references"])
    )
    design = next(item for item in document["nodes"] if item["kind"] == "DESIGN_PACKAGE")
    hypothesis = create_hypothesis(
        document=document,
        project_id=sources.project_id,
        owner_user_id=sources.design.created_by_user_id,
        request={
            "candidate_key": candidate["key"],
            "twin_key": actor_key,
            "scenario_key": scenario["key"],
            "design_key": design["key"],
            "question": "Does the synthetic task expose the assumption?",
            "task": "Add three synthetic entries",
            "observe": ["Whether the synthetic entries remain visible"],
            "limitations": "Fabricated fixture; no actual human validation",
        },
        code="HYP-001",
        created_at=PUBLISHED_AT,
        version_number=version,
        based_on_version_number=version - 1 if version > 1 else None,
        hypothesis_id=UUID("35000000-0000-4000-8000-000000000001"),
    )
    quote = evidence["citations"][0]["citation"]["quote"]
    original = f"Unexported synthetic preface.\n{quote}\nUnexported synthetic ending."
    source = EvidenceVersion(
        **{
            **metadata,
            "id": UUID(metadata["id"]),
            "source_kind": EvidenceSourceKind(metadata["source_kind"]),
            "status": EvidenceStatus(metadata["status"]),
            "created_at": PUBLISHED_AT,
        }
    )
    outcome = create_outcome(
        hypothesis=hypothesis,
        source=source,
        text=original,
        project_id=sources.project_id,
        owner_user_id=sources.design.created_by_user_id,
        request={
            "hypothesis_id": str(hypothesis.id),
            "hypothesis_version_number": hypothesis.version_number,
            "hypothesis_content_hash": hypothesis.content_hash,
            "session_ref": "SES-SYNTHETIC-FIXTURE" if human else "SYN-FIXTURE",
            "session_kind": "HUMAN_SESSION" if human else "SYNTHETIC_EXERCISE",
            "outcome": "CONFIRMED",
            "coverage": "COMPLETE",
            "limitations": "Synthetic fixture; no real session",
            "evidence_id": metadata["id"],
            "evidence_version": metadata["version"],
            "quote": quote,
            "line": 2,
        },
        code="HVO-001",
        recorded_at=PUBLISHED_AT,
        outcome_id=UUID("35000000-0000-4000-8000-000000000002"),
    )
    if retired:
        metadata.update(
            status="RETIRED",
            retired_at=PUBLISHED_AT.isoformat(),
            retired_reason="Synthetic fixture retirement",
            text_available=False,
        )
        evidence["citations"][0]["status"] = "RETIRED"
    evidence["citations"] = []
    return replace(
        sources,
        research_evidence=evidence,
        validation_records={
            "hypotheses": [hypothesis.to_snapshot()],
            "outcomes": [outcome.to_snapshot()],
        },
    )
