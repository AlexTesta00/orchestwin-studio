"""Synthetic contract-calibration candidates; never empirical user-study labels.

Historical S66/S67 data stays immutable. Counterfactual siblings and translations
share one split, and opaque identifiers are independent of the target judgement.
The small controlled HTML vocabulary supports exact, deliberately narrow oracles.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime
from html import escape
from uuid import UUID
from xml.etree import ElementTree

from orchestwin.evaluation.artifact_content import (
    artifact_content_instruction,
    prepare_artifact_content,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    UserTwinEvaluationRequest,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.field_scope_prompt import field_scope_instruction
from orchestwin.evaluation.model_evaluator import (
    USER_TWIN_MODEL_EVALUATION_TASK_ID,
    _input_payload,
    _output_schema_payload,
    _response_from_payload,
    _system_instruction,
)
from orchestwin.models.final_evaluator_gateway import RESPONSE_CONTRACT
from orchestwin.models.strict_evaluator_json import validate_evaluator_value
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

CURRICULUM_ID = "grounded-evaluator-contract-calibration-v1"
NOW = datetime(2026, 9, 14, tzinfo=UTC)
FAMILIES = (
    "button_name",
    "input_label",
    "image_text",
    "document_language",
    "error_guidance",
    "heading",
)
SCHEMA = _output_schema_payload(require_finding_id_pattern=True)
INSTRUCTION = artifact_content_instruction(field_scope_instruction(_system_instruction(), SCHEMA))
TASKS = (
    ("Confirm booking", "Conferma prenotazione"),
    ("Save draft", "Salva bozza"),
    ("Search catalogue", "Cerca nel catalogo"),
    ("Send request", "Invia richiesta"),
    ("Cancel order", "Annulla ordine"),
    ("Update address", "Aggiorna indirizzo"),
    ("Export report", "Esporta rapporto"),
    ("Review details", "Controlla dettagli"),
)
ROLES = (
    ("Office coordinator", "Coordinatore ufficio"),
    ("Library visitor", "Visitatore biblioteca"),
    ("Service operator", "Operatore servizio"),
    ("Course participant", "Partecipante al corso"),
)
CHECKS = {
    "button_name": (
        "a nonempty accessible name on the target button",
        "un nome accessibile non vuoto sul pulsante indicato",
    ),
    "input_label": (
        "an explicit label associated with the target input",
        "un'etichetta esplicita associata al campo indicato",
    ),
    "image_text": (
        "nonempty alternative text for the target informative image",
        "un testo alternativo non vuoto per l'immagine informativa indicata",
    ),
    "document_language": (
        "a language declaration on the document element",
        "una dichiarazione di lingua nell'elemento radice del documento",
    ),
    "error_guidance": (
        "nonempty recovery text in the target error element",
        "un testo di recupero non vuoto nell'elemento di errore indicato",
    ),
    "heading": (
        "nonempty text in the target page heading",
        "un testo non vuoto nel titolo di pagina indicato",
    ),
}


def _uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def oracle(raw: str | None, family: str, target: str) -> str:
    """Classify only our closed XML-compatible HTML fixtures, not arbitrary sites."""
    if family not in FAMILIES:
        raise ValueError("unknown calibration family")
    if raw is None:
        return "INSUFFICIENT"
    root = ElementTree.fromstring(raw)
    element = next((e for e in root.iter() if e.get("id") == target), None)
    if element is None:
        return "INSUFFICIENT"
    if family == "button_name":
        present = bool(element.get("aria-label", "").strip() or "".join(element.itertext()).strip())
    elif family == "input_label":
        present = any(
            e.tag == "label" and e.get("for") == target and "".join(e.itertext()).strip()
            for e in root.iter()
        )
    elif family == "image_text":
        present = bool(element.get("alt", "").strip())
    elif family == "document_language":
        present = bool(element.get("lang", "").strip())
    else:
        present = bool("".join(element.itertext()).strip())
    return "PRESENT" if present else "MISSING"


def _html(family: str, target: str, text: str, locale: str, present: bool) -> str:
    value = escape(text) if present else ""
    snippet = {
        "button_name": f'<button id="{target}" aria-label="{value}"></button>',
        "input_label": (f'<label for="{target}">{value}</label>' if present else "")
        + f'<input id="{target}" />',
        "image_text": f'<img id="{target}" src="diagram.png" alt="{value}" />',
        "document_language": "",
        "error_guidance": f'<p id="{target}" role="alert">{value}</p>',
        "heading": f'<h1 id="{target}">{value}</h1>',
    }[family]
    language = locale if present or family != "document_language" else ""
    document_id = target if family == "document_language" else "document"
    # Opposite-state distractors make the selected element matter.
    distractor = '<button id="unrelated">Help</button><button id="empty"></button>'
    return f'<html id="{document_id}" lang="{language}"><body><main>{snippet}{distractor}</main></body></html>'


def example(*, seed: int, family: str, variant: int, locale: str, state: str) -> dict:
    if (
        family not in FAMILIES
        or locale not in {"en", "it"}
        or state not in {"MISSING", "PRESENT", "INSUFFICIENT"}
    ):
        raise ValueError("invalid calibration selection")
    # State/locale are absent from identity seed: siblings have the same opaque IDs.
    group = hashlib.sha256(f"{CURRICULUM_ID}:{seed}:{family}:{variant}".encode()).hexdigest()
    rng = random.Random(group)
    project, workflow, artifact, twin_id, evaluation, scenario_id, bundle_id = (
        _uuid(rng) for _ in range(7)
    )
    version = rng.randint(1, 20)
    target = "target-" + _uuid(rng).hex[:10]
    lang = int(locale == "it")
    task = TASKS[variant % len(TASKS)][lang]
    role = ROLES[(variant // len(TASKS)) % len(ROLES)][lang]
    check = CHECKS[family][lang]
    raw = _html(family, target, task, locale, state == "PRESENT")
    supplied = None if state == "INSUFFICIENT" else raw
    judgement = oracle(supplied, family, target)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    descriptor = EvaluationArtifactReference(
        artifact_id=artifact,
        version_number=version,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(raw.encode()),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location=f"dom:#{target}",
    )
    task_scope = (
        f"For the task '{task}', inspect only {check} (element #{target}). Evaluate the supplied static text; runtime behaviour is outside this scenario."
        if locale == "en"
        else f"Per il compito '{task}', controlla soltanto {check} (elemento #{target}). Valuta il testo statico fornito; il comportamento a runtime è fuori da questo scenario."
    )
    bundle = create_evaluation_artifact_bundle(
        project_id=project,
        workflow_run_id=workflow,
        scenario=EvaluationScenario(scenario_id, task, task_scope, locale, (check,)),
        artifacts=(descriptor,),
        created_at=NOW,
        bundle_id=bundle_id,
    )
    profile = canonical_json(
        {
            "name": role,
            "role": role,
            "operational_constraints": [
                "Uses the supplied interface to complete the stated task; no observed user study."
            ],
        }
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
    if supplied is not None:
        prepared = prepare_artifact_content(
            request, selected=((artifact, version),), read_content=lambda *_: raw.encode()
        )
        request = prepared.request
        payload = prepared.content.enrich(request, _input_payload(request))
    missing = judgement == "MISSING"
    gap = (
        "Artifact content was not supplied; identifiers and hashes do not reveal the element."
        if locale == "en"
        else "Il contenuto dell'artefatto non è fornito; identificativi e hash non mostrano l'elemento."
    )
    summary = (
        (
            f"The supplied element lacks {check}. This is a simulated assessment requiring human validation."
            if locale == "en"
            else f"Nell'elemento fornito manca {check}. Questa valutazione simulata richiede verifica umana."
        )
        if missing
        else (
            gap
            if judgement == "INSUFFICIENT"
            else (
                "The supplied element satisfies this narrow text check; no conclusion about complete accessibility or real-user performance."
                if locale == "en"
                else "L'elemento fornito soddisfa questo controllo testuale circoscritto; nessuna conclusione sull'accessibilità completa o sulle prestazioni di utenti reali."
            )
        )
    )
    findings = []
    if missing:
        findings.append(
            {
                "finding_id": "UTF-001",
                "artifact_id": str(artifact),
                "artifact_version": version,
                "location": descriptor.location,
                "summary": summary,
                "rationale": (
                    f"The supplied static content at #{target} does not contain {check}; this could hinder the task '{task}' for {role}. No user behaviour was observed."
                    if locale == "en"
                    else f"Il contenuto statico fornito in #{target} non contiene {check}; questo potrebbe ostacolare il compito '{task}' per {role}. Nessun comportamento utente è stato osservato."
                ),
                "criterion": "actionability" if family == "error_guidance" else "accessibility",
                "severity": "major",
                "epistemic_status": "MODEL_INFERRED",
                "evidence_refs": [f"artifact:{artifact}:v{version}"],
                "confidence": 0.7,
                "recommended_action": (
                    f"Provide {check} on #{target} and verify it with the represented user."
                    if locale == "en"
                    else f"Fornisci {check} in #{target} e verificalo con l'utente rappresentato."
                ),
                "requires_human_validation": True,
            }
        )
    output = {
        "overall_summary": summary,
        "findings": findings,
        "evidence_gaps": [gap] if judgement == "INSUFFICIENT" else [],
        "abstained": judgement == "INSUFFICIENT",
    }
    validate_evaluator_value(output, SCHEMA)
    _response_from_payload(
        request=request,
        configuration=UserTwinEvaluatorConfiguration(
            CURRICULUM_ID, "1", "synthetic-candidate", "contract-calibration-v1"
        ),
        payload=output,
        completed_at=NOW,
    )
    user = {
        "task_id": USER_TWIN_MODEL_EVALUATION_TASK_ID,
        "input": payload,
        "allowed_evidence_refs": [e.reference_id for e in request.evidence],
        "output_schema": SCHEMA,
        "response_contract": list(RESPONSE_CONTRACT),
    }
    return {
        "group_id": group,
        "family": family,
        "locale": locale,
        "judgement": judgement,
        "synthetic": True,
        "empirical": False,
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": canonical_json(user)},
            {"role": "assistant", "content": canonical_json(output)},
        ],
    }


def build_curriculum(*, seed: int = 20260914, variants: int = 32) -> list[dict]:
    if variants < 8 or variants > 256:
        raise ValueError("calibration requires between 8 and 256 variants")
    rows = []
    for family in FAMILIES:
        for variant in range(variants):
            # Split by scenario, not row. Held-out tasks are unseen across every family.
            split = "test" if variant % 8 == 7 else "validation" if variant % 8 == 6 else "train"
            for locale in ("en", "it"):
                for state in ("MISSING", "PRESENT", "INSUFFICIENT"):
                    row = example(
                        seed=seed, family=family, variant=variant, locale=locale, state=state
                    )
                    row["split"] = split
                    rows.append(row)
    random.Random(seed).shuffle(rows)
    return rows
