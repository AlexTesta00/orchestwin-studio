from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from itertools import groupby, pairwise
from string import Template
from typing import Final

from orchestwin.artifacts.design_packages import DesignExplorationPackage, DesignPackageVersion
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.mockup_layout import (
    BUTTON,
    CARD,
    COLUMN_ZONE,
    HEADING,
    LINK,
    LIST,
    MAIN_ZONE,
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
UNDETERMINED_LANGUAGE: Final = "und"
PAGE_WIDTH_PIXELS: Final = 1100
SINGLE_COLUMN_FIELDS: Final = 3
FIGURE_LENGTH: Final = 40
TABLE_ZONE: Final = "table"
CARD_GRID_ZONES: Final = frozenset({MAIN_ZONE, "aside"})
FIELD_KINDS: Final = frozenset({TEXT_INPUT, SELECT})
ACTION_KINDS: Final = frozenset({BUTTON, LINK})
TILE_KINDS: Final = frozenset({STATUS, CARD})
SPLIT_ARCHETYPES: Final = frozenset({LayoutArchetype.LIST_DETAIL, LayoutArchetype.SPLIT_SCREEN})
_PAIR: Final = "PAIR"
_NUMBERED_ITEM: Final = re.compile(r"(?<!\S)(\d+)[.)](?=\s)")
_TRAILING_GROUP: Final = re.compile(r"\s*\([^()]*\)$")

_STYLE: Final = Template(
    """
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:var(--vl-color-background);color:var(--vl-color-text);font-family:var(--vl-font-body);font-size:var(--vl-size-body);line-height:var(--vl-line-height);overflow-wrap:anywhere}
.shell{--page:${page}px;--gutter:clamp(12px,3vw,calc(var(--vl-space)*2));min-height:100vh;display:grid;grid-template-rows:auto 1fr auto;background:var(--vl-color-background)}
.bg-TINTED,.bg-DOTS,.bg-GRID,.bg-STRIPES{background:var(--vl-color-surface-alt)}
.bg-GRADIENT{background:linear-gradient(180deg,var(--vl-color-primary-soft),var(--vl-color-background) 440px)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:var(--vl-gap);padding:var(--vl-space) max(var(--gutter),calc((100% - var(--page))/2));border-bottom:var(--vl-border-width) solid var(--vl-color-border);background:var(--vl-color-surface);flex-wrap:wrap}
.header-HERO_BAND .bar{background:var(--vl-color-primary);color:var(--vl-color-on-primary);padding-top:calc(var(--vl-space)*3);padding-bottom:calc(var(--vl-space)*3);border-bottom:0}
.header-HERO_BAND .bar a{color:inherit}
.header-MINIMAL .bar{background:transparent;border-bottom:0}
.header-CENTERED_TITLE .bar{justify-content:center;text-align:center;flex-direction:column}
.brand{margin:0;font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:min(var(--vl-size-title),7vw)}
.links{display:flex;gap:calc(var(--vl-space)/2);flex-wrap:wrap}
.links a{color:inherit;text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);font-weight:600}
.links a:hover{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.nav-TABS .links a{border-radius:0;border-bottom:2px solid transparent}
.nav-TABS .links a:hover{background:transparent;border-bottom-color:var(--vl-color-primary)}
.layout{display:grid;grid-template-columns:minmax(0,1fr);align-content:center;gap:var(--vl-gap);width:100%;max-width:calc(var(--page) + 2*var(--gutter));margin:0 auto;padding:var(--gutter)}
main{min-width:0;background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);box-shadow:var(--vl-shadow);padding:clamp(16px,3vw,calc(var(--vl-space)*2.5))}
.rail{display:grid;gap:calc(var(--vl-space)/2);align-content:start;background:var(--vl-color-surface);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:var(--vl-space)}
.rail a{color:inherit;text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);font-weight:600}
.rail a:hover{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.screen{display:none}
.screen:target{display:block}
.screen:first-of-type{display:block}
main:has(.screen:target) .screen:first-of-type:not(:target){display:none}
.title{margin:0 0 var(--vl-gap);font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:min(var(--vl-size-display),8.5vw);line-height:1.15}
h2{margin:0;font-family:var(--vl-font-heading);font-weight:var(--vl-heading-weight);text-transform:var(--vl-heading-transform);font-variant:var(--vl-heading-variant);letter-spacing:var(--vl-heading-tracking);font-size:var(--vl-size-title);line-height:1.25}
p{margin:0}
.zones{display:grid;gap:calc(var(--vl-gap)*1.25)}
.zone{display:grid;gap:var(--vl-gap);align-content:start;min-width:0}
.zone>h2:not(:first-child){margin-top:calc(var(--vl-gap)/2)}
.zone>p:not(.status){max-width:72ch}
.zone-main>label{max-width:560px}
.zone-tiles{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.zone-gallery{grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.zone-thread{gap:var(--vl-space)}
.bubble{max-width:78%;padding:var(--vl-space) calc(var(--vl-space)*1.5);border-radius:var(--vl-radius-panel);background:var(--vl-color-surface-alt);border:var(--vl-border-width) solid var(--vl-color-border)}
.bubble.person{margin-left:auto;background:var(--vl-color-primary-soft)}
.zone-composer,.zone-search{display:flex;gap:var(--vl-space);align-items:end;flex-wrap:wrap}
.zone-composer label,.zone-search label{flex:1 1 200px}
.zone-search{max-width:680px;margin:0 auto;width:100%}
.zone-search input{min-height:calc(var(--vl-control-height)*1.2)}
.zone-table{overflow-x:auto}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--vl-color-surface);border:max(1px,var(--vl-border-width)) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);overflow:hidden}
td{padding:var(--vl-space) calc(var(--vl-space)*1.5);border-top:1px solid var(--vl-color-border);text-align:left;vertical-align:top}
tr:first-child td{border-top:0}
tr:nth-child(even) td{background:var(--vl-color-surface-alt)}
.list{margin:0;padding:0;list-style:none;background:var(--vl-color-surface);border:max(1px,var(--vl-border-width)) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);overflow:hidden}
.list li{padding:var(--vl-space) calc(var(--vl-space)*1.5);border-top:1px solid var(--vl-color-border)}
.list li:first-child{border-top:0}
.cards{display:grid;gap:var(--vl-gap);grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.zone-timeline{border-left:2px solid var(--vl-color-primary);padding-left:var(--vl-gap)}
.columns{display:grid;gap:var(--vl-gap);grid-template-columns:repeat(auto-fit,minmax(220px,1fr));align-items:start}
.column{background:var(--vl-color-surface-alt);border-radius:var(--vl-radius-panel);padding:var(--vl-space);display:grid;gap:var(--vl-space);align-content:start}
.card{background:var(--vl-color-surface-alt);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:calc(var(--vl-space)*1.5)}
.column .card{background:var(--vl-color-surface);box-shadow:var(--vl-shadow)}
.status{border-radius:var(--vl-radius-panel);padding:calc(var(--vl-space)*1.5);font-weight:600;border:max(1px,var(--vl-border-width)) solid}
.status-ok{background:var(--vl-color-success-soft);color:var(--vl-color-success);border-color:var(--vl-color-success)}
.status-error{background:var(--vl-color-danger-soft);color:var(--vl-color-danger);border-color:var(--vl-color-danger)}
.zone-tiles .status-ok{background:var(--vl-color-surface-alt);color:var(--vl-color-text);border-color:var(--vl-color-border)}
.tile-label{display:block}
.figure{display:block;margin-top:calc(var(--vl-space)/2);font-family:var(--vl-font-heading);font-size:var(--vl-size-title);font-weight:var(--vl-heading-weight);line-height:1.2}
.pairs{margin:0;max-width:760px;background:var(--vl-color-surface-alt);border:var(--vl-border-width) solid var(--vl-color-border);border-radius:var(--vl-radius-panel);padding:0 calc(var(--vl-space)*1.5)}
.pair{display:grid;gap:calc(var(--vl-space)/4);padding:var(--vl-space) 0;border-top:1px solid var(--vl-color-border)}
.pair:first-child{border-top:0}
.pair dt{color:var(--vl-color-text-muted);font-weight:600}
.pair dd{margin:0}
label{display:grid;gap:calc(var(--vl-space)/2);font-weight:600;color:var(--vl-color-text-muted)}
input,select{min-height:var(--vl-control-height);padding:0 var(--vl-space);font:inherit;color:var(--vl-color-text);background:var(--vl-color-surface);border:max(1px,var(--vl-border-width)) solid var(--vl-color-border);border-radius:var(--vl-radius-control);width:100%;min-width:0}
.inputs-UNDERLINED input,.inputs-UNDERLINED select{border-width:0 0 2px;border-radius:0;background:transparent;padding-left:0}
.inputs-FILLED input,.inputs-FILLED select{background:var(--vl-color-surface-alt);border-color:transparent}
.button{display:inline-flex;align-items:center;justify-content:center;min-height:var(--vl-control-height);max-width:100%;padding:0 calc(var(--vl-space)*2);border-radius:var(--vl-radius-control);font:inherit;font-weight:700;text-align:center;text-decoration:none;cursor:pointer;border:max(1px,var(--vl-border-width)) solid transparent;background:var(--vl-color-primary);color:var(--vl-color-on-primary);justify-self:start}
.buttons-OUTLINED .button{border-color:var(--vl-color-primary);color:var(--vl-color-primary);background:transparent}
.buttons-SOFT .button{background:var(--vl-color-primary-soft);color:var(--vl-color-primary)}
.buttons-GHOST .button{background:transparent;color:var(--vl-color-primary);text-decoration:underline}
.emphasis-BOLD .button{min-height:calc(var(--vl-control-height)*1.15);font-size:1.05em}
.button[aria-disabled=true]{opacity:.6;cursor:default}
.link{color:var(--vl-color-accent);font-weight:600;justify-self:start}
.stepper{display:flex;gap:calc(var(--vl-space)/2);flex-wrap:wrap;margin-bottom:var(--vl-gap)}
.stepper a{color:var(--vl-color-text-muted);text-decoration:none;padding:calc(var(--vl-space)/2) var(--vl-space);border-radius:var(--vl-radius-control);background:var(--vl-color-surface-alt);border:var(--vl-border-width) solid var(--vl-color-border);font-weight:600}
.stepper a:hover{color:var(--vl-color-primary)}
.shell-FOCUS_MODE main{width:100%;max-width:640px;justify-self:center}
.shell-FOCUS_MODE .screen{text-align:center}
.shell-FOCUS_MODE .zone{justify-items:center}
.shell-FOCUS_MODE .button,.shell-FOCUS_MODE .link{justify-self:center}
.shell-FOCUS_MODE .zone>label,.shell-FOCUS_MODE .list,.shell-FOCUS_MODE .cards,.shell-FOCUS_MODE .pairs{width:100%}
.shell-FOCUS_MODE .title{font-size:min(calc(var(--vl-size-display)*1.15),9.5vw)}
.shell-CONVERSATIONAL main{width:100%;max-width:820px;justify-self:center}
.shell-SEARCH_FIRST .zone-intro{text-align:center;justify-items:center}
.split{display:grid;gap:calc(var(--vl-gap)*1.5);align-items:start}
.footnote{width:100%;max-width:calc(var(--page) + 2*var(--gutter));margin:0 auto;padding:0 var(--gutter) var(--gutter);color:var(--vl-color-text-muted);font-size:.85em}
@media (min-width:768px){
.nav-SIDE_RAIL .layout{grid-template-columns:minmax(160px,220px) minmax(0,1fr)}
.pair{grid-template-columns:minmax(0,1fr) minmax(0,2fr);gap:var(--vl-gap)}
.shell-LIST_DETAIL .split{grid-template-columns:minmax(0,2fr) minmax(0,3fr)}
.shell-SPLIT_SCREEN .split{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
.zone-main.two-columns{grid-template-columns:repeat(2,minmax(0,1fr))}
.zone-main.two-columns>:not(label){grid-column:1/-1}
.zone-main.two-columns>label{max-width:none}
}
"""
).substitute(page=PAGE_WIDTH_PIXELS)


def _attr(value: object) -> str:
    return escape(str(value), quote=True)


def _text(value: object) -> str:
    return escape(str(value), quote=False)


def _screen_anchor(code: str) -> str:
    return code.lower()


def _plain_key(text: object) -> str:
    return " ".join(str(text).casefold().split()).rstrip(" :*.!?")


def _label_key(text: object) -> str:
    return _plain_key(_TRAILING_GROUP.sub("", _plain_key(text)))


def _repeats_label(paragraph: Mapping[str, object], field: Mapping[str, object]) -> bool:
    key = _label_key(paragraph["content"])
    labels = (field.get("accessible_name") or field["content"], field["content"])
    return bool(key) and any(key == _label_key(label) for label in labels)


def _visible_elements(screen: Mapping[str, object], product: str) -> list[Mapping[str, object]]:
    elements = list(screen["elements"])
    repeated = {_plain_key(screen["title"]), _plain_key(product)}
    visible = []
    for element, following in zip(elements, [*elements[1:], None], strict=True):
        if element["kind"] == HEADING and _plain_key(element["content"]) in repeated:
            continue
        if (
            element["kind"] == TEXT
            and following is not None
            and following["kind"] in FIELD_KINDS
            and _repeats_label(element, following)
        ):
            continue
        visible.append(element)
    return visible


def _is_label(element: Mapping[str, object]) -> bool:
    return element["kind"] == TEXT and str(element["content"]).rstrip().endswith(":")


def _display_elements(
    screen: Mapping[str, object], *, archetype: LayoutArchetype, product: str
) -> list[Mapping[str, object]]:
    elements = _visible_elements(screen, product)
    merged: list[Mapping[str, object]] = []
    index = 0
    while index < len(elements):
        element = elements[index]
        following = elements[index + 1] if index + 1 < len(elements) else None
        if following is not None and following["kind"] == TEXT and not _is_label(following):
            if (
                archetype is LayoutArchetype.DASHBOARD
                and element["kind"] in TILE_KINDS
                and len(str(following["content"])) <= FIGURE_LENGTH
            ):
                merged.append({**element, "figure": following["content"]})
                index += 2
                continue
            if _is_label(element):
                merged.append({**element, "value": following["content"]})
                index += 2
                continue
        merged.append(element)
        index += 1
    return merged


def _list_items(content: str) -> list[str]:
    starts = []
    for match in _NUMBERED_ITEM.finditer(content):
        if int(match.group(1)) == len(starts) + 1:
            starts.append(match.start())
    if len(starts) < 2:
        return [content]
    pieces = (content[start:end].strip() for start, end in pairwise([0, *starts, len(content)]))
    return [piece for piece in pieces if piece]


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
        cells = "".join(
            f"<td>{_text(cell.strip())}</td>" for cell in str(element["content"]).split(" · ")
        )
        return f"<tr>{cells}</tr>"
    if "figure" in element:
        content = (
            f'<span class="tile-label">{content}</span>'
            f'<span class="figure">{_text(element["figure"])}</span>'
        )
    if kind == CARD:
        return f'<div class="card">{content}</div>'
    if kind == STATUS:
        tone = "status-error" if state == "ERROR" else "status-ok"
        return f'<p class="status {tone}" role="status">{content}</p>'
    if kind in FIELD_KINDS:
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


def _list_html(elements: Iterable[Mapping[str, object]]) -> str:
    items = "".join(
        f"<li>{_text(item)}</li>"
        for element in elements
        for item in _list_items(str(element["content"]))
    )
    return f'<ul class="list">{items}</ul>'


def _cards_html(elements: Iterable[Mapping[str, object]]) -> str:
    cards = "".join(f'<div class="card">{_text(element["content"])}</div>' for element in elements)
    return f'<div class="cards">{cards}</div>'


def _pair_label(element: Mapping[str, object]) -> str:
    return str(element["content"]).rstrip().removesuffix(":").rstrip()


def _pairs_html(elements: Iterable[Mapping[str, object]]) -> str:
    rows = "".join(
        f'<div class="pair"><dt>{_text(_pair_label(element))}</dt>'
        f"<dd>{_text(element['value'])}</dd></div>"
        for element in elements
    )
    return f'<dl class="pairs">{rows}</dl>'


def _run_kind(item: tuple[int, Mapping[str, object]]) -> object:
    element = item[1]
    return _PAIR if "value" in element else element["kind"]


def _zone_parts(
    zone: str, elements: Sequence[Mapping[str, object]], state: str, targets: Mapping[str, str]
) -> list[str]:
    parts = []
    for kind, group in groupby(enumerate(elements), key=_run_kind):
        run = list(group)
        if kind == _PAIR:
            parts.append(_pairs_html(element for _, element in run))
        elif kind == LIST and zone != TABLE_ZONE:
            parts.append(_list_html(element for _, element in run))
        elif kind == CARD and zone in CARD_GRID_ZONES:
            parts.append(_cards_html(element for _, element in run))
        else:
            parts.extend(
                _element_html(element, zone=zone, state=state, index=index, targets=targets)
                for index, element in run
            )
    return parts


def _zone_html(
    zone: str, elements: Sequence[Mapping[str, object]], state: str, targets: Mapping[str, str]
) -> str:
    inner = "".join(_zone_parts(zone, elements, state, targets))
    if zone == TABLE_ZONE:
        return f'<div class="zone zone-table"><table><tbody>{inner}</tbody></table></div>'
    if zone == COLUMN_ZONE:
        return f'<div class="column">{inner}</div>'
    classes = f"zone zone-{zone}"
    fields = sum(1 for item in elements if item["kind"] in FIELD_KINDS)
    if zone == MAIN_ZONE and fields > SINGLE_COLUMN_FIELDS:
        classes += " two-columns"
    return f'<div class="{classes}">{inner}</div>'


def _splits(archetype: LayoutArchetype, zones: Sequence[tuple[str, Sequence]]) -> bool:
    return (
        archetype in SPLIT_ARCHETYPES
        and len(zones) == 2
        and all(any(item["kind"] not in ACTION_KINDS for item in items) for _, items in zones)
    )


def _screen_html(
    screen: Mapping[str, object],
    *,
    archetype: LayoutArchetype,
    product: str,
    targets: Mapping[str, str],
    stepper: str,
) -> str:
    zones = layout_zones(archetype, _display_elements(screen, archetype=archetype, product=product))
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
    if _splits(archetype, others):
        parts.append('<div class="split">' + "".join(rendered) + "</div>")
    else:
        parts.extend(rendered)
    return (
        f'<section class="screen" id="{_attr(_screen_anchor(str(screen["code"])))}" '
        f'data-state="{_attr(state)}" aria-label="{_attr(screen["title"])}">'
        f'{stepper}<h1 class="title">{_text(screen["title"])}</h1>'
        f'<div class="zones">{"".join(parts)}</div></section>'
    )


def _screen_links(screens: Sequence[Mapping[str, object]], *, numbered: bool = False) -> str:
    links = []
    for position, screen in enumerate(screens, 1):
        prefix = f"{position}. " if numbered else ""
        anchor = _attr(_screen_anchor(str(screen["code"])))
        links.append(f'<a href="#{anchor}">{prefix}{_text(screen["title"])}</a>')
    return "".join(links)


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
            head + f'<body style="{_attr(style)}"><div class="shell"><div class="layout"><main>'
            "<p>No declarative prototype was recorded for the selected alternative.</p>"
            "</main></div></div></body></html>"
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
        f'<nav class="stepper" aria-label="Steps">{_screen_links(screens, numbered=True)}</nav>'
        if archetype is LayoutArchetype.GUIDED_STEPS
        else ""
    )
    sections = "".join(
        _screen_html(screen, archetype=archetype, product=product, targets=targets, stepper=stepper)
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


def _review_element_html(
    element: Mapping[str, object], *, state: str, targets: Mapping[str, str]
) -> str:
    kind = str(element["kind"])
    identifier = _attr(str(element["code"]).lower())
    content = _text(element["content"])
    name = str(element.get("accessible_name") or element["content"])
    if kind == HEADING:
        return f'<h3 id="{identifier}">{content}</h3>'
    if kind == TEXT:
        return f'<p id="{identifier}">{content}</p>'
    if kind == LIST:
        return f'<ul id="{identifier}"><li>{content}</li></ul>'
    if kind == CARD:
        return f'<article id="{identifier}">{content}</article>'
    if kind == STATUS:
        role = "alert" if state == "ERROR" else "status"
        return f'<p id="{identifier}" role="{role}">{content}</p>'
    if kind in {TEXT_INPUT, SELECT}:
        field = _attr(element.get("field_name") or element["code"])
        required = ' required aria-required="true"' if element.get("required") else ""
        label = f'<label for="{identifier}">{_text(name)}</label>'
        if kind == TEXT_INPUT:
            return f'{label}<input type="text" id="{identifier}" name="{field}"{required}>'
        options = "".join(
            f"<option>{_text(option)}</option>" for option in element.get("options", ())
        )
        return f'{label}<select id="{identifier}" name="{field}"{required}>{options}</select>'
    target = targets.get(str(element["id"]))
    described = "" if name == str(element["content"]) else f' aria-label="{_attr(name)}"'
    if kind == BUTTON:
        leads = "" if target is None else f' data-target="{_attr(_screen_anchor(target))}"'
        return f'<button type="button" id="{identifier}"{leads}{described}>{content}</button>'
    if target is None:
        return f'<a id="{identifier}" aria-disabled="true"{described}>{content}</a>'
    return f'<a id="{identifier}" href="#{_attr(_screen_anchor(target))}"{described}>{content}</a>'


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
            {
                **element,
                "content": _shorten(str(element["content"]), max_content),
                "accessible_name": None
                if element.get("accessible_name") is None
                else _shorten(str(element["accessible_name"]), max_content),
            }
            for element in screen["elements"]
        ]
        anchor = _attr(_screen_anchor(str(screen["code"])))
        body = "".join(
            _review_element_html(element, state=str(screen["state"]), targets=targets)
            for element in elements
        )
        if any(element["kind"] in {TEXT_INPUT, SELECT} for element in elements):
            body = f'<form id="{anchor}-form" aria-labelledby="{anchor}-title">{body}</form>'
        parts.append(
            f'<section id="{anchor}" data-state="{_attr(str(screen["state"]))}" '
            f'aria-labelledby="{anchor}-title"><h2 id="{anchor}-title">'
            f"{_text(screen['title'])}</h2>{body}</section>"
        )
    parts.append("</main></body></html>")
    return "".join(parts)


def generated_mockup_html(package: DesignExplorationPackage, *, language: str | None = None) -> str:
    bound = package.generated_mockup
    if bound is None:
        raise ValueError("a generated mockup document requires a generated mockup")
    selected = next(
        alternative
        for alternative in package.alternatives
        if alternative.id == bound.design_alternative_id
    )
    return mockup_document(
        bound.mockup,
        tokens=dict(selected.visual_language.tokens),
        language=language or UNDETERMINED_LANGUAGE,
    )


def mockup_html(version: DesignPackageVersion, *, language: str | None = None) -> str:
    if version.package.generated_mockup is not None:
        return generated_mockup_html(version.package, language=language)
    return render_mockup_html(version.package.to_snapshot())


__all__ = [
    "MOCKUP_HTML_FILE",
    "UNDETERMINED_LANGUAGE",
    "generated_mockup_html",
    "mockup_html",
    "render_evaluation_document",
    "render_mockup_html",
]
