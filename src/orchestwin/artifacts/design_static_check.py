from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final
from uuid import UUID, uuid5

from orchestwin.artifacts.design_evaluation import (
    CONTENT_STEPS,
    DesignEvaluationDocument,
    DesignEvaluationError,
    evaluation_reference,
    ordered_screens,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.prototypes import PrototypeElementKind, PrototypeScreenState
from orchestwin.evaluation.artifact_content import MAX_VIEW_BYTES
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactBundle,
    EvaluationArtifactKind,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile
from orchestwin.projects.requirements_primitives import canonical_json

STATIC_CHECK_MEDIA_TYPE: Final = "text/html"
STATIC_CHECK_NOT_APPLICABLE: Final = "STATIC_CHECK_NOT_APPLICABLE"
MAX_STATIC_CONTROLS: Final = 4
STATIC_CHECKS: Final = {
    "input_label": (
        "a nonempty explicit label associated by for",
        "un'etichetta esplicita non vuota associata tramite for",
    ),
    "button_name": (
        "a nonempty button name from text, aria-label or referenced aria-labelledby text",
        "un nome del pulsante non vuoto da testo, aria-label o testi riferiti da aria-labelledby",
    ),
    "heading": ("nonempty text in this heading", "un testo non vuoto in questo titolo"),
    "error_guidance": (
        "nonempty recovery text in this alert",
        "un testo di recupero non vuoto in questo avviso",
    ),
}
STATIC_PROFILE_CONSTRAINT: Final = (
    "Synthetic profile for static review; user behavior has not been observed.",
    "Profilo sintetico per revisione statica; il comportamento utente non è stato osservato.",
)
_SCENARIO_NAMESPACE: Final = UUID("9c1f4a77-5a0b-4a39-8b63-2d5f0b8c7e21")
_FIELDS: Final = frozenset({PrototypeElementKind.TEXT_INPUT, PrototypeElementKind.SELECT})


@dataclass(frozen=True, slots=True)
class StaticControl:
    element_code: str
    target: str
    family: str


@dataclass(frozen=True, slots=True)
class StaticCheckTarget:
    screen_code: str
    form: str
    task: str
    locale: str
    controls: tuple[StaticControl, ...]

    @property
    def checks(self) -> tuple[str, ...]:
        language = int(self.locale == "it")
        return tuple(
            f"#{control.target}: {STATIC_CHECKS[control.family][language]}"
            for control in self.controls
        )


def _opaque(prefix: str, identifier: UUID) -> str:
    return f"{prefix}-{hashlib.sha256(str(identifier).encode('utf-8')).hexdigest()[:10]}"


def static_check_target(version: DesignPackageVersion, *, locale: str) -> StaticCheckTarget:
    package = version.package
    if package.prototype is None or package.owner_selected_alternative_id is None:
        raise DesignEvaluationError("DESIGN_PROTOTYPE_REQUIRED")
    alternative = next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )
    for screen in ordered_screens(version):
        fields = [item for item in screen.elements if item.kind in _FIELDS]
        buttons = [item for item in screen.elements if item.kind is PrototypeElementKind.BUTTON]
        if not fields or not buttons:
            continue
        selected = [(fields[0], "input_label"), (buttons[0], "button_name")]
        headings = [item for item in screen.elements if item.kind is PrototypeElementKind.HEADING]
        if headings:
            selected.append((headings[0], "heading"))
        alerts = [item for item in screen.elements if item.kind is PrototypeElementKind.STATUS]
        if alerts and screen.state is PrototypeScreenState.ERROR:
            selected.append((alerts[0], "error_guidance"))
        return StaticCheckTarget(
            screen_code=screen.code,
            form=_opaque("f", screen.id),
            task=alternative.workflows[0].title,
            locale="it" if locale.casefold().startswith("it") else "en",
            controls=tuple(
                StaticControl(
                    element_code=element.code, target=_opaque("c", element.id), family=family
                )
                for element, family in selected[:MAX_STATIC_CONTROLS]
            ),
        )
    raise DesignEvaluationError(STATIC_CHECK_NOT_APPLICABLE)


def static_check_scope(target: StaticCheckTarget) -> str:
    checks = "; ".join(target.checks)
    if target.locale == "it":
        return (
            f"Compito: {target.task}. Esamina la pagina completa fornita, concentrandoti sul "
            f"modulo #{target.form}. Controlla separatamente ogni elemento: {checks}. "
            "Riporta un finding per ogni proprietà mancante supportata; non inserire controlli "
            "corretti nei finding. Testi estranei non etichettano questi controlli. Se mancano "
            "solo alcuni elementi, registra le lacune e valuta gli altri. Astieniti quando "
            "nessuno è valutabile. Esamina soltanto HTML statico; nessuna osservazione di utenti "
            "o runtime."
        )
    return (
        f"Task: {target.task}. Inspect the complete supplied page, focusing on form "
        f"#{target.form}. Check each selected control separately: {checks}. "
        "Report one finding for each supported missing property; do not put correct controls in "
        "findings. Unrelated text cannot label these controls. If only some targets are absent, "
        "record evidence gaps and assess the remaining targets. Abstain when none can be "
        "assessed. Evaluate static HTML only; no observed user or runtime behavior."
    )


def _shorten(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _element(element, *, selected: dict[str, StaticControl], limit: int | None, leads) -> str:
    content = escape(_shorten(element.content, limit), quote=False)
    name = escape(_shorten(element.accessible_name or element.content, limit), quote=False)
    control = selected.get(element.code)
    kind = element.kind
    if kind in _FIELDS:
        identifier = control.target if control else element.code.lower()
        field = control.target if control else escape(element.field_name or "", quote=True)
        return f'<label for="{identifier}">{name}</label><input id="{identifier}" name="{field}" />'
    if kind is PrototypeElementKind.BUTTON:
        if control:
            return f'<button id="{control.target}"><span>{content}</span></button>'
        return f"<button>{content}</button>"
    if kind is PrototypeElementKind.HEADING:
        if control:
            return f'<h2 id="{control.target}"><span>{content}</span></h2>'
        return f"<h2>{content}</h2>"
    if kind is PrototypeElementKind.STATUS:
        if control:
            return f'<p id="{control.target}" role="alert"><strong>{content}</strong></p>'
        return f'<p role="status">{content}</p>'
    if kind is PrototypeElementKind.LINK:
        target = leads.get(element.id)
        return f'<a href="#{target.lower()}">{content}</a>' if target else f"<span>{content}</span>"
    if kind is PrototypeElementKind.LIST:
        return f"<ul><li>{content}</li></ul>"
    if kind is PrototypeElementKind.CARD:
        return f"<div>{content}</div>"
    return f"<p>{content}</p>"


def _render(version: DesignPackageVersion, target: StaticCheckTarget, limit: int | None) -> str:
    prototype = version.package.prototype
    screens = ordered_screens(version)
    codes = {screen.id: screen.code for screen in screens}
    leads = {
        item.trigger_element_id: codes[item.target_screen_id] for item in prototype.transitions
    }
    selected = {control.element_code: control for control in target.controls}
    task = escape(target.task, quote=False)
    links = "".join(
        f'<a href="#{screen.code.lower()}">{escape(_shorten(screen.title, limit), quote=False)}</a>'
        for screen in screens
    )
    parts = [
        f'<html lang="{target.locale}"><head><title>{task}</title><meta charset="utf-8" /></head>'
        f"<body><header><h1>{task}</h1><nav>{links}</nav></header><main>"
    ]
    for screen in screens:
        body = "".join(
            _element(element, selected=selected, limit=limit, leads=leads)
            for element in screen.elements
        )
        title = escape(_shorten(screen.title, limit), quote=False)
        if screen.code == target.screen_code:
            body = f'<form id="{target.form}">{body}</form>'
        parts.append(f'<section id="{screen.code.lower()}"><h2>{title}</h2>{body}</section>')
    parts.append(
        f"</main><footer>{escape(_shorten(prototype.title, limit), quote=False)}</footer>"
        "</body></html>"
    )
    return "".join(parts)


def static_check_document(
    version: DesignPackageVersion, target: StaticCheckTarget
) -> DesignEvaluationDocument:
    for step in CONTENT_STEPS:
        content = _render(version, target, step).encode("utf-8")
        if len(content) <= MAX_VIEW_BYTES:
            return DesignEvaluationDocument(
                content=content,
                reference=evaluation_reference(
                    artifact_id=version.package.prototype.id,
                    version_number=version.version_number,
                    kind=EvaluationArtifactKind.DOM_SNAPSHOT,
                    media_type=STATIC_CHECK_MEDIA_TYPE,
                    content=content,
                    location=f"dom:#{target.form}",
                ),
            )
    raise DesignEvaluationError("EVALUATION_DOCUMENT_TOO_LARGE")


def static_check_bundle(
    version: DesignPackageVersion,
    document: DesignEvaluationDocument,
    target: StaticCheckTarget,
    *,
    created_at: datetime,
    bundle_id: UUID | None = None,
) -> EvaluationArtifactBundle:
    return create_evaluation_artifact_bundle(
        project_id=version.project_id,
        workflow_run_id=version.id,
        scenario=EvaluationScenario(
            id=uuid5(_SCENARIO_NAMESPACE, f"{version.id}:{target.form}"),
            name=target.task,
            task=static_check_scope(target),
            locale=target.locale,
            expected_outcomes=target.checks,
        ),
        artifacts=(document.reference,),
        created_at=created_at,
        bundle_id=bundle_id,
    )


def static_check_profile(
    twin: EvaluationUserTwinProfile, target: StaticCheckTarget
) -> EvaluationUserTwinProfile:
    profile = canonical_json(
        {
            "name": twin.name,
            "role": twin.name,
            "goals": [target.task],
            "operational_constraints": [STATIC_PROFILE_CONSTRAINT[int(target.locale == "it")]],
        }
    )
    return EvaluationUserTwinProfile(
        twin_id=twin.twin_id,
        version_number=twin.version_number,
        name=twin.name,
        lifecycle_status=twin.lifecycle_status,
        content_hash=hashlib.sha256(profile.encode("utf-8")).hexdigest(),
        snapshot_json=profile,
    )


__all__ = [
    "MAX_STATIC_CONTROLS",
    "STATIC_CHECKS",
    "STATIC_CHECK_NOT_APPLICABLE",
    "STATIC_PROFILE_CONSTRAINT",
    "StaticCheckTarget",
    "StaticControl",
    "static_check_bundle",
    "static_check_document",
    "static_check_profile",
    "static_check_scope",
    "static_check_target",
]
