"""Counterfactual loss focuses actual output decisions without leaking held-out inputs."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from orchestwin.training.decision_supervision import (
    balance_decision_supervision,
    configure_decision_loss,
)


def trainer():
    return SimpleNamespace(
        args=SimpleNamespace(
            per_device_train_batch_size=1, world_size=1, gradient_accumulation_steps=4
        ),
        compute_loss_func=None,
        model_accepts_loss_kwargs=True,
    )


def test_decision_supervision_uses_per_example_mean_with_gradient_accumulation():
    configured = trainer()
    report = configure_decision_loss(configured)
    assert configured.model_accepts_loss_kwargs is False
    assert report["model_accepts_loss_kwargs_before"] is True
    assert report["gradient_accumulation_steps"] == 4


@pytest.mark.parametrize("invalid", ["batch", "processes", "custom_loss"])
def test_decision_loss_rejects_unvalidated_normalization_modes(invalid):
    configured = trainer()
    if invalid == "batch":
        configured.args.per_device_train_batch_size = 2
    elif invalid == "processes":
        configured.args.world_size = 2
    else:
        configured.compute_loss_func = object()
    with pytest.raises(ValueError, match="one example"):
        configure_decision_loss(configured)
    assert configured.model_accepts_loss_kwargs is True


def corpus():
    rows, encoded = [], []
    # Token 10 is the abstention decision; 20 is the findings decision.
    completions = {
        "MISSING": [10, 0, 20, 1, 30, 99],
        "PRESENT": [10, 0, 20, 0, 99],
        "INSUFFICIENT": [10, 1, 30, 99],
    }
    for group in ("a", "b"):
        for locale in ("en", "it"):
            for state, completion in completions.items():
                rows.append(
                    {
                        "split": "train",
                        "family": "example",
                        "group_id": group,
                        "locale": locale,
                        "judgement": state,
                    }
                )
                prompt = [80] * (len(rows) + 1)
                encoded.append(
                    {
                        "input_ids": prompt + completion,
                        "completion_mask": [0] * len(prompt) + [1] * len(completion),
                    }
                )
    return rows, encoded


def test_only_counterfactual_decisions_change_loss_and_all_tokens_stay_exact():
    rows, encoded = corpus()
    before = deepcopy(encoded)
    result, report = balance_decision_supervision(rows, encoded)
    assert encoded == before
    assert report["decision_rows"] == report["full_completion_rows"] == 6
    for row, original, changed in zip(rows, encoded, result, strict=True):
        assert changed["input_ids"] == original["input_ids"]
        start = original["completion_mask"].index(1)
        assert not any(changed["completion_mask"][:start])
        if row["group_id"] == "b":
            assert changed == original
        else:
            supervised = [i - start for i, value in enumerate(changed["completion_mask"]) if value]
            assert supervised == ([1, 2] if row["judgement"] == "INSUFFICIENT" else [1, 2, 3, 4])
    result[0]["input_ids"][0] = 7
    assert encoded == before


@pytest.mark.parametrize("split", ["validation", "test"])
def test_held_out_rows_cannot_be_used_to_derive_decision_supervision(split):
    rows, encoded = corpus()
    rows[0]["split"] = split
    with pytest.raises(ValueError, match="training rows only"):
        balance_decision_supervision(rows, encoded)


def test_missing_and_duplicate_siblings_are_rejected():
    rows, encoded = corpus()
    with pytest.raises(ValueError, match="all three"):
        balance_decision_supervision(rows[1:], encoded[1:])
    rows[0]["judgement"] = rows[1]["judgement"]
    with pytest.raises(ValueError, match="duplicate"):
        balance_decision_supervision(rows, encoded)


def test_previously_masked_or_identical_counterfactual_targets_are_rejected():
    rows, encoded = corpus()
    encoded[0]["completion_mask"][-1] = 0
    with pytest.raises(ValueError, match="whole completion"):
        balance_decision_supervision(rows, encoded)
    rows, encoded = corpus()
    encoded[0] = deepcopy(encoded[1])
    with pytest.raises(ValueError, match="divergent token"):
        balance_decision_supervision(rows, encoded)
