"""CLI application helpers for preparing and finalizing real Sprint 12 case evidence."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_artifact_capture import load_case_study_evidence_map
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_environment import (
    CaseStudyContainerImage,
    CaseStudyRuntimeVersion,
    collect_local_case_study_environment_identity,
)
from orchestwin.evaluation.case_environment_io import (
    load_case_study_environment_identity,
    write_case_study_environment_identity,
)
from orchestwin.evaluation.case_finalization import finalize_case_study_run
from orchestwin.evaluation.case_observations import load_case_study_observation_set
from orchestwin.evaluation.case_preflight import (
    CaseExecutionHostState,
    capture_git_execution_host_state,
    evaluate_case_execution_readiness,
)
from orchestwin.evaluation.case_runs import CaseStudyRunStatus
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import (
    CaseStudyRunWorkspace,
    load_case_study_run_request,
    prepare_case_study_run_workspace,
)

_DEFAULT_BRANCH = "sprint/12-case-studies-expert-evaluation"


@dataclass(frozen=True, slots=True)
class PreparedFormalCaseRun:
    """Paths and immutable identities emitted before the user proceeds through governed gates."""

    workspace_root: Path
    run_request_path: Path
    environment_path: Path
    case_id: str
    workflow_run_id: UUID
    platform_commit: str
    execution_profile: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "workspace_root": str(self.workspace_root),
            "run_request_path": str(self.run_request_path),
            "environment_path": str(self.environment_path),
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "platform_commit": self.platform_commit,
            "execution_profile": self.execution_profile,
        }


def prepare_formal_case_run(
    *,
    repo_root: Path,
    artifact_root: Path,
    host: CaseExecutionHostState,
    case_id: str,
    workflow_run_id: UUID,
    requested_at: datetime,
    expected_branch: str,
    runtime_versions: tuple[CaseStudyRuntimeVersion, ...],
    container_images: tuple[CaseStudyContainerImage, ...],
    network_policy: str,
) -> PreparedFormalCaseRun:
    """Preflight and prepare evidence capture without starting or bypassing the workflow itself."""
    campaign = build_formal_case_campaign_plan(repo_root, platform_commit=host.platform_commit)
    readiness = evaluate_case_execution_readiness(
        campaign,
        host,
        expected_branch=expected_branch,
    )
    if not readiness.ready:
        raise RuntimeError("formal case preflight failed: " + "; ".join(readiness.blockers))
    workspace, request = prepare_case_study_run_workspace(
        artifact_root,
        campaign,
        case_id=case_id,
        workflow_run_id=workflow_run_id,
        requested_at=requested_at,
    )
    environment = collect_local_case_study_environment_identity(
        platform_commit=request.platform_commit,
        execution_profile=request.execution_profile,
        runtime_versions=runtime_versions,
        container_images=container_images,
        network_policy=network_policy,
    )
    environment_path = workspace.raw_dir / "environment.json"
    write_case_study_environment_identity(environment_path, environment)
    return PreparedFormalCaseRun(
        workspace_root=workspace.root,
        run_request_path=workspace.request_path,
        environment_path=environment_path,
        case_id=request.case_id,
        workflow_run_id=request.workflow_run_id,
        platform_commit=request.platform_commit,
        execution_profile=request.execution_profile,
    )


def _runtime(value: str) -> CaseStudyRuntimeVersion:
    component, separator, version = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("runtime must use COMPONENT=VERSION")
    try:
        return CaseStudyRuntimeVersion(component=component, version=version)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _container(value: str) -> CaseStudyContainerImage:
    name, separator, digest = value.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("container must use NAME=sha256:DIGEST")
    try:
        return CaseStudyContainerImage(name=name, digest=digest)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _case_definition_for_request(repo_root: Path, case_id: str):
    case_dir = repo_root / "experiments" / "case-studies"
    matches = []
    for path in sorted(case_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("case_id") == case_id:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("formal case definition could not be resolved uniquely")
    return load_case_study_definition(matches[0])


def _workspace_from_root(root: Path) -> CaseStudyRunWorkspace:
    return CaseStudyRunWorkspace(
        root=root,
        request_path=root / "run-request.json",
        evidence_dir=root / "evidence",
        raw_dir=root / "raw",
        final_dir=root / "final",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or finalize governed Sprint 12 formal case evidence capture.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Print the frozen generic formal-case plan.")
    plan.add_argument("--repo-root", type=Path, default=Path.cwd())
    plan.add_argument("--platform-commit", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="Bind an existing OrchesTwin workflow run to an immutable evidence workspace.",
    )
    prepare.add_argument("--repo-root", type=Path, default=Path.cwd())
    prepare.add_argument("--artifact-root", type=Path, required=True)
    prepare.add_argument("--case-id", required=True)
    prepare.add_argument("--workflow-run-id", type=UUID, required=True)
    prepare.add_argument("--expected-branch", default=_DEFAULT_BRANCH)
    prepare.add_argument("--available-profile", action="append", required=True)
    prepare.add_argument("--runtime", action="append", type=_runtime, default=[])
    prepare.add_argument("--container", action="append", type=_container, default=[])
    prepare.add_argument(
        "--network-policy",
        default="No external network during generated application execution.",
    )

    finalize = subparsers.add_parser(
        "finalize",
        help="Create a terminal record from files and measurements already observed in a workspace.",
    )
    finalize.add_argument("--repo-root", type=Path, default=Path.cwd())
    finalize.add_argument("--workspace-root", type=Path, required=True)
    finalize.add_argument("--evidence-map", type=Path)
    finalize.add_argument("--observations", type=Path)
    finalize.add_argument("--started-at", type=datetime.fromisoformat, required=True)
    finalize.add_argument("--completed-at", type=datetime.fromisoformat, required=True)
    finalize.add_argument(
        "--status",
        type=CaseStudyRunStatus,
        choices=tuple(CaseStudyRunStatus),
        required=True,
    )
    finalize.add_argument("--note", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Formal workflow execution remains governed by OrchesTwin UI/API gates."""
    arguments = _parser().parse_args(argv)
    if arguments.command == "plan":
        plan = build_formal_case_campaign_plan(
            arguments.repo_root,
            platform_commit=arguments.platform_commit,
        )
        print(json.dumps(plan.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if arguments.command == "prepare":
        host = capture_git_execution_host_state(
            arguments.repo_root,
            available_execution_profiles=tuple(arguments.available_profile),
        )
        prepared = prepare_formal_case_run(
            repo_root=arguments.repo_root,
            artifact_root=arguments.artifact_root,
            host=host,
            case_id=arguments.case_id,
            workflow_run_id=arguments.workflow_run_id,
            requested_at=datetime.now(UTC),
            expected_branch=arguments.expected_branch,
            runtime_versions=tuple(arguments.runtime),
            container_images=tuple(arguments.container),
            network_policy=arguments.network_policy,
        )
        print(json.dumps(prepared.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    workspace = _workspace_from_root(arguments.workspace_root)
    request = load_case_study_run_request(workspace.request_path)
    environment = load_case_study_environment_identity(workspace.raw_dir / "environment.json")
    evidence_map_path = arguments.evidence_map or workspace.raw_dir / "evidence-map.json"
    evidence_map = load_case_study_evidence_map(evidence_map_path)
    observations_path = arguments.observations
    if observations_path is None:
        default_observations = workspace.raw_dir / "observations.json"
        observations_path = default_observations if default_observations.exists() else None
    observations = (
        None if observations_path is None else load_case_study_observation_set(observations_path)
    )
    finalized = finalize_case_study_run(
        workspace=workspace,
        request=request,
        definition=_case_definition_for_request(arguments.repo_root, request.case_id),
        environment=environment,
        evidence_map=evidence_map,
        observations=observations,
        started_at=arguments.started_at,
        completed_at=arguments.completed_at,
        status=arguments.status,
        notes=tuple(arguments.note),
    )
    print(
        json.dumps(
            {
                "record_path": str(finalized.record_path),
                "record_content_hash": finalized.record.content_hash,
                "status": finalized.record.status.value,
                "definition_of_done_complete": finalized.coverage.is_complete,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0
