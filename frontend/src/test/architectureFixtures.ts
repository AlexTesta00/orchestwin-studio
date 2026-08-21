import type {
  ArchitecturePackageDiffPayload,
  ArchitecturePackagePayload,
  ArchitecturePackageVersionPayload,
  ArchitectureReadinessPayload,
  HumanGatePayload,
} from "../types/architecture";

export const ARCHITECTURE_PROJECT_ID = "00000000-0000-4000-8000-000000000201";
export const ARCHITECTURE_OWNER_ID = "00000000-0000-4000-8000-000000000202";
export const ARCHITECTURE_VERSION_ID = "00000000-0000-4000-8000-000000000203";
export const ARCHITECTURE_ID = "00000000-0000-4000-8000-000000000204";
export const TEST_PLAN_ID = "00000000-0000-4000-8000-000000000205";
export const FRONTEND_COMPONENT_ID = "00000000-0000-4000-8000-000000000206";
export const BACKEND_COMPONENT_ID = "00000000-0000-4000-8000-000000000207";
export const TEST_CASE_ID = "00000000-0000-4000-8000-000000000208";
export const ARCHITECTURE_DIFF_ID = "00000000-0000-4000-8000-000000000209";
export const ARCHITECTURE_GATE_ID = "00000000-0000-4000-8000-000000000210";
export const ARCHITECTURE_CREATED_AT = "2026-08-21T12:00:00Z";

const REQUIREMENTS_VERSION_ID = "00000000-0000-4000-8000-000000000220";
const DESIGN_VERSION_ID = "00000000-0000-4000-8000-000000000221";
const TEAM_VERSION_ID = "00000000-0000-4000-8000-000000000222";
const USER_MODELING_VERSION_ID = "00000000-0000-4000-8000-000000000223";
const ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000224";
const PROTOTYPE_ID = "00000000-0000-4000-8000-000000000225";
const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000226";
const STORY_ID = "00000000-0000-4000-8000-000000000227";
const CRITERION_ID = "00000000-0000-4000-8000-000000000228";
const TWIN_ID = "00000000-0000-4000-8000-000000000229";
const CONNECTION_ID = "00000000-0000-4000-8000-000000000230";
const DECISION_ID = "00000000-0000-4000-8000-000000000231";
const ENTITY_ID = "00000000-0000-4000-8000-000000000232";
const API_OPERATION_ID = "00000000-0000-4000-8000-000000000233";
const RISK_ID = "00000000-0000-4000-8000-000000000234";
const ENVIRONMENT_ID = "00000000-0000-4000-8000-000000000235";
const QUALITY_GATE_ID = "00000000-0000-4000-8000-000000000236";

export const ARCHITECTURE_PACKAGE: ArchitecturePackagePayload = {
  schema_version: 1,
  project_id: ARCHITECTURE_PROJECT_ID,
  grounding: {
    project_id: ARCHITECTURE_PROJECT_ID,
    design_package_reference: {
      kind: "DESIGN_PACKAGE",
      artifact_id: DESIGN_VERSION_ID,
      version_number: 2,
      content_hash: "a".repeat(64),
    },
    requirements_reference: {
      kind: "REQUIREMENTS_SPECIFICATION",
      artifact_id: REQUIREMENTS_VERSION_ID,
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: TEAM_VERSION_ID,
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: USER_MODELING_VERSION_ID,
      version_number: 1,
      content_hash: "d".repeat(64),
    },
    catalog: {
      version: 1,
      content_hash: "e".repeat(64),
    },
    owner_selected_alternative_id: ALTERNATIVE_ID,
    prototype_id: PROTOTYPE_ID,
    requirement_ids: [REQUIREMENT_ID],
    user_story_ids: [STORY_ID],
    acceptance_criterion_ids: [CRITERION_ID],
    user_twin_references: [
      {
        twin_id: TWIN_ID,
        version_number: 1,
        content_hash: "f".repeat(64),
        name: "Receptionist Twin",
      },
    ],
  },
  architecture: {
    id: ARCHITECTURE_ID,
    code: "ARC-001",
    title: "Reservation platform architecture",
    style: "CLIENT_SERVER",
    summary: "A compact client-server architecture for the selected reservation workflow.",
    selected_design_alternative_id: ALTERNATIVE_ID,
    prototype_id: PROTOTYPE_ID,
    requirement_ids: [REQUIREMENT_ID],
    acceptance_criterion_ids: [CRITERION_ID],
    components: [
      {
        id: FRONTEND_COMPONENT_ID,
        code: "CMP-001",
        name: "Reservation interface",
        kind: "USER_INTERFACE",
        responsibility: "Render the approved workflow with accessible feedback.",
        technology: "Vue 3 and TypeScript",
        interfaces: ["Reservation API"],
        requirement_ids: [REQUIREMENT_ID],
        assumptions: [],
      },
      {
        id: BACKEND_COMPONENT_ID,
        code: "CMP-002",
        name: "Reservation service",
        kind: "APPLICATION_SERVICE",
        responsibility: "Validate and persist reservation commands.",
        technology: "Python and FastAPI",
        interfaces: ["POST /reservations"],
        requirement_ids: [REQUIREMENT_ID],
        assumptions: [],
      },
    ],
    connections: [
      {
        id: CONNECTION_ID,
        code: "CON-001",
        source_component_id: FRONTEND_COMPONENT_ID,
        target_component_id: BACKEND_COMPONENT_ID,
        kind: "CALLS",
        description: "The interface submits reservation commands to the service.",
        data_flows: ["Reservation command", "Reservation confirmation"],
        requirement_ids: [REQUIREMENT_ID],
      },
    ],
    decisions: [
      {
        id: DECISION_ID,
        code: "ADR-001",
        title: "Use a small client-server architecture",
        context: "The selected workflow needs a browser interface and durable state.",
        decision: "Separate the interface from one application API.",
        consequences: ["The interface and API can be tested independently."],
        alternatives_considered: ["A browser-only application."],
        requirement_ids: [REQUIREMENT_ID],
      },
    ],
    data_entities: [
      {
        id: ENTITY_ID,
        code: "ENT-001",
        name: "Reservation",
        description: "The durable booking record.",
        fields: ["id: UUID", "guest_name: string"],
        owning_component_id: BACKEND_COMPONENT_ID,
        requirement_ids: [REQUIREMENT_ID],
      },
    ],
    api_operations: [
      {
        id: API_OPERATION_ID,
        code: "API-001",
        method: "POST",
        path: "/reservations",
        summary: "Create one reservation.",
        owning_component_id: BACKEND_COMPONENT_ID,
        request_schema: "ReservationInput",
        response_schema: "ReservationResponse",
        requirement_ids: [REQUIREMENT_ID],
        acceptance_criterion_ids: [CRITERION_ID],
      },
    ],
    risks: [
      {
        id: RISK_ID,
        code: "ARK-001",
        summary: "Concurrent updates could overwrite reservation state.",
        likelihood: "POSSIBLE",
        impact: "HIGH",
        mitigation: "Use optimistic concurrency and explicit conflict responses.",
        component_ids: [BACKEND_COMPONENT_ID],
        requirement_ids: [REQUIREMENT_ID],
      },
    ],
    quality_attributes: ["Accessible keyboard operation", "Deterministic testability"],
    deployment_view: ["Browser", "Application API", "PostgreSQL"],
    assumptions: [],
    open_questions: ["Which validated execution profile will implement this plan?"],
  },
  test_plan: {
    id: TEST_PLAN_ID,
    code: "TPL-001",
    title: "Reservation architecture test plan",
    strategy: "Verify the selected design through traceable deterministic checks.",
    architecture_id: ARCHITECTURE_ID,
    selected_design_alternative_id: ALTERNATIVE_ID,
    requirement_ids: [REQUIREMENT_ID],
    acceptance_criterion_ids: [CRITERION_ID],
    architecture_component_ids: [FRONTEND_COMPONENT_ID, BACKEND_COMPONENT_ID],
    environments: [
      {
        id: ENVIRONMENT_ID,
        code: "ENV-001",
        name: "Controlled browser and API environment",
        kind: "CONTAINER",
        description: "A local environment with deterministic dependencies.",
        configuration: ["Browser viewport 1280x720", "PostgreSQL test database"],
      },
    ],
    test_cases: [
      {
        id: TEST_CASE_ID,
        code: "TST-001",
        title: "Create a reservation end to end",
        objective: "Verify the approved workflow and visible confirmation state.",
        level: "END_TO_END",
        automation: "AUTOMATED",
        priority: "CRITICAL",
        preconditions: ["The interface, API, and test database are running."],
        steps: ["Open the reservation screen.", "Submit valid reservation data."],
        expected_results: ["The interface displays the reservation confirmation."],
        requirement_ids: [REQUIREMENT_ID],
        acceptance_criterion_ids: [CRITERION_ID],
        architecture_component_ids: [FRONTEND_COMPONENT_ID, BACKEND_COMPONENT_ID],
        design_alternative_ids: [ALTERNATIVE_ID],
        environment_ids: [ENVIRONMENT_ID],
      },
    ],
    quality_gates: [
      {
        id: QUALITY_GATE_ID,
        code: "QGT-001",
        title: "Critical acceptance suite",
        criterion: "All critical automated acceptance tests pass.",
        required_test_case_ids: [TEST_CASE_ID],
        minimum_pass_rate: 100,
        blocking: true,
      },
    ],
    fixtures: ["Minimal reservation fixture"],
    assumptions: [],
    open_questions: [],
  },
  open_questions: ["Which validated execution profile will implement this plan?"],
};

export const ARCHITECTURE_VERSION: ArchitecturePackageVersionPayload = {
  id: ARCHITECTURE_VERSION_ID,
  project_id: ARCHITECTURE_PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "1".repeat(64),
  package: ARCHITECTURE_PACKAGE,
  created_by_user_id: ARCHITECTURE_OWNER_ID,
  created_at: ARCHITECTURE_CREATED_AT,
};

export const ARCHITECTURE_DIFF: ArchitecturePackageDiffPayload = {
  id: ARCHITECTURE_DIFF_ID,
  project_id: ARCHITECTURE_PROJECT_ID,
  owner_user_id: ARCHITECTURE_OWNER_ID,
  base_version_id: ARCHITECTURE_VERSION_ID,
  base_version_number: 1,
  base_content_hash: ARCHITECTURE_VERSION.content_hash,
  proposed_package: {
    ...ARCHITECTURE_PACKAGE,
    open_questions: ["Confirm the execution profile before implementation."],
  },
  proposal_hash: "2".repeat(64),
  changes: [
    {
      kind: "REPLACE",
      artifact_kind: "OPEN_QUESTIONS",
      artifact_id: ARCHITECTURE_ID,
      before: { values: ARCHITECTURE_PACKAGE.open_questions },
      after: { values: ["Confirm the execution profile before implementation."] },
    },
  ],
  status: "PROPOSED",
  created_at: ARCHITECTURE_CREATED_AT,
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
  applied_version_id: null,
  content_hash: "3".repeat(64),
};

export const PENDING_ARCHITECTURE_GATE: HumanGatePayload = {
  id: ARCHITECTURE_GATE_ID,
  project_id: ARCHITECTURE_PROJECT_ID,
  owner_user_id: ARCHITECTURE_OWNER_ID,
  gate_type: "ARCHITECTURE",
  artifact: {
    project_id: ARCHITECTURE_PROJECT_ID,
    gate_type: "ARCHITECTURE",
    artifact_id: ARCHITECTURE_VERSION_ID,
    version: 1,
    content_hash: ARCHITECTURE_VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: ARCHITECTURE_CREATED_AT,
  updated_at: ARCHITECTURE_CREATED_AT,
  event_sequence: 1,
  resume_status: null,
};

export const ARCHITECTURE_READINESS: ArchitectureReadinessPayload = {
  status: "ARCHITECTURE_APPROVAL_REQUIRED",
  version: ARCHITECTURE_VERSION,
  gate: PENDING_ARCHITECTURE_GATE,
  has_package: true,
  approved_current_package: false,
};
