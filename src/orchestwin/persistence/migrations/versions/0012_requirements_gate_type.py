from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_requirements_gate_type"
down_revision: str | None = "0011_requirements_specifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GATE_TABLE = "human_gates"
_EVENT_TABLE = "human_gate_events"
_GATE_CONSTRAINT = "ck_human_gates_gate_type_valid"
_EVENT_CONSTRAINT = "ck_human_gate_events_gate_type_valid"

_PREVIOUS_GATE_TYPES = (
    "PROJECT_BRIEF",
    "AGENT_TEAM",
    "USER_MODELING",
)
_REQUIREMENTS_GATE_TYPES = (
    *_PREVIOUS_GATE_TYPES,
    "REQUIREMENTS",
)


def upgrade() -> None:
    """Extend persisted human-gate types with Gate 4."""
    _replace_gate_type_constraints(_REQUIREMENTS_GATE_TYPES)


def downgrade() -> None:
    """Remove Gate 4 while preserving the first three human gates."""
    _replace_gate_type_constraints(_PREVIOUS_GATE_TYPES)


def _replace_gate_type_constraints(
    gate_types: tuple[str, ...],
) -> None:
    """Replace both gate-state and gate-event type constraints."""
    op.drop_constraint(
        _EVENT_CONSTRAINT,
        _EVENT_TABLE,
        type_="check",
    )
    op.drop_constraint(
        _GATE_CONSTRAINT,
        _GATE_TABLE,
        type_="check",
    )

    expression = _gate_type_expression(gate_types)

    op.create_check_constraint(
        _GATE_CONSTRAINT,
        _GATE_TABLE,
        expression,
    )
    op.create_check_constraint(
        _EVENT_CONSTRAINT,
        _EVENT_TABLE,
        expression,
    )


def _gate_type_expression(
    gate_types: tuple[str, ...],
) -> str:
    """Return one deterministic SQL IN expression."""
    values = ", ".join(f"'{gate_type}'" for gate_type in gate_types)

    return f"gate_type IN ({values})"
