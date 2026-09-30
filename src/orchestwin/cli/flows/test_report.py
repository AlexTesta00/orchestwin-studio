from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.flows import align_review, test_plan
from orchestwin.cli.flows.design_state import bullets, wrapped
from orchestwin.cli.project import json_bytes, read_json, write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

RUN_NAME: Final = "run.json"
REPORT_NAME: Final = "report.html"
LATEST_NAME: Final = "latest.json"
IGNORE_NAME: Final = ".gitignore"
IGNORE_CONTENT: Final = b"*\n"
LATEST_SCHEMA_VERSION: Final = 1
FOLDER_FORMAT: Final = "%Y%m%d-%H%M%S"
SCREENSHOT_WIDTH: Final = 480
STATEMENT_LIMIT: Final = 90
MICRO_USD: Final = 1_000_000
REQUIREMENTS_DOCUMENT: Final = ("requirements", "requirements.json")
STATUS_KEYS: Final[Mapping[str, str]] = {
    tests_api.PASSED: "test.status_passed",
    tests_api.FAILED: "test.status_failed",
    tests_api.BLOCKED: "test.status_blocked",
    tests_api.NOT_COVERED: "test.status_not_covered",
    tests_api.NOT_RUN: "test.status_not_run",
}
STEP_STATUS_KEYS: Final[Mapping[str, str]] = {
    tests_api.DONE: "test.step_done",
    tests_api.FAILED: "test.step_failed",
    tests_api.BLOCKED: "test.step_blocked",
    tests_api.SKIPPED: "test.step_skipped",
}
ACTION_KEYS: Final[Mapping[str, str]] = {
    tests_api.OPEN: "test.step_open",
    tests_api.CLICK: "test.step_click",
    tests_api.TYPE: "test.step_type",
    tests_api.SELECT: "test.step_select",
    tests_api.PRESS: "test.step_press",
    tests_api.CHECK: "test.step_check",
}
EXPECTATION_KEYS: Final[Mapping[str, str]] = {
    tests_api.TEXT_VISIBLE: "test.expect_text_visible",
    tests_api.TEXT_ABSENT: "test.expect_text_absent",
    tests_api.ELEMENT_VISIBLE: "test.expect_element_visible",
    tests_api.ELEMENT_ABSENT: "test.expect_element_absent",
    tests_api.VALUE_IS: "test.expect_value_is",
    tests_api.URL_CONTAINS: "test.expect_url_contains",
    tests_api.TITLE_CONTAINS: "test.expect_title_contains",
}
VERDICT_KEYS: Final[Mapping[str, str]] = {
    tests_api.FINE: "test.verdict_fine",
    tests_api.CONCERN: "test.verdict_concern",
    tests_api.DRIFT: "test.verdict_drift",
}
SEVERITY_KEYS: Final[Mapping[str, str]] = {
    "LOW": "test.severity_low",
    "MEDIUM": "test.severity_medium",
    "HIGH": "test.severity_high",
}
WEAK_KEYS: Final[Mapping[str, str]] = {
    test_plan.VISIBLE_AT_OPENING: "test.weak_visible",
    test_plan.HIDDEN_AT_OPENING: "test.weak_hidden",
    test_plan.ABSENT_VISIBLE_AT_OPENING: "test.weak_absent_visible",
    test_plan.NEVER_ON_PAGE: "test.weak_absent",
}
STATUS_CLASSES: Final[Mapping[str, str]] = {
    tests_api.PASSED: "passed",
    tests_api.DONE: "passed",
    tests_api.FAILED: "failed",
    tests_api.BLOCKED: "blocked",
    tests_api.NOT_COVERED: "muted",
    tests_api.NOT_RUN: "muted",
    tests_api.SKIPPED: "muted",
}
STYLES: Final = (
    ":root{color-scheme:light}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:#f4f6f8;color:#1b1f24;"
    'font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
    "main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}"
    "h1{margin:0 0 8px;font-size:1.75rem;line-height:1.25}"
    "h2{margin:0 0 8px;font-size:1.25rem;line-height:1.3}"
    "h3{margin:0 0 4px;font-size:1rem}"
    "p{margin:0 0 8px}"
    ".lead{color:#48525c;max-width:70ch}"
    ".summary{font-weight:600}"
    "section{margin:24px 0 0;padding:20px;background:#fff;border:1px solid #d3d9df;"
    "border-radius:12px}"
    "article{margin:16px 0 0;padding:16px 0 0;border-top:1px solid #e3e7eb}"
    ".code{font-weight:600;letter-spacing:.02em}"
    ".chip{display:inline-block;margin:0 0 0 8px;padding:2px 8px;border-radius:999px;"
    "font-size:.8125rem;font-weight:600;background:#eceff2;color:#1b1f24}"
    ".chip.passed{background:#e3f3e8;color:#0f5c33}"
    ".chip.failed{background:#fbe7e6;color:#8f1d16}"
    ".chip.blocked{background:#fdf0dc;color:#7a4a00}"
    ".chip.muted{background:#eceff2;color:#48525c}"
    ".chip.weak{background:#efe7fb;color:#4a2485}"
    ".weak{color:#4a2485}"
    ".muted{color:#48525c}"
    "ol,ul{margin:8px 0 0;padding-left:24px;display:grid;gap:12px}"
    ".detail{font-style:italic}"
    "img{display:block;max-width:100%;height:auto;margin:4px 0 0;border:1px solid #d3d9df;"
    "border-radius:4px}"
)


@dataclass(frozen=True, slots=True)
class Names:
    criteria: Mapping[str, str]
    requirements: Mapping[str, str]
    screens: Mapping[str, str]


def names(project: ProjectFolder) -> Names:
    titles = align_review.titles(project)
    return Names(
        criteria=statements(project),
        requirements=titles.requirements,
        screens=titles.screens,
    )


def statements(project: ProjectFolder) -> dict[str, str]:
    document = read_json(project.knowledge.joinpath(*REQUIREMENTS_DOCUMENT))
    specification = document.get("specification") if isinstance(document, Mapping) else None
    items = specification.get("acceptance_criteria") if isinstance(specification, Mapping) else None
    found: dict[str, str] = {}
    for item in tests_api.mappings(items):
        code = item.get("code")
        statement = _text(item.get("statement"))
        if isinstance(code, str) and code and statement:
            found[code] = statement
    return found


def moment_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "-"
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return value.strip()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def run_folder(tests: Path, moment: datetime) -> Path:
    tests.mkdir(parents=True, exist_ok=True)
    ignore = tests / IGNORE_NAME
    if not ignore.exists():
        write_atomically(ignore, IGNORE_CONTENT)
    stem = moment.astimezone(UTC).strftime(FOLDER_FORMAT)
    candidate = tests / stem
    number = 1
    while True:
        try:
            candidate.mkdir()
        except FileExistsError:
            number += 1
            candidate = tests / f"{stem}-{number}"
            continue
        return candidate


def write_run(
    folder: Path,
    run: Mapping[str, object],
    *,
    first_attempt: Sequence[Mapping[str, object]] = (),
) -> Path:
    document = dict(run)
    if first_attempt:
        document["first_attempt"] = [dict(item) for item in first_attempt]
    path = folder / RUN_NAME
    write_atomically(path, json_bytes(document))
    return path


def write_latest(tests: Path, folder: Path, run: Mapping[str, object]) -> Path:
    document = {
        "schema_version": LATEST_SCHEMA_VERSION,
        "run_id": run.get("id"),
        "folder": folder.name,
        "report": f"{folder.name}/{REPORT_NAME}",
        "finished_at": run.get("finished_at"),
    }
    path = tests / LATEST_NAME
    write_atomically(path, json_bytes(document))
    return path


def write_report(
    context: CommandContext,
    folder: Path,
    run: Mapping[str, object],
    *,
    project_name: str,
    names: Names,
    labels: Mapping[str, str],
    first_attempt: Sequence[Mapping[str, object]] = (),
    weak: Sequence[Mapping[str, object]] = (),
) -> Path:
    page = report_html(
        context,
        run,
        project_name=project_name,
        names=names,
        labels=labels,
        first_attempt=first_attempt,
        weak=weak,
    )
    path = folder / REPORT_NAME
    write_atomically(path, page.encode("utf-8"))
    return path


def report_html(
    context: CommandContext,
    run: Mapping[str, object],
    *,
    project_name: str,
    names: Names,
    labels: Mapping[str, str],
    first_attempt: Sequence[Mapping[str, object]] = (),
    weak: Sequence[Mapping[str, object]] = (),
) -> str:
    title = context.text("test.report_title", name=project_name)
    lead = context.text(
        "test.report_lead",
        date=moment_text(run.get("finished_at")),
        application=application_text(context, run.get("application")),
        browsers=browsers_text(run.get("browsers"), labels),
    )
    marks = weak_marks(run, weak)
    sections = [
        _criterion_section(context, run, item, names, labels, marks)
        for item in tests_api.criteria_of(run)
    ]
    lines = [
        "<!doctype html>",
        f'<html lang="{_escape(context.language)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="referrer" content="no-referrer">',
        f"<title>{_escape(title)}</title>",
        f"<style>{STYLES}</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{_escape(title)}</h1>",
        f'<p class="lead">{_escape(lead)}</p>',
        f'<p class="summary">{_escape(summary_text(context, run))}</p>',
    ]
    if marks:
        counted = context.text("test.report_weak", count=len(marks))
        lines.append(f'<p class="weak">{_escape(counted)}</p>')
    lines.extend([*sections, _critiques_section(context, run, names)])
    if first_attempt:
        lines.append(_first_attempt_section(context, first_attempt, labels))
    lines.extend(["</main>", "</body>", "</html>"])
    return "\n".join(lines) + "\n"


def application_text(context: CommandContext, application: object) -> str:
    found = application if isinstance(application, Mapping) else {}
    address = str(found.get("address") or "-")
    if found.get("kind") == tests_api.STATIC:
        return context.text("test.report_on_static", folder=address)
    return context.text("test.report_on_url", address=address)


def browsers_text(browsers: object, labels: Mapping[str, str]) -> str:
    parts = []
    for item in tests_api.mappings(browsers):
        name = str(item.get("name") or "")
        version = _text(item.get("version"))
        label = labels.get(name) or name
        parts.append(f"{label} {version}".strip())
    return ", ".join(parts) or "-"


def summary_text(context: CommandContext, run: Mapping[str, object]) -> str:
    return context.text("test.summary", **tests_api.numbers(run))


def status_text(context: CommandContext, status: object) -> str:
    key = STATUS_KEYS.get(status) if isinstance(status, str) else None
    return context.text(key) if key else str(status or "-")


def show_table(
    context: CommandContext, run: Mapping[str, object], labels: Mapping[str, str]
) -> None:
    rows = []
    results = tests_api.results_of(run)
    for item in tests_api.criteria_of(run):
        code = str(item.get("code") or "-")
        paths = tests_api.texts(item.get("paths"))
        browsers = tests_api.ordered(
            [
                str(result.get("browser") or "")
                for result in results
                if code in tests_api.texts(_path(result).get("criteria"))
            ]
        )
        rows.append(
            [
                code,
                status_text(context, item.get("status")),
                ", ".join(paths) or "-",
                ", ".join(labels.get(name) or name for name in browsers if name) or "-",
            ]
        )
    context.console.table(
        [
            context.text("test.column_criterion"),
            context.text("test.column_status"),
            context.text("test.column_paths"),
            context.text("test.column_browsers"),
        ],
        rows,
    )


def show_summary(context: CommandContext, run: Mapping[str, object]) -> None:
    context.console.write(summary_text(context, run))


def show_weak(context: CommandContext, weak: Sequence[Mapping[str, object]]) -> None:
    lines = [line for line in (weak_sentence(context, item) for item in weak) if line]
    if not lines:
        return
    context.console.say("test.weak_count", count=len(lines))
    context.console.items(lines)


def weak_sentence(context: CommandContext, item: Mapping[str, object]) -> str:
    kind = item.get("kind")
    key = WEAK_KEYS.get(kind) if isinstance(kind, str) else None
    if key is None:
        return ""
    return context.text(
        key,
        path=str(item.get("path") or "-"),
        step=item.get("step"),
        text=_text(item.get("text")),
    )


def weak_marks(
    run: Mapping[str, object], weak: Sequence[Mapping[str, object]]
) -> dict[tuple[str, int], Mapping[str, object]]:
    shown = {str(_path(result).get("code") or "") for result in tests_api.results_of(run)}
    marks: dict[tuple[str, int], Mapping[str, object]] = {}
    for item in weak:
        path, step, kind = item.get("path"), item.get("step"), item.get("kind")
        if not isinstance(path, str) or path not in shown or not isinstance(kind, str):
            continue
        if kind in WEAK_KEYS and isinstance(step, int) and not isinstance(step, bool):
            marks.setdefault((path, step), item)
    return marks


def show_review(
    context: CommandContext,
    critiques: Sequence[Mapping[str, object]],
    names: Names,
    *,
    cost_microusd: object = None,
) -> None:
    console = context.console
    console.write()
    console.heading(context.text("test.review_heading"))
    if not critiques:
        console.say("test.no_critiques")
    for critique in critiques:
        console.write()
        console.write(
            context.text(
                "test.twin_line",
                name=_text(critique.get("twin_name")) or context.text("test.twin_unknown"),
                verdict=verdict_text(context, critique.get("verdict")),
            )
        )
        summary = _text(critique.get("summary"))
        if summary:
            wrapped(context, summary, indent="  ")
        findings = tests_api.mappings(critique.get("findings"))
        if findings:
            bullets(context, [finding_line(context, item, names) for item in findings], indent="  ")
        else:
            wrapped(context, context.text("test.no_findings"), indent="  ")
    if isinstance(cost_microusd, int) and not isinstance(cost_microusd, bool) and cost_microusd > 0:
        console.write()
        console.say(
            "test.review_cost",
            amount=costs.usd_text(cost_microusd / MICRO_USD, context.language),
        )


def verdict_text(context: CommandContext, verdict: object) -> str:
    key = VERDICT_KEYS.get(verdict) if isinstance(verdict, str) else None
    return context.text(key) if key else str(verdict or "-")


def finding_line(context: CommandContext, finding: Mapping[str, object], names: Names) -> str:
    severity = finding.get("severity")
    key = SEVERITY_KEYS.get(severity) if isinstance(severity, str) else None
    line = context.text(
        "test.finding",
        severity=context.text(key) if key else str(severity or "-"),
        text=_text(finding.get("text")),
    )
    about = finding.get("about")
    about = about if isinstance(about, Mapping) else {}
    parts = [
        part
        for part in (
            _about(context, about.get("criterion"), names.criteria, "criterion", STATEMENT_LIMIT),
            _about(context, about.get("requirement"), names.requirements, "requirement", None),
            _about(context, about.get("screen"), names.screens, "screen", None),
        )
        if part
    ]
    if parts:
        line = context.text("test.finding_about", finding=line, about=", ".join(parts))
    action = _text(finding.get("action"))
    if action:
        line = context.text("test.finding_action", finding=line, action=action)
    return line


def target_text(target: object) -> str:
    if not isinstance(target, Mapping):
        return "-"
    name = _text(target.get("name"))
    role = target.get("role")
    return f"{role}: {name}" if isinstance(role, str) and role else name


def expectation_text(expect: object) -> str:
    if not isinstance(expect, Mapping):
        return "-"
    kind = str(expect.get("kind") or "-")
    text = _text(expect.get("text"))
    if kind == tests_api.VALUE_IS:
        return f"{kind}: {target_text(expect.get('target'))} = {text}"
    if kind in (tests_api.ELEMENT_VISIBLE, tests_api.ELEMENT_ABSENT):
        return f"{kind}: {target_text(expect.get('target'))}"
    return f"{kind}: {text}"


def step_text(context: CommandContext, step: object) -> str:
    if not isinstance(step, Mapping):
        return "-"
    action = step.get("action")
    key = ACTION_KEYS.get(action) if isinstance(action, str) else None
    described = (
        context.text(
            key,
            value=_text(step.get("value")),
            target=_target_words(context, step.get("target")),
        )
        if key
        else str(action or "-")
    )
    expect = step.get("expect")
    if isinstance(expect, Mapping):
        described = context.text(
            "test.step_expecting",
            step=described,
            expectation=expectation_words(context, expect),
        )
    return described


def expectation_words(context: CommandContext, expect: Mapping[str, object]) -> str:
    kind = expect.get("kind")
    key = EXPECTATION_KEYS.get(kind) if isinstance(kind, str) else None
    if key is None:
        return expectation_text(expect)
    return context.text(
        key,
        text=_text(expect.get("text")),
        target=_target_words(context, expect.get("target")),
    )


def _target_words(context: CommandContext, target: object) -> str:
    if not isinstance(target, Mapping):
        return "-"
    name = _text(target.get("name"))
    role = target.get("role")
    if isinstance(role, str) and role:
        return context.text("test.target", role=role, name=name)
    return context.text("test.target_name", name=name)


def _about(
    context: CommandContext,
    code: object,
    titles: Mapping[str, str],
    kind: str,
    limit: int | None,
) -> str:
    if not isinstance(code, str) or not code:
        return ""
    title = titles.get(code)
    if title and limit is not None and len(title) > limit:
        title = title[: limit - 1].rstrip() + "…"
    if title:
        return context.text(f"test.about_{kind}", code=code, title=title)
    return context.text(f"test.about_{kind}_code", code=code)


def _criterion_section(
    context: CommandContext,
    run: Mapping[str, object],
    item: Mapping[str, object],
    names: Names,
    labels: Mapping[str, str],
    marks: Mapping[tuple[str, int], Mapping[str, object]],
) -> str:
    code = str(item.get("code") or "-")
    status = item.get("status")
    parts = [
        '<section class="criterion">',
        f'<h2><span class="code">{_escape(code)}</span>{_chip(context, status)}</h2>',
    ]
    statement = names.criteria.get(code)
    if statement:
        parts.append(f"<p>{_escape(statement)}</p>")
    results = [
        result
        for result in tests_api.results_of(run)
        if code in tests_api.texts(_path(result).get("criteria"))
    ]
    if status == tests_api.NOT_COVERED:
        reason = next(
            (
                _text(entry.get("reason"))
                for entry in tests_api.mappings(run.get("not_covered"))
                if entry.get("criterion") == code
            ),
            "",
        )
        text = context.text("test.report_not_covered", reason=reason or "-")
        parts.append(f'<p class="muted">{_escape(text)}</p>')
    elif not results:
        parts.append(f'<p class="muted">{_escape(context.text("test.report_not_run"))}</p>')
    parts.extend(_result_article(context, result, labels, marks) for result in results)
    parts.append("</section>")
    return "\n".join(parts)


def _result_article(
    context: CommandContext,
    result: Mapping[str, object],
    labels: Mapping[str, str],
    marks: Mapping[tuple[str, int], Mapping[str, object]] | None = None,
) -> str:
    path = _path(result)
    code = str(path.get("code") or "-")
    browser = str(result.get("browser") or "")
    label = labels.get(browser) or browser or "-"
    seconds = result.get("seconds")
    shown = f"{float(seconds):.1f}" if isinstance(seconds, int | float) else "-"
    heading = context.text("test.report_path", code=code, browser=label, seconds=shown)
    planned = tests_api.mappings(path.get("steps"))
    items = []
    for step in tests_api.mappings(result.get("steps")):
        index = step.get("index")
        position = index if isinstance(index, int) and not isinstance(index, bool) else 0
        described = (
            step_text(context, planned[position - 1]) if 0 < position <= len(planned) else "-"
        )
        item = [
            f'<li class="step">{_chip(context, step.get("status"), step=True)} {_escape(described)}'
        ]
        mark = (marks or {}).get((code, position))
        if mark is not None:
            word = context.text("test.report_weak_mark")
            item.append(f' <span class="chip weak">{_escape(word)}</span>')
            item.append(f'<p class="weak">{_escape(weak_sentence(context, mark))}</p>')
        detail = _text(step.get("detail"))
        if detail:
            item.append(f'<p class="detail">{_escape(detail)}</p>')
        place = " - ".join(
            part for part in (_text(step.get("title")), _text(step.get("url"))) if part
        )
        if place:
            item.append(f'<p class="muted">{_escape(place)}</p>')
        screenshot = step.get("screenshot")
        if isinstance(screenshot, str) and screenshot:
            alternative = context.text(
                "test.report_screenshot", index=position, code=code, browser=label
            )
            item.append(
                f'<img src="{_escape(screenshot)}" width="{SCREENSHOT_WIDTH}" '
                f'alt="{_escape(alternative)}">'
            )
        item.append("</li>")
        items.append("".join(item))
    parts = [
        '<article class="path">',
        f"<h3>{_escape(heading)}{_chip(context, result.get('status'))}</h3>",
    ]
    title = _text(path.get("heading"))
    if title:
        parts.append(f"<p>{_escape(title)}</p>")
    if items:
        parts.append(f'<ol class="steps">{"".join(items)}</ol>')
    page_text = _text(result.get("page_text"))
    if page_text:
        text = context.text("test.report_page_text", text=page_text)
        parts.append(f'<p class="muted">{_escape(text)}</p>')
    parts.append("</article>")
    return "\n".join(parts)


def _critiques_section(context: CommandContext, run: Mapping[str, object], names: Names) -> str:
    critiques = tests_api.critiques_of(run)
    parts = [
        '<section class="critiques">',
        f"<h2>{_escape(context.text('test.review_heading'))}</h2>",
    ]
    if not critiques:
        parts.append(f'<p class="muted">{_escape(context.text("test.report_no_review"))}</p>')
    for critique in critiques:
        name = _text(critique.get("twin_name")) or context.text("test.twin_unknown")
        line = context.text(
            "test.twin_line", name=name, verdict=verdict_text(context, critique.get("verdict"))
        )
        parts.append(f"<h3>{_escape(line)}</h3>")
        summary = _text(critique.get("summary"))
        if summary:
            parts.append(f"<p>{_escape(summary)}</p>")
        findings = [
            finding_line(context, item, names)
            for item in tests_api.mappings(critique.get("findings"))
        ]
        if findings:
            listed = "".join(f"<li>{_escape(finding)}</li>" for finding in findings)
            parts.append(f"<ul>{listed}</ul>")
        else:
            parts.append(f'<p class="muted">{_escape(context.text("test.no_findings"))}</p>')
    parts.append("</section>")
    return "\n".join(parts)


def _first_attempt_section(
    context: CommandContext,
    results: Sequence[Mapping[str, object]],
    labels: Mapping[str, str],
) -> str:
    parts = [
        '<section class="first-attempt">',
        f"<h2>{_escape(context.text('test.report_first_attempt'))}</h2>",
        f'<p class="muted">{_escape(context.text("test.report_first_attempt_lead"))}</p>',
        *(_result_article(context, result, labels) for result in results),
        "</section>",
    ]
    return "\n".join(parts)


def _chip(context: CommandContext, status: object, *, step: bool = False) -> str:
    keys = STEP_STATUS_KEYS if step else STATUS_KEYS
    key = keys.get(status) if isinstance(status, str) else None
    word = context.text(key) if key else str(status or "-")
    style = STATUS_CLASSES.get(status, "muted") if isinstance(status, str) else "muted"
    return f' <span class="chip {style}">{_escape(word)}</span>'


def _path(result: Mapping[str, object]) -> Mapping[str, object]:
    path = result.get("path")
    return path if isinstance(path, Mapping) else {}


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)
