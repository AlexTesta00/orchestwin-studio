from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from orchestwin.activity import MAX_JOURNAL_EVENTS, SECTIONS, ActivityError
from orchestwin.projects.activity_runtime import SqlAlchemyProjectActivityService
from orchestwin.projects.persistence.usage_journal import SqlAlchemyUsageJournalRepository

OWNER = UUID(int=3701)
PROJECT = UUID(int=3702)
STRANGER = UUID(int=3703)
START = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
ROME = timezone(timedelta(hours=2))
CLIENT = "2026-10-04T09:00:00+02:00"
READ_ONLY = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
SELECTED = frozenset(
    {
        "created_at",
        "completed_at",
        "asked_at",
        "answered_at",
        "answer_kind",
        "version_number",
        "decided_at",
        "status",
        "revision_kind",
        "code",
        "version",
        "retired_at",
        "started_at",
        "finished_at",
        "recorded_at",
        "decision",
        "decision_kind",
        "target",
        "action",
        "occurred_at",
        "gate_type",
        "kind",
        "artifact_version",
        "acted",
        "aligned",
        "id",
        "task_id",
        "purpose",
        "generation_id",
        "failure_code",
        "role",
    }
)


def at(seconds):
    return START + timedelta(seconds=seconds)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self.rows)


class Store:
    def __init__(self, tables=None, *, padding=0):
        self.tables = tables or {}
        self.rows = []
        self.padding = padding
        self.sessions = 0
        self.statements = []
        self.owned = []


class Transaction:
    def __init__(self, store):
        self.store = store

    async def __aenter__(self):
        self.before = list(self.store.rows)
        return self

    async def __aexit__(self, kind, error, trace):
        if error is not None:
            self.store.rows = self.before


class Session:
    def __init__(self, store):
        self.store = store
        self.open = False

    async def __aenter__(self):
        self.open = True
        return self

    async def __aexit__(self, kind, error, trace):
        self.open = False

    def begin(self):
        return Transaction(self.store)

    async def execute(self, statement):
        assert self.open
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.store.statements.append((statement, sql))
        found = sorted((sql.find(key), key) for key in self.store.tables if key in sql)
        return Result(self.store.tables[found[0][1]] if found else [])


class Journal:
    def __init__(self, store, session, *, owner_user_id):
        assert isinstance(session, Session) and session.store is store
        self.store, self.session, self.owner = store, session, owner_user_id
        self.locked = False

    async def owned(self, project_id, *, lock=False):
        assert self.session.open
        self.store.owned.append(lock)
        self.locked = lock
        return self.owner == OWNER and project_id == PROJECT

    async def rows(self, project_id):
        assert self.session.open and project_id == PROJECT
        return [dict(row) for row in self.store.rows]

    async def count(self, project_id):
        assert self.session.open and project_id == PROJECT
        return self.store.padding + len(self.store.rows)

    async def append(self, project_id, rows, *, received_at):
        assert self.session.open and self.locked and project_id == PROJECT
        for row in rows:
            sequence = len(self.store.rows) + 1
            self.store.rows.append({**row, "sequence": sequence, "received_at": received_at})
        return len(rows)


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


def service(store, clock=None):
    def sessions():
        store.sessions += 1
        return Session(store)

    def journal(session, *, owner_user_id):
        return Journal(store, session, owner_user_id=owner_user_id)

    return SqlAlchemyProjectActivityService(
        sessions, clock=clock or Clock(), journal_factory=journal
    )


def call(runtime, method, *, owner=OWNER, project=PROJECT, **values):
    return asyncio.run(getattr(runtime, method)(owner_user_id=owner, project_id=project, **values))


def refused(runtime, method, **values):
    with pytest.raises(ActivityError) as raised:
        call(runtime, method, **values)
    return raised.value.code


def web(kind, seconds, **values):
    return {"kind": kind, "client_at": at(seconds).isoformat(), **values}


def batch(*events, code="SES-P01", source="WEB"):
    return {"session_code": code, "source": source, "events": list(events)}


def session_row(sequence, kind, seconds, **values):
    return {
        "sequence": sequence,
        "session_code": "SES-P01",
        "source": "STUDIO",
        "kind": kind,
        "section": None,
        "target": None,
        "client_at": None,
        "received_at": at(seconds),
        "duration_ms": None,
        "status": None,
        **values,
    }


BATCH = batch(web("SECTION_OPENED", 1, section="BRIEF"))


def test_a_session_starts_under_the_project_lock_in_one_sql_session():
    store = Store()
    runtime = service(store, Clock(at(5).astimezone(ROME)))

    started = call(runtime, "start_session", session_code="SES-P01")

    assert started == {
        "status": "ACTIVITY_SESSION_STARTED",
        "session": {"code": "SES-P01", "started_at": at(5).isoformat()},
    }
    assert store.rows == [
        {
            "session_code": "SES-P01",
            "source": "STUDIO",
            "kind": "SESSION_STARTED",
            "section": None,
            "target": None,
            "client_at": None,
            "duration_ms": None,
            "status": None,
            "sequence": 1,
            "received_at": at(5),
        }
    ]
    assert (store.sessions, store.owned, store.statements) == (1, [True], [])
    assert call(runtime, "session") == {"active": True, "session": started["session"]}
    assert refused(runtime, "start_session", session_code="SES-P02") == "ACTIVITY_SESSION_ACTIVE"
    assert len(store.rows) == 1
    assert (store.sessions, store.owned) == (3, [True, False, True])


def test_an_ended_session_frees_the_project_but_its_code_cannot_return():
    store, clock = Store(), Clock(at(0))
    runtime = service(store, clock)
    assert call(runtime, "session") == {"active": False, "session": None}
    call(runtime, "start_session", session_code="SES-P01")
    clock.now = at(60)

    ended = call(runtime, "end_session", session_code="SES-P01")

    assert ended == {
        "status": "ACTIVITY_SESSION_ENDED",
        "session": {
            "code": "SES-P01",
            "started_at": at(0).isoformat(),
            "ended_at": at(60).isoformat(),
        },
    }
    assert [(row["kind"], row["received_at"]) for row in store.rows] == [
        ("SESSION_STARTED", at(0)),
        ("SESSION_ENDED", at(60)),
    ]
    assert call(runtime, "session") == {"active": False, "session": None}
    assert refused(runtime, "end_session", session_code="SES-P01") == "ACTIVITY_SESSION_NOT_ACTIVE"
    assert refused(runtime, "start_session", session_code="SES-P01") == (
        "ACTIVITY_SESSION_CODE_USED"
    )
    call(runtime, "start_session", session_code="SES-P02")
    assert refused(runtime, "end_session", session_code="SES-P01") == "ACTIVITY_SESSION_NOT_ACTIVE"
    assert [row["session_code"] for row in store.rows] == ["SES-P01", "SES-P01", "SES-P02"]
    assert store.owned == [False, True, True, False, True, True, True, True]


def test_events_are_recorded_only_inside_the_active_session_of_their_code():
    store = Store()
    runtime = service(store, Clock(at(30)))
    events = batch(
        web("SECTION_OPENED", 1, section="BRIEF"),
        web("DETAIL_OPENED", 2, section="BRIEF", target="brief-goals"),
    )
    assert refused(runtime, "append_events", request=events) == "ACTIVITY_SESSION_NOT_ACTIVE"
    call(runtime, "start_session", session_code="SES-P01")
    other = {**events, "session_code": "SES-P02"}
    assert refused(runtime, "append_events", request=other) == "ACTIVITY_SESSION_NOT_ACTIVE"

    recorded = call(runtime, "append_events", request=events)

    assert recorded == {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 2}
    common = {"session_code": "SES-P01", "source": "WEB", "duration_ms": None, "status": None}
    assert store.rows[1:] == [
        {
            **common,
            "kind": "SECTION_OPENED",
            "section": "BRIEF",
            "target": None,
            "client_at": at(1).isoformat(),
            "sequence": 2,
            "received_at": at(30),
        },
        {
            **common,
            "kind": "DETAIL_OPENED",
            "section": "BRIEF",
            "target": "brief-goals",
            "client_at": at(2).isoformat(),
            "sequence": 3,
            "received_at": at(30),
        },
    ]
    command = {
        "kind": "COMMAND_FINISHED",
        "client_at": CLIENT,
        "target": "design",
        "status": "0",
        "duration_ms": 1200,
    }
    assert call(runtime, "append_events", request=batch(command, source="UT"))["recorded"] == 1
    assert (store.rows[-1]["source"], store.rows[-1]["client_at"]) == (
        "UT",
        "2026-10-04T07:00:00+00:00",
    )
    assert store.owned == [True, True, True, True, True]


INVALID = {
    "start-lowercase": ("start_session", {"session_code": "ses-p01"}),
    "start-with-a-name": ("start_session", {"session_code": "SES-MARIO.ROSSI"}),
    "start-without-code": ("start_session", {"session_code": None}),
    "end-with-spaces": ("end_session", {"session_code": "SES-P01 "}),
    "events-with-other-keys": ("append_events", {"request": {**BATCH, "note": "typed text"}}),
    "events-not-an-object": ("append_events", {"request": [BATCH]}),
    "events-missing-body": ("append_events", {"request": None}),
    "events-without-code": ("append_events", {"request": {"source": "WEB", "events": []}}),
    "events-from-the-studio": ("append_events", {"request": {**BATCH, "source": "STUDIO"}}),
    "events-empty-batch": ("append_events", {"request": {**BATCH, "events": []}}),
    "events-free-text": (
        "append_events",
        {"request": batch(web("DETAIL_OPENED", 1, target="Mario Rossi"))},
    ),
}


@pytest.mark.parametrize("method,values", list(INVALID.values()), ids=list(INVALID))
def test_invalid_requests_are_refused_before_any_sql_session(method, values):
    store = Store()

    assert refused(service(store), method, **values) == "ACTIVITY_INPUT_INVALID"
    assert (store.sessions, store.rows, store.owned) == (0, [], [])


def test_the_journal_never_grows_beyond_its_limit():
    store = Store(padding=MAX_JOURNAL_EVENTS - 3)
    runtime = service(store)
    call(runtime, "start_session", session_code="SES-P01")
    three = batch(web("PAGE_HIDDEN", 1), web("PAGE_VISIBLE", 2), web("PAGE_HIDDEN", 3))

    assert refused(runtime, "append_events", request=three) == "ACTIVITY_JOURNAL_FULL"
    two = batch(web("PAGE_HIDDEN", 1), web("PAGE_VISIBLE", 2))
    assert call(runtime, "append_events", request=two)["recorded"] == 2
    assert store.padding + len(store.rows) == MAX_JOURNAL_EVENTS
    one = batch(web("PAGE_HIDDEN", 4))
    assert refused(runtime, "append_events", request=one) == "ACTIVITY_JOURNAL_FULL"
    assert call(runtime, "end_session", session_code="SES-P01")["status"] == (
        "ACTIVITY_SESSION_ENDED"
    )
    assert refused(runtime, "start_session", session_code="SES-P02") == "ACTIVITY_JOURNAL_FULL"
    assert store.padding + len(store.rows) == MAX_JOURNAL_EVENTS + 1


@pytest.mark.parametrize("owner,project", [(STRANGER, PROJECT), (OWNER, UUID(int=3799))])
def test_other_owners_and_unknown_projects_are_not_found(owner, project):
    store = Store()
    runtime = service(store)
    call(runtime, "start_session", session_code="SES-P01")
    scope = {"owner": owner, "project": project}

    assert call(runtime, "current", **scope) is None
    assert call(runtime, "session", **scope) is None
    for method, values in (
        ("start_session", {"session_code": "SES-P02"}),
        ("end_session", {"session_code": "SES-P01"}),
        ("append_events", {"request": BATCH}),
    ):
        assert refused(runtime, method, **scope, **values) == "PROJECT_NOT_FOUND"
    assert [row["kind"] for row in store.rows] == ["SESSION_STARTED"]
    assert [sql for _statement, sql in store.statements] == [READ_ONLY]


def generation(identifier, task_id, seconds, purpose=None, *, zone=UTC):
    return {
        "id": identifier,
        "task_id": task_id,
        "recorded_at": at(seconds).astimezone(zone).isoformat(),
        "purpose": purpose,
    }


def stored(identifier, kind, seconds, **values):
    return {
        "generation_id": identifier,
        "kind": kind,
        "recorded_at": at(seconds).isoformat(),
        "status": None,
        "failure_code": None,
        "code": None,
        "role": None,
        **values,
    }


def gate(seconds, gate_type, kind, version, *, acted=True, aligned=None):
    return {
        "occurred_at": at(seconds),
        "gate_type": gate_type,
        "kind": kind,
        "artifact_version": version,
        "acted": acted,
        "aligned": aligned,
    }


G = [UUID(int=3800 + number) for number in range(7)]
TABLES = {
    "FROM projects": [{"created_at": at(0)}],
    "FROM brief_dialogues": [{"created_at": at(10), "completed_at": at(90)}],
    "FROM brief_dialogue_turns": [
        {"asked_at": at(20), "answered_at": at(32.5), "answer_kind": "UNKNOWN"},
        {"asked_at": at(40), "answered_at": None, "answer_kind": None},
    ],
    "FROM project_brief_versions": [{"created_at": at(100), "version_number": 1}],
    "FROM brief_assumptions": [{"decided_at": at(110), "status": "ACCEPTED"}],
    "FROM team_proposals": [
        {"created_at": at(200), "version_number": 1, "revision_kind": "PROPOSER_GENERATED"},
        {"created_at": at(210), "version_number": 2, "revision_kind": "OWNER_EDITED"},
    ],
    "FROM persona_profile_versions": [{"created_at": at(300), "version_number": 1}],
    "FROM user_modeling_snapshot_versions": [{"created_at": at(310), "version_number": 1}],
    "FROM user_twin_profile_diffs": [
        {"created_at": at(320), "decided_at": at(330), "status": "APPROVED"}
    ],
    "FROM twin_conversation_turns": [{"created_at": at(340)}],
    "FROM research_evidence_versions": [
        {"code": "EVD-001", "version": 1, "created_at": at(350).isoformat()},
        {"code": "EVD-001", "version": 2, "created_at": at(355).astimezone(ROME).isoformat()},
    ],
    "DISTINCT ON (research_evidence_versions.id)": [
        {"code": "EVD-001", "version": 2, "retired_at": at(360)}
    ],
    "FROM requirements_specification_versions": [{"created_at": at(400), "version_number": 1}],
    "FROM requirements_specification_diffs": [
        {"created_at": at(410), "decided_at": None, "status": "PROPOSED"}
    ],
    "FROM design_package_versions": [{"created_at": at(500), "version_number": 1}],
    "FROM design_package_diffs": [
        {"created_at": at(510), "decided_at": at(515), "status": "REJECTED"}
    ],
    "FROM design_evaluation_runs": [{"started_at": at(520), "completed_at": at(545.25)}],
    "FROM design_finding_validations": [{"decided_at": at(550), "decision": "CONFIRMED"}],
    "FROM design_discussions": [{"created_at": at(560), "decided_at": at(580)}],
    "FROM design_discussion_rounds": [{"created_at": at(570)}],
    "FROM insight_applications": [{"created_at": at(590)}],
    "FROM project_validation_hypotheses": [
        {"created_at": at(600), "code": "HYP-001", "version_number": 2}
    ],
    "FROM project_validation_outcomes": [{"recorded_at": at(610), "code": "HVO-001"}],
    "FROM project_workflow_decisions": [
        {"recorded_at": at(620), "target": "EVIDENCE", "action": "DECLARE_MISSING"},
        {"recorded_at": at(625), "target": "JOURNEYS", "action": "RESOLVE_MISSING"},
        {"recorded_at": at(626), "target": "PACKAGE", "action": "DECLARE_MISSING"},
    ],
    "FROM project_provided_prototypes": [{"created_at": at(630)}],
    "FROM knowledge_package_versions": [{"created_at": at(700), "version_number": 1}],
    "FROM project_code_changes": [
        {"recorded_at": at(710), "decided_at": at(720), "decision_kind": "ALIGNED"}
    ],
    "FROM acceptance_test_runs": [
        {"recorded_at": at(740), "started_at": at(725), "finished_at": at(735)}
    ],
    "FROM twin_updates": [{"created_at": at(750), "decided_at": at(760), "status": "APPROVED"}],
    "FROM human_gate_events": [
        gate(120, "PROJECT_BRIEF", "SUBMIT", 1),
        gate(130, "PROJECT_BRIEF", "APPROVE", 1, aligned=False),
        gate(515, "DESIGN", "ARTIFACT_SUPERSEDED", 1, acted=False),
        gate(420, "REQUIREMENTS", "APPROVE", 2, aligned=True),
    ],
    "FROM model_proposal_generations": [
        generation(G[1], "proposal-team-v1", 190, zone=ROME),
        generation(G[2], "proposal-design-v1", 480, "DESIGN_MOCKUP"),
        generation(G[3], "proposal-design-v1", 485, "DESIGN_MOCKUP"),
        generation(G[4], "proposal-user-twin-evaluation-v1", 730, "TEST_REVIEW"),
        generation(G[5], "proposal-user-twin-evaluation-v1", 731),
        generation(G[6], "proposal-brief-dialogue-v1", 15, "BRIEF_QUESTION"),
    ],
    "FROM model_proposal_generation_events": [
        stored(G[6], "PROVIDER_RESULT", 16, status="FAILED"),
        stored(G[1], "HTTP_RESPONSE", 219),
        stored(G[1], "PROVIDER_RESULT", 220, status="SUCCEEDED"),
        stored(G[2], "PROVIDER_RESULT", 490, status="SUCCEEDED"),
        stored(G[2], "ADAPTER_REJECTED", 491, code="MOCKUP_NOT_ACCESSIBLE"),
        stored(
            G[2],
            "APPLICATION_RESULT",
            492,
            status="MOCKUP_NOT_ACCESSIBLE",
            role="MOCKUP_ATTEMPT",
        ),
        stored(G[3], "PROVIDER_RESULT", 495.5, status="FAILED", failure_code="TIMEOUT"),
        stored(G[4], "PROVIDER_RESULT", 733, status="SUCCEEDED"),
        stored(G[4], "APPLICATION_RESULT", 734, status="RECORDED"),
    ],
}


def fact(seconds, section, kind, actor, **values):
    fields = ("code", "version_number", "duration_ms", "outcome", "purpose", "role")
    return (at(seconds).isoformat(), section, kind, actor, *(values.get(key) for key in fields))


EXPECTED = [
    fact(0, "BRIEF", "PROJECT_CREATED", "OWNER"),
    fact(10, "BRIEF", "BRIEF_DIALOGUE_STARTED", "OWNER"),
    fact(
        15,
        "BRIEF",
        "GENERATION",
        "MODEL",
        duration_ms=1000,
        outcome="FAILED",
        purpose="BRIEF_QUESTION",
    ),
    fact(20, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
    fact(32.5, "BRIEF", "BRIEF_QUESTION_ANSWERED", "OWNER", duration_ms=12500, outcome="UNKNOWN"),
    fact(40, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
    fact(90, "BRIEF", "BRIEF_DIALOGUE_COMPLETED", "STUDIO"),
    fact(100, "BRIEF", "BRIEF_VERSION_SAVED", "OWNER", version_number=1),
    fact(110, "BRIEF", "BRIEF_ASSUMPTION_DECIDED", "OWNER", outcome="ACCEPTED"),
    fact(120, "BRIEF", "GATE_SUBMITTED", "OWNER", version_number=1),
    fact(130, "BRIEF", "GATE_APPROVED", "OWNER", version_number=1),
    fact(
        190, "TEAM", "GENERATION", "MODEL", duration_ms=30000, outcome="SUCCEEDED", purpose="team"
    ),
    fact(
        200,
        "TEAM",
        "TEAM_VERSION_SAVED",
        "MODEL",
        version_number=1,
        outcome="PROPOSER_GENERATED",
    ),
    fact(210, "TEAM", "TEAM_VERSION_SAVED", "OWNER", version_number=2, outcome="OWNER_EDITED"),
    fact(300, "USER_TWINS", "ARCHETYPE_VERSION_SAVED", "STUDIO", version_number=1),
    fact(310, "USER_TWINS", "TWINS_VERSION_SAVED", "STUDIO", version_number=1),
    fact(320, "USER_TWINS", "TWIN_REVISION_PROPOSED", "OWNER"),
    fact(330, "USER_TWINS", "TWIN_REVISION_DECIDED", "OWNER", outcome="APPROVED"),
    fact(340, "USER_TWINS", "TWIN_CHAT_TURN", "OWNER"),
    fact(350, "USER_TWINS", "EVIDENCE_ADDED", "OWNER", code="EVD-001", version_number=1),
    fact(355, "USER_TWINS", "EVIDENCE_ADDED", "OWNER", code="EVD-001", version_number=2),
    fact(360, "USER_TWINS", "EVIDENCE_RETIRED", "OWNER", code="EVD-001", version_number=2),
    fact(400, "REQUIREMENTS", "DEFINITION_VERSION_SAVED", "STUDIO", version_number=1),
    fact(410, "REQUIREMENTS", "DEFINITION_CHANGE_PROPOSED", "OWNER"),
    fact(420, "REQUIREMENTS", "GATE_APPROVED", "STUDIO", version_number=2, outcome="ALIGNED"),
    fact(
        480,
        "DESIGN",
        "GENERATION",
        "MODEL",
        duration_ms=12000,
        outcome="MOCKUP_NOT_ACCESSIBLE",
        purpose="DESIGN_MOCKUP",
        role="MOCKUP_ATTEMPT",
    ),
    fact(
        485,
        "DESIGN",
        "GENERATION",
        "MODEL",
        duration_ms=10500,
        outcome="TIMEOUT",
        purpose="DESIGN_MOCKUP",
    ),
    fact(500, "DESIGN", "DESIGN_VERSION_SAVED", "STUDIO", version_number=1),
    fact(510, "DESIGN", "DESIGN_CHANGE_PROPOSED", "OWNER"),
    fact(515, "DESIGN", "DESIGN_CHANGE_DECIDED", "OWNER", outcome="REJECTED"),
    fact(515, "DESIGN", "GATE_SUPERSEDED", "STUDIO", version_number=1),
    fact(545.25, "DESIGN", "EVALUATION_RUN_COMPLETED", "STUDIO", duration_ms=25250),
    fact(550, "DESIGN", "FINDING_DECIDED", "OWNER", outcome="CONFIRMED"),
    fact(560, "DESIGN", "DISCUSSION_OPENED", "OWNER"),
    fact(570, "DESIGN", "DISCUSSION_ROUND_COMPLETED", "STUDIO"),
    fact(580, "DESIGN", "DISCUSSION_DECIDED", "OWNER"),
    fact(590, "DESIGN", "INSIGHT_APPLIED", "OWNER"),
    fact(600, "DESIGN", "HYPOTHESIS_SAVED", "OWNER", code="HYP-001", version_number=2),
    fact(610, "DESIGN", "OUTCOME_RECORDED", "OWNER", code="HVO-001"),
    fact(620, "USER_TWINS", "GAP_DECLARED", "OWNER"),
    fact(625, "REQUIREMENTS", "GAP_RESOLVED", "OWNER"),
    fact(626, "PACKAGE", "GAP_DECLARED", "OWNER"),
    fact(630, "DESIGN", "PROTOTYPE_PROVIDED", "OWNER"),
    fact(700, "PACKAGE", "PACKAGE_PUBLISHED", "OWNER", version_number=1),
    fact(710, "PACKAGE", "CODE_CHANGE_RECORDED", "OWNER"),
    fact(720, "PACKAGE", "CODE_CHANGE_DECIDED", "OWNER", outcome="ALIGNED"),
    fact(
        730,
        "PACKAGE",
        "GENERATION",
        "MODEL",
        duration_ms=4000,
        outcome="SUCCEEDED",
        purpose="TEST_REVIEW",
    ),
    fact(731, "DESIGN", "GENERATION", "MODEL", purpose="user-twin-evaluation"),
    fact(740, "PACKAGE", "TEST_RUN_RECORDED", "OWNER", duration_ms=10000),
    fact(750, "USER_TWINS", "TWIN_UPDATE_PROPOSED", "OWNER"),
    fact(760, "USER_TWINS", "TWIN_UPDATE_DECIDED", "OWNER", outcome="APPROVED"),
]
JOURNAL = [
    session_row(1, "SESSION_STARTED", 5),
    session_row(
        2,
        "SECTION_OPENED",
        7,
        source="WEB",
        section="BRIEF",
        client_at=at(6).isoformat(),
    ),
    session_row(3, "PAGE_HIDDEN", 67, source="WEB", section="BRIEF", client_at=at(66).isoformat()),
    session_row(4, "SESSION_ENDED", 70),
]


def server(document):
    return [
        (
            event["at"],
            event["section"],
            event["kind"],
            event["actor"],
            event["code"],
            event["version_number"],
            event["duration_ms"],
            event["outcome"],
            event["purpose"],
            event["role"],
        )
        for event in document["events"]
        if event["source"] == "SERVER"
    ]


def section(document, key):
    return next(item for item in document["sections"] if item["key"] == key)


def test_the_activity_reads_every_table_without_a_lock_and_keeps_only_codes():
    store = Store(TABLES)
    store.rows = [dict(row) for row in JOURNAL]

    document = call(service(store), "current")

    assert server(document) == EXPECTED
    assert (store.sessions, store.owned) == (1, [False])
    sqls = [sql for _statement, sql in store.statements]
    assert sqls[0] == READ_ONLY
    assert not any("FOR UPDATE" in sql for sql in sqls)
    assert all(any(key in sql for sql in sqls) for key in TABLES)
    selected = {
        column.key
        for statement, _sql in store.statements
        if isinstance(statement, sa.Select)
        for column in statement.selected_columns
    }
    assert selected <= SELECTED
    assert len(store.statements) == 33
    assert [item["key"] for item in document["sections"]] == list(SECTIONS)
    brief, requirements = section(document, "BRIEF"), section(document, "REQUIREMENTS")
    assert (brief["first_approved_at"], brief["elapsed_seconds"], brief["owner_actions"]) == (
        at(130).isoformat(),
        130.0,
        7,
    )
    assert (requirements["approved_at"], requirements["elapsed_seconds"]) == (
        at(420).isoformat(),
        20.0,
    )
    assert brief["gate"] == {
        "submissions": 1,
        "approvals": 1,
        "revision_requests": 0,
        "rejections": 0,
    }
    assert {key: section(document, key)["generations"] for key in SECTIONS} == {
        "BRIEF": {"count": 1, "succeeded": 0, "failed": 1, "retries": 0, "wait_seconds": 1.0},
        "TEAM": {"count": 1, "succeeded": 1, "failed": 0, "retries": 0, "wait_seconds": 30.0},
        "USER_TWINS": {"count": 0, "succeeded": 0, "failed": 0, "retries": 0, "wait_seconds": 0.0},
        "REQUIREMENTS": {
            "count": 0,
            "succeeded": 0,
            "failed": 0,
            "retries": 0,
            "wait_seconds": 0.0,
        },
        "DESIGN": {"count": 3, "succeeded": 0, "failed": 3, "retries": 1, "wait_seconds": 22.5},
        "PACKAGE": {"count": 1, "succeeded": 1, "failed": 0, "retries": 0, "wait_seconds": 4.0},
    }
    assert document["brief_dialogue"] == {
        "questions": 2,
        "answered": 1,
        "unknown_answers": 1,
        "answer_seconds": [12.5],
    }
    assert document["sessions"] == [
        {
            "code": "SES-P01",
            "started_at": at(5).isoformat(),
            "ended_at": at(70).isoformat(),
            "events": 4,
            "sources": ["STUDIO", "WEB"],
            "discarded_intervals": 0,
        }
    ]
    assert brief["journal"]["dwell_seconds"] == 60.0
    assert (document["totals"]["generations"], document["totals"]["generation_wait_seconds"]) == (
        6,
        57.5,
    )
    assert "CLIENT_CLOCK_NOT_VERIFIED" in document["limits"]


def test_the_activity_of_an_empty_project_has_only_its_creation():
    store = Store({"FROM projects": [{"created_at": at(0)}]})

    document = call(service(store), "current")

    assert server(document) == [fact(0, "BRIEF", "PROJECT_CREATED", "OWNER")]
    assert (document["sessions"], document["totals"]["events"]) == ([], 1)


def one_generation(task_id, purpose, events=()):
    identifier = UUID(int=3900)
    store = Store(
        {
            "FROM model_proposal_generations": [generation(identifier, task_id, 0, purpose)],
            "FROM model_proposal_generation_events": [
                stored(identifier, kind, seconds, **values) for kind, seconds, values in events
            ],
        }
    )
    [event] = call(service(store), "current")["events"]
    return event


SECTION_CASES = [
    ("proposal-requirements-v1", "TEST_PLAN", "PACKAGE", "TEST_PLAN"),
    ("proposal-requirements-v1", None, "REQUIREMENTS", "requirements"),
    ("proposal-requirements-v1", "REQUIREMENTS_CHANGE", "REQUIREMENTS", "REQUIREMENTS_CHANGE"),
    ("proposal-user-twin-evaluation-v1", "TWIN_UPDATE", "USER_TWINS", "TWIN_UPDATE"),
    (
        "proposal-user-twin-evaluation-v1",
        "TWIN_EVIDENCE_UPDATE",
        "USER_TWINS",
        "TWIN_EVIDENCE_UPDATE",
    ),
    ("proposal-user-twin-evaluation-v1", "DESIGN_TWIN_REVIEW", "DESIGN", "DESIGN_TWIN_REVIEW"),
    ("proposal-user-twin-evaluation-v1", "CODE_CHANGE_REVIEW", "PACKAGE", "CODE_CHANGE_REVIEW"),
    ("proposal-user-twin-evaluation-v1", "CODE_ALIGNMENT", "PACKAGE", "CODE_ALIGNMENT"),
    ("proposal-requirements-v1", "KNOWLEDGE_ALIGNMENT", "PACKAGE", "KNOWLEDGE_ALIGNMENT"),
    ("proposal-design-v1", "DESIGN_CHANGE", "DESIGN", "DESIGN_CHANGE"),
    ("proposal-user-twin-evaluation-v1", "NEW_PURPOSE", "DESIGN", "NEW_PURPOSE"),
    ("proposal-personas-v1", None, "USER_TWINS", "personas"),
    ("proposal-user-twins-v1", "", "USER_TWINS", "user-twins"),
    ("proposal-twin-chat-v1", "TWIN_CHAT", "USER_TWINS", "TWIN_CHAT"),
    ("proposal-twin-discussion-v1", "TWIN_STATEMENT", "DESIGN", "TWIN_STATEMENT"),
    ("proposal-twin-discussion-v1", "DISCUSSION_SYNTHESIS", "DESIGN", "DISCUSSION_SYNTHESIS"),
    ("proposal-brief-dialogue-v1", "BRIEF_SYNTHESIS", "BRIEF", "BRIEF_SYNTHESIS"),
    ("proposal-team-v1", None, "TEAM", "team"),
    ("proposal-design-v1", "DESIGN_DIRECTIONS", "DESIGN", "DESIGN_DIRECTIONS"),
    ("proposal-design-v1", None, "DESIGN", "design"),
    ("unversioned-task", None, "DESIGN", "unversioned-task"),
]


@pytest.mark.parametrize("task_id,purpose,expected,shown", SECTION_CASES)
def test_generation_sections_follow_the_purpose_then_the_task(task_id, purpose, expected, shown):
    event = one_generation(task_id, purpose)

    assert (event["section"], event["purpose"], event["actor"]) == (expected, shown, "MODEL")


OUTCOME_CASES = {
    "no-event-yet": ([], None, None, None),
    "succeeded": ([("PROVIDER_RESULT", 2, {"status": "SUCCEEDED"})], "SUCCEEDED", None, 2000),
    "failure-code": (
        [
            ("PROVIDER_RESULT", 3, {"status": "FAILED", "failure_code": "RATE_LIMITED"}),
            ("APPLICATION_RESULT", 4, {"status": "RATE_LIMITED", "role": "PROVIDER_RETRY"}),
        ],
        "RATE_LIMITED",
        "PROVIDER_RETRY",
        4000,
    ),
    "failure-without-code": ([("PROVIDER_RESULT", 1, {"status": "FAILED"})], "FAILED", None, 1000),
    "discarded-answer": (
        [
            ("PROVIDER_RESULT", 1, {"status": "SUCCEEDED"}),
            ("ADAPTER_REJECTED", 1.5, {"code": "DESIGN_PROPOSAL_INVALID"}),
        ],
        "DESIGN_PROPOSAL_INVALID",
        None,
        1500,
    ),
    "transport-only": ([("TRANSPORT_ERROR", 9, {"code": "ReadTimeout"})], None, None, 9000),
}


@pytest.mark.parametrize(
    "events,outcome,role,duration", list(OUTCOME_CASES.values()), ids=list(OUTCOME_CASES)
)
def test_generation_outcome_role_and_wait_follow_the_recorded_events(
    events, outcome, role, duration
):
    event = one_generation("proposal-design-v1", "DESIGN_MOCKUP_HTML", events)

    assert (event["outcome"], event["role"], event["duration_ms"]) == (outcome, role, duration)


@pytest.mark.parametrize(
    "tables",
    [
        {"FROM projects": [{"created_at": datetime(2026, 10, 4, 8, 0)}]},
        {"FROM research_evidence_versions": [{"code": "EVD-001", "version": 1, "created_at": "x"}]},
        {"FROM model_proposal_generations": [generation(G[0], "proposal-team-v1", 0)]}
        | {
            "FROM model_proposal_generation_events": [
                stored(G[0], "HTTP_RESPONSE", 1) | {"recorded_at": "2026-10-04T08:00:01"}
            ]
        },
    ],
    ids=["naive-column", "evidence-instant-not-iso", "event-without-zone"],
)
def test_stored_instants_without_a_zone_are_invalid_records(tables):
    with pytest.raises(ActivityError) as raised:
        call(service(Store(tables)), "current")

    assert raised.value.code == "ACTIVITY_RECORDS_INVALID"


def test_the_default_journal_is_the_repository_of_the_contract():
    runtime = SqlAlchemyProjectActivityService(object())
    session = object()
    journal = runtime._journal(session, owner_user_id=OWNER)

    assert runtime._journal is SqlAlchemyUsageJournalRepository
    assert (journal.session, journal.owner_user_id) == (session, OWNER)
