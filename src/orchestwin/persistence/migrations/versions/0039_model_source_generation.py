"""Audited source and repair generation with exact atomic publication links."""

from alembic import op

revision = "0039_model_source_generation"
down_revision = "0038_proposal_generation_evidence"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
LINKS = "model_proposal_artifact_links"
OLD_TASKS = "'proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1','proposal-design-v1','proposal-architecture-v1'"
NEW_TASKS = "'proposal-web-source-v1','proposal-web-repair-v1','proposal-jvm-source-v1','proposal-jvm-repair-v1'"
OLD_KINDS = (
    "'AGENT_TEAM','PERSONA','USER_TWIN','USER_MODELING','REQUIREMENTS','DESIGN','ARCHITECTURE'"
)
NEW_KINDS = "'WEB_SOURCE','WEB_REPAIR','JVM_SOURCE','JVM_REPAIR'"
OLD_RELATION = "relation = 'GENERATED' OR (relation = 'MATCHED_EXISTING' AND artifact_kind = 'AGENT_TEAM') OR (relation = 'ASSEMBLED' AND artifact_kind = 'USER_MODELING')"


def _replace(table, name, expression):
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(name, table, f"COALESCE(({expression}), false)")


def upgrade():
    _replace(GENERATIONS, "task_valid", f"task_id IN ({OLD_TASKS},{NEW_TASKS})")
    _replace(
        LINKS,
        "artifact_valid",
        f"artifact_kind IN ({OLD_KINDS},{NEW_KINDS}) AND version_number > 0 AND artifact_content_hash ~ '^[0-9a-f]{{64}}$'",
    )
    _replace(
        LINKS,
        "relation_valid",
        f"(artifact_kind IN ({OLD_KINDS}) AND ({OLD_RELATION})) OR (artifact_kind IN ('WEB_SOURCE','JVM_SOURCE') AND relation = 'SOURCE_GENERATED') OR (artifact_kind IN ('WEB_REPAIR','JVM_REPAIR') AND relation = 'REPAIR_PROPOSED')",
    )
    op.execute(f"""
        DROP TRIGGER model_proposal_artifact_exact ON {LINKS};
        CREATE TRIGGER model_proposal_artifact_exact BEFORE INSERT ON {LINKS}
        FOR EACH ROW WHEN (NEW.artifact_kind IN ({OLD_KINDS}))
        EXECUTE FUNCTION validate_model_proposal_artifact_link();
        CREATE UNIQUE INDEX uq_model_source_generation_artifact ON {LINKS}(artifact_kind, artifact_version_id)
        WHERE artifact_kind IN ({NEW_KINDS});
    """)
    op.execute("""
        CREATE FUNCTION validate_model_source_link() RETURNS trigger AS $$
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
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_source_artifact_exact BEFORE INSERT ON model_proposal_artifact_links
        FOR EACH ROW WHEN (NEW.artifact_kind IN ('WEB_SOURCE','WEB_REPAIR','JVM_SOURCE','JVM_REPAIR'))
        EXECUTE FUNCTION validate_model_source_link();
    """)


def downgrade():
    # Existing source-generation evidence must never be deleted to permit downgrade.
    _replace(GENERATIONS, "task_valid", f"task_id IN ({OLD_TASKS})")
    _replace(
        LINKS,
        "artifact_valid",
        f"artifact_kind IN ({OLD_KINDS}) AND version_number > 0 AND artifact_content_hash ~ '^[0-9a-f]{{64}}$'",
    )
    _replace(LINKS, "relation_valid", OLD_RELATION)
    op.execute(f"""
        DROP TRIGGER model_source_artifact_exact ON {LINKS};
        DROP FUNCTION validate_model_source_link();
        DROP INDEX uq_model_source_generation_artifact;
        DROP TRIGGER model_proposal_artifact_exact ON {LINKS};
        CREATE TRIGGER model_proposal_artifact_exact BEFORE INSERT ON {LINKS}
        FOR EACH ROW EXECUTE FUNCTION validate_model_proposal_artifact_link();
    """)
