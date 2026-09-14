"""Candidate requests and adapter bytes fail closed before GPU work."""

import hashlib
import json
from uuid import uuid4

import pytest

from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    create_structured_generation_request,
    create_structured_json_schema,
)
from src.test.python.training.test_evaluator_calibration_operator import operator


def request(identity, **overrides):
    arguments = dict(
        request_id=uuid4(),
        task_id="user-twin-evaluation-v1",
        expected_identity=identity,
        output_schema=create_structured_json_schema(
            schema_id="test",
            version_number=1,
            schema_payload={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        system_instruction="Evaluate the supplied test artifact.",
        input_payload={},
        allowed_evidence_refs=(),
        prompt_version_ref="test",
        temperature=0.0,
        max_output_tokens=900,
        timeout_seconds=120,
    )
    return create_structured_generation_request(**(arguments | overrides))


@pytest.mark.parametrize(
    "change",
    [{"temperature": 0.5}, {"max_output_tokens": 2049}, {"task_id": "proposal-web-source-v1"}],
)
def test_worker_refuses_other_tasks_or_decoding_conditions(change):
    worker = operator("evaluator_candidate_worker")
    identity = ModelRuntimeIdentity(
        "test", "runtime", worker.MODEL, worker.REVISION, worker.REVISION, "a" * 64
    )
    valid = request(identity)
    assert worker.hydrate(valid.to_snapshot(), identity) == valid
    with pytest.raises(ValueError):
        worker.hydrate(request(identity, **change).to_snapshot(), identity)
    tampered = valid.to_snapshot() | {"input_payload_json": '{"changed":true}'}
    with pytest.raises(ValueError, match="content hash"):
        worker.hydrate(tampered, identity)


def test_adapter_hashes_and_base_are_verified_without_loading_a_model(tmp_path):
    worker = operator("evaluator_candidate_worker")
    weights = b"synthetic test bytes, never loaded"
    config = json.dumps({"base_model_name_or_path": worker.MODEL, "peft_type": "LORA"}).encode()
    (tmp_path / "adapter_model.safetensors").write_bytes(weights)
    (tmp_path / "adapter_config.json").write_bytes(config)
    hashes = [hashlib.sha256(raw).hexdigest() for raw in (weights, config)]
    assert worker.verify_adapter(tmp_path, *hashes)["adapter_model.safetensors"] == hashes[0]
    (tmp_path / "adapter_model.safetensors").write_bytes(weights + b"changed")
    with pytest.raises(ValueError, match="bytes differ"):
        worker.verify_adapter(tmp_path, *hashes)
