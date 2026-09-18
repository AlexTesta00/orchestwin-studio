"""Interactive evaluator selection never substitutes base inference for the adapter."""

import json
from dataclasses import replace

import pytest

from orchestwin.evaluation.local_runtime import build_local_evaluator_runtime
from orchestwin.models.real_runtime import build_real_model_runtime
from src.test.python.models.test_model_proposals import make_generator


def configuration(tmp_path):
    generator, _ = make_generator(tmp_path, {})
    base = generator.configuration
    base.token_file.write_text("local-test-token-" + "x" * 40, encoding="ascii")
    identity = replace(
        base.identity,
        adapter_id="local-trained-candidate",
        adapter_sha256="d" * 64,
        runtime_id="evaluator",
        configuration_sha256="e" * 64,
    )
    adapted = base.model_copy(
        update={"identity": identity, "temperature": 0.0, "base_url": "http://127.0.0.1:19452"}
    )
    path = tmp_path / "evaluator.json"
    path.write_text(adapted.model_dump_json(), encoding="utf-8")
    return path, base


def test_local_adapter_can_replace_evaluator_without_changing_proposal_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, base = configuration(tmp_path)
    proposal = tmp_path / "proposal.json"
    proposal.write_text(base.model_dump_json(), encoding="utf-8")
    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {"proposal_config_file": str(proposal), "final_evaluator_config_file": str(path)}
        )
    )
    runtime = build_real_model_runtime(manifest)
    assert runtime.proposal_configuration.identity.adapter_id is None
    assert runtime.final_evaluator.identity["adapter_id"] == "local-trained-candidate"
    assert runtime.final_evaluator.generation_lock is runtime.team.generator.port._lock
    assert runtime.final_evaluator.create_evaluator() is not None
    assert "local-test-token" not in repr(runtime.final_evaluator)


@pytest.mark.parametrize("change", ["base", "sampled", "empty_token", "drift"])
def test_local_evaluator_fails_closed(tmp_path, change):
    path, base = configuration(tmp_path)
    runtime = build_local_evaluator_runtime(path)
    value = json.loads(path.read_text())
    if change == "base":
        value["identity"] = base.identity.to_snapshot()
    elif change == "sampled":
        value["temperature"] = 0.6
    elif change == "empty_token":
        base.token_file.write_text("")
    else:
        value["model_name"] = "changed"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        if change == "drift":
            runtime.create_evaluator()
        else:
            build_local_evaluator_runtime(path)
