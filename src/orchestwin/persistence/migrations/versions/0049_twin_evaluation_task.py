from alembic import op

revision = "0049_twin_evaluation_task"
down_revision = "0048_twin_conversations"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
KNOWN_TASKS = (
    "'proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1',"
    "'proposal-design-v1','proposal-architecture-v1','proposal-web-source-v1','proposal-web-repair-v1',"
    "'proposal-jvm-source-v1','proposal-jvm-repair-v1','proposal-twin-chat-v1'"
)
EVALUATION_TASK = "'proposal-user-twin-evaluation-v1'"


def _replace(table, name, expression):
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(name, table, f"COALESCE(({expression}), false)")


def upgrade():
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS},{EVALUATION_TASK})")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE task_id = 'proposal-user-twin-evaluation-v1') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained User Twin evaluation generations';
            END IF;
        END $$;
    """)
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS})")
