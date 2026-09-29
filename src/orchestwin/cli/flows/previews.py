from __future__ import annotations

import contextlib
import html
import re
import webbrowser
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.flows import design_state
from orchestwin.cli.project import write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import Alternative, DesignState
    from orchestwin.cli.project import ProjectFolder

INDEX_NAME: Final = "index.html"
PAGE_SUFFIX: Final = ".html"
BEFORE_SUFFIX: Final = "-before"
UNSAFE_NAME: Final = re.compile(r"[^A-Za-z0-9_-]+")
STYLES: Final = (
    ":root{color-scheme:light}"
    "*{box-sizing:border-box}"
    "body{margin:0;background:#f4f6f8;color:#1b1f24;"
    'font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}'
    "main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}"
    "h1{margin:0 0 8px;font-size:1.75rem;line-height:1.25}"
    "h2{margin:0;font-size:1.25rem;line-height:1.3}"
    "h3{margin:4px 0 0;font-size:1rem}"
    "p{margin:0}"
    ".lead{margin:0 0 24px;color:#48525c;max-width:65ch}"
    ".cards{list-style:none;margin:0;padding:0;display:grid;gap:16px;"
    "grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))}"
    ".card{display:flex;flex-direction:column;gap:12px;padding:20px;background:#fff;"
    "border:1px solid #d3d9df;border-radius:12px}"
    ".card.chosen{border:2px solid #0f5c33}"
    ".code{font-size:.875rem;font-weight:600;letter-spacing:.02em;color:#48525c}"
    ".badge{display:inline-block;margin:0 0 0 8px;padding:2px 8px;border-radius:999px;"
    "font-size:.8125rem;font-weight:600;background:#e6eefb;color:#0b4a8b}"
    ".badge.chosen{background:#e3f3e8;color:#0f5c33}"
    ".muted{color:#48525c}"
    ".verdicts{margin:0;padding-left:20px;display:grid;gap:6px}"
    ".points{margin:4px 0 0;padding-left:20px;display:grid;gap:4px}"
    ".actions{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:auto;padding-top:4px}"
    "a{color:#0b57a4;font-weight:600;text-decoration:underline;text-underline-offset:3px}"
    "a:hover{color:#083d73}"
    "a:focus-visible{outline:3px solid #0b57a4;outline-offset:3px;border-radius:4px}"
    ".missing{color:#48525c;font-style:italic}"
)


@dataclass(frozen=True, slots=True)
class Change:
    alternative_id: str
    request: str
    before_html: str | None
    before_version: int | None
    after_version: int | None


def file_name(alternative: Alternative, *, before: bool = False) -> str:
    stem = UNSAFE_NAME.sub("-", alternative.code).strip("-") or f"alternative-{alternative.number}"
    return f"{stem}{BEFORE_SUFFIX if before else ''}{PAGE_SUFFIX}"


def write_previews(
    context: CommandContext,
    project: ProjectFolder,
    state: DesignState,
    *,
    change: Change | None = None,
) -> Path:
    folder = project.previews
    folder.mkdir(parents=True, exist_ok=True)
    written = {INDEX_NAME}
    pages: dict[str, str] = {}
    for alternative in state.alternatives:
        document = state.documents.get(alternative.id)
        content = None if document is None else document.get("html")
        if not isinstance(content, str):
            continue
        name = file_name(alternative)
        write_atomically(folder / name, content.encode("utf-8"))
        written.add(name)
        pages[alternative.id] = name
    before: str | None = None
    changed = None if change is None else state.alternative_by_id(change.alternative_id)
    if change is not None and changed is not None and change.before_html is not None:
        before = file_name(changed, before=True)
        write_atomically(folder / before, change.before_html.encode("utf-8"))
        written.add(before)
    index = folder / INDEX_NAME
    page = index_html(context, state, pages, change=change if before else None, before=before)
    write_atomically(index, page.encode("utf-8"))
    for stale in folder.glob(f"*{PAGE_SUFFIX}"):
        if stale.name not in written and stale.is_file():
            with contextlib.suppress(OSError):
                stale.unlink()
    return index


def open_page(context: CommandContext, path: Path) -> bool:
    try:
        opened = bool(context.environment.open_browser(path.as_uri()))
    except (OSError, ValueError, webbrowser.Error):
        opened = False
    key = "design.previews_opened" if opened else "design.previews_not_opened"
    context.console.say(key, path=str(path))
    return opened


def index_html(
    context: CommandContext,
    state: DesignState,
    pages: Mapping[str, str],
    *,
    change: Change | None = None,
    before: str | None = None,
) -> str:
    title = context.text("design.page_title", project=state.project_name)
    cards = [
        _card(context, state, alternative, pages.get(alternative.id), change, before)
        for alternative in state.alternatives
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
        f'<p class="lead">{_escape(context.text("design.page_lead"))}</p>',
        '<ul class="cards">',
        *cards,
        "</ul>",
        "</main>",
        "</body>",
        "</html>",
    ]
    return "\n".join(lines) + "\n"


def _card(
    context: CommandContext,
    state: DesignState,
    alternative: Alternative,
    page: str | None,
    change: Change | None,
    before: str | None,
) -> str:
    chosen = state.chosen is not None and state.chosen.id == alternative.id
    badges = []
    if alternative.recommended:
        badges.append(
            f'<span class="badge">{_escape(context.text("design.page_recommended"))}</span>'
        )
    if chosen:
        badges.append(
            f'<span class="badge chosen">{_escape(context.text("design.page_chosen"))}</span>'
        )
    parts = [
        f'<li class="card{" chosen" if chosen else ""}">',
        f'<p class="code">{_escape(alternative.code)}{"".join(badges)}</p>',
        f"<h2>{_escape(alternative.title)}</h2>",
    ]
    if alternative.summary:
        parts.append(f"<p>{_escape(alternative.summary)}</p>")
    if alternative.product_name:
        product = context.text("design.page_product", name=alternative.product_name)
        parts.append(f'<p class="muted">{_escape(product)}</p>')
    verdicts = _verdicts(context, state, alternative)
    if verdicts:
        parts.append(f"<h3>{_escape(context.text('design.page_twins'))}</h3>")
        parts.append(f'<ul class="verdicts">{"".join(verdicts)}</ul>')
    if change is not None and before is not None and change.alternative_id == alternative.id:
        request = context.text("design.page_change", request=change.request)
        parts.append(f'<p class="muted">{_escape(request)}</p>')
        links = [
            _link(before, context.text("design.page_before", version=change.before_version or "-")),
        ]
        if page is not None:
            after = context.text("design.page_after", version=change.after_version or "-")
            links.append(_link(page, after))
        parts.append(f'<p class="actions">{"".join(links)}</p>')
    elif page is not None:
        label = context.text("design.page_open", code=alternative.code)
        parts.append(f'<p class="actions">{_link(page, label)}</p>')
    else:
        parts.append(f'<p class="missing">{_escape(context.text("design.page_missing"))}</p>')
    parts.append("</li>")
    return "".join(parts)


def _verdicts(context: CommandContext, state: DesignState, alternative: Alternative) -> list[str]:
    items = []
    for verdict in state.verdicts:
        if verdict.alternative_id != alternative.id:
            continue
        text = _escape(verdict.verdict or "")
        if verdict.quote:
            quote = _escape(context.text("design.page_quote", quote=verdict.quote))
            text = f"{text} {quote}" if text else quote
        points = [] if verdict.verdict else design_state.point_lines(context, verdict)
        if not text and not points:
            continue
        body = f"<strong>{_escape(verdict.twin_name)}</strong>"
        if text:
            body = f"{body}: {text}"
        if points:
            listed = "".join(f"<li>{_escape(line)}</li>" for line in points)
            body = f'{body}<ul class="points">{listed}</ul>'
        items.append(f"<li>{body}</li>")
    return items


def _link(target: str, label: str) -> str:
    return f'<a href="{_escape(target)}">{_escape(label)}</a>'


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)
