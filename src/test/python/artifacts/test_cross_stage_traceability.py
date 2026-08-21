"""Tests for deterministic cross-stage artifact traceability."""

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.traceability import (
    ArtifactGraphLinkKind,
    ArtifactGraphNodeKind,
    ArtifactGraphReference,
    ArtifactGraphStage,
    build_cross_stage_artifact_graph,
)

from .architecture_fixtures import (
    ARCHITECTURE_ID,
    FRONTEND_COMPONENT_ID,
    TEST_CASE_ID,
    architecture_version,
)
from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    CRITERION_ID,
    DESIGN_VERSION_ID,
    PROTOTYPE_ID,
    REQUIREMENT_ID,
    REQUIREMENTS_VERSION_ID,
    design_version,
    requirements_version,
)


def reference(kind: ArtifactGraphNodeKind, artifact_id: UUID) -> ArtifactGraphReference:
    """Create one concise non-versioned graph reference for assertions."""
    return ArtifactGraphReference(kind=kind, artifact_id=artifact_id)


def test_cross_stage_graph_preserves_exact_stage_roots_and_is_reproducible() -> None:
    """Derive the same canonical graph and hash from the same immutable versions."""
    first = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
        architecture_version(),
    )
    second = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
        architecture_version(),
    )

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.requirements_reference.artifact_id == REQUIREMENTS_VERSION_ID
    assert first.design_reference is not None
    assert first.design_reference.artifact_id == DESIGN_VERSION_ID
    assert first.architecture_reference is not None
    assert first.architecture_reference.artifact_id == architecture_version().id
    assert first.to_snapshot()["schema_version"] == 1


def test_cross_stage_graph_connects_requirements_design_architecture_and_tests() -> None:
    """Expose traceable links from approved needs through implementation planning."""
    graph = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
        architecture_version(),
    )
    links = set(graph.links)

    requirement = reference(ArtifactGraphNodeKind.REQUIREMENT, REQUIREMENT_ID)
    criterion = reference(ArtifactGraphNodeKind.ACCEPTANCE_CRITERION, CRITERION_ID)
    alternative = reference(ArtifactGraphNodeKind.DESIGN_ALTERNATIVE, ALTERNATIVE_ONE_ID)
    prototype = reference(ArtifactGraphNodeKind.DECLARATIVE_PROTOTYPE, PROTOTYPE_ID)
    architecture = reference(ArtifactGraphNodeKind.SOFTWARE_ARCHITECTURE, ARCHITECTURE_ID)
    component = reference(ArtifactGraphNodeKind.ARCHITECTURE_COMPONENT, FRONTEND_COMPONENT_ID)
    test_case = reference(ArtifactGraphNodeKind.TEST_CASE, TEST_CASE_ID)

    assert any(
        link.kind is ArtifactGraphLinkKind.VERIFIED_BY
        and link.source == requirement
        and link.target == criterion
        for link in links
    )
    assert any(
        link.kind is ArtifactGraphLinkKind.TRACES_TO
        and link.source == alternative
        and link.target == requirement
        for link in links
    )
    assert any(
        link.kind is ArtifactGraphLinkKind.REPRESENTS
        and link.source == prototype
        and link.target == alternative
        for link in links
    )
    assert any(
        link.kind is ArtifactGraphLinkKind.REALIZES
        and link.source == architecture
        and link.target == alternative
        for link in links
    )
    assert any(
        link.kind is ArtifactGraphLinkKind.TRACES_TO
        and link.source == component
        and link.target == requirement
        for link in links
    )
    assert any(
        link.kind is ArtifactGraphLinkKind.TESTS
        and link.source == test_case
        and link.target == requirement
        for link in links
    )


def test_cross_stage_graph_keeps_synthetic_critiques_explicitly_separate() -> None:
    """Represent synthetic critique artifacts without treating them as validation evidence."""
    graph = build_cross_stage_artifact_graph(
        requirements_version(),
        design_version(),
        architecture_version(),
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
    assert graph.architecture_reference is None
    assert any(
        node.reference.kind is ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION
        for node in graph.nodes
    )
    assert not any(node.stage is ArtifactGraphStage.DESIGN for node in graph.nodes)
    assert not any(node.stage is ArtifactGraphStage.ARCHITECTURE for node in graph.nodes)


def test_cross_stage_graph_rejects_a_design_grounded_in_another_requirements_version() -> None:
    """Never combine artifacts whose exact version/hash approval tuples diverge."""
    other_requirements = replace(
        requirements_version(),
        id=UUID("00000000-0000-4000-8000-000000009999"),
    )

    with pytest.raises(ValueError, match="exact Requirements version"):
        build_cross_stage_artifact_graph(other_requirements, design_version())


def test_cross_stage_graph_rejects_architecture_without_its_exact_design() -> None:
    """Require Design provenance before adding Architecture and Test Plan artifacts."""
    with pytest.raises(ValueError, match="exact Design version"):
        build_cross_stage_artifact_graph(
            requirements_version(),
            architecture=architecture_version(),
        )
