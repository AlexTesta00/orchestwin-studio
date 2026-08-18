"""Tests for immutable requirements and user stories."""

from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.projects.requirements import (
    Requirement,
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
SECOND_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")


def project_brief_source() -> RequirementSourceReference:
    """Create one exact Project Brief source reference."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id=("00000000-0000-4000-8000-000000000040"),
        source_version=2,
        content_hash="a" * 64,
        locator="functional_requirements[0]",
    )


def owner_source() -> RequirementSourceReference:
    """Create one explicit owner-input source reference."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.OWNER_INPUT,
        source_id=("owner:00000000-0000-4000-8000-000000000001"),
        locator="requirements.review",
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=3,
        content_hash="b" * 64,
        name="Hotel Receptionist Twin",
    )


def test_requirement_preserves_identity_priority_and_grounding() -> None:
    """Keep one requirement stable, typed, and inspectably grounded."""
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="  Manage   reservations ",
        statement=(" Staff must create and update reservations. "),
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(
            owner_source(),
            project_brief_source(),
        ),
        user_twin_references=(twin_reference(),),
    )

    assert requirement.title == "Manage reservations"
    assert requirement.statement == ("Staff must create and update reservations.")
    assert requirement.sources == (
        owner_source(),
        project_brief_source(),
    )
    assert requirement.user_twin_references == (twin_reference(),)
    assert requirement.to_snapshot()["priority"] == "MUST"
    assert len(requirement.content_hash) == 64


def test_requirement_requires_auditable_sources() -> None:
    """Do not accept a requirement with no inspectable origin."""
    with pytest.raises(
        ValueError,
        match="sources must not be empty",
    ):
        create_requirement(
            requirement_id=REQUIREMENT_ID,
            code="REQ-001",
            title="Manage reservations",
            statement=("Staff must create and update reservations."),
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            sources=(),
        )


def test_direct_requirement_requires_canonical_reference_order() -> None:
    """Keep direct construction deterministic rather than order-sensitive."""
    with pytest.raises(
        ValueError,
        match="sources must use canonical order",
    ):
        Requirement(
            id=REQUIREMENT_ID,
            code="REQ-001",
            title="Manage reservations",
            statement=("Staff must create and update reservations."),
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            sources=(
                project_brief_source(),
                owner_source(),
            ),
        )


def test_user_story_references_one_exact_twin_and_requirements() -> None:
    """Bind a user story to a specific User Twin and stable requirements."""
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="  review   room availability ",
        benefit=" avoid double bookings ",
        requirement_ids=(
            SECOND_REQUIREMENT_ID,
            REQUIREMENT_ID,
        ),
    )

    assert story.goal == "review room availability"
    assert story.benefit == "avoid double bookings"
    assert story.requirement_ids == (
        REQUIREMENT_ID,
        SECOND_REQUIREMENT_ID,
    )
    assert story.user_twin_reference == twin_reference()


def test_user_story_requires_at_least_one_requirement() -> None:
    """Reject a story that cannot be traced to project requirements."""
    with pytest.raises(
        ValueError,
        match="requirement IDs must not be empty",
    ):
        create_user_story(
            story_id=STORY_ID,
            code="USR-001",
            user_twin_reference=twin_reference(),
            goal="Review room availability",
            benefit="Avoid double bookings",
            requirement_ids=(),
        )


@pytest.mark.parametrize(
    (
        "code",
        "expected_message",
    ),
    (
        (
            "REQ-1",
            "REQ-NNN",
        ),
        (
            "req-001",
            "REQ-NNN",
        ),
        (
            "USR-01",
            "USR-NNN",
        ),
    ),
)
def test_artifact_codes_use_stable_readable_formats(
    code: str,
    expected_message: str,
) -> None:
    """Reject unstable or ambiguously formatted display codes."""
    if code.startswith("USR"):
        with pytest.raises(
            ValueError,
            match=expected_message,
        ):
            create_user_story(
                story_id=STORY_ID,
                code=code,
                user_twin_reference=twin_reference(),
                goal="Review room availability",
                benefit="Avoid double bookings",
                requirement_ids=(REQUIREMENT_ID,),
            )

        return

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        create_requirement(
            requirement_id=REQUIREMENT_ID,
            code=code,
            title="Manage reservations",
            statement=("Staff must create and update reservations."),
            kind=RequirementKind.FUNCTIONAL,
            priority=RequirementPriority.MUST,
            sources=(project_brief_source(),),
        )


def test_requirement_and_story_hashes_are_deterministic() -> None:
    """Produce stable hashes independently from iterable input ordering."""
    first_requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Manage reservations",
        statement=("Staff must create and update reservations."),
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(
            owner_source(),
            project_brief_source(),
        ),
    )
    second_requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Manage reservations",
        statement=("Staff must create and update reservations."),
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(
            project_brief_source(),
            owner_source(),
        ),
    )

    assert first_requirement.to_snapshot() == second_requirement.to_snapshot()
    assert first_requirement.content_hash == second_requirement.content_hash
