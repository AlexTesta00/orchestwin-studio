"""Bind generated source bytes to a complete set of audited file invocations."""

from alembic import op

revision = "0040_source_file_evidence"
down_revision = "0039_model_source_generation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(r"""
        CREATE FUNCTION model_source_context(snapshot text) RETURNS jsonb
        LANGUAGE sql IMMUTABLE STRICT AS $$
            SELECT (snapshot::jsonb->'request'->>'input_payload_json')::jsonb->'context'
        $$;
        CREATE UNIQUE INDEX uq_source_file_parent_ordinal ON model_proposal_generations
        ((model_source_context(snapshot_json)->'source_step'->>'parent_generation_id'),
         (model_source_context(snapshot_json)->'source_step'->>'ordinal'))
        WHERE model_source_context(snapshot_json) ? 'source_step';

        CREATE FUNCTION validate_source_file_request() RETURNS trigger AS $$
        DECLARE ctx jsonb; step jsonb; parent record; manifest_text text; ordinal integer;
        BEGIN
            ctx := model_source_context(NEW.snapshot_json);
            IF NOT (ctx ? 'source_step') THEN RETURN NEW; END IF;
            step := ctx->'source_step';
            ordinal := (step->>'ordinal')::integer;
            SELECT * INTO STRICT parent FROM model_proposal_generations
            WHERE id = (step->>'parent_generation_id')::uuid FOR UPDATE;
            SELECT snapshot_json::jsonb->'payload'->'success'->>'payload_json'
            INTO manifest_text FROM model_proposal_generation_events
            WHERE generation_id = parent.id AND kind = 'PROVIDER_RESULT';
            IF NOT COALESCE(
                ctx->>'generation_protocol' = 'SOURCE_FILES_V1'
                AND NEW.task_id IN ('proposal-web-source-v1','proposal-jvm-source-v1')
                AND NEW.task_id = parent.task_id
                AND NEW.project_id = parent.project_id AND NEW.owner_user_id = parent.owner_user_id
                AND step->>'parent_request_hash' = parent.request_content_hash
                AND model_source_context(parent.snapshot_json)->>'generation_protocol' = 'SOURCE_FILES_V1'
                AND NOT (model_source_context(parent.snapshot_json) ? 'source_step')
                AND NEW.snapshot_json::jsonb->'request'->'expected_identity' = parent.snapshot_json::jsonb->'request'->'expected_identity'
                AND ctx->'target_selection' = model_source_context(parent.snapshot_json)->'target_selection'
                AND ordinal BETWEEN 1 AND 8
                AND step->'file' = manifest_text::jsonb->'files'->(ordinal - 1)
                AND ctx->'manifest' = manifest_text::jsonb
                AND step->>'manifest_hash' = encode(sha256(convert_to(manifest_text,'UTF8')),'hex')
                AND NOT EXISTS (SELECT 1 FROM model_proposal_generation_events WHERE generation_id = parent.id AND kind IN ('APPLICATION_RESULT','ADAPTER_ACCEPTED','ADAPTER_REJECTED')),
                false) THEN RAISE EXCEPTION 'Source file request has no matching active manifest'; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_source_file_request BEFORE INSERT ON model_proposal_generations
        FOR EACH ROW EXECUTE FUNCTION validate_source_file_request();

        CREATE FUNCTION validate_source_file_acceptance() RETURNS trigger AS $$
        DECLARE generation record; ctx jsonb; accepted jsonb; output jsonb; planned jsonb;
                step jsonb; child record; child_context jsonb; child_file jsonb; content text;
                files jsonb; binding jsonb; digest text; entry jsonb; ordinal integer; completed jsonb;
        BEGIN
            SELECT * INTO STRICT generation FROM model_proposal_generations WHERE id=NEW.generation_id FOR UPDATE;
            ctx := model_source_context(generation.snapshot_json);
            IF ctx->>'generation_protocol' IS DISTINCT FROM 'SOURCE_FILES_V1' THEN RETURN NEW; END IF;
            SELECT (snapshot_json::jsonb->'payload'->'success'->>'payload_json')::jsonb INTO output
            FROM model_proposal_generation_events WHERE generation_id=generation.id AND kind='PROVIDER_RESULT';
            accepted := NEW.snapshot_json::jsonb->'payload';
            IF ctx ? 'source_step' THEN
                planned := ctx->'source_step'->'file';
                IF jsonb_typeof(output->'lines') IS DISTINCT FROM 'array'
                   OR jsonb_array_length(output->'lines') NOT BETWEEN 1 AND 60
                   OR EXISTS (SELECT 1 FROM jsonb_array_elements(output->'lines') AS l(value)
                     WHERE jsonb_typeof(value) <> 'string' OR length(value #>> '{}') > 240
                     OR (value #>> '{}') ~ E'[\\r\\n]') THEN
                    RAISE EXCEPTION 'Source file requires bounded individual lines';
                END IF;
                SELECT string_agg(value, E'\n' ORDER BY n) || E'\n' INTO content
                FROM jsonb_array_elements_text(output->'lines') WITH ORDINALITY AS l(value,n);
                IF accepted->'source_file' IS DISTINCT FROM jsonb_build_object(
                    'normalized_path',planned->>'normalized_path','media_type',planned->>'media_type','content',content) THEN
                    RAISE EXCEPTION 'Source file bytes differ from the provider lines';
                END IF;
                RETURN NEW;
            END IF;
            files := accepted->'result'->'output'->'files';
            binding := accepted->'source_binding';
            IF NOT COALESCE(jsonb_typeof(files)='array'
                AND jsonb_typeof(accepted->'result'->'generation_steps')='array'
                AND jsonb_array_length(files)=jsonb_array_length(output->'files')
                AND jsonb_array_length(files) BETWEEN 1 AND 8
                AND jsonb_array_length(files)=jsonb_array_length(accepted->'result'->'generation_steps')
                AND binding->'target_selection'=ctx->'target_selection'
                AND binding->'provenance_references'=ctx->'provenance_references'
                AND accepted->'result'->'output'->>'rationale'=output->>'rationale',false) THEN
                RAISE EXCEPTION 'Complete source file lineage required';
            END IF;
            completed := ctx->'fixed_files';
            FOR ordinal IN 1..jsonb_array_length(files) LOOP
                step := accepted->'result'->'generation_steps'->(ordinal-1);
                SELECT * INTO STRICT child FROM model_proposal_generations WHERE id=(step->>'generation_id')::uuid;
                child_context := model_source_context(child.snapshot_json);
                SELECT snapshot_json::jsonb->'payload'->'source_file' INTO child_file
                FROM model_proposal_generation_events WHERE generation_id=child.id AND kind='ADAPTER_ACCEPTED';
                IF NOT COALESCE(child.project_id=generation.project_id AND child.owner_user_id=generation.owner_user_id
                    AND child.task_id=generation.task_id AND step->>'request_hash'=child.request_content_hash
                    AND (step->>'ordinal')::integer=ordinal
                    AND child_context->'source_step'->>'parent_generation_id'=generation.id::text
                    AND (child_context->'source_step'->>'ordinal')::integer=ordinal
                    AND files->(ordinal-1)=child_file
                    AND EXISTS (SELECT 1 FROM model_proposal_generation_events WHERE generation_id=child.id
                        AND kind='APPLICATION_RESULT' AND snapshot_json::jsonb->'payload'->>'status'='SOURCE_FILE_GENERATED'),false) THEN
                    RAISE EXCEPTION 'Source manifest references a missing or different file invocation';
                END IF;
                content := child_file->>'content';
                digest := encode(sha256(convert_to(content,'UTF8')),'hex');
                entry := jsonb_build_object('normalized_path',child_file->>'normalized_path',
                    'sha256_digest',digest,'size_bytes',octet_length(convert_to(content,'UTF8')),
                    'storage_key','sha256/' || left(digest,2) || '/' || digest,'media_type',child_file->>'media_type');
                IF step->'file' IS DISTINCT FROM entry THEN RAISE EXCEPTION 'Source file digest mismatch'; END IF;
                IF generation.task_id='proposal-jvm-source-v1' THEN
                    entry := jsonb_set(entry,'{media_type}','"application/octet-stream"');
                END IF;
                completed := completed || jsonb_build_array(entry);
            END LOOP;
            IF NOT COALESCE(jsonb_array_length(binding->'files')=jsonb_array_length(completed)
                AND (binding->'files') @> completed AND completed @> (binding->'files'),false) THEN
                RAISE EXCEPTION 'Published binding does not preserve generated and pinned bytes';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_source_file_acceptance BEFORE INSERT ON model_proposal_generation_events
        FOR EACH ROW WHEN (NEW.kind='ADAPTER_ACCEPTED') EXECUTE FUNCTION validate_source_file_acceptance();
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM model_proposal_generations
                WHERE model_source_context(snapshot_json)->>'generation_protocol'='SOURCE_FILES_V1') THEN
                RAISE EXCEPTION 'Cannot remove protection of retained source file evidence';
            END IF;
        END $$;
        DROP TRIGGER model_source_file_acceptance ON model_proposal_generation_events;
        DROP FUNCTION validate_source_file_acceptance();
        DROP TRIGGER model_source_file_request ON model_proposal_generations;
        DROP FUNCTION validate_source_file_request();
        DROP INDEX uq_source_file_parent_ordinal;
        DROP FUNCTION model_source_context(text);
    """)
