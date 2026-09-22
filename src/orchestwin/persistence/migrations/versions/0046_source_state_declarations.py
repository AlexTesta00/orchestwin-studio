from importlib import import_module

from alembic import op

revision = "0046_source_state_declarations"
down_revision = "0045_source_module_parts"
branch_labels = None
depends_on = None

replace_function = import_module(
    "orchestwin.persistence.migrations.versions.0041_source_text_evidence"
).replace_function

ACCEPTANCE_CHANGES = (
    (
        "                       OR jsonb_typeof(output->'shared_state') IS DISTINCT FROM 'string'\n",
        "                       OR jsonb_typeof(output->'shared_state') IS DISTINCT FROM 'array'\n",
    ),
    (
        "                        (output->>'browser_setup') <> ''\n",
        r"""                        (output->>'browser_setup') <> ''
                        AND jsonb_array_length(output->'shared_state') BETWEEN 0 AND 8
                        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(output->'shared_state') AS s(declaration)
                            WHERE jsonb_typeof(declaration) IS DISTINCT FROM 'object'
                            OR CASE WHEN jsonb_typeof(declaration) = 'object'
                                THEN (declaration - ARRAY['kind','name','initializer']) IS DISTINCT FROM '{}'::jsonb
                                ELSE true END
                            OR ((declaration->>'kind') IS DISTINCT FROM 'const' AND (declaration->>'kind') IS DISTINCT FROM 'let')
                            OR jsonb_typeof(declaration->'name') IS DISTINCT FROM 'string'
                            OR jsonb_typeof(declaration->'initializer') IS DISTINCT FROM 'string'
                            OR (declaration->>'name') !~ '^[A-Za-z_$][A-Za-z0-9_$]*$'
                            OR (declaration->>'initializer') !~ '^(\[\]|\{\}|new Map\(\)|new Set\(\)|null|true|false|-?[0-9]+(\.[0-9]+)?|''[^''\\\x01-\x1f\x7f]*'')$')
"""
        + "\n",
    ),
    (
        r"                    SELECT CASE WHEN output->>'shared_state' = '' THEN '' ELSE (output->>'shared_state') || E'\n\n' END"
        + "\n",
        r"""                    SELECT CASE WHEN jsonb_array_length(output->'shared_state') = 0 THEN ''
                        ELSE (SELECT string_agg((declaration->>'kind') || ' ' || (declaration->>'name') || ' = ' || (declaration->>'initializer') || ';', E'\n' ORDER BY n)
                            FROM jsonb_array_elements(output->'shared_state') WITH ORDINALITY AS s(declaration, n)) || E'\n\n' END"""
        + "\n",
    ),
)


def upgrade():
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json)->>'generation_protocol'='SOURCE_FILES_V3_PARTS') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source text assembled from state declarations';
            END IF;
        END $$;
    """)
    replace_function("validate_source_file_acceptance", ACCEPTANCE_CHANGES, reverse=True)
