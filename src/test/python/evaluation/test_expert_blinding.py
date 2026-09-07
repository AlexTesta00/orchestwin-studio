"""Tests for deterministic and identity-separated expert A/B blinding."""

from __future__ import annotations

import json

from orchestwin.evaluation.expert_blinding import (
    ModelVariant,
    create_blinded_pair,
    sanitize_for_blind_review,
)


def test_public_pair_removes_model_identity_metadata_and_keeps_private_key_separate() -> None:
    pair, key = create_blinded_pair(
        pair_id="PAIR-001",
        case_id="held-out-001",
        base_output_id="OUT-101",
        base_payload={
            "model_name": "hidden identity",
            "summary": "The primary action is difficult to discover.",
            "nested": {"checkpoint": "private", "severity": "MAJOR"},
        },
        adapter_output_id="OUT-102",
        adapter_payload={
            "adapter_id": "hidden identity",
            "summary": "The primary action lacks a visible label.",
            "nested": {"variant": "private", "severity": "MAJOR"},
        },
        randomization_seed="s12-frozen-seed",
    )

    public_json = json.dumps(pair.to_snapshot(), sort_keys=True).lower()
    assert "model_name" not in public_json
    assert "adapter_id" not in public_json
    assert "checkpoint" not in public_json
    assert '"variant"' not in public_json
    assert {key.candidate_a_variant, key.candidate_b_variant} == {
        ModelVariant.BASE,
        ModelVariant.ADAPTER,
    }
    assert key.pair_id == pair.pair_id


def test_blinding_order_is_reproducible_for_the_same_seed_and_pair_id() -> None:
    kwargs = {
        "pair_id": "PAIR-002",
        "case_id": "held-out-002",
        "base_output_id": "OUT-201",
        "base_payload": {"summary": "Candidate one"},
        "adapter_output_id": "OUT-202",
        "adapter_payload": {"summary": "Candidate two"},
        "randomization_seed": "s12-frozen-seed",
    }

    first = create_blinded_pair(**kwargs)
    second = create_blinded_pair(**kwargs)

    assert first == second


def test_sanitizer_recursively_removes_identity_keys() -> None:
    assert sanitize_for_blind_review(
        {
            "model": "hidden",
            "findings": [
                {"source_model": "hidden", "summary": "Keep this"},
            ],
        }
    ) == {"findings": [{"summary": "Keep this"}]}
