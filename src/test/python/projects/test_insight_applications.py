from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.briefs import BriefField
from orchestwin.projects.insight_applications import (
    InsightSourceKind,
    InsightTarget,
    create_insight_application,
    insight_application_from_snapshot,
)

NOW = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)


def application(**overrides):
    values = {
        "application_id": UUID(int=1),
        "project_id": UUID(int=2),
        "owner_user_id": UUID(int=3),
        "source_kind": InsightSourceKind.SYNTHETIC_FINDING,
        "source_id": "run:00000000-0000-4000-8000-000000000901:UTF-001",
        "source_twin_id": UUID(int=4),
        "text": "  The guest name field   lacks help text. ",
        "target": InsightTarget.REQUIREMENTS,
        "target_field": None,
        "target_version_id": UUID(int=5),
        "target_version_number": 2,
        "target_code": "REQ-004",
        "created_at": NOW,
    }
    values.update(overrides)
    return create_insight_application(**values)


def test_application_normalizes_text_and_round_trips():
    item = application()
    assert item.text == "The guest name field lacks help text."
    snapshot = item.to_snapshot()
    assert snapshot["target"] == "REQUIREMENTS"
    assert snapshot["target_field"] is None
    assert insight_application_from_snapshot(snapshot) == item
    with pytest.raises(ValueError, match=r"hash is inconsistent|not canonical"):
        insight_application_from_snapshot({**snapshot, "text": "Changed"})
    with pytest.raises(ValueError, match="hash is inconsistent"):
        replace(item, text="Changed")


def test_brief_applications_name_a_list_field_and_others_carry_a_code():
    brief = application(
        target=InsightTarget.BRIEF,
        target_field=BriefField.RISKS,
        target_code=None,
        source_kind=InsightSourceKind.TWIN_CHAT_INSIGHT,
    )
    assert brief.target_field is BriefField.RISKS
    with pytest.raises(ValueError, match="name a brief field"):
        application(target=InsightTarget.BRIEF, target_field=None, target_code=None)
    with pytest.raises(ValueError, match="list fields"):
        application(target=InsightTarget.BRIEF, target_field=BriefField.NAME, target_code=None)
    with pytest.raises(ValueError, match="carry the created code"):
        application(target=InsightTarget.DESIGN, target_code=None)
    with pytest.raises(ValueError, match="carry the created code"):
        application(
            target=InsightTarget.BRIEF, target_field=BriefField.GOALS, target_code="REQ-001"
        )
    with pytest.raises(ValueError, match="must not be empty"):
        application(text="   ")
    with pytest.raises(ValueError, match="timezone-aware"):
        application(created_at=NOW.replace(tzinfo=None))


def test_twin_discussion_applications_round_trip_like_the_other_kinds():
    assert InsightSourceKind("TWIN_DISCUSSION") is InsightSourceKind.TWIN_DISCUSSION
    source_id = f"discussion:{UUID(int=6)}:2:PRP-001"
    for target, field, code in (
        (InsightTarget.REQUIREMENTS, None, "REQ-004"),
        (InsightTarget.DESIGN, None, "DRK-002"),
        (InsightTarget.BRIEF, BriefField.RISKS, None),
    ):
        item = application(
            source_kind=InsightSourceKind.TWIN_DISCUSSION,
            source_id=source_id,
            source_twin_id=None,
            target=target,
            target_field=field,
            target_code=code,
        )
        snapshot = item.to_snapshot()
        assert (snapshot["source_kind"], snapshot["source_id"]) == ("TWIN_DISCUSSION", source_id)
        assert snapshot["source_twin_id"] is None
        assert insight_application_from_snapshot(snapshot) == item
