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

from .design_fixtures import (
    DESIGN_VERSION_ID,
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
    assert first.architecture_reference is None
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
