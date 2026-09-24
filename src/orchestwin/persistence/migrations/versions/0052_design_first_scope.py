from alembic import op

revision = "0052_design_first_scope"
down_revision = "0051_source_third_attempt"
branch_labels = None
depends_on = None

GATE_TRIGGER = "retain_running_jvm_operation_gate"
GATE_TABLE = "human_gates"
TABLES = (
    "synthetic_findings",
    "evaluation_runs",
    "final_reviews",
    "export_bundles",
    "authorized_evaluation_artifacts",
    "workflow_events",
    "workflow_graph_writes",
    "workflow_graph_checkpoints",
    "workflow_checkpoints",
    "workflow_runs",
    "static_browser_inspections",
    "web_governed_operations",
    "web_profile_validation_evidence",
    "web_execution_attempts",
    "web_source_revisions",
    "jvm_governed_operations",
    "jvm_profile_validation_evidence",
    "jvm_execution_attempts",
    "jvm_source_revisions",
    "sandbox_command_results",
    "sandbox_runs",
    "brownfield_intake_versions",
    "high_impact_operation_versions",
    "architecture_package_diffs",
    "architecture_package_versions",
)
FUNCTIONS = (
    "reject_synthetic_finding_mutation",
    "reject_evaluation_run_mutation",
    "reject_final_review_mutation",
    "reject_export_bundle_mutation",
    "reject_authorized_evaluation_artifact_mutation",
    "reject_workflow_event_mutation",
    "reject_workflow_checkpoint_mutation",
    "protect_static_browser_inspection",
    "protect_web_governed_operation",
    "reject_web_profile_validation_evidence_mutation",
    "reject_web_execution_attempt_mutation",
    "reject_web_source_revision_mutation",
    "protect_jvm_governed_operation",
    "reject_jvm_profile_validation_evidence_mutation",
    "reject_jvm_execution_attempt_mutation",
    "reject_jvm_source_revision_mutation",
    "reject_sandbox_evidence_mutation",
    "reject_brownfield_intake_version_mutation",
    "reject_high_impact_operation_version_mutation",
    "reject_architecture_package_version_mutation",
)
RESTORE_FUNCTIONS = """
CREATE OR REPLACE FUNCTION reject_synthetic_finding_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'synthetic findings are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_evaluation_run_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'evaluation runs are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_final_review_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'final reviews are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_export_bundle_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'export bundles are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_authorized_evaluation_artifact_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION
                'authorized evaluation artifact registrations are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_workflow_event_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'workflow events are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_workflow_checkpoint_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'workflow checkpoints are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION protect_static_browser_inspection()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'static inspection audit records are not deletable';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['state','started_at','finished_at','result_json','result_hash'])
                IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['state','started_at','finished_at','result_json','result_hash']) THEN
                RAISE EXCEPTION 'static inspection plans are immutable';
            END IF;
            IF NOT ((OLD.state = 'PENDING' AND NEW.state = 'RUNNING') OR
                    (OLD.state = 'RUNNING' AND NEW.state IN ('COMPLETED','FAILED')
                     AND NEW.started_at = OLD.started_at)) THEN
                RAISE EXCEPTION 'static inspection transition is forbidden';
            END IF;
            RETURN NEW;
        END;
        $function$;
CREATE OR REPLACE FUNCTION protect_web_governed_operation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'Web operation audit records cannot be deleted or truncated';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
               NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR NEW.source_revision_id IS DISTINCT FROM OLD.source_revision_id OR
               NEW.kind IS DISTINCT FROM OLD.kind OR NEW.payload_json IS DISTINCT FROM OLD.payload_json OR
               NEW.payload_content_hash IS DISTINCT FROM OLD.payload_content_hash OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
               NEW.gate_id IS DISTINCT FROM OLD.gate_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Web operation approval inputs are immutable';
            END IF;
            IF NOT ((OLD.state = 'PENDING' AND NEW.state = 'RUNNING') OR
                    (OLD.state = 'PENDING' AND NEW.state = 'FAILED' AND NEW.started_at IS NULL) OR
                    (OLD.state = 'RUNNING' AND NEW.state IN ('COMPLETED', 'FAILED') AND NEW.started_at = OLD.started_at)) THEN
                RAISE EXCEPTION 'Web operation lifecycle transition is forbidden';
            END IF;
            RETURN NEW;
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_web_profile_validation_evidence_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'Web profile validation evidence is immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_web_execution_attempt_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'Web execution attempts are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_web_source_revision_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'Web source revisions are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION protect_jvm_governed_operation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'Jvm operation audit records cannot be deleted or truncated';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
               NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR NEW.source_revision_id IS DISTINCT FROM OLD.source_revision_id OR
               NEW.kind IS DISTINCT FROM OLD.kind OR NEW.payload_json IS DISTINCT FROM OLD.payload_json OR
               NEW.payload_content_hash IS DISTINCT FROM OLD.payload_content_hash OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
               NEW.gate_id IS DISTINCT FROM OLD.gate_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Jvm operation approval inputs are immutable';
            END IF;
            IF NOT ((OLD.state = 'PENDING' AND NEW.state = 'RUNNING') OR
                    (OLD.state = 'PENDING' AND NEW.state = 'FAILED' AND NEW.started_at IS NULL) OR
                    (OLD.state = 'RUNNING' AND NEW.state IN ('COMPLETED', 'FAILED') AND NEW.started_at = OLD.started_at)) THEN
                RAISE EXCEPTION 'Jvm operation lifecycle transition is forbidden';
            END IF;
            RETURN NEW;
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_jvm_profile_validation_evidence_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'JVM profile validation evidence is immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_jvm_execution_attempt_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'JVM execution attempts are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_jvm_source_revision_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'JVM source revisions are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_sandbox_evidence_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'sandbox run evidence is immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_brownfield_intake_version_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'brownfield intake versions are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_high_impact_operation_version_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            RAISE EXCEPTION 'high-impact operation versions are immutable';
        END;
        $function$;
CREATE OR REPLACE FUNCTION reject_architecture_package_version_mutation()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
            BEGIN
                RAISE EXCEPTION
                    'Architecture Package versions are immutable';
            END;
            $function$;
CREATE OR REPLACE FUNCTION retain_running_jvm_operation_gate()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
        BEGIN
            IF NEW.gate_type = 'HIGH_IMPACT_OPERATION' AND EXISTS (
                SELECT 1 FROM jvm_governed_operations
                WHERE project_id = NEW.project_id AND state = 'RUNNING'
            ) THEN
                RAISE EXCEPTION 'A running JVM operation retains its Gate 7';
            END IF;
            RETURN NEW;
        END;
        $function$
;;
"""
RESTORE_TABLES = r"""
CREATE TABLE architecture_package_diffs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    base_version_id uuid NOT NULL,
    base_version_number integer NOT NULL,
    base_content_hash character varying(64) NOT NULL,
    proposal_hash character varying(64) NOT NULL,
    diff_snapshot jsonb NOT NULL,
    status character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    decided_by_user_id uuid,
    decided_at timestamp with time zone,
    decision_reason text,
    applied_version_id uuid,
    CONSTRAINT ck_architecture_package_diffs_ck_architecture_package_d_19bd CHECK (status IN ('PROPOSED', 'APPROVED', 'REJECTED')),
    CONSTRAINT ck_architecture_package_diffs_ck_architecture_package_d_43a2 CHECK (base_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_architecture_package_diffs_ck_architecture_package_d_b820 CHECK (proposal_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_architecture_package_diffs_ck_architecture_package_d_b922 CHECK (base_version_number > 0),
    CONSTRAINT ck_architecture_package_diffs_ck_architecture_package_d_fdce CHECK (
            (
                status = 'PROPOSED'
                AND decided_by_user_id IS NULL
                AND decided_at IS NULL
                AND decision_reason IS NULL
                AND applied_version_id IS NULL
            )
            OR
            (
                status = 'REJECTED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NOT NULL
                AND applied_version_id IS NULL
            )
            OR
            (
                status = 'APPROVED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND applied_version_id IS NOT NULL
            )
            )
);
CREATE TABLE architecture_package_versions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_number integer NOT NULL,
    based_on_version_number integer,
    schema_version integer NOT NULL,
    content_hash character varying(64) NOT NULL,
    package_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_architecture_package_versions_ck_architecture_packag_1c21 CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_architecture_package_versions_ck_architecture_packag_237d CHECK (schema_version > 0),
    CONSTRAINT ck_architecture_package_versions_ck_architecture_packag_7d5d CHECK (
            (
                version_number = 1
                AND based_on_version_number IS NULL
            )
            OR
            (
                version_number > 1
                AND based_on_version_number = version_number - 1
            )
            ),
    CONSTRAINT ck_architecture_package_versions_ck_architecture_packag_f4ee CHECK (version_number > 0)
);
CREATE TABLE authorized_evaluation_artifacts (
    owner_user_id uuid NOT NULL,
    project_id uuid NOT NULL,
    workflow_run_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    version_number integer NOT NULL,
    kind character varying(32) NOT NULL,
    media_type character varying(127) NOT NULL,
    sha256_digest character varying(64) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_key character varying(74) NOT NULL,
    location character varying(500) NOT NULL,
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_004d CHECK (char_length(location) BETWEEN 1 AND 500),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_010a CHECK (version_number >= 1),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_6b84 CHECK (char_length(media_type) BETWEEN 3 AND 127 AND position('/' in media_type) > 1),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_7149 CHECK (kind IN ('SCREENSHOT', 'DOM_SNAPSHOT', 'ACCESSIBILITY_TREE', 'AXE_REPORT', 'FUNCTIONAL_TEST_REPORT', 'EXECUTION_REPORT', 'DESIGN_SPECIFICATION', 'PROTOTYPE_MANIFEST', 'SOURCE_SNAPSHOT')),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_aadc CHECK (size_bytes >= 1),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_c8f8 CHECK (sha256_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_authorized_evaluation_artifacts_ck_authorized_evalua_ec39 CHECK (storage_key = 'sha256/' || substring(sha256_digest from 1 for 2) || '/' || sha256_digest)
);
CREATE TABLE brownfield_intake_versions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_number integer NOT NULL,
    based_on_version_number integer,
    schema_version integer NOT NULL,
    content_hash character varying(64) NOT NULL,
    archive_sha256 character varying(64) NOT NULL,
    archive_size_bytes bigint NOT NULL,
    archive_storage_key text NOT NULL,
    inventory_content_hash character varying(64) NOT NULL,
    capability_status character varying(40) NOT NULL,
    effective_capability_status character varying(32) NOT NULL,
    selected_profile_id character varying(128),
    selected_profile_version character varying(64),
    selected_profile_content_hash character varying(64),
    intake_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_0612 CHECK (archive_size_bytes >= 0),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_1706 CHECK (effective_capability_status IN ('VALIDATED_LEVEL_D', 'EXPERIMENTAL_LEVEL_D', 'DESIGN_ONLY_LEVEL_C')),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_2229 CHECK (capability_status IN ('VALIDATED_LEVEL_D_SELECTED', 'EXPERIMENTAL_LEVEL_D_SELECTED', 'DESIGN_ONLY_LEVEL_C_SELECTED', 'HUMAN_DECISION_REQUIRED', 'UNSUPPORTED')),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_41bb CHECK ((version_number = 1 AND based_on_version_number IS NULL) OR (version_number > 1 AND based_on_version_number = version_number - 1)),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_4ade CHECK (version_number > 0),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_8820 CHECK (inventory_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_8db9 CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_b45d CHECK (archive_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_c447 CHECK ((selected_profile_id IS NULL AND selected_profile_version IS NULL AND selected_profile_content_hash IS NULL) OR (selected_profile_id IS NOT NULL AND selected_profile_version IS NOT NULL AND selected_profile_content_hash IS NOT NULL)),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_d6f8 CHECK (selected_profile_content_hash IS NULL OR selected_profile_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_brownfield_intake_versions_ck_brownfield_intake_vers_f6e8 CHECK (schema_version > 0)
);
CREATE TABLE evaluation_runs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    workflow_run_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    artifact_bundle_id uuid NOT NULL,
    artifact_bundle_hash character varying(64) NOT NULL,
    evaluator_id character varying(256) NOT NULL,
    evaluator_version character varying(256) NOT NULL,
    model_config_ref character varying(256) NOT NULL,
    prompt_version_ref character varying(256) NOT NULL,
    status character varying(32) NOT NULL,
    response_count integer NOT NULL,
    finding_count integer NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone NOT NULL,
    content_hash character varying(64) NOT NULL,
    run_snapshot_json text NOT NULL,
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_artifact_bundle_hash CHECK (artifact_bundle_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_finding_count CHECK (finding_count >= 0),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_response_count CHECK (response_count BETWEEN 1 AND 4),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_snapshot CHECK (char_length(run_snapshot_json) > 0),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_status CHECK (status = 'COMPLETED'),
    CONSTRAINT ck_evaluation_runs_ck_evaluation_runs_time_order CHECK (completed_at >= started_at)
);
CREATE TABLE export_bundles (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    workflow_run_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    manifest_id uuid NOT NULL,
    manifest_hash character varying(64) NOT NULL,
    final_review_id uuid NOT NULL,
    final_review_hash character varying(64) NOT NULL,
    final_approval_gate_id uuid NOT NULL,
    final_approval_event_id uuid NOT NULL,
    archive_hash character varying(64) NOT NULL,
    archive_size_bytes integer NOT NULL,
    storage_ref character varying(500) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    bundle_snapshot_json text NOT NULL,
    CONSTRAINT ck_export_bundles_ck_export_bundles_archive_hash CHECK (archive_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_export_bundles_ck_export_bundles_archive_size CHECK (archive_size_bytes > 0),
    CONSTRAINT ck_export_bundles_ck_export_bundles_final_review_hash CHECK (final_review_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_export_bundles_ck_export_bundles_manifest_hash CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_export_bundles_ck_export_bundles_snapshot CHECK (char_length(bundle_snapshot_json) > 0),
    CONSTRAINT ck_export_bundles_ck_export_bundles_storage_ref CHECK (char_length(storage_ref) > 0)
);
CREATE TABLE final_reviews (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    workflow_run_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    version_number integer NOT NULL,
    parent_review_id uuid,
    workflow_state_version integer NOT NULL,
    ready_for_gate8 boolean NOT NULL,
    content_hash character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    review_snapshot_json text NOT NULL,
    CONSTRAINT ck_final_reviews_ck_final_reviews_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_final_reviews_ck_final_reviews_parent CHECK ((version_number = 1 AND parent_review_id IS NULL) OR (version_number > 1 AND parent_review_id IS NOT NULL)),
    CONSTRAINT ck_final_reviews_ck_final_reviews_snapshot CHECK (char_length(review_snapshot_json) > 0),
    CONSTRAINT ck_final_reviews_ck_final_reviews_version CHECK (version_number >= 1),
    CONSTRAINT ck_final_reviews_ck_final_reviews_workflow_state CHECK (workflow_state_version >= 1)
);
CREATE TABLE high_impact_operation_versions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_number integer NOT NULL,
    based_on_version_number integer,
    content_hash character varying(64) NOT NULL,
    policy_content_hash character varying(64) NOT NULL,
    classification character varying(40) NOT NULL,
    request_snapshot jsonb NOT NULL,
    classification_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_high_impact_operation_versions_ck_high_impact_operat_1586 CHECK (classification IN ('ALLOWED_WITHOUT_APPROVAL', 'REQUIRES_OWNER_APPROVAL', 'FORBIDDEN_BY_POLICY')),
    CONSTRAINT ck_high_impact_operation_versions_ck_high_impact_operat_4860 CHECK (version_number > 0),
    CONSTRAINT ck_high_impact_operation_versions_ck_high_impact_operat_7411 CHECK (policy_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_high_impact_operation_versions_ck_high_impact_operat_e068 CHECK ((version_number = 1 AND based_on_version_number IS NULL) OR (version_number > 1 AND based_on_version_number = version_number - 1)),
    CONSTRAINT ck_high_impact_operation_versions_ck_high_impact_operat_f78d CHECK (content_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE jvm_execution_attempts (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    attempt_number integer NOT NULL,
    previous_attempt_id uuid,
    content_hash character varying(64) NOT NULL,
    source_revision_id uuid NOT NULL,
    source_revision_version integer NOT NULL,
    source_revision_content_hash character varying(64) NOT NULL,
    source_tree_hash character varying(64) NOT NULL,
    target character varying(32) NOT NULL,
    profile_id character varying(128) NOT NULL,
    profile_version character varying(64) NOT NULL,
    profile_validation_content_hash character varying(64) NOT NULL,
    execution_plan_content_hash character varying(64) NOT NULL,
    runner_id character varying(128) NOT NULL,
    runner_version character varying(64) NOT NULL,
    runner_image_digest character varying(64) NOT NULL,
    policy_content_hash character varying(64) NOT NULL,
    trigger character varying(32) NOT NULL,
    report_status character varying(16) NOT NULL,
    attempt_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_con_95c0 CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_exe_d308 CHECK (execution_plan_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_lin_c60f CHECK ((attempt_number = 1 AND previous_attempt_id IS NULL) OR (attempt_number > 1 AND previous_attempt_id IS NOT NULL)),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_policy_hash CHECK (policy_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_pos_555a CHECK (attempt_number > 0),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_pro_e9f4 CHECK (profile_validation_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_rep_f72a CHECK (report_status IN ('PASSED', 'FAILED', 'INCOMPLETE')),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_runner_hash CHECK (runner_image_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_sou_0328 CHECK (source_revision_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_sou_b9aa CHECK (source_tree_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_target CHECK (target IN ('JVM_JAVA', 'JVM_KOTLIN', 'JVM_SCALA')),
    CONSTRAINT ck_jvm_execution_attempts_ck_jvm_execution_attempts_trigger CHECK (trigger IN ('INITIAL', 'PROFILE_VALIDATION', 'REPAIR_RERUN', 'MANUAL_RERUN'))
);
CREATE TABLE jvm_governed_operations (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    kind character varying(16) NOT NULL,
    payload_json text NOT NULL,
    payload_content_hash character varying(64) NOT NULL,
    content_hash character varying(64) NOT NULL,
    gate_id uuid NOT NULL,
    state character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    result_json text,
    result_content_hash character varying(64),
    CONSTRAINT ck_jvm_governed_operations_finished_order CHECK (finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)),
    CONSTRAINT ck_jvm_governed_operations_hashes_valid CHECK (content_hash ~ '^[0-9a-f]{64}$' AND payload_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_governed_operations_kind_valid CHECK (kind IN ('EXECUTION', 'REPAIR')),
    CONSTRAINT ck_jvm_governed_operations_lifecycle_valid CHECK ((state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR (state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR (state = 'COMPLETED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL) OR (state = 'FAILED' AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL AND (started_at IS NOT NULL OR result_json::jsonb = jsonb_build_object('failure_code', 'JVM_OPERATION_CANCELLED', 'execution_started', false)))),
    CONSTRAINT ck_jvm_governed_operations_payload_bounded CHECK (octet_length(payload_json) BETWEEN 1 AND 4194304),
    CONSTRAINT ck_jvm_governed_operations_payload_object CHECK (jsonb_typeof(payload_json::jsonb) = 'object'),
    CONSTRAINT ck_jvm_governed_operations_result_bounded CHECK (result_json IS NULL OR (octet_length(result_json) BETWEEN 1 AND 4194304 AND jsonb_typeof(result_json::jsonb) = 'object')),
    CONSTRAINT ck_jvm_governed_operations_result_hash_valid CHECK (result_content_hash IS NULL OR result_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_governed_operations_started_order CHECK (started_at IS NULL OR started_at >= created_at),
    CONSTRAINT ck_jvm_governed_operations_state_valid CHECK (state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'))
);
CREATE TABLE jvm_profile_validation_evidence (
    evidence_id text NOT NULL,
    kind character varying(32) NOT NULL,
    profile_id text NOT NULL,
    profile_version character varying(64) NOT NULL,
    baseline_scope_hash character varying(64) NOT NULL,
    runner_image_digest character varying(64) NOT NULL,
    runner_build_recipe_hash character varying(64) CONSTRAINT jvm_profile_validation_eviden_runner_build_recipe_hash_not_null NOT NULL,
    toolchain_manifest_hash character varying(64) CONSTRAINT jvm_profile_validation_evidenc_toolchain_manifest_hash_not_null NOT NULL,
    fixture_bundle_hash character varying(64) NOT NULL,
    environment_fingerprint character varying(64) CONSTRAINT jvm_profile_validation_evidenc_environment_fingerprint_not_null NOT NULL,
    artifact_content_hash character varying(64) NOT NULL,
    reference text NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    passed boolean NOT NULL,
    content_hash character varying(64) NOT NULL,
    evidence_snapshot jsonb NOT NULL,
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_4ab8 CHECK ((jsonb_typeof(evidence_snapshot) = 'object' AND evidence_snapshot ?& ARRAY['evidence_id', 'kind', 'profile_id', 'profile_version', 'baseline_scope_hash', 'runner_image_digest', 'runner_build_recipe_hash', 'toolchain_manifest_hash', 'fixture_bundle_hash', 'environment_fingerprint', 'artifact_content_hash', 'reference', 'recorded_at', 'passed'] AND evidence_snapshot - ARRAY['evidence_id', 'kind', 'profile_id', 'profile_version', 'baseline_scope_hash', 'runner_image_digest', 'runner_build_recipe_hash', 'toolchain_manifest_hash', 'fixture_bundle_hash', 'environment_fingerprint', 'artifact_content_hash', 'reference', 'recorded_at', 'passed'] = '{}'::jsonb) IS TRUE),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_4e39 CHECK (reference ~ '^[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$'),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_6e9e CHECK (kind IN ('CONTRACT_TESTS', 'RUNNER_IMAGE', 'RUNNER_BUILD_RECIPE', 'TOOLCHAIN_MANIFEST', 'SOURCE_FIXTURE', 'VALIDATE_REPORT', 'SETUP_REPORT', 'STATIC_CHECK_REPORT', 'BUILD_REPORT', 'TEST_REPORT', 'RUN_REPORT', 'ARTIFACT_INVENTORY', 'FAILURE_MATRIX', 'REPAIR_RERUN', 'REPRODUCIBILITY', 'KNOWN_LIMITATIONS')),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_7bcc CHECK (baseline_scope_hash ~ '^[0-9a-f]{64}$' AND runner_image_digest ~ '^[0-9a-f]{64}$' AND runner_build_recipe_hash ~ '^[0-9a-f]{64}$' AND toolchain_manifest_hash ~ '^[0-9a-f]{64}$' AND fixture_bundle_hash ~ '^[0-9a-f]{64}$' AND environment_fingerprint ~ '^[0-9a-f]{64}$' AND artifact_content_hash ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_80b0 CHECK (evidence_id ~ '^[A-Za-z][A-Za-z0-9]*([._/-][A-Za-z0-9]+)*$' AND profile_id ~ '^[A-Za-z][A-Za-z0-9]*([._/-][A-Za-z0-9]+)*$'),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_8e58 CHECK (profile_version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$'),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_cc8b CHECK ((jsonb_typeof(evidence_snapshot -> 'recorded_at') = 'string' AND evidence_snapshot ->> 'recorded_at' ~ 'T.*[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?$') IS TRUE),
    CONSTRAINT ck_jvm_profile_validation_evidence_ck_jvm_profile_valid_d3fc CHECK ((evidence_snapshot -> 'evidence_id' = to_jsonb(evidence_id) AND evidence_snapshot -> 'kind' = to_jsonb(kind) AND evidence_snapshot -> 'profile_id' = to_jsonb(profile_id) AND evidence_snapshot -> 'profile_version' = to_jsonb(profile_version) AND evidence_snapshot -> 'baseline_scope_hash' = to_jsonb(baseline_scope_hash) AND evidence_snapshot -> 'runner_image_digest' = to_jsonb(runner_image_digest) AND evidence_snapshot -> 'runner_build_recipe_hash' = to_jsonb(runner_build_recipe_hash) AND evidence_snapshot -> 'toolchain_manifest_hash' = to_jsonb(toolchain_manifest_hash) AND evidence_snapshot -> 'fixture_bundle_hash' = to_jsonb(fixture_bundle_hash) AND evidence_snapshot -> 'environment_fingerprint' = to_jsonb(environment_fingerprint) AND evidence_snapshot -> 'artifact_content_hash' = to_jsonb(artifact_content_hash) AND evidence_snapshot -> 'reference' = to_jsonb(reference) AND evidence_snapshot -> 'passed' = to_jsonb(passed)) IS TRUE)
);
CREATE TABLE jvm_source_revisions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_number integer NOT NULL,
    based_on_revision_id uuid,
    based_on_version_number integer,
    content_hash character varying(64) NOT NULL,
    source_tree_hash character varying(64) NOT NULL,
    validation_scope_hash character varying(64) NOT NULL,
    target character varying(32) NOT NULL,
    layout character varying(32) NOT NULL,
    origin character varying(32) NOT NULL,
    related_failure_signature character varying(64),
    revision_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_failure_bc1c CHECK (related_failure_signature IS NULL OR related_failure_signature ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_layout CHECK (layout IN ('SINGLE_MODULE')),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_linear_lineage CHECK ((version_number = 1 AND based_on_revision_id IS NULL AND based_on_version_number IS NULL) OR (version_number > 1 AND based_on_revision_id IS NOT NULL AND based_on_version_number = version_number - 1)),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_origin CHECK (origin IN ('GENERATED_PLAN', 'IMPORTED_BROWNFIELD', 'REPAIR_CHANGE_SET', 'DETERMINISTIC_FIXTURE')),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_positiv_c29d CHECK (version_number > 0),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_source__1b45 CHECK (source_tree_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_target CHECK (target IN ('JVM_JAVA', 'JVM_KOTLIN', 'JVM_SCALA')),
    CONSTRAINT ck_jvm_source_revisions_ck_jvm_source_revisions_validat_a544 CHECK (validation_scope_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE sandbox_command_results (
    run_id uuid NOT NULL,
    ordinal integer NOT NULL,
    command_id character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone NOT NULL,
    exit_code integer,
    output_parser_id character varying(128),
    failure_message text,
    stdout_log jsonb NOT NULL,
    stderr_log jsonb NOT NULL,
    artifacts jsonb NOT NULL,
    CONSTRAINT ck_sandbox_command_results_ck_sandbox_command_results_exit_code CHECK (exit_code IS NULL OR exit_code BETWEEN 0 AND 255),
    CONSTRAINT ck_sandbox_command_results_ck_sandbox_command_results_ordinal CHECK (ordinal >= 0),
    CONSTRAINT ck_sandbox_command_results_ck_sandbox_command_results_status CHECK (status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT', 'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR')),
    CONSTRAINT ck_sandbox_command_results_ck_sandbox_command_results_t_a67e CHECK (finished_at >= started_at)
);
CREATE TABLE sandbox_runs (
    run_id uuid NOT NULL,
    project_id uuid NOT NULL,
    intake_id uuid,
    intake_version_number integer,
    intake_content_hash character varying(64),
    schema_version integer NOT NULL,
    evidence_content_hash character varying(64) NOT NULL,
    plan_id character varying(128) NOT NULL,
    plan_content_hash character varying(64) NOT NULL,
    profile_id character varying(128) NOT NULL,
    profile_version character varying(64) NOT NULL,
    image_reference text NOT NULL,
    runtime_reference character varying(128) NOT NULL,
    status character varying(32) NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone NOT NULL,
    failure_message text,
    evidence_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_evidence_content_hash CHECK (evidence_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_intake_content_hash CHECK (intake_content_hash IS NULL OR intake_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_intake_reference_shape CHECK ((intake_id IS NULL AND intake_version_number IS NULL AND intake_content_hash IS NULL) OR (intake_id IS NOT NULL AND intake_version_number > 0 AND intake_content_hash IS NOT NULL)),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_plan_content_hash CHECK (plan_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_positive_schema CHECK (schema_version > 0),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_recording_time CHECK (recorded_at >= finished_at),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_status CHECK (status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT', 'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR')),
    CONSTRAINT ck_sandbox_runs_ck_sandbox_runs_time_range CHECK (finished_at >= started_at)
);
CREATE TABLE static_browser_inspections (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    gate_id uuid NOT NULL,
    plan_hash character varying(64) NOT NULL,
    job_hash character varying(64) NOT NULL,
    plan_json text NOT NULL,
    state character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    result_json text,
    result_hash character varying(64),
    CONSTRAINT ck_static_browser_inspections_finish_order CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_static_browser_inspections_hashes_valid CHECK (plan_hash ~ '^[0-9a-f]{64}$' AND job_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_static_browser_inspections_lifecycle_consistent CHECK ((state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR (state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR (state IN ('COMPLETED', 'FAILED') AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_hash IS NOT NULL)),
    CONSTRAINT ck_static_browser_inspections_plan_size_valid CHECK (octet_length(plan_json) BETWEEN 1 AND 5242880),
    CONSTRAINT ck_static_browser_inspections_start_order CHECK (started_at IS NULL OR started_at >= created_at),
    CONSTRAINT ck_static_browser_inspections_state_valid CHECK (state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'))
);
CREATE TABLE synthetic_findings (
    evaluation_run_id uuid NOT NULL,
    finding_id character varying(64) NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    sequence_number integer NOT NULL,
    twin_id uuid NOT NULL,
    twin_version integer NOT NULL,
    artifact_id uuid NOT NULL,
    artifact_version integer NOT NULL,
    criterion character varying(32) NOT NULL,
    severity character varying(16) NOT NULL,
    epistemic_status character varying(32) NOT NULL,
    confidence double precision NOT NULL,
    requires_human_validation boolean NOT NULL,
    content_hash character varying(64) NOT NULL,
    finding_snapshot_json text NOT NULL,
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_artifact_version CHECK (artifact_version >= 1),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_criterion CHECK (criterion IN ('usefulness', 'comprehensibility', 'actionability', 'cognitive_load', 'trust', 'accessibility', 'task_alignment')),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_epistemic_status CHECK (epistemic_status IN ('USER_PROVIDED', 'EMPIRICALLY_SUPPORTED', 'HUMAN_VALIDATED', 'MODEL_INFERRED', 'UNSUPPORTED_ASSUMPTION')),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_sequence CHECK (sequence_number >= 1),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_severity CHECK (severity IN ('critical', 'major', 'moderate', 'minor', 'observation')),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_snapshot CHECK (char_length(finding_snapshot_json) > 0),
    CONSTRAINT ck_synthetic_findings_ck_synthetic_findings_twin_version CHECK (twin_version >= 1)
);
CREATE TABLE web_execution_attempts (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    attempt_number integer NOT NULL,
    previous_attempt_id uuid,
    content_hash character varying(64) NOT NULL,
    source_revision_id uuid NOT NULL,
    source_revision_version integer NOT NULL,
    source_revision_content_hash character varying(64) NOT NULL,
    source_tree_hash character varying(64) NOT NULL,
    profile_id character varying(128) NOT NULL,
    profile_version character varying(64) NOT NULL,
    profile_validation_content_hash character varying(64) NOT NULL,
    execution_plan_content_hash character varying(64) NOT NULL,
    policy_content_hash character varying(64) NOT NULL,
    runner_image_digest character varying(64) NOT NULL,
    trigger character varying(32) NOT NULL,
    report_status character varying(16) NOT NULL,
    attempt_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_con_ad9e CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_exe_0b36 CHECK (execution_plan_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_lin_f9e7 CHECK ((attempt_number = 1 AND previous_attempt_id IS NULL) OR (attempt_number > 1 AND previous_attempt_id IS NOT NULL)),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_policy_hash CHECK (policy_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_pos_9bfe CHECK (attempt_number > 0),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_pro_0503 CHECK (profile_validation_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_rep_5ad3 CHECK (report_status IN ('PASSED', 'FAILED', 'INCOMPLETE')),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_runner_hash CHECK (runner_image_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_sou_0d1a CHECK (source_tree_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_sou_3ec6 CHECK (source_revision_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_execution_attempts_ck_web_execution_attempts_trigger CHECK (trigger IN ('INITIAL', 'PROFILE_VALIDATION', 'REPAIR_RERUN', 'MANUAL_RERUN'))
);
CREATE TABLE web_governed_operations (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    kind character varying(16) NOT NULL,
    payload_json text NOT NULL,
    payload_content_hash character varying(64) NOT NULL,
    content_hash character varying(64) NOT NULL,
    gate_id uuid NOT NULL,
    state character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    result_json text,
    result_content_hash character varying(64),
    CONSTRAINT ck_web_governed_operations_finished_order CHECK (finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)),
    CONSTRAINT ck_web_governed_operations_hashes_valid CHECK (content_hash ~ '^[0-9a-f]{64}$' AND payload_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_governed_operations_kind_valid CHECK (kind IN ('EXECUTION', 'REPAIR')),
    CONSTRAINT ck_web_governed_operations_lifecycle_valid CHECK ((state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR (state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR (state = 'COMPLETED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL) OR (state = 'FAILED' AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL AND (started_at IS NOT NULL OR result_json::jsonb = jsonb_build_object('failure_code', 'WEB_OPERATION_CANCELLED', 'execution_started', false)))),
    CONSTRAINT ck_web_governed_operations_payload_bounded CHECK (octet_length(payload_json) BETWEEN 1 AND 4194304),
    CONSTRAINT ck_web_governed_operations_payload_object CHECK (jsonb_typeof(payload_json::jsonb) = 'object'),
    CONSTRAINT ck_web_governed_operations_result_bounded CHECK (result_json IS NULL OR (octet_length(result_json) BETWEEN 1 AND 4194304 AND jsonb_typeof(result_json::jsonb) = 'object')),
    CONSTRAINT ck_web_governed_operations_result_hash_valid CHECK (result_content_hash IS NULL OR result_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_governed_operations_started_order CHECK (started_at IS NULL OR started_at >= created_at),
    CONSTRAINT ck_web_governed_operations_state_valid CHECK (state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'))
);
CREATE TABLE web_profile_validation_evidence (
    evidence_id text NOT NULL,
    kind character varying(32) NOT NULL,
    profile_id text NOT NULL,
    profile_version character varying(64) NOT NULL,
    baseline_scope_hash character varying(64) NOT NULL,
    language_configuration jsonb,
    execution_runner_image_digest character varying(64) CONSTRAINT web_profile_validation_evid_execution_runner_image_dig_not_null NOT NULL,
    browser_runner_image_digest character varying(64),
    artifact_content_hash character varying(64) NOT NULL,
    reference text NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    passed boolean NOT NULL,
    content_hash character varying(64) NOT NULL,
    evidence_snapshot jsonb NOT NULL,
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_0999 CHECK (baseline_scope_hash ~ '^[0-9a-f]{64}$' AND execution_runner_image_digest ~ '^[0-9a-f]{64}$' AND artifact_content_hash ~ '^[0-9a-f]{64}$' AND content_hash ~ '^[0-9a-f]{64}$' AND (browser_runner_image_digest IS NULL OR browser_runner_image_digest ~ '^[0-9a-f]{64}$')),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_14d0 CHECK (language_configuration IS NULL OR (jsonb_typeof(language_configuration) = 'object' AND language_configuration ?& ARRAY['frontend', 'backend'] AND language_configuration - ARRAY['frontend', 'backend'] = '{}'::jsonb AND language_configuration -> 'frontend' IN ('null'::jsonb, '"STATIC_ASSETS"', '"JAVASCRIPT"', '"TYPESCRIPT"') AND language_configuration -> 'backend' IN ('null'::jsonb, '"JAVASCRIPT"', '"TYPESCRIPT"', '"PHP"') AND (language_configuration ->> 'frontend' IS NOT NULL OR language_configuration ->> 'backend' IS NOT NULL)) IS TRUE),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_4d4d CHECK (profile_version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$'),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_7241 CHECK ((kind IN ('CONTRACT_TESTS', 'RUNNER_BUILD', 'CI_VERIFICATION', 'ENVIRONMENT_MANIFEST', 'KNOWN_LIMITATIONS', 'REPRODUCIBILITY') AND language_configuration IS NULL) OR (kind IN ('VALID_FIXTURE_RUN', 'FAILURE_REPAIR_RERUN', 'BROWSER_EVIDENCE') AND language_configuration IS NOT NULL)),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_d19e CHECK ((evidence_snapshot -> 'evidence_id' = COALESCE(to_jsonb(evidence_id), 'null'::jsonb) AND evidence_snapshot -> 'kind' = COALESCE(to_jsonb(kind), 'null'::jsonb) AND evidence_snapshot -> 'profile_id' = COALESCE(to_jsonb(profile_id), 'null'::jsonb) AND evidence_snapshot -> 'profile_version' = COALESCE(to_jsonb(profile_version), 'null'::jsonb) AND evidence_snapshot -> 'baseline_scope_hash' = COALESCE(to_jsonb(baseline_scope_hash), 'null'::jsonb) AND evidence_snapshot -> 'language_configuration' = COALESCE(to_jsonb(language_configuration), 'null'::jsonb) AND evidence_snapshot -> 'execution_runner_image_digest' = COALESCE(to_jsonb(execution_runner_image_digest), 'null'::jsonb) AND evidence_snapshot -> 'browser_runner_image_digest' = COALESCE(to_jsonb(browser_runner_image_digest), 'null'::jsonb) AND evidence_snapshot -> 'artifact_content_hash' = COALESCE(to_jsonb(artifact_content_hash), 'null'::jsonb) AND evidence_snapshot -> 'reference' = COALESCE(to_jsonb(reference), 'null'::jsonb) AND evidence_snapshot -> 'passed' = COALESCE(to_jsonb(passed), 'null'::jsonb)) IS TRUE),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_e4ee CHECK (evidence_id ~ '^[A-Za-z][A-Za-z0-9]*([._:/-][A-Za-z0-9]+)*$' AND profile_id ~ '^[A-Za-z][A-Za-z0-9]*([._:/-][A-Za-z0-9]+)*$' AND reference ~ '^[A-Za-z][A-Za-z0-9]*([._:/-][A-Za-z0-9]+)*$'),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_e6e8 CHECK ((jsonb_typeof(evidence_snapshot) = 'object' AND evidence_snapshot ?& ARRAY['evidence_id', 'kind', 'profile_id', 'profile_version', 'baseline_scope_hash', 'language_configuration', 'execution_runner_image_digest', 'browser_runner_image_digest', 'artifact_content_hash', 'reference', 'recorded_at', 'passed'] AND evidence_snapshot - ARRAY['evidence_id', 'kind', 'profile_id', 'profile_version', 'baseline_scope_hash', 'language_configuration', 'execution_runner_image_digest', 'browser_runner_image_digest', 'artifact_content_hash', 'reference', 'recorded_at', 'passed'] = '{}'::jsonb) IS TRUE),
    CONSTRAINT ck_web_profile_validation_evidence_ck_web_profile_valid_ea60 CHECK ((jsonb_typeof(evidence_snapshot -> 'recorded_at') = 'string' AND evidence_snapshot ->> 'recorded_at' ~ 'T.*[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?$') IS TRUE)
);
CREATE TABLE web_source_revisions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    version_number integer NOT NULL,
    based_on_revision_id uuid,
    based_on_version_number integer,
    content_hash character varying(64) NOT NULL,
    source_tree_hash character varying(64) NOT NULL,
    validation_scope_hash character varying(64) NOT NULL,
    target character varying(32) NOT NULL,
    layout character varying(32) NOT NULL,
    origin character varying(32) NOT NULL,
    related_failure_signature character varying(64),
    revision_snapshot jsonb NOT NULL,
    created_by_user_id uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_content_hash CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_failure_f428 CHECK (related_failure_signature IS NULL OR related_failure_signature ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_layout CHECK (layout IN ('SINGLE_ROOT', 'FRONTEND_BACKEND')),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_linear_lineage CHECK ((version_number = 1 AND based_on_revision_id IS NULL AND based_on_version_number IS NULL) OR (version_number > 1 AND based_on_revision_id IS NOT NULL AND based_on_version_number = version_number - 1)),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_origin CHECK (origin IN ('GENERATED_PLAN', 'IMPORTED_BROWNFIELD', 'REPAIR_CHANGE_SET', 'DETERMINISTIC_FIXTURE', 'OWNER_EDIT')),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_positiv_3ce9 CHECK (version_number > 0),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_source__3cd9 CHECK (source_tree_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_target CHECK (target IN ('WEB_STATIC', 'WEB_VUE', 'WEB_NODE_EXPRESS', 'WEB_PHP', 'WEB_VUE_NODE')),
    CONSTRAINT ck_web_source_revisions_ck_web_source_revisions_validat_4701 CHECK (validation_scope_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE workflow_checkpoints (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    sequence_number integer NOT NULL,
    schema_version integer NOT NULL,
    parent_checkpoint_id uuid,
    state_version integer NOT NULL,
    state_hash character varying(64) NOT NULL,
    payload_json text NOT NULL,
    payload_hash character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_lineage CHECK ((sequence_number = 1 AND parent_checkpoint_id IS NULL) OR (sequence_number > 1 AND parent_checkpoint_id IS NOT NULL)),
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_payload_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_schema_version CHECK (schema_version >= 1),
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_sequence CHECK (sequence_number >= 1),
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_state_hash CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_checkpoints_ck_workflow_checkpoints_state_version CHECK (state_version >= 1)
);
CREATE TABLE workflow_events (
    id uuid NOT NULL,
    run_id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    sequence_number integer NOT NULL,
    event_type character varying(64) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    payload_json text NOT NULL,
    payload_hash character varying(64) NOT NULL,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_workflow_events_ck_workflow_events_event_type CHECK (event_type IN ('workflow.run.started', 'workflow.stage.changed', 'workflow.waiting_for_human', 'workflow.paused', 'workflow.resumed', 'workflow.cancelled', 'workflow.failed', 'workflow.completed', 'workflow.approved', 'workflow.checkpoint.created', 'budget.warning', 'budget.exhausted')),
    CONSTRAINT ck_workflow_events_ck_workflow_events_payload CHECK (char_length(payload_json) > 0),
    CONSTRAINT ck_workflow_events_ck_workflow_events_payload_hash CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_events_ck_workflow_events_sequence CHECK (sequence_number >= 1)
);
CREATE TABLE workflow_graph_checkpoints (
    run_id uuid NOT NULL,
    checkpoint_namespace character varying(256) NOT NULL,
    checkpoint_id character varying(64) NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    parent_checkpoint_id character varying(64),
    checkpoint_type character varying(64) NOT NULL,
    checkpoint_blob bytea NOT NULL,
    metadata_type character varying(64) NOT NULL,
    metadata_blob bytea NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE workflow_graph_writes (
    run_id uuid NOT NULL,
    checkpoint_namespace character varying(256) NOT NULL,
    checkpoint_id character varying(64) NOT NULL,
    task_id character varying(128) NOT NULL,
    write_index integer NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    task_path character varying(512) NOT NULL,
    channel character varying(256) NOT NULL,
    value_type character varying(64) NOT NULL,
    value_blob bytea NOT NULL
);
CREATE TABLE workflow_runs (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    owner_user_id uuid NOT NULL,
    project_mode character varying(32) NOT NULL,
    current_stage character varying(48) NOT NULL,
    status character varying(48) NOT NULL,
    resume_status character varying(48),
    pending_gate_id uuid,
    state_version integer NOT NULL,
    checkpoint_sequence integer NOT NULL,
    state_hash character varying(64) NOT NULL,
    state_snapshot_json text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT ck_workflow_runs_ck_workflow_runs_checkpoint_sequence CHECK (checkpoint_sequence >= 0),
    CONSTRAINT ck_workflow_runs_ck_workflow_runs_project_mode CHECK (project_mode IN ('GREENFIELD_GENERATION', 'BROWNFIELD_ASSESSMENT')),
    CONSTRAINT ck_workflow_runs_ck_workflow_runs_snapshot CHECK (char_length(state_snapshot_json) > 0),
    CONSTRAINT ck_workflow_runs_ck_workflow_runs_state_hash CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_workflow_runs_ck_workflow_runs_state_version CHECK (state_version >= 1)
);
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT pk_architecture_package_diffs PRIMARY KEY (id);
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT pk_architecture_package_versions PRIMARY KEY (id);
ALTER TABLE ONLY authorized_evaluation_artifacts
    ADD CONSTRAINT pk_authorized_evaluation_artifacts PRIMARY KEY (owner_user_id, project_id, workflow_run_id, artifact_id, version_number);
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT pk_brownfield_intake_versions PRIMARY KEY (id);
ALTER TABLE ONLY evaluation_runs
    ADD CONSTRAINT pk_evaluation_runs PRIMARY KEY (id);
ALTER TABLE ONLY export_bundles
    ADD CONSTRAINT pk_export_bundles PRIMARY KEY (id);
ALTER TABLE ONLY final_reviews
    ADD CONSTRAINT pk_final_reviews PRIMARY KEY (id);
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT pk_high_impact_operation_versions PRIMARY KEY (id);
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT pk_jvm_execution_attempts PRIMARY KEY (id);
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT pk_jvm_governed_operations PRIMARY KEY (id);
ALTER TABLE ONLY jvm_profile_validation_evidence
    ADD CONSTRAINT pk_jvm_profile_validation_evidence PRIMARY KEY (evidence_id);
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT pk_jvm_source_revisions PRIMARY KEY (id);
ALTER TABLE ONLY sandbox_command_results
    ADD CONSTRAINT pk_sandbox_command_results PRIMARY KEY (run_id, ordinal);
ALTER TABLE ONLY sandbox_runs
    ADD CONSTRAINT pk_sandbox_runs PRIMARY KEY (run_id);
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT pk_static_browser_inspections PRIMARY KEY (id);
ALTER TABLE ONLY synthetic_findings
    ADD CONSTRAINT pk_synthetic_findings PRIMARY KEY (evaluation_run_id, twin_id, twin_version, finding_id);
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT pk_web_execution_attempts PRIMARY KEY (id);
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT pk_web_governed_operations PRIMARY KEY (id);
ALTER TABLE ONLY web_profile_validation_evidence
    ADD CONSTRAINT pk_web_profile_validation_evidence PRIMARY KEY (evidence_id);
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT pk_web_source_revisions PRIMARY KEY (id);
ALTER TABLE ONLY workflow_checkpoints
    ADD CONSTRAINT pk_workflow_checkpoints PRIMARY KEY (id);
ALTER TABLE ONLY workflow_events
    ADD CONSTRAINT pk_workflow_events PRIMARY KEY (id);
ALTER TABLE ONLY workflow_graph_checkpoints
    ADD CONSTRAINT pk_workflow_graph_checkpoints PRIMARY KEY (run_id, checkpoint_namespace, checkpoint_id);
ALTER TABLE ONLY workflow_graph_writes
    ADD CONSTRAINT pk_workflow_graph_writes PRIMARY KEY (run_id, checkpoint_namespace, checkpoint_id, task_id, write_index);
ALTER TABLE ONLY workflow_runs
    ADD CONSTRAINT pk_workflow_runs PRIMARY KEY (id);
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT uq_architecture_package_versions_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT uq_architecture_package_versions_project_version UNIQUE (project_id, version_number);
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT uq_brownfield_intake_versions_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT uq_brownfield_intake_versions_project_version UNIQUE (project_id, version_number);
ALTER TABLE ONLY evaluation_runs
    ADD CONSTRAINT uq_evaluation_runs_scope UNIQUE (id, project_id, owner_user_id);
ALTER TABLE ONLY export_bundles
    ADD CONSTRAINT uq_export_bundles_manifest UNIQUE (manifest_id);
ALTER TABLE ONLY export_bundles
    ADD CONSTRAINT uq_export_bundles_run_hash UNIQUE (workflow_run_id, archive_hash);
ALTER TABLE ONLY final_reviews
    ADD CONSTRAINT uq_final_reviews_run_hash UNIQUE (workflow_run_id, content_hash);
ALTER TABLE ONLY final_reviews
    ADD CONSTRAINT uq_final_reviews_run_version UNIQUE (workflow_run_id, version_number);
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT uq_high_impact_operation_versions_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT uq_high_impact_operation_versions_project_version UNIQUE (project_id, version_number);
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT uq_jvm_execution_attempts_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT uq_jvm_execution_attempts_project_id UNIQUE (project_id, id);
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT uq_jvm_execution_attempts_project_number UNIQUE (project_id, attempt_number);
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT uq_jvm_governed_operations_gate_id UNIQUE (gate_id);
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT uq_jvm_source_revisions_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT uq_jvm_source_revisions_project_id UNIQUE (project_id, id);
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT uq_jvm_source_revisions_project_version UNIQUE (project_id, version_number);
ALTER TABLE ONLY sandbox_command_results
    ADD CONSTRAINT uq_sandbox_command_results_run_command UNIQUE (run_id, command_id);
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT uq_static_browser_inspections_gate_id UNIQUE (gate_id);
ALTER TABLE ONLY synthetic_findings
    ADD CONSTRAINT uq_synthetic_findings_sequence UNIQUE (evaluation_run_id, sequence_number);
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT uq_web_execution_attempts_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT uq_web_execution_attempts_project_id UNIQUE (project_id, id);
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT uq_web_execution_attempts_project_number UNIQUE (project_id, attempt_number);
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT uq_web_governed_operations_gate_id UNIQUE (gate_id);
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT uq_web_source_revisions_project_hash UNIQUE (project_id, content_hash);
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT uq_web_source_revisions_project_id UNIQUE (project_id, id);
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT uq_web_source_revisions_project_version UNIQUE (project_id, version_number);
ALTER TABLE ONLY workflow_checkpoints
    ADD CONSTRAINT uq_workflow_checkpoints_run_id UNIQUE (run_id, id);
ALTER TABLE ONLY workflow_checkpoints
    ADD CONSTRAINT uq_workflow_checkpoints_sequence UNIQUE (run_id, sequence_number);
ALTER TABLE ONLY workflow_events
    ADD CONSTRAINT uq_workflow_events_run_id UNIQUE (run_id, id);
ALTER TABLE ONLY workflow_events
    ADD CONSTRAINT uq_workflow_events_sequence UNIQUE (run_id, sequence_number);
ALTER TABLE ONLY workflow_runs
    ADD CONSTRAINT uq_workflow_runs_scope UNIQUE (id, project_id, owner_user_id);
CREATE INDEX ix_architecture_package_diffs_project_created ON architecture_package_diffs USING btree (project_id, created_at);
CREATE INDEX ix_architecture_package_versions_project_version ON architecture_package_versions USING btree (project_id, version_number);
CREATE INDEX ix_brownfield_intake_versions_project_version ON brownfield_intake_versions USING btree (project_id, version_number);
CREATE INDEX ix_evaluation_runs_project_completed ON evaluation_runs USING btree (project_id, completed_at);
CREATE INDEX ix_evaluation_runs_workflow_completed ON evaluation_runs USING btree (workflow_run_id, completed_at);
CREATE INDEX ix_export_bundles_project_created ON export_bundles USING btree (project_id, created_at);
CREATE INDEX ix_final_reviews_project_created ON final_reviews USING btree (project_id, created_at);
CREATE INDEX ix_final_reviews_run_version ON final_reviews USING btree (workflow_run_id, version_number);
CREATE INDEX ix_high_impact_operation_versions_project_version ON high_impact_operation_versions USING btree (project_id, version_number);
CREATE INDEX ix_jvm_execution_attempts_project_number ON jvm_execution_attempts USING btree (project_id, attempt_number);
CREATE INDEX ix_jvm_governed_operations_project_created ON jvm_governed_operations USING btree (project_id, created_at);
CREATE INDEX ix_jvm_profile_validation_evidence_profile_version ON jvm_profile_validation_evidence USING btree (profile_id, profile_version);
CREATE INDEX ix_jvm_source_revisions_project_version ON jvm_source_revisions USING btree (project_id, version_number);
CREATE INDEX ix_sandbox_command_results_run_ordinal ON sandbox_command_results USING btree (run_id, ordinal);
CREATE INDEX ix_sandbox_runs_project_recorded ON sandbox_runs USING btree (project_id, recorded_at);
CREATE INDEX ix_static_browser_inspections_project_created ON static_browser_inspections USING btree (project_id, created_at);
CREATE INDEX ix_synthetic_findings_project_severity ON synthetic_findings USING btree (project_id, severity);
CREATE INDEX ix_synthetic_findings_run_sequence ON synthetic_findings USING btree (evaluation_run_id, sequence_number);
CREATE INDEX ix_synthetic_findings_twin ON synthetic_findings USING btree (twin_id, twin_version);
CREATE INDEX ix_web_execution_attempts_project_number ON web_execution_attempts USING btree (project_id, attempt_number);
CREATE INDEX ix_web_governed_operations_project_created ON web_governed_operations USING btree (project_id, created_at);
CREATE INDEX ix_web_profile_validation_evidence_profile_version ON web_profile_validation_evidence USING btree (profile_id, profile_version);
CREATE INDEX ix_web_source_revisions_project_version ON web_source_revisions USING btree (project_id, version_number);
CREATE INDEX ix_workflow_checkpoints_run_sequence ON workflow_checkpoints USING btree (run_id, sequence_number);
CREATE INDEX ix_workflow_events_project_occurred ON workflow_events USING btree (project_id, occurred_at);
CREATE INDEX ix_workflow_events_run_sequence ON workflow_events USING btree (run_id, sequence_number);
CREATE INDEX ix_workflow_graph_checkpoints_latest ON workflow_graph_checkpoints USING btree (run_id, checkpoint_namespace, checkpoint_id);
CREATE INDEX ix_workflow_graph_writes_checkpoint ON workflow_graph_writes USING btree (run_id, checkpoint_namespace, checkpoint_id);
CREATE INDEX ix_workflow_runs_owner_status ON workflow_runs USING btree (owner_user_id, status);
CREATE INDEX ix_workflow_runs_project_updated ON workflow_runs USING btree (project_id, updated_at);
CREATE UNIQUE INDEX uq_architecture_package_diffs_pending_base ON architecture_package_diffs USING btree (project_id, base_version_id) WHERE ((status)::text = 'PROPOSED'::text);
CREATE UNIQUE INDEX uq_jvm_governed_operations_project_running ON jvm_governed_operations USING btree (project_id) WHERE ((state)::text = 'RUNNING'::text);
CREATE UNIQUE INDEX uq_web_governed_operations_project_running ON web_governed_operations USING btree (project_id) WHERE ((state)::text = 'RUNNING'::text);
CREATE TRIGGER jvm_governed_operation_guard BEFORE DELETE OR UPDATE ON jvm_governed_operations FOR EACH ROW EXECUTE FUNCTION protect_jvm_governed_operation();
CREATE TRIGGER jvm_governed_operation_no_truncate BEFORE TRUNCATE ON jvm_governed_operations FOR EACH STATEMENT EXECUTE FUNCTION protect_jvm_governed_operation();
CREATE TRIGGER static_browser_inspection_guard BEFORE DELETE OR UPDATE ON static_browser_inspections FOR EACH ROW EXECUTE FUNCTION protect_static_browser_inspection();
CREATE TRIGGER trg_architecture_package_versions_immutable BEFORE DELETE OR UPDATE ON architecture_package_versions FOR EACH ROW EXECUTE FUNCTION reject_architecture_package_version_mutation();
CREATE TRIGGER trg_authorized_evaluation_artifacts_immutable BEFORE DELETE OR UPDATE ON authorized_evaluation_artifacts FOR EACH ROW EXECUTE FUNCTION reject_authorized_evaluation_artifact_mutation();
CREATE TRIGGER trg_brownfield_intake_versions_immutable BEFORE DELETE OR UPDATE ON brownfield_intake_versions FOR EACH ROW EXECUTE FUNCTION reject_brownfield_intake_version_mutation();
CREATE TRIGGER trg_evaluation_runs_immutable BEFORE DELETE OR UPDATE ON evaluation_runs FOR EACH ROW EXECUTE FUNCTION reject_evaluation_run_mutation();
CREATE TRIGGER trg_export_bundles_immutable BEFORE DELETE OR UPDATE ON export_bundles FOR EACH ROW EXECUTE FUNCTION reject_export_bundle_mutation();
CREATE TRIGGER trg_final_reviews_immutable BEFORE DELETE OR UPDATE ON final_reviews FOR EACH ROW EXECUTE FUNCTION reject_final_review_mutation();
CREATE TRIGGER trg_high_impact_operation_versions_immutable BEFORE DELETE OR UPDATE ON high_impact_operation_versions FOR EACH ROW EXECUTE FUNCTION reject_high_impact_operation_version_mutation();
CREATE TRIGGER trg_jvm_execution_attempts_immutable BEFORE DELETE OR UPDATE ON jvm_execution_attempts FOR EACH ROW EXECUTE FUNCTION reject_jvm_execution_attempt_mutation();
CREATE TRIGGER trg_jvm_profile_validation_evidence_immutable BEFORE DELETE OR UPDATE ON jvm_profile_validation_evidence FOR EACH ROW EXECUTE FUNCTION reject_jvm_profile_validation_evidence_mutation();
CREATE TRIGGER trg_jvm_profile_validation_evidence_no_truncate BEFORE TRUNCATE ON jvm_profile_validation_evidence FOR EACH STATEMENT EXECUTE FUNCTION reject_jvm_profile_validation_evidence_mutation();
CREATE TRIGGER trg_jvm_source_revisions_immutable BEFORE DELETE OR UPDATE ON jvm_source_revisions FOR EACH ROW EXECUTE FUNCTION reject_jvm_source_revision_mutation();
CREATE TRIGGER trg_sandbox_command_results_immutable BEFORE DELETE OR UPDATE ON sandbox_command_results FOR EACH ROW EXECUTE FUNCTION reject_sandbox_evidence_mutation();
CREATE TRIGGER trg_sandbox_runs_immutable BEFORE DELETE OR UPDATE ON sandbox_runs FOR EACH ROW EXECUTE FUNCTION reject_sandbox_evidence_mutation();
CREATE TRIGGER trg_synthetic_findings_immutable BEFORE DELETE OR UPDATE ON synthetic_findings FOR EACH ROW EXECUTE FUNCTION reject_synthetic_finding_mutation();
CREATE TRIGGER trg_web_execution_attempts_immutable BEFORE DELETE OR UPDATE ON web_execution_attempts FOR EACH ROW EXECUTE FUNCTION reject_web_execution_attempt_mutation();
CREATE TRIGGER trg_web_profile_validation_evidence_immutable BEFORE DELETE OR UPDATE ON web_profile_validation_evidence FOR EACH ROW EXECUTE FUNCTION reject_web_profile_validation_evidence_mutation();
CREATE TRIGGER trg_web_profile_validation_evidence_no_truncate BEFORE TRUNCATE ON web_profile_validation_evidence FOR EACH STATEMENT EXECUTE FUNCTION reject_web_profile_validation_evidence_mutation();
CREATE TRIGGER trg_web_source_revisions_immutable BEFORE DELETE OR UPDATE ON web_source_revisions FOR EACH ROW EXECUTE FUNCTION reject_web_source_revision_mutation();
CREATE TRIGGER trg_workflow_checkpoints_immutable BEFORE DELETE OR UPDATE ON workflow_checkpoints FOR EACH ROW EXECUTE FUNCTION reject_workflow_checkpoint_mutation();
CREATE TRIGGER trg_workflow_events_immutable BEFORE DELETE OR UPDATE ON workflow_events FOR EACH ROW EXECUTE FUNCTION reject_workflow_event_mutation();
CREATE TRIGGER web_governed_operation_guard BEFORE DELETE OR UPDATE ON web_governed_operations FOR EACH ROW EXECUTE FUNCTION protect_web_governed_operation();
CREATE TRIGGER web_governed_operation_no_truncate BEFORE TRUNCATE ON web_governed_operations FOR EACH STATEMENT EXECUTE FUNCTION protect_web_governed_operation();
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT fk_architecture_package_diffs_applied_version FOREIGN KEY (applied_version_id) REFERENCES architecture_package_versions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT fk_architecture_package_diffs_base_version FOREIGN KEY (base_version_id) REFERENCES architecture_package_versions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT fk_architecture_package_diffs_decider FOREIGN KEY (decided_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT fk_architecture_package_diffs_owner FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_diffs
    ADD CONSTRAINT fk_architecture_package_diffs_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT fk_architecture_package_versions_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT fk_architecture_package_versions_previous FOREIGN KEY (project_id, based_on_version_number) REFERENCES architecture_package_versions(project_id, version_number) ON DELETE RESTRICT;
ALTER TABLE ONLY architecture_package_versions
    ADD CONSTRAINT fk_architecture_package_versions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY authorized_evaluation_artifacts
    ADD CONSTRAINT fk_authorized_evaluation_artifacts_workflow_scope FOREIGN KEY (workflow_run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT fk_brownfield_intake_versions_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT fk_brownfield_intake_versions_previous FOREIGN KEY (project_id, based_on_version_number) REFERENCES brownfield_intake_versions(project_id, version_number) ON DELETE RESTRICT;
ALTER TABLE ONLY brownfield_intake_versions
    ADD CONSTRAINT fk_brownfield_intake_versions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY evaluation_runs
    ADD CONSTRAINT fk_evaluation_runs_workflow_scope FOREIGN KEY (workflow_run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY export_bundles
    ADD CONSTRAINT fk_export_bundles_workflow_scope FOREIGN KEY (workflow_run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY final_reviews
    ADD CONSTRAINT fk_final_reviews_parent FOREIGN KEY (parent_review_id) REFERENCES final_reviews(id) ON DELETE RESTRICT;
ALTER TABLE ONLY final_reviews
    ADD CONSTRAINT fk_final_reviews_workflow_scope FOREIGN KEY (workflow_run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT fk_high_impact_operation_versions_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT fk_high_impact_operation_versions_previous FOREIGN KEY (project_id, based_on_version_number) REFERENCES high_impact_operation_versions(project_id, version_number) ON DELETE RESTRICT;
ALTER TABLE ONLY high_impact_operation_versions
    ADD CONSTRAINT fk_high_impact_operation_versions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT fk_jvm_execution_attempts_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT fk_jvm_execution_attempts_previous FOREIGN KEY (project_id, previous_attempt_id) REFERENCES jvm_execution_attempts(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT fk_jvm_execution_attempts_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_execution_attempts
    ADD CONSTRAINT fk_jvm_execution_attempts_source_revision FOREIGN KEY (project_id, source_revision_id) REFERENCES jvm_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT fk_jvm_governed_operations_gate_id_human_gates FOREIGN KEY (gate_id) REFERENCES human_gates(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT fk_jvm_governed_operations_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT fk_jvm_governed_operations_project_id_projects FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_governed_operations
    ADD CONSTRAINT fk_jvm_governed_operations_source FOREIGN KEY (project_id, source_revision_id) REFERENCES jvm_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT fk_jvm_source_revisions_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT fk_jvm_source_revisions_predecessor_id FOREIGN KEY (project_id, based_on_revision_id) REFERENCES jvm_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT fk_jvm_source_revisions_predecessor_version FOREIGN KEY (project_id, based_on_version_number) REFERENCES jvm_source_revisions(project_id, version_number) ON DELETE RESTRICT;
ALTER TABLE ONLY jvm_source_revisions
    ADD CONSTRAINT fk_jvm_source_revisions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY sandbox_command_results
    ADD CONSTRAINT fk_sandbox_command_results_run FOREIGN KEY (run_id) REFERENCES sandbox_runs(run_id) ON DELETE RESTRICT;
ALTER TABLE ONLY sandbox_runs
    ADD CONSTRAINT fk_sandbox_runs_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY sandbox_runs
    ADD CONSTRAINT fk_sandbox_runs_intake FOREIGN KEY (intake_id) REFERENCES brownfield_intake_versions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY sandbox_runs
    ADD CONSTRAINT fk_sandbox_runs_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT fk_static_browser_inspections_gate_id_human_gates FOREIGN KEY (gate_id) REFERENCES human_gates(id) ON DELETE RESTRICT;
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT fk_static_browser_inspections_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT fk_static_browser_inspections_project_id_projects FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY static_browser_inspections
    ADD CONSTRAINT fk_static_browser_inspections_source_revision_id_web_so_4461 FOREIGN KEY (source_revision_id) REFERENCES web_source_revisions(id) ON DELETE RESTRICT;
ALTER TABLE ONLY synthetic_findings
    ADD CONSTRAINT fk_synthetic_findings_evaluation_scope FOREIGN KEY (evaluation_run_id, project_id, owner_user_id) REFERENCES evaluation_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT fk_web_execution_attempts_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT fk_web_execution_attempts_previous FOREIGN KEY (project_id, previous_attempt_id) REFERENCES web_execution_attempts(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT fk_web_execution_attempts_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_execution_attempts
    ADD CONSTRAINT fk_web_execution_attempts_source_revision FOREIGN KEY (project_id, source_revision_id) REFERENCES web_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT fk_web_governed_operations_gate_id_human_gates FOREIGN KEY (gate_id) REFERENCES human_gates(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT fk_web_governed_operations_owner_user_id_users FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT fk_web_governed_operations_project_id_projects FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_governed_operations
    ADD CONSTRAINT fk_web_governed_operations_source FOREIGN KEY (project_id, source_revision_id) REFERENCES web_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT fk_web_source_revisions_creator FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT fk_web_source_revisions_predecessor_id FOREIGN KEY (project_id, based_on_revision_id) REFERENCES web_source_revisions(project_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT fk_web_source_revisions_predecessor_version FOREIGN KEY (project_id, based_on_version_number) REFERENCES web_source_revisions(project_id, version_number) ON DELETE RESTRICT;
ALTER TABLE ONLY web_source_revisions
    ADD CONSTRAINT fk_web_source_revisions_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT;
ALTER TABLE ONLY workflow_checkpoints
    ADD CONSTRAINT fk_workflow_checkpoints_parent FOREIGN KEY (run_id, parent_checkpoint_id) REFERENCES workflow_checkpoints(run_id, id) ON DELETE RESTRICT;
ALTER TABLE ONLY workflow_checkpoints
    ADD CONSTRAINT fk_workflow_checkpoints_run_scope FOREIGN KEY (run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY workflow_events
    ADD CONSTRAINT fk_workflow_events_run_scope FOREIGN KEY (run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY workflow_graph_checkpoints
    ADD CONSTRAINT fk_workflow_graph_checkpoints_run_scope FOREIGN KEY (run_id, project_id, owner_user_id) REFERENCES workflow_runs(id, project_id, owner_user_id) ON DELETE CASCADE;
ALTER TABLE ONLY workflow_runs
    ADD CONSTRAINT fk_workflow_runs_owner FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE ONLY workflow_runs
    ADD CONSTRAINT fk_workflow_runs_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
"""
RESTORE_GATE_TRIGGER = """
CREATE TRIGGER retain_running_jvm_operation_gate BEFORE INSERT OR UPDATE ON human_gates
FOR EACH ROW EXECUTE FUNCTION retain_running_jvm_operation_gate();
"""


def upgrade():
    op.execute(f"DROP TRIGGER {GATE_TRIGGER} ON {GATE_TABLE}")
    for table in TABLES:
        op.drop_table(table)
    for function in (GATE_TRIGGER, *FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}()")


def downgrade():
    op.execute(RESTORE_FUNCTIONS)
    op.execute(RESTORE_TABLES)
    op.execute(RESTORE_GATE_TRIGGER)
