"""Native, independently checked multi-control training targets; no model calls."""

from __future__ import annotations

import hashlib
import random
from uuid import UUID

from orchestwin.evaluation.artifact_content import prepare_artifact_content
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import EvaluationUserTwinProfile, UserTwinEvaluationRequest
from orchestwin.evaluation.model_evaluator import USER_TWIN_MODEL_EVALUATION_TASK_ID, _input_payload
from orchestwin.models.final_evaluator_gateway import RESPONSE_CONTRACT
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.training.complete_interface_fixtures import (
    Scenario,
    conditions,
    localized,
    render,
    scenario,
)
from orchestwin.training.complete_interface_validation import observe, validate_annotations
from orchestwin.training.grounded_evaluator_curriculum import NOW, SCHEMA
from orchestwin.training.relational_evaluator_curriculum import INSTRUCTION
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

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
        f"Task: {task}. Inspect the complete supplied page, focusing on form #{case.form}. Check each selected control separately: {'; '.join(checks)}. "
        "Report one finding for each supported missing property; do not put correct controls in findings. Unrelated text cannot label these controls. If only some targets are absent, record evidence gaps and assess the remaining targets. Abstain when none can be assessed. Evaluate static HTML only; no observed user or runtime behavior."
        if locale == "en"
        else f"Compito: {task}. Esamina la pagina completa fornita, concentrandoti sul modulo #{case.form}. Controlla separatamente ogni elemento: {'; '.join(checks)}. "
        "Riporta un finding per ogni proprietà mancante supportata; non inserire controlli corretti nei finding. Testi estranei non etichettano questi controlli. Se mancano solo alcuni elementi, registra le lacune e valuta gli altri. Astieniti quando nessuno è valutabile. Esamina soltanto HTML statico; nessuna osservazione di utenti o runtime."
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
                else "Profilo sintetico per revisione statica; il comportamento utente non è stato osservato."
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


def _gap(observation: dict, locale: str) -> str:
    target = observation["target"]
    reason = observation["reason"]
    if locale == "en":
        reasons = {
            "CONTENT_NOT_SUPPLIED": "HTML content was not supplied",
            "FORM_ABSENT": "the selected form is absent",
            "TARGET_ABSENT_FROM_FORM": "this target is absent from the selected form",
        }
        return f"#{target} cannot be assessed: {reasons[reason]}."
    reasons = {
        "CONTENT_NOT_SUPPLIED": "il contenuto HTML non è fornito",
        "FORM_ABSENT": "il modulo selezionato è assente",
        "TARGET_ABSENT_FROM_FORM": "questo elemento è assente dal modulo selezionato",
    }
    return f"#{target} non è valutabile: {reasons[reason]}."


def _output(case: Scenario, locale: str, observations: list[dict], request):
    lang = int(locale == "it")
    task, field, action = localized(case, locale)
    role = ROLES[case.role][lang]
    descriptor = request.artifact_bundle.artifacts[0]
    findings, gaps = [], []
    for observation in observations:
        state, target, family = (observation[key] for key in ("state", "target", "family"))
        if state == "INSUFFICIENT":
            gaps.append(_gap(observation, locale))
        if state != "MISSING":
            continue
        check = CHECKS[family][lang]
        summary = f"#{target} lacks {check}." if locale == "en" else f"In #{target} manca {check}."
        repairs = {
            "input_label": (
                f"Add a nonempty label such as '{field}' with for='{target}'.",
                f"Aggiungi un'etichetta non vuota come '{field}' con for='{target}'.",
            ),
            "button_name": (
                f"Give #{target} a nonempty name such as '{action}' using button text, aria-label or valid aria-labelledby references.",
                f"Assegna a #{target} un nome non vuoto come '{action}' tramite testo, aria-label o riferimenti aria-labelledby validi.",
            ),
            "image_text": (
                f"Provide meaningful nonempty alt text on #{target} describing the informative image.",
                f"Fornisci in #{target} un testo alt non vuoto e significativo per l'immagine informativa.",
            ),
            "heading": (
                f"Add descriptive nonempty heading text to #{target}.",
                f"Aggiungi un testo di titolo descrittivo e non vuoto in #{target}.",
            ),
            "error_guidance": (
                f"Add nonempty recovery instructions to #{target}.",
                f"Aggiungi istruzioni di recupero non vuote in #{target}.",
            ),
        }
        rationale = (
            f"The supplied HTML for #{target} does not satisfy the specified property: {check}. This could hinder '{task}' for the represented {role}; no user behavior was observed."
            if locale == "en"
            else f"L'HTML fornito per #{target} non soddisfa la proprietà richiesta: {check}. Ciò potrebbe ostacolare '{task}' per il profilo {role}; nessun comportamento utente è stato osservato."
        )
        findings.append(
            dict(
                finding_id=f"UTF-{len(findings) + 1:03}",
                artifact_id=str(descriptor.artifact_id),
                artifact_version=descriptor.version_number,
                location=f"dom:#{target}",
                summary=summary,
                rationale=rationale,
                recommended_action=repairs[family][lang],
                criterion="actionability" if family == "error_guidance" else "accessibility",
                severity="major",
                epistemic_status="MODEL_INFERRED",
                evidence_refs=[f"artifact:{descriptor.artifact_id}:v{descriptor.version_number}"],
                confidence=0.7,
                requires_human_validation=True,
            )
        )
    missing = ", ".join(f"#{o['target']}" for o in observations if o["state"] == "MISSING")
    correct = ", ".join(f"#{o['target']}" for o in observations if o["state"] == "PRESENT")
    parts = []
    if missing:
        parts.append(
            f"Missing required properties: {missing}."
            if locale == "en"
            else f"Proprietà richieste mancanti: {missing}."
        )
    if correct:
        parts.append(
            f"Specified static checks satisfied: {correct}."
            if locale == "en"
            else f"Controlli statici richiesti soddisfatti: {correct}."
        )
    parts.extend(gaps)
    parts.append(
        "Simulated static assessment; human validation is required."
        if locale == "en"
        else "Valutazione statica simulata; è richiesta verifica umana."
    )
    return dict(
        overall_summary=" ".join(parts),
        findings=findings,
        evidence_gaps=gaps,
        abstained=all(o["state"] == "INSUFFICIENT" for o in observations),
    )


def example(case: Scenario, locale: str, mode: str, states: tuple[str, ...]) -> dict:
    raw = render(case, locale, mode, states)
    controls = [dict(target=control.target, family=control.family) for control in case.controls]
    supplied = mode != "content_unavailable"
    observations = observe(raw if supplied else None, case.form, controls)
    if tuple(item["state"] for item in observations) != states:
        raise ValueError("rendered control facts disagree with declared counterfactual")
    request, payload = _request(case, locale, raw, supplied)
    output = _output(case, locale, observations, request)
    judgement = (
        "INSUFFICIENT"
        if output["abstained"]
        else "PARTIAL"
        if output["evidence_gaps"]
        else "MISSING"
        if output["findings"]
        else "PRESENT"
    )
    user = dict(
        task_id=USER_TWIN_MODEL_EVALUATION_TASK_ID,
        input=payload,
        allowed_evidence_refs=[e.reference_id for e in request.evidence],
        output_schema=SCHEMA,
        response_contract=list(RESPONSE_CONTRACT),
    )
    row = dict(
        group_id=case.group_id,
        split=case.split,
        family="complete_interface",
        component="complete_interface",
        locale=locale,
        judgement=judgement,
        synthetic=True,
        empirical=False,
        service_family=case.service,
        structure_family=case.layout,
        form_target=case.form,
        condition=mode,
        control_judgements=observations,
        messages=[
            dict(role="system", content=INSTRUCTION),
            dict(role="user", content=canonical_json(user)),
            dict(role="assistant", content=canonical_json(output)),
        ],
    )
    validate_annotations(row)
    return row


def iter_curriculum(*, seed: int, split: str, groups: int):
    if (
        isinstance(groups, bool)
        or not isinstance(groups, int)
        or not 3 <= groups <= 30000
        or groups % 3
    ):
        raise ValueError(
            "complete-interface groups must be a multiple of three between 3 and 30000"
        )
    # Shuffle group order and siblings deterministically without materializing the corpus.
    order = list(range(groups))
    random.Random(f"{seed}:{split}").shuffle(order)
    for ordinal in order:
        case = scenario(seed, split, ordinal)
        selected = [
            (locale, mode, states) for mode, states in conditions(case) for locale in ("en", "it")
        ]
        random.Random(case.group_id).shuffle(selected)
        for locale, mode, states in selected:
            yield example(case, locale, mode, states)
