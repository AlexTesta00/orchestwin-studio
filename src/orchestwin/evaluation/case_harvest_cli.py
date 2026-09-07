"""CLI for harvesting already-observed formal case files into Sprint 12 raw evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from orchestwin.evaluation.case_artifact_capture import load_case_study_evidence_map
from orchestwin.evaluation.case_harvest_pipeline import harvest_case_study_workspace_evidence
from orchestwin.evaluation.case_metric_bindings import load_case_metric_binding_set
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import (
    CaseStudyRunWorkspace,
    load_case_study_run_request,
)


def _workspace(root: Path) -> CaseStudyRunWorkspace:
    return CaseStudyRunWorkspace(
        root=root,
        request_path=root / "run-request.json",
        evidence_dir=root / "evidence",
        raw_dir=root / "raw",
        final_dir=root / "final",
    )


def _definition(repo_root: Path, case_id: str):
    case_dir = repo_root / "experiments" / "case-studies"
    matches = []
    for path in sorted(case_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("case_id") == case_id:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError("formal case definition could not be resolved uniquely")
    return load_case_study_definition(matches[0])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Harvest metrics from JSON pointers in already-observed Sprint 12 evidence files. "
            "This command does not execute OrchesTwin or fabricate missing values."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--evidence-map", type=Path, required=True)
    parser.add_argument("--captured-at", type=datetime.fromisoformat)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Harvest actual files for a prepared workflow-bound formal case workspace."""
    arguments = _parser().parse_args(argv)
    workspace = _workspace(arguments.workspace_root)
    request = load_case_study_run_request(workspace.request_path)
    definition = _definition(arguments.repo_root, request.case_id)
    binding_set = load_case_metric_binding_set(arguments.bindings)
    evidence_map = load_case_study_evidence_map(arguments.evidence_map)
    harvested = harvest_case_study_workspace_evidence(
        workspace=workspace,
        request=request,
        definition=definition,
        binding_set=binding_set,
        evidence_map=evidence_map,
        captured_at=arguments.captured_at or datetime.now(UTC),
    )
    print(json.dumps(harvested.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0
