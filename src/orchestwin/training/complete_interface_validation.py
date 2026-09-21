"""Independent HTMLParser oracle and annotation checks for the closed v3 grammar.

This checks static fixture facts, not the full accessible-name algorithm, rendered
visibility, real-user impact, or arbitrary web accessibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from html.parser import HTMLParser

from orchestwin.models.strict_evaluator_json import validate_evaluator_value
from orchestwin.training.evaluator_assessment import validate_domain_response
from orchestwin.training.grounded_evaluator_curriculum import SCHEMA


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
                # Generated cases never combine competing naming sources.
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


def validate_annotations(row: dict) -> list[dict]:
    user = json.loads(row["messages"][1]["content"])
    output = json.loads(row["messages"][2]["content"])
    content = user["input"].get("verified_artifact_content")
    raw = None
    if content is not None:
        if content["source_truncation_performed"] or len(content["items"]) != 1:
            raise ValueError("complete fixture content required")
        item = content["items"][0]
        raw = item["data"]
        if hashlib.sha256(raw.encode()).hexdigest() != item["artifact"]["sha256_digest"]:
            raise ValueError("fixture content digest differs")
    actual = observe(raw, row["form_target"], row["control_judgements"])
    if actual != row["control_judgements"]:
        raise ValueError("control annotation disagrees with independent HTML oracle")
    expected = {item["target"] for item in actual if item["state"] == "MISSING"}
    missing_evidence = {item["target"] for item in actual if item["state"] == "INSUFFICIENT"}
    locations = [finding["location"] for finding in output["findings"]]
    if set(locations) != {f"dom:#{target}" for target in expected} or len(locations) != len(
        expected
    ):
        raise ValueError("annotation must cover each missing control exactly once")
    if bool(output["evidence_gaps"]) != bool(missing_evidence):
        raise ValueError("annotation evidence gaps disagree with absent controls")
    if output["abstained"] != (len(missing_evidence) == len(actual)):
        raise ValueError("annotation must distinguish partial evidence from full abstention")
    for finding in output["findings"]:
        control = next(item for item in actual if finding["location"] == f"dom:#{item['target']}")
        expected_criterion = (
            "actionability" if control["family"] == "error_guidance" else "accessibility"
        )
        if finding["criterion"] != expected_criterion:
            raise ValueError("annotation criterion differs from the requested property")
        if (
            finding["epistemic_status"] != "MODEL_INFERRED"
            or not finding["requires_human_validation"]
        ):
            raise ValueError("synthetic annotation cannot claim human or empirical validation")
    validate_evaluator_value(output, SCHEMA)
    validate_domain_response(output, row)
    return actual
