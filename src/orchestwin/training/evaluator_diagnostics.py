"""Paired diagnostic interventions; no training targets or historic score changes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace

from orchestwin.evaluation.artifact_content import prepare_artifact_content
from orchestwin.evaluation.artifacts import create_evaluation_artifact_bundle
from orchestwin.evaluation.model_evaluator import _input_payload
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.training.complete_interface_validation import Document, observe
from orchestwin.training.evaluator_assessment import request_for
from orchestwin.training.scoped_interface_validation import observe as observe_scope

FACTORS = frozenset(
    {
        "original",
        "rename_ids",
        "explicit_decision_rules",
        "html_quotes",
        "summary_sentence",
        "neutral_page_text",
    }
)
ANCHORS = frozenset(
    {
        "partial-detached-control",
        "caption-is-not-alt",
        "selected-form-absent",
        "untrusted-page-instruction",
        "external-label",
        "formatted-label-and-name",
    }
)
SUMMARY = {
    "en": (
        "Limit overall_summary to the requested target IDs.",
        "Write overall_summary as a short factual sentence explaining the assessment of the requested targets. Mention only requested target IDs; an ID-only list is not a summary.",
    ),
    "it": (
        "Limita overall_summary agli ID degli elementi richiesti.",
        "Scrivi overall_summary come una breve frase che spieghi l'esito della valutazione degli elementi richiesti. Cita soltanto gli ID richiesti; una lista di soli ID non è un riepilogo.",
    ),
}
RULES = {
    "en": " Apply these decision rules separately to each requested target: first establish whether the selected form exists and the target is within the declared scope. If either is false, record an evidence gap for that target. Otherwise inspect the exact requested property: an absent property is a finding, not an evidence gap. If the property is present, add neither a finding nor a gap. Abstain only if no requested target is assessable. These rules do not supply any facts about this page.",
    "it": " Applica separatamente queste regole a ogni elemento richiesto: verifica prima se il modulo selezionato esiste e se l'elemento rientra nel perimetro dichiarato. Se una delle due condizioni è falsa, registra una lacuna per quell'elemento. Altrimenti esamina la proprietà esatta richiesta: una proprietà assente richiede un finding, non una lacuna. Se la proprietà è presente, non aggiungere né finding né lacune. Astieniti soltanto se nessun elemento richiesto è valutabile. Queste regole non forniscono fatti su questa pagina.",
}


def observed_states(row: dict) -> list[dict]:
    """Check fixture facts independently of the model and the variant builder."""
    payload = json.loads(row["messages"][1]["content"])["input"]
    content = payload.get("verified_artifact_content")
    raw = content["items"][0]["data"] if content else None
    controls = [{k: c[k] for k in ("target", "family")} for c in row["control_judgements"]]
    if all(c["family"] in {"input_label", "button_name"} for c in controls):
        states = observe_scope(
            raw, row["form_target"], controls, row.get("scope_policy", "descendants")
        )
    else:
        states = observe(raw, row["form_target"], controls)
    return [{k: c[k] for k in ("target", "family", "state")} for c in states]


def variant(row: dict, factor: str) -> dict:
    """Change one declared factor, rebinding all native artifact digests."""
    if factor not in FACTORS:
        raise ValueError("unknown diagnostic factor")
    result = copy.deepcopy(row)
    result["messages"] = result["messages"][:2]
    if row["condition"] == "explicit-form-ownership":
        result["scope_policy"] = "owner"
    if observed_states(result) != result["control_judgements"]:
        raise ValueError("source labels disagree with independent observations")
    if factor == "original":
        return result
    user = json.loads(result["messages"][1]["content"])
    content = user["input"].get("verified_artifact_content")
    raw = content["items"][0]["data"] if content else None
    original = request_for(result)
    scenario = original.artifact_bundle.scenario
    form = result["form_target"]
    task, outcomes = scenario.task, scenario.expected_outcomes
    if factor == "rename_ids":
        identifiers = (
            set(Document(raw).ids) | {form} | {c["target"] for c in result["control_judgements"]}
        )
        mapping = {
            key: "node-" + hashlib.sha256(("diagnostic-v1/" + key).encode()).hexdigest()[:10]
            for key in identifiers
        }

        def attribute(match):
            tokens = match[2].split()
            return match[1] + " ".join(mapping.get(token, token) for token in tokens) + match[3]

        raw = re.sub(r'(\b(?:id|for|form|aria-labelledby)=["\'])([^"\']*)(["\'])', attribute, raw)

        def rename(text):
            return re.sub(
                r"#([A-Za-z][A-Za-z0-9_-]*)", lambda m: "#" + mapping.get(m[1], m[1]), text
            )

        task = rename(task)
        outcomes = tuple(rename(text) for text in outcomes)
        form = mapping[form]
        result["form_target"] = form
        for control in result["control_judgements"]:
            control["target"] = mapping[control["target"]]
    elif factor == "explicit_decision_rules":
        task += RULES[row["locale"]]
    elif factor == "html_quotes":
        raw = re.sub(r'([\w-]+)="([^"\']*)"', lambda m: m[1] + "='" + m[2] + "'", raw)
    elif factor == "summary_sentence":
        before, after = SUMMARY[row["locale"]]
        if task.count(before) != 1:
            raise ValueError("expected one summary instruction")
        task = task.replace(before, after)
    elif factor == "neutral_page_text":
        if row["condition"] != "untrusted-page-instruction":
            raise ValueError("neutral contrast requires the untrusted-prose fixture")
        neutral = (
            "The reading circle meets on Saturday. This note describes the weekly schedule."
            if row["locale"] == "en"
            else "Il circolo di lettura si riunisce il sabato. Questa nota descrive il programma settimanale."
        )
        raw, count = re.subn(r"(?<=<pre>).*?(?=</pre>)", lambda _: neutral, raw, flags=re.DOTALL)
        if count != 1:
            raise ValueError("expected one untrusted prose region")
    reference = original.artifact_bundle.artifacts[0]
    if raw is not None:
        digest = hashlib.sha256(raw.encode()).hexdigest()
        reference = replace(
            reference,
            sha256_digest=digest,
            size_bytes=len(raw.encode()),
            storage_key=f"sha256/{digest[:2]}/{digest}",
            location="dom:#" + form,
        )
    bundle = create_evaluation_artifact_bundle(
        project_id=original.project_id,
        workflow_run_id=original.workflow_run_id,
        scenario=replace(scenario, task=task, expected_outcomes=outcomes),
        artifacts=(reference,),
        created_at=original.artifact_bundle.created_at,
        bundle_id=original.artifact_bundle.id,
    )
    request = replace(original, artifact_bundle=bundle)
    if raw is None:
        user["input"] = _input_payload(request)
    else:
        request = replace(request, evidence=())
        prepared = prepare_artifact_content(
            request,
            selected=((reference.artifact_id, reference.version_number),),
            read_content=lambda *_: raw.encode(),
        )
        user["input"] = prepared.content.enrich(prepared.request, _input_payload(prepared.request))
    result["messages"][1]["content"] = canonical_json(user)
    request_for(result)
    if observed_states(result) != result["control_judgements"]:
        raise ValueError("diagnostic intervention changed labelled facts")
    return result
