"""Tests for structured partial Project Briefs."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.briefs import (
    BriefField,
    ProjectBrief,
    ProjectBriefVersion,
    create_project_brief,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
USER_ID = UUID("00000000-0000-4000-8000-000000000001")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")


def test_brief_distinguishes_provided_unknown_and_missing_fields() -> None:
    """Preserve epistemic status without inventing absent facts."""
    brief = create_project_brief(
        name=" Hotel   Management ",
        goals=[
            " Manage rooms ",
            " Track reservations ",
        ],
        unknown_fields=[
            BriefField.BUDGET,
            BriefField.TEMPORAL_CONSTRAINTS,
        ],
    )

    assert brief.name == "Hotel Management"
    assert brief.goals == (
        "Manage rooms",
        "Track reservations",
    )
    assert BriefField.NAME in (brief.provided_fields)
    assert BriefField.BUDGET in (brief.unknown_fields)
    assert BriefField.PROBLEM in (brief.missing_fields)
    assert BriefField.BUDGET not in (brief.missing_fields)


def test_field_cannot_be_provided_and_unknown() -> None:
    """Reject contradictory epistemic state."""
    with pytest.raises(
        ValueError,
        match="cannot be provided and UNKNOWN",
    ):
        create_project_brief(
            budget="EUR 5,000",
            unknown_fields=[BriefField.BUDGET],
        )


def test_brief_snapshot_and_hash_are_deterministic() -> None:
    """Produce stable immutable content identifiers."""
    first = create_project_brief(
        name="Project",
        stakeholders=[
            "Owner",
            "Reviewer",
        ],
        unknown_fields=[
            BriefField.BUDGET,
            BriefField.DOMAIN,
        ],
    )
    second = create_project_brief(
        name="Project",
        stakeholders=[
            "Owner",
            "Reviewer",
        ],
        unknown_fields=[
            BriefField.DOMAIN,
            BriefField.BUDGET,
        ],
    )

    assert first.to_snapshot() == (second.to_snapshot())
    assert first.canonical_json() == (second.canonical_json())
    assert first.content_hash == (second.content_hash)
    assert len(first.content_hash) == 64


def test_brief_can_be_reconstructed_from_snapshot() -> None:
    """Round-trip the JSONB-compatible representation."""
    original = create_project_brief(
        name="Project",
        description="A structured project brief.",
        functional_requirements=[
            "Create a project",
            "Version its brief",
        ],
        unknown_fields=[BriefField.BUDGET],
    )

    reconstructed = ProjectBrief.from_snapshot(original.to_snapshot())

    assert reconstructed == original
    assert reconstructed.content_hash == (original.content_hash)


def test_brief_version_requires_matching_hash() -> None:
    """Bind a version to exactly one immutable snapshot."""
    brief = create_project_brief(name="Project")

    version = ProjectBriefVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=USER_ID,
        created_at=datetime.now(UTC),
    )

    assert version.version_number == 1

    with pytest.raises(
        ValueError,
        match="hash does not match",
    ):
        ProjectBriefVersion(
            id=VERSION_ID,
            project_id=PROJECT_ID,
            version_number=1,
            schema_version=brief.SCHEMA_VERSION,
            brief=brief,
            content_hash="0" * 64,
            created_by_user_id=USER_ID,
            created_at=datetime.now(UTC),
        )
