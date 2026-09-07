"""Deterministic base-versus-adapter blinding with a separately stored identity key."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_IDENTITY_KEYS: Final = frozenset(
    {
        "adapter",
        "adapter_id",
        "adapter_name",
        "checkpoint",
        "checkpoint_path",
        "model",
        "model_id",
        "model_name",
        "model_variant",
        "source_model",
        "variant",
    }
)


class ModelVariant(StrEnum):
    """Private model identities never written into the public expert package."""

    BASE = "BASE"
    ADAPTER = "ADAPTER"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def sanitize_for_blind_review(payload: object) -> object:
    """Remove known model-identity metadata while preserving reviewable evaluator content."""
    if isinstance(payload, dict):
        return {
            key: sanitize_for_blind_review(value)
            for key, value in payload.items()
            if key.lower() not in _IDENTITY_KEYS
        }
    if isinstance(payload, list):
        return [sanitize_for_blind_review(value) for value in payload]
    if isinstance(payload, tuple):
        return [sanitize_for_blind_review(value) for value in payload]
    return payload


@dataclass(frozen=True, slots=True)
class BlindedCandidate:
    """One public candidate carrying no model identity metadata."""

    alias: str
    output_id: str
    payload: object

    def to_snapshot(self) -> dict[str, object]:
        return {
            "alias": self.alias,
            "output_id": self.output_id,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class BlindedPair:
    """Public A/B pair supplied to expert reviewers."""

    pair_id: str
    case_id: str
    candidate_a: BlindedCandidate
    candidate_b: BlindedCandidate
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "pair_id": self.pair_id,
            "case_id": self.case_id,
            "candidate_a": self.candidate_a.to_snapshot(),
            "candidate_b": self.candidate_b.to_snapshot(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


@dataclass(frozen=True, slots=True)
class BlindingKey:
    """Private identity mapping that must be stored outside the expert package."""

    pair_id: str
    candidate_a_variant: ModelVariant
    candidate_b_variant: ModelVariant
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "pair_id": self.pair_id,
            "candidate_a_variant": self.candidate_a_variant.value,
            "candidate_b_variant": self.candidate_b_variant.value,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_blinded_pair(
    *,
    pair_id: str,
    case_id: str,
    base_output_id: str,
    base_payload: object,
    adapter_output_id: str,
    adapter_payload: object,
    randomization_seed: str,
) -> tuple[BlindedPair, BlindingKey]:
    """Create a stable A/B order while keeping the decoding key physically separable."""
    base_candidate = BlindedCandidate(
        alias="A",
        output_id=base_output_id,
        payload=sanitize_for_blind_review(base_payload),
    )
    adapter_candidate = BlindedCandidate(
        alias="B",
        output_id=adapter_output_id,
        payload=sanitize_for_blind_review(adapter_payload),
    )
    digest = hashlib.sha256(f"{randomization_seed}:{pair_id}".encode()).digest()
    if digest[0] % 2 == 0:
        candidate_a, candidate_b = base_candidate, adapter_candidate
        variant_a, variant_b = ModelVariant.BASE, ModelVariant.ADAPTER
    else:
        candidate_a = BlindedCandidate("A", adapter_candidate.output_id, adapter_candidate.payload)
        candidate_b = BlindedCandidate("B", base_candidate.output_id, base_candidate.payload)
        variant_a, variant_b = ModelVariant.ADAPTER, ModelVariant.BASE
    pair_snapshot = {
        "pair_id": pair_id,
        "case_id": case_id,
        "candidate_a": candidate_a.to_snapshot(),
        "candidate_b": candidate_b.to_snapshot(),
    }
    key_snapshot = {
        "pair_id": pair_id,
        "candidate_a_variant": variant_a.value,
        "candidate_b_variant": variant_b.value,
    }
    return (
        BlindedPair(
            pair_id=pair_id,
            case_id=case_id,
            candidate_a=candidate_a,
            candidate_b=candidate_b,
            content_hash=_hash(pair_snapshot),
        ),
        BlindingKey(
            pair_id=pair_id,
            candidate_a_variant=variant_a,
            candidate_b_variant=variant_b,
            content_hash=_hash(key_snapshot),
        ),
    )
