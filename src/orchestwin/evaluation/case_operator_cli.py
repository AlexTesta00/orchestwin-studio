"""Operator CLI for launching and observing the three formal Sprint 12 case runs."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_api_capture import (
    build_core_case_api_requests,
    capture_case_api_snapshot,
)
from orchestwin.evaluation.case_gate_journal import (
    ObservedGateDecision,
    append_gate_decision,
    load_gate_journal,
    write_gate_journal,
)
from orchestwin.evaluation.case_launch_inputs import FormalGateType, load_formal_case_launch_input
from orchestwin.evaluation.case_operator_workspace import initialize_case_operator_session

_TOKEN_ENV = "ORCHESTWIN_ACCESS_TOKEN"


def _input_path(repo_root: Path, case_id: str) -> Path:
    return repo_root / "experiments" / "case-studies" / "run-inputs" / f"{case_id}-v1.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and observe real formal case runs without bypassing OrchesTwin gates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show-input")
    show.add_argument("--repo-root", type=Path, default=Path.cwd())
    show.add_argument("--case-id", required=True)

    initialize = subparsers.add_parser("initialize")
    initialize.add_argument("--repo-root", type=Path, default=Path.cwd())
    initialize.add_argument("--workspace-root", type=Path, required=True)
    initialize.add_argument("--case-id", required=True)
    initialize.add_argument("--project-id", type=UUID, required=True)
    initialize.add_argument("--workflow-run-id", type=UUID, required=True)

    capture = subparsers.add_parser("capture-core-api")
    capture.add_argument("--workspace-root", type=Path, required=True)
    capture.add_argument("--project-id", type=UUID, required=True)
    capture.add_argument("--workflow-run-id", type=UUID, required=True)
    capture.add_argument("--base-url", default="http://127.0.0.1:8000")
    capture.add_argument("--access-token-env", default=_TOKEN_ENV)

    gate = subparsers.add_parser("record-gate")
    gate.add_argument("--workspace-root", type=Path, required=True)
    gate.add_argument(
        "--gate-type",
        type=FormalGateType,
        choices=tuple(FormalGateType),
        required=True,
    )
    gate.add_argument("--gate-id", type=UUID, required=True)
    gate.add_argument("--source-event-id", type=UUID, required=True)
    gate.add_argument("--sequence-number", type=int, required=True)
    gate.add_argument("--action", required=True)
    gate.add_argument("--resulting-status", required=True)
    gate.add_argument("--artifact-id", type=UUID, required=True)
    gate.add_argument("--artifact-version", type=int, required=True)
    gate.add_argument("--artifact-content-hash", required=True)
    gate.add_argument("--actor-user-id", type=UUID, required=True)
    gate.add_argument("--occurred-at", type=datetime.fromisoformat, required=True)
    gate.add_argument("--source-snapshot-sha256", required=True)
    gate.add_argument("--reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one operator action; all actual owner approvals remain in OrchesTwin."""
    args = _parser().parse_args(argv)
    if args.command == "show-input":
        launch = load_formal_case_launch_input(_input_path(args.repo_root, args.case_id))
        print(json.dumps(launch.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "initialize":
        launch = load_formal_case_launch_input(_input_path(args.repo_root, args.case_id))
        session = initialize_case_operator_session(
            workspace_root=args.workspace_root,
            launch=launch,
            project_id=args.project_id,
            workflow_run_id=args.workflow_run_id,
            prepared_at=datetime.now(UTC),
        )
        print(json.dumps(session.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "capture-core-api":
        token = os.environ.get(args.access_token_env)
        if token is None:
            raise RuntimeError(
                f"required access token environment variable is missing: {args.access_token_env}"
            )
        artifacts = tuple(
            capture_case_api_snapshot(
                base_url=args.base_url,
                access_token=token,
                request=request,
                evidence_root=args.workspace_root / "evidence",
            )
            for request in build_core_case_api_requests(
                project_id=args.project_id,
                workflow_run_id=args.workflow_run_id,
            )
        )
        print(
            json.dumps(
                {"artifacts": [item.to_snapshot() for item in artifacts]},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    journal_path = args.workspace_root / "raw" / "gate-journal.json"
    journal = load_gate_journal(journal_path)
    decision = ObservedGateDecision(
        gate_type=args.gate_type,
        gate_id=args.gate_id,
        source_event_id=args.source_event_id,
        sequence_number=args.sequence_number,
        action=args.action,
        resulting_status=args.resulting_status,
        artifact_id=args.artifact_id,
        artifact_version=args.artifact_version,
        artifact_content_hash=args.artifact_content_hash,
        actor_user_id=args.actor_user_id,
        occurred_at=args.occurred_at,
        source_snapshot_sha256=args.source_snapshot_sha256,
        reason=args.reason,
    )
    updated = append_gate_decision(journal, decision)
    write_gate_journal(journal_path, updated)
    print(json.dumps(updated.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0
