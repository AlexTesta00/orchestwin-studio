"""Diagnostic interventions must isolate factors and preserve credential boundaries."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "source_diagnosis", ROOT / "environments/training/diagnose_source_generation.py"
)
diagnosis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnosis
SPEC.loader.exec_module(diagnosis)


@pytest.mark.parametrize("target", diagnosis.CASES)
def test_ablation_changes_only_declared_factor_and_never_mutates_baseline(target):
    context = {
        "implementation_contract": {
            "content": {"architecture": {"selected": "original"}, "requirements": ["keep"]}
        },
        "completed_files": [{"content": "literal\\n plus actual\nline"}],
    }
    original = {
        "messages": [
            {"role": "system", "content": "original system instruction"},
            {"role": "user", "content": json.dumps({"context": context})},
        ],
        "max_tokens": 1100,
        "temperature": 0.6,
        "response_format": {"schema": {"maxItems": 60}},
    }
    before = copy.deepcopy(original)
    assert diagnosis.variant(original, target, "BASELINE") == original
    budget = diagnosis.variant(original, target, "OUTPUT_BUDGET_2200")
    assert budget.pop("max_tokens") == 2200
    assert budget == {k: v for k, v in original.items() if k != "max_tokens"}
    focused = diagnosis.variant(original, target, "FOCUSED_INSTRUCTION")
    assert focused["messages"][0]["content"] != original["messages"][0]["content"]
    focused["messages"][0] = original["messages"][0]
    assert focused == original
    compact = diagnosis.variant(original, target, "OMIT_ARCHITECTURE")
    value = json.loads(compact["messages"][1]["content"])["context"]
    assert "architecture" not in value["implementation_contract"]["content"]
    value["implementation_contract"]["content"]["architecture"] = {"selected": "original"}
    assert value == context
    compact["messages"][1] = original["messages"][1]
    assert compact == original
    assert original == before


def test_rejects_unknown_intervention():
    with pytest.raises(ValueError, match="unknown intervention"):
        diagnosis.variant({}, "WEB_STATIC", "UNDECLARED_REPAIR")


def test_historical_diagnosis_keeps_v1_limits_and_rejects_live_text_protocol():
    assert diagnosis.HistoricalSourceLines.model_validate({"lines": ["old file"]}).lines == [
        "old file"
    ]
    for payload in ({"lines": ["line"] * 61}, {"content": "new file"}):
        with pytest.raises(ValueError):
            diagnosis.HistoricalSourceLines.model_validate(payload)


def test_transport_never_returns_response_that_echoes_secret(monkeypatch):
    token = "secret-diagnostic-credential-1234567890"
    closed = []

    class Connection:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer " + token

        def getresponse(self):
            return SimpleNamespace(status=200, read=lambda _limit: token.encode())

        def close(self):
            closed.append(True)

    monkeypatch.setattr(diagnosis.http.client, "HTTPConnection", Connection)
    config = SimpleNamespace(base_url="http://127.0.0.1:45678")
    with pytest.raises(ValueError, match="response retention rejected") as error:
        diagnosis.send_http(config, token, "GET", "/health")
    assert token not in str(error.value)
    assert closed == [True]
