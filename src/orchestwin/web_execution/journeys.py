import re

from orchestwin.web_execution.phase_browser_evidence import WebBrowserInteraction
from orchestwin.web_execution.static_browser_jobs import BrowserAction

MAX_ACTIONS = 8
MAX_INPUTS = 4
ROUTE_ID = "root"
TEXT_SAMPLE = "Giulia Verdi"
_NUMERIC = re.compile(
    r"(amount|price|prezzo|import|quant|qty|number|numero|count|age|anni|eta|year|score|total|"
    r"totale|percent|rate|tasso|length|width|height|weight|peso|hours|ore|minutes|minuti|days|giorni|"
    r"km|chilometr|kilomet|migli|mile|metr|distan|valore|value|euro|eur\b|litr|liter|grad|degree|"
    r"temperat|speed|velocit|pace|calor|volume|area|larghezza|lunghezza|altezza|profond|depth|"
    r"conto|bill|mancia|tip\b|sconto|discount|tax|budget|cost|salar|stipendio|income|reddito|"
    r"spesa|spend|ratio|rapport|fattore|factor|coefficient|scala|scale|porzion|portion|"
    r"capacit|capacity|size|dimension|misura|measure|unit|units|units)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"(mail)", re.IGNORECASE)
_DATE = re.compile(r"(date|data|giorno|day)", re.IGNORECASE)
_OUTPUT_KINDS = ("STATUS", "TEXT", "LIST", "CARD", "HEADING")


def sample_value(element):
    if element["kind"] == "SELECT":
        options = element.get("options") or ()
        return options[0] if options else ""
    name = " ".join(filter(None, (element.get("field_name"), element.get("content"))))
    if _EMAIL.search(name):
        return "giulia.verdi@example.com"
    if _DATE.search(name):
        return "2026-10-01"
    if _NUMERIC.search(name):
        return "12"
    return TEXT_SAMPLE


def _screens(prototype):
    screens = {screen["id"]: screen for screen in prototype["screens"]}
    entry = prototype.get("entry_screen_id") or next(iter(screens))
    return screens, screens[entry]


def _transitions(prototype, screen):
    elements = {element["id"]: element for element in screen.get("elements", [])}
    for edge in prototype.get("transitions", []):
        trigger = elements.get(edge["trigger_element_id"])
        if trigger is not None and trigger["kind"] in {"BUTTON", "LINK"}:
            yield trigger, edge["target_screen_id"]


def _first(elements, kinds):
    for kind in kinds:
        for element in elements:
            if element["kind"] == kind:
                return element
    return None


def _label(element):
    return element.get("accessible_name") or element["content"]


_EXAMPLE_WORD = re.compile(r"[^\W\d_]{2,}")


def _example_like(content):
    return len(content.strip()) >= 4 and _EXAMPLE_WORD.search(content) is not None


def _step(action, element, screen):
    return {
        "action": action.snapshot(),
        "element_code": element["code"],
        "element_label": _label(element),
        "screen_code": screen["code"],
        "screen_title": screen["title"],
    }


def derive_static_journey(prototype):
    screens, entry = _screens(prototype)
    inputs = [
        element
        for element in entry.get("elements", [])
        if element["kind"] in {"TEXT_INPUT", "SELECT"}
    ]
    if len(inputs) > MAX_INPUTS:
        return {"status": "NOT_DERIVABLE", "reason": "TOO_MANY_ENTRY_INPUTS"}
    transition = next(iter(_transitions(prototype, entry)), None)
    if transition is None:
        return {"status": "NOT_DERIVABLE", "reason": "ENTRY_TRANSITION_MISSING"}
    trigger, target_id = transition
    target = screens[target_id]
    output = _first(
        [element for element in target.get("elements", []) if element["id"] != trigger["id"]],
        _OUTPUT_KINDS,
    )
    if output is None:
        return {"status": "NOT_DERIVABLE", "reason": "TARGET_OUTPUT_MISSING"}
    heading = _first(entry.get("elements", []), ("HEADING", "TEXT"))
    if heading is None:
        return {"status": "NOT_DERIVABLE", "reason": "ENTRY_HEADING_MISSING"}
    back = next(
        (
            element
            for element, back_target in _transitions(prototype, target)
            if back_target == entry["id"]
        ),
        None,
    )
    steps = []
    if back is None:
        if not inputs:
            return {"status": "NOT_DERIVABLE", "reason": "ENTRY_INPUT_MISSING"}
        steps.append(_step(BrowserAction("click", f"#{inputs[0]['code']}"), inputs[0], entry))
        steps.append(
            _step(
                BrowserAction("expect_text", f"#{heading['code']}", heading["content"]),
                heading,
                entry,
            )
        )
    for element in inputs:
        if element["kind"] == "SELECT":
            continue
        steps.append(
            _step(
                BrowserAction("fill", f"#{element['code']}", sample_value(element)), element, entry
            )
        )
    steps.append(_step(BrowserAction("press", f"#{trigger['code']}", "Enter"), trigger, entry))
    if _example_like(output["content"]):
        steps.append(
            _step(
                BrowserAction("expect_not_text", f"#{output['code']}", output["content"]),
                output,
                target,
            )
        )
    text_sample = next(
        (sample_value(element) for element in inputs if sample_value(element) == TEXT_SAMPLE), None
    )
    budget = MAX_ACTIONS - len(steps) - (2 if back is not None else 0)
    if text_sample is not None and budget >= 1:
        steps.append(
            _step(
                BrowserAction("expect_contains", f"#{output['code']}", text_sample), output, target
            )
        )
    if back is not None:
        steps.append(_step(BrowserAction("click", f"#{back['code']}"), back, target))
        steps.append(
            _step(
                BrowserAction("expect_text", f"#{heading['code']}", heading["content"]),
                heading,
                entry,
            )
        )
    if len(steps) > MAX_ACTIONS:
        return {"status": "NOT_DERIVABLE", "reason": "ACTION_LIMIT_EXCEEDED"}
    actions = tuple(BrowserAction(**step["action"]) for step in steps)
    interaction = WebBrowserInteraction(ROUTE_ID, actions)
    return {
        "status": "DERIVED",
        "declared_routes": [],
        "browser_interactions": [interaction.to_snapshot()],
        "steps": steps,
    }
