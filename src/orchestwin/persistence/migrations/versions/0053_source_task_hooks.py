from alembic import op

revision = "0053_source_task_hooks"
down_revision = "0052_design_first_scope"
branch_labels = None
depends_on = None

INDEX = "uq_source_file_parent_ordinal"
TRIGGERS = (
    ("model_proposal_generations", "model_source_file_request"),
    ("model_proposal_generations", "model_source_syntax_retry"),
    ("model_proposal_generation_events", "model_source_file_acceptance"),
    ("model_proposal_artifact_links", "model_source_artifact_exact"),
)
FUNCTIONS = (
    "validate_source_file_request",
    "validate_source_syntax_retry",
    "validate_source_file_acceptance",
    "validate_model_source_link",
)
RESTORE_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION validate_source_file_request()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
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
                ctx->>'generation_protocol' IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')
                AND NEW.task_id IN ('proposal-web-source-v1','proposal-jvm-source-v1')
                AND NEW.task_id = parent.task_id
                AND NEW.project_id = parent.project_id AND NEW.owner_user_id = parent.owner_user_id
                AND step->>'parent_request_hash' = parent.request_content_hash
                AND model_source_context(parent.snapshot_json)->>'generation_protocol' = ctx->>'generation_protocol'
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
        $function$;
CREATE OR REPLACE FUNCTION validate_source_syntax_retry()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        DECLARE ctx jsonb; retry jsonb; retry_key text; previous record;
                previous_context jsonb; previous_content text; rejection jsonb;
        BEGIN
            ctx := model_source_context(NEW.snapshot_json);
            IF NOT (ctx ?| ARRAY['syntax_retry','design_retry','repair_retry']) THEN RETURN NEW; END IF;
            IF (ctx ? 'syntax_retry')::int + (ctx ? 'design_retry')::int + (ctx ? 'repair_retry')::int > 1 THEN
                RAISE EXCEPTION 'Only one source retry category is allowed';
            END IF;
            retry_key := CASE WHEN ctx ? 'design_retry' THEN 'design_retry'
                WHEN ctx ? 'repair_retry' THEN 'repair_retry' ELSE 'syntax_retry' END;
            retry := ctx->retry_key;
            SELECT * INTO STRICT previous FROM model_proposal_generations
            WHERE id = (retry->>'previous_generation_id')::uuid FOR UPDATE;
            previous_context := model_source_context(previous.snapshot_json);
            SELECT snapshot_json::jsonb->'payload' INTO rejection
                FROM model_proposal_generation_events
                WHERE generation_id = previous.id AND kind = 'ADAPTER_REJECTED';
            IF NOT COALESCE(
                jsonb_typeof(retry) = 'object'
                AND retry->'attempt' IN ('2'::jsonb, '3'::jsonb)
                AND CASE WHEN retry_key = 'repair_retry'
                    THEN NOT (ctx ? 'source_step') AND NEW.task_id = 'proposal-web-repair-v1'
                    ELSE ctx ? 'source_step'
                        AND ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS')
                        AND NEW.task_id = 'proposal-web-source-v1' END
                AND ctx->'target_selection'->>'target' = 'WEB_STATIC'
                AND previous.task_id = NEW.task_id
                AND previous.project_id = NEW.project_id
                AND previous.owner_user_id = NEW.owner_user_id
                AND retry->>'previous_request_hash' = previous.request_content_hash
                AND CASE WHEN retry->'attempt' = '2'::jsonb
                    THEN NOT (previous_context ?| ARRAY['syntax_retry','design_retry','repair_retry'])
                        AND (ctx - retry_key) = previous_context
                    ELSE previous_context->retry_key->'attempt' = '2'::jsonb
                        AND (ctx - retry_key) = (previous_context - retry_key) END
                AND rejection->>'code' = retry->>'code'
                AND EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'APPLICATION_RESULT'
                    AND snapshot_json::jsonb->'payload'->>'status' = 'FAILED'
                    AND snapshot_json::jsonb->'payload'->>'code' = retry->>'code')
                AND NOT EXISTS (SELECT 1 FROM model_proposal_generation_events
                    WHERE generation_id = previous.id AND kind = 'ADAPTER_ACCEPTED'),
                false) THEN RAISE EXCEPTION 'Source retry requires an exact rejected first attempt'; END IF;
            IF retry_key IN ('syntax_retry', 'repair_retry') THEN
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
        $function$;
CREATE OR REPLACE FUNCTION validate_source_file_acceptance()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        DECLARE generation record; ctx jsonb; accepted jsonb; output jsonb; planned jsonb;
                step jsonb; child record; child_context jsonb; child_file jsonb; content text;
                files jsonb; binding jsonb; digest text; entry jsonb; ordinal integer; completed jsonb;
        BEGIN
            SELECT * INTO STRICT generation FROM model_proposal_generations WHERE id=NEW.generation_id FOR UPDATE;
            ctx := model_source_context(generation.snapshot_json);
            IF COALESCE(ctx->>'generation_protocol','') NOT IN ('SOURCE_FILES_V1', 'SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS') THEN RETURN NEW; END IF;
            SELECT (snapshot_json::jsonb->'payload'->'success'->>'payload_json')::jsonb INTO output
            FROM model_proposal_generation_events WHERE generation_id=generation.id AND kind='PROVIDER_RESULT';
            accepted := NEW.snapshot_json::jsonb->'payload';
            IF ctx ? 'source_step' THEN
                planned := ctx->'source_step'->'file';
                IF ctx->>'generation_protocol' = 'SOURCE_FILES_V3_PARTS' AND planned->>'normalized_path' = 'app.js' THEN
                    IF jsonb_typeof(output->'functions') IS DISTINCT FROM 'array'
                       OR (output - ARRAY['shared_state','private_helpers','functions','browser_setup']) IS DISTINCT FROM '{}'::jsonb
                       OR jsonb_typeof(output->'shared_state') IS DISTINCT FROM 'array'
                       OR jsonb_typeof(output->'private_helpers') IS DISTINCT FROM 'string'
                       OR jsonb_typeof(output->'browser_setup') IS DISTINCT FROM 'string' THEN
                        RAISE EXCEPTION 'Source file requires bounded module parts';
                    END IF;
                    IF NOT COALESCE(
                        (output->>'browser_setup') <> ''
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
                            OR (part->>'parameters') ~ '[-(){};:]'
                            OR (part->>'body') = '')
                        AND (SELECT count(DISTINCT part->>'name') = count(*)
                            FROM jsonb_array_elements(output->'functions') AS f(part)), false) THEN
                        RAISE EXCEPTION 'Source file requires bounded module parts';
                    END IF;
                    SELECT CASE WHEN jsonb_array_length(output->'shared_state') = 0 THEN ''
                        ELSE (SELECT string_agg((declaration->>'kind') || ' ' || (declaration->>'name') || ' = ' || (declaration->>'initializer') || ';', E'\n' ORDER BY n)
                            FROM jsonb_array_elements(output->'shared_state') WITH ORDINALITY AS s(declaration, n)) || E'\n\n' END
                        || CASE WHEN output->>'private_helpers' = '' THEN '' ELSE (output->>'private_helpers') || E'\n\n' END
                        || string_agg('function ' || (part->>'name') || '(' || (part->>'parameters') || ') {' || E'\n' || (part->>'body') || E'\n}\n\n', '' ORDER BY n)
                        || E'function resetSharedState() {\n' || COALESCE((SELECT string_agg(CASE
                            WHEN (declaration->>'kind') = 'let' THEN '  ' || (declaration->>'name') || ' = ' || (declaration->>'initializer') || E';\n'
                            WHEN (declaration->>'initializer') = '[]' THEN '  ' || (declaration->>'name') || E'.length = 0;\n'
                            WHEN (declaration->>'initializer') = '{}' THEN '  Object.keys(' || (declaration->>'name') || ').forEach(function (key) { delete ' || (declaration->>'name') || E'[key]; });\n'
                            WHEN (declaration->>'initializer') IN ('new Map()', 'new Set()') THEN '  ' || (declaration->>'name') || E'.clear();\n'
                            END, '' ORDER BY n)
                            FROM jsonb_array_elements(output->'shared_state') WITH ORDINALITY AS s(declaration, n)), '') || E'}\n\n'
                        || E'if (typeof document !== ''undefined'') {\n  document.addEventListener(''DOMContentLoaded'', function () {\n'
                        || (output->>'browser_setup') || E'\n  });\n}\n\n'
                        || E'if (typeof module !== ''undefined'') {\n  module.exports = { '
                        || string_agg(part->>'name', ', ' ORDER BY n) || E', resetSharedState };\n}\n'
                    INTO content FROM jsonb_array_elements(output->'functions') WITH ORDINALITY AS f(part, n);
                    IF octet_length(content) NOT BETWEEN 1 AND 32768
                       OR content ~ '[--]' THEN
                        RAISE EXCEPTION 'Source file requires bounded complete UTF-8 text';
                    END IF;
                ELSIF ctx->>'generation_protocol' IN ('SOURCE_FILES_V2_TEXT', 'SOURCE_FILES_V3_PARTS') THEN
                    content := output->>'content';
                    IF jsonb_typeof(output->'content') IS DISTINCT FROM 'string'
                       OR (output - 'content') IS DISTINCT FROM '{}'::jsonb
                       OR octet_length(content) NOT BETWEEN 1 AND 32768
                       OR content ~ '[--]' THEN
                        RAISE EXCEPTION 'Source file requires bounded complete UTF-8 text';
                    END IF;
                ELSE
                IF jsonb_typeof(output->'lines') IS DISTINCT FROM 'array'
                   OR jsonb_array_length(output->'lines') NOT BETWEEN 1 AND 60
                   OR EXISTS (SELECT 1 FROM jsonb_array_elements(output->'lines') AS l(value)
                     WHERE jsonb_typeof(value) <> 'string' OR length(value #>> '{}') > 240
                     OR (value #>> '{}') ~ E'[\\r\\n]') THEN
                    RAISE EXCEPTION 'Source file requires bounded individual lines';
                END IF;
                SELECT string_agg(value, E'\n' ORDER BY n) || E'\n' INTO content
                FROM jsonb_array_elements_text(output->'lines') WITH ORDINALITY AS l(value,n);
                END IF;
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
        $function$;
CREATE OR REPLACE FUNCTION validate_model_source_link()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        DECLARE generation record; binding jsonb; artifact jsonb; matches boolean; target_table text;
        BEGIN
            SELECT * INTO STRICT generation FROM model_proposal_generations WHERE id = NEW.generation_id FOR UPDATE;
            IF generation.task_id <> 'proposal-' || replace(lower(NEW.artifact_kind), '_', '-') || '-v1'
               OR NOT EXISTS (SELECT 1 FROM projects WHERE id = generation.project_id AND owner_user_id = generation.owner_user_id AND archived_at IS NULL)
               OR EXISTS (SELECT 1 FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id AND kind = 'APPLICATION_RESULT') THEN
                RAISE EXCEPTION 'Source generation task, owner or lifecycle mismatch';
            END IF;
            SELECT snapshot_json::jsonb->'payload'->'source_binding' INTO binding
            FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id AND kind = 'ADAPTER_ACCEPTED';
            IF binding IS NULL THEN RAISE EXCEPTION 'Accepted source binding required'; END IF;
            IF NEW.artifact_kind IN ('WEB_SOURCE','JVM_SOURCE') THEN
                target_table := CASE NEW.artifact_kind WHEN 'WEB_SOURCE' THEN 'web_source_revisions' ELSE 'jvm_source_revisions' END;
                EXECUTE format('SELECT revision_snapshot FROM %I WHERE id=$1 AND project_id=$2 AND created_by_user_id=$3 AND version_number=$4 AND content_hash=$5 AND version_number=1 AND origin=''GENERATED_PLAN''', target_table)
                INTO artifact USING NEW.artifact_version_id, generation.project_id, generation.owner_user_id, NEW.version_number, NEW.artifact_content_hash;
                matches := artifact IS NOT NULL AND artifact->'files' = binding->'files'
                    AND artifact->'target_selection' = binding->'target_selection'
                    AND artifact->'provenance_references' = binding->'provenance_references';
            ELSE
                target_table := CASE NEW.artifact_kind WHEN 'WEB_REPAIR' THEN 'web_governed_operations' ELSE 'jvm_governed_operations' END;
                EXECUTE format('SELECT payload_json::jsonb FROM %I WHERE id=$1 AND project_id=$2 AND owner_user_id=$3 AND content_hash=$4 AND kind=''REPAIR'' AND state=''PENDING'' AND source_revision_id=$5', target_table)
                INTO artifact USING NEW.artifact_version_id, generation.project_id, generation.owner_user_id, NEW.artifact_content_hash, (binding->'base_revision'->>'revision_id')::uuid;
                matches := artifact IS NOT NULL AND NEW.version_number = 1
                    AND artifact->>'execution_id' = binding->>'execution_id'
                    AND artifact->>'execution_content_hash' = binding->>'execution_content_hash'
                    AND artifact->'proposal'->'base_revision' = binding->'base_revision'
                    AND artifact->'proposal'->'failure_signature' = binding->'failure_signature'
                    AND artifact->'proposal'->'change_set'->'changes' = binding->'changes'
                    AND artifact->'proposal'->'change_set'->>'rationale' = binding->>'rationale';
            END IF;
            IF NOT COALESCE(matches, false) THEN RAISE EXCEPTION 'Published source differs from accepted model binding'; END IF;
            RETURN NEW;
        END;
        $function$;
"""
RESTORE_INDEX = """
CREATE UNIQUE INDEX uq_source_file_parent_ordinal ON model_proposal_generations
((model_source_context(snapshot_json)->'source_step'->>'parent_generation_id'),
(model_source_context(snapshot_json)->'source_step'->>'ordinal'),
(COALESCE(model_source_context(snapshot_json)->'syntax_retry'->>'attempt',
model_source_context(snapshot_json)->'design_retry'->>'attempt','1')))
WHERE model_source_context(snapshot_json) ? 'source_step';
"""
RESTORE_TRIGGERS = """
CREATE TRIGGER model_source_file_request BEFORE INSERT ON model_proposal_generations
FOR EACH ROW EXECUTE FUNCTION validate_source_file_request();
CREATE TRIGGER model_source_syntax_retry BEFORE INSERT ON model_proposal_generations
FOR EACH ROW EXECUTE FUNCTION validate_source_syntax_retry();
CREATE TRIGGER model_source_file_acceptance BEFORE INSERT ON model_proposal_generation_events
FOR EACH ROW WHEN (NEW.kind='ADAPTER_ACCEPTED') EXECUTE FUNCTION validate_source_file_acceptance();
CREATE TRIGGER model_source_artifact_exact BEFORE INSERT ON model_proposal_artifact_links
FOR EACH ROW WHEN (NEW.artifact_kind IN ('WEB_SOURCE','WEB_REPAIR','JVM_SOURCE','JVM_REPAIR'))
EXECUTE FUNCTION validate_model_source_link();
"""


def upgrade():
    for table, trigger in TRIGGERS:
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_index(INDEX, table_name=TRIGGERS[0][0])


def downgrade():
    op.execute(RESTORE_FUNCTIONS)
    op.execute(RESTORE_INDEX)
    op.execute(RESTORE_TRIGGERS)
