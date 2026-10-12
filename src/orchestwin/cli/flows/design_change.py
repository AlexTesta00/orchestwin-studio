from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import design_choice, design_generate, design_state, previews, review
from orchestwin.cli.shapes import mapping_or_empty as _mapping
from orchestwin.cli.shapes import mappings as _mappings
from orchestwin.cli.shapes import sequence as _list
from orchestwin.cli.shapes import squeezed as _squeezed

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import DesignState
    from orchestwin.cli.flows.mockup_screens import MockupElement, MockupScreen
    from orchestwin.cli.jobs import JobResult
    from orchestwin.cli.project import ProjectFolder

MAX_REQUEST: Final = 1000
MAX_RULE: Final = 300
MAX_NEW_RULES: Final = 5
MAX_RULES: Final = 20
MAX_PARTS: Final = 8
ITERATION: Final = "ITERATION"
OPINION: Final = "DESIGN_CHANGE_OPINION"
REJECTED: Final = "REJECTED"
PREVIEW_LIMIT: Final = 40
SCREEN_CODE: Final = re.compile(r"SCR-[0-9]{3}")
PART_CODE: Final = re.compile(r"(ELM|ZON)-[0-9]{3,6}")
ZONE_PREFIX: Final = "ZON-"
ELEMENT_MISSING: Final = "ELEMENT"
VERDICTS: Final = ("HELPS", "SLOWS", "BLOCKS")
APPLY: Final = "apply"
REWRITE: Final = "change"
CANCEL: Final = "cancel"
OPINION_CHOICES: Final = (APPLY, REWRITE, CANCEL)
TWIN_INDENT: Final = "  "
POINT_INDENT: Final = "    "


@dataclass(frozen=True, slots=True)
class ChangeRequest:
    text: str
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Aim:
    screen: str
    elements: tuple[str, ...] = ()

    @property
    def zoned(self) -> bool:
        return any(code.startswith(ZONE_PREFIX) for code in self.elements)


def aim_of(screen: str | None, elements: Sequence[str] | None) -> Aim | None:
    if screen is None:
        if elements:
            raise CliError("DESIGN_ELEMENT_NEEDS_SCREEN", status=USAGE_STATUS)
        return None
    return Aim(screen_code(screen), part_codes(elements or ()))


def screen_code(value: str) -> str:
    code = value.strip().upper()
    if SCREEN_CODE.fullmatch(code) is None:
        raise CliError("DESIGN_SCREEN_CODE_INVALID", status=USAGE_STATUS, values={"code": value})
    return code


def part_codes(values: Sequence[str]) -> tuple[str, ...]:
    codes = tuple(part_code(value) for value in values)
    repeated = next((code for index, code in enumerate(codes) if code in codes[:index]), None)
    if repeated is not None:
        raise CliError(
            "DESIGN_ELEMENT_CODE_REPEATED", status=USAGE_STATUS, values={"code": repeated}
        )
    if len(codes) > MAX_PARTS:
        raise CliError(
            "DESIGN_ELEMENT_TOO_MANY",
            status=USAGE_STATUS,
            values={"count": len(codes), "limit": MAX_PARTS},
        )
    return codes


def part_code(value: str) -> str:
    code = value.strip().upper()
    if PART_CODE.fullmatch(code) is None:
        raise CliError("DESIGN_ELEMENT_CODE_INVALID", status=USAGE_STATUS, values={"code": value})
    return code


def find_screen(
    context: CommandContext, screens: Sequence[MockupScreen], code: str
) -> MockupScreen:
    screen = next((item for item in screens if item.code == code), None)
    if screen is None:
        raise _not_found(context, screens, code)
    return screen


def target_of(
    context: CommandContext, document: Mapping[str, object], aim: Aim
) -> dict[str, object]:
    screens = design_state.document_screens(document)
    screen = find_screen(context, screens, aim.screen)
    if not aim.elements:
        return {"screen_code": screen.code, "label": screen.label, "html": screen.html}
    for code in aim.elements:
        if screen.element(code) is None:
            raise _not_found(context, screens, screen.code, code)
    parts = [item for item in screen.elements if item.code in aim.elements]
    if len(parts) > 1:
        return {"screen_code": screen.code, "elements": [_part(item) for item in parts]}
    [part] = parts
    if part.zone:
        return {"screen_code": screen.code, **_part(part)}
    return {"screen_code": screen.code, **_part(part), "html": part.html}


def scope_of(target: Mapping[str, object] | None) -> dict[str, object] | None:
    if target is None:
        return None
    codes = codes_of(target)
    scope: dict[str, object] = {"screen_code": target["screen_code"]}
    if len(codes) > 1:
        scope["element_codes"] = codes
    elif codes:
        scope["element_code"] = codes[0]
    return scope


def codes_of(target: Mapping[str, object]) -> list[str]:
    parts = _mappings(target.get("elements"))
    code = target.get("element_code")
    if parts:
        return [str(item.get("element_code")) for item in parts]
    return [] if code is None else [str(code)]


def say_target(context: CommandContext, target: Mapping[str, object]) -> None:
    console = context.console
    screen = target["screen_code"]
    parts = _mappings(target.get("elements"))
    code = target.get("element_code")
    if parts:
        listed = ", ".join(
            context.text("design.screen_item", code=item["element_code"], title=item["label"])
            for item in parts
        )
        console.say("design.target_parts", parts=listed, screen=screen)
    elif code is None:
        console.say("design.target_screen", screen=screen, text=target["label"])
    elif str(code).startswith(ZONE_PREFIX):
        console.say("design.target_zone", zone=code, screen=screen, text=target["label"])
    else:
        console.say("design.target_element", element=code, screen=screen, text=target["label"])


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
    asking: bool = False,
) -> int:
    console = context.console
    reason = unavailable(state)
    chosen = state.chosen
    version = state.version
    if reason is not None or chosen is None or version is None:
        console.say(reason or "design.change_needs_choice")
        return 1
    request = None if text is None else request_of(text, rules, state.rules)
    zoned = aim is not None and aim.zoned
    before = design_api.mockup_document(
        client, state.project_id, chosen.id, source=design_api.APPLIED, zones=zoned
    )
    target = None
    if aim is not None:
        if before is None:
            console.say("design.change_unavailable")
            return 1
        target = target_of(context, before, aim)
        say_target(context, target)
    if request is None:
        request = request_of(console.ask_text("design.change_ask"), rules, state.rules)
    opinion = None
    if asking and target is not None:
        answer = ask_first(context, client, state, version, request, target, rules)
        if answer is None:
            console.say("design.opinion_cancelled")
            return 0
        request, opinion = answer
    result = iterated(context, client, state, version, request, target, opinion, reviewing)
    return finish(
        context,
        client,
        project,
        state,
        iteration_result(result),
        request=request.text,
        before=before,
        reviewing=reviewing,
        target=target,
    )


def iterated(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    version: Mapping[str, object],
    request: ChangeRequest,
    target: Mapping[str, object] | None,
    opinion: str | None,
    reviewing: bool,
) -> JobResult:
    console = context.console
    project_id = state.project_id
    console.say(
        "design.about_change" if reviewing else "design.about_change_alone", request=request.text
    )
    if request.rules:
        console.say("design.about_rules")
        console.items(list(request.rules))
    costs.confirm_spending(
        context, client, [ITERATION, review.REVIEW] if reviewing else [ITERATION]
    )
    return design_generate.generate(
        context,
        client,
        project_id,
        design_api.iteration_jobs_path(project_id),
        design_api.iteration_body(version, request.text, request.rules, target, opinion),
        label=context.text("design.label_change"),
        job_path=lambda job_id: design_api.iteration_job_path(project_id, job_id),
    )


def ask_first(
    context: CommandContext,
    client: StudioClient,
    state: DesignState,
    version: Mapping[str, object],
    request: ChangeRequest,
    target: Mapping[str, object],
    rules: Sequence[str],
) -> tuple[ChangeRequest, str] | None:
    run = opinion_run(context, client, state.project_id, version, request.text, target)
    show_opinion(context, run)
    opinion = str(run["run_id"])
    if context.assume_yes:
        return request, opinion
    options = [Choice(key, context.text(f"design.opinion_choice_{key}")) for key in OPINION_CHOICES]
    picked = context.console.choose("design.menu", options)
    if picked.key == CANCEL:
        return None
    if picked.key == REWRITE:
        request = request_of(context.console.ask_text("design.change_ask"), rules, state.rules)
    return request, opinion


def opinion_run(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    version: Mapping[str, object],
    request: str,
    target: Mapping[str, object],
) -> Mapping[str, object]:
    console = context.console
    recorded = recorded_opinion(client, project_id, version, request, target)
    if recorded is not None:
        console.say("design.opinion_exists")
        return recorded
    console.say("design.opinion_about")
    costs.confirm_spending(context, client, [OPINION])
    result = design_generate.generate(
        context,
        client,
        project_id,
        design_api.opinions_path(project_id),
        design_api.opinion_body(version, request, target, review.review_locale(context.language)),
        label=context.text("design.opinion_running"),
    )
    if result.status_code >= 400:
        design_generate.raise_failure(design_generate.failure_of(result.status_code, result.body))
    if not isinstance(result.body, Mapping) or not isinstance(result.body.get("run_id"), str):
        raise ApiFailure("API_FAILURE", http_status=result.status_code)
    return result.body


def recorded_opinion(
    client: StudioClient,
    project_id: str,
    version: Mapping[str, object],
    request: str,
    target: Mapping[str, object],
) -> Mapping[str, object] | None:
    wanted = opinion_binding(version.get("content_hash"), request, target)
    return next(
        (
            run
            for run in design_api.opinions(client, project_id)
            if isinstance(run.get("run_id"), str)
            and opinion_binding(
                run.get("design_content_hash"), run.get("request"), _mapping(run.get("target"))
            )
            == wanted
        ),
        None,
    )


def opinion_binding(
    content_hash: object, request: object, target: Mapping[str, object]
) -> tuple[object, ...]:
    return (content_hash, request, target.get("screen_code"), *codes_of(target))


def show_opinion(context: CommandContext, run: Mapping[str, object]) -> None:
    console = context.console
    console.write()
    console.heading(context.text("design.opinion_heading"))
    console.say("design.opinion_simulated")
    for opinion in _mappings(run.get("opinions")):
        title = context.text(
            "design.opinion_twin",
            name=_squeezed(opinion.get("twin_name")) or context.text("design.review_twin"),
            verdict=verdict_text(context, opinion.get("verdict")),
        )
        design_state.wrapped(context, title, indent=TWIN_INDENT)
        for line in opinion_lines(context, opinion):
            design_state.wrapped(context, line, indent=POINT_INDENT)
    console.write()


def verdict_text(context: CommandContext, verdict: object) -> str:
    return context.text(f"design.opinion_verdict_{verdict}") if verdict in VERDICTS else "-"


def opinion_lines(context: CommandContext, opinion: Mapping[str, object]) -> list[str]:
    lines = [
        context.text("design.opinion_why", why=_squeezed(opinion.get("why"))),
        context.text("design.opinion_what_to_do", action=_squeezed(opinion.get("what_to_do"))),
    ]
    suggestion = _squeezed(opinion.get("try_this"))
    if suggestion:
        lines.append(context.text("design.opinion_try_this", request=suggestion))
    return lines


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
    target: Mapping[str, object] | None = None,
) -> int:
    console = context.console
    package = result.get("package")
    current = design_api.current(client, state.project_id)
    if (
        state.chosen is None
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
    design_state.show_corrections(context, _mappings(result.get("corrections")))
    applied = version.get("package")
    rules = _list(applied.get("owner_assertions")) if isinstance(applied, Mapping) else []
    design_state.show_rules(context, [item for item in rules if isinstance(item, str)])
    show_previews(context, client, project, state.chosen.id, request, before, current)
    reached = version.get("version_number") or "-"
    if not reviewing:
        console.say("design.change_review_later", version=reached)
        return 0
    return reviewed(context, client, project, reached, scope_of(target))


def show_previews(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    alternative_id: str,
    request: str,
    before: Mapping[str, object] | None,
    current: Mapping[str, object],
) -> None:
    fresh = design_state.read_state(client, project)
    if not fresh.generated or fresh.version is None:
        return
    html = None if before is None else before.get("html")
    number = current.get("version_number")
    index = previews.write_previews(
        context,
        project,
        fresh,
        change=previews.Change(
            alternative_id=alternative_id,
            request=request,
            before_html=html if isinstance(html, str) else None,
            before_version=number if isinstance(number, int) else None,
            after_version=fresh.version_number,
        ),
    )
    context.console.say("design.previews_written", path=str(index.parent))
    previews.open_page(context, index)


def reviewed(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    number: object,
    scope: Mapping[str, object] | None = None,
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


def iteration_result(result: JobResult) -> Mapping[str, object]:
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


def _part(item: MockupElement) -> dict[str, object]:
    return {"element_code": item.code, "label": item.label}


def _control(text: str) -> bool:
    return any(ord(character) < 32 or 127 <= ord(character) < 160 for character in text)


def _short(text: str) -> str:
    return text if len(text) <= PREVIEW_LIMIT else text[: PREVIEW_LIMIT - 1] + "…"


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
