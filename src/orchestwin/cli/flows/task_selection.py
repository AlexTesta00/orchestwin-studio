from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.flows.design_state import wrapped

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

ATTEMPTS: Final = 3
ALL_ANSWERS: Final = frozenset({"a", "t", "all", "tutti"})
SEPARATORS: Final = re.compile(r"[\s,;]+")
INDENT: Final = "  "
HANG: Final = "     "
IMPORTANCE_KEYS: Final[Mapping[str, str]] = {
    "LOW": "tasks.importance_low",
    "MEDIUM": "tasks.importance_medium",
    "HIGH": "tasks.importance_high",
}


@dataclass(frozen=True, slots=True)
class Candidate:
    label: str | None
    text: str
    source: Mapping[str, object] | None
    task_code: str | None = None
    finding: str | None = None
    severity: str | None = None

    @property
    def offered(self) -> bool:
        return self.task_code is None

    @property
    def verdict(self) -> bool:
        return self.finding is None


def verdict_candidates(texts: Sequence[str]) -> tuple[Candidate, ...]:
    cleaned = [" ".join(text.split()) for text in texts]
    return tuple(Candidate(label=None, text=text, source=None) for text in cleaned if text)


def candidates_of_run(
    run: Mapping[str, object], tasks: Sequence[Mapping[str, object]]
) -> tuple[Candidate, ...]:
    run_id = _text(run.get("id"))

    def source(twin_id: str, index: int) -> dict[str, object]:
        return tasks_api.run_source(run_id, twin_id, index)

    return _candidates(run, tasks, kind=tasks_api.TEST_RUN, subject=run_id, source=source)


def candidates_of_review(
    commit: str, run: Mapping[str, object], tasks: Sequence[Mapping[str, object]]
) -> tuple[Candidate, ...]:
    hash_value = commit.strip().lower()

    def source(twin_id: str, index: int) -> dict[str, object]:
        return tasks_api.change_source(hash_value, twin_id, index)

    return _candidates(run, tasks, kind=tasks_api.CODE_CHANGE, subject=hash_value, source=source)


def choose(
    context: CommandContext,
    candidates: Sequence[Candidate],
    *,
    question_key: str,
    default: Sequence[Candidate] = (),
    limit: int | None = None,
) -> tuple[Candidate, ...]:
    if not candidates:
        return ()
    console = context.console
    offered = [item for item in candidates if item.offered]
    show(context, candidates)
    if not offered:
        console.say("tasks.choice_all_tasks")
        return ()
    for _ in range(ATTEMPTS):
        answer = console.ask(question_key, required=False, count=len(offered))
        picked = selection(answer, offered, default)
        if picked is None:
            console.say("tasks.choice_invalid", count=len(offered))
        elif limit is not None and len(picked) > limit:
            console.say("tasks.choice_too_many", limit=limit)
        else:
            return picked
    console.say("tasks.choice_given_up")
    return ()


def show(context: CommandContext, candidates: Sequence[Candidate]) -> None:
    number = 0
    for item in candidates:
        line = candidate_line(context, item)
        if item.offered:
            number += 1
            wrapped(context, f"{number}. {line}", indent=INDENT, hang=HANG)
        else:
            existing = context.text("tasks.choice_existing", line=line, code=item.task_code)
            wrapped(context, f"-  {existing}", indent=INDENT, hang=HANG)
        if not item.verdict and item.text != item.finding:
            wrapped(context, context.text("tasks.choice_task", text=item.text), indent=HANG)


def candidate_line(context: CommandContext, item: Candidate) -> str:
    if item.verdict:
        return context.text("tasks.choice_verdict", text=item.text)
    return context.text(
        "tasks.choice_finding",
        who=item.label or context.text("tasks.twin_unknown"),
        importance=importance_text(context, item.severity),
        finding=item.finding or "",
    )


def importance_text(context: CommandContext, severity: str | None) -> str:
    key = IMPORTANCE_KEYS.get(severity or "")
    return context.text(key) if key else (severity or "-").lower()


def selection(
    answer: str, offered: Sequence[Candidate], default: Sequence[Candidate]
) -> tuple[Candidate, ...] | None:
    text = answer.strip()
    if not text:
        return tuple(item for item in offered if item in default)
    if text.casefold() in ALL_ANSWERS:
        return tuple(offered)
    chosen: set[int] = set()
    for part in SEPARATORS.split(text):
        if not part:
            continue
        if not part.isdecimal():
            return None
        number = int(part)
        if not 1 <= number <= len(offered):
            return None
        chosen.add(number)
    if not chosen:
        return None
    return tuple(offered[number - 1] for number in sorted(chosen))


def _candidates(
    run: Mapping[str, object],
    tasks: Sequence[Mapping[str, object]],
    *,
    kind: str,
    subject: str,
    source: Callable[[str, int], dict[str, object]],
) -> tuple[Candidate, ...]:
    found: list[Candidate] = []
    for critique in tasks_api.mappings(run.get("critiques")):
        twin_id = _text(critique.get("twin_id"))
        name = _text(critique.get("twin_name")) or None
        findings = critique.get("findings")
        for index, finding in enumerate(findings if isinstance(findings, list) else []):
            if not isinstance(finding, Mapping):
                continue
            text = _text(finding.get("text"))
            if not twin_id or not text:
                continue
            action = finding.get("action")
            existing = next(
                (
                    task
                    for task in tasks
                    if tasks_api.same_finding(
                        task, kind=kind, subject=subject, twin_id=twin_id, finding=text
                    )
                ),
                None,
            )
            severity = finding.get("severity")
            found.append(
                Candidate(
                    label=name,
                    text=tasks_api.finding_text(text, action if isinstance(action, str) else None),
                    source=source(twin_id, index),
                    task_code=None if existing is None else tasks_api.task_code(existing),
                    finding=text,
                    severity=severity if isinstance(severity, str) else None,
                )
            )
    return tuple(found)


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
