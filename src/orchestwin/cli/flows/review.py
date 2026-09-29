from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.flows import design_generate
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

REVIEW: Final = "DESIGN_EVALUATION"
REVIEW_CODES: Final = frozenset(
    {
        "DESIGN_REVIEWER_NOT_CONFIGURED",
        "DESIGN_EVALUATOR_NOT_CONFIGURED",
        "DESIGN_PROTOTYPE_REQUIRED",
        "USER_TWIN_CONTEXT_CHANGED",
        "TOO_MANY_GENERATIONS",
        "GENERATION_BUDGET_EXCEEDED",
        "INCOMPLETE_OUTPUT",
        "TIMEOUT",
        "INVALID_PROVIDER_OUTPUT",
    }
)
SEVERITIES: Final = ("critical", "major", "moderate", "minor", "observation")
LEADING_SCREEN: Final = re.compile(r"(SCR-[0-9]{3,6})(?![0-9])")
LABEL_LIMIT: Final = 60
ITALIAN_LOCALE: Final = "it-IT"
ENGLISH_LOCALE: Final = "en-US"


def run_review(context: CommandContext, client: StudioClient, project: ProjectFolder) -> int:
    console = context.console
    link = project.link()
    version = design_api.current(client, link.project_id)
    if version is None:
        console.say("design.review_no_design")
        return 1
    if not chosen(version):
        console.say("design.review_not_chosen")
        return 1
    locale = review_locale(link.language or context.language)
    try:
        run = _reviewed(context, client, link.project_id, version, locale)
    except CliError as error:
        key = error_key(error)
        if key is None:
            raise
        console.error(key, **error.values)
        return error.status
    show_review(context, run, version)
    show_comparison(context, client, link.project_id, run, version)
    return 0


def review_after(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    *,
    key: str,
    number: object,
) -> int:
    try:
        status = run_review(context, client, project)
    except CliError:
        context.console.say(key, version=number)
        raise
    if status != 0:
        context.console.say(key, version=number)
    return status


def existing_review(
    client: StudioClient, project_id: str, version: Mapping[str, object]
) -> Mapping[str, object] | None:
    wanted = (version.get("id"), version.get("content_hash"))
    return next(
        (
            run
            for run in design_api.evaluations(client, project_id)
            if (run.get("design_version_id"), run.get("design_content_hash")) == wanted
        ),
        None,
    )


def chosen(version: Mapping[str, object]) -> bool:
    package = version.get("package")
    return (
        isinstance(package, Mapping)
        and isinstance(package.get("owner_selected_alternative_id"), str)
        and isinstance(package.get("prototype"), Mapping)
    )


def review_locale(language: str) -> str:
    return ITALIAN_LOCALE if language.strip().lower().startswith("it") else ENGLISH_LOCALE


def error_key(error: CliError) -> str | None:
    if error.code == design_generate.CONTEXT_CHANGED:
        return "design.review_changed"
    if (
        error.code == design_generate.UNREACHABLE
        and error.values.get("reason") == design_generate.JOB_RUNNING_REASON
    ):
        return "design.errors.STUDIO_UNREACHABLE.JOB_RUNNING"
    key = f"design.errors.{error.code}"
    return key if error.code in REVIEW_CODES and known(key) else None


def finished_run(outcome: design_generate.Outcome) -> Mapping[str, object]:
    if outcome.status == design_generate.LOST:
        raise CliError(
            "GENERATION_LOST",
            values={"label": outcome.tracked.name, "job_id": outcome.tracked.job_id},
        )
    response = outcome.response
    if response is None:
        raise ApiFailure("API_FAILURE", http_status=200)
    status, body = response
    if status >= 400:
        design_generate.raise_failure(design_generate.failure_of(status, body))
    return _run(body, status)


def show_review(
    context: CommandContext, run: Mapping[str, object], version: Mapping[str, object]
) -> None:
    console = context.console
    package = version.get("package")
    package = package if isinstance(package, Mapping) else {}
    names = twin_names(package)
    screens, elements = places(package)
    number = run.get("design_version_number")
    console.write()
    console.heading(context.text("design.review_heading", version=number or "-"))
    responses = [item for item in _list(run.get("responses")) if isinstance(item, Mapping)]
    if not responses:
        console.say("design.review_empty")
        return
    for response in responses:
        twin = response.get("twin_id")
        name = names.get(twin) if isinstance(twin, str) else None
        console.write(name or context.text("design.review_twin"))
        findings = [item for item in _list(response.get("findings")) if isinstance(item, Mapping)]
        if not findings:
            console.say("design.review_no_findings")
            continue
        console.items([finding_line(context, item, screens, elements) for item in findings])
    console.write()


def show_comparison(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    run: Mapping[str, object],
    version: Mapping[str, object],
) -> None:
    comparison = design_api.comparison(client, project_id)
    if comparison is None or comparison.get("head_run_id") != run.get("id"):
        return
    console = context.console
    package = version.get("package")
    package = package if isinstance(package, Mapping) else {}
    names = twin_names(package)
    screens, elements = places(package)

    def lines(findings: list[Mapping[str, object]]) -> list[str]:
        return [
            context.text(
                "design.comparison_item",
                twin=names.get(str(item.get("twin_id"))) or context.text("design.review_twin"),
                finding=finding_line(context, item, screens, elements),
            )
            for item in findings
        ]

    resolved = _findings(comparison.get("resolved"))
    persisting = _findings(
        [
            item.get("after")
            for item in _list(comparison.get("persisting"))
            if isinstance(item, Mapping)
        ]
    )
    introduced = _findings(comparison.get("introduced"))
    console.say("design.comparison_heading")
    if resolved:
        console.say("design.comparison_resolved", count=len(resolved))
        console.items(lines(resolved))
    else:
        console.say("design.comparison_resolved_none")
    if persisting:
        console.say("design.comparison_persisting", count=len(persisting))
        console.items(lines(persisting))
    else:
        console.say("design.comparison_persisting_none")
    if introduced:
        console.say("design.comparison_introduced", count=len(introduced))
        console.items(lines(introduced))
    else:
        console.say("design.comparison_introduced_none")
    console.write()


def finding_line(
    context: CommandContext,
    finding: Mapping[str, object],
    screens: Mapping[str, str],
    elements: Mapping[str, tuple[str, str]],
) -> str:
    severity = str(finding.get("severity") or "")
    weight = (
        context.text(f"design.weight_{severity}")
        if severity in SEVERITIES
        else severity or context.text("design.weight_unknown")
    )
    summary = " ".join(str(finding.get("summary") or "").split())
    place = place_text(context, finding, screens, elements)
    if place:
        return context.text("design.finding_placed", weight=weight, summary=summary, place=place)
    return context.text("design.finding", weight=weight, summary=summary)


def place_text(
    context: CommandContext,
    finding: Mapping[str, object],
    screens: Mapping[str, str],
    elements: Mapping[str, tuple[str, str]],
) -> str:
    screen, element = placement(finding, screens, elements)
    if screen is not None and element is not None:
        return context.text(
            "design.place_element", screen=screens[screen], element=elements[element][1]
        )
    if screen is not None:
        return context.text("design.place_screen", screen=screens[screen])
    return " ".join(str(finding.get("location") or "").split())


def placement(
    finding: Mapping[str, object],
    screens: Mapping[str, str],
    elements: Mapping[str, tuple[str, str]],
) -> tuple[str | None, str | None]:
    key = finding.get("anchor_key")
    if isinstance(key, str):
        screen, _separator, element = key.partition("/")
        if element and element in elements and elements[element][0] == screen:
            return screen, element
        if screen in screens:
            return screen, None
    match = LEADING_SCREEN.match(str(finding.get("location") or "").strip())
    if match is not None and match[1] in screens:
        return match[1], None
    return None, None


def places(
    package: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    screens: dict[str, str] = {}
    elements: dict[str, tuple[str, str]] = {}
    bound = package.get("generated_mockup")
    mockup = bound.get("mockup") if isinstance(bound, Mapping) else None
    sources = [package.get("prototype"), mockup]
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for screen in _list(source.get("screens")):
            if not isinstance(screen, Mapping):
                continue
            code = screen.get("code")
            title = " ".join(str(screen.get("title") or "").split())
            if not isinstance(code, str) or not title:
                continue
            screens.setdefault(code, title)
            for element in _list(screen.get("elements")):
                if isinstance(element, Mapping) and isinstance(element.get("code"), str):
                    label = _label(element)
                    if label:
                        elements.setdefault(element["code"], (code, label))
    return screens, elements


def twin_names(package: Mapping[str, object]) -> dict[str, str]:
    grounding = package.get("grounding")
    references = grounding.get("user_twin_references") if isinstance(grounding, Mapping) else None
    names: dict[str, str] = {}
    for item in _list(references):
        if isinstance(item, Mapping) and isinstance(item.get("twin_id"), str):
            names[item["twin_id"]] = " ".join(str(item.get("name") or "").split())
    return names


def _reviewed(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    version: Mapping[str, object],
    locale: str,
) -> Mapping[str, object]:
    console = context.console
    label = context.text("design.label_review")
    running = [
        job for job in jobs.running_jobs(client, project_id) if job.get("operation") == REVIEW
    ]
    if running:
        console.say("design.review_running")
        job = running[0]
        tracked = design_generate.Tracked(
            job_id=str(job.get("job_id")),
            operation=REVIEW,
            address=design_api.request_job_path(project_id, str(job.get("job_id"))),
            name=context.text("design.job_review"),
            alternative_id=None,
            job=job,
        )
        return finished_run(design_generate.follow(context, client, [tracked], label=label)[0])
    existing = existing_review(client, project_id, version)
    if existing is not None:
        console.say("design.review_exists")
        return existing
    console.say("design.review_about")
    costs.confirm_spending(context, client, [REVIEW])
    try:
        result = design_generate.generate(
            context,
            client,
            project_id,
            design_api.evaluations_path(project_id),
            design_api.evaluation_body(version, locale),
            label=label,
        )
    except CliError as error:
        if error.code == design_generate.UNREACHABLE:
            raise design_generate.unreachable_while_running(error, label) from None
        raise
    if result.status_code >= 400:
        design_generate.raise_failure(design_generate.failure_of(result.status_code, result.body))
    return _run(result.body, result.status_code)


def _run(body: object, status: int) -> Mapping[str, object]:
    if not isinstance(body, Mapping) or not isinstance(body.get("responses"), list):
        raise ApiFailure("API_FAILURE", http_status=status)
    return body


def _label(element: Mapping[str, object]) -> str:
    for name in ("accessible_name", "content"):
        text = " ".join(str(element.get(name) or "").split())
        if text:
            return text if len(text) <= LABEL_LIMIT else text[: LABEL_LIMIT - 1].rstrip() + "…"
    return ""


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _findings(value: object) -> list[Mapping[str, object]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]
