"""Scope counterfactuals, separate from the frozen complete-interface v3 corpus."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape

CURRICULUM_ID = "grounded-evaluator-scoped-interface-v4"
SERVICES = (
    ("Renew a library loan", "Rinnova un prestito bibliotecario", "Borrower", "Lettore"),
    ("Request a pet appointment", "Richiedi una visita veterinaria", "Pet keeper", "Proprietario"),
    ("Order a course transcript", "Ordina un certificato dei corsi", "Student", "Studente"),
    ("Borrow a community tool", "Prendi in prestito un attrezzo", "Member", "Socio"),
    ("Schedule a solar inspection", "Programma un controllo solare", "Site contact", "Referente"),
    ("Join a volunteer shift", "Partecipa a un turno volontario", "Volunteer", "Volontario"),
    (
        "Request a laptop repair",
        "Richiedi una riparazione del portatile",
        "Device owner",
        "Intestatario",
    ),
    (
        "Update an emergency contact",
        "Aggiorna un contatto di emergenza",
        "Contact name",
        "Nome contatto",
    ),
)
SERVICE_SPLITS = {"train": tuple(range(6)), "validation": (6, 7)}
LAYOUT_SPLITS = {"train": (0, 1, 2), "validation": (3, 4)}


@dataclass(frozen=True)
class ScopeCase:
    group_id: str
    split: str
    service: int
    layout: int
    phrasing: int
    form: str
    field: str
    button: str
    decoy: str
    other_form: str


@dataclass(frozen=True)
class Variant:
    name: str
    label: str = "explicit"
    button: str = "text"
    placement: str = "inside"
    scope: str = "descendants"
    selected: str = "both"
    decoy_missing: bool = False


VARIANTS = (
    Variant("explicit-present"),
    Variant("explicit-absent", label="none"),
    Variant("implicit-only", label="implicit"),
    Variant("implicit-and-explicit", label="both"),
    Variant("wrong-label-reference", label="wrong"),
    Variant("blank-explicit-label", label="blank"),
    Variant("nameless-button", button="empty"),
    Variant("broken-button-reference", button="broken"),
    Variant("valid-button-reference", button="reference"),
    Variant("detached-present", placement="detached"),
    Variant("detached-unlabelled", placement="detached", label="none"),
    Variant("detached-with-missing-button", placement="detached", button="comment"),
    Variant("form-absent-targets-present", placement="absent"),
    Variant("external-owned", placement="owned", scope="owner"),
    Variant("external-owned-descendants-only", placement="owned"),
    Variant("foreign-owner-inside", placement="foreign", scope="owner"),
    Variant("button-subset-good-decoy", selected="button", button="empty"),
    Variant(
        "button-subset-bad-decoy",
        selected="button",
        button="empty",
        label="none",
        decoy_missing=True,
    ),
    Variant("input-subset-good-decoy", selected="field"),
    Variant("input-subset-bad-decoy", selected="field", button="empty", decoy_missing=True),
    Variant("metadata-only", placement="unavailable"),
)


def scenario(seed: int, split: str, ordinal: int) -> ScopeCase:
    if split not in SERVICE_SPLITS or type(ordinal) is not int or ordinal < 0:
        raise ValueError("unknown scoped split or ordinal")
    group = hashlib.sha256(f"{CURRICULUM_ID}:{seed}:{split}:{ordinal}".encode()).hexdigest()
    services, layouts = SERVICE_SPLITS[split], LAYOUT_SPLITS[split]
    return ScopeCase(
        group,
        split,
        services[ordinal % len(services)],
        layouts[(ordinal // len(services)) % len(layouts)],
        (ordinal // (len(services) * len(layouts))) % 3,
        *[
            f"{prefix}-{group[i * 10 : (i + 1) * 10]}"
            for i, prefix in enumerate(("scope", "person", "apply", "extra", "other"))
        ],
    )


def controls(case: ScopeCase, variant: Variant) -> list[dict]:
    selected = []
    if variant.selected != "button":
        selected.append(dict(target=case.field, family="input_label"))
    if variant.selected != "field":
        selected.append(dict(target=case.button, family="button_name"))
    return selected


def declared_states(variant: Variant) -> tuple[str, ...]:
    """Design intent independent of parsing the rendered fixture."""
    field = "PRESENT" if variant.label in {"explicit", "both"} else "MISSING"
    button = "PRESENT" if variant.button in {"text", "reference"} else "MISSING"
    if variant.placement in {"absent", "unavailable"} or (
        variant.placement == "owned" and variant.scope == "descendants"
    ):
        field = button = "INSUFFICIENT"
    elif variant.placement in {"detached", "foreign"}:
        field = "INSUFFICIENT"
    return (
        (button,)
        if variant.selected == "button"
        else (field,)
        if variant.selected == "field"
        else (field, button)
    )


def render(case: ScopeCase, variant: Variant, locale: str) -> str:
    if locale not in {"en", "it"}:
        raise ValueError("unsupported locale")
    lang = int(locale == "it")
    task, caption = SERVICES[case.service][lang], SERVICES[case.service][2 + lang]
    owner = (
        f' form="{case.form}"'
        if variant.placement == "owned"
        else f' form="{case.other_form}"'
        if variant.placement == "foreign"
        else ""
    )
    field = f'<input id="{case.field}"{owner} />'
    explicit = f'<label for="{case.field}"><strong>{escape(caption)}</strong></label>'
    if variant.label in {"implicit", "both"}:
        field = f"<label>{escape(caption)}{field}</label>"
    if variant.label in {"explicit", "both"}:
        field = explicit + field
    elif variant.label == "wrong":
        field = f'<label for="{case.decoy}">{escape(caption)}</label>' + field
    elif variant.label == "blank":
        field = f'<label for="{case.field}"> <!-- caption --> </label>' + field
    button_owner = f' form="{case.form}"' if variant.placement == "owned" else ""
    text = escape(task)
    button = f'<button id="{case.button}"{button_owner}>'
    if variant.button == "text":
        button += f"<span>{text}</span></button>"
    elif variant.button in {"reference", "broken"}:
        reference = case.button + ("-name" if variant.button == "reference" else "-missing")
        button = f'<button id="{case.button}"{button_owner} aria-labelledby="{reference}"></button><span id="{case.button}-name">{text}</span>'
    else:
        button += (f"<!-- {text} -->" if variant.button == "comment" else "") + "</button>"
    decoy_label = "" if variant.decoy_missing else f'<label for="{case.decoy}">Reference</label>'
    decoy = decoy_label + f'<input id="{case.decoy}" />'
    inside = (
        button + decoy
        if variant.placement == "detached"
        else decoy
        if variant.placement == "owned"
        else field + button + decoy
    )
    if case.layout == 0:
        body = f"<fieldset><legend>{text}</legend>{inside}</fieldset>"
    elif case.layout == 1:
        body = f"<section><header><h2>{text}</h2></header><div>{inside}</div></section>"
    elif case.layout == 2:
        body = f"<table><tbody><tr><td>{inside}</td></tr></tbody></table>"
    elif case.layout == 3:
        body = f"<dl><dt>{text}</dt><dd><article>{inside}</article></dd></dl>"
    else:
        body = f"<article><aside>Details</aside><ol><li>{inside}</li></ol></article>"
    selected_form = (
        f'<form id="{case.form}">{body}</form>'
        if variant.placement != "absent"
        else f"<section>{field}{button}{decoy}</section>"
    )
    outside = (
        f"<section>{field}</section>"
        if variant.placement == "detached"
        else f"<section>{field}{button}</section>"
        if variant.placement == "owned"
        else ""
    )
    return f'<html lang="{locale}"><head><title>{text}</title></head><body><main>{outside}{selected_form}<form id="{case.other_form}"><button>Help</button></form></main></body></html>'
