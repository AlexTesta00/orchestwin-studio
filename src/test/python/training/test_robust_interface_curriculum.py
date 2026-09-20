"""Surface invariance, real counterfactuals, retention and protected split boundaries."""

import importlib
import itertools
import json
from copy import deepcopy
from pathlib import Path

import pytest

from orchestwin.training.robust_interface_curriculum import example
from orchestwin.training.robust_interface_fixtures import (
    CURRICULUM_ID,
    ID_STYLES,
    MODES,
    case,
    identifiers,
    render,
)
from orchestwin.training.robustness_leakage import semantic_key


def response(row):
    return json.loads(row["messages"][2]["content"])


def html(row):
    return json.loads(row["messages"][1]["content"])["input"]["verified_artifact_content"]["items"][
        0
    ]["data"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("locale", ("en", "it"))
def test_surface_interventions_preserve_static_facts_and_native_claims(mode, locale):
    for split, ordinal in itertools.product(("train", "validation"), range(2)):
        item = case(456, split, ordinal)
        baseline = example(item, mode, locale)
        states = [(f["family"], f["state"], f["reason"]) for f in baseline["control_judgements"]]
        for style, quote, void, prose in itertools.product(
            ID_STYLES, ('"', "'"), ("native", "xml"), ("neutral", "instruction")
        ):
            row = example(item, mode, locale, style, quote, void, prose)
            assert [
                (f["family"], f["state"], f["reason"]) for f in row["control_judgements"]
            ] == states
            native = response(row)
            assert native["abstained"] == response(baseline)["abstained"]
            assert all(
                f["epistemic_status"] == "MODEL_INFERRED" and f["requires_human_validation"]
                for f in native["findings"]
            )
            assert all(f["target"] in native["overall_summary"] for f in row["control_judgements"])
            if prose == "neutral" or mode == "content_unavailable":
                assert semantic_key(row) == semantic_key(baseline)


@pytest.mark.parametrize("split", ("train", "validation"))
@pytest.mark.parametrize("locale", ("en", "it"))
def test_identical_html_changes_assessability_only_when_scope_policy_changes(split, locale):
    item = case(8, split, 0)
    descendant, owner = [
        example(item, mode, locale) for mode in ("owned_descendants", "owned_owner")
    ]
    assert html(descendant) == html(owner)
    assert semantic_key(descendant) != semantic_key(owner)
    assert len(response(descendant)["evidence_gaps"]) == 2
    assert not response(descendant)["abstained"]  # The image is still assessable.
    assert not response(owner)["evidence_gaps"]
    assert not response(owner)["findings"]


def test_external_label_and_image_caption_counterfactuals_change_only_requested_property():
    item = case(8, "train", 0)
    good, wrong = [
        example(item, mode, "en") for mode in ("external_label_present", "external_label_wrong")
    ]
    _, field, _, image, spare = identifiers(item, "short")
    assert html(good).replace(f'for="{field}"', f'for="{spare}"') == html(wrong)
    assert not response(good)["findings"]
    assert [f["location"] for f in response(wrong)["findings"]] == ["dom:#" + field]
    present, missing = [
        example(item, mode, "en") for mode in ("all_present", "caption_without_alt")
    ]
    assert html(present).replace(' alt="Service location"', "") == html(missing)
    assert [f["location"] for f in response(missing)["findings"]] == ["dom:#" + image]
    assert semantic_key(good) != semantic_key(wrong)
    assert semantic_key(present) != semantic_key(missing)


def test_missing_properties_absent_form_and_absent_content_have_distinct_evidence():
    item = case(19, "validation", 1)
    for mode in ("form_absent", "content_unavailable"):
        value = response(example(item, mode, "it"))
        assert value["abstained"] and len(value["evidence_gaps"]) == 3 and not value["findings"]
    value = response(example(item, "all_missing", "it"))
    assert not value["abstained"] and not value["evidence_gaps"] and len(value["findings"]) == 3
    partial = response(example(item, "partial_detached", "it"))
    assert (
        not partial["abstained"] and len(partial["evidence_gaps"]) == len(partial["findings"]) == 1
    )


def test_short_ids_never_replace_letters_inside_natural_words_or_untrusted_prose():
    row = example(case(9, "train", 0), "all_missing", "en")
    changed = deepcopy(row)
    user = json.loads(changed["messages"][1]["content"])
    user["input"]["artifact_bundle"]["scenario"]["task"] += " Read a database record."
    changed["messages"][1]["content"] = json.dumps(user)
    assert semantic_key(changed) != semantic_key(row)
    adversarial = example(case(9, "train", 0), "all_missing", "en", prose="instruction")
    assert semantic_key(adversarial) != semantic_key(row)
    assert len(response(adversarial)["findings"]) == 3
    assert response(adversarial)["evidence_gaps"] == []


def test_invalid_partition_and_surface_variants_fail_closed():
    with pytest.raises(ValueError):
        case(0, "test", 0)
    with pytest.raises(ValueError):
        case(0, "train", 8)
    with pytest.raises(ValueError):
        render(case(0, "train", 0), "all_present", "en", "short", "`", "native", "neutral")


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "environments/training"))
    module = importlib.import_module("prepare_robust_evaluator")

    def tiny(*, seed, split):
        for style, locale in itertools.product(ID_STYLES, ("en", "it")):
            yield example(case(seed, split, 0), "all_missing", locale, style)

    monkeypatch.setattr(module, "iter_curriculum", tiny)
    return module


@pytest.fixture
def retention(operator, tmp_path):
    from orchestwin.training.balanced_scope_curriculum import CONTRASTS, balanced_case
    from orchestwin.training.balanced_scope_curriculum import example as old_example

    source = tmp_path / "v5"
    source.mkdir()
    files = {}
    for split in ("train", "validation"):
        rows = [
            old_example(balanced_case(76, split, 0), CONTRASTS[0], locale)
            for locale in ("en", "it")
        ]
        path = source / f"{split}.jsonl"
        path.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in rows))
        files[path.name] = dict(rows=len(rows), sha256=operator.digest(path))
    operator.save(
        source / "manifest.json",
        dict(curriculum_id="grounded-evaluator-balanced-scope-v5", files=files),
    )
    return source


def test_export_preserves_all_old_bytes_and_invariant_siblings(operator, retention, tmp_path):
    output = tmp_path / "v6"
    report = operator.export(output, retention=retention)
    assert report["files"]["train.jsonl"]["rows"] == 8
    assert report["files"]["validation.jsonl"]["rows"] == 6
    assert report["statistics"]["train"]["counts"]["normalized_siblings_retained"] == 4
    assert (output / "train.jsonl").read_bytes().endswith((retention / "train.jsonl").read_bytes())
    assert not (output / "test.jsonl").exists()
    with (retention / "train.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="source changed"):
        operator.export(tmp_path / "changed", retention=retention)
    assert not (tmp_path / "changed").exists()


def test_protected_known_prompt_rejects_renaming_and_equivalent_html(operator, retention, tmp_path):
    row = example(case(2026091706, "train", 0), "all_missing", "en", "opaque", "'", "xml")
    known = tmp_path / "known.json"
    operator.save(known, [dict(messages=row["messages"][:2])])
    with pytest.raises(ValueError, match="overlaps protected"):
        operator.export(tmp_path / "overlap", retention=retention, known_inputs=(known,))
    assert not (tmp_path / "overlap/manifest.json").exists()


def test_retained_data_cannot_copy_new_training(operator, retention, tmp_path):
    row = example(case(2026091706, "train", 0), "all_missing", "en")
    row["group_id"] = "different-group-same-input"
    path = retention / "train.jsonl"
    path.write_text(json.dumps(row) + "\n")
    manifest = json.loads((retention / "manifest.json").read_bytes())
    manifest["files"]["train.jsonl"] = dict(rows=1, sha256=operator.digest(path))
    operator.save(retention / "manifest.json", manifest)
    with pytest.raises(ValueError, match="duplicates retained"):
        operator.export(tmp_path / "overlap", retention=retention)


def test_retained_group_identity_cannot_cross_into_new_validation(operator, retention, tmp_path):
    path = retention / "train.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    for row in rows:
        row["group_id"] = case(2026091706, "validation", 0).group_id
    path.write_bytes(b"".join((json.dumps(row) + "\n").encode() for row in rows))
    manifest = json.loads((retention / "manifest.json").read_bytes())
    manifest["files"]["train.jsonl"]["sha256"] = operator.digest(path)
    operator.save(retention / "manifest.json", manifest)
    with pytest.raises(ValueError, match="sibling group crosses"):
        operator.export(tmp_path / "overlap", retention=retention)
    assert not (tmp_path / "overlap/manifest.json").exists()


def test_v6_audit_preserves_training_cache_and_never_opens_reserved_test(
    operator, retention, tmp_path, monkeypatch
):
    audit = importlib.import_module("audit_scoped_evaluator")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.name != "test.jsonl", "reserved test opened"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    data = tmp_path / "v6"
    manifest = operator.export(data, retention=retention)

    class Tokenizer:
        eos_token_id = 9

        def apply_chat_template(self, messages, **kwargs):
            return [1, 2] if len(messages) == 2 else [1, 2, 3, 9]

    report = audit.audit(data, tmp_path / "preflight", Tokenizer(), curriculum_id=CURRICULUM_ID)
    assert report["cache"]["rows"] == manifest["files"]["train.jsonl"]["rows"]
    assert report["cache"]["curriculum_id"] == CURRICULUM_ID
    with pytest.raises(ValueError, match="development corpus"):
        audit.audit(data, tmp_path / "wrong-version", None)
    manifest["files"]["test.jsonl"] = manifest["files"]["validation.jsonl"]
    operator.save(data / "manifest.json", manifest)
    with pytest.raises(ValueError, match="development corpus"):
        audit.audit(data, tmp_path / "forbidden", None, curriculum_id=CURRICULUM_ID)
