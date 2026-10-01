from importlib import import_module

revision = "0067_claude_code_provider"
down_revision = "0066_twin_learning"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

FUNCTION = "validate_model_proposal_event"
EVENT_CHANGES = (
    (
        "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
        "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED')",
        "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
        "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED', "
        "'CLAUDE_CODE_CLI')",
    ),
)


def upgrade():
    replace_function(FUNCTION, EVENT_CHANGES)


def downgrade():
    replace_function(FUNCTION, EVENT_CHANGES, reverse=True)
