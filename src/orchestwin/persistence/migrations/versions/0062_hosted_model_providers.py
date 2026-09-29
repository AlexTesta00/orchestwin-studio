from importlib import import_module

revision = "0062_hosted_model_providers"
down_revision = "0061_project_imports"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

FUNCTION = "validate_model_proposal_event"
EVENT_CHANGES = (
    (
        "snapshot_json::jsonb->'payload'->>'provider_kind' = 'OPENAI_COMPATIBLE_LOCAL'",
        "snapshot_json::jsonb->'payload'->>'provider_kind' IN "
        "('OPENAI_COMPATIBLE_LOCAL', 'ANTHROPIC_HOSTED', 'OPENAI_COMPATIBLE_HOSTED')",
    ),
)


def upgrade():
    replace_function(FUNCTION, EVENT_CHANGES)


def downgrade():
    replace_function(FUNCTION, EVENT_CHANGES, reverse=True)
