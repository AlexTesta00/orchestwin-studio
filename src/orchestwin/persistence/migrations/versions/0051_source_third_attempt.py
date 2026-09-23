from importlib import import_module

revision = "0051_source_third_attempt"
down_revision = "0050_synthetic_finding_identity"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

RETRY_CHANGES = (
    (
        "                AND retry->'attempt' = '2'::jsonb\n",
        "                AND retry->'attempt' IN ('2'::jsonb, '3'::jsonb)\n",
    ),
    (
        "                AND NOT (previous_context ?| ARRAY['syntax_retry','design_retry','repair_retry'])\n"
        "                AND (ctx - retry_key) = previous_context\n",
        "                AND CASE WHEN retry->'attempt' = '2'::jsonb\n"
        "                    THEN NOT (previous_context ?| ARRAY['syntax_retry','design_retry','repair_retry'])\n"
        "                        AND (ctx - retry_key) = previous_context\n"
        "                    ELSE previous_context->retry_key->'attempt' = '2'::jsonb\n"
        "                        AND (ctx - retry_key) = (previous_context - retry_key) END\n",
    ),
)


def upgrade():
    replace_function("validate_source_syntax_retry", RETRY_CHANGES)


def downgrade():
    replace_function("validate_source_syntax_retry", RETRY_CHANGES, reverse=True)
