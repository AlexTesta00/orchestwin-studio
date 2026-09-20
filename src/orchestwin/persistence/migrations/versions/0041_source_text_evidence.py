"""Preserve complete generated file text alongside historical line-array evidence."""

from alembic import op

revision = "0041_source_text_evidence"
down_revision = "0040_source_file_evidence"
branch_labels = None
depends_on = None

REQUEST_CHANGES = (
    (
        "ctx->>'generation_protocol' = 'SOURCE_FILES_V1'",
        "ctx->>'generation_protocol' IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT')",
    ),
    (
        "model_source_context(parent.snapshot_json)->>'generation_protocol' = 'SOURCE_FILES_V1'",
        "model_source_context(parent.snapshot_json)->>'generation_protocol' = ctx->>'generation_protocol'",
    ),
)
ACCEPTANCE_CHANGES = (
    (
        "IF ctx->>'generation_protocol' IS DISTINCT FROM 'SOURCE_FILES_V1' THEN RETURN NEW; END IF;",
        "IF COALESCE(ctx->>'generation_protocol','') NOT IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT') THEN RETURN NEW; END IF;",
    ),
    (
        "                IF jsonb_typeof(output->'lines') IS DISTINCT FROM 'array'",
        """                IF ctx->>'generation_protocol' = 'SOURCE_FILES_V2_TEXT' THEN
                    content := output->>'content';
                    IF jsonb_typeof(output->'content') IS DISTINCT FROM 'string'
                       OR (output - 'content') IS DISTINCT FROM '{}'::jsonb
                       OR octet_length(content) NOT BETWEEN 1 AND 32768
                       OR content ~ '[\x01-\x08\x0b-\x1f\x7f]' THEN
                        RAISE EXCEPTION 'Source file requires bounded complete UTF-8 text';
                    END IF;
                ELSE
                IF jsonb_typeof(output->'lines') IS DISTINCT FROM 'array'""",
    ),
    (
        "                IF accepted->'source_file' IS DISTINCT FROM jsonb_build_object(",
        """                END IF;
                IF accepted->'source_file' IS DISTINCT FROM jsonb_build_object(""",
    ),
)


def replace_function(name, changes, *, reverse=False):
    """Check and edit the predecessor in PostgreSQL, including offline SQL exports."""
    statements = [f"definition := pg_get_functiondef({_sql_string(name + '()')}::regprocedure);"]
    for before, after in changes:
        old, new = (after, before) if reverse else (before, after)
        old_sql, new_sql = _sql_string(old), _sql_string(new)
        statements.append(f"""
            IF (length(definition) - length(replace(definition, {old_sql}, '')))
                / length({old_sql}) <> 1 THEN
                RAISE EXCEPTION 'Unexpected source evidence guard definition';
            END IF;
            definition := replace(definition, {old_sql}, {new_sql});
        """)
    op.execute(
        "DO $source_evidence_guard$ DECLARE definition text; BEGIN\n"
        + "\n".join(statements)
        + "\nEXECUTE definition; END $source_evidence_guard$;"
    )


def _sql_string(value):
    return "'" + value.replace("'", "''") + "'"


def upgrade():
    replace_function("validate_source_file_request", REQUEST_CHANGES)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json)->>'generation_protocol'='SOURCE_FILES_V2_TEXT') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source text evidence';
            END IF;
        END $$;
    """)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES, reverse=True)
    replace_function("validate_source_file_request", REQUEST_CHANGES, reverse=True)
