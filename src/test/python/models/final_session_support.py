"""Synthetic session documents for isolated final-evaluator tests; no real token or model."""

from __future__ import annotations

import json
from pathlib import Path

from orchestwin.models.final_evaluator_session import (
    ADAPTER_SHA256,
    IDENTITY_FIELDS,
    MODEL_NAME,
    REVISION,
    SERVING_BASE_COMMIT,
    content_hash,
    load_final_session,
)


def record(path: Path, value):
    data = {**value, "content_hash": content_hash(value)}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def make_session(root: Path, *, port=54321):
    root.mkdir(parents=True, exist_ok=True)
    config = record(
        root / "configuration.json",
        {
            "platform_commit": SERVING_BASE_COMMIT,
            "model_name": MODEL_NAME,
            "adapter_sha256": ADAPTER_SHA256,
        },
    )
    identity = {**IDENTITY_FIELDS, "configuration_sha256": config["content_hash"]}
    ready = {
        "status": "FINAL_EVALUATOR_SERVING_READY",
        "platform_commit": SERVING_BASE_COMMIT,
        "host": "127.0.0.1",
        "port": port,
        "credential_file": "access-token.secret",
        "model_name": MODEL_NAME,
        "model_identity": identity,
        "authenticated_health_verified": True,
        "training_executed": False,
        "formal_run_started": False,
    }
    record(root / "ready.json", ready)
    (root / "access-token.secret").write_text("b" * 64, encoding="ascii")
    return load_final_session(root / "ready.json")


def health(session):
    return {
        "status": "FINAL_EVALUATOR_READY",
        "model_name": MODEL_NAME,
        "model_identity": session.identity,
        "completed_generation_count": 2,
        "fallback_policy": "FAIL_CLOSED_NO_BASE_FALLBACK",
        "training_executed": False,
        "benchmark_reexecuted": False,
        "load_observation": {
            "base_revision_observed": REVISION,
            "active_adapters": ["default"],
            "load_in_4bit_observed": True,
            "trainable_parameters": 0,
        },
    }
