from __future__ import annotations

import contextlib
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from orchestwin.cli import costs
from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import design_critique as critique_api
from orchestwin.cli.browser import BrowserError, find_browsers, open_page
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import (
    design_change,
    design_generate,
    design_recovery,
    design_state,
    review,
)
from orchestwin.cli.flows.code_order import project_language
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.http import is_loopback

if TYPE_CHECKING:
    from orchestwin.cli.browser import BrowserProgram, PageSnapshot
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.jobs import JobResult
    from orchestwin.cli.project import ProjectFolder

CRITIQUE: Final = "DESIGN_CRITIQUE"
LATEST: Final = "latest"
MEBIBYTE: Final = 1024 * 1024
MICRO_USD: Final = 1_000_000
MAX_IMAGE_BYTES: Final = 5 * MEBIBYTE
MAX_PAGE_BYTES: Final = 200 * 1024
MAX_TITLE_LENGTH: Final = 200
MAX_ADDRESS_LENGTH: Final = 2048
VIEWPORTS: Final = ((1440, 900), (390, 844))
WEB_SCHEMES: Final = ("http", "https")
PNG: Final = "image/png"
JPEG: Final = "image/jpeg"
SUFFIXES: Final = {".png": PNG, ".jpg": JPEG, ".jpeg": JPEG}
SIGNATURES: Final = ((b"\x89PNG\r\n\x1a\n", PNG), (b"\xff\xd8\xff", JPEG))
VERDICTS: Final = ("WORKS", "SLOWS", "BLOCKS")
FILE_TYPE: Final = "DESIGN_CRITIQUE_FILE_TYPE"
FILE_TOO_LARGE: Final = "DESIGN_CRITIQUE_FILE_TOO_LARGE"
FILE_MISSING: Final = "DESIGN_CRITIQUE_FILE_MISSING"
FILE_UNREADABLE: Final = "DESIGN_CRITIQUE_FILE_UNREADABLE"
URL_INVALID: Final = "DESIGN_CRITIQUE_URL_INVALID"
NOT_FOUND: Final = "DESIGN_CRITIQUE_NOT_FOUND"
NUMBER_INVALID: Final = "DESIGN_CRITIQUE_NUMBER_INVALID"
BROWSER_NOT_FOUND: Final = "BROWSER_NOT_FOUND"
REDRAW_TEXT: Final = {
    "it": (
        "Ridisegna il mockup perché riproduca l'aspetto e la struttura del design fornito "
        "«{title}»: stessa disposizione, stessi colori e stessa gerarchia dei contenuti, con le "
        "schermate e i requisiti del progetto."
    ),
    "en": (
        "Redraw the mockup so that it reproduces the look and the structure of the supplied "
        "design “{title}”: same layout, colours and hierarchy of the content, with the screens "
        "and the requirements of the project."
    ),
}


def run(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    *,
    image: str | None = None,
    url: str | None = None,
    redraw: int | None = None,
) -> int:
    if redraw is not None:
        return redraw_as_mockup(context, client, project, redraw)
    if image is not None:
        return critique_image(context, client, project, image)
    if url is not None:
        return critique_url(context, client, project, url)
    return list_critiques(context, client, project)


def critique_number(value: str | None) -> int:
    text = (value or "").strip()
    if text.casefold() == LATEST:
        return 1
    if not (text.isascii() and text.isdigit()) or int(text) < 1:
        raise CliError(NUMBER_INVALID, status=USAGE_STATUS, values={"value": value or ""})
    return int(text)


def critique_image(
    context: CommandContext, client: StudioClient, project: ProjectFolder, value: str
) -> int:
    given = Path(value)
    path = given if given.is_absolute() else context.environment.working_directory / given
    declared = SUFFIXES.get(path.suffix.lower())
    if declared is None:
        raise CliError(FILE_TYPE, status=USAGE_STATUS, values={"path": str(path)})
    if not path.is_file():
        raise CliError(FILE_MISSING, values={"path": str(path)})
    try:
        size = path.stat().st_size
        content = b"" if size > MAX_IMAGE_BYTES else path.read_bytes()
    except OSError:
        raise CliError(FILE_UNREADABLE, values={"path": str(path)}) from None
    if max(size, len(content)) > MAX_IMAGE_BYTES:
        raise too_large(context, path.name, max(size, len(content)))
    title = clipped(path.stem) or clipped(path.name)
    name = path.name if path.name.isascii() and path.name.isprintable() else f"image{path.suffix}"
    context.console.say("design.critique_uploading", title=title)
    source = critique_api.upload_source(
        client,
        project.link().project_id,
        kind=critique_api.IMAGE,
        title=title,
        url=None,
        page=None,
        shots=[(name, image_type(content) or declared, content, None)],
    )
    return critique(context, client, project, source)


def critique_url(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    value: str,
    *,
    capture: Callable[[CommandContext, BrowserProgram, str, int, int], tuple[PageSnapshot, bytes]]
    | None = None,
) -> int:
    address = web_address(value)
    programs = find_browsers(context.environment)
    if not programs:
        raise BrowserError(BROWSER_NOT_FOUND)
    program = programs[0]
    take = capture_page if capture is None else capture
    console = context.console
    captured: list[tuple[int, PageSnapshot, bytes]] = []
    for width, height in VIEWPORTS:
        console.say("design.critique_capturing", browser=program.label, width=width)
        snapshot, image = take(context, program, address, width, height)
        if len(image) > MAX_IMAGE_BYTES:
            raise too_large(context, shot_name(width), len(image))
        captured.append((width, snapshot, image))
    page = captured[0][1]
    title = clipped(page.title) or clipped(urlsplit(address).hostname or address)
    console.say("design.critique_uploading", title=title)
    try:
        source = critique_api.upload_source(
            client,
            project.link().project_id,
            kind=critique_api.WEB_PAGE,
            title=title,
            url=address,
            page=page_document(page),
            shots=[
                (shot_name(width), image_type(image) or PNG, image, width)
                for width, _, image in captured
            ],
        )
    except ApiFailure as failure:
        if failure.code != URL_INVALID:
            raise
        raise CliError(URL_INVALID, status=USAGE_STATUS, values={"address": address}) from None
    return critique(context, client, project, source)


def capture_page(
    context: CommandContext, program: BrowserProgram, address: str, width: int, height: int
) -> tuple[PageSnapshot, bytes]:
    page = open_page(
        context,
        program,
        width=width,
        height=height,
        language=context.language,
        direct=is_loopback(urlsplit(address).hostname or ""),
    )
    try:
        page.open(address)
        snapshot = page.snapshot()
        return snapshot, page.screenshot()
    finally:
        with contextlib.suppress(BrowserError):
            page.close()


def web_address(value: str) -> str:
    address = value.strip()
    invalid = CliError(URL_INVALID, status=USAGE_STATUS, values={"address": value})
    if (
        not address
        or len(address) > MAX_ADDRESS_LENGTH
        or not all(character.isprintable() and not character.isspace() for character in address)
    ):
        raise invalid
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:
        raise invalid from None
    if parts.scheme.lower() not in WEB_SCHEMES or not host:
        raise invalid
    return address


def page_document(snapshot: PageSnapshot) -> dict[str, object]:
    document = snapshot.document()
    elements = document.get("elements")
    kept: list[object] = []
    size = len(_json({**document, "elements": []}))
    for element in elements if isinstance(elements, list) else []:
        size += len(_json(element)) + 2
        if size > MAX_PAGE_BYTES:
            break
        kept.append(element)
    return {**document, "elements": kept}


def critique(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    source: Mapping[str, object],
) -> int:
    console = context.console
    console.say("design.critique_about", title=_text(source.get("title")) or "-")
    costs.confirm_spending(context, client, [CRITIQUE])
    locale = review.review_locale(project_language(project, context.language))
    with console.progress(context.text("design.label_critique")):
        found = critique_api.run_critique(
            client, project.link().project_id, str(source.get("id")), locale
        )
    show_run(context, client, found)
    return 0


def show_run(context: CommandContext, client: StudioClient, run: Mapping[str, object]) -> None:
    console = context.console
    source = _mapping(run.get("source"))
    screens = screen_labels(context, source)
    names = twin_names(run)
    verdicts = {
        (str(item.get("twin_id")), str(item.get("anchor_key"))): item.get("verdict")
        for item in _list(run.get("verdicts"))
        if isinstance(item, Mapping)
    }
    responses = [item for item in _list(run.get("responses")) if isinstance(item, Mapping)]
    console.write()
    console.heading(
        context.text("design.critique_heading", title=_text(source.get("title")) or "-")
    )
    console.say("design.review_simulated" if responses else "design.review_empty")
    for response in responses:
        twin = str(response.get("twin_id"))
        name = names.get(twin) or context.text("design.review_twin")
        summary = _text(response.get("summary"))
        console.write()
        if summary:
            console.say("design.critique_twin", name=name, summary=summary)
        else:
            console.write(name)
        for code, label in screens.items():
            verdict = verdicts.get((twin, code))
            if verdict in VERDICTS:
                console.say(
                    "design.critique_verdict",
                    screen=label,
                    verdict=context.text(f"design.critique_verdict_{verdict}"),
                )
        findings = [item for item in _list(response.get("findings")) if isinstance(item, Mapping)]
        if not findings:
            console.say("design.review_no_findings")
        for finding in findings:
            console.items([review.finding_line(context, finding, screens, {})])
            action = _text(finding.get("recommended_action"))
            if action:
                design_state.wrapped(
                    context, context.text("design.critique_what_to_do", action=action), indent="  "
                )
        gaps = [_text(item) for item in _list(response.get("evidence_gaps")) if _text(item)]
        if gaps:
            design_state.wrapped(
                context, context.text("design.critique_gaps", gaps="; ".join(gaps))
            )
    console.write()
    seconds = seconds_text(run.get("duration_seconds"))
    if costs.uses_subscription(client):
        console.say("design.critique_done_subscription", seconds=seconds)
    else:
        console.say("design.critique_done", seconds=seconds, cost=cost_text(context, run))


def list_critiques(context: CommandContext, client: StudioClient, project: ProjectFolder) -> int:
    console = context.console
    runs = critique_api.critiques(client, project.link().project_id)
    if not runs:
        console.say("design.critique_none")
        return 0
    console.heading(context.text("design.critique_list_heading"))
    for number, item in enumerate(runs, start=1):
        source = _mapping(item.get("source"))
        kind = source.get("kind")
        found = [
            entry.get("verdict")
            for entry in _list(item.get("verdicts"))
            if isinstance(entry, Mapping)
        ]
        console.say(
            "design.critique_list_line",
            number=number,
            date=moment_text(item.get("completed_at")),
            title=_text(source.get("title")) or "-",
            kind=context.text(f"design.critique_kind_{kind}")
            if kind in critique_api.KINDS
            else "-",
            twins=len(_list(item.get("twins"))),
            works=found.count("WORKS"),
            slows=found.count("SLOWS"),
            blocks=found.count("BLOCKS"),
        )
    console.say("design.critique_list_next")
    return 0


def redraw_as_mockup(
    context: CommandContext, client: StudioClient, project: ProjectFolder, number: int
) -> int:
    console = context.console
    project_id = project.link().project_id
    runs = critique_api.critiques(client, project_id)
    if not runs:
        console.say("design.critique_none")
        return 1
    if number > len(runs):
        raise CliError(NOT_FOUND, values={"number": number, "count": len(runs)})
    source = _mapping(runs[number - 1].get("source"))
    title = _text(source.get("title")) or "-"
    state = design_state.read_state(client, project)
    if state.kind == design_state.JOB_RUNNING:
        names = ", ".join(design_generate.track(context, state, job).name for job in state.running)
        console.say("design.wait_running", names=names)
        return 1
    chosen = state.chosen
    if state.version is None or chosen is None or design_change.unavailable(state) is not None:
        console.say("design.critique_redraw_needs_design")
        return 1
    recovery = design_recovery.read(client, project, state)
    if recovery.action is not None:
        design_recovery.explain(context, recovery, error=True)
        return 1
    request = REDRAW_TEXT[redraw_language(context, project)].format(title=title)
    console.say("design.critique_redraw_about", title=title)
    costs.confirm_spending(context, client, [design_change.ITERATION])
    before = design_api.mockup_document(client, project_id, chosen.id, source=design_api.APPLIED)
    body = design_api.iteration_body(state.version, request, ())
    body["critique_source_id"] = source.get("id")
    result = design_generate.generate(
        context,
        client,
        project_id,
        design_api.iteration_jobs_path(project_id),
        body,
        label=context.text("design.label_redraw"),
        job_path=lambda job_id: design_api.iteration_job_path(project_id, job_id),
    )
    status = design_change.finish(
        context,
        client,
        project,
        state,
        iteration_result(result),
        request=request,
        before=before,
        reviewing=False,
    )
    current = design_api.current(client, project_id)
    reached = None if current is None else current.get("version_number")
    if status == 0 and reached is not None and reached != state.version_number:
        console.say("design.critique_redrawn", title=title, version=reached)
    return status


def iteration_result(result: JobResult) -> Mapping[str, object]:
    body = result.body
    job = body if isinstance(body, Mapping) and isinstance(body.get("job_id"), str) else None
    if job is not None and result.status_code < 400:
        value = job.get("result")
        if isinstance(value, Mapping) and isinstance(value.get("package"), Mapping):
            return value
        raise ApiFailure("API_FAILURE", http_status=result.status_code)
    failure = design_generate.failure_of(result.status_code, body)
    if job is not None and job.get("status") == design_change.REJECTED:
        reasons = "; ".join(design_generate.failure_reasons(job))
        raise CliError(
            "GENERATION_REJECTED",
            values={"code": failure.code, "detail": reasons or failure.code},
        )
    design_generate.raise_failure(failure)


def redraw_language(context: CommandContext, project: ProjectFolder) -> str:
    language = project_language(project, context.language)
    return "it" if language.strip().lower().startswith("it") else "en"


def screen_labels(context: CommandContext, source: Mapping[str, object]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for number, shot in enumerate(_list(source.get("shots")), start=1):
        code = shot.get("code") if isinstance(shot, Mapping) else None
        if not isinstance(code, str):
            continue
        width = shot.get("viewport_width")
        if isinstance(width, int) and not isinstance(width, bool):
            labels[code] = context.text("design.critique_screen", number=number, width=width)
        else:
            labels[code] = context.text("design.critique_image")
    return labels


def twin_names(run: Mapping[str, object]) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in _list(run.get("twins")):
        if isinstance(item, Mapping):
            twin, name = item.get("twin_id"), item.get("name")
        elif isinstance(item, list | tuple) and len(item) == 3:
            twin, _, name = item
        else:
            continue
        if isinstance(twin, str):
            names[twin] = _text(name)
    return names


def image_type(content: bytes) -> str | None:
    return next((media for signature, media in SIGNATURES if content.startswith(signature)), None)


def shot_name(width: int) -> str:
    return f"screenshot-{width}.png"


def too_large(context: CommandContext, name: str, size: int) -> CliError:
    shown = f"{size / MEBIBYTE:.1f}"
    return CliError(
        FILE_TOO_LARGE,
        values={
            "name": name,
            "size": shown.replace(".", ",") if context.language == "it" else shown,
        },
    )


def clipped(text: str) -> str:
    return " ".join(text.split())[:MAX_TITLE_LENGTH].rstrip()


def seconds_text(value: object) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value):
        return str(max(round(value), 0))
    return "-"


def cost_text(context: CommandContext, run: Mapping[str, object]) -> str:
    cost = run.get("cost_microusd")
    amount = cost / MICRO_USD if isinstance(cost, int) and not isinstance(cost, bool) else 0.0
    return costs.usd_text(amount, context.language)


def _json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []
