from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api.sections import STAGE_OF
from orchestwin.cli.console import format_elapsed

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

HEADERS: Final = (
    "sections.column_section",
    "activity.column_first",
    "activity.column_approved",
    "activity.column_elapsed",
    "activity.column_owner",
    "activity.column_generations",
    "activity.column_wait",
    "activity.column_retries",
)
CSV_COLUMNS: Final = (
    "number",
    "at",
    "source",
    "section",
    "kind",
    "actor",
    "code",
    "version_number",
    "duration_ms",
    "outcome",
    "purpose",
    "role",
    "session_code",
    "target",
)
FORMULA_PREFIXES: Final = ("=", "+", "-", "@")
TEXT_MARKER: Final = "'"
MOMENT_FORMAT: Final = "%d/%m %H:%M"
SEPARATOR: Final = ", "


def show(context: CommandContext, document: Mapping[str, object]) -> None:
    console = context.console
    console.table(
        [context.text(key) for key in HEADERS],
        [section_row(context, item) for item in mappings(document.get("sections"))],
    )
    console.say("activity.utc")
    dialogue = document.get("brief_dialogue")
    if isinstance(dialogue, Mapping) and dialogue.get("questions"):
        seconds = [value for value in dialogue.get("answer_seconds") or () if number(value)]
        console.say(
            "activity.brief_dialogue",
            questions=dialogue["questions"],
            answered=dialogue.get("answered", 0),
            unknown=dialogue.get("unknown_answers", 0),
            average=duration(sum(seconds) / len(seconds)) if seconds else "-",
        )
    for session in mappings(document.get("sessions")):
        ended = session.get("ended_at")
        console.say(
            "activity.session" if ended else "activity.session_open",
            code=session.get("code", "-"),
            started=moment(session.get("started_at")),
            ended=moment(ended),
            events=session.get("events", 0),
            sources=SEPARATOR.join(str(item) for item in session.get("sources") or ()),
            discarded=session.get("discarded_intervals", 0),
        )
    limits = document.get("limits") or ()
    console.say("activity.limits", codes=SEPARATOR.join(str(item) for item in limits))


def section_row(context: CommandContext, item: Mapping[str, object]) -> list[str]:
    from orchestwin.cli.commands.sections import stage_name

    key = str(item.get("key"))
    generations = item.get("generations")
    generations = generations if isinstance(generations, Mapping) else {}
    count = generations.get("count", 0)
    return [
        stage_name(context, STAGE_OF.get(key, key.lower())),
        moment(item.get("first_event_at")),
        moment(item.get("approved_at")),
        duration(item.get("elapsed_seconds")),
        str(item.get("owner_actions", 0)),
        str(count),
        duration(generations.get("wait_seconds")) if count else "-",
        str(generations.get("retries", 0)),
    ]


def csv_text(events: Sequence[Mapping[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows([cell(event.get(column)) for column in CSV_COLUMNS] for event in events)
    return buffer.getvalue()


def cell(value: object) -> str:
    text = "" if value is None else " ".join(str(value).split())
    return TEXT_MARKER + text if text.startswith(FORMULA_PREFIXES) else text


def moment(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "-"
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        return value
    if found.tzinfo is None:
        found = found.replace(tzinfo=UTC)
    return found.astimezone(UTC).strftime(MOMENT_FORMAT)


def duration(value: object) -> str:
    return format_elapsed(float(value)) if number(value) else "-"


def number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]
