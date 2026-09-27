"""Tests for immutable versioned Design Packages."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from orchestwin.artifacts.design import DesignApproach
from orchestwin.artifacts.design_packages import (
    DesignPackageVersion,
    create_design_grounding,
)
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.references import (
    ArtifactKind,
)

from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    ALTERNATIVE_TWO_ID,
    CREATED_AT,
    DESIGN_VERSION_ID,
    OWNER_ID,
    PROJECT_ID,
    REQUIREMENT_ID,
    design_alternative,
    design_package,
    design_version,
    requirements_version,
)


def test_requirements_scope_preserves_exact_approved_version_and_ids() -> None:
    """Build design scope from one exact immutable Requirements baseline."""
    requirements = requirements_version()
    grounding = create_design_grounding(requirements)

    assert grounding.requirements_reference.kind is ArtifactKind.REQUIREMENTS_SPECIFICATION
    assert grounding.requirements_reference.artifact_id == requirements.id
    assert grounding.requirements_reference.version_number == requirements.version_number
    assert grounding.requirements_reference.content_hash == requirements.content_hash
    assert grounding.agent_team_reference.kind is ArtifactKind.AGENT_TEAM
    assert (
        grounding.agent_team_reference.artifact_id
        == requirements.specification.agent_team_reference.artifact_id
    )
    assert grounding.user_modeling_reference.kind is ArtifactKind.USER_MODELING
    assert (
        grounding.user_modeling_reference.content_hash
        == requirements.specification.user_modeling_reference.content_hash
    )
    assert grounding.catalog_content_hash == requirements.specification.catalog_content_hash
    assert grounding.requirement_ids == (REQUIREMENT_ID,)


def test_design_package_is_canonical_and_ready_only_with_selection_and_prototype() -> None:
    """Distinguish provider recommendation from owner-controlled readiness."""
    ready = design_package()
    unselected = design_package(selected=False)
    selected_without_prototype = design_package(include_prototype=False)

    assert tuple(alternative.code for alternative in ready.alternatives) == (
        "DES-001",
        "DES-002",
    )
    assert ready.recommended_alternative_id == ALTERNATIVE_ONE_ID
    assert ready.owner_selected_alternative_id == ALTERNATIVE_ONE_ID
    assert ready.ready_for_gate is True
    assert unselected.ready_for_gate is False
    assert selected_without_prototype.ready_for_gate is False


def test_design_package_requires_distinct_approaches_and_critiques() -> None:
    """Reject nominal alternatives and uncritiqued design directions."""
    package = design_package()
    duplicate_approach = replace(
        design_alternative(index=2),
        approach=design_alternative(index=1).approach,
    )

    with pytest.raises(ValueError, match="distinct approaches"):
        replace(
            package,
            alternatives=(design_alternative(index=1), duplicate_approach),
        )

    with pytest.raises(ValueError, match="cover every alternative/User Twin pair"):
        replace(
            package,
            critiques=(package.critiques[0],),
        )


def test_distinct_approach_rule_ignores_alternatives_without_approach() -> None:
    package = design_package()
    first = replace(design_alternative(index=1), approach=None)
    second = replace(design_alternative(index=2), approach=None)

    without = replace(package, alternatives=(first, second))
    mixed = replace(package, alternatives=(first, design_alternative(index=2)))

    assert [item.approach for item in without.alternatives] == [None, None]
    assert [item.approach for item in mixed.alternatives] == [
        None,
        DesignApproach.DASHBOARD_FIRST,
    ]


def test_stored_snapshot_with_approaches_reloads_to_the_identical_snapshot_and_hash() -> None:
    package = design_package()
    stored = json.loads(package.canonical_json())

    restored = design_package_from_snapshot(stored)

    assert [item["approach"] for item in stored["alternatives"]] == [
        "GUIDED_WORKFLOW",
        "DASHBOARD_FIRST",
    ]
    assert [item.approach for item in restored.alternatives] == [
        DesignApproach.GUIDED_WORKFLOW,
        DesignApproach.DASHBOARD_FIRST,
    ]
    assert restored.to_snapshot() == stored
    assert restored.canonical_json() == package.canonical_json()
    assert restored.content_hash == package.content_hash


def test_snapshot_without_approach_reloads_without_it() -> None:
    package = design_package()
    snapshot = package.to_snapshot()
    stripped = {
        **snapshot,
        "alternatives": [
            {key: value for key, value in item.items() if key != "approach"}
            for item in snapshot["alternatives"]
        ],
    }

    restored = design_package_from_snapshot(stripped)

    assert [item.approach for item in restored.alternatives] == [None, None]
    assert restored.to_snapshot() == stripped
    assert restored.content_hash != package.content_hash

    with pytest.raises(ValueError, match="not canonical"):
        design_package_from_snapshot(
            {
                **snapshot,
                "alternatives": [{**item, "approach": None} for item in snapshot["alternatives"]],
            }
        )


def test_prototype_must_represent_the_owner_selected_alternative() -> None:
    """Keep prototype identity aligned with the explicit owner decision."""
    package = design_package()

    with pytest.raises(ValueError, match="owner-selected alternative"):
        replace(
            package,
            owner_selected_alternative_id=ALTERNATIVE_TWO_ID,
        )


def test_design_package_version_requires_matching_hash_and_linear_lineage() -> None:
    """Bind each immutable version to exact package content."""
    package = design_package()
    version = DesignPackageVersion(
        id=DESIGN_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    assert version == design_version()

    with pytest.raises(ValueError, match="hash must match"):
        replace(version, content_hash="0" * 64)

    with pytest.raises(ValueError, match="immediately preceding"):
        replace(
            version,
            version_number=2,
            based_on_version_number=None,
        )


def test_equal_design_packages_have_equal_snapshots_and_hashes() -> None:
    """Keep Design Package content addressing deterministic."""
    first = design_package()
    second = design_package()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
