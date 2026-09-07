"""Preflight checks that block formal case execution on an uncontrolled repository state."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.case_campaign import FormalCaseCampaignPlan


@dataclass(frozen=True, slots=True)
class CaseExecutionHostState:
    """Observed repository and execution-profile state used for one campaign preflight."""

    platform_commit: str
    branch: str
    worktree_clean: bool
    available_execution_profiles: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.branch or self.branch != " ".join(self.branch.split()):
            raise ValueError("execution host branch must be normalized")
        if not self.available_execution_profiles:
            raise ValueError("at least one execution profile must be observed")
        if len(self.available_execution_profiles) != len(set(self.available_execution_profiles)):
            raise ValueError("observed execution profiles must be unique")
        if self.available_execution_profiles != tuple(sorted(self.available_execution_profiles)):
            raise ValueError("observed execution profiles must use canonical order")


@dataclass(frozen=True, slots=True)
class CaseExecutionReadiness:
    """Deterministic preflight decision; blockers must be resolved before formal execution."""

    ready: bool
    blockers: tuple[str, ...]
    required_profiles: tuple[str, ...]
    observed_profiles: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ready == bool(self.blockers):
            raise ValueError("case execution readiness and blockers are inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "blockers": list(self.blockers),
            "required_profiles": list(self.required_profiles),
            "observed_profiles": list(self.observed_profiles),
        }


def evaluate_case_execution_readiness(
    plan: FormalCaseCampaignPlan,
    host: CaseExecutionHostState,
    *,
    expected_branch: str,
) -> CaseExecutionReadiness:
    """Require the frozen commit, clean tree, branch, and all generic execution profiles."""
    blockers: list[str] = []
    if host.platform_commit != plan.platform_commit:
        blockers.append("platform commit differs from the frozen campaign plan")
    if host.branch != expected_branch:
        blockers.append("formal case execution is on an unexpected Git branch")
    if not host.worktree_clean:
        blockers.append("formal case execution requires a clean working tree")
    required_profiles = tuple(sorted({case.execution_profile for case in plan.cases}))
    missing_profiles = tuple(
        profile for profile in required_profiles if profile not in host.available_execution_profiles
    )
    if missing_profiles:
        blockers.append(f"missing execution profiles: {', '.join(missing_profiles)}")
    return CaseExecutionReadiness(
        ready=not blockers,
        blockers=tuple(blockers),
        required_profiles=required_profiles,
        observed_profiles=host.available_execution_profiles,
    )


def capture_git_execution_host_state(
    repo_root: Path,
    *,
    available_execution_profiles: tuple[str, ...],
) -> CaseExecutionHostState:
    """Observe Git state locally without mutating the repository or contacting a network service."""

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    return CaseExecutionHostState(
        platform_commit=git("rev-parse", "HEAD"),
        branch=git("branch", "--show-current"),
        worktree_clean=not bool(git("status", "--porcelain")),
        available_execution_profiles=tuple(sorted(available_execution_profiles)),
    )
