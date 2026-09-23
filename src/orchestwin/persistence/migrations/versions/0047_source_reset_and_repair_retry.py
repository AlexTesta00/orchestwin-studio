from importlib import import_module

from alembic import op

revision = "0047_source_reset_and_repair_retry"
down_revision = "0046_source_state_declarations"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

ACCEPTANCE_CHANGES = (
    (
        r"""                        || string_agg('function ' || (part->>'name') || '(' || (part->>'parameters') || ') {' || E'\n' || (part->>'body') || E'\n}\n\n', '' ORDER BY n)
""",
        r"""                        || string_agg('function ' || (part->>'name') || '(' || (part->>'parameters') || ') {' || E'\n' || (part->>'body') || E'\n}\n\n', '' ORDER BY n)
                        || E'function resetSharedState() {\n' || COALESCE((SELECT string_agg(CASE
                            WHEN (declaration->>'kind') = 'let' THEN '  ' || (declaration->>'name') || ' = ' || (declaration->>'initializer') || E';\n'
                            WHEN (declaration->>'initializer') = '[]' THEN '  ' || (declaration->>'name') || E'.length = 0;\n'
                            WHEN (declaration->>'initializer') = '{}' THEN '  Object.keys(' || (declaration->>'name') || ').forEach(function (key) { delete ' || (declaration->>'name') || E'[key]; });\n'
                            WHEN (declaration->>'initializer') IN ('new Map()', 'new Set()') THEN '  ' || (declaration->>'name') || E'.clear();\n'
                            END, '' ORDER BY n)
                            FROM jsonb_array_elements(output->'shared_state') WITH ORDINALITY AS s(declaration, n)), '') || E'}\n\n'
""",
    ),
    (
        r"""                        || string_agg(part->>'name', ', ' ORDER BY n) || E' };\n}\n'
""",
        r"""                        || string_agg(part->>'name', ', ' ORDER BY n) || E', resetSharedState };\n}\n'
""",
    ),
)

RETRY_CHANGES = (
    (
        "            IF NOT (ctx ?| ARRAY['syntax_retry','design_retry']) THEN RETURN NEW; END IF;\n"
        "            IF ctx ?& ARRAY['syntax_retry','design_retry'] THEN\n",
        "            IF NOT (ctx ?| ARRAY['syntax_retry','design_retry','repair_retry']) THEN RETURN NEW; END IF;\n"
        "            IF (ctx ? 'syntax_retry')::int + (ctx ? 'design_retry')::int + (ctx ? 'repair_retry')::int > 1 THEN\n",
    ),
    (
        "            retry_key := CASE WHEN ctx ? 'design_retry' THEN 'design_retry' ELSE 'syntax_retry' END;\n",
        "            retry_key := CASE WHEN ctx ? 'design_retry' THEN 'design_retry'\n"
        "                WHEN ctx ? 'repair_retry' THEN 'repair_retry' ELSE 'syntax_retry' END;\n",
    ),
    (
        "                AND ctx ? 'source_step'\n"
        "                AND ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')\n"
        "                AND ctx->'target_selection'->>'target' = 'WEB_STATIC'\n"
        "                AND NEW.task_id = 'proposal-web-source-v1'\n",
        "                AND CASE WHEN retry_key = 'repair_retry'\n"
        "                    THEN NOT (ctx ? 'source_step') AND NEW.task_id = 'proposal-web-repair-v1'\n"
        "                    ELSE ctx ? 'source_step'\n"
        "                        AND ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')\n"
        "                        AND NEW.task_id = 'proposal-web-source-v1' END\n"
        "                AND ctx->'target_selection'->>'target' = 'WEB_STATIC'\n",
    ),
    (
        "                AND NOT (previous_context ?| ARRAY['syntax_retry','design_retry'])\n",
        "                AND NOT (previous_context ?| ARRAY['syntax_retry','design_retry','repair_retry'])\n",
    ),
    (
        "            IF retry_key = 'syntax_retry' THEN\n",
        "            IF retry_key IN ('syntax_retry', 'repair_retry') THEN\n",
    ),
)


def upgrade():
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES)
    replace_function("validate_source_syntax_retry", RETRY_CHANGES)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json) ? 'repair_retry')
               OR EXISTS (SELECT 1 FROM model_proposal_generation_events
                WHERE kind = 'ADAPTER_ACCEPTED'
                AND snapshot_json::jsonb->'payload'->'source_file'->>'content' LIKE '%function resetSharedState() {%') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source text assembled with the state reset or of repair retries';
            END IF;
        END $$;
    """)
    replace_function("validate_source_syntax_retry", RETRY_CHANGES, reverse=True)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES, reverse=True)
