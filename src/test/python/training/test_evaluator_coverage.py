"""Coverage must distinguish physically absent targets from relocated ones."""

import hashlib
import json

import pytest

from orchestwin.training.evaluator_coverage import audit_training_coverage, structural_features


def row(html, controls, *, form="reservation"):
    item = {"data": html, "artifact": {"sha256_digest": hashlib.sha256(html.encode()).hexdigest()}}
    return {
        "split": "train",
        "family": "complete_interface",
        "locale": "en",
        "form_target": form,
        "control_judgements": [
            {"target": target, "family": family, "state": state}
            for target, family, state in controls
        ],
        "messages": [
            {"role": "system", "content": "synthetic coverage fixture"},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "input": {
                            "verified_artifact_content": {
                                "items": [item],
                                "source_truncation_performed": False,
                            }
                        }
                    }
                ),
            },
        ],
    }


def test_relocated_target_and_absent_form_are_not_conflated_with_missing_nodes():
    controls = [("person", "input_label", "INSUFFICIENT")]
    absent = row('<html><form id="reservation"></form></html>', controls)
    relocated = row('<html><input id="person" /><form id="reservation"></form></html>', controls)
    no_form = row('<html><input id="person" /></html>', controls)
    assert structural_features(absent)["unassessable_target_present_outside_form"] == 0
    assert structural_features(relocated)["unassessable_target_present_outside_form"] == 1
    assert structural_features(relocated)["selected_form_absent_but_requested_targets_present"] == 0
    assert structural_features(no_form)["selected_form_absent_but_requested_targets_present"] == 1


def test_implicit_label_detection_preserves_anonymous_ancestors_and_explicit_links():
    html = '<html><form id="reservation"><label><b>Person</b><input id="person" /></label></form>{}</html>'
    controls = [("person", "input_label", "MISSING")]
    assert (
        structural_features(row(html.format(""), controls))[
            "implicit_label_without_requested_explicit_label"
        ]
        == 1
    )
    explicit = '<label for="person">Person</label>'
    assert (
        structural_features(row(html.format(explicit), controls))[
            "implicit_label_without_requested_explicit_label"
        ]
        == 0
    )
    wrong_link = html.format("").replace("<label>", '<label for="another">')
    assert (
        structural_features(row(wrong_link, controls))[
            "implicit_label_without_requested_explicit_label"
        ]
        == 0
    )


def test_unrequested_controls_are_counted_only_inside_actual_form():
    html = '<html><form id="reservation"><button id="save">Save</button><input id="extra" /></form><input id="help" /></html>'
    controls = [("save", "button_name", "PRESENT")]
    assert (
        structural_features(row(html, controls))["unrequested_controls_inside_selected_form"] == 1
    )
    assert (
        structural_features(
            row(html.replace("<form", "<div").replace("</form", "</div"), controls)
        )["unrequested_controls_inside_selected_form"]
        == 0
    )


def test_external_form_ownership_is_recorded_without_changing_gold_scope():
    html = '<html><form id="reservation"></form><button id="save" form="reservation">Save</button></html>'
    value = row(html, [("save", "button_name", "PRESENT")])
    result = structural_features(value)
    assert result["requested_control_with_external_form_owner"] == 1
    assert result["unassessable_target_present_outside_form"] == 0
    image = row(
        '<html><form id="reservation"></form><img id="map" form="reservation" /></html>',
        [("map", "image_text", "INSUFFICIENT")],
    )
    assert structural_features(image)["requested_control_with_external_form_owner"] == 0


def test_metadata_only_rows_are_not_mistaken_for_observed_html():
    value = row("", [("person", "input_label", "INSUFFICIENT")])
    value["messages"][1]["content"] = json.dumps({"input": {}})
    assert not any(structural_features(value).values())


def test_streaming_audit_pins_bytes_and_separates_legacy_rows(tmp_path):
    value = row('<html><input id="person" /></html>', [("person", "input_label", "INSUFFICIENT")])
    path = tmp_path / "train.jsonl"
    raw = (
        json.dumps(value) + "\n" + json.dumps({"split": "train", "family": "legacy"}) + "\n"
    ).encode()
    path.write_bytes(raw)
    report = audit_training_coverage(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    assert report["training_rows"] == 2
    assert report["analysed_rows"] == report["unanalysed_rows"] == 1
    assert report["features"]["selected_form_absent_but_requested_targets_present"]["rows"] == 1
    with pytest.raises(ValueError, match="hash differs"):
        audit_training_coverage(path, expected_sha256="0" * 64)


def test_nontraining_rows_and_paths_are_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"select train\.jsonl"):
        audit_training_coverage(tmp_path / "test.jsonl", expected_sha256="0" * 64)
    path = tmp_path / "train.jsonl"
    path.write_text('{"split":"validation"}\n')
    with pytest.raises(ValueError, match="non-training row"):
        audit_training_coverage(path, expected_sha256="0" * 64)


def test_tampered_content_is_rejected():
    value = row("<html></html>", [])
    payload = json.loads(value["messages"][1]["content"])
    payload["input"]["verified_artifact_content"]["items"][0]["data"] = "<html>changed</html>"
    value["messages"][1]["content"] = json.dumps(payload)
    with pytest.raises(ValueError, match="content digest"):
        structural_features(value)
