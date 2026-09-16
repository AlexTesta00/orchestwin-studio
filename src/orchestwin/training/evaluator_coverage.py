"""Measure structural coverage in the closed complete-interface training grammar.

These are dataset counts, not model scores or a general HTML accessibility audit.
Legacy rows remain visible as unanalysed; they are never counted as negative cases.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from orchestwin.training.complete_interface_validation import Document

FEATURES = (
    "unassessable_target_present_outside_form",
    "selected_form_absent_but_requested_targets_present",
    "implicit_label_without_requested_explicit_label",
    "unrequested_controls_inside_selected_form",
    "requested_control_with_external_form_owner",
)


class _CoverageDocument(Document):
    def __init__(self, raw: str):
        self.parents_by_id = {}
        super().__init__(raw)
        if self.stack:
            raise ValueError("unclosed fixture HTML")

    def handle_starttag(self, tag, attrs):
        parents = tuple(self.stack)
        super().handle_starttag(tag, attrs)
        if identifier := self.elements[-1].attrs.get("id"):
            self.parents_by_id[identifier] = parents


def structural_features(row: dict) -> dict[str, int]:
    """Count target/control occurrences per feature, using input structure and gold scope."""
    payload = json.loads(row["messages"][1]["content"])["input"]
    content = payload.get("verified_artifact_content")
    counts = dict.fromkeys(FEATURES, 0)
    if content is None:
        return counts
    if content["source_truncation_performed"] or len(content["items"]) != 1:
        raise ValueError("coverage audit requires one complete, untruncated fixture")
    item = content["items"][0]
    raw = item["data"]
    if hashlib.sha256(raw.encode()).hexdigest() != item["artifact"]["sha256_digest"]:
        raise ValueError("fixture content digest differs")
    document = _CoverageDocument(raw)
    form_id = row["form_target"]
    form = document.ids.get(form_id)
    form_present = form is not None and form.tag == "form"
    requested = {control["target"] for control in row["control_judgements"]}
    for control in row["control_judgements"]:
        target = control["target"]
        element = document.ids.get(target)
        if element is None:
            continue
        in_form = form_present and form_id in element.ancestors
        if control["state"] == "INSUFFICIENT" and not in_form:
            counts["unassessable_target_present_outside_form"] += 1
        if not form_present:
            counts["selected_form_absent_but_requested_targets_present"] += 1
        if (
            form_present
            and not in_form
            and element.tag in {"input", "button"}
            and element.attrs.get("form") == form_id
        ):
            counts["requested_control_with_external_form_owner"] += 1
        if control["family"] == "input_label" and element.tag == "input":
            implicit = any(
                e.tag == "label" and "for" not in e.attrs and e.text
                for e in document.parents_by_id[target]
            )
            explicit = any(
                e.tag == "label" and e.attrs.get("for") == target and e.text
                for e in document.elements
            )
            if implicit and not explicit:
                counts["implicit_label_without_requested_explicit_label"] += 1
    for identifier, element in document.ids.items():
        is_control = element.tag in {"input", "button", "img", "h1", "h2", "h3"} or (
            element.attrs.get("role") == "alert"
        )
        if (
            form_present
            and form_id in element.ancestors
            and identifier not in requested
            and is_control
        ):
            counts["unrequested_controls_inside_selected_form"] += 1
    return counts


def audit_training_coverage(path: Path, *, expected_sha256: str) -> dict:
    """Stream only the explicitly selected training split and bind counts to its bytes."""
    if path.name != "train.jsonl":
        raise ValueError("select train.jsonl explicitly; validation and test splits are excluded")
    digest = hashlib.sha256()
    rows, analysed = 0, 0
    families, locales = Counter(), Counter()
    feature_rows, feature_occurrences = Counter(), Counter()
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            row = json.loads(line)
            if row["split"] != "train":
                raise ValueError("non-training row in training coverage audit")
            rows += 1
            family = row.get("family", "UNSPECIFIED")
            families[family] += 1
            if family != "complete_interface":
                continue
            analysed += 1
            locales[row["locale"]] += 1
            features = structural_features(row)
            feature_occurrences.update(features)
            feature_rows.update(name for name, count in features.items() if count)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("training dataset hash differs from the pinned input")
    if rows == 0 or analysed == 0:
        raise ValueError("no complete-interface training rows to analyse")
    return {
        "schema_version": 1,
        "scope": "CLOSED_COMPLETE_INTERFACE_TRAINING_STRUCTURE",
        "training_sha256": actual_sha256,
        "training_rows": rows,
        "analysed_rows": analysed,
        "unanalysed_rows": rows - analysed,
        "family_counts": dict(sorted(families.items())),
        "analysed_locale_counts": dict(sorted(locales.items())),
        "features": {
            name: {"rows": feature_rows[name], "occurrences": feature_occurrences[name]}
            for name in FEATURES
        },
        "limitations": [
            "Counts describe the closed fixture grammar, not arbitrary browser DOM semantics.",
            "A zero applies only to analysed complete-interface rows; legacy rows are unanalysed.",
            "Coverage does not establish model accuracy, calibrated confidence or real-user impact.",
        ],
        "model_inference_performed": False,
        "validation_or_test_files_opened": False,
    }
