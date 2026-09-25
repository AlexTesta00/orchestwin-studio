from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from typing import Final

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.mockup_layout import (
    BUTTON,
    CARD,
    COLUMN_ZONE,
    HEADING,
    LIST,
    SELECT,
    STATUS,
    TEXT,
    TEXT_INPUT,
    layout_zones,
)
from orchestwin.artifacts.visual_catalog import (
    NEUTRAL_VISUAL_CHOICES,
    LayoutArchetype,
    NavigationPattern,
    resolve_visual_tokens,
)

MOCKUP_HTML_FILE: Final = "design/mockup.html"

_STYLE: Final = """
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:var(--vl-color-background);color:var(--vl-color-text);font-family:var(--vl-font-body);font-size:var(--vl-size-body);line-height:var(--vl-line-height)}
.shell{min-height:100vh;display:grid;grid-template-rows:auto 1fr}
.bg-TINTED{background:var(--vl-color-surface-alt)}
.bg-GRADIENT{background:linear-gradient(160deg,var(--vl-color-primary-soft),var(--vl-color-background) 60%)}
.bg-DOTS{background-image:radial-gradient(var(--vl-color-border) 1px,transparent 1px);background-size:18px 18px}
.bg-GRID{background-image:linear-gradient(var(--vl-color-border) 1px,transparent 1px),linear-gradient(90deg,var(--vl-color-border) 1px,transparent 1px);background-size:28px 28px}
.bg-STRIPES{background-image:repeating-linear-gradient(135deg,var(--vl-color-surface-alt) 0 12px,transparent 12px 24px)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:var(--vl-gap);padding:var(--vl-space) calc(var(--vl-space)*2);border-bottom:var(--vl-border-width) solid var(--vl-color-border);background:var(--vl-color-surface);flex-wrap:wrap}
.header-HERO_BAND .bar{background:var(--vl-color-primary);color:var(--vl-color-on-primary);padding:calc(var(--vl-space)*3) calc(var(--vl-space)*2);border-bottom:0}
.header-HERO_BAND .bar a{color:inherit}
.header-MINIMAL .bar{background:transparent;border-bottom:0}
.header-CENTERED_TITLE .bar{justify-content:center;text-align:center;flex-direction:column}
.brand{margin:0;font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:var(--vl-size-title)}
.links{display:flex;gap:calc(var(--vl-space)/2);flex-wrap:wrap}
.links a{color:inherit;text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);font-weight:600}
.links a:hover{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.nav-TABS .links a{border-radius:0;border-bottom:2px solid transparent}
.nav-TABS .links a:hover{background:transparent;border-bottom-color:var(--vl-color-primary)}
.layout{display:grid;gap:var(--vl-gap);padding:calc(var(--vl-space)*2);align-items:start}
.rail{display:grid;gap:calc(var(--vl-space)/2);align-content:start;background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:var(--vl-space)}
.rail a{color:inherit;text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);font-weight:600}
.rail a:hover{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.screen{display:none}
.screen:target{display:block}
.screen:first-of-type{display:block}
main:has(.screen:target) .screen:first-of-type:not(:target){display:none}
.title{margin:0 0 var(--vl-gap);font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:var(--vl-size-display);line-height:1.15}
h2{margin:0;font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:var(--vl-size-title);line-height:1.25}
p{margin:0}
.zones{display:grid;gap:var(--vl-gap)}
.zone{display:grid;gap:var(--vl-gap)}
.zone-tiles{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}
.zone-gallery{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}
.zone-thread{gap:calc(var(--vl-space))}
.bubble{max-width:78%;padding:var(--vl-space) calc(var(--vl-space)*1.5);border-radius:var(--vl-radius-panel);background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border)}
.bubble.person{margin-left:auto;background:var(--vl-color-primary-soft)}
.zone-composer,.zone-search{display:flex;gap:var(--vl-space);align-items:end;flex-wrap:wrap}
.zone-composer label,.zone-search label{flex:1 1 200px}
.zone-search{max-width:680px;margin:0 auto;width:100%}
.zone-search input{min-height:calc(var(--vl-control-height)*1.2)}
table{width:100%;border-collapse:collapse;background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);overflow:hidden}
td{padding:var(--vl-space);border-bottom:1px solid var(--vl-color-border);text-align:left;vertical-align:top}
tr:nth-child(even) td{background:var(--vl-color-surface-alt)}
.zone-timeline{border-left:2px solid var(--vl-color-primary);padding-left:var(--vl-gap)}
.columns{display:grid;gap:var(--vl-gap);grid-template-columns:repeat(auto-fit,minmax(200px,1fr));align-items:start}
.column{background:var(--vl-color-surface-alt);border-radius:var(--vl-radius-panel);padding:var(--vl-space);display:grid;gap:var(--vl-space);align-content:start}
.card{background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:calc(var(--vl-space)*1.5);box-shadow:var(--vl-shadow)}
.status{border-radius:var(--vl-radius-panel);padding:calc(var(--vl-space)*1.5);font-weight:600;border:max(1px,var(--vl-border-width)) solid}
.status-ok{background:var(--vl-color-success-soft);color:var(--vl-color-success);border-color:var(--vl-color-success)}
.status-error{background:var(--vl-color-danger-soft);color:var(--vl-color-danger);border-color:var(--vl-color-danger)}
ul{margin:0;padding-left:1.25em}
label{display:grid;gap:calc(var(--vl-space)/2);font-weight:600;color:var(--vl-color-text-muted)}
input,select{min-height:var(--vl-control-height);padding:0 var(--vl-space);font:inherit;color:var(--vl-color-text);background:var(--vl-color-surface);border:max(1px,var(--vl-border-width)) solid var(--vl-color-border);border-radius:var(--vl-radius-control);width:100%}
.inputs-UNDERLINED input,.inputs-UNDERLINED select{border-width:0 0 2px;border-radius:0;background:transparent;padding-left:0}
.inputs-FILLED input,.inputs-FILLED select{background:var(--vl-color-surface-alt);border-color:transparent}
.button{display:inline-flex;align-items:center;justify-content:center;min-height:var(--vl-control-height);padding:0 calc(var(--vl-space)*2);border-radius:var(--vl-radius-control);font:inherit;font-weight:700;text-decoration:none;cursor:pointer;border:max(1px,var(--vl-border-width)) solid transparent;background:var(--vl-color-primary);color:var(--vl-color-on-primary);justify-self:start}
.buttons-OUTLINED .button{border-color:var(--vl-color-primary);color:var(--vl-color-primary);background:transparent}
.buttons-SOFT .button{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.buttons-GHOST .button{background:transparent;color:var(--vl-color-primary);text-decoration:underline}
.emphasis-BOLD .button{min-height:calc(var(--vl-control-height)*1.15);font-size:1.05em}
.button[aria-disabled=true]{opacity:.6;cursor:default}
.link{color:var(--vl-color-accent);font-weight:600;justify-self:start}
.stepper{display:flex;gap:calc(var(--vl-space)/2);flex-wrap:wrap;margin-bottom:var(--vl-gap)}
.stepper a{color:var(--vl-color-text-muted);text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);font-weight:600}
.stepper a:hover{color:var(--vl-color-primary)}
.frame{background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:calc(var(--vl-space)*2);box-shadow:var(--vl-shadow)}
.shell-SINGLE_CARD .screen,.shell-GUIDED_STEPS .screen{max-width:560px;margin:0 auto;width:100%}
.shell-FOCUS_MODE .screen{max-width:520px;margin:0 auto;width:100%;text-align:center}
.shell-FOCUS_MODE .zone{justify-items:center}
.shell-FOCUS_MODE .title{font-size:calc(var(--vl-size-display)*1.15)}
.shell-CONVERSATIONAL .screen{max-width:720px;margin:0 auto;width:100%}
.shell-SEARCH_FIRST .zone-intro{text-align:center}
.footnote{padding:var(--vl-space) calc(var(--vl-space)*2);color:var(--vl-color-text-muted);font-size:.85em}
@media (min-width:768px){
.nav-SIDE_RAIL .layout{grid-template-columns:minmax(160px,220px) 1fr}
.split{display:grid;gap:var(--vl-gap);align-items:start}
.shell-LIST_DETAIL .split{grid-template-columns:2fr 3fr}
.shell-SPLIT_SCREEN .split{grid-template-columns:1fr 1fr}
.zone-main.two-columns{grid-template-columns:1fr 1fr}
.zone-main.two-columns>h2,.zone-main.two-columns>p,.zone-main.two-columns>.button,.zone-main.two-columns>.link,.zone-main.two-columns>.status,.zone-main.two-columns>ul{grid-column:1/-1}
}
"""


def _attr(value: object) -> str:
    return escape(str(value), quote=True)


def _text(value: object) -> str:
    return escape(str(value), quote=False)


def _screen_anchor(code: str) -> str:
    return code.lower()


def _element_html(
    element: Mapping[str, object],
    *,
    zone: str,
    state: str,
    index: int,
    targets: Mapping[str, str],
) -> str:
    kind = str(element["kind"])
    content = _text(element["content"])
    label = _text(element.get("accessible_name") or element["content"])
    if kind == HEADING:
        return f"<h2>{content}</h2>"
    if kind == TEXT:
        if zone == "thread":
            side = "person" if index % 2 == 0 else "system"
            return f'<div class="bubble {side}">{content}</div>'
        return f"<p>{content}</p>"
    if kind == LIST:
        if zone == "table":
            cells = "".join(
                f"<td>{_text(cell.strip())}</td>" for cell in str(element["content"]).split(" · ")
            )
            return f"<tr>{cells}</tr>"
        return f"<ul><li>{content}</li></ul>"
    if kind == CARD:
        return f'<div class="card">{content}</div>'
    if kind == STATUS:
        tone = "status-error" if state == "ERROR" else "status-ok"
        return f'<p class="status {tone}" role="status">{content}</p>'
    if kind in {TEXT_INPUT, SELECT}:
        name = _attr(element.get("field_name") or element["id"])
        required = " required" if element.get("required") else ""
        if kind == TEXT_INPUT:
            control = f'<input type="text" name="{name}"{required}>'
        else:
            options = "".join(
                f"<option>{_text(option)}</option>" for option in element.get("options", ())
            )
            control = (
                f'<select name="{name}"{required}><option value="">—</option>{options}</select>'
            )
        return f"<label>{label}{control}</label>"
    target = targets.get(str(element["id"]))
    css = "button" if kind == BUTTON else "link"
    if target is None:
        return f'<span class="{css}" aria-disabled="true">{content}</span>'
    return f'<a class="{css}" href="#{_attr(_screen_anchor(target))}">{content}</a>'


def _zone_html(zone: str, elements: Sequence[Mapping[str, object]], state: str, targets) -> str:
    inner = "".join(
        _element_html(element, zone=zone, state=state, index=index, targets=targets)
        for index, element in enumerate(elements)
    )
    if zone == "table":
        return f'<div class="zone zone-table"><table><tbody>{inner}</tbody></table></div>'
    if zone == COLUMN_ZONE:
        return f'<div class="column">{inner}</div>'
    classes = f"zone zone-{zone}"
    if zone == "main" and sum(1 for item in elements if item["kind"] in {TEXT_INPUT, SELECT}) > 1:
        classes += " two-columns"
    return f'<div class="{classes}">{inner}</div>'


def _screen_html(
    screen: Mapping[str, object],
    *,
    archetype: LayoutArchetype,
    targets: Mapping[str, str],
    stepper: str,
) -> str:
    zones = layout_zones(archetype, screen["elements"])
    parts = []
    columns = [items for name, items in zones if name == COLUMN_ZONE]
    others = [(name, items) for name, items in zones if name != COLUMN_ZONE]
    state = str(screen["state"])
    if columns:
        parts.append(
            '<div class="columns">'
            + "".join(_zone_html(COLUMN_ZONE, items, state, targets) for items in columns)
            + "</div>"
        )
    rendered = [_zone_html(name, items, state, targets) for name, items in others]
    if archetype in {LayoutArchetype.LIST_DETAIL, LayoutArchetype.SPLIT_SCREEN} and (
        len(rendered) == 2
    ):
        parts.append('<div class="split">' + "".join(rendered) + "</div>")
    else:
        parts.extend(rendered)
    body = "".join(parts)
    if archetype in {LayoutArchetype.SINGLE_CARD, LayoutArchetype.GUIDED_STEPS}:
        body = f'<div class="frame">{body}</div>'
    return (
        f'<section class="screen" id="{_attr(_screen_anchor(str(screen["code"])))}" '
        f'data-state="{_attr(state)}" aria-label="{_attr(screen["title"])}">'
        f'{stepper}<h1 class="title">{_text(screen["title"])}</h1>'
        f'<div class="zones">{body}</div></section>'
    )


def _screen_links(screens: Sequence[Mapping[str, object]]) -> str:
    return "".join(
        f'<a href="#{_attr(_screen_anchor(str(screen["code"])))}">{_text(screen["title"])}</a>'
        for screen in screens
    )


def render_mockup_html(package: Mapping[str, object], *, language: str = "en") -> str:
    prototype = package.get("prototype")
    alternatives = {item["id"]: item for item in package["alternatives"]}
    alternative = (
        None if prototype is None else alternatives.get(prototype["design_alternative_id"])
    )
    visual = None if alternative is None else alternative.get("visual_language")
    if visual is None:
        choices = NEUTRAL_VISUAL_CHOICES.to_snapshot()
        tokens = resolve_visual_tokens(NEUTRAL_VISUAL_CHOICES)
        product = "" if prototype is None else str(prototype["title"])
    else:
        choices = dict(visual["choices"])
        tokens = dict(visual["tokens"])
        product = str(visual["product_name"])
    style = ";".join(f"{name}:{value}" for name, value in tokens.items())
    head = (
        f'<!doctype html><html lang="{_attr(language)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_text(product or 'Mockup')}</title><style>{_STYLE}</style></head>"
    )
    if prototype is None:
        return (
            head + f'<body style="{_attr(style)}"><main class="layout"><p class="footnote">'
            "No declarative prototype was recorded for the selected alternative."
            "</p></main></body></html>"
        )
    archetype = LayoutArchetype(choices["archetype"])
    navigation = NavigationPattern(choices["navigation"])
    screens_by_id = {screen["id"]: screen for screen in prototype["screens"]}
    targets = {
        str(transition["trigger_element_id"]): str(
            screens_by_id[transition["target_screen_id"]]["code"]
        )
        for transition in prototype["transitions"]
    }
    entry = screens_by_id[prototype["entry_screen_id"]]
    screens = [entry, *[screen for screen in prototype["screens"] if screen["id"] != entry["id"]]]
    links = _screen_links(screens)
    header_links = (
        f'<nav class="links" aria-label="Screens">{links}</nav>'
        if navigation in {NavigationPattern.TOP_BAR, NavigationPattern.TABS}
        else ""
    )
    header = f'<header class="bar"><p class="brand">{_text(product)}</p>{header_links}</header>'
    rail = (
        f'<aside class="rail" aria-label="Screens">{links}</aside>'
        if navigation is NavigationPattern.SIDE_RAIL
        else ""
    )
    stepper = (
        f'<nav class="stepper" aria-label="Steps">{links}</nav>'
        if archetype is LayoutArchetype.GUIDED_STEPS
        else ""
    )
    sections = "".join(
        _screen_html(screen, archetype=archetype, targets=targets, stepper=stepper)
        for screen in screens
    )
    shell = (
        f"shell shell-{choices['archetype']} nav-{choices['navigation']} "
        f"header-{choices['header']} bg-{choices['background']} buttons-{choices['buttons']} "
        f"inputs-{choices['inputs']} emphasis-{choices['emphasis']}"
    )
    return (
        head + f'<body style="{_attr(style)}"><div class="{_attr(shell)}">{header}'
        f'<div class="layout">{rail}<main>{sections}</main></div>'
        f'<p class="footnote">{_text(prototype["title"])} · {_text(prototype["code"])}</p>'
        "</div></body></html>"
    )


def _shorten(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_evaluation_document(
    package: Mapping[str, object], *, language: str = "und", max_content: int | None = None
) -> str:
    prototype = package.get("prototype")
    if prototype is None:
        raise ValueError("an evaluation document requires a prototype")
    alternatives = {item["id"]: item for item in package["alternatives"]}
    alternative = alternatives[prototype["design_alternative_id"]]
    visual = alternative.get("visual_language")
    product = str(prototype["title"]) if visual is None else str(visual["product_name"])
    choices = None if visual is None else visual["choices"]
    screens_by_id = {screen["id"]: screen for screen in prototype["screens"]}
    targets = {
        str(transition["trigger_element_id"]): str(
            screens_by_id[transition["target_screen_id"]]["code"]
        )
        for transition in prototype["transitions"]
    }
    entry = screens_by_id[prototype["entry_screen_id"]]
    screens = [entry, *[screen for screen in prototype["screens"] if screen["id"] != entry["id"]]]
    parts = [
        f'<!doctype html><html lang="{_attr(language)}"><head><meta charset="utf-8">'
        f"<title>{_text(product)}</title></head><body><header><h1>{_text(product)}</h1>"
    ]
    parts.append(f"<p>{_text(_shorten(str(alternative['summary']), max_content))}</p>")
    if choices is not None:
        described = "; ".join(f"{key}: {value}" for key, value in choices.items())
        parts.append(f'<p data-role="visual-language">{_text(described)}</p>')
    parts.append("</header><main>")
    for screen in screens:
        elements = [
            {**element, "content": _shorten(str(element["content"]), max_content)}
            for element in screen["elements"]
        ]
        body = "".join(
            _element_html(
                element, zone="main", state=str(screen["state"]), index=index, targets=targets
            )
            for index, element in enumerate(elements)
        )
        parts.append(
            f'<section id="{_attr(_screen_anchor(str(screen["code"])))}" '
            f'data-state="{_attr(str(screen["state"]))}"><h2>{_text(screen["title"])}</h2>{body}</section>'
        )
    parts.append("</main></body></html>")
    return "".join(parts)


def mockup_html(version: DesignPackageVersion) -> str:
    return render_mockup_html(version.package.to_snapshot())


__all__ = ["MOCKUP_HTML_FILE", "mockup_html", "render_evaluation_document", "render_mockup_html"]
