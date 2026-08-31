"""Deterministic multi-twin aggregation without fabricated consensus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.evaluation.application import SyntheticEvaluationRun
from orchestwin.evaluation.findings import SyntheticFinding
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_sha256,
)

_MAX_TEXT_LENGTH: Final = 2_000
_MAX_IDENTIFIER_LENGTH: Final = 128

MULTI_TWIN_AGGREGATION_DISCLAIMER: Final = (
    "This aggregation preserves independent simulated User Twin findings. It does not "
    "represent human consensus or empirical validation."
)


@dataclass(frozen=True, slots=True)
class DeclaredFindingConflict:
    """Explicit conflict between two findings, never inferred from fluent text alone."""

    conflict_id: str
    left_finding_id: str
    right_finding_id: str
    summary: str
    owner_decision_question: str

    def __post_init__(self) -> None:
        for value, label, maximum_length in (
            (self.conflict_id, "finding conflict ID", _MAX_IDENTIFIER_LENGTH),
            (self.left_finding_id, "left finding ID", _MAX_IDENTIFIER_LENGTH),
            (self.right_finding_id, "right finding ID", _MAX_IDENTIFIER_LENGTH),
            (self.summary, "finding conflict summary", _MAX_TEXT_LENGTH),
            (
                self.owner_decision_question,
                "finding conflict owner question",
                _MAX_TEXT_LENGTH,
            ),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=maximum_length,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")
        if self.left_finding_id >= self.right_finding_id:
            raise ValueError("finding conflict IDs must use canonical order")

    @property
    def finding_ids(self) -> tuple[str, str]:
        return (self.left_finding_id, self.right_finding_id)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return (self.left_finding_id, self.right_finding_id, self.conflict_id)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "conflict_id": self.conflict_id,
            "finding_ids": list(self.finding_ids),
            "summary": self.summary,
            "owner_decision_question": self.owner_decision_question,
        }


@dataclass(frozen=True, slots=True)
class SharedFindingGroup:
    """Exact semantically matching findings reported by at least two distinct twins."""

    group_id: str
    findings: tuple[SyntheticFinding, ...]

    def __post_init__(self) -> None:
        if len(self.findings) < 2:
            raise ValueError("shared finding groups require at least two findings")
        ordered = tuple(sorted(self.findings, key=_finding_sort_key))
        if ordered != self.findings:
            raise ValueError("shared finding groups must use canonical finding order")
        if len({item.twin_id for item in self.findings}) < 2:
            raise ValueError("shared finding groups require distinct User Twins")
        keys = {_shared_comparison_key(item) for item in self.findings}
        if len(keys) != 1:
            raise ValueError("shared finding groups require one exact comparison key")

    @property
    def finding_ids(self) -> tuple[str, ...]:
        return tuple(item.finding_id for item in self.findings)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "comparison_key": list(_shared_comparison_key(self.findings[0])),
            "findings": [item.to_snapshot() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class RoleSpecificFinding:
    """One finding that is neither shared nor part of an explicit direct conflict."""

    finding: SyntheticFinding

    @property
    def sort_key(self) -> tuple[str, str, int]:
        return (
            self.finding.finding_id,
            self.finding.twin_id.hex,
            self.finding.twin_version,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {"finding": self.finding.to_snapshot()}


@dataclass(frozen=True, slots=True)
class DirectFindingConflict:
    """Validated explicit conflict preserving both original finding snapshots."""

    declaration: DeclaredFindingConflict
    findings: tuple[SyntheticFinding, SyntheticFinding]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.findings, key=_finding_sort_key))
        if ordered != self.findings:
            raise ValueError("direct conflicts must use canonical finding order")
        if tuple(item.finding_id for item in self.findings) != self.declaration.finding_ids:
            raise ValueError("direct conflict findings must match the declaration")
        left, right = self.findings
        if left.twin_id == right.twin_id:
            raise ValueError("direct conflicts require findings from different User Twins")
        if _conflict_scope_key(left) != _conflict_scope_key(right):
            raise ValueError(
                "direct conflicts must target the same artifact location and criterion"
            )
        if left.recommended_action == right.recommended_action:
            raise ValueError("direct conflicts require distinct recommended actions")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.declaration.sort_key

    def to_snapshot(self) -> dict[str, object]:
        return {
            "declaration": self.declaration.to_snapshot(),
            "findings": [item.to_snapshot() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class TwinEvidenceGap:
    """One evaluator evidence gap retained with its exact User Twin identity."""

    twin_id: UUID
    twin_version: int
    gap: str

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.gap,
            label="User Twin evidence gap",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized != self.gap:
            raise ValueError("User Twin evidence gap must be normalized")
        if self.twin_version < 1:
            raise ValueError("User Twin evidence gap version must be positive")

    @property
    def sort_key(self) -> tuple[str, int, str]:
        return (self.twin_id.hex, self.twin_version, self.gap)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "twin_version": self.twin_version,
            "gap": self.gap,
        }


@dataclass(frozen=True, slots=True)
class HumanValidationQuestion:
    """Deterministically generated question for a later human validation activity."""

    question_id: str
    related_finding_ids: tuple[str, ...]
    question: str

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.question,
            label="human validation question",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized != self.question:
            raise ValueError("human validation question must be normalized")
        if not self.related_finding_ids:
            raise ValueError("human validation questions require finding references")
        canonical = tuple(sorted(set(self.related_finding_ids)))
        if canonical != self.related_finding_ids:
            raise ValueError("human validation finding references must be canonical")

    @property
    def sort_key(self) -> tuple[tuple[str, ...], str]:
        return (self.related_finding_ids, self.question_id)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "question_id": self.question_id,
            "related_finding_ids": list(self.related_finding_ids),
            "question": self.question,
        }


@dataclass(frozen=True, slots=True)
class MultiTwinEvaluationAggregation:
    """Immutable deterministic view over one completed synthetic evaluation run."""

    evaluation_run_id: UUID
    evaluation_run_hash: str
    shared_findings: tuple[SharedFindingGroup, ...]
    role_specific_findings: tuple[RoleSpecificFinding, ...]
    direct_conflicts: tuple[DirectFindingConflict, ...]
    unresolved_trade_offs: tuple[str, ...]
    evidence_gaps: tuple[TwinEvidenceGap, ...]
    human_validation_questions: tuple[HumanValidationQuestion, ...]
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(
            self.evaluation_run_hash,
            label="aggregated evaluation run hash",
        )
        validate_sha256(
            self.content_hash,
            label="multi-twin aggregation content hash",
        )
        if tuple(sorted(self.shared_findings, key=lambda item: item.group_id)) != (
            self.shared_findings
        ):
            raise ValueError("shared finding groups must use canonical order")
        if tuple(sorted(self.role_specific_findings, key=lambda item: item.sort_key)) != (
            self.role_specific_findings
        ):
            raise ValueError("role-specific findings must use canonical order")
        if tuple(sorted(self.direct_conflicts, key=lambda item: item.sort_key)) != (
            self.direct_conflicts
        ):
            raise ValueError("direct conflicts must use canonical order")
        if tuple(sorted(set(self.unresolved_trade_offs))) != self.unresolved_trade_offs:
            raise ValueError("unresolved trade-offs must be canonical and unique")
        if tuple(sorted(self.evidence_gaps, key=lambda item: item.sort_key)) != self.evidence_gaps:
            raise ValueError("evidence gaps must use canonical order")
        if (
            tuple(sorted(self.human_validation_questions, key=lambda item: item.sort_key))
            != self.human_validation_questions
        ):
            raise ValueError("human validation questions must use canonical order")
        expected = multi_twin_aggregation_hash(
            evaluation_run_id=self.evaluation_run_id,
            evaluation_run_hash=self.evaluation_run_hash,
            shared_findings=self.shared_findings,
            role_specific_findings=self.role_specific_findings,
            direct_conflicts=self.direct_conflicts,
            unresolved_trade_offs=self.unresolved_trade_offs,
            evidence_gaps=self.evidence_gaps,
            human_validation_questions=self.human_validation_questions,
        )
        if self.content_hash != expected:
            raise ValueError("multi-twin aggregation content hash is inconsistent")

    @property
    def disclaimer(self) -> str:
        return MULTI_TWIN_AGGREGATION_DISCLAIMER

    def semantic_snapshot(self) -> dict[str, object]:
        return _aggregation_semantic_snapshot(
            evaluation_run_id=self.evaluation_run_id,
            evaluation_run_hash=self.evaluation_run_hash,
            shared_findings=self.shared_findings,
            role_specific_findings=self.role_specific_findings,
            direct_conflicts=self.direct_conflicts,
            unresolved_trade_offs=self.unresolved_trade_offs,
            evidence_gaps=self.evidence_gaps,
            human_validation_questions=self.human_validation_questions,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "content_hash": self.content_hash,
            "disclaimer": self.disclaimer,
            "is_empirical_evidence": False,
        }


def aggregate_synthetic_evaluation(
    run: SyntheticEvaluationRun,
    *,
    declared_conflicts: tuple[DeclaredFindingConflict, ...] = (),
) -> MultiTwinEvaluationAggregation:
    """Aggregate exact findings while preserving role specificity and disagreements."""
    findings = run.findings
    findings_by_id = {item.finding_id: item for item in findings}
    if len(findings_by_id) != len(findings):
        raise ValueError("synthetic evaluation finding IDs must be unique across User Twins")

    ordered_declarations = tuple(sorted(declared_conflicts, key=lambda item: item.sort_key))
    if ordered_declarations != declared_conflicts:
        raise ValueError("declared conflicts must use canonical order")
    direct_conflicts: list[DirectFindingConflict] = []
    conflicted_ids: set[str] = set()
    for declaration in declared_conflicts:
        try:
            pair = (
                findings_by_id[declaration.left_finding_id],
                findings_by_id[declaration.right_finding_id],
            )
        except KeyError as error:
            raise ValueError("declared conflict references an unknown finding") from error
        if conflicted_ids.intersection(declaration.finding_ids):
            raise ValueError("one finding cannot belong to multiple direct conflicts")
        conflict = DirectFindingConflict(declaration=declaration, findings=pair)
        direct_conflicts.append(conflict)
        conflicted_ids.update(declaration.finding_ids)

    candidates = [item for item in findings if item.finding_id not in conflicted_ids]
    grouped: dict[tuple[str, int, str, str, str], list[SyntheticFinding]] = {}
    for finding in candidates:
        grouped.setdefault(_shared_comparison_key(finding), []).append(finding)

    shared: list[SharedFindingGroup] = []
    shared_ids: set[str] = set()
    for key, group in grouped.items():
        distinct_twins = {item.twin_id for item in group}
        if len(group) < 2 or len(distinct_twins) < 2:
            continue
        ordered = tuple(sorted(group, key=_finding_sort_key))
        group_id = f"shared-{snapshot_content_hash({'key': list(key)})[:16]}"
        shared.append(SharedFindingGroup(group_id=group_id, findings=ordered))
        shared_ids.update(item.finding_id for item in ordered)

    role_specific = tuple(
        sorted(
            (
                RoleSpecificFinding(item)
                for item in findings
                if item.finding_id not in conflicted_ids and item.finding_id not in shared_ids
            ),
            key=lambda item: item.sort_key,
        )
    )
    shared_findings = tuple(sorted(shared, key=lambda item: item.group_id))
    conflicts = tuple(sorted(direct_conflicts, key=lambda item: item.sort_key))
    trade_offs = tuple(
        sorted(
            {f"{item.declaration.conflict_id}: {item.declaration.summary}" for item in conflicts}
        )
    )
    evidence_gaps = tuple(
        sorted(
            (
                TwinEvidenceGap(response.twin_id, response.twin_version, gap)
                for response in run.twin_evaluations
                for gap in response.evidence_gaps
            ),
            key=lambda item: item.sort_key,
        )
    )
    questions = _human_validation_questions(findings, conflicts)
    content_hash = multi_twin_aggregation_hash(
        evaluation_run_id=run.id,
        evaluation_run_hash=run.content_hash,
        shared_findings=shared_findings,
        role_specific_findings=role_specific,
        direct_conflicts=conflicts,
        unresolved_trade_offs=trade_offs,
        evidence_gaps=evidence_gaps,
        human_validation_questions=questions,
    )
    return MultiTwinEvaluationAggregation(
        evaluation_run_id=run.id,
        evaluation_run_hash=run.content_hash,
        shared_findings=shared_findings,
        role_specific_findings=role_specific,
        direct_conflicts=conflicts,
        unresolved_trade_offs=trade_offs,
        evidence_gaps=evidence_gaps,
        human_validation_questions=questions,
        content_hash=content_hash,
    )


def multi_twin_aggregation_hash(
    *,
    evaluation_run_id: UUID,
    evaluation_run_hash: str,
    shared_findings: tuple[SharedFindingGroup, ...],
    role_specific_findings: tuple[RoleSpecificFinding, ...],
    direct_conflicts: tuple[DirectFindingConflict, ...],
    unresolved_trade_offs: tuple[str, ...],
    evidence_gaps: tuple[TwinEvidenceGap, ...],
    human_validation_questions: tuple[HumanValidationQuestion, ...],
) -> str:
    """Hash the complete deterministic aggregation projection."""
    return snapshot_content_hash(
        _aggregation_semantic_snapshot(
            evaluation_run_id=evaluation_run_id,
            evaluation_run_hash=evaluation_run_hash,
            shared_findings=shared_findings,
            role_specific_findings=role_specific_findings,
            direct_conflicts=direct_conflicts,
            unresolved_trade_offs=unresolved_trade_offs,
            evidence_gaps=evidence_gaps,
            human_validation_questions=human_validation_questions,
        )
    )


def _aggregation_semantic_snapshot(
    *,
    evaluation_run_id: UUID,
    evaluation_run_hash: str,
    shared_findings: tuple[SharedFindingGroup, ...],
    role_specific_findings: tuple[RoleSpecificFinding, ...],
    direct_conflicts: tuple[DirectFindingConflict, ...],
    unresolved_trade_offs: tuple[str, ...],
    evidence_gaps: tuple[TwinEvidenceGap, ...],
    human_validation_questions: tuple[HumanValidationQuestion, ...],
) -> dict[str, object]:
    return {
        "evaluation_run_id": str(evaluation_run_id),
        "evaluation_run_hash": evaluation_run_hash,
        "shared_findings": [item.to_snapshot() for item in shared_findings],
        "role_specific_findings": [item.to_snapshot() for item in role_specific_findings],
        "direct_conflicts": [item.to_snapshot() for item in direct_conflicts],
        "unresolved_trade_offs": list(unresolved_trade_offs),
        "evidence_gaps": [item.to_snapshot() for item in evidence_gaps],
        "human_validation_questions": [item.to_snapshot() for item in human_validation_questions],
        "aggregation_policy": "EXACT_MATCH_PLUS_EXPLICIT_CONFLICT_DECLARATIONS",
        "independent_human_sample_count": 0,
    }


def _human_validation_questions(
    findings: tuple[SyntheticFinding, ...],
    conflicts: tuple[DirectFindingConflict, ...],
) -> tuple[HumanValidationQuestion, ...]:
    questions: list[HumanValidationQuestion] = []
    conflicted_ids = {
        finding_id for conflict in conflicts for finding_id in conflict.declaration.finding_ids
    }
    for conflict in conflicts:
        questions.append(
            HumanValidationQuestion(
                question_id=f"HVQ-{snapshot_content_hash(conflict.to_snapshot())[:12]}",
                related_finding_ids=conflict.declaration.finding_ids,
                question=conflict.declaration.owner_decision_question,
            )
        )
    for finding in sorted(findings, key=_finding_sort_key):
        if not finding.requires_human_validation or finding.finding_id in conflicted_ids:
            continue
        questions.append(
            HumanValidationQuestion(
                question_id=f"HVQ-{finding.content_hash[:12]}",
                related_finding_ids=(finding.finding_id,),
                question=(
                    f"Validate with target users whether finding {finding.finding_id} "
                    f"affects the stated task: {finding.summary}"
                ),
            )
        )
    return tuple(sorted(questions, key=lambda item: item.sort_key))


def _shared_comparison_key(finding: SyntheticFinding) -> tuple[str, int, str, str, str]:
    return (
        finding.artifact_id.hex,
        finding.artifact_version,
        finding.location.casefold(),
        finding.criterion.value,
        finding.summary.casefold(),
    )


def _conflict_scope_key(finding: SyntheticFinding) -> tuple[str, int, str, str]:
    return (
        finding.artifact_id.hex,
        finding.artifact_version,
        finding.location.casefold(),
        finding.criterion.value,
    )


def _finding_sort_key(finding: SyntheticFinding) -> tuple[str, str, int]:
    return (finding.finding_id, finding.twin_id.hex, finding.twin_version)
