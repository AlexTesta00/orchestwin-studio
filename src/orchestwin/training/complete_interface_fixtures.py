"""Compositional, XML-compatible HTML fixtures for static evaluator supervision.

The vocabulary is deliberately closed. State changes alter controls, not their
opaque identity, profile, task, layout, or counterfactual split assignment.
"""

from __future__ import annotations

import hashlib
import itertools
import random
from dataclasses import dataclass
from html import escape

CURRICULUM_ID = "grounded-evaluator-complete-interface-v3"
LAYOUTS = {"train": tuple(range(8)), "validation": (8, 9), "test": (10, 11)}
# Task, field label and action text; held-out services never occur in training.
SERVICES = (
    (
        "Reserve a workshop seat",
        "Prenota un posto al laboratorio",
        "Participant",
        "Partecipante",
        "Reserve seat",
        "Prenota posto",
    ),
    (
        "Request a parking permit",
        "Richiedi un permesso di sosta",
        "Vehicle plate",
        "Targa veicolo",
        "Request permit",
        "Richiedi permesso",
    ),
    (
        "Schedule an equipment inspection",
        "Programma un controllo attrezzatura",
        "Equipment code",
        "Codice attrezzatura",
        "Schedule inspection",
        "Programma controllo",
    ),
    (
        "Register a community event",
        "Registra un evento comunitario",
        "Event title",
        "Titolo evento",
        "Register event",
        "Registra evento",
    ),
    (
        "Arrange a parcel collection",
        "Organizza un ritiro pacco",
        "Collection address",
        "Indirizzo ritiro",
        "Arrange collection",
        "Organizza ritiro",
    ),
    (
        "Apply for a studio slot",
        "Richiedi un turno in studio",
        "Applicant name",
        "Nome candidato",
        "Apply for slot",
        "Richiedi turno",
    ),
    (
        "Submit a maintenance ticket",
        "Invia una richiesta di manutenzione",
        "Asset number",
        "Numero bene",
        "Submit ticket",
        "Invia segnalazione",
    ),
    (
        "Enroll in a language session",
        "Iscriviti a una sessione linguistica",
        "Learner name",
        "Nome studente",
        "Enroll now",
        "Iscriviti ora",
    ),
    (
        "Book a rehearsal room",
        "Prenota una sala prove",
        "Group name",
        "Nome gruppo",
        "Book room",
        "Prenota sala",
    ),
    (
        "Request an archive consultation",
        "Richiedi una consultazione archivio",
        "Collection name",
        "Nome collezione",
        "Request consultation",
        "Richiedi consultazione",
    ),
    (
        "Arrange a recycling pickup",
        "Organizza un ritiro riciclabili",
        "Pickup street",
        "Via del ritiro",
        "Arrange pickup",
        "Organizza ritiro",
    ),
    (
        "Register a mentoring meeting",
        "Registra un incontro di tutoraggio",
        "Mentee name",
        "Nome partecipante",
        "Register meeting",
        "Registra incontro",
    ),
    (
        "Reserve a swimming lane",
        "Prenota una corsia nuoto",
        "Swimmer name",
        "Nome nuotatore",
        "Reserve lane",
        "Prenota corsia",
    ),
    (
        "Request a garden plot",
        "Richiedi un lotto orto",
        "Resident name",
        "Nome residente",
        "Request plot",
        "Richiedi lotto",
    ),
    (
        "Arrange a museum visit",
        "Organizza una visita al museo",
        "Visitor group",
        "Gruppo visitatori",
        "Arrange visit",
        "Organizza visita",
    ),
    (
        "Register a telescope session",
        "Registra una sessione al telescopio",
        "Observer name",
        "Nome osservatore",
        "Register session",
        "Registra sessione",
    ),
    (
        "Book a ferry crossing",
        "Prenota un passaggio in traghetto",
        "Passenger name",
        "Nome passeggero",
        "Book crossing",
        "Prenota passaggio",
    ),
    (
        "Request a seed exchange",
        "Richiedi uno scambio di semi",
        "Plant variety",
        "Varietà pianta",
        "Request exchange",
        "Richiedi scambio",
    ),
)
SERVICE_SPLITS = {"train": tuple(range(12)), "validation": (12, 13, 14), "test": (15, 16, 17)}


@dataclass(frozen=True)
class Control:
    target: str
    family: str
    style: int
    defect: int


@dataclass(frozen=True)
class Scenario:
    group_id: str
    split: str
    service: int
    layout: int
    form: str
    controls: tuple[Control, ...]
    role: int
    detail: int
    noise: int
    reverse: bool


def scenario(seed: int, split: str, ordinal: int) -> Scenario:
    if split not in LAYOUTS or ordinal < 0:
        raise ValueError("unknown complete-interface split or group")
    group = hashlib.sha256(f"{CURRICULUM_ID}:{seed}:{split}:{ordinal}".encode()).hexdigest()
    rng = random.Random(group)
    count = 2 + ordinal % 3
    services = SERVICE_SPLITS[split]
    service = services[(ordinal // 3) % len(services)]
    layouts = LAYOUTS[split]
    layout = layouts[(ordinal // (3 * len(services))) % len(layouts)]
    extras = rng.sample(["heading", "image_text", "error_guidance"], count - 2)
    families = ["input_label", "button_name", *extras]
    rng.shuffle(families)
    controls = tuple(
        Control(f"c-{rng.getrandbits(40):010x}", family, rng.randrange(3), rng.randrange(4))
        for family in families
    )
    return Scenario(
        group,
        split,
        service,
        layout,
        f"f-{rng.getrandbits(40):010x}",
        controls,
        rng.randrange(4),
        rng.randrange(1, 1000),
        rng.randrange(3),
        bool(rng.randrange(2)),
    )


def conditions(case: Scenario):
    """Every defect combination, full absence, and partial-evidence combinations."""
    count = len(case.controls)
    for missing in itertools.product((False, True), repeat=count):
        yield "complete", tuple("MISSING" if flag else "PRESENT" for flag in missing)
    yield "form_absent", ("INSUFFICIENT",) * count
    yield "content_unavailable", ("INSUFFICIENT",) * count
    for absent in range(count):
        states = ["PRESENT"] * count
        states[absent] = "INSUFFICIENT"
        yield "partial", tuple(states)
        states[(absent + 1) % count] = "MISSING"
        yield "partial", tuple(states)


def _control(item: Control, state: str, texts: tuple[str, str, str], locale: str) -> str:
    if state == "INSUFFICIENT":
        return ""
    task, field, action = (escape(value) for value in texts)
    target, present = item.target, state == "PRESENT"
    if item.family == "input_label":
        control = f'<input id="{target}" name="{target}" />'
        label = f'<label for="{target}">{field}</label>'
        if not present:
            label = (
                "",
                f'<label for="help-input">{field}</label>',
                f'<label for="{target}"> \n </label>',
                f"<span>{field}</span>",
            )[item.defect]
        if item.style == 0:
            return label + control
        if item.style == 1:
            return control + f"<div>{label}</div>"
        return f"<div><span>{label}</span></div><div>{control}</div>"
    if item.family == "button_name":
        if present:
            if item.style == 0:
                return f'<button id="{target}"><span>{action}</span></button>'
            if item.style == 1:
                return f'<button id="{target}" aria-label="{action}"></button>'
            return (
                f'<button id="{target}" aria-labelledby="{target}-a {target}-b"></button>'
                f'<aside><span id="{target}-a">{action}</span><span id="{target}-b"> · {field}</span></aside>'
            )
        if item.defect == 0:
            return f'<button id="{target}"></button><span>{action}</span>'
        if item.defect == 1:
            return f'<button id="{target}" aria-label=" "></button><span>{action}</span>'
        reference = f"{target}-unresolved" if item.defect == 2 else f"{target}-name"
        named = action if item.defect == 2 else " "
        return (
            f'<span id="{target}-name">{named}</span>'
            f'<button id="{target}" aria-labelledby="{reference}"></button>'
        )
    if item.family == "image_text":
        alt = field if present else " "
        return f'<figure><img id="{target}" src="diagram.svg" alt="{alt}" /><figcaption>{field}</figcaption></figure>'
    if item.family == "heading":
        value = task if present else " \n "
        return f'<h2 id="{target}"><span>{value}</span></h2>'
    if item.family == "error_guidance":
        value = (
            (f"Check {field} and try again." if locale == "en" else f"Controlla {field} e riprova.")
            if present
            else " "
        )
        return f'<p id="{target}" role="alert"><strong>{value}</strong></p>'
    raise ValueError("unsupported complete-interface control")


def _layout(parts: list[str], layout: int) -> str:
    if layout == 0:
        return "".join(parts)
    if layout == 1:
        return "<fieldset><legend>Details</legend>" + "".join(parts) + "</fieldset>"
    if layout == 2:
        return "".join(f"<section>{part}</section>" for part in parts)
    if layout == 3:
        return "<ul>" + "".join(f"<li>{part}</li>" for part in parts) + "</ul>"
    if layout == 4:
        return (
            "<table><tbody>"
            + "".join(f"<tr><td>{part}</td></tr>" for part in parts)
            + "</tbody></table>"
        )
    if layout == 5:
        return "<dl>" + "".join(f"<dt>Detail</dt><dd>{part}</dd>" for part in parts) + "</dl>"
    if layout == 6:
        return "<article>" + "".join(f"<div>{part}</div>" for part in parts) + "</article>"
    if layout == 7:
        return "".join(f"<fieldset><legend>Detail</legend>{part}</fieldset>" for part in parts)
    if layout == 8:
        return (
            "<section><ol>"
            + "".join(f"<li><div>{part}</div></li>" for part in parts)
            + "</ol></section>"
        )
    if layout == 9:
        return (
            "<article><fieldset><legend>Details</legend>"
            + "".join(f"<section>{part}</section>" for part in parts)
            + "</fieldset></article>"
        )
    if layout == 10:
        return (
            "<section><table><tbody>"
            + "".join(f"<tr><th>Detail</th><td><div>{part}</div></td></tr>" for part in parts)
            + "</tbody></table></section>"
        )
    if layout == 11:
        return (
            "<article><dl>"
            + "".join(f"<dt>Detail</dt><dd><section>{part}</section></dd>" for part in parts)
            + "</dl></article>"
        )
    raise ValueError("unknown complete-interface layout")


def localized(case: Scenario, locale: str) -> tuple[str, str, str]:
    if locale not in {"en", "it"}:
        raise ValueError("unsupported complete-interface locale")
    return SERVICES[case.service][int(locale == "it") :: 2]


def render(case: Scenario, locale: str, mode: str, states: tuple[str, ...]) -> str:
    if len(states) != len(case.controls) or any(
        s not in {"PRESENT", "MISSING", "INSUFFICIENT"} for s in states
    ):
        raise ValueError("invalid complete-interface state vector")
    texts = localized(case, locale)
    task, field, action = (escape(value) for value in texts)
    physical = ("PRESENT",) * len(states) if mode == "content_unavailable" else states
    parts = [
        _control(control, state, texts, locale)
        for control, state in zip(case.controls, physical, strict=True)
    ]
    if case.reverse:
        parts.reverse()
    form = (
        ""
        if mode == "form_absent"
        else f'<form id="{case.form}">{_layout(parts, case.layout)}</form>'
    )
    navigation = f'<header><h1>{task}</h1><nav><a href="#help">Help</a><a href="#catalogue">Catalogue</a></nav></header>'
    details = f'<section id="catalogue"><h2>{task}</h2><p>Reference {case.detail}</p></section>'
    help_content = (
        f'<aside id="help"><h2>Help</h2><label for="help-input">{field}</label>'
        f'<input id="help-input" /><button id="help-action">{action}</button>'
        '<img src="help.svg" alt="Help" /><p role="alert">Try again</p></aside>'
    )
    extra = "".join(
        f"<section><h2>Item {case.detail + i}</h2><p>{task}</p><button>{action}</button></section>"
        for i in range(case.noise)
    )
    return (
        f'<html lang="{locale}"><head><title>{task}</title><meta charset="utf-8" /></head><body>'
        f"{navigation}<main>{details}{form}{help_content}{extra}</main><footer>Example service</footer></body></html>"
    )
