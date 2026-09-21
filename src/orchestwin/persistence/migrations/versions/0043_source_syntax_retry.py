"""Permit one audited static source retry after a retained syntax rejection."""

from alembic import op

revision = "0043_source_syntax_retry"
down_revision = "0042_web_source_owner_edits"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DROP INDEX uq_source_file_parent_ordinal;
        CREATE UNIQUE INDEX uq_source_file_parent_ordinal ON model_proposal_generations
        ((model_source_context(snapshot_json)->'source_step'->>'parent_generation_id'),
         (model_source_context(snapshot_json)->'source_step'->>'ordinal'),
         (COALESCE(model_source_context(snapshot_json)->'syntax_retry'->>'attempt','1')))
        WHERE model_source_context(snapshot_json) ? 'source_step';

        CREATE FUNCTION validate_source_syntax_retry() RETURNS trigger AS $$
        DECLARE ctx jsonb; retry jsonb; previous record; previous_context jsonb;
        BEGIN
            ctx := model_source_context(NEW.snapshot_json);
            IF NOT (ctx ? 'syntax_retry') THEN RETURN NEW; END IF;
            retry := ctx->'syntax_retry';
            SELECT * INTO STRICT previous FROM model_proposal_generations
            WHERE id = (retry->>'previous_generation_id')::uuid FOR UPDATE;
            previous_context := model_source_context(previous.snapshot_json);
            IF NOT COALESCE(
                jsonb_typeof(retry) = 'object'
                AND (retry - ARRAY['attempt','previous_generation_id','previous_request_hash','code']) = '{}'::jsonb
                AND retry->'attempt' = '2'::jsonb
                AND retry->>'code' = 'SOURCE_JAVASCRIPT_SYNTAX_INVALID'
                AND ctx ? 'source_step'
                AND ctx->>'generation_protocol' = 'SOURCE_FILES_V2_TEXT'
                AND ctx->'target_selection'->>'target' = 'WEB_STATIC'
                AND NEW.task_id = 'proposal-web-source-v1'
                AND previous.task_id = NEW.task_id
                AND previous.project_id = NEW.project_id
                AND previous.owner_user_id = NEW.owner_user_id
                AND retry->>'previous_request_hash' = previous.request_content_hash
                AND NOT (previous_context ? 'syntax_retry')
                AND (ctx - 'syntax_retry') = previous_context
                AND EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'ADAPTER_REJECTED'
                    AND snapshot_json::jsonb->'payload'->>'code' = 'SOURCE_JAVASCRIPT_SYNTAX_INVALID')
                AND EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'APPLICATION_RESULT'
                    AND snapshot_json::jsonb->'payload'->>'status' = 'FAILED'
                    AND snapshot_json::jsonb->'payload'->>'code' = 'SOURCE_JAVASCRIPT_SYNTAX_INVALID')
                AND NOT EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'ADAPTER_ACCEPTED'),
                false) THEN RAISE EXCEPTION 'Source syntax retry requires an exact rejected first attempt'; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_source_syntax_retry BEFORE INSERT ON model_proposal_generations
        FOR EACH ROW EXECUTE FUNCTION validate_source_syntax_retry();
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json) ? 'syntax_retry') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source syntax retries';
            END IF;
        END $$;
        DROP TRIGGER model_source_syntax_retry ON model_proposal_generations;
        DROP FUNCTION validate_source_syntax_retry();
        DROP INDEX uq_source_file_parent_ordinal;
        CREATE UNIQUE INDEX uq_source_file_parent_ordinal ON model_proposal_generations
        ((model_source_context(snapshot_json)->'source_step'->>'parent_generation_id'),
         (model_source_context(snapshot_json)->'source_step'->>'ordinal'))
        WHERE model_source_context(snapshot_json) ? 'source_step';
    """)
