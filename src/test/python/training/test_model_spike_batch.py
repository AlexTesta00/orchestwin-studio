from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (
    ModelSourceCaptureMode,
    create_captured_model_source_evidence,
    expected_candidate_source_roles,
    serialize_captured_model_source_evidence,
)
from orchestwin.training.model_spike_batch import (
    MODEL_SPIKE_BATCH_ALL_GATE,
    ModelSpikeBatchError,
    ModelSpikeProcessStatus,
    execute_model_spike_batch,
    select_model_spike_requests,
)
from orchestwin.training.model_spike_requests import materialize_model_spike_execution_plan

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)


def _plan(tmp_path: Path):
    matrix = load_frozen_model_candidate_matrix(REPOSITORY_ROOT)
    evidence = []
    for candidate in matrix.candidates:
        files = {
            path: f"{candidate.candidate_id}:{path}".encode()
            for path in expected_candidate_source_roles(candidate)
        }
        item = create_captured_model_source_evidence(
            candidate=candidate,
            captured_files=files,
            capture_mode=ModelSourceCaptureMode.CACHE_ONLY,
            captured_at=NOW,
            resolved_revision=candidate.revision,
        )
        digest = (
            __import__("hashlib").sha256(serialize_captured_model_source_evidence(item)).hexdigest()
        )
        evidence.append((item, digest))
    return materialize_model_spike_execution_plan(
        matrix=matrix,
        source_evidence=tuple(evidence),
        output_root=tmp_path / "inputs",
        package_lock_sha256="a" * 64,
        environment_sha256="b" * 64,
        created_at=NOW,
    )


def _fake_runner(path: Path) -> Path:
    path.write_text(
        """\
import argparse
import hashlib
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--request', type=Path, required=True)
parser.add_argument('--result', type=Path, required=True)
args = parser.parse_args()
request = json.loads(args.request.read_text())
payload = {
    'candidate_id': request['candidate_id'],
    'request_sha256': request['request_sha256'],
    'network': os.environ.get('ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK'),
    'offline': os.environ.get('HF_HUB_OFFLINE'),
}
args.result.parent.mkdir(parents=True, exist_ok=True)
args.result.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':')))
print(request['candidate_id'])
raise SystemExit(7 if 'qwen3' in request['candidate_id'] else 0)
""",
        encoding="utf-8",
    )
    return path


class _Clock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=5)
        return current

    def monotonic(self) -> float:
        self.value += timedelta(milliseconds=5)
        return self.value.timestamp()


def test_selection_requires_explicit_gate_for_the_full_matrix(tmp_path: Path) -> None:
    plan, _ = _plan(tmp_path)

    with pytest.raises(ModelSpikeBatchError, match=MODEL_SPIKE_BATCH_ALL_GATE):
        select_model_spike_requests(
            plan=plan,
            candidate_ids=(),
            all_requested=True,
            all_authorized=False,
        )

    assert (
        select_model_spike_requests(
            plan=plan,
            candidate_ids=(),
            all_requested=True,
            all_authorized=True,
        )
        == plan.requests
    )


def test_batch_executes_each_selected_candidate_once_and_preserves_failures(
    tmp_path: Path,
) -> None:
    plan, plan_path = _plan(tmp_path)
    selected = plan.requests[:2]
    runner = _fake_runner(tmp_path / "fake_runner.py")
    clock = _Clock()

    record, record_path = execute_model_spike_batch(
        plan_path=plan_path,
        output_root=tmp_path / "output",
        runner_path=runner,
        selected=selected,
        network_authorized=False,
        timeout_seconds=60,
        python_executable=sys.executable,
        environment={},
        now=clock.now,
        monotonic=clock.monotonic,
    )

    assert record.execution_complete is True
    assert record.all_succeeded is False
    assert [item.status for item in record.processes] == [
        ModelSpikeProcessStatus.SUCCEEDED,
        ModelSpikeProcessStatus.FAILED,
    ]
    assert [item.exit_code for item in record.processes] == [0, 7]
    assert record_path.is_file()
    for process in record.processes:
        run_root = record_path.parent / "runs" / process.candidate_id
        assert (run_root / "result.json").is_file()
        assert (run_root / "process.json").is_file()
        result = json.loads((run_root / "result.json").read_text())
        assert result["offline"] == "1"
        assert result["network"] is None
        assert (run_root / "stdout.log").read_text().count(process.candidate_id) == 1


def test_network_gate_is_forwarded_without_recording_credentials(tmp_path: Path) -> None:
    plan, plan_path = _plan(tmp_path)
    runner = _fake_runner(tmp_path / "fake_runner.py")
    clock = _Clock()

    record, record_path = execute_model_spike_batch(
        plan_path=plan_path,
        output_root=tmp_path / "output",
        runner_path=runner,
        selected=(plan.requests[0],),
        network_authorized=True,
        timeout_seconds=60,
        python_executable=sys.executable,
        environment={"HF_TOKEN": "secret-not-recorded"},
        now=clock.now,
        monotonic=clock.monotonic,
    )

    result = json.loads(
        (record_path.parent / str(record.processes[0].result_reference)).read_text()
    )
    assert result["network"] == "1"
    assert result["offline"] is None
    assert "secret-not-recorded" not in record_path.read_text()
    assert (
        "secret-not-recorded"
        not in (record_path.parent / record.processes[0].stdout_reference).read_text()
    )


def test_batch_refuses_to_overwrite_existing_evidence(tmp_path: Path) -> None:
    plan, plan_path = _plan(tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "existing.txt").write_text("preserve")

    with pytest.raises(ModelSpikeBatchError, match="absent or empty"):
        execute_model_spike_batch(
            plan_path=plan_path,
            output_root=output_root,
            runner_path=_fake_runner(tmp_path / "fake_runner.py"),
            selected=(plan.requests[0],),
            network_authorized=False,
            timeout_seconds=60,
        )


def test_selection_rejects_unknown_duplicate_or_ambiguous_candidates(tmp_path: Path) -> None:
    plan, _ = _plan(tmp_path)

    with pytest.raises(ModelSpikeBatchError, match="cannot combine"):
        select_model_spike_requests(
            plan=plan,
            candidate_ids=(plan.requests[0].candidate_id,),
            all_requested=True,
            all_authorized=True,
        )
    with pytest.raises(ModelSpikeBatchError, match="must not be repeated"):
        select_model_spike_requests(
            plan=plan,
            candidate_ids=(plan.requests[0].candidate_id,) * 2,
            all_requested=False,
            all_authorized=False,
        )
    with pytest.raises(ModelSpikeBatchError, match="not present"):
        select_model_spike_requests(
            plan=plan,
            candidate_ids=("model-candidate-not-frozen",),
            all_requested=False,
            all_authorized=False,
        )
