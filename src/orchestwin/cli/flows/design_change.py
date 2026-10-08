from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import design_choice, design_generate, design_state, previews, review

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import DesignState, MockupScreen
    from orchestwin.cli.jobs import JobResult
    from orchestwin.cli.project import ProjectFolder

MAX_REQUEST: Final = 1000
MAX_RULE: Final = 300
MAX_NEW_RULES: Final = 5
MAX_RULES: Final = 20
ITERATION: Final = "ITERATION"
REJECTED: Final = "REJECTED"
PREVIEW_LIMIT: Final = 40
SCREEN_CODE: Final = re.compile(r"SCR-[0-9]{3}")
ELEMENT_CODE: Final = re.compile(r"ELM-[0-9]{3}")
ELEMENT_MISSING: Final = "ELEMENT"


@dataclass(frozen=True, slots=True)
class ChangeRequest:
    text: str
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Aim:
    screen: str
    element: str | None = None


def aim_of(screen: str | None, element: str | None) -> Aim | None:
    if screen is None:
        if element is not None:
            raise CliError("DESIGN_ELEMENT_NEEDS_SCREEN", status=USAGE_STATUS)
        return None
    return Aim(screen_code(screen), None if element is None else element_code(element))


def screen_code(value: str) -> str:
    code = value.strip().upper()
    if SCREEN_CODE.fullmatch(code) is None:
        raise CliError("DESIGN_SCREEN_CODE_INVALID", status=USAGE_STATUS, values={"code": value})
    return code


def element_code(value: str) -> str:
    code = value.strip().upper()
    if ELEMENT_CODE.fullmatch(code) is None:
        raise CliError("DESIGN_ELEMENT_CODE_INVALID", status=USAGE_STATUS, values={"code": value})
    return code


def find_screen(
    context: CommandContext, screens: Sequence[MockupScreen], code: str
) -> MockupScreen:
    screen = next((item for item in screens if item.code == code), None)
    if screen is None:
        raise _not_found(context, screens, code)
    return screen


def target_of(context: CommandContext, document: Mapping[str, object], aim: Aim) -> dict[str, str]:
    screens = design_state.document_screens(document)
    screen = find_screen(context, screens, aim.screen)
    if aim.element is None:
        return {"screen_code": screen.code, "label": screen.label, "html": screen.html}
    element = screen.element(aim.element)
    if element is None:
        raise _not_found(context, screens, screen.code, aim.element)
    return {
        "screen_code": screen.code,
        "element_code": element.code,
        "label": element.label,
        "html": element.html,
    }


def scope_of(target: Mapping[str, str] | None) -> dict[str, str] | None:
    if target is None:
        return None
    return {name: target[name] for name in ("screen_code", "element_code") if name in target}


def say_target(context: CommandContext, target: Mapping[str, str]) -> None:
    element = target.get("element_code")
    screen = target["screen_code"]
    if element is None:
        context.console.say("design.target_screen", screen=screen, text=target["label"])
    else:
        context.console.say(
            "design.target_element", element=element, screen=screen, text=target["label"]
        )


def request_of(text: str, rules: Sequence[str], current: Sequence[str]) -> ChangeRequest:
    request = " ".join(text.split())
    if not request:
        raise CliError("CHANGE_EMPTY", status=USAGE_STATUS)
    if len(request) > MAX_REQUEST:
        raise CliError(
            "CHANGE_TOO_LONG",
            status=USAGE_STATUS,
            values={"limit": MAX_REQUEST, "length": len(request)},
        )
    if _control(request):
        raise CliError("CHANGE_NOT_VALID", status=USAGE_STATUS)
    added: list[str] = []
    for rule in rules:
        item = " ".join(rule.split())
        if not item:
            continue
        if len(item) > MAX_RULE or _control(item):
            raise CliError(
                "RULE_NOT_VALID",
                status=USAGE_STATUS,
                values={"limit": MAX_RULE, "rule": _short(item)},
            )
        if item not in added:
            added.append(item)
    if len(added) > MAX_NEW_RULES:
        raise CliError("TOO_MANY_NEW_RULES", status=USAGE_STATUS, values={"limit": MAX_NEW_RULES})
    merged = [*current, *(item for item in added if item not in current)]
    if len(merged) > MAX_RULES:
        raise CliError(
            "TOO_MANY_RULES",
            status=USAGE_STATUS,
            values={"limit": MAX_RULES, "count": len(current)},
        )
    return ChangeRequest(text=request, rules=tuple(added))


def unavailable(state: DesignState) -> str | None:
    if state.chosen is None:
        return "design.change_needs_choice"
    if not state.changeable:
        return "design.change_unavailable"
    return None


def change(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    text: str | None,
    rules: Sequence[str],
    *,
    aim: Aim | None = None,
    reviewing: bool = True,
) -> int:
    console = context.console
    reason = unavailable(state)
    chosen = state.chosen
    if reason is not None or chosen is None or state.version is None:
        console.say(reason or "design.change_needs_choice")
        return 1
    request = None if text is None else request_of(text, rules, state.rules)
    project_id = state.project_id
    before = design_api.mockup_document(client, project_id, chosen.id, source=design_api.APPLIED)
    target = None
    if aim is not None:
        if before is None:
            console.say("design.change_unavailable")
            return 1
        target = target_of(context, before, aim)
        say_target(context, target)
    if request is None:
        request = request_of(console.ask_text("design.change_ask"), rules, state.rules)
    console.say(
        "design.about_change" if reviewing else "design.about_change_alone", request=request.text
    )
    if request.rules:
        console.say("design.about_rules")
        console.items(list(request.rules))
    costs.confirm_spending(
        context, client, [ITERATION, review.REVIEW] if reviewing else [ITERATION]
    )
    result = design_generate.generate(
        context,
        client,
        project_id,
        design_api.iteration_jobs_path(project_id),
        design_api.iteration_body(state.version, request.text, request.rules, target),
        label=context.text("design.label_change"),
        job_path=lambda job_id: design_api.iteration_job_path(project_id, job_id),
    )
    return finish(
        context,
        client,
        project,
        state,
        _result(result),
        request=request.text,
        before=before,
        reviewing=reviewing,
        target=target,
    )


def finish(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    result: Mapping[str, object],
    *,
    request: str,
    before: Mapping[str, object] | None,
    reviewing: bool = True,
    target: Mapping[str, str] | None = None,
) -> int:
    console = context.console
    chosen = state.chosen
    package = result.get("package")
    current = design_api.current(client, state.project_id)
    if (
        chosen is None
        or not isinstance(package, Mapping)
        or current is None
        or (current.get("id"), current.get("content_hash"))
        != (result.get("design_version_id"), result.get("design_content_hash"))
    ):
        raise CliError(design_generate.CONTEXT_CHANGED)
    version = design_choice.apply_package(client, replace(state, version=current), package)
    if version.get("id") == current.get("id"):
        console.say("design.change_same", version=current.get("version_number") or "-")
        return 0
    console.say("design.change_applied", version=version.get("version_number") or "-")
    console.say("design.change_request", request=request)
    changes = [item for item in _list(result.get("changes")) if isinstance(item, str) and item]
    if changes:
        console.say("design.change_list")
        console.items(changes)
    applied = version.get("package")
    rules = _list(applied.get("owner_assertions")) if isinstance(applied, Mapping) else []
    design_state.show_rules(context, [item for item in rules if isinstance(item, str)])
    fresh = design_state.read_state(client, project)
    if fresh.generated and fresh.version is not None:
        html = None if before is None else before.get("html")
        number = current.get("version_number")
        index = previews.write_previews(
            context,
            project,
            fresh,
            change=previews.Change(
                alternative_id=chosen.id,
                request=request,
                before_html=html if isinstance(html, str) else None,
                before_version=number if isinstance(number, int) else None,
                after_version=fresh.version_number,
            ),
        )
        console.say("design.previews_written", path=str(index.parent))
        previews.open_page(context, index)
    reached = version.get("version_number") or "-"
    if not reviewing:
        console.say("design.change_review_later", version=reached)
        return 0
    return reviewed(context, client, project, reached, scope_of(target))


def reviewed(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    number: object,
    scope: Mapping[str, str] | None = None,
) -> int:
    return review.review_after(
        context, client, project, key="design.change_not_reviewed", number=number, scope=scope
    )


def finish_followed(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
    outcome: design_generate.Outcome,
) -> int:
    result = outcome.result
    chosen = state.chosen
    if result is None or chosen is None:
        design_generate.report_job(context, outcome)
        return 1
    before = design_api.mockup_document(
        client, state.project_id, chosen.id, source=design_api.APPLIED
    )
    return finish(
        context, client, project, state, result, request=_asked(client, state), before=before
    )


def apply_pending(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    state: DesignState,
) -> int:
    chosen = state.chosen
    item = state.pending_change
    content_hash = None if state.version is None else state.version.get("content_hash")
    if chosen is None or item is None or not isinstance(content_hash, str):
        return 1
    result = design_choice.stored_result(client, state, chosen.id, content_hash=content_hash)
    if result is None:
        context.console.say("design.pending_missing")
        return 1
    before = design_api.mockup_document(
        client, state.project_id, chosen.id, source=design_api.APPLIED
    )
    request = item.get("request")
    return finish(
        context,
        client,
        project,
        state,
        result,
        request=request if isinstance(request, str) else "-",
        before=before,
    )


def _result(result: JobResult) -> Mapping[str, object]:
    body = result.body
    job = body if isinstance(body, Mapping) and isinstance(body.get("job_id"), str) else None
    if job is not None and result.status_code < 400:
        value = job.get("result")
        if isinstance(value, Mapping) and isinstance(value.get("package"), Mapping):
            return value
        raise ApiFailure("API_FAILURE", http_status=result.status_code)
    failure = design_generate.failure_of(result.status_code, body)
    if job is not None and job.get("status") == REJECTED:
        reasons = "; ".join(design_generate.failure_reasons(job))
        raise CliError(
            "GENERATION_REJECTED",
            values={"code": failure.code, "detail": reasons or failure.code},
        )
    design_generate.raise_failure(failure)


def _asked(client: StudioClient, state: DesignState) -> str:
    for item in design_api.iterations(client, state.project_id):
        request = item.get("request")
        if item.get("status") == design_state.PROPOSED and isinstance(request, str):
            return request
    return "-"


def _control(text: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) < 160 for character in text)


def _short(text: str) -> str:
    return text if len(text) <= PREVIEW_LIMIT else text[: PREVIEW_LIMIT - 1] + "…"


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _not_found(
    context: CommandContext,
    screens: Sequence[MockupScreen],
    screen: str,
    element: str | None = None,
) -> CliError:
    listed = ", ".join(
        context.text("design.screen_item", code=item.code, title=item.title)
        if item.title
        else item.code
        for item in screens
    )
    values: dict[str, object] = {"screen": screen, "screens": listed or "-"}
    if element is not None:
        values.update(element=element, reason=ELEMENT_MISSING)
    return CliError("DESIGN_TARGET_NOT_FOUND", status=USAGE_STATUS, values=values)
