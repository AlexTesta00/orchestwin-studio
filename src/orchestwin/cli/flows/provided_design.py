from __future__ import annotations

from orchestwin.cli.api import workflow_inputs
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.previews import open_page
from orchestwin.cli.project import write_atomically
from orchestwin.cli.views.workflow_inputs import show_limits


def perform(context, client, project, source, action, value=None):
    from orchestwin.workflow_inputs import (
        PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
        PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
    )

    prototype = source["prototype"]
    if action not in {None, "show", "open"}:
        raise CliError(
            PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE
            if action == "review"
            else PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE
        )
    console = context.console
    console.heading(prototype["title"])
    label = "Prototipo fornito" if context.language == "it" else "Supplied prototype"
    gate = source.get("gate") or {}
    console.write(
        f"{label} · {prototype['code']} · v{prototype['version_number']} · {gate.get('status', 'NOT_APPROVED')}"
    )
    if prototype.get("declared_origin"):
        label = "Origine dichiarata" if context.language == "it" else "Declared origin"
        console.write(f"{label}: {prototype['declared_origin']}")
    if source.get("context_current") is False:
        console.say("why.gap.CONTEXT_OUTDATED")
    for screen in prototype["mockup"]["mockup"]["screens"]:
        console.write(f"{screen['code']}: {screen['title']}")
    show_limits(console, source.get("limits", []))
    if action != "open":
        return 0
    codes = {item["code"] for item in prototype["mockup"]["mockup"]["screens"]}
    if value is not None and value not in codes | {prototype["code"], prototype["id"]}:
        raise CliError("SCREEN_NOT_FOUND", values={"screen": value})
    document = workflow_inputs.document(
        client,
        project.link().project_id,
        prototype["id"],
        entry_screen=value if value in codes else "SCR-001",
    )
    project.previews.mkdir(parents=True, exist_ok=True)
    target = project.previews / f"{prototype['code']}.html"
    write_atomically(target, document["html"].encode("utf-8"))
    console.say("design.previews_written", path=str(target.parent))
    open_page(context, target)
    return 0
