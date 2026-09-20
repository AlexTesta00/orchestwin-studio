"""Probe safety checks; synthetic values here are not model-quality evidence."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "probe_web_proposer", ROOT / "environments/training/probe_web_proposer.py"
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.mark.parametrize(
    "case_file",
    ("proposer-postprompt-cases-20260919.json", "proposer-cross-project-cases-20260920.json"),
)
def test_independent_oracle_is_never_sent_as_model_context(case_file):
    cases = probe.read_cases(ROOT / "experiments/model-proposals" / case_file)
    for case in cases:
        context = probe.context(case)
        text = json.dumps(context)
        assert case["oracle"] not in text
        assert "independent persistent records" not in text
        assert "independent exact allocation" not in text
        assert context["design"]["content"]["prototype"] == case["prototype"]


def test_evidence_writer_refuses_to_overwrite_original_output(tmp_path):
    target = tmp_path / "evidence.json"
    probe.save(target, {"observed": 1})
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        probe.save(target, {"observed": 2})
    assert target.read_bytes() == before


def test_expired_budget_never_starts_model_transport(monkeypatch):
    async def forbidden(**_):
        raise AssertionError("No request may start after its budget expires")

    monkeypatch.setattr(probe.DirectProposalTransport, "post_json", forbidden)
    transport = probe.DeadlineTransport(0)
    with pytest.raises(probe.ProposalGenerationError, match="BENCHMARK_TIME_BUDGET_EXHAUSTED"):
        asyncio.run(transport.post_json(timeout_seconds=60))


def test_case_ids_cannot_escape_output_directory(tmp_path):
    cases = [{"id": "../escape"}]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    with pytest.raises(ValueError, match="portable"):
        probe.read_cases(path)
