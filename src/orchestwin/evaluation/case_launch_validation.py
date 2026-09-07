"""Cross-check formal launch inputs and observed gate completeness before final case capture."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestwin.evaluation.case_gate_journal import FormalCaseGateJournal
from orchestwin.evaluation.case_launch_inputs import (
    REQUIRED_FORMAL_GATES,
    FormalCaseLaunchInput,
    load_formal_case_launch_input,
    validate_launch_input_against_definition,
)

_EXPECTED_CASE_IDS = (
    "web-calculator",
    "hotel-management-web",
    "weather-comparison-web",
)


@dataclass(frozen=True, slots=True)
class FormalLaunchValidationSummary:
    """Validated configuration summary for the three formal Web case launches."""

    case_ids: tuple[str, ...]
    execution_profiles: tuple[str, ...]
    technology_union: tuple[str, ...]
    required_gate_count: int
    mobile_scope_present: bool
    php_in_scope: bool
    ready_for_observed_execution: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "case_ids": list(self.case_ids),
            "execution_profiles": list(self.execution_profiles),
            "technology_union": list(self.technology_union),
            "required_gate_count": self.required_gate_count,
            "mobile_scope_present": self.mobile_scope_present,
            "php_in_scope": self.php_in_scope,
            "ready_for_observed_execution": self.ready_for_observed_execution,
        }


def verify_formal_case_launch_configuration(repo_root: Path) -> FormalLaunchValidationSummary:
    """Validate every run input against its exact frozen case definition."""
    launch_dir = repo_root / "experiments" / "case-studies" / "run-inputs"
    launches: list[FormalCaseLaunchInput] = []
    for case_id in _EXPECTED_CASE_IDS:
        launch = load_formal_case_launch_input(launch_dir / f"{case_id}-v1.json")
        definition_path = repo_root / launch.definition_path
        definition = json.loads(definition_path.read_text(encoding="utf-8"))
        validate_launch_input_against_definition(launch, definition)
        launches.append(launch)
    case_ids = tuple(item.case_id for item in launches)
    if case_ids != _EXPECTED_CASE_IDS:
        raise ValueError("formal launch case IDs differ from the frozen Sprint 12 campaign")
    technology_union = tuple(sorted({tech for item in launches for tech in item.technologies}))
    serialized = json.dumps(
        [item.to_snapshot() for item in launches],
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    mobile_tokens = ("android", "flutter", "jetpack compose", "apk", "adb", "emulator")
    mobile_scope_present = any(token in serialized for token in mobile_tokens)
    php_in_scope = any("PHP" in item.technologies for item in launches)
    if mobile_scope_present:
        raise ValueError("formal launch configuration contains stale mobile scope")
    if php_in_scope:
        raise ValueError("formal launch configuration contains PHP outside the revised scope")
    if any(item.required_gates != REQUIRED_FORMAL_GATES for item in launches):
        raise ValueError("formal launch configuration does not preserve all owner gates")
    return FormalLaunchValidationSummary(
        case_ids=case_ids,
        execution_profiles=tuple(item.execution_profile for item in launches),
        technology_union=technology_union,
        required_gate_count=len(REQUIRED_FORMAL_GATES),
        mobile_scope_present=False,
        php_in_scope=False,
        ready_for_observed_execution=True,
    )


def verify_gate_journal_complete(
    launch: FormalCaseLaunchInput,
    journal: FormalCaseGateJournal,
) -> None:
    """Require one observed APPROVED event for every frozen owner gate before final analysis."""
    if journal.case_id != launch.case_id:
        raise ValueError("gate journal belongs to a different formal case")
    approved = {
        item.gate_type: item
        for item in journal.observations
        if item.action == "APPROVE" and item.resulting_status == "APPROVED"
    }
    missing = [gate.value for gate in launch.required_gates if gate not in approved]
    if missing:
        raise ValueError("formal gate journal is incomplete: " + ", ".join(missing))
    approval_times = [approved[gate].occurred_at for gate in launch.required_gates]
    if approval_times != sorted(approval_times):
        raise ValueError("formal gate approvals are not in governed workflow order")
