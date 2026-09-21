from importlib import import_module

from alembic import op

revision = "0045_source_module_parts"
down_revision = "0044_source_design_retry"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

PARTS_BRANCH = """                IF ctx->>'generation_protocol' = 'SOURCE_FILES_V3_PARTS' AND planned->>'normalized_path' = 'app.js' THEN
                    IF jsonb_typeof(output->'functions') IS DISTINCT FROM 'array'
                       OR (output - ARRAY['shared_state','private_helpers','functions','browser_setup']) IS DISTINCT FROM '{}'::jsonb
                       OR jsonb_typeof(output->'shared_state') IS DISTINCT FROM 'string'
                       OR jsonb_typeof(output->'private_helpers') IS DISTINCT FROM 'string'
                       OR jsonb_typeof(output->'browser_setup') IS DISTINCT FROM 'string' THEN
                        RAISE EXCEPTION 'Source file requires bounded module parts';
                    END IF;
                    IF NOT COALESCE(
                        (output->>'browser_setup') <> ''
                        AND jsonb_array_length(output->'functions') BETWEEN 1 AND 12
                        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(output->'functions') AS f(part)
                            WHERE jsonb_typeof(part) IS DISTINCT FROM 'object'
                            OR CASE WHEN jsonb_typeof(part) = 'object'
                                THEN (part - ARRAY['name','parameters','body']) IS DISTINCT FROM '{}'::jsonb
                                ELSE true END
                            OR jsonb_typeof(part->'name') IS DISTINCT FROM 'string'
                            OR jsonb_typeof(part->'parameters') IS DISTINCT FROM 'string'
                            OR jsonb_typeof(part->'body') IS DISTINCT FROM 'string'
                            OR (part->>'name') !~ '^[A-Za-z_$][A-Za-z0-9_$]*$'
                            OR (part->>'parameters') ~ '[\x01-\x1f\x7f(){};:]'
                            OR (part->>'body') = '')
                        AND (SELECT count(DISTINCT part->>'name') = count(*)
                            FROM jsonb_array_elements(output->'functions') AS f(part)), false) THEN
                        RAISE EXCEPTION 'Source file requires bounded module parts';
                    END IF;
                    SELECT CASE WHEN output->>'shared_state' = '' THEN '' ELSE (output->>'shared_state') || E'\\n\\n' END
                        || CASE WHEN output->>'private_helpers' = '' THEN '' ELSE (output->>'private_helpers') || E'\\n\\n' END
                        || string_agg('function ' || (part->>'name') || '(' || (part->>'parameters') || ') {' || E'\\n' || (part->>'body') || E'\\n}\\n\\n', '' ORDER BY n)
                        || E'if (typeof document !== ''undefined'') {\\n  document.addEventListener(''DOMContentLoaded'', function () {\\n'
                        || (output->>'browser_setup') || E'\\n  });\\n}\\n\\n'
                        || E'if (typeof module !== ''undefined'') {\\n  module.exports = { '
                        || string_agg(part->>'name', ', ' ORDER BY n) || E' };\\n}\\n'
                    INTO content FROM jsonb_array_elements(output->'functions') WITH ORDINALITY AS f(part, n);
                    IF octet_length(content) NOT BETWEEN 1 AND 32768
                       OR content ~ '[\x01-\x08\x0b-\x1f\x7f]' THEN
                        RAISE EXCEPTION 'Source file requires bounded complete UTF-8 text';
                    END IF;
"""

REQUEST_CHANGES = (
    (
        "ctx->>'generation_protocol' IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT')",
        "ctx->>'generation_protocol' IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')",
    ),
)
ACCEPTANCE_CHANGES = (
    (
        "IF COALESCE(ctx->>'generation_protocol','') NOT IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT') THEN RETURN NEW; END IF;",
        "IF COALESCE(ctx->>'generation_protocol','') NOT IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS') THEN RETURN NEW; END IF;",
    ),
    (
        "                IF ctx->>'generation_protocol' = 'SOURCE_FILES_V2_TEXT' THEN\n",
        PARTS_BRANCH
        + "                ELSIF ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS') THEN\n",
    ),
)
RETRY_CHANGES = (
    (
        "                AND ctx->>'generation_protocol' = 'SOURCE_FILES_V2_TEXT'\n",
        "                AND ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')\n",
    ),
)


def upgrade():
    replace_function("validate_source_file_request", REQUEST_CHANGES)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES)
    replace_function("validate_source_syntax_retry", RETRY_CHANGES)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json)->>'generation_protocol'='SOURCE_FILES_V3_PARTS') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source text assembled from module parts';
            END IF;
        END $$;
    """)
    replace_function("validate_source_syntax_retry", RETRY_CHANGES, reverse=True)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES, reverse=True)
    replace_function("validate_source_file_request", REQUEST_CHANGES, reverse=True)
