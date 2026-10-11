from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from uuid import UUID

from orchestwin.evaluation.artifact_content import prepare_artifact_content
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.evaluation.model_evaluator import _input_payload
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

CURRICULUM_ID = "grounded-evaluator-complete-interface-v3"
NOW = datetime(2026, 9, 14, tzinfo=UTC)
LAYOUTS = {"train": tuple(range(8)), "validation": (8, 9), "test": (10, 11)}
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
CHECKS = {
    "input_label": (
        "a nonempty explicit label associated by for",
        "un'etichetta esplicita non vuota associata tramite for",
    ),
    "button_name": (
        "a nonempty button name from text, aria-label or referenced aria-labelledby text",
        "un nome del pulsante non vuoto da testo, aria-label o testi riferiti da aria-labelledby",
    ),
    "image_text": (
        "nonempty alt text for this informative image",
        "un testo alt non vuoto per questa immagine informativa",
    ),
    "heading": ("nonempty text in this heading", "un testo non vuoto in questo titolo"),
    "error_guidance": (
        "nonempty recovery text in this alert",
        "un testo di recupero non vuoto in questo avviso",
    ),
}
ROLES = (
    ("Occasional service user", "Utente occasionale del servizio"),
    ("Regular service operator", "Operatore abituale del servizio"),
    ("New service participant", "Nuovo partecipante al servizio"),
    ("Service desk assistant", "Addetto allo sportello del servizio"),
)


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


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None]
    ancestors: tuple[str, ...]
    parts: list[str] = field(default_factory=list)

    @property
    def text(self):
        return "".join(self.parts).strip()


class Document(HTMLParser):
    def __init__(self, raw: str):
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self.ids: dict[str, Element] = {}
        self.stack: list[Element] = []
        self.feed(raw)
        self.close()

    def handle_starttag(self, tag, attrs):
        if len(dict(attrs)) != len(attrs):
            raise ValueError("duplicate fixture attribute")
        element = Element(
            tag, dict(attrs), tuple(e.attrs.get("id") for e in self.stack if e.attrs.get("id"))
        )
        self.elements.append(element)
        if identifier := element.attrs.get("id"):
            if identifier in self.ids:
                raise ValueError("duplicate fixture ID")
            self.ids[identifier] = element
        if tag not in {"input", "img", "meta", "link", "br", "hr"}:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1].tag != tag:
            raise ValueError("unbalanced closed fixture HTML")
        self.stack.pop()

    def handle_data(self, data):
        for element in self.stack:
            element.parts.append(data)


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
                f'<aside><span id="{target}-a">{action}</span>'
                f'<span id="{target}-b"> · {field}</span></aside>'
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
        return (
            f'<figure><img id="{target}" src="diagram.svg" alt="{alt}" />'
            f"<figcaption>{field}</figcaption></figure>"
        )
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
    navigation = (
        f"<header><h1>{task}</h1>"
        '<nav><a href="#help">Help</a><a href="#catalogue">Catalogue</a></nav></header>'
    )
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
        f"{navigation}<main>{details}{form}{help_content}{extra}</main>"
        "<footer>Example service</footer></body></html>"
    )


def _request(case: Scenario, locale: str, raw: str, supplied: bool):
    rng = random.Random(case.group_id)
    project, workflow, artifact, twin_id, evaluation, scenario_id, bundle_id = (
        UUID(int=rng.getrandbits(128), version=4) for _ in range(7)
    )
    version = rng.randint(1, 20)
    task, _, _ = localized(case, locale)
    lang = int(locale == "it")
    checks = [f"#{control.target}: {CHECKS[control.family][lang]}" for control in case.controls]
    scope = (
        f"Task: {task}. Inspect the complete supplied page, focusing on form #{case.form}. "
        f"Check each selected control separately: {'; '.join(checks)}. "
        "Report one finding for each supported missing property; do not put correct controls "
        "in findings. Unrelated text cannot label these controls. If only some targets are "
        "absent, record evidence gaps and assess the remaining targets. Abstain when none can "
        "be assessed. Evaluate static HTML only; no observed user or runtime behavior."
        if locale == "en"
        else f"Compito: {task}. Esamina la pagina completa fornita, concentrandoti sul modulo "
        f"#{case.form}. Controlla separatamente ogni elemento: {'; '.join(checks)}. "
        "Riporta un finding per ogni proprietà mancante supportata; non inserire controlli "
        "corretti nei finding. Testi estranei non etichettano questi controlli. Se mancano solo "
        "alcuni elementi, registra le lacune e valuta gli altri. Astieniti quando nessuno è "
        "valutabile. Esamina soltanto HTML statico; nessuna osservazione di utenti o runtime."
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    descriptor = EvaluationArtifactReference(
        artifact_id=artifact,
        version_number=version,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(raw.encode()),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location=f"dom:#{case.form}",
    )
    bundle = create_evaluation_artifact_bundle(
        project_id=project,
        workflow_run_id=workflow,
        scenario=EvaluationScenario(scenario_id, task, scope, locale, tuple(checks)),
        artifacts=(descriptor,),
        created_at=NOW,
        bundle_id=bundle_id,
    )
    role = ROLES[case.role][lang]
    profile = canonical_json(
        dict(
            name=role,
            role=role,
            goals=[task],
            operational_constraints=[
                "Synthetic profile for static review; user behavior has not been observed."
                if locale == "en"
                else "Profilo sintetico per revisione statica; il comportamento utente "
                "non è stato osservato."
            ],
        )
    )
    twin = EvaluationUserTwinProfile(
        twin_id,
        version,
        role,
        UserTwinLifecycleStatus.PROTO_UT,
        hashlib.sha256(profile.encode()).hexdigest(),
        profile,
    )
    request = UserTwinEvaluationRequest(evaluation, project, workflow, bundle, twin, (), NOW)
    payload = _input_payload(request)
    if supplied:
        prepared = prepare_artifact_content(
            request, selected=((artifact, version),), read_content=lambda *_: raw.encode()
        )
        request = prepared.request
        payload = prepared.content.enrich(request, _input_payload(request))
    return request, payload


def observe(raw: str | None, form: str, controls: list[dict]) -> list[dict]:
    document = Document(raw) if raw is not None else None
    if document and document.stack:
        raise ValueError("unclosed fixture HTML")
    observations = []
    for control in controls:
        target, family = control["target"], control["family"]
        reason, state = "PROPERTY_PRESENT", "PRESENT"
        element = document.ids.get(target) if document else None
        if document is None:
            state, reason = "INSUFFICIENT", "CONTENT_NOT_SUPPLIED"
        elif form not in document.ids:
            state, reason = "INSUFFICIENT", "FORM_ABSENT"
        elif element is None or form not in element.ancestors:
            state, reason = "INSUFFICIENT", "TARGET_ABSENT_FROM_FORM"
        else:
            if family == "input_label":
                present = element.tag == "input" and any(
                    e.tag == "label" and e.attrs.get("for") == target and e.text
                    for e in document.elements
                )
                reason = "NO_EXPLICIT_LABEL"
            elif family == "button_name":
                references = (element.attrs.get("aria-labelledby") or "").split()
                present = element.tag == "button" and bool(
                    element.text
                    or (element.attrs.get("aria-label") or "").strip()
                    or any(document.ids[r].text for r in references if r in document.ids)
                )
                reason = "NO_BUTTON_NAME"
            elif family == "image_text":
                present = element.tag == "img" and bool((element.attrs.get("alt") or "").strip())
                reason = "NO_IMAGE_TEXT"
            elif family == "heading":
                present = element.tag in {"h1", "h2", "h3"} and bool(element.text)
                reason = "NO_HEADING_TEXT"
            elif family == "error_guidance":
                present = element.attrs.get("role") == "alert" and bool(element.text)
                reason = "NO_RECOVERY_TEXT"
            else:
                raise ValueError("unsupported fixture criterion")
            state = "PRESENT" if present else "MISSING"
            if present:
                reason = "PROPERTY_PRESENT"
        observations.append(dict(target=target, family=family, state=state, reason=reason))
    return observations
