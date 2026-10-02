from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli.api import requirements as api

if TYPE_CHECKING:
    from orchestwin.cli.console import Console

GROUPS = (
    ("scenarios", "scenarios"),
    ("needs", "needs"),
    ("user_stories", "stories"),
    ("requirements", "functional"),
    ("requirements", "non_functional"),
    ("requirements", "constraints"),
)
KINDS = {
    "functional": "FUNCTIONAL",
    "non_functional": "NON_FUNCTIONAL",
    "constraints": "CONSTRAINT",
}


def show(console: Console, version: Mapping[str, object], *, details: bool = False) -> None:
    console.write()
    console.heading(
        console.text("definition.heading", version=version.get("version_number") or "-")
    )
    console.say(
        "definition.summary",
        scenarios=len(api.entries(version, "scenarios")),
        needs=len(api.entries(version, "needs")),
        stories=len(api.entries(version, "user_stories")),
        requirements=len(api.entries(version, "requirements")),
        criteria=len(api.entries(version, "acceptance_criteria")),
    )
    console.say("definition.synthetic")
    journeys = api.entries(version, "journeys")
    if journeys:
        console.say("definition.journey_count", count=len(journeys))
    if not api.entries(version, "needs"):
        console.say("definition.legacy")
    titles = {
        str(item.get("id")): item_title(item)
        for key in ("scenarios", "needs", "user_stories", "requirements", "acceptance_criteria")
        for item in api.entries(version, key)
    }
    scenarios = {str(item.get("id")): item for item in api.entries(version, "scenarios")}
    main_groups = (*GROUPS[:2], ("journeys", "journeys"), *GROUPS[2:]) if journeys else GROUPS
    groups = (
        (
            *main_groups,
            ("acceptance_criteria", "criteria"),
            ("risks", "risks"),
            ("definition_of_done", "done"),
        )
        if details
        else main_groups
    )
    for key, label in groups:
        items = api.entries(version, key)
        if label in KINDS:
            items = [item for item in items if item.get("kind") == KINDS[label]]
        console.write()
        console.heading(f"{console.text('definition.' + label)} ({len(items)})")
        for item in items:
            if details:
                show_item(console, item, key, titles, scenarios)
            else:
                console.write(f"- {item_title(item)}")


def item_title(item: Mapping[str, object]) -> str:
    return str(
        item.get("title") or item.get("goal") or item.get("statement") or item.get("summary") or ""
    )


def show_item(
    console: Console,
    item: Mapping[str, object],
    group: str,
    titles: Mapping[str, str],
    scenarios: Mapping[str, Mapping[str, object]],
) -> None:
    if group == "requirements":
        console.write(
            console.text(
                "init.requirement_line",
                code=item.get("code") or "",
                title=item.get("title") or "",
                priority=console.text(f"init.priority_{str(item.get('priority')).lower()}"),
                kind=console.text(f"init.kind_{str(item.get('kind')).lower()}"),
            )
        )
        console.write(f"  {item.get('statement') or ''}")
    elif group == "user_stories":
        actor = item.get("user_twin_reference")
        name = actor.get("name") if isinstance(actor, Mapping) else None
        console.write(
            console.text(
                "init.story_line",
                code=item.get("code") or "",
                twin=name or console.text("init.story_someone"),
                goal=item.get("goal") or "",
                benefit=item.get("benefit") or "",
            )
        )
    else:
        console.write(f"{item.get('code') or ''} {item_title(item)}")
        if item.get("title") and item.get("statement"):
            console.write(f"  {item['statement']}")
    if group == "scenarios":
        actor = item.get("actor")
        field(console, "actor", actor.get("name") if isinstance(actor, Mapping) else None)
        for key in (
            "context",
            "goal",
            "preconditions",
            "trigger",
            "steps",
            "criticalities",
            "expected_outcome",
        ):
            field(console, key, item.get(key))
    if group == "needs":
        names = [
            str(actor.get("name"))
            for identifier in texts(item.get("scenario_ids"))
            if isinstance(actor := scenarios.get(identifier, {}).get("actor"), Mapping)
            and actor.get("name")
        ]
        field(console, "actor", list(dict.fromkeys(names)))
    if group == "journeys":
        identifier = str(item.get("scenario_id"))
        scenario = scenarios.get(identifier, {})
        field(console, "scenarios", titles.get(identifier, identifier))
        actor = scenario.get("actor")
        field(console, "actor", actor.get("name") if isinstance(actor, Mapping) else None)
        console.write(f"  {console.text('definition.phases')}:")
        for number, phase in enumerate(item.get("phases") or [], start=1):
            if not isinstance(phase, Mapping):
                continue
            console.write(f"  {number}. {phase.get('title') or ''}")
            field(console, "action", phase.get("action"))
            field(console, "touchpoint", phase.get("touchpoint") or "-")
            field(console, "criticalities", phase.get("criticalities"))
            field(
                console,
                "needs",
                [titles.get(identifier, identifier) for identifier in texts(phase.get("need_ids"))],
            )
    for key, label in (
        ("scenario_ids", "scenarios"),
        ("need_ids", "needs"),
        ("requirement_ids", "requirements"),
        ("user_story_ids", "stories"),
        ("acceptance_criterion_ids", "criteria"),
    ):
        field(
            console,
            label,
            [titles.get(identifier, identifier) for identifier in texts(item.get(key))],
        )
    method = item.get("verification_method")
    if group in {"acceptance_criteria", "definition_of_done"} and method:
        console.write(
            "  "
            + console.text(
                "init.criterion_check", method=console.text(f"init.verify_{str(method).lower()}")
            )
        )
    for key in (
        "likelihood",
        "impact",
        "mitigation",
        "review_status",
        "applicability",
        "condition",
    ):
        field(console, key, item.get(key))
    references = item.get("user_twin_references")
    if isinstance(references, list):
        field(
            console,
            "actor",
            [
                str(actor.get("name"))
                for actor in references
                if isinstance(actor, Mapping) and actor.get("name")
            ],
        )
    sources = item.get("sources")
    if isinstance(sources, list) and sources:
        field(
            console,
            "sources",
            [source_text(source) for source in sources if isinstance(source, Mapping)],
        )


def source_text(source: Mapping[str, object]) -> str:
    return "; ".join(f"{key}={value}" for key, value in source.items() if value is not None)


def field(console: Console, label: str, value: object) -> None:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    if value:
        console.write(f"  {console.text('definition.' + label)}: {value}")


def texts(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
