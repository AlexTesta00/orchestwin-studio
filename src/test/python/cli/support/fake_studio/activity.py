from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from .values import ALIGNMENT_REASON, GATE_TYPES, SECTION_STAGES, _Answer, _iso, _Refusal

if TYPE_CHECKING:
    from .fields import _Call
    from .project import FakeProject


ACTIVITY_GATES = {GATE_TYPES[stage]: key for key, stage in SECTION_STAGES.items()}
ACTIVITY_GATE_KINDS = {
    "SUBMIT": "GATE_SUBMITTED",
    "APPROVE": "GATE_APPROVED",
    "REJECT": "GATE_REJECTED",
    "REQUEST_REVISION": "GATE_REVISION_REQUESTED",
    "PAUSE": "GATE_PAUSED",
    "RESUME": "GATE_RESUMED",
    "CANCEL": "GATE_CANCELLED",
    "ARTIFACT_SUPERSEDED": "GATE_SUPERSEDED",
}
ACTIVITY_PURPOSES = {
    "TEST_PLAN": "PACKAGE",
    "TEST_REVIEW": "PACKAGE",
    "CODE_CHANGE_REVIEW": "PACKAGE",
    "CODE_ALIGNMENT": "PACKAGE",
    "TWIN_UPDATE": "USER_TWINS",
    "KNOWLEDGE_ALIGNMENT": "PACKAGE",
    "DESIGN_CHANGE": "DESIGN",
}
ACTIVITY_TASKS = {
    "brief": "BRIEF",
    "team": "TEAM",
    "user_modeling": "USER_TWINS",
    "requirements": "REQUIREMENTS",
}
OWNER_REVISIONS = ("OWNER_EDITED", "OWNER_PROVIDED")


class _ActivityRoutes:
    def _activity_facts(self, project: FakeProject) -> list[dict[str, object]]:
        facts = [_activity_fact(project.created_at, "BRIEF", "PROJECT_CREATED", "OWNER")]
        for turn in (turn for dialogue in project.dialogues for turn in dialogue.turns):
            facts.append(_activity_fact(turn.asked_at, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"))
            if turn.answer is not None and turn.answered_at is not None:
                waited = turn.answered_at - turn.asked_at
                facts.append(
                    _activity_fact(
                        turn.answered_at,
                        "BRIEF",
                        "BRIEF_QUESTION_ANSWERED",
                        "OWNER",
                        duration_ms=round(waited.total_seconds() * 1000),
                        outcome=turn.answer.kind.value,
                    )
                )
        versions = (
            ("BRIEF", "BRIEF_VERSION_SAVED", "OWNER", [item.payload for item in project.briefs]),
            ("TEAM", "TEAM_VERSION_SAVED", "MODEL", project.teams),
            ("USER_TWINS", "TWINS_VERSION_SAVED", "STUDIO", project.snapshots),
            ("REQUIREMENTS", "DEFINITION_VERSION_SAVED", "STUDIO", project.requirements),
            ("DESIGN", "DESIGN_VERSION_SAVED", "STUDIO", project.designs),
            ("PACKAGE", "PACKAGE_PUBLISHED", "OWNER", project.packages),
        )
        for section, kind, actor, items in versions:
            for item in items:
                if not item.get("created_at"):
                    continue
                revision = item.get("revision_kind")
                facts.append(
                    _activity_fact(
                        item["created_at"],
                        section,
                        kind,
                        "OWNER" if revision in OWNER_REVISIONS else actor,
                        version_number=item.get("version_number"),
                        outcome=revision,
                    )
                )
        for event in (event for events in project.gate_events.values() for event in events):
            aligned = event.reason == ALIGNMENT_REASON
            facts.append(
                _activity_fact(
                    event.occurred_at,
                    ACTIVITY_GATES[event.artifact.gate_type],
                    ACTIVITY_GATE_KINDS[event.kind.value],
                    "STUDIO" if aligned or event.actor_user_id is None else "OWNER",
                    version_number=event.artifact.version,
                    outcome="ALIGNED" if aligned else None,
                )
            )
        for item in project.usage:
            purpose = str(item["purpose"])
            facts.append(
                _activity_fact(
                    item["recorded_at"],
                    ACTIVITY_PURPOSES.get(purpose)
                    or ACTIVITY_TASKS.get(str(item["task"]), "DESIGN"),
                    "GENERATION",
                    "MODEL",
                    duration_ms=item["latency_milliseconds"],
                    outcome=item["failure_code"] or item["status"],
                    purpose=purpose,
                )
            )
        return facts

    def _activity_append(
        self, project: FakeProject, rows: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        received_at = _iso(self._now())
        first = len(project.activity_journal) + 1
        added = [
            {"sequence": first + index, **row, "received_at": received_at}
            for index, row in enumerate(rows)
        ]
        project.activity_journal.extend(added)
        return added

    def _route_activity(self, call: _Call) -> _Answer:
        from orchestwin.activity import ActivityError, project_activity

        project = self._code_project(call)
        try:
            document = project_activity(
                project_id=project.id,
                facts=self._activity_facts(project),
                journal=project.activity_journal,
            )
        except ActivityError as error:
            raise _Refusal(422, {"code": error.code}) from None
        return _Answer(200, document)

    def _route_activity_session(self, call: _Call) -> _Answer:
        from orchestwin.activity import active_session

        session = active_session(self._code_project(call).activity_journal)
        return _Answer(200, {"active": session is not None, "session": session})

    def _route_activity_start(self, call: _Call) -> _Answer:
        from orchestwin.activity import (
            MAX_JOURNAL_EVENTS,
            ActivityError,
            active_session,
            validate_session_code,
        )

        body = call.json()
        try:
            if not isinstance(body, dict) or set(body) != {"session_code"}:
                raise ActivityError("ACTIVITY_INPUT_INVALID")
            code = validate_session_code(body["session_code"])
        except ActivityError as error:
            raise _Refusal(422, {"code": error.code}) from None
        project = self._code_project(call)
        if active_session(project.activity_journal) is not None:
            raise _Refusal(409, {"code": "ACTIVITY_SESSION_ACTIVE"})
        if any(row["session_code"] == code for row in project.activity_journal):
            raise _Refusal(409, {"code": "ACTIVITY_SESSION_CODE_USED"})
        if len(project.activity_journal) >= MAX_JOURNAL_EVENTS:
            raise _Refusal(409, {"code": "ACTIVITY_JOURNAL_FULL"})
        (row,) = self._activity_append(project, [_activity_row(code, "SESSION_STARTED")])
        return _Answer(
            201,
            {
                "status": "ACTIVITY_SESSION_STARTED",
                "session": {"code": code, "started_at": row["received_at"]},
            },
        )

    def _route_activity_end(self, call: _Call) -> _Answer:
        from orchestwin.activity import ActivityError, active_session, validate_session_code

        try:
            code = validate_session_code(call.params["session_code"])
        except ActivityError as error:
            raise _Refusal(422, {"code": error.code}) from None
        project = self._code_project(call)
        session = active_session(project.activity_journal)
        if session is None or session["code"] != code:
            raise _Refusal(409, {"code": "ACTIVITY_SESSION_NOT_ACTIVE"})
        (row,) = self._activity_append(project, [_activity_row(code, "SESSION_ENDED")])
        return _Answer(
            200,
            {
                "status": "ACTIVITY_SESSION_ENDED",
                "session": {**session, "ended_at": row["received_at"]},
            },
        )

    def _route_activity_events(self, call: _Call) -> _Answer:
        from orchestwin.activity import (
            MAX_JOURNAL_EVENTS,
            ActivityError,
            active_session,
            journal_rows,
        )

        body = call.json()
        try:
            if not isinstance(body, dict) or not set(body) <= {"session_code", "source", "events"}:
                raise ActivityError("ACTIVITY_INPUT_INVALID")
            rows = journal_rows(
                source=body.get("source"),
                events=body.get("events"),
                session_code=body.get("session_code"),
            )
        except ActivityError as error:
            raise _Refusal(422, {"code": error.code}) from None
        project = self._code_project(call)
        session = active_session(project.activity_journal)
        if session is None or session["code"] != body["session_code"]:
            raise _Refusal(409, {"code": "ACTIVITY_SESSION_NOT_ACTIVE"})
        if len(project.activity_journal) + len(rows) > MAX_JOURNAL_EVENTS:
            raise _Refusal(409, {"code": "ACTIVITY_JOURNAL_FULL"})
        self._activity_append(project, rows)
        return _Answer(202, {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": len(rows)})


def _activity_fact(
    at: datetime | str, section: str, kind: str, actor: str, **values: object
) -> dict[str, object]:
    return {
        "at": at if isinstance(at, str) else _iso(at),
        "section": section,
        "kind": kind,
        "actor": actor,
        **values,
    }


def _activity_row(session_code: str, kind: str) -> dict[str, object]:
    return {
        "session_code": session_code,
        "source": "STUDIO",
        "kind": kind,
        "section": None,
        "target": None,
        "client_at": None,
        "duration_ms": None,
        "status": None,
    }
