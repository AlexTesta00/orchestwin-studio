"""Bind one HTML design retry to retained bytes and its rejected first attempt."""

from importlib import import_module

from alembic import op

revision = "0044_source_design_retry"
down_revision = "0043_source_syntax_retry"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DROP INDEX uq_source_file_parent_ordinal;
        CREATE UNIQUE INDEX uq_source_file_parent_ordinal ON model_proposal_generations
        ((model_source_context(snapshot_json)->'source_step'->>'parent_generation_id'),
         (model_source_context(snapshot_json)->'source_step'->>'ordinal'),
         (COALESCE(model_source_context(snapshot_json)->'syntax_retry'->>'attempt',
                   model_source_context(snapshot_json)->'design_retry'->>'attempt','1')))
        WHERE model_source_context(snapshot_json) ? 'source_step';

        CREATE OR REPLACE FUNCTION validate_source_syntax_retry() RETURNS trigger AS $$
        DECLARE ctx jsonb; retry jsonb; retry_key text; previous record;
                previous_context jsonb; previous_content text; rejection jsonb;
        BEGIN
            ctx := model_source_context(NEW.snapshot_json);
            IF NOT (ctx ?| ARRAY['syntax_retry','design_retry']) THEN RETURN NEW; END IF;
            IF ctx ?& ARRAY['syntax_retry','design_retry'] THEN
                RAISE EXCEPTION 'Only one source retry category is allowed';
            END IF;
            retry_key := CASE WHEN ctx ? 'design_retry' THEN 'design_retry' ELSE 'syntax_retry' END;
            retry := ctx->retry_key;
            SELECT * INTO STRICT previous FROM model_proposal_generations
            WHERE id = (retry->>'previous_generation_id')::uuid FOR UPDATE;
            previous_context := model_source_context(previous.snapshot_json);
            SELECT snapshot_json::jsonb->'payload' INTO rejection
                FROM model_proposal_generation_events
                WHERE generation_id = previous.id AND kind = 'ADAPTER_REJECTED';
            IF NOT COALESCE(
                jsonb_typeof(retry) = 'object'
                AND retry->'attempt' = '2'::jsonb
                AND ctx ? 'source_step'
                AND ctx->>'generation_protocol' = 'SOURCE_FILES_V2_TEXT'
                AND ctx->'target_selection'->>'target' = 'WEB_STATIC'
                AND NEW.task_id = 'proposal-web-source-v1'
                AND previous.task_id = NEW.task_id
                AND previous.project_id = NEW.project_id
                AND previous.owner_user_id = NEW.owner_user_id
                AND retry->>'previous_request_hash' = previous.request_content_hash
                AND NOT (previous_context ?| ARRAY['syntax_retry','design_retry'])
                AND (ctx - retry_key) = previous_context
                AND rejection->>'code' = retry->>'code'
                AND EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'APPLICATION_RESULT'
                    AND snapshot_json::jsonb->'payload'->>'status' = 'FAILED'
                    AND snapshot_json::jsonb->'payload'->>'code' = retry->>'code')
                AND NOT EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'ADAPTER_ACCEPTED'),
                false) THEN RAISE EXCEPTION 'Source retry requires an exact rejected first attempt'; END IF;
            IF retry_key = 'syntax_retry' THEN
                IF NOT COALESCE(
                    (retry - ARRAY['attempt','previous_generation_id','previous_request_hash','code']) = '{}'::jsonb
                    AND retry->>'code' = 'SOURCE_JAVASCRIPT_SYNTAX_INVALID', false) THEN
                    RAISE EXCEPTION 'Invalid source syntax retry';
                END IF;
            ELSE
                SELECT (snapshot_json::jsonb->'payload'->'success'->>'payload_json')::jsonb->>'content'
                    INTO previous_content FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'PROVIDER_RESULT';
                IF NOT COALESCE(
                    (retry - ARRAY['attempt','previous_generation_id','previous_request_hash','code','previous_source_sha256','feedback']) = '{}'::jsonb
                    AND retry->>'code' = 'SOURCE_DESIGN_STRUCTURE_MISMATCH'
                    AND ctx->'source_step'->'file'->>'normalized_path' = 'index.html'
                    AND jsonb_typeof(retry->'feedback') = 'object'
                    AND retry->'feedback' = rejection->'design_feedback'
                    AND retry->'feedback'->>'normalized_path' = 'index.html'
                    AND retry->'feedback'->>'previous_source_sha256' = retry->>'previous_source_sha256'
                    AND retry->>'previous_source_sha256' = encode(sha256(convert_to(previous_content,'UTF8')),'hex'),
                    false) THEN RAISE EXCEPTION 'HTML design retry requires exact rejected bytes and feedback'; END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json) ? 'design_retry') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source design retries';
            END IF;
        END $$;
        DROP TRIGGER model_source_syntax_retry ON model_proposal_generations;
        DROP FUNCTION validate_source_syntax_retry();
    """)
    # Restore the exact previous index/function/trigger, including retained syntax retries.
    import_module("orchestwin.persistence.migrations.versions.0043_source_syntax_retry").upgrade()
