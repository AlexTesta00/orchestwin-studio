"""No model loading: check candidate data integrity and honest held-out scoring."""

import importlib.util
import json
from pathlib import Path

import pytest

from orchestwin.training.grounded_evaluator_curriculum import example

ROOT = Path(__file__).resolve().parents[4]


def operator(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "environments/training" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_is_new_and_data_hashes_are_checked(tmp_path):
    prepare = operator("prepare_evaluator_calibration")
    run = operator("run_evaluator_calibration")
    folder = tmp_path / "candidate"
    report = prepare.export(folder, variants=8)
    assert report["training_executed"] is False
    assert report["human_label_review_performed"] is False
    assert not tuple(folder.glob("*.md"))
    manifest, rows = run.read_data(folder)
    assert len(rows["train"]) == manifest["files"]["train.jsonl"]["rows"]
    with pytest.raises(FileExistsError):
        prepare.export(folder, variants=8)
    (folder / "train.jsonl").write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="data changed"):
        run.read_data(folder)


@pytest.mark.parametrize("state", ["MISSING", "PRESENT", "INSUFFICIENT"])
def test_scoring_accepts_the_oracle_and_rejects_the_wrong_judgement(state):
    run = operator("run_evaluator_calibration")
    row = example(seed=7, family="input_label", variant=7, locale="it", state=state)
    expected = row["messages"][-1]["content"]
    assert run.assess(expected, row)["passed"] is True
    wrong = json.loads(expected)
    wrong["abstained"] = not wrong["abstained"]
    assert run.assess(json.dumps(wrong), row)["passed"] is False


def test_scoring_rejects_invented_artifact_or_citation():
    run = operator("run_evaluator_calibration")
    row = example(seed=7, family="heading", variant=7, locale="en", state="MISSING")
    value = json.loads(row["messages"][-1]["content"])
    value["findings"][0]["evidence_refs"] = ["invented"]
    assert run.assess(json.dumps(value), row)["passed"] is False
    assert run.assess("not JSON", row)["passed"] is False


def test_tokenization_never_truncates_or_trains_on_prompt():
    run = operator("run_evaluator_calibration")
    row = {"messages": [{}, {}, {}]}

    class Tokenizer:
        eos_token_id = 9

        def apply_chat_template(self, messages, **_):
            return [1, 2] if len(messages) == 2 else [1, 2, 3, 9]

    assert run.encode(Tokenizer(), row) == {
        "input_ids": [1, 2, 3, 9],
        "completion_mask": [0, 0, 1, 1],
    }
    run.MAX_LENGTH = 3
    with pytest.raises(ValueError, match="truncation"):
        run.encode(Tokenizer(), row)
