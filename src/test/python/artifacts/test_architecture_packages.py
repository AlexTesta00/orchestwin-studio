"""Tests for immutable architecture package versions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    create_architecture_grounding,
)
from orchestwin.artifacts.references import ArtifactKind

from .architecture_fixtures import (
    ARCHITECTURE_ID,
    BACKEND_COMPONENT_ID,
    FRONTEND_COMPONENT_ID,
    architecture_package,
    architecture_test_plan,
    architecture_version,
    software_architecture,
)
from .design_fixtures import (
    ALTERNATIVE_ONE_ID,
    OWNER_ID,
    PROJECT_ID,
    PROTOTYPE_ID,
    design_package,
    design_version,
)


def test_architecture_package_preserves_exact_design_grounding() -> None:
    """Carry the selected Design Package and inherited context without weakening it."""
    value = architecture_package()
    design = design_version()

    assert value.grounding.design_package_reference.artifact_id == design.id
    assert value.grounding.design_package_reference.version_number == design.version_number
    assert value.grounding.design_package_reference.content_hash == design.content_hash
    assert value.grounding.requirements_reference == design.package.grounding.requirements_reference
    assert value.grounding.agent_team_reference == design.package.grounding.agent_team_reference
    assert (
        value.grounding.user_modeling_reference == design.package.grounding.user_modeling_reference
    )
    assert value.grounding.owner_selected_alternative_id == ALTERNATIVE_ONE_ID
    assert value.grounding.prototype_id == PROTOTYPE_ID
    assert value.architecture.id == ARCHITECTURE_ID
    assert len(value.content_hash) == 64


def test_architecture_package_rejects_foreign_project_grounding() -> None:
    """Keep exact design grounding inside the owning project scope."""
    other_project = UUID("00000000-0000-4000-8000-000000000999")

    with pytest.raises(ValueError, match="grounding must belong to its project"):
        replace(architecture_package(), project_id=other_project)


def test_architecture_grounding_requires_selected_design_and_prototype() -> None:
    """Do not plan architecture from a Design Package that is not Gate-5-ready."""
    unselected = design_version(package=design_package(selected=False))

    with pytest.raises(ValueError, match="owner-selected design and prototype"):
        create_architecture_grounding(unselected)


def test_package_rejects_a_different_design_alternative() -> None:
    """Keep architecture tied to the exact owner-selected alternative."""
    other = UUID("00000000-0000-4000-8000-000000000999")
    invalid = replace(software_architecture(), selected_design_alternative_id=other)

    with pytest.raises(ValueError, match="owner-selected design alternative"):
        replace(architecture_package(), architecture=invalid)


def test_package_rejects_a_different_prototype() -> None:
    """Keep architecture tied to the exact trusted declarative prototype."""
    other = UUID("00000000-0000-4000-8000-000000000999")
    invalid = replace(software_architecture(), prototype_id=other)

    with pytest.raises(ValueError, match="selected declarative prototype"):
        replace(architecture_package(), architecture=invalid)


def test_package_rejects_a_test_plan_for_another_architecture() -> None:
    """Require the test plan to target the packaged architecture."""
    other = UUID("00000000-0000-4000-8000-000000000999")
    invalid = replace(architecture_test_plan(), architecture_id=other)

    with pytest.raises(ValueError, match="packaged architecture"):
        replace(architecture_package(), test_plan=invalid)


def test_package_requires_test_plan_coverage_of_every_component() -> None:
    """Keep the architecture component index exact across the stage package."""
    original = architecture_test_plan()
    frontend_only_case = replace(
        original.test_cases[0],
        architecture_component_ids=(FRONTEND_COMPONENT_ID,),
    )
    invalid = replace(
        original,
        architecture_component_ids=(FRONTEND_COMPONENT_ID,),
        test_cases=(frontend_only_case,),
    )

    with pytest.raises(ValueError, match="every packaged architecture component"):
        replace(architecture_package(), test_plan=invalid)


def test_architecture_version_exposes_an_exact_reference() -> None:
    """Expose the exact immutable tuple required by Gate 6 and later stages."""
    value = architecture_version()

    assert value.reference.kind is ArtifactKind.ARCHITECTURE_PACKAGE
    assert value.reference.artifact_id == value.id
    assert value.reference.version_number == value.version_number
    assert value.reference.content_hash == value.content_hash


def test_architecture_version_rejects_project_mismatch() -> None:
    """Protect owner/project scoping at the immutable version boundary."""
    other_project = UUID("00000000-0000-4000-8000-000000000999")

    with pytest.raises(ValueError, match="belong to its project"):
        replace(architecture_version(), project_id=other_project)


def test_architecture_version_rejects_hash_mismatch() -> None:
    """Prevent content from being stored under an unrelated digest."""
    with pytest.raises(ValueError, match="hash must match"):
        replace(architecture_version(), content_hash="f" * 64)


def test_architecture_version_requires_timezone_aware_creation_time() -> None:
    """Keep immutable version chronology unambiguous."""
    naive = datetime(2026, 8, 21, 10, 0)

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(architecture_version(), created_at=naive)


def test_architecture_version_requires_linear_lineage() -> None:
    """Require every later version to identify the immediately preceding version."""
    package = architecture_package()

    with pytest.raises(ValueError, match="immediately preceding version"):
        ArchitecturePackageVersion(
            id=UUID("00000000-0000-4000-8000-000000000998"),
            project_id=PROJECT_ID,
            version_number=2,
            based_on_version_number=None,
            package=package,
            content_hash=package.content_hash,
            created_by_user_id=OWNER_ID,
            created_at=architecture_version().created_at,
        )


def test_equal_architecture_packages_have_equal_snapshots_and_hashes() -> None:
    """Keep Architecture Package generation reproducible."""
    first = architecture_package()
    second = architecture_package()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
    assert set(first.test_plan.architecture_component_ids) == {
        FRONTEND_COMPONENT_ID,
        BACKEND_COMPONENT_ID,
    }
