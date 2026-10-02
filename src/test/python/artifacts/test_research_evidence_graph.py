from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from orchestwin.artifacts import traceability_runtime
from orchestwin.artifacts.traceability import build_cross_stage_artifact_graph
from orchestwin.twins.epistemics import EvidenceReference, EvidenceSourceKind, ObservationProvenance
from orchestwin.twins.user_modeling_gate import user_modeling_artifact_reference
from orchestwin.workflow.gates import HumanGateType
from src.test.python.knowledge.knowledge_fixtures import approved_gate, real_sources
from src.test.python.knowledge.test_research_evidence import NEW_OWNER, evidence_document


def test_graph_links_evidence_to_current_twin_and_preserves_definition_reference():
    sources = real_sources()
    evidence = evidence_document(sources)
    old = sources.modeling.snapshot.twin_versions[0]
    observations = list(old.profile.observations)
    index = next(
        index
        for index, observation in enumerate(observations)
        if observation.observation_key == "user_twin.goals"
    )
    source = evidence["evidence"][0]
    observations[index] = replace(
        observations[index],
        provenance=ObservationProvenance.from_references(
            (
                *observations[index].provenance.references,
                EvidenceReference(
                    source_kind=EvidenceSourceKind.OWNER_INPUT,
                    source_id=source["id"],
                    source_version=source["version"],
                    content_hash=source["content_hash"],
                ),
            )
        ),
    )
    profile = replace(old.profile, observations=tuple(observations))
    current = replace(
        old,
        id=NEW_OWNER,
        version_number=old.version_number + 1,
        based_on_version_number=old.version_number,
        profile=profile,
        content_hash=profile.content_hash,
    )
    graph = build_cross_stage_artifact_graph(
        sources.requirements, sources.design, research_evidence=evidence, evidence_twins=(current,)
    ).to_snapshot()
    twins = [
        node["reference"]
        for node in graph["nodes"]
        if node["reference"]["kind"] == "USER_TWIN"
        and node["reference"]["artifact_id"] == str(current.twin_id)
    ]
    assert {reference["version_number"] for reference in twins} == {
        old.version_number,
        current.version_number,
    }
    link = next(item for item in graph["links"] if item["kind"] == "SUPPORTS")
    assert link["target"]["content_hash"] == current.content_hash
    assert link["target"]["version_number"] == current.version_number
    assert link["source"]["content_hash"] == source["content_hash"]
    evidence["citations"][0]["status"] = "RETIRED"
    evidence["evidence"][0]["status"] = "RETIRED"
    withdrawn = build_cross_stage_artifact_graph(
        sources.requirements, sources.design, research_evidence=evidence, evidence_twins=(current,)
    ).to_snapshot()
    assert not any(item["kind"] == "SUPPORTS" for item in withdrawn["links"])


def test_graph_is_unchanged_when_no_evidence_exists():
    sources = real_sources()
    first = build_cross_stage_artifact_graph(sources.requirements, sources.design)
    second = build_cross_stage_artifact_graph(
        sources.requirements, sources.design, research_evidence={"evidence": [], "citations": []}
    )
    assert first == second


@pytest.mark.parametrize("approved", [False, True])
def test_graph_runtime_uses_only_current_approved_twin_for_evidence(monkeypatch, approved):
    sources = real_sources()
    evidence = evidence_document(sources)
    old = sources.modeling.snapshot.twin_versions[0]
    reference = EvidenceReference(
        source_kind=EvidenceSourceKind.OWNER_INPUT,
        source_id=evidence["evidence"][0]["id"],
        source_version=2,
        content_hash=evidence["evidence"][0]["content_hash"],
    )
    observations = tuple(
        replace(
            item,
            provenance=ObservationProvenance.from_references(
                (*item.provenance.references, reference)
            ),
        )
        if item.observation_key == "user_twin.goals"
        else item
        for item in old.profile.observations
    )
    profile = replace(old.profile, observations=observations)
    current = replace(
        old,
        id=NEW_OWNER,
        version_number=old.version_number + 1,
        based_on_version_number=old.version_number,
        profile=profile,
        content_hash=profile.content_hash,
    )
    snapshot = replace(
        sources.modeling.snapshot,
        twin_versions=(current, *sources.modeling.snapshot.twin_versions[1:]),
    )
    modeling = replace(sources.modeling, snapshot=snapshot, content_hash=snapshot.content_hash)
    gate = (
        approved_gate(
            modeling, HumanGateType.USER_MODELING, user_modeling_artifact_reference(modeling), 9950
        )
        if approved
        else None
    )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *details):
            return None

        async def scalar(self, query):
            return gate

    class Repository:
        def __init__(self, version):
            self.version = version

        def __call__(self, session, *, owner_user_id):
            return self

        async def current(self, *, project_id):
            return self.version

        async def dossier(self, project_id):
            return evidence

    for name, version in (
        ("SqlAlchemyRequirementsSpecificationRepository", sources.requirements),
        ("SqlAlchemyDesignPackageRepository", sources.design),
        ("SqlAlchemyResearchEvidenceRepository", None),
        ("SqlAlchemyUserModelingSnapshotRepository", modeling),
    ):
        monkeypatch.setattr(traceability_runtime, name, Repository(version))
    monkeypatch.setattr(traceability_runtime, "gate_record_to_domain", lambda record: record)
    graph = asyncio.run(
        traceability_runtime.SqlAlchemyArtifactGraphQueryService(Session).current(
            owner_user_id=modeling.created_by_user_id, project_id=sources.project_id
        )
    )
    supports = [item for item in graph.links if item.kind.value == "SUPPORTS"]
    assert bool(supports) is approved
    if supports:
        assert supports[0].target.version_number == current.version_number
    assert any(item.reference.kind.value == "RESEARCH_EVIDENCE" for item in graph.nodes)
