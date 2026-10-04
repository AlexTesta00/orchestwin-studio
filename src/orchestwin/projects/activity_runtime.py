from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.activity import (
    MAX_JOURNAL_EVENTS,
    ActivityError,
    active_session,
    journal_rows,
    project_activity,
    validate_session_code,
)
from orchestwin.agents.persistence.models import TeamProposalVersionRecord
from orchestwin.artifacts.design_discussion_persistence import DISCUSSIONS, ROUNDS
from orchestwin.artifacts.design_evaluation_persistence import RUNS
from orchestwin.artifacts.design_finding_validation_persistence import VALIDATIONS
from orchestwin.artifacts.design_persistence import PACKAGE_DIFFS
from orchestwin.artifacts.design_persistence import PACKAGE_VERSIONS as DESIGN_VERSIONS
from orchestwin.artifacts.human_validation_persistence import HYPOTHESES, OUTCOMES
from orchestwin.artifacts.workflow_inputs_persistence import DECISIONS, PROTOTYPES
from orchestwin.knowledge.package_persistence import PACKAGE_VERSIONS as FOLDER_VERSIONS
from orchestwin.models.proposal_evidence_persistence import _TASK_ID, EVENTS, _owned_generation
from orchestwin.projects.persistence.acceptance_tests import TEST_RUNS
from orchestwin.projects.persistence.brief_dialogue import DIALOGUES, TURNS
from orchestwin.projects.persistence.code_changes import CHANGES as CODE_CHANGES
from orchestwin.projects.persistence.insight_applications import APPLICATIONS
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.projects.persistence.progress import GATES
from orchestwin.projects.persistence.research_evidence import VERSIONS as EVIDENCE
from orchestwin.projects.persistence.twin_learning import UPDATES
from orchestwin.projects.persistence.usage_journal import SqlAlchemyUsageJournalRepository
from orchestwin.projects.requirements_persistence import DIFFS as DEFINITION_DIFFS
from orchestwin.projects.requirements_persistence import SPECIFICATIONS
from orchestwin.projects.sections_service import ALIGNMENT_REASON, FOLDER_STAGE_KEYS
from orchestwin.twins.persistence.conversations import TWIN_CONVERSATION_TURNS, TWIN_CONVERSATIONS
from orchestwin.twins.persistence.repositories import (
    PERSONA_PROFILE_VERSIONS,
    USER_MODELING_SNAPSHOT_VERSIONS,
)
from orchestwin.twins.revision_persistence import DIFFS as TWIN_DIFFS
from orchestwin.workflow.gates import HumanGateEventKind
from orchestwin.workflow.persistence.models import HumanGateEventRecord, HumanGateRecord

_READ_ONLY: Final = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
_RECORDS_INVALID: Final = "ACTIVITY_RECORDS_INVALID"
_REQUEST_KEYS: Final = frozenset({"session_code", "source", "events"})
_OWNER_REVISIONS: Final = frozenset({"OWNER_EDITED", "OWNER_PROVIDED"})
_MILLISECOND: Final = timedelta(milliseconds=1)
_GATE_SECTIONS: Final = {
    gate.value: FOLDER_STAGE_KEYS[name.removesuffix("_gate")].value for name, gate in GATES.items()
}
_GATE_KINDS: Final = {
    HumanGateEventKind.SUBMIT: "GATE_SUBMITTED",
    HumanGateEventKind.APPROVE: "GATE_APPROVED",
    HumanGateEventKind.REJECT: "GATE_REJECTED",
    HumanGateEventKind.REQUEST_REVISION: "GATE_REVISION_REQUESTED",
    HumanGateEventKind.PAUSE: "GATE_PAUSED",
    HumanGateEventKind.RESUME: "GATE_RESUMED",
    HumanGateEventKind.CANCEL: "GATE_CANCELLED",
    HumanGateEventKind.ARTIFACT_SUPERSEDED: "GATE_SUPERSEDED",
}
_GAP_KINDS: Final = {"DECLARE_MISSING": "GAP_DECLARED", "RESOLVE_MISSING": "GAP_RESOLVED"}
_TARGET_SECTIONS: Final = {
    "EVIDENCE": "USER_TWINS",
    "SCENARIOS": "REQUIREMENTS",
    "NEEDS": "REQUIREMENTS",
    "JOURNEYS": "REQUIREMENTS",
    "EVALUATION": "DESIGN",
}
_PURPOSE_SECTIONS: Final = {
    "BRIEF_QUESTION": "BRIEF",
    "BRIEF_SYNTHESIS": "BRIEF",
    "TWIN_UPDATE": "USER_TWINS",
    "TWIN_EVIDENCE_UPDATE": "USER_TWINS",
    "TWIN_CHAT": "USER_TWINS",
    "REQUIREMENTS_CHANGE": "REQUIREMENTS",
    "TWIN_STATEMENT": "DESIGN",
    "DISCUSSION_SYNTHESIS": "DESIGN",
    "TEST_PLAN": "PACKAGE",
    "TEST_REVIEW": "PACKAGE",
    "CODE_CHANGE_REVIEW": "PACKAGE",
    "CODE_ALIGNMENT": "PACKAGE",
}
_TASK_SECTIONS: Final = {
    "brief-dialogue": "BRIEF",
    "team": "TEAM",
    "personas": "USER_TWINS",
    "user-twins": "USER_TWINS",
    "twin-chat": "USER_TWINS",
    "requirements": "REQUIREMENTS",
    "design": "DESIGN",
    "user-twin-evaluation": "DESIGN",
}


def _instant(value):
    try:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise ActivityError(_RECORDS_INVALID) from None
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise ActivityError(_RECORDS_INVALID)
    return moment


def _milliseconds(start, end):
    if start is None or end is None:
        return None
    start, end = _instant(start), _instant(end)
    return None if end < start else (end - start) // _MILLISECOND


def _fact(at, section, kind, actor, **fields):
    return {"at": _instant(at), "section": section, "kind": kind, "actor": actor, **fields}


def _when(column, section, kind, actor, *, code=None, version=None, outcome=None, duration=None):
    def build(rows):
        return [
            _fact(
                row[column],
                section,
                kind,
                actor,
                code=None if code is None else row[code],
                version_number=None if version is None else row[version],
                outcome=None if outcome is None else row[outcome],
                duration_ms=None if duration is None else _milliseconds(*map(row.get, duration)),
            )
            for row in rows
            if row[column] is not None
        ]

    return build


def _team(rows):
    return [
        _fact(
            row["created_at"],
            "TEAM",
            "TEAM_VERSION_SAVED",
            "OWNER" if row["revision_kind"] in _OWNER_REVISIONS else "MODEL",
            version_number=row["version_number"],
            outcome=row["revision_kind"],
        )
        for row in rows
    ]


def _gaps(rows):
    return [
        _fact(
            row["recorded_at"],
            _TARGET_SECTIONS.get(row["target"], row["target"]),
            _GAP_KINDS[row["action"]],
            "OWNER",
        )
        for row in rows
    ]


def _gates(rows):
    return [
        _fact(
            row["occurred_at"],
            _GATE_SECTIONS[row["gate_type"]],
            _GATE_KINDS[row["kind"]],
            "OWNER" if row["acted"] and not row["aligned"] else "STUDIO",
            version_number=row["artifact_version"],
            outcome="ALIGNED" if row["aligned"] else None,
        )
        for row in rows
    ]


def _generation_section(task, purpose):
    if purpose in _PURPOSE_SECTIONS:
        return _PURPOSE_SECTIONS[purpose]
    if purpose is not None and purpose.startswith("DESIGN_"):
        return "DESIGN"
    return _TASK_SECTIONS.get(task, "DESIGN")


def _generation_outcome(events):
    rejected = events.get("ADAPTER_REJECTED")
    if rejected is not None and rejected["code"]:
        return rejected["code"]
    result = events.get("PROVIDER_RESULT")
    if result is None:
        return None
    if result["status"] == "SUCCEEDED":
        return "SUCCEEDED"
    return result["failure_code"] or result["status"]


def _generations(generations, events):
    observed = {}
    for event in events:
        observed.setdefault(event["generation_id"], {})[event["kind"]] = event
    facts = []
    for generation in generations:
        seen = observed.get(generation["id"], {})
        at = _instant(generation["recorded_at"])
        last = max((_instant(event["recorded_at"]) for event in seen.values()), default=None)
        match = _TASK_ID.fullmatch(str(generation["task_id"]))
        task = match.group("task") if match else generation["task_id"]
        purpose = generation["purpose"] or None
        retired = seen.get("APPLICATION_RESULT")
        facts.append(
            _fact(
                at,
                _generation_section(task, purpose),
                "GENERATION",
                "MODEL",
                duration_ms=_milliseconds(at, last),
                outcome=_generation_outcome(seen),
                purpose=purpose or task,
                role=None if retired is None else retired["role"],
            )
        )
    return facts


def _generation_statements(owner_user_id, project_id):
    owned = _owned_generation(owner_user_id, project_id).subquery()
    context = sa.func.model_source_context(owned.c.snapshot_json)
    event = sa.cast(EVENTS.c.snapshot_json, JSONB)
    return (
        sa.select(
            owned.c.id,
            owned.c.task_id,
            sa.cast(owned.c.snapshot_json, JSONB)["recorded_at"].astext.label("recorded_at"),
            sa.func.coalesce(
                context.op("->>")("purpose"), context.op("->")("request").op("->>")("purpose")
            ).label("purpose"),
        ),
        sa.select(
            EVENTS.c.generation_id,
            EVENTS.c.kind,
            event["recorded_at"].astext.label("recorded_at"),
            event["payload"]["status"].astext.label("status"),
            event["payload"]["failure"]["code"].astext.label("failure_code"),
            event["payload"]["code"].astext.label("code"),
            event["payload"]["role"].astext.label("role"),
        ).join(owned, owned.c.id == EVENTS.c.generation_id),
    )


def _readers(owner_user_id, project_id):
    def owned(table, *names):
        return sa.select(*(table.c[name] for name in names)).where(
            table.c.project_id == project_id, table.c.owner_user_id == owner_user_id
        )

    def of_project(table, *names):
        return sa.select(*(table.c[name] for name in names)).where(table.c.project_id == project_id)

    return (
        (
            sa.select(ProjectRecord.created_at).where(
                ProjectRecord.id == project_id, ProjectRecord.owner_user_id == owner_user_id
            ),
            (_when("created_at", "BRIEF", "PROJECT_CREATED", "OWNER"),),
        ),
        (
            owned(DIALOGUES, "created_at", "completed_at"),
            (
                _when("created_at", "BRIEF", "BRIEF_DIALOGUE_STARTED", "OWNER"),
                _when("completed_at", "BRIEF", "BRIEF_DIALOGUE_COMPLETED", "STUDIO"),
            ),
        ),
        (
            sa.select(TURNS.c.asked_at, TURNS.c.answered_at, TURNS.c.answer_kind)
            .join(DIALOGUES, DIALOGUES.c.id == TURNS.c.dialogue_id)
            .where(
                DIALOGUES.c.project_id == project_id, DIALOGUES.c.owner_user_id == owner_user_id
            ),
            (
                _when("asked_at", "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
                _when(
                    "answered_at",
                    "BRIEF",
                    "BRIEF_QUESTION_ANSWERED",
                    "OWNER",
                    outcome="answer_kind",
                    duration=("asked_at", "answered_at"),
                ),
            ),
        ),
        (
            of_project(ProjectBriefVersionRecord.__table__, "created_at", "version_number"),
            (
                _when(
                    "created_at", "BRIEF", "BRIEF_VERSION_SAVED", "OWNER", version="version_number"
                ),
            ),
        ),
        (
            of_project(BriefAssumptionRecord.__table__, "decided_at", "status"),
            (_when("decided_at", "BRIEF", "BRIEF_ASSUMPTION_DECIDED", "OWNER", outcome="status"),),
        ),
        (
            of_project(
                TeamProposalVersionRecord.__table__, "created_at", "version_number", "revision_kind"
            ),
            (_team,),
        ),
        (
            of_project(PERSONA_PROFILE_VERSIONS, "created_at", "version_number"),
            (
                _when(
                    "created_at",
                    "USER_TWINS",
                    "ARCHETYPE_VERSION_SAVED",
                    "STUDIO",
                    version="version_number",
                ),
            ),
        ),
        (
            of_project(USER_MODELING_SNAPSHOT_VERSIONS, "created_at", "version_number"),
            (
                _when(
                    "created_at",
                    "USER_TWINS",
                    "TWINS_VERSION_SAVED",
                    "STUDIO",
                    version="version_number",
                ),
            ),
        ),
        (
            of_project(TWIN_DIFFS, "created_at", "decided_at", "status"),
            (
                _when("created_at", "USER_TWINS", "TWIN_REVISION_PROPOSED", "OWNER"),
                _when(
                    "decided_at", "USER_TWINS", "TWIN_REVISION_DECIDED", "OWNER", outcome="status"
                ),
            ),
        ),
        (
            sa.select(TWIN_CONVERSATION_TURNS.c.created_at)
            .join(
                TWIN_CONVERSATIONS,
                TWIN_CONVERSATIONS.c.id == TWIN_CONVERSATION_TURNS.c.conversation_id,
            )
            .where(
                TWIN_CONVERSATIONS.c.project_id == project_id,
                TWIN_CONVERSATIONS.c.owner_user_id == owner_user_id,
            ),
            (_when("created_at", "USER_TWINS", "TWIN_CHAT_TURN", "OWNER"),),
        ),
        (
            sa.select(
                EVIDENCE.c.code,
                EVIDENCE.c.version,
                EVIDENCE.c.metadata["created_at"].astext.label("created_at"),
            ).where(EVIDENCE.c.project_id == project_id, EVIDENCE.c.owner_user_id == owner_user_id),
            (
                _when(
                    "created_at",
                    "USER_TWINS",
                    "EVIDENCE_ADDED",
                    "OWNER",
                    code="code",
                    version="version",
                ),
            ),
        ),
        (
            owned(EVIDENCE, "code", "version", "retired_at")
            .distinct(EVIDENCE.c.id)
            .order_by(EVIDENCE.c.id, EVIDENCE.c.version.desc()),
            (
                _when(
                    "retired_at",
                    "USER_TWINS",
                    "EVIDENCE_RETIRED",
                    "OWNER",
                    code="code",
                    version="version",
                ),
            ),
        ),
        (
            of_project(SPECIFICATIONS, "created_at", "version_number"),
            (
                _when(
                    "created_at",
                    "REQUIREMENTS",
                    "DEFINITION_VERSION_SAVED",
                    "STUDIO",
                    version="version_number",
                ),
            ),
        ),
        (
            of_project(DEFINITION_DIFFS, "created_at", "decided_at", "status"),
            (
                _when("created_at", "REQUIREMENTS", "DEFINITION_CHANGE_PROPOSED", "OWNER"),
                _when(
                    "decided_at",
                    "REQUIREMENTS",
                    "DEFINITION_CHANGE_DECIDED",
                    "OWNER",
                    outcome="status",
                ),
            ),
        ),
        (
            of_project(DESIGN_VERSIONS, "created_at", "version_number"),
            (
                _when(
                    "created_at",
                    "DESIGN",
                    "DESIGN_VERSION_SAVED",
                    "STUDIO",
                    version="version_number",
                ),
            ),
        ),
        (
            owned(PACKAGE_DIFFS, "created_at", "decided_at", "status"),
            (
                _when("created_at", "DESIGN", "DESIGN_CHANGE_PROPOSED", "OWNER"),
                _when("decided_at", "DESIGN", "DESIGN_CHANGE_DECIDED", "OWNER", outcome="status"),
            ),
        ),
        (
            owned(RUNS, "started_at", "completed_at"),
            (
                _when(
                    "completed_at",
                    "DESIGN",
                    "EVALUATION_RUN_COMPLETED",
                    "STUDIO",
                    duration=("started_at", "completed_at"),
                ),
            ),
        ),
        (
            owned(VALIDATIONS, "decided_at", "decision"),
            (_when("decided_at", "DESIGN", "FINDING_DECIDED", "OWNER", outcome="decision"),),
        ),
        (
            owned(DISCUSSIONS, "created_at", "decided_at"),
            (
                _when("created_at", "DESIGN", "DISCUSSION_OPENED", "OWNER"),
                _when("decided_at", "DESIGN", "DISCUSSION_DECIDED", "OWNER"),
            ),
        ),
        (
            sa.select(ROUNDS.c.created_at)
            .join(DISCUSSIONS, DISCUSSIONS.c.id == ROUNDS.c.discussion_id)
            .where(
                DISCUSSIONS.c.project_id == project_id,
                DISCUSSIONS.c.owner_user_id == owner_user_id,
            ),
            (_when("created_at", "DESIGN", "DISCUSSION_ROUND_COMPLETED", "STUDIO"),),
        ),
        (
            owned(APPLICATIONS, "created_at"),
            (_when("created_at", "DESIGN", "INSIGHT_APPLIED", "OWNER"),),
        ),
        (
            owned(HYPOTHESES, "created_at", "code", "version_number"),
            (
                _when(
                    "created_at",
                    "DESIGN",
                    "HYPOTHESIS_SAVED",
                    "OWNER",
                    code="code",
                    version="version_number",
                ),
            ),
        ),
        (
            owned(OUTCOMES, "recorded_at", "code"),
            (_when("recorded_at", "DESIGN", "OUTCOME_RECORDED", "OWNER", code="code"),),
        ),
        (
            sa.select(
                DECISIONS.c.recorded_at,
                DECISIONS.c.snapshot["target"].astext.label("target"),
                DECISIONS.c.snapshot["action"].astext.label("action"),
            ).where(
                DECISIONS.c.project_id == project_id,
                DECISIONS.c.owner_user_id == owner_user_id,
                DECISIONS.c.snapshot["action"].astext.in_(tuple(_GAP_KINDS)),
            ),
            (_gaps,),
        ),
        (
            owned(PROTOTYPES, "created_at"),
            (_when("created_at", "DESIGN", "PROTOTYPE_PROVIDED", "OWNER"),),
        ),
        (
            owned(FOLDER_VERSIONS, "created_at", "version_number"),
            (
                _when(
                    "created_at",
                    "PACKAGE",
                    "PACKAGE_PUBLISHED",
                    "OWNER",
                    version="version_number",
                ),
            ),
        ),
        (
            owned(CODE_CHANGES, "recorded_at", "decided_at", "decision_kind"),
            (
                _when("recorded_at", "PACKAGE", "CODE_CHANGE_RECORDED", "OWNER"),
                _when(
                    "decided_at",
                    "PACKAGE",
                    "CODE_CHANGE_DECIDED",
                    "OWNER",
                    outcome="decision_kind",
                ),
            ),
        ),
        (
            owned(TEST_RUNS, "recorded_at", "started_at", "finished_at"),
            (
                _when(
                    "recorded_at",
                    "PACKAGE",
                    "TEST_RUN_RECORDED",
                    "OWNER",
                    duration=("started_at", "finished_at"),
                ),
            ),
        ),
        (
            owned(UPDATES, "created_at", "decided_at", "status"),
            (
                _when("created_at", "USER_TWINS", "TWIN_UPDATE_PROPOSED", "OWNER"),
                _when("decided_at", "USER_TWINS", "TWIN_UPDATE_DECIDED", "OWNER", outcome="status"),
            ),
        ),
        (
            sa.select(
                HumanGateEventRecord.occurred_at,
                HumanGateEventRecord.gate_type,
                HumanGateEventRecord.kind,
                HumanGateEventRecord.artifact_version,
                HumanGateEventRecord.actor_user_id.is_not(None).label("acted"),
                (HumanGateEventRecord.reason == ALIGNMENT_REASON).label("aligned"),
            )
            .join(HumanGateRecord, HumanGateRecord.id == HumanGateEventRecord.gate_id)
            .where(
                HumanGateEventRecord.project_id == project_id,
                HumanGateRecord.project_id == project_id,
                HumanGateRecord.owner_user_id == owner_user_id,
                HumanGateEventRecord.gate_type.in_(tuple(_GATE_SECTIONS)),
            ),
            (_gates,),
        ),
    )


def _order(item):
    rank, fact = item
    return (
        fact["at"],
        rank,
        fact["kind"],
        fact.get("code") or "",
        fact.get("version_number") or 0,
    )


async def _facts(session: AsyncSession, *, owner_user_id: UUID, project_id: UUID) -> list[dict]:
    ranked = []
    readers = _readers(owner_user_id, project_id)
    for rank, (statement, builders) in enumerate(readers):
        rows = (await session.execute(statement)).mappings().all()
        ranked.extend((rank, fact) for build in builders for fact in build(rows))
    generations, events = [
        (await session.execute(statement)).mappings().all()
        for statement in _generation_statements(owner_user_id, project_id)
    ]
    ranked.extend((len(readers), fact) for fact in _generations(generations, events))
    ranked.sort(key=_order)
    return [fact for _rank, fact in ranked]


def _session_row(code, kind):
    return {
        "session_code": code,
        "source": "STUDIO",
        "kind": kind,
        "section": None,
        "target": None,
        "client_at": None,
        "duration_ms": None,
        "status": None,
    }


class SqlAlchemyProjectActivityService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
        journal_factory: Callable[..., SqlAlchemyUsageJournalRepository] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._journal = journal_factory or SqlAlchemyUsageJournalRepository

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    async def _locked(self, session, *, owner_user_id: UUID, project_id: UUID):
        journal = self._journal(session, owner_user_id=owner_user_id)
        if not await journal.owned(project_id, lock=True):
            raise ActivityError("PROJECT_NOT_FOUND")
        return journal

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None:
        async with self._session_factory() as session, session.begin():
            await session.execute(sa.text(_READ_ONLY))
            journal = self._journal(session, owner_user_id=owner_user_id)
            if not await journal.owned(project_id):
                return None
            facts = await _facts(session, owner_user_id=owner_user_id, project_id=project_id)
            rows = await journal.rows(project_id)
        return project_activity(project_id=str(project_id), facts=facts, journal=rows)

    async def session(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None:
        async with self._session_factory() as session:
            journal = self._journal(session, owner_user_id=owner_user_id)
            if not await journal.owned(project_id):
                return None
            active = active_session(await journal.rows(project_id))
        return {"active": active is not None, "session": active}

    async def start_session(
        self, *, owner_user_id: UUID, project_id: UUID, session_code: str
    ) -> dict:
        code = validate_session_code(session_code)
        async with self._session_factory() as session, session.begin():
            journal = await self._locked(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            rows = await journal.rows(project_id)
            if active_session(rows) is not None:
                raise ActivityError("ACTIVITY_SESSION_ACTIVE")
            if any(row["session_code"] == code for row in rows):
                raise ActivityError("ACTIVITY_SESSION_CODE_USED")
            if await journal.count(project_id) >= MAX_JOURNAL_EVENTS:
                raise ActivityError("ACTIVITY_JOURNAL_FULL")
            started_at = self._now()
            await journal.append(
                project_id, [_session_row(code, "SESSION_STARTED")], received_at=started_at
            )
        return {
            "status": "ACTIVITY_SESSION_STARTED",
            "session": {"code": code, "started_at": started_at.isoformat()},
        }

    async def end_session(
        self, *, owner_user_id: UUID, project_id: UUID, session_code: str
    ) -> dict:
        code = validate_session_code(session_code)
        async with self._session_factory() as session, session.begin():
            journal = await self._locked(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            active = active_session(await journal.rows(project_id))
            if active is None or active["code"] != code:
                raise ActivityError("ACTIVITY_SESSION_NOT_ACTIVE")
            ended_at = self._now()
            await journal.append(
                project_id, [_session_row(code, "SESSION_ENDED")], received_at=ended_at
            )
        return {
            "status": "ACTIVITY_SESSION_ENDED",
            "session": {
                "code": code,
                "started_at": active["started_at"],
                "ended_at": ended_at.isoformat(),
            },
        }

    async def append_events(
        self, *, owner_user_id: UUID, project_id: UUID, request: Mapping
    ) -> dict:
        if not isinstance(request, Mapping) or not set(request) <= _REQUEST_KEYS:
            raise ActivityError("ACTIVITY_INPUT_INVALID")
        rows = journal_rows(
            source=request.get("source"),
            events=request.get("events"),
            session_code=request.get("session_code"),
        )
        async with self._session_factory() as session, session.begin():
            journal = await self._locked(
                session, owner_user_id=owner_user_id, project_id=project_id
            )
            active = active_session(await journal.rows(project_id))
            if active is None or active["code"] != request["session_code"]:
                raise ActivityError("ACTIVITY_SESSION_NOT_ACTIVE")
            if await journal.count(project_id) + len(rows) > MAX_JOURNAL_EVENTS:
                raise ActivityError("ACTIVITY_JOURNAL_FULL")
            recorded = await journal.append(project_id, rows, received_at=self._now())
        return {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": recorded}


__all__ = ["SqlAlchemyProjectActivityService"]
