"""Retain model proposal observations and exact atomic artifact links.

Revision ID: 0038_proposal_generation_evidence
Revises: 0037_jvm_governed_operations
"""

import sqlalchemy as sa
from alembic import op

revision = "0038_proposal_generation_evidence"
down_revision = "0037_jvm_governed_operations"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
EVENTS = "model_proposal_generation_events"
LINKS = "model_proposal_artifact_links"


def _check(expression, *, name):
    # PostgreSQL CHECK otherwise accepts NULL when a JSON field is absent.
    return sa.CheckConstraint(f"({expression}) IS TRUE", name=name)


def _snapshot_columns():
    return [
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        _check(
            "octet_length(snapshot_json) BETWEEN 1 AND 16777216 AND jsonb_typeof(snapshot_json::jsonb) = 'object'",
            name="snapshot_bounded",
        ),
        _check(
            "content_hash = encode(sha256(convert_to(snapshot_json, 'UTF8')), 'hex')",
            name="snapshot_hash_valid",
        ),
    ]


def upgrade():
    op.create_table(
        GENERATIONS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("request_content_hash", sa.String(64), nullable=False),
        *_snapshot_columns(),
        _check(
            "task_id IN ('proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1','proposal-design-v1','proposal-architecture-v1')",
            name="task_valid",
        ),
        _check("request_content_hash ~ '^[0-9a-f]{64}$'", name="request_hash_valid"),
        _check(
            "snapshot_json::jsonb->>'generation_id' = id::text AND snapshot_json::jsonb->>'project_id' = project_id::text AND snapshot_json::jsonb->>'owner_user_id' = owner_user_id::text AND snapshot_json::jsonb->'request'->>'request_id' = id::text AND snapshot_json::jsonb->'request'->>'task_id' = task_id AND snapshot_json::jsonb->'request'->>'content_hash' = request_content_hash",
            name="request_identity_valid",
        ),
    )
    op.create_index(
        "ix_model_proposal_generations_owner_project",
        GENERATIONS,
        ["owner_user_id", "project_id", "id"],
    )
    op.create_table(
        EVENTS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey(f"{GENERATIONS}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        *_snapshot_columns(),
        sa.Column("raw_body", sa.LargeBinary()),
        sa.UniqueConstraint("generation_id", "kind"),
        _check(
            "kind IN ('HTTP_REQUEST','HTTP_RESPONSE','TRANSPORT_ERROR','PROVIDER_RESULT','ADAPTER_ACCEPTED','ADAPTER_REJECTED','APPLICATION_RESULT')",
            name="kind_valid",
        ),
        _check(
            "raw_body IS NULL OR (kind = 'HTTP_RESPONSE' AND octet_length(raw_body) <= 4000000 AND snapshot_json::jsonb->>'raw_body_sha256' = encode(sha256(raw_body), 'hex'))",
            name="raw_response_valid",
        ),
        _check(
            "snapshot_json::jsonb->>'generation_id' = generation_id::text AND snapshot_json::jsonb->>'kind' = kind",
            name="event_identity_valid",
        ),
    )
    op.create_table(
        LINKS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey(f"{GENERATIONS}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("artifact_kind", sa.String(24), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("artifact_content_hash", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(24), nullable=False),
        *_snapshot_columns(),
        sa.UniqueConstraint("generation_id", "artifact_kind", "artifact_version_id"),
        _check(
            "artifact_kind IN ('AGENT_TEAM','PERSONA','USER_TWIN','USER_MODELING','REQUIREMENTS','DESIGN','ARCHITECTURE') AND version_number > 0 AND artifact_content_hash ~ '^[0-9a-f]{64}$'",
            name="artifact_valid",
        ),
        _check(
            "relation = 'GENERATED' OR (relation = 'MATCHED_EXISTING' AND artifact_kind = 'AGENT_TEAM') OR (relation = 'ASSEMBLED' AND artifact_kind = 'USER_MODELING')",
            name="relation_valid",
        ),
        _check(
            "snapshot_json::jsonb->>'generation_id' = generation_id::text AND snapshot_json::jsonb->'artifact'->>'kind' = artifact_kind AND snapshot_json::jsonb->'artifact'->>'version_id' = artifact_version_id::text AND (snapshot_json::jsonb->'artifact'->>'version_number')::integer = version_number AND snapshot_json::jsonb->'artifact'->>'content_hash' = artifact_content_hash AND snapshot_json::jsonb->'artifact'->>'relation' = relation",
            name="link_identity_valid",
        ),
    )
    op.create_index(
        "uq_model_proposal_generated_artifact",
        LINKS,
        ["artifact_kind", "artifact_version_id"],
        unique=True,
        postgresql_where=sa.text("relation = 'GENERATED'"),
    )
    op.execute("""
        CREATE FUNCTION protect_model_proposal_evidence() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Model proposal evidence is append-only';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in (GENERATIONS, EVENTS, LINKS):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_model_proposal_evidence()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION protect_model_proposal_evidence()"
        )
    op.execute("""
        CREATE FUNCTION validate_model_proposal_request() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND owner_user_id = NEW.owner_user_id AND archived_at IS NULL) THEN
                RAISE EXCEPTION 'Model generation project is not active and owned';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_proposal_request_owner BEFORE INSERT ON model_proposal_generations
        FOR EACH ROW EXECUTE FUNCTION validate_model_proposal_request();
    """)
    op.execute("""
        CREATE FUNCTION validate_model_proposal_event() RETURNS trigger AS $$
        DECLARE kinds text[];
        BEGIN
            PERFORM 1 FROM model_proposal_generations WHERE id = NEW.generation_id FOR UPDATE;
            SELECT array_agg(kind) INTO kinds FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id;
            kinds := COALESCE(kinds, ARRAY[]::text[]);
            IF 'APPLICATION_RESULT' = ANY(kinds) THEN RAISE EXCEPTION 'Generation command is terminal'; END IF;
            IF NEW.kind = 'HTTP_REQUEST' AND cardinality(kinds) <> 0 THEN RAISE EXCEPTION 'HTTP request is not first'; END IF;
            IF NEW.kind IN ('HTTP_RESPONSE','TRANSPORT_ERROR') AND
               (NOT ('HTTP_REQUEST' = ANY(kinds)) OR 'HTTP_RESPONSE' = ANY(kinds) OR 'TRANSPORT_ERROR' = ANY(kinds)) THEN
                RAISE EXCEPTION 'Invalid HTTP observation sequence';
            END IF;
            IF NEW.kind = 'PROVIDER_RESULT' AND NEW.snapshot_json::jsonb->'payload'->>'status' = 'SUCCEEDED' AND NOT ('HTTP_RESPONSE' = ANY(kinds)) THEN
                RAISE EXCEPTION 'Model success requires an HTTP response';
            END IF;
            IF NEW.kind = 'ADAPTER_ACCEPTED' AND (
                'ADAPTER_REJECTED' = ANY(kinds) OR NOT EXISTS (
                    SELECT 1 FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id AND kind = 'PROVIDER_RESULT'
                    AND snapshot_json::jsonb->'payload'->>'status' = 'SUCCEEDED'
                    AND snapshot_json::jsonb->'payload'->>'provider_kind' = 'OPENAI_COMPATIBLE_LOCAL'
                )) THEN RAISE EXCEPTION 'Accepted proposal requires model success'; END IF;
            IF NEW.kind = 'ADAPTER_REJECTED' AND 'ADAPTER_ACCEPTED' = ANY(kinds) THEN RAISE EXCEPTION 'Proposal was already accepted'; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_proposal_event_sequence BEFORE INSERT ON model_proposal_generation_events
        FOR EACH ROW EXECUTE FUNCTION validate_model_proposal_event();
    """)
    op.execute("""
        CREATE FUNCTION validate_model_proposal_artifact_link() RETURNS trigger AS $$
        DECLARE generation model_proposal_generations%ROWTYPE; accepted jsonb; target_table text; matches boolean;
        BEGIN
            SELECT * INTO STRICT generation FROM model_proposal_generations WHERE id = NEW.generation_id FOR UPDATE;
            IF NOT EXISTS (SELECT 1 FROM projects WHERE id = generation.project_id AND owner_user_id = generation.owner_user_id AND archived_at IS NULL) THEN
                RAISE EXCEPTION 'Artifact publication project is not active and owned';
            END IF;
            IF EXISTS (SELECT 1 FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id AND kind = 'APPLICATION_RESULT') THEN
                RAISE EXCEPTION 'Generation command is terminal';
            END IF;
            SELECT snapshot_json::jsonb->'payload'->'generated_content_hashes' INTO accepted
            FROM model_proposal_generation_events WHERE generation_id = NEW.generation_id AND kind = 'ADAPTER_ACCEPTED';
            IF accepted IS NULL THEN RAISE EXCEPTION 'No accepted proposal to publish'; END IF;
            IF NEW.relation <> 'ASSEMBLED' AND NOT COALESCE(accepted->NEW.artifact_kind ? NEW.artifact_content_hash, false) THEN
                RAISE EXCEPTION 'Artifact differs from accepted generation';
            END IF;
            IF NEW.relation = 'ASSEMBLED' AND (NOT (accepted ? 'USER_TWIN') OR NOT EXISTS (
                SELECT 1 FROM model_proposal_artifact_links WHERE generation_id = NEW.generation_id AND artifact_kind = 'USER_TWIN'
            )) THEN RAISE EXCEPTION 'Snapshot requires linked generated twins'; END IF;
            target_table := CASE NEW.artifact_kind
                WHEN 'AGENT_TEAM' THEN 'team_proposals'
                WHEN 'PERSONA' THEN 'persona_profile_versions'
                WHEN 'USER_TWIN' THEN 'user_twin_profile_versions'
                WHEN 'USER_MODELING' THEN 'user_modeling_snapshot_versions'
                WHEN 'REQUIREMENTS' THEN 'requirements_specification_versions'
                WHEN 'DESIGN' THEN 'design_package_versions'
                WHEN 'ARCHITECTURE' THEN 'architecture_package_versions' END;
            IF target_table IS NULL THEN RAISE EXCEPTION 'Unsupported generated artifact'; END IF;
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I WHERE id=$1 AND project_id=$2 AND created_by_user_id=$3 AND version_number=$4 AND content_hash=$5)', target_table)
            INTO matches USING NEW.artifact_version_id, generation.project_id, generation.owner_user_id, NEW.version_number, NEW.artifact_content_hash;
            IF NOT matches THEN RAISE EXCEPTION 'Exact generated artifact does not exist'; END IF;
            IF NEW.relation = 'ASSEMBLED' AND EXISTS (
                SELECT 1 FROM user_modeling_snapshot_versions s WHERE s.id = NEW.artifact_version_id AND (
                    jsonb_array_length(s.snapshot->'twin_versions') <> (
                        SELECT count(*) FROM model_proposal_artifact_links l WHERE l.generation_id = NEW.generation_id AND l.artifact_kind = 'USER_TWIN'
                    ) OR EXISTS (
                        SELECT 1 FROM jsonb_array_elements(s.snapshot->'twin_versions') twin WHERE NOT EXISTS (
                            SELECT 1 FROM model_proposal_artifact_links l WHERE l.generation_id = NEW.generation_id AND l.artifact_kind = 'USER_TWIN'
                            AND l.artifact_version_id::text = twin->>'id'
                            AND l.version_number = (twin->>'version_number')::integer
                            AND l.artifact_content_hash = twin->>'content_hash'
                        )
                    )
                )
            ) THEN RAISE EXCEPTION 'Snapshot must contain exactly the linked generated twins'; END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER model_proposal_artifact_exact BEFORE INSERT ON model_proposal_artifact_links
        FOR EACH ROW EXECUTE FUNCTION validate_model_proposal_artifact_link();
    """)


def downgrade():
    for table in (LINKS, EVENTS, GENERATIONS):
        op.drop_table(table)
    for function in (
        "validate_model_proposal_artifact_link",
        "validate_model_proposal_event",
        "validate_model_proposal_request",
        "protect_model_proposal_evidence",
    ):
        op.execute(f"DROP FUNCTION {function}()")
