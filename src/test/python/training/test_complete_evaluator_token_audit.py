"""Context, EOS and timing provenance checks without loading a tokenizer or model."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def audit(monkeypatch):
    directory = Path(__file__).resolve().parents[4] / "environments/training"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location(
        "audit_complete_evaluator", directory / "audit_complete_evaluator.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Tokenizer:
    eos_token_id = 9

    def __init__(self, prefix, complete):
        self.prefix, self.complete = prefix, complete

    def apply_chat_template(self, messages, **options):
        ids = self.prefix if len(messages) == 2 else self.complete
        # Current Transformers defaults to a mapping; request the token IDs explicitly.
        return (
            ids
            if options.get("return_dict") is False
            else {"input_ids": ids, "attention_mask": [1] * len(ids)}
        )


MESSAGES = [dict(role=role, content="example") for role in ("system", "user", "assistant")]


def test_exact_inference_prefix_and_complete_target(audit):
    assert audit.check_tokens(
        Tokenizer([1, 2], [1, 2, 3, 9]), MESSAGES, max_sequence=8, output_reserve=4
    ) == (2, 2)


@pytest.mark.parametrize(
    "prefix,complete,sequence,reserve,reason",
    [
        ([1, 2], [1, 3, 9], 8, 4, "boundary"),
        ([1, 2], [1, 2, 3, 4], 8, 4, "EOS"),
        ([1, 2], [1, 2, 3, 9], 5, 4, "context"),
        ([1, 2], [1, 2, 3, 4, 5, 9], 8, 3, "output budget"),
    ],
)
def test_incomplete_or_truncated_training_examples_are_rejected(
    audit, prefix, complete, sequence, reserve, reason
):
    with pytest.raises(ValueError, match=reason):
        audit.check_tokens(
            Tokenizer(prefix, complete), MESSAGES, max_sequence=sequence, output_reserve=reserve
        )


def test_estimate_preserves_uncertain_recorded_times_and_excludes_validation(audit):
    result = audit.estimate_hours(
        dict(rows=12, total_tokens=2000),
        dict(rows=6, total_tokens=1000),
        dict(seconds=3600, metrics=dict(train_runtime=4000)),
    )
    assert result["nominal_one_epoch_hours"] == [2, 8000 / 3600]
    assert not result["includes_validation_or_checkpoint_overhead"]
    assert not result["measured_new_training_throughput"]
