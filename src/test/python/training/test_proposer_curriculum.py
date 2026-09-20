"""Reference admission, curriculum isolation and real prompt-capture boundaries."""

import importlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.source_design_contract import validate_prototype_html

TRAINING = Path(__file__).resolve().parents[4] / "environments" / "training"
sys.path.insert(0, str(TRAINING))
curriculum = importlib.import_module("proposer_curriculum")
prepare = importlib.import_module("proposer_prepare")


def test_semantic_split_has_no_translation_leak_or_reserved_evaluation_families():
    families = curriculum.all_families()
    assert Counter(family.split for family in families) == {"train": 30, "validation": 8}
    assert len({family.name for family in families}) == len(families)
    assert set(curriculum.EXCLUDED_FAMILIES) == {
        "guest-list",
        "expense-split",
        "expense-splitting",
        "sales-tax",
        "temperature",
    }
    assert not set(curriculum.EXCLUDED_FAMILIES) & {family.name for family in families}


@pytest.mark.parametrize("family", curriculum.all_families(), ids=lambda family: family.name)
@pytest.mark.parametrize("locale", ("en", "it"))
def test_reference_markup_preserves_approved_controls_and_separate_screens(family, locale):
    files, prototype = curriculum.source_bundle(family, locale)
    validate_prototype_html(files["index.html"], prototype)
    assert '<script src="app.js"></script>' in files["index.html"]
    assert "require('./app.js')" in files["app.test.cjs"]
    assert "assert.throws" in files["app.test.cjs"]
    assert "if (typeof document !== 'undefined')" in files["app.js"]
    with pytest.raises(ProposalGenerationError, match="SOURCE_DESIGN_STRUCTURE_MISMATCH"):
        validate_prototype_html(
            files["index.html"].replace('name="mode"', 'name="wrong"'), prototype
        )


@pytest.mark.parametrize("family", [curriculum.NUMERIC[0], curriculum.STATEFUL[0]])
def test_capture_uses_production_messages_without_inference_or_fake_provider_results(family):
    rows, files, _ = prepare.capture_rows(family, "it")
    assert [row["step"] for row in rows] == ["manifest", "app.js", "app.test.cjs", "index.html"]
    assert len({row["group_id"] for row in rows}) == 1
    for row in rows:
        assert row["provenance"] == "SYNTHETIC_ENGINEER_AUTHORED"
        assert row["provider_inference_performed"] is False
        assert [message["role"] for message in row["messages"]] == ["system", "user", "assistant"]
        visible = json.loads(row["messages"][1]["content"])
        assert "output_schema" in visible
        assert visible["context"]["generation_protocol"] == prepare.PROTOCOL
        assert visible["context"]["runtime_contract"] == {
            "javascript_mode": "CLASSIC_SCRIPT_COMMONJS_COMPATIBLE",
            "browser_loading": "classic script src=app.js",
            "node_exports": "guarded module.exports of top-level functions",
            "test_loading": "require('./app.js') with node:test and node:assert/strict",
            "forbidden_module_declarations": ["import", "export"],
        }
        if row["source_path"]:
            assert json.loads(row["messages"][2]["content"]) == {
                "content": files[row["source_path"]]
            }
            assert (
                visible["context"]["source_step"]["file"]["normalized_path"] == row["source_path"]
            )
            assert "ONLY file to write" in row["messages"][0]["content"]
    if isinstance(family, curriculum.StatefulFamily):
        manifest = json.loads(rows[0]["messages"][2]["content"])
        assert manifest["files"][0]["interface"] == (
            "createService(): object; readNumber(raw: string): number"
        )
        assert "apply(action: string" in manifest["acceptance_checks"][0]["public_interface"]


def test_references_are_not_published_when_isolated_verification_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "all_families", lambda: (curriculum.NUMERIC[0],))

    def reject(*args):
        raise RuntimeError("reference failed")

    monkeypatch.setattr(prepare, "docker_verify", reject)
    output = tmp_path / "candidate"
    with pytest.raises(RuntimeError, match="reference failed"):
        prepare.prepare(output)
    assert not (output / "train.jsonl").exists()
    assert not (output / "validation.jsonl").exists()
    assert not (output / "manifest.json").exists()


def test_isolated_verification_has_no_network_and_requires_each_bundle(tmp_path, monkeypatch):
    commands = []

    def run(command, **kwargs):
        from types import SimpleNamespace

        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")

    monkeypatch.setattr(prepare.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Every reference bundle"):
        prepare.docker_verify(tmp_path, ["rectangle-en"])
    command = commands[0]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--user") + 1] == "1000:1000"
    assert prepare.NODE_IMAGE in command


def test_dataset_revision_preserves_semantic_identity_and_default_compatibility(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(prepare, "all_families", lambda: (curriculum.NUMERIC[0],))
    monkeypatch.setattr(
        prepare,
        "docker_verify",
        lambda output, bundles: {"bundles": len(bundles), "all_passed": True},
    )
    first = prepare.prepare(tmp_path / "first")
    second = prepare.prepare(tmp_path / "second", dataset_version=2)
    assert first["dataset_version"] == 1
    assert second["dataset_version"] == 2
    assert first["curriculum_id"] == second["curriculum_id"] == curriculum.CURRICULUM_ID
    assert first["semantic_family_splits"] == second["semantic_family_splits"]
    before = (tmp_path / "first" / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare.prepare(tmp_path / "first", dataset_version=2)
    assert (tmp_path / "first" / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("version", (0, -1, True, "2"))
def test_invalid_dataset_revision_does_not_create_output(tmp_path, version):
    output = tmp_path / "candidate"
    with pytest.raises(ValueError, match="positive integer"):
        prepare.prepare(output, dataset_version=version)
    assert not output.exists()
