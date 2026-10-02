"""Tests for deterministic cross-stage artifact traceability."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

import pytest

from orchestwin.artifacts import traceability_runtime
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_realignment import realigned_design_version
from orchestwin.artifacts.traceability import (
    ArtifactGraphLinkKind,
    ArtifactGraphNodeKind,
    ArtifactGraphReference,
    ArtifactGraphStage,
    CrossStageArtifactGraph,
    build_cross_stage_artifact_graph,
    grounded_design,
)
from orchestwin.artifacts.traceability_runtime import SqlAlchemyArtifactGraphQueryService
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from src.test.python.projects.test_requirements_needs import enriched_specification

from .design_fixtures import (
    DESIGN_VERSION_ID,
    OWNER_ID,
    PROJECT_ID,
    REQUIREMENTS_VERSION_ID,
    design_version,
    requirements_version,
)

CHANGED_REQUIREMENTS_ID = UUID("00000000-0000-4000-8000-00000000c001")
REALIGNED_DESIGN_ID = UUID("00000000-0000-4000-8000-00000000c002")
CHANGED_AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def test_definition_two_cross_stage_graph_contains_actor_scenario_need_chain():
    written = requirements_version()
    specification = enriched_specification(written.specification)
    version = replace(written, specification=specification, content_hash=specification.content_hash)
    graph = build_cross_stage_artifact_graph(version)
    shapes = {
        (
            link.kind,
            link.source.kind,
            link.source.artifact_id,
            link.target.kind,
            link.target.artifact_id,
        )
        for link in graph.links
    }
    for scenario, need in zip(specification.scenarios, specification.needs, strict=True):
        assert (
            ArtifactGraphLinkKind.PARTICIPATES_IN,
            ArtifactGraphNodeKind.USER_TWIN,
            scenario.actor.twin_id,
            ArtifactGraphNodeKind.SCENARIO,
            scenario.id,
        ) in shapes
        assert (
            ArtifactGraphLinkKind.REVEALS,
            ArtifactGraphNodeKind.SCENARIO,
            scenario.id,
            ArtifactGraphNodeKind.NEED,
            need.id,
        ) in shapes
        for kind, artifacts in (
            (ArtifactGraphNodeKind.REQUIREMENT, specification.requirements),
            (ArtifactGraphNodeKind.USER_STORY, specification.user_stories),
        ):
            for artifact in artifacts:
                if need.id in artifact.need_ids:
                    assert (
                        ArtifactGraphLinkKind.MOTIVATES,
                        ArtifactGraphNodeKind.NEED,
                        need.id,
                        kind,
                        artifact.id,
                    ) in shapes
    assert graph.requirements_reference.content_hash == version.content_hash


def test_legacy_cross_stage_graph_does_not_invent_need_or_actor_scenario_links():
    graph = build_cross_stage_artifact_graph(requirements_version())
    assert all(node.reference.kind is not ArtifactGraphNodeKind.NEED for node in graph.nodes)
    assert all(
        link.kind not in (ArtifactGraphLinkKind.PARTICIPATES_IN, ArtifactGraphLinkKind.REVEALS)
        for link in graph.links
    )


def reference(kind: ArtifactGraphNodeKind, artifact_id: UUID) -> ArtifactGraphReference:
    """Create one concise non-versioned graph reference for assertions."""
    return ArtifactGraphReference(kind=kind, artifact_id=artifact_id)


def changed_requirements() -> RequirementsSpecificationVersion:
    written = requirements_version()
    specification = written.specification
    reworded = replace(
        specification,
        requirements=tuple(
            replace(requirement, title=f"{requirement.title} and confirm them")
            for requirement in specification.requirements
        ),
    )
    return RequirementsSpecificationVersion(
        id=CHANGED_REQUIREMENTS_ID,
        project_id=written.project_id,
        version_number=2,
        based_on_version_number=1,
        specification=reworded,
        content_hash=reworded.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CHANGED_AT,
    )


def realigned_design(requirements: RequirementsSpecificationVersion) -> DesignPackageVersion:
    return realigned_design_version(
        design_version(),
        requirements,
        version_id=REALIGNED_DESIGN_ID,
        created_by_user_id=OWNER_ID,
        created_at=CHANGED_AT,
    )


class Session:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_details: object) -> None:
        return None


class Repository:
    def __init__(self, version: object) -> None:
        self.version = version
        self.owners: list[UUID] = []

    def __call__(self, session: Session, *, owner_user_id: UUID) -> Self:
        self.owners.append(owner_user_id)
        return self

    async def current(self, *, project_id: UUID) -> object:
        return self.version if project_id == PROJECT_ID else None


def current_graph(
    monkeypatch: pytest.MonkeyPatch,
    requirements: RequirementsSpecificationVersion | None,
    design: DesignPackageVersion | None,
) -> CrossStageArtifactGraph | None:
    monkeypatch.setattr(
        traceability_runtime,
        "SqlAlchemyRequirementsSpecificationRepository",
        Repository(requirements),
    )
    monkeypatch.setattr(
        traceability_runtime, "SqlAlchemyDesignPackageRepository", Repository(design)
    )
    service = SqlAlchemyArtifactGraphQueryService(Session)
    return asyncio.run(service.current(owner_user_id=OWNER_ID, project_id=PROJECT_ID))


def test_the_graph_query_shows_the_requirements_alone_while_the_design_is_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = current_graph(monkeypatch, changed_requirements(), design_version())

    assert graph is not None
    assert graph.requirements_reference.artifact_id == CHANGED_REQUIREMENTS_ID
    assert graph.design_reference is None
    assert not any(node.stage is ArtifactGraphStage.DESIGN for node in graph.nodes)
    assert graph == build_cross_stage_artifact_graph(changed_requirements())


def test_cross_stage_graph_preserves_exact_stage_roots_and_is_reproducible() -> None:
    """Derive the same canonical graph and hash from the same immutable versions."""
    first = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
    )
    second = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
    )

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.requirements_reference.artifact_id == REQUIREMENTS_VERSION_ID
    assert first.design_reference is not None
    assert first.design_reference.artifact_id == DESIGN_VERSION_ID
    assert first.to_snapshot()["schema_version"] == 1


def test_cross_stage_graph_keeps_synthetic_critiques_explicitly_separate() -> None:
    """Represent synthetic critique artifacts without treating them as validation evidence."""
    graph = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
    )
    critiques = [
        node
        for node in graph.nodes
        if node.reference.kind is ArtifactGraphNodeKind.SYNTHETIC_DESIGN_CRITIQUE
    ]

    assert critiques
    assert all(node.stage is ArtifactGraphStage.DESIGN for node in critiques)
    assert all("Synthetic critique" in node.title for node in critiques)
    assert all(
        any(
            link.kind is ArtifactGraphLinkKind.CRITIQUES and link.source == critique.reference
            for link in graph.links
        )
        for critique in critiques
    )


def test_cross_stage_graph_can_expose_requirements_before_later_stages_exist() -> None:
    """Keep traceability queryable while Design and Architecture remain absent."""
    graph = build_cross_stage_artifact_graph(requirements_version())

    assert graph.design_reference is None
    assert any(
        node.reference.kind is ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION
        for node in graph.nodes
    )
    assert not any(node.stage is ArtifactGraphStage.DESIGN for node in graph.nodes)


def test_cross_stage_graph_rejects_a_design_grounded_in_another_requirements_version() -> None:
    """Never combine artifacts whose exact version/hash approval tuples diverge."""
    other_requirements = replace(
        requirements_version(),
        id=UUID("00000000-0000-4000-8000-000000009999"),
    )

    with pytest.raises(ValueError, match="exact Requirements version"):
        build_cross_stage_artifact_graph(other_requirements, design_version())


def test_the_graph_query_shows_the_design_again_after_the_realignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = changed_requirements()
    realigned = realigned_design(current)

    graph = current_graph(monkeypatch, current, realigned)

    assert graph is not None
    assert graph.design_reference is not None
    assert (graph.design_reference.artifact_id, graph.design_reference.version_number) == (
        REALIGNED_DESIGN_ID,
        2,
    )
    assert graph == build_cross_stage_artifact_graph(current, realigned)
    assert any(node.stage is ArtifactGraphStage.DESIGN for node in graph.nodes)


def test_the_graph_query_keeps_a_design_grounded_on_the_current_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = current_graph(monkeypatch, requirements_version(), design_version())

    assert graph == build_cross_stage_artifact_graph(requirements_version(), design_version())
    assert graph.design_reference is not None


def test_the_graph_query_finds_nothing_without_requirements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert current_graph(monkeypatch, None, design_version()) is None


def test_only_a_design_grounded_on_the_exact_requirements_version_is_kept() -> None:
    written = requirements_version()
    current = changed_requirements()
    design = design_version()
    foreign_package = replace(design.package, project_id=UUID(int=7))
    foreign = replace(
        design,
        project_id=foreign_package.project_id,
        package=foreign_package,
        content_hash=foreign_package.content_hash,
    )

    assert grounded_design(written, design) is design
    assert grounded_design(current, design) is None
    assert grounded_design(current, realigned_design(current)) is not None
    assert grounded_design(written, None) is None
    assert grounded_design(written, foreign) is None


def test_the_node_of_the_approved_team_speaks_of_perspectives() -> None:
    graph = build_cross_stage_artifact_graph(requirements_version(), design_version())

    [team] = [
        node for node in graph.nodes if node.reference.kind is ArtifactGraphNodeKind.AGENT_TEAM
    ]

    assert (team.display_code, team.title) == ("TEAM-v1", "Approved perspectives")
