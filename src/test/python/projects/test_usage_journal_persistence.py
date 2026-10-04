from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Insert

from orchestwin.activity import ActivityError, active_session, journal_rows, project_activity
from orchestwin.artifacts.human_validation_persistence import SqlAlchemyHumanValidationRepository
from orchestwin.projects.persistence.usage_journal import (
    USAGE_EVENTS,
    SqlAlchemyUsageJournalRepository,
)

PROJECT = UUID(int=3701)
OWNER = UUID(int=3702)
NOW = datetime(2026, 10, 4, 9, tzinfo=UTC)
ROME = timezone(timedelta(hours=2))
CODE = "SES-P01"
ROW_KEYS = [
    "sequence",
    "session_code",
    "source",
    "kind",
    "section",
    "target",
    "client_at",
    "received_at",
    "duration_ms",
    "status",
]


class Session:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    async def scalar(self, statement):
        self.calls.append(("scalar", statement, None))
        return self.results.pop(0)

    async def execute(self, statement, parameters=None):
        self.calls.append(("execute", statement, parameters))
        return self.results.pop(0) if self.results else None


def journal(session):
    return SqlAlchemyUsageJournalRepository(session, owner_user_id=OWNER)


def compiled(statement):
    result = statement.compile(dialect=postgresql.dialect())
    return str(result), result.params


def started():
    return {"session_code": CODE, "source": "STUDIO", "kind": "SESSION_STARTED"}


@pytest.mark.parametrize("lock", [False, True])
def test_owned_has_the_owner_scope_and_project_lock_of_human_validation(lock):
    ours, reference = Session(PROJECT), Session(PROJECT)
    assert asyncio.run(journal(ours).owned(PROJECT, lock=lock)) is True
    assert (
        asyncio.run(
            SqlAlchemyHumanValidationRepository(reference, owner_user_id=OWNER).owned(
                PROJECT, lock=lock
            )
        )
        is True
    )
    text, values = compiled(ours.calls[0][1])
    assert (text, values) == compiled(reference.calls[0][1])
    assert values == {"id_1": PROJECT, "owner_user_id_1": OWNER}
    assert "projects.archived_at IS NULL" in text
    assert text.endswith(" FOR UPDATE") is lock
    assert asyncio.run(journal(Session(None)).owned(PROJECT, lock=lock)) is False


def test_rows_are_the_owner_journal_in_sequence_order_with_utc_iso_instants():
    stored = [
        {
            "sequence": 1,
            "session_code": CODE,
            "source": "STUDIO",
            "kind": "SESSION_STARTED",
            "section": None,
            "target": None,
            "client_at": None,
            "received_at": datetime(2026, 10, 4, 11, tzinfo=ROME),
            "duration_ms": None,
            "status": None,
        },
        {
            "sequence": 2,
            "session_code": CODE,
            "source": "WEB",
            "kind": "SECTION_OPENED",
            "section": "BRIEF",
            "target": None,
            "client_at": datetime(2026, 10, 4, 11, 0, 1, 250000, tzinfo=ROME),
            "received_at": datetime(2026, 10, 4, 11, 0, 3, tzinfo=ROME),
            "duration_ms": None,
            "status": None,
        },
    ]
    session = Session(SimpleNamespace(mappings=lambda: stored))
    rows = asyncio.run(journal(session).rows(PROJECT))
    assert [list(row) for row in rows] == [ROW_KEYS, ROW_KEYS]
    assert rows[0] == {
        **stored[0],
        "received_at": "2026-10-04T09:00:00+00:00",
    }
    assert rows[1] == {
        **stored[1],
        "client_at": "2026-10-04T09:00:01.250000+00:00",
        "received_at": "2026-10-04T09:00:03+00:00",
    }
    text, values = compiled(session.calls[0][1])
    assert values == {"project_id_1": PROJECT, "owner_user_id_1": OWNER}
    assert "WHERE project_usage_events.project_id = " in text
    assert " AND project_usage_events.owner_user_id = " in text
    assert text.endswith("ORDER BY project_usage_events.sequence")
    assert active_session(rows) == {"code": CODE, "started_at": "2026-10-04T09:00:00+00:00"}
    document = project_activity(project_id=str(PROJECT), facts=[], journal=rows)
    assert [event["at"] for event in document["events"]] == [
        "2026-10-04T09:00:00+00:00",
        "2026-10-04T09:00:01.250000+00:00",
    ]


def test_count_reads_only_the_owner_rows_of_the_project():
    session = Session(3)
    assert asyncio.run(journal(session).count(PROJECT)) == 3
    text, values = compiled(session.calls[0][1])
    assert text.startswith("SELECT count(*)")
    assert "FROM project_usage_events" in text
    assert values == {"project_id_1": PROJECT, "owner_user_id_1": OWNER}


def test_append_numbers_rows_after_the_project_maximum_under_the_project_lock():
    rows = [
        started(),
        *journal_rows(
            source="WEB",
            session_code=CODE,
            events=[
                {
                    "kind": "SECTION_OPENED",
                    "section": "BRIEF",
                    "client_at": "2026-10-04T11:00:01+02:00",
                },
                {
                    "kind": "REQUEST_FAILED",
                    "section": "BRIEF",
                    "target": "BRIEF_LOCKED",
                    "status": "409",
                    "client_at": "2026-10-04T11:00:02+02:00",
                },
            ],
        ),
    ]
    session = Session(PROJECT, 7)
    assert asyncio.run(journal(session).append(PROJECT, rows, received_at=NOW)) == 3
    assert [call[0] for call in session.calls] == ["scalar", "scalar", "execute"]
    lock_text, lock_values = compiled(session.calls[0][1])
    assert lock_text.endswith(" FOR UPDATE")
    assert lock_values == {"id_1": PROJECT, "owner_user_id_1": OWNER}
    maximum_text, maximum_values = compiled(session.calls[1][1])
    assert "max(project_usage_events.sequence)" in maximum_text
    assert "owner_user_id" not in maximum_text
    assert maximum_values == {"project_id_1": PROJECT}
    _, insert, values = session.calls[2]
    assert isinstance(insert, Insert) and insert.table is USAGE_EVENTS
    assert len({value.pop("id") for value in values}) == 3
    assert values == [
        {
            "project_id": PROJECT,
            "owner_user_id": OWNER,
            "session_code": CODE,
            "sequence": 8,
            "source": "STUDIO",
            "kind": "SESSION_STARTED",
            "section": None,
            "target": None,
            "client_at": None,
            "received_at": NOW,
            "duration_ms": None,
            "status": None,
        },
        {
            "project_id": PROJECT,
            "owner_user_id": OWNER,
            "session_code": CODE,
            "sequence": 9,
            "source": "WEB",
            "kind": "SECTION_OPENED",
            "section": "BRIEF",
            "target": None,
            "client_at": datetime(2026, 10, 4, 9, 0, 1, tzinfo=UTC),
            "received_at": NOW,
            "duration_ms": None,
            "status": None,
        },
        {
            "project_id": PROJECT,
            "owner_user_id": OWNER,
            "session_code": CODE,
            "sequence": 10,
            "source": "WEB",
            "kind": "REQUEST_FAILED",
            "section": "BRIEF",
            "target": "BRIEF_LOCKED",
            "client_at": datetime(2026, 10, 4, 9, 0, 2, tzinfo=UTC),
            "received_at": NOW,
            "duration_ms": None,
            "status": "409",
        },
    ]


def test_append_starts_an_empty_journal_at_one_and_skips_an_empty_batch():
    session = Session(PROJECT, None)
    assert asyncio.run(journal(session).append(PROJECT, [started()], received_at=NOW)) == 1
    assert session.calls[2][2][0]["sequence"] == 1
    empty = Session(PROJECT, 4)
    assert asyncio.run(journal(empty).append(PROJECT, [], received_at=NOW)) == 0
    assert [call[0] for call in empty.calls] == ["scalar", "scalar"]


def test_append_outside_the_owner_scope_raises_before_any_read_or_write():
    session = Session(None)
    with pytest.raises(ActivityError, match="PROJECT_NOT_FOUND") as refused:
        asyncio.run(journal(session).append(PROJECT, [started()], received_at=NOW))
    assert refused.value.code == "PROJECT_NOT_FOUND"
    assert [call[0] for call in session.calls] == ["scalar"]
    assert compiled(session.calls[0][1])[0].endswith(" FOR UPDATE")
