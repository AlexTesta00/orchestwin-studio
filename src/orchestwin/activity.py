from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

SECTIONS = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
ACTORS = ("OWNER", "MODEL", "STUDIO")
JOURNAL_KINDS = {
    "WEB": (
        "SECTION_OPENED",
        "DETAIL_OPENED",
        "WHY_OPENED",
        "MOCKUP_OPENED",
        "MODE_CHANGED",
        "LOCALE_SET",
        "PAGE_HIDDEN",
        "PAGE_VISIBLE",
        "REQUEST_FAILED",
    ),
    "UT": ("COMMAND_STARTED", "COMMAND_FINISHED", "GENERATION_WAITED"),
}
SESSION_KINDS = ("SESSION_STARTED", "SESSION_ENDED")
SESSION_CODE_PATTERN = r"SES-[A-Z0-9][A-Z0-9-]{0,19}"
TARGET_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}"
STATUS_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}"
MAX_BATCH_EVENTS = 50
MAX_JOURNAL_EVENTS = 20000
MAX_DURATION_MS = 86_400_000
MAX_DWELL_INTERVAL_SECONDS = 14_400
ACTIVITY_KIND = "orchestwin.project-activity"
ACTIVITY_SCHEMA_VERSION = 1


class ActivityError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_INPUT_INVALID = "ACTIVITY_INPUT_INVALID"
_RECORDS_INVALID = "ACTIVITY_RECORDS_INVALID"
_SESSION_CODE = re.compile(SESSION_CODE_PATTERN)
_TARGET = re.compile(TARGET_PATTERN)
_STATUS = re.compile(STATUS_PATTERN)
_KINDS = {**JOURNAL_KINDS, "STUDIO": SESSION_KINDS}
_SOURCES = ("SERVER", "STUDIO", "WEB", "UT")
_FIELDS = ("kind", "section", "target", "client_at", "duration_ms", "status")
_FACT_FIELDS = ("code", "version_number", "duration_ms", "outcome", "purpose", "role")
_REQUIRED = {
    "SECTION_OPENED": ("section",),
    "DETAIL_OPENED": ("target",),
    "WHY_OPENED": ("target",),
    "MOCKUP_OPENED": ("target",),
    "MODE_CHANGED": ("status",),
    "LOCALE_SET": ("status",),
    "REQUEST_FAILED": ("status",),
    "COMMAND_STARTED": ("target",),
    "COMMAND_FINISHED": ("target", "status", "duration_ms"),
    "GENERATION_WAITED": ("target", "duration_ms"),
}
_STATUS_VALUES = {"MODE_CHANGED": ("GUIDED", "EXPERT"), "LOCALE_SET": ("it", "en")}
_GATES = (
    ("submissions", "GATE_SUBMITTED"),
    ("approvals", "GATE_APPROVED"),
    ("revision_requests", "GATE_REVISION_REQUESTED"),
    ("rejections", "GATE_REJECTED"),
)
_LIMITS = (
    "ELAPSED_INCLUDES_IDLE_TIME",
    "ACTOR_DERIVED_FROM_RECORD_KIND",
    "VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS",
    "PRE_MODEL_REFUSALS_NOT_RECORDED",
    "GENERATION_JOBS_NOT_PERSISTED",
    "FAILED_EVALUATION_RUNS_NOT_RECORDED",
)


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _conforms(value, pattern):
    return value is None or (isinstance(value, str) and pattern.fullmatch(value) is not None)


def _instant(value, code):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ActivityError(code) from None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ActivityError(code)
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ActivityError(code) from None


def _iso(value):
    return None if value is None else value.isoformat()


def _seconds(milliseconds):
    return round(milliseconds / 1000, 1)


def _session_code(value, code):
    if not isinstance(value, str) or _SESSION_CODE.fullmatch(value) is None:
        raise ActivityError(code)
    return value


def validate_session_code(value: object) -> str:
    return _session_code(value, _INPUT_INVALID)


def _fields(source, item, code, *, clock_required):
    values = {key: item.get(key) for key in _FIELDS}
    kind, duration = values["kind"], values["duration_ms"]
    if (
        kind not in _KINDS[source]
        or any(values[key] is None for key in _REQUIRED.get(kind, ()))
        or (clock_required and values["client_at"] is None)
        or values["section"] not in (None, *SECTIONS)
        or not _conforms(values["target"], _TARGET)
        or not _conforms(values["status"], _STATUS)
        or (kind in _STATUS_VALUES and values["status"] not in _STATUS_VALUES[kind])
        or not (duration is None or (_integer(duration) and 0 <= duration <= MAX_DURATION_MS))
    ):
        raise ActivityError(code)
    if values["client_at"] is not None:
        values["client_at"] = _instant(values["client_at"], code)
    return values


def journal_rows(*, source: object, events: object, session_code: object) -> list[dict]:
    code = _session_code(session_code, _INPUT_INVALID)
    if (
        source not in ("WEB", "UT")
        or not isinstance(events, list)
        or not 1 <= len(events) <= MAX_BATCH_EVENTS
        or not all(
            isinstance(event, Mapping)
            and set(event) <= set(_FIELDS)
            and isinstance(event.get("client_at"), str)
            for event in events
        )
    ):
        raise ActivityError(_INPUT_INVALID)
    rows = [_fields(source, event, _INPUT_INVALID, clock_required=True) for event in events]
    return [
        {"session_code": code, "source": source, **row, "client_at": row["client_at"].isoformat()}
        for row in rows
    ]


def _rows(journal):
    rows = []
    for item in journal:
        if (
            not isinstance(item, Mapping)
            or item.get("source") not in ("WEB", "UT", "STUDIO")
            or not _integer(item.get("sequence"))
        ):
            raise ActivityError(_RECORDS_INVALID)
        source = item["source"]
        row = _fields(source, item, _RECORDS_INVALID, clock_required=source != "STUDIO")
        row.update(
            sequence=item["sequence"],
            session_code=_session_code(item.get("session_code"), _RECORDS_INVALID),
            source=source,
            received_at=_instant(item.get("received_at"), _RECORDS_INVALID),
        )
        rows.append(row)
    return sorted(rows, key=lambda row: row["sequence"])


def active_session(journal: Sequence[Mapping]) -> dict | None:
    ended = set()
    for row in reversed(_rows(journal)):
        if row["kind"] == "SESSION_ENDED":
            ended.add(row["session_code"])
        elif row["kind"] == "SESSION_STARTED" and row["session_code"] not in ended:
            return {"code": row["session_code"], "started_at": row["received_at"].isoformat()}
    return None


def _fact(item):
    if (
        not isinstance(item, Mapping)
        or item.get("section") not in SECTIONS
        or item.get("actor") not in ACTORS
        or not isinstance(item.get("kind"), str)
        or any(
            item.get(key) is not None and not isinstance(item.get(key), str)
            for key in ("code", "outcome", "purpose", "role")
        )
        or any(
            item.get(key) is not None and not _integer(item.get(key))
            for key in ("version_number", "duration_ms")
        )
    ):
        raise ActivityError(_RECORDS_INVALID)
    return {
        "at": _instant(item.get("at"), _RECORDS_INVALID),
        "source": "SERVER",
        "section": item["section"],
        "kind": item["kind"],
        "actor": item["actor"],
        **{key: item.get(key) for key in _FACT_FIELDS},
        "session_code": None,
        "target": None,
    }


def _journal_event(row):
    return {
        "at": row["received_at"] if row["client_at"] is None else row["client_at"],
        "source": row["source"],
        "section": row["section"],
        "kind": row["kind"],
        "actor": "STUDIO" if row["source"] == "STUDIO" else "OWNER",
        "code": None,
        "version_number": None,
        "duration_ms": row["duration_ms"],
        "outcome": row["status"],
        "purpose": None,
        "role": None,
        "session_code": row["session_code"],
        "target": row["target"],
    }


def _intervals(rows):
    intervals, section, start, last = [], None, None, None
    for row in rows:
        if row["source"] == "WEB":
            if start is not None and row["kind"] in ("SECTION_OPENED", "PAGE_HIDDEN"):
                intervals.append((section, start, row["client_at"]))
                start = None
            if row["kind"] == "SECTION_OPENED":
                section, start = row["section"], row["client_at"]
            elif row["kind"] == "PAGE_VISIBLE" and start is None and section is not None:
                start = row["client_at"]
            last = row["client_at"]
        elif row["kind"] == "SESSION_ENDED" and start is not None:
            intervals.append((section, start, last))
            start = None
    return intervals


def _sessions(rows):
    groups, bounds = {}, {}
    for row in rows:
        code = row["session_code"]
        groups.setdefault(code, []).append(row)
        if row["kind"] == "SESSION_STARTED":
            bounds.setdefault(code, [row["received_at"], None])
        elif row["kind"] == "SESSION_ENDED" and code in bounds and bounds[code][1] is None:
            bounds[code][1] = row["received_at"]
    dwell, sessions = dict.fromkeys(SECTIONS, 0.0), []
    for code, (started_at, ended_at) in bounds.items():
        discarded = 0
        for section, start, end in _intervals(groups[code]):
            seconds = (end - start).total_seconds()
            if 0 <= seconds <= MAX_DWELL_INTERVAL_SECONDS:
                dwell[section] += seconds
            else:
                discarded += 1
        sessions.append(
            {
                "code": code,
                "started_at": started_at.isoformat(),
                "ended_at": _iso(ended_at),
                "events": len(groups[code]),
                "sources": sorted({item["source"] for item in groups[code]}),
                "discarded_intervals": discarded,
            }
        )
    return dwell, sessions


def _section(key, server, rows, dwell):
    facts = [event for event in server if event["section"] == key]
    approvals = [event["at"] for event in facts if event["kind"] == "GATE_APPROVED"]
    runs = [event for event in facts if event["kind"] == "GENERATION"]
    opened = [row["kind"] for row in rows if row["source"] == "WEB" and row["section"] == key]
    first = facts[0]["at"] if facts else None
    elapsed = None
    if approvals and approvals[0] >= first:
        elapsed = round((approvals[0] - first).total_seconds(), 1)
    succeeded = sum(event["outcome"] == "SUCCEEDED" for event in runs)
    return {
        "key": key,
        "first_event_at": _iso(first),
        "last_event_at": _iso(facts[-1]["at"]) if facts else None,
        "first_approved_at": _iso(approvals[0]) if approvals else None,
        "approved_at": _iso(approvals[-1]) if approvals else None,
        "elapsed_seconds": elapsed,
        "owner_actions": sum(event["actor"] == "OWNER" for event in facts),
        "gate": {name: sum(event["kind"] == kind for event in facts) for name, kind in _GATES},
        "generations": {
            "count": len(runs),
            "succeeded": succeeded,
            "failed": len(runs) - succeeded,
            "retries": sum(
                event["role"] is not None and event["outcome"] != "SUCCEEDED" for event in runs
            ),
            "wait_seconds": _seconds(sum(event["duration_ms"] or 0 for event in runs)),
        },
        "journal": {
            "opened": opened.count("SECTION_OPENED"),
            "dwell_seconds": round(dwell, 1),
            "details_opened": opened.count("DETAIL_OPENED"),
            "why_opened": opened.count("WHY_OPENED"),
            "mockups_opened": opened.count("MOCKUP_OPENED"),
        },
    }


def project_activity(
    *, project_id: str, facts: Sequence[Mapping], journal: Sequence[Mapping] = ()
) -> dict:
    rows = _rows(journal)
    timeline = sorted(
        [*map(_fact, facts), *map(_journal_event, rows)],
        key=lambda event: (event["at"], _SOURCES.index(event["source"])),
    )
    server = [event for event in timeline if event["source"] == "SERVER"]
    answers = [event for event in server if event["kind"] == "BRIEF_QUESTION_ANSWERED"]
    dwell, sessions = _sessions(rows)
    sections = [_section(key, server, rows, dwell[key]) for key in SECTIONS]
    limits = list(_LIMITS)
    if any(row["source"] in ("WEB", "UT") for row in rows):
        limits.append("CLIENT_CLOCK_NOT_VERIFIED")
    return {
        "kind": ACTIVITY_KIND,
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "project_id": str(project_id),
        "events": [
            {"number": number, **event, "at": event["at"].isoformat()}
            for number, event in enumerate(timeline, start=1)
        ],
        "sections": sections,
        "brief_dialogue": {
            "questions": sum(event["kind"] == "BRIEF_QUESTION_ASKED" for event in server),
            "answered": len(answers),
            "unknown_answers": sum(event["outcome"] == "UNKNOWN" for event in answers),
            "answer_seconds": [
                _seconds(event["duration_ms"])
                for event in answers
                if event["duration_ms"] is not None
            ],
        },
        "sessions": sessions,
        "totals": {
            "events": len(timeline),
            "owner_actions": sum(section["owner_actions"] for section in sections),
            "generations": sum(section["generations"]["count"] for section in sections),
            "generation_wait_seconds": _seconds(
                sum(event["duration_ms"] or 0 for event in server if event["kind"] == "GENERATION")
            ),
            "first_event_at": _iso(timeline[0]["at"]) if timeline else None,
            "last_event_at": _iso(timeline[-1]["at"]) if timeline else None,
        },
        "limits": sorted(limits),
    }


__all__ = [
    "ACTIVITY_KIND",
    "ACTIVITY_SCHEMA_VERSION",
    "ACTORS",
    "JOURNAL_KINDS",
    "MAX_BATCH_EVENTS",
    "MAX_DURATION_MS",
    "MAX_DWELL_INTERVAL_SECONDS",
    "MAX_JOURNAL_EVENTS",
    "SECTIONS",
    "SESSION_CODE_PATTERN",
    "SESSION_KINDS",
    "STATUS_PATTERN",
    "TARGET_PATTERN",
    "ActivityError",
    "active_session",
    "journal_rows",
    "project_activity",
    "validate_session_code",
]
