"""Protect the evaluation split, complete targets and replayable cache integrity."""

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "environments/training"))
    return importlib.import_module("proposer_training_data"), importlib.import_module(
        "complete_training_data"
    )


class Tokenizer:
    eos_token_id = 9

    def apply_chat_template(self, messages, **kwargs):
        return [1, 2] if len(messages) == 2 else [1, 2, 3, 9]


def source(tmp_path, module, *, family="rectangle-area", split="train", duplicate=False):
    row = dict(
        group_id=family,
        semantic_family=family,
        split=split,
        locale="en",
        step="app.js",
        provenance="SYNTHETIC_ENGINEER_AUTHORED",
        messages=[dict(role=role, content="example") for role in ("system", "user", "assistant")],
    )
    path = tmp_path / "data"
    path.mkdir()
    (path / "train.jsonl").write_text((json.dumps(row) + "\n") * (2 if duplicate else 1))
    module.save(
        path / "manifest.json",
        dict(
            curriculum_id=module.CURRICULUM,
            excluded_semantic_families=sorted(module.EXCLUDED_FAMILIES),
            files={"train.jsonl": dict(sha256=module.digest(path / "train.jsonl"))},
        ),
    )
    return path


def test_cache_requires_no_validation_and_masks_prompt_only(modules, tmp_path):
    module, shared = modules
    data = source(tmp_path, module)
    output = tmp_path / "cache"
    report = module.prepare_cache(data, output, module.digest(data / "manifest.json"), Tokenizer())
    assert report["rows"] == 1 and report["validation_read"] is False
    dataset = shared.TokenDataset(output, max_sequence=module.MAX_SEQUENCE)
    try:
        assert dataset[0]["labels"] == [-100, -100, 3, 9]
    finally:
        dataset.close()
    with pytest.raises(ValueError, match="context mismatch"):
        shared.TokenDataset(output)  # evaluator defaults cannot accept this cache silently
    with (output / "train.sqlite").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        shared.TokenDataset(output, max_sequence=module.MAX_SEQUENCE)


@pytest.mark.parametrize("dataset_version", (None, 1, 2))
def test_cache_reads_legacy_and_versioned_manifests_without_rewriting_them(
    modules, tmp_path, dataset_version
):
    module, _ = modules
    data = source(tmp_path, module)
    manifest_path = data / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if dataset_version is not None:
        manifest["dataset_version"] = dataset_version
        module.save(manifest_path, manifest)
    before = manifest_path.read_bytes()
    # Validation need not exist: this cache operation remains strictly train-only.
    report = module.prepare_cache(
        data, tmp_path / "cache", module.digest(manifest_path), Tokenizer()
    )
    assert report["rows"] == 1
    assert report["validation_read"] is False
    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize(
    "options", [dict(family="guest-list"), dict(split="validation"), dict(duplicate=True)]
)
def test_reject_leakage_and_duplicates(modules, tmp_path, options):
    module, _ = modules
    data = source(tmp_path, module, **options)
    with pytest.raises(ValueError, match=r"excluded|held-out|duplicate"):
        module.prepare_cache(
            data, tmp_path / "cache", module.digest(data / "manifest.json"), Tokenizer()
        )


@pytest.mark.parametrize("failure", ["boundary", "eos", "oversize"])
def test_never_truncate_or_train_misaligned_response(modules, failure):
    module, _ = modules

    class InvalidTokenizer(Tokenizer):
        def apply_chat_template(self, messages, **kwargs):
            if len(messages) == 2:
                return [1, 2]
            return {
                "boundary": [1, 3, 9],
                "eos": [1, 2, 3],
                "oversize": [1, 2] + [3] * module.MAX_SEQUENCE + [9],
            }[failure]

    messages = [dict(role=role, content="x") for role in ("system", "user", "assistant")]
    with pytest.raises(ValueError):
        module.encode(InvalidTokenizer(), messages)
