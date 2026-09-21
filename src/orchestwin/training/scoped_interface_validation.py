"""Independent observations for the explicitly declared synthetic scope policies."""

from __future__ import annotations

import hashlib
import json
import re

from orchestwin.models.strict_evaluator_json import validate_evaluator_value
from orchestwin.training.complete_interface_validation import Document
from orchestwin.training.evaluator_assessment import validate_domain_response
from orchestwin.training.grounded_evaluator_curriculum import SCHEMA


def observe(raw: str | None, form_id: str, controls: list[dict], scope: str) -> list[dict]:
    if (
        scope not in {"descendants", "owner"}
        or not controls
        or len({c["target"] for c in controls}) != len(controls)
    ):
        raise ValueError("explicit scope and unique requested controls required")
    document = Document(raw) if raw is not None else None
    if document and document.stack:
        raise ValueError("unclosed scoped fixture")
    form = document.ids.get(form_id) if document else None
    results = []
    for control in controls:
        target, family = control["target"], control["family"]
        if family not in {"input_label", "button_name"}:
            raise ValueError("unsupported scoped property")
        element = document.ids.get(target) if document else None
        reason = (
            "CONTENT_NOT_SUPPLIED"
            if document is None
            else "FORM_ABSENT"
            if form is None or form.tag != "form"
            else None
        )
        if reason is None:
            eligible = element is not None and form_id in element.ancestors
            if element is not None and scope == "owner" and "form" in element.attrs:
                eligible = element.tag in {"input", "button"} and element.attrs["form"] == form_id
            if not eligible:
                reason = "OUTSIDE_REQUESTED_SCOPE"
        if reason:
            results.append(dict(control, state="INSUFFICIENT", reason=reason))
            continue
        if family == "input_label":
            present = element.tag == "input" and any(
                e.tag == "label" and e.attrs.get("for") == target and e.text
                for e in document.elements
            )
            reason = "NO_EXPLICIT_LABEL"
        else:
            refs = (element.attrs.get("aria-labelledby") or "").split()
            present = element.tag == "button" and bool(
                element.text
                or (element.attrs.get("aria-label") or "").strip()
                or any(document.ids[r].text for r in refs if r in document.ids)
            )
            reason = "NO_BUTTON_NAME"
        results.append(
            dict(
                control,
                state="PRESENT" if present else "MISSING",
                reason="PROPERTY_PRESENT" if present else reason,
            )
        )
    return results


def validate_annotations(row: dict) -> None:
    payload = json.loads(row["messages"][1]["content"])["input"]
    content = payload.get("verified_artifact_content")
    raw = None
    if content:
        if content["source_truncation_performed"] or len(content["items"]) != 1:
            raise ValueError("one complete fixture required")
        item = content["items"][0]
        raw = item["data"]
        if hashlib.sha256(raw.encode()).hexdigest() != item["artifact"]["sha256_digest"]:
            raise ValueError("fixture content digest differs")
    actual = observe(
        raw,
        row["form_target"],
        [{k: c[k] for k in ("target", "family")} for c in row["control_judgements"]],
        row["scope_policy"],
    )
    if actual != row["control_judgements"]:
        raise ValueError("scoped annotations disagree with independently parsed facts")
    value = json.loads(row["messages"][2]["content"])
    expected = {"dom:#" + c["target"] for c in actual if c["state"] == "MISSING"}
    locations = [f["location"] for f in value["findings"]]
    gaps = [c["target"] for c in actual if c["state"] == "INSUFFICIENT"]
    requested = {"#" + c["target"] for c in actual}
    if set(locations) != expected or len(locations) != len(expected):
        raise ValueError("each requested missing property must be reported exactly once")
    if value["abstained"] != (len(gaps) == len(actual)) or len(value["evidence_gaps"]) != len(gaps):
        raise ValueError("scope gaps and abstention disagree with observations")
    if any(
        "#" + target not in gap for target, gap in zip(gaps, value["evidence_gaps"], strict=True)
    ):
        raise ValueError("gap must identify its requested target")
    for text in [value["overall_summary"], *value["evidence_gaps"]]:
        if not set(re.findall(r"#[A-Za-z][A-Za-z0-9_-]*", text)) <= requested:
            raise ValueError("summary or gap mentions an unrequested target")
    for finding in value["findings"]:
        if (
            finding["criterion"] != "accessibility"
            or finding["epistemic_status"] != "MODEL_INFERRED"
            or not finding["requires_human_validation"]
        ):
            raise ValueError("synthetic finding cannot claim empirical or human validation")
    validate_evaluator_value(value, SCHEMA)
    validate_domain_response(value, row)
