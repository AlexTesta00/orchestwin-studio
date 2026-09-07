"""CLI tests for harvesting already-observed formal case evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_harvest_cli import main
from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
    write_case_metric_binding_set,
)
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 7, 19, 10, tzinfo=UTC)
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000039001")


def test_harvest_cli_reads_bound_json_values_and_writes_raw_outputs(tmp_path, capsys) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="c" * 40)
    workspace, _ = prepare_case_study_run_workspace(
        tmp_path / "artifacts",
        campaign,
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=NOW,
    )
    values = {}
    for field, value_type in METRIC_FIELD_TYPES.items():
        values[field] = True if value_type is MetricValueType.BOOLEAN else 1
    values["criteria_total"] = len(definition.definition_of_done)
    values["criteria_satisfied"] = len(definition.definition_of_done)
    values["repair_successes"] = 0
    values["repair_attempts"] = 0
    (workspace.evidence_dir / "metrics.json").write_text(
        json.dumps({"metrics": values}), encoding="utf-8"
    )
    bindings = create_case_metric_binding_set(
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        bindings=tuple(
            CaseMetricBinding(
                field=field,
                value_type=value_type,
                source_path="metrics.json",
                json_pointer=f"/metrics/{field}",
            )
            for field, value_type in METRIC_FIELD_TYPES.items()
        ),
    )
    binding_path = tmp_path / "bindings.json"
    write_case_metric_binding_set(binding_path, bindings)
    by_kind = {}
    for criterion in definition.definition_of_done:
        for kind in criterion.evidence:
            by_kind.setdefault(kind, []).append(criterion.criterion_id)
    entries = []
    for kind, criteria in sorted(by_kind.items(), key=lambda item: item[0].value):
        relative = f"{kind.value.lower()}.json"
        (workspace.evidence_dir / relative).write_text("{}", encoding="utf-8")
        entries.append(
            CaseStudyEvidenceMapEntry(
                kind=kind,
                relative_path=relative,
                criterion_ids=tuple(sorted(criteria)),
            )
        )
    map_path = tmp_path / "evidence-map.json"
    map_path.write_text(
        json.dumps({"schema_version": 1, "entries": [entry.to_snapshot() for entry in entries]}),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--repo-root",
                str(REPO_ROOT),
                "--workspace-root",
                str(workspace.root),
                "--bindings",
                str(binding_path),
                "--evidence-map",
                str(map_path),
                "--captured-at",
                NOW.isoformat(),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["case_id"] == definition.case_id
    assert (workspace.raw_dir / "observations.json").is_file()
