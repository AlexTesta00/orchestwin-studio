"""Deterministic mandatory and impossible agent-selection rules."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    AgentSelectionPolicy,
    all_agent_catalog_entries,
    catalog_entry,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBrief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)

_BRIEF_FIELD_ORDER: Final = tuple(BriefField)


def _ordered_fields(
    fields: Iterable[BriefField],
) -> tuple[BriefField, ...]:
    """Return unique fields in stable Project Brief order."""
    unique_fields = set(fields)

    return tuple(field for field in _BRIEF_FIELD_ORDER if field in unique_fields)


def _normalize_search_text(
    value: str,
) -> str:
    """Normalize text for deterministic phrase matching."""
    return " ".join(
        re.findall(
            r"[^\W_]+",
            value.casefold(),
        )
    )


def _normalized_terms(
    values: Iterable[str],
) -> tuple[str, ...]:
    """Normalize terms and order longer phrases before shorter ones."""
    normalized = {term for value in values if (term := _normalize_search_text(value))}

    return tuple(
        sorted(
            normalized,
            key=lambda term: (
                -len(term.split()),
                term,
            ),
        )
    )


class TeamRoleConstraintKind(StrEnum):
    """Deterministic participation constraints for one catalog role."""

    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"
    IMPOSSIBLE = "IMPOSSIBLE"
    CONFLICT = "CONFLICT"


class TeamSelectionReasonCode(StrEnum):
    """Stable explanations emitted by deterministic selection rules."""

    CATALOG_ALWAYS_PRESENT = "CATALOG_ALWAYS_PRESENT"
    CATALOG_MODE_INCOMPATIBLE = "CATALOG_MODE_INCOMPATIBLE"

    CORE_REQUIREMENTS_DISCIPLINE = "CORE_REQUIREMENTS_DISCIPLINE"
    CORE_USER_CENTERED_DESIGN = "CORE_USER_CENTERED_DESIGN"
    CORE_ARCHITECTURE_DISCIPLINE = "CORE_ARCHITECTURE_DISCIPLINE"
    CORE_QUALITY_DISCIPLINE = "CORE_QUALITY_DISCIPLINE"

    BROWNFIELD_INTEGRATION = "BROWNFIELD_INTEGRATION"

    USER_INTERFACE_SIGNAL = "USER_INTERFACE_SIGNAL"
    WEB_DELIVERY_SIGNAL = "WEB_DELIVERY_SIGNAL"
    BACKEND_DELIVERY_SIGNAL = "BACKEND_DELIVERY_SIGNAL"
    MOBILE_DELIVERY_SIGNAL = "MOBILE_DELIVERY_SIGNAL"
    EXTERNAL_INTEGRATION_SIGNAL = "EXTERNAL_INTEGRATION_SIGNAL"
    SECURITY_SENSITIVITY_SIGNAL = "SECURITY_SENSITIVITY_SIGNAL"
    ACCESSIBILITY_REQUIREMENT_SIGNAL = "ACCESSIBILITY_REQUIREMENT_SIGNAL"

    EXPLICIT_SCOPE_EXCLUSION = "EXPLICIT_SCOPE_EXCLUSION"


class TeamSelectionIssueCode(StrEnum):
    """Stable issues requiring owner clarification."""

    CONTRADICTORY_ROLE_SIGNALS = "CONTRADICTORY_ROLE_SIGNALS"


@dataclass(frozen=True, slots=True)
class RuleEvidence:
    """Brief fields and normalized terms that activated a rule."""

    fields: tuple[BriefField, ...] = ()
    terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect deterministic evidence ordering."""
        if bool(self.fields) != bool(self.terms):
            raise ValueError("rule evidence fields and terms must both be empty or populated")

        if self.fields != _ordered_fields(self.fields):
            raise ValueError("rule evidence fields must be unique and use Project Brief order")

        if self.terms != tuple(sorted(set(self.terms))):
            raise ValueError("rule evidence terms must be unique and lexicographically ordered")


@dataclass(frozen=True, slots=True)
class TeamSelectionReason:
    """One typed explanation for a role constraint."""

    code: TeamSelectionReasonCode
    evidence: RuleEvidence = RuleEvidence()


@dataclass(frozen=True, slots=True)
class TeamRoleConstraint:
    """Deterministic constraint for one fixed-catalog agent."""

    agent_id: AgentIdentifier
    kind: TeamRoleConstraintKind
    reasons: tuple[
        TeamSelectionReason,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect constraint and catalog invariants."""
        if self.kind is TeamRoleConstraintKind.OPTIONAL and self.reasons:
            raise ValueError("an optional role must not contain deterministic reasons")

        if self.kind is not TeamRoleConstraintKind.OPTIONAL and not self.reasons:
            raise ValueError("a constrained role requires at least one reason")

        if (
            catalog_entry(self.agent_id).is_always_present
            and self.kind is not TeamRoleConstraintKind.MANDATORY
        ):
            raise ValueError("an always-present catalog agent must remain mandatory")

    @property
    def owner_editable(self) -> bool:
        """Return whether the owner may add or remove this role."""
        return self.kind is TeamRoleConstraintKind.OPTIONAL


@dataclass(frozen=True, slots=True)
class TeamSelectionIssue:
    """One contradiction found by deterministic rules."""

    code: TeamSelectionIssueCode
    agent_id: AgentIdentifier
    mandatory_reasons: tuple[
        TeamSelectionReason,
        ...,
    ]
    impossible_reasons: tuple[
        TeamSelectionReason,
        ...,
    ]

    def __post_init__(self) -> None:
        """Require evidence for both sides of a conflict."""
        if not self.mandatory_reasons or not self.impossible_reasons:
            raise ValueError("a team-selection conflict requires mandatory and impossible reasons")


@dataclass(frozen=True, slots=True)
class DeterministicTeamConstraints:
    """Complete deterministic constraints for a project team."""

    catalog_version: int
    catalog_content_hash: str
    project_mode: ProjectMode
    role_constraints: tuple[
        TeamRoleConstraint,
        ...,
    ]
    issues: tuple[
        TeamSelectionIssue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect catalog coverage and conflict consistency."""
        if self.catalog_version != AGENT_CATALOG_VERSION:
            raise ValueError("team constraints must use the current catalog version")

        if self.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH:
            raise ValueError("team constraints must use the current catalog hash")

        expected_agent_ids = tuple(entry.agent_id for entry in all_agent_catalog_entries())
        actual_agent_ids = tuple(constraint.agent_id for constraint in self.role_constraints)

        if actual_agent_ids != expected_agent_ids:
            raise ValueError("team constraints must cover the complete catalog in order")

        conflicting_agent_ids = tuple(
            constraint.agent_id
            for constraint in self.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.CONFLICT)
        )
        issue_agent_ids = tuple(issue.agent_id for issue in self.issues)

        if conflicting_agent_ids != issue_agent_ids:
            raise ValueError("conflicting constraints and issues must reference the same agents")

    @property
    def mandatory_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return every role that must be present."""
        return tuple(
            constraint.agent_id
            for constraint in self.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.MANDATORY)
        )

    @property
    def optional_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return roles the owner may add or remove."""
        return tuple(
            constraint.agent_id
            for constraint in self.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.OPTIONAL)
        )

    @property
    def impossible_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return roles explicitly incompatible with the brief."""
        return tuple(
            constraint.agent_id
            for constraint in self.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.IMPOSSIBLE)
        )

    @property
    def conflicting_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return roles whose brief signals contradict one another."""
        return tuple(
            constraint.agent_id
            for constraint in self.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.CONFLICT)
        )

    @property
    def has_conflicts(self) -> bool:
        """Return whether owner clarification is required."""
        return bool(self.issues)

    def constraint_for(
        self,
        agent_id: AgentIdentifier,
    ) -> TeamRoleConstraint:
        """Return the deterministic constraint for one role."""
        for constraint in self.role_constraints:
            if constraint.agent_id is agent_id:
                return constraint

        raise KeyError(agent_id)

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable snapshot."""
        return {
            "catalog_version": (self.catalog_version),
            "catalog_content_hash": (self.catalog_content_hash),
            "project_mode": (self.project_mode.value),
            "role_constraints": [
                {
                    "agent_id": (constraint.agent_id.value),
                    "kind": (constraint.kind.value),
                    "owner_editable": (constraint.owner_editable),
                    "reasons": [
                        {
                            "code": reason.code.value,
                            "evidence": {
                                "fields": [field.value for field in reason.evidence.fields],
                                "terms": list(reason.evidence.terms),
                            },
                        }
                        for reason in constraint.reasons
                    ],
                }
                for constraint in self.role_constraints
            ],
            "issues": [
                {
                    "code": issue.code.value,
                    "agent_id": (issue.agent_id.value),
                }
                for issue in self.issues
            ],
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the constraints with deterministic ordering."""
        return json.dumps(
            self.to_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @property
    def content_hash(
        self,
    ) -> str:
        """Return the SHA-256 hash of the complete constraint set."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _RoleSignalRule:
    """Private deterministic marker rule for one specialist."""

    agent_id: AgentIdentifier
    positive_terms: tuple[
        str,
        ...,
    ]
    exclusion_terms: tuple[
        str,
        ...,
    ]
    mandatory_reason: TeamSelectionReasonCode

    def __post_init__(self) -> None:
        """Protect rule configuration."""
        entry = catalog_entry(self.agent_id)

        if entry.selection_policy is not AgentSelectionPolicy.OWNER_SELECTABLE:
            raise ValueError("signal rules may target only owner-selectable specialists")

        if not _normalized_terms(self.positive_terms):
            raise ValueError("a role signal rule requires positive terms")


_BASELINE_MANDATORY_REASONS: Final[
    tuple[
        tuple[
            AgentIdentifier,
            TeamSelectionReasonCode,
        ],
        ...,
    ]
] = (
    (
        AgentIdentifier.REQUIREMENTS_ANALYST,
        TeamSelectionReasonCode.CORE_REQUIREMENTS_DISCIPLINE,
    ),
    (
        AgentIdentifier.UX_RESEARCHER_USER_MODELER,
        TeamSelectionReasonCode.CORE_USER_CENTERED_DESIGN,
    ),
    (
        AgentIdentifier.SOFTWARE_ARCHITECT,
        TeamSelectionReasonCode.CORE_ARCHITECTURE_DISCIPLINE,
    ),
    (
        AgentIdentifier.QA_TEST_ENGINEER,
        TeamSelectionReasonCode.CORE_QUALITY_DISCIPLINE,
    ),
)


_USER_INTERFACE_MARKERS: Final = (
    "user interface",
    "graphical interface",
    "dashboard",
    "web application",
    "web app",
    "website",
    "browser interface",
    "mobile application",
    "mobile app",
    "android application",
    "ios application",
    "flutter application",
    "screen",
    "screens",
)


_WEB_MARKERS: Final = (
    "web application",
    "web app",
    "website",
    "browser",
    "frontend",
    "vue",
    "react",
    "angular",
    "html",
    "css",
    "vite",
    "pwa",
)


_BACKEND_MARKERS: Final = (
    "backend",
    "server",
    "api",
    "apis",
    "database",
    "postgresql",
    "postgres",
    "mysql",
    "sql",
    "authentication",
    "authorization",
    "login",
    "log in",
    "account",
    "persistence",
    "rest api",
    "graphql",
)


_MOBILE_MARKERS: Final = (
    "mobile",
    "android",
    "ios",
    "flutter",
    "kotlin",
    "swift",
    "jetpack compose",
    "react native",
)


_INTEGRATION_MARKERS: Final = (
    "external api",
    "external apis",
    "third party",
    "webhook",
    "integration",
    "integrations",
    "provider",
    "oauth",
    "payment gateway",
    "data synchronization",
    "synchronization",
    "sync",
)


_SECURITY_MARKERS: Final = (
    "authentication",
    "authorization",
    "login",
    "log in",
    "password",
    "token",
    "secret",
    "personal data",
    "sensitive data",
    "privacy",
    "security",
    "encryption",
    "permission",
    "permissions",
    "payment",
)


_ACCESSIBILITY_MARKERS: Final = (
    "accessibility",
    "wcag",
    "screen reader",
    "keyboard navigation",
    "assistive technology",
    "high contrast",
    "color contrast",
)


_NO_USER_INTERFACE_MARKERS: Final = (
    "headless",
    "api only",
    "backend only",
    "no user interface",
    "without user interface",
    "no gui",
    "without gui",
)


_NO_FRONTEND_MARKERS: Final = (
    "no frontend",
    "without frontend",
    "api only",
    "backend only",
    "headless",
    "command line only",
    "cli only",
    "mobile only",
)


_NO_BACKEND_MARKERS: Final = (
    "no backend",
    "without backend",
    "frontend only",
    "client only",
    "static site only",
    "static website only",
    "no server",
    "without server",
)


_NO_MOBILE_MARKERS: Final = (
    "no mobile",
    "without mobile",
    "web only",
    "browser only",
    "desktop only",
)


_NO_INTEGRATION_MARKERS: Final = (
    "no integrations",
    "without integrations",
    "no external integrations",
    "no external api",
    "no external apis",
    "without external api",
    "without external apis",
    "no third party services",
    "without third party services",
)


_SIGNAL_RULES: Final[
    tuple[
        _RoleSignalRule,
        ...,
    ]
] = (
    _RoleSignalRule(
        agent_id=(AgentIdentifier.UX_UI_DESIGNER),
        positive_terms=(_USER_INTERFACE_MARKERS),
        exclusion_terms=(_NO_USER_INTERFACE_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.USER_INTERFACE_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.FRONTEND_ENGINEER),
        positive_terms=(_WEB_MARKERS),
        exclusion_terms=(_NO_FRONTEND_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.WEB_DELIVERY_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.BACKEND_ENGINEER),
        positive_terms=(_BACKEND_MARKERS),
        exclusion_terms=(_NO_BACKEND_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.BACKEND_DELIVERY_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.MOBILE_ENGINEER),
        positive_terms=(_MOBILE_MARKERS),
        exclusion_terms=(_NO_MOBILE_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.MOBILE_DELIVERY_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.SECURITY_REVIEWER),
        positive_terms=(_SECURITY_MARKERS),
        exclusion_terms=(),
        mandatory_reason=(TeamSelectionReasonCode.SECURITY_SENSITIVITY_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.ACCESSIBILITY_REVIEWER),
        positive_terms=(_ACCESSIBILITY_MARKERS),
        exclusion_terms=(_NO_USER_INTERFACE_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.ACCESSIBILITY_REQUIREMENT_SIGNAL),
    ),
    _RoleSignalRule(
        agent_id=(AgentIdentifier.INTEGRATION_ENGINEER),
        positive_terms=(_INTEGRATION_MARKERS),
        exclusion_terms=(_NO_INTEGRATION_MARKERS),
        mandatory_reason=(TeamSelectionReasonCode.EXTERNAL_INTEGRATION_SIGNAL),
    ),
)


def _provided_evidence(
    brief: ProjectBrief,
) -> tuple[
    tuple[
        BriefField,
        str,
    ],
    ...,
]:
    """Return normalized owner-provided values with field provenance."""
    values: list[
        tuple[
            BriefField,
            str,
        ]
    ] = []

    for field in BriefField:
        value = brief.value_for(field)

        if isinstance(
            value,
            str,
        ):
            normalized = _normalize_search_text(value)

            if normalized:
                values.append(
                    (
                        field,
                        normalized,
                    )
                )

            continue

        if isinstance(
            value,
            tuple,
        ):
            for item in value:
                normalized = _normalize_search_text(item)

                if normalized:
                    values.append(
                        (
                            field,
                            normalized,
                        )
                    )

    return tuple(values)


def _remove_phrases(
    value: str,
    phrases: tuple[str, ...],
) -> str:
    """Remove explicit exclusion phrases before positive matching."""
    searchable = f" {value} "

    for phrase in phrases:
        searchable = searchable.replace(
            f" {phrase} ",
            " ",
        )

    return " ".join(searchable.split())


def _contains_phrase(
    value: str,
    phrase: str,
) -> bool:
    """Match one normalized phrase using token boundaries."""
    return f" {phrase} " in f" {value} "


def _match_terms(
    evidence_values: tuple[
        tuple[
            BriefField,
            str,
        ],
        ...,
    ],
    terms: Iterable[str],
    *,
    ignored_phrases: Iterable[str] = (),
) -> RuleEvidence:
    """Return fields and markers matching a deterministic rule."""
    normalized_terms = _normalized_terms(terms)
    normalized_ignored = _normalized_terms(ignored_phrases)

    matched_fields: set[BriefField] = set()
    matched_terms: set[str] = set()

    for (
        field,
        value,
    ) in evidence_values:
        searchable = _remove_phrases(
            value,
            normalized_ignored,
        )

        for term in normalized_terms:
            if _contains_phrase(
                searchable,
                term,
            ):
                matched_fields.add(field)
                matched_terms.add(term)

    return RuleEvidence(
        fields=_ordered_fields(matched_fields),
        terms=tuple(sorted(matched_terms)),
    )


def _baseline_reason_code(
    agent_id: AgentIdentifier,
) -> TeamSelectionReasonCode | None:
    """Return the baseline reason for one specialist."""
    for (
        candidate_agent_id,
        reason_code,
    ) in _BASELINE_MANDATORY_REASONS:
        if candidate_agent_id is agent_id:
            return reason_code

    return None


def _signal_rule(
    agent_id: AgentIdentifier,
) -> _RoleSignalRule | None:
    """Return the signal rule configured for one specialist."""
    for rule in _SIGNAL_RULES:
        if rule.agent_id is agent_id:
            return rule

    return None


def _reason(
    code: TeamSelectionReasonCode,
    evidence: RuleEvidence | None = None,
) -> TeamSelectionReason:
    """Create one immutable deterministic reason."""
    resolved_evidence = evidence if evidence is not None else RuleEvidence()

    return TeamSelectionReason(
        code=code,
        evidence=resolved_evidence,
    )


def determine_team_constraints(
    *,
    project_mode: ProjectMode,
    brief: ProjectBrief,
) -> DeterministicTeamConstraints:
    """Evaluate deterministic team constraints for one Project Brief."""
    evidence_values = _provided_evidence(brief)

    constraints: list[TeamRoleConstraint] = []
    issues: list[TeamSelectionIssue] = []

    for entry in all_agent_catalog_entries():
        mandatory_reasons: list[TeamSelectionReason] = []
        impossible_reasons: list[TeamSelectionReason] = []

        if entry.is_always_present:
            mandatory_reasons.append(_reason(TeamSelectionReasonCode.CATALOG_ALWAYS_PRESENT))

        if project_mode not in entry.supported_project_modes:
            impossible_reasons.append(_reason(TeamSelectionReasonCode.CATALOG_MODE_INCOMPATIBLE))

        baseline_reason = _baseline_reason_code(entry.agent_id)

        if baseline_reason is not None:
            mandatory_reasons.append(_reason(baseline_reason))

        brownfield_integration = (
            project_mode is ProjectMode.BROWNFIELD_ASSESSMENT
            and entry.agent_id is AgentIdentifier.INTEGRATION_ENGINEER
        )

        if brownfield_integration:
            mandatory_reasons.append(_reason(TeamSelectionReasonCode.BROWNFIELD_INTEGRATION))

        rule = _signal_rule(entry.agent_id)

        if rule is not None:
            exclusion_evidence = _match_terms(
                evidence_values,
                rule.exclusion_terms,
            )
            positive_evidence = _match_terms(
                evidence_values,
                rule.positive_terms,
                ignored_phrases=(rule.exclusion_terms),
            )

            if positive_evidence.fields:
                mandatory_reasons.append(
                    _reason(
                        rule.mandatory_reason,
                        positive_evidence,
                    )
                )

            if exclusion_evidence.fields and not brownfield_integration:
                impossible_reasons.append(
                    _reason(
                        TeamSelectionReasonCode.EXPLICIT_SCOPE_EXCLUSION,
                        exclusion_evidence,
                    )
                )

        if mandatory_reasons and impossible_reasons:
            constraint = TeamRoleConstraint(
                agent_id=entry.agent_id,
                kind=(TeamRoleConstraintKind.CONFLICT),
                reasons=(
                    *mandatory_reasons,
                    *impossible_reasons,
                ),
            )
            issue = TeamSelectionIssue(
                code=(TeamSelectionIssueCode.CONTRADICTORY_ROLE_SIGNALS),
                agent_id=entry.agent_id,
                mandatory_reasons=tuple(mandatory_reasons),
                impossible_reasons=tuple(impossible_reasons),
            )

            constraints.append(constraint)
            issues.append(issue)
            continue

        if mandatory_reasons:
            constraints.append(
                TeamRoleConstraint(
                    agent_id=entry.agent_id,
                    kind=(TeamRoleConstraintKind.MANDATORY),
                    reasons=tuple(mandatory_reasons),
                )
            )
            continue

        if impossible_reasons:
            constraints.append(
                TeamRoleConstraint(
                    agent_id=entry.agent_id,
                    kind=(TeamRoleConstraintKind.IMPOSSIBLE),
                    reasons=tuple(impossible_reasons),
                )
            )
            continue

        constraints.append(
            TeamRoleConstraint(
                agent_id=entry.agent_id,
                kind=(TeamRoleConstraintKind.OPTIONAL),
            )
        )

    return DeterministicTeamConstraints(
        catalog_version=(AGENT_CATALOG_VERSION),
        catalog_content_hash=(AGENT_CATALOG_CONTENT_HASH),
        project_mode=project_mode,
        role_constraints=tuple(constraints),
        issues=tuple(issues),
    )
