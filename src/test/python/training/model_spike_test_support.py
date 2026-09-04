"""Deterministic file-backed support for live model-spike evidence tests."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    create_captured_model_source_evidence,
    expected_candidate_source_roles,
    serialize_captured_model_source_evidence,
)
from orchestwin.training.model_spike_batch import execute_model_spike_batch
from orchestwin.training.model_spike_requests import materialize_model_spike_execution_plan

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MODEL_SPIKE_TEST_NOW = datetime(2026, 9, 4, 14, 30, tzinfo=UTC)


def create_model_spike_test_plan(tmp_path: Path):
    """Create a three-candidate plan backed by deterministic source evidence."""
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    evidence = []
    for candidate in matrix.candidates:
        item = create_captured_model_source_evidence(
            candidate=candidate,
            captured_files={
                path: f"{candidate.candidate_id}:{path}".encode()
                for path in expected_candidate_source_roles(candidate)
            },
            capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
            captured_at=MODEL_SPIKE_TEST_NOW,
            resolved_revision=candidate.revision,
        )
        evidence.append(
            (
                item,
                hashlib.sha256(serialize_captured_model_source_evidence(item)).hexdigest(),
            )
        )
    return materialize_model_spike_execution_plan(
        matrix=matrix,
        source_evidence=tuple(evidence),
        output_root=tmp_path / "inputs",
        package_lock_sha256="a" * 64,
        environment_sha256="b" * 64,
        created_at=MODEL_SPIKE_TEST_NOW,
    )


def write_fake_model_spike_runner(path: Path) -> Path:
    """Write a subprocess runner that emits hash-bound success evidence."""
    path.write_text(
        """\
import argparse
import hashlib
import json
import os
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument('--request', type=Path, required=True)
parser.add_argument('--result', type=Path, required=True)
args = parser.parse_args()
request = json.loads(args.request.read_text())
root = args.result.parent
(root / 'prompts').mkdir(parents=True, exist_ok=True)
(root / 'raw').mkdir(parents=True, exist_ok=True)
(root / 'structured').mkdir(parents=True, exist_ok=True)
prompt = root / 'prompts' / 'bench-en-001-r01.json'
raw = root / 'raw' / 'bench-en-001-r01.txt'
structured = root / 'structured' / 'bench-en-001-r01.json'
prompt.write_text('{}')
raw.write_text('{"ok":true}')
structured.write_text('{"ok":true}')
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
score = {
    'task_id': 'bench-en-001',
    'task_content_hash': '1' * 64,
    'language': 'en',
    'generation_status': 'SUCCEEDED',
    'schema_valid_rate': 1.0,
    'evidence_reference_precision': 1.0,
    'unsupported_claim_rate': 0.0,
    'abstention_accuracy': 1.0,
    'role_adherence': 1.0,
    'criterion_agreement': 1.0,
    'severity_agreement': 1.0,
    'context_reference_recall': 1.0,
    'latency_milliseconds': 10,
    'failure_code': None,
}
resource = {
    'measurement_id': '00000000-0000-4000-8000-000000000001',
    'candidate_id': request['candidate_id'],
    'task_id': 'bench-en-001',
    'repetition': 1,
    'status': 'SUCCEEDED',
    'latency_milliseconds': 10,
    'peak_gpu_memory_mb': 1000,
    'input_tokens': 100,
    'output_tokens': 20,
    'failure_summary': None,
    'evidence_reference': 'prompts/bench-en-001-r01.json',
    'observed_at': '2026-09-04T14:30:00+00:00',
}
task = {
    'task_id': 'bench-en-001',
    'task_content_hash': '1' * 64,
    'language': 'en',
    'category': 'SCHEMA_AND_PROVENANCE',
    'repetition': 1,
    'status': 'SUCCEEDED',
    'prompt_reference': 'prompts/bench-en-001-r01.json',
    'prompt_sha256': sha(prompt),
    'raw_output_reference': 'raw/bench-en-001-r01.txt',
    'raw_output_sha256': sha(raw),
    'structured_output_reference': 'structured/bench-en-001-r01.json',
    'structured_output_sha256': sha(structured),
    'finish_reason': 'STOP',
    'score': score,
    'resource_measurement': resource,
    'failure_kind': None,
    'failure_message': None,
}
task['content_hash'] = digest(task)
metrics = [
    {'metric_id': 'schema_valid_rate', 'value': 1.0, 'sample_count': 1},
    {'metric_id': 'unsupported_claim_rate', 'value': 0.0, 'sample_count': 1},
]
payload = {
    'schema_version': 1,
    'request_sha256': request['request_sha256'],
    'status': 'COMPLETED',
    'started_at': '2026-09-04T14:30:00+00:00',
    'completed_at': '2026-09-04T14:30:01+00:00',
    'duration_milliseconds': 1000,
    'candidate_id': request['candidate_id'],
    'candidate_matrix': {
        'matrix_sha256': '8ceb306ff2a6b6a04087897de15cf1a83e41af620163493af1663599a1ef8101',
        'matrix_content_hash': 'fe95f38476c85967d17c4cc542e5bd4fb8ad96c98965394597232e9f21a3c1ea',
        'family_id': 'test',
        'chat_template_control': {},
    },
    'model_identity': {},
    'observed_identity': {},
    'benchmark': {
        'suite_id': 'evaluator-benchmark-protocol-v1',
        'suite_version_number': 1,
        'suite_sha256': '68d4fb67a727e1ba48751bbe9a436c18857f1d2f71ef2ccc874a3299c5407e0c',
        'suite_content_hash': '53b30e2961d56d6b35543566490461d83108102af6700e2655be0d98548e6795',
        'task_count': 1,
        'repetitions': 1,
        'expected_measurement_count': 1,
        'observed_measurement_count': 1,
        'complete': True,
    },
    'environment': {
        'environment_sha256': 'b' * 64,
        'package_lock_sha256': 'a' * 64,
        'environment_id': 'test',
        'gpu': {},
        'build_toolchain': {},
    },
    'network_authorized': os.environ.get('ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK') == '1',
    'model_load': {},
    'tasks': [task],
    'benchmark_metrics': metrics,
    'resource_summary': {
        'candidate_id': request['candidate_id'],
        'measurement_count': 1,
        'successful_count': 1,
        'mean_latency_milliseconds': 10.0,
        'peak_gpu_memory_mb': 1000,
        'complete': True,
    },
    'failure_kind': None,
    'failure_message': None,
}
payload['result_sha256'] = digest(payload)
args.result.write_text(canonical(payload))
""",
        encoding="utf-8",
    )
    return path


class ModelSpikeTestClock:
    """Deterministic wall and monotonic clock for process records."""

    def __init__(self) -> None:
        self.value = MODEL_SPIKE_TEST_NOW

    def now(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=10)
        return current

    def monotonic(self) -> float:
        self.value += timedelta(milliseconds=10)
        return self.value.timestamp()


def run_fake_model_spike_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Execute the complete fake matrix and return plan and batch paths."""
    plan, plan_path = create_model_spike_test_plan(tmp_path)
    clock = ModelSpikeTestClock()
    _, batch_path = execute_model_spike_batch(
        plan_path=plan_path,
        output_root=tmp_path / "output",
        runner_path=write_fake_model_spike_runner(tmp_path / "fake_runner.py"),
        selected=plan.requests,
        network_authorized=False,
        timeout_seconds=60,
        python_executable=sys.executable,
        environment={},
        now=clock.now,
        monotonic=clock.monotonic,
    )
    return plan_path, batch_path
