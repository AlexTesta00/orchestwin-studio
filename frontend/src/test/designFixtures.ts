import { buildSelectedDesignPackage } from "../components/designPrototype";
import type {
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  HumanGatePayload,
} from "../types/design";

export const DESIGN_PROJECT_ID = "00000000-0000-4000-8000-000000000101";
export const DESIGN_OWNER_ID = "00000000-0000-4000-8000-000000000102";
export const DESIGN_VERSION_ID = "00000000-0000-4000-8000-000000000103";
export const DESIGN_ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000104";
export const SECOND_DESIGN_ALTERNATIVE_ID = "00000000-0000-4000-8000-000000000105";
export const DESIGN_DIFF_ID = "00000000-0000-4000-8000-000000000106";
export const DESIGN_GATE_ID = "00000000-0000-4000-8000-000000000107";
export const DESIGN_CREATED_AT = "2026-08-21T10:00:00Z";

const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000110";
const STORY_ID = "00000000-0000-4000-8000-000000000111";
const CRITERION_ID = "00000000-0000-4000-8000-000000000112";
const TWIN_ID = "00000000-0000-4000-8000-000000000113";

const TWIN_REFERENCE = {
  twin_id: TWIN_ID,
  version_number: 1,
  content_hash: "e".repeat(64),
  name: "Receptionist Twin",
};

export const BASE_DESIGN_PACKAGE: DesignPackagePayload = {
  schema_version: 1,
  project_id: DESIGN_PROJECT_ID,
  grounding: {
    requirements_reference: {
      kind: "REQUIREMENTS_SPECIFICATION",
      artifact_id: "00000000-0000-4000-8000-000000000120",
      version_number: 1,
      content_hash: "a".repeat(64),
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: "00000000-0000-4000-8000-000000000121",
      version_number: 1,
      content_hash: "b".repeat(64),
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: "00000000-0000-4000-8000-000000000122",
      version_number: 1,
      content_hash: "c".repeat(64),
    },
    catalog: {
      version: 1,
      content_hash: "d".repeat(64),
    },
    requirement_ids: [REQUIREMENT_ID],
    user_story_ids: [STORY_ID],
    acceptance_criterion_ids: [CRITERION_ID],
    user_twin_references: [TWIN_REFERENCE],
  },
  alternatives: [
    {
      id: DESIGN_ALTERNATIVE_ID,
      code: "DES-001",
      approach: "GUIDED_WORKFLOW",
      title: "Guided reservation flow",
      summary: "Guide the receptionist through one decision at a time.",
      rationale: "Reduce avoidable cognitive load while keeping recovery visible.",
      requirement_ids: [REQUIREMENT_ID],
      user_story_ids: [STORY_ID],
      acceptance_criterion_ids: [CRITERION_ID],
      user_twin_references: [TWIN_REFERENCE],
      workflows: [
        {
          id: "00000000-0000-4000-8000-000000000130",
          code: "FLOW-001",
          title: "Create a reservation",
          steps: ["Review availability.", "Enter guest details.", "Confirm the reservation."],
          requirement_ids: [REQUIREMENT_ID],
          user_story_ids: [STORY_ID],
        },
      ],
      information_architecture: ["Availability", "Reservation", "Confirmation"],
      accessibility_considerations: ["Keep persistent labels for every control."],
      security_considerations: ["Minimize guest data shown in summaries."],
      advantages: ["The current step remains explicit."],
      trade_offs: ["Frequent users may need additional navigation."],
      assumptions: [],
      open_questions: ["Should an expert shortcut be added later?"],
    },
    {
      id: SECOND_DESIGN_ALTERNATIVE_ID,
      code: "DES-002",
      approach: "DASHBOARD_FIRST",
      title: "Reservation operations dashboard",
      summary: "Keep operational status and frequent actions visible together.",
      rationale: "Support rapid orientation across active reservation work.",
      requirement_ids: [REQUIREMENT_ID],
      user_story_ids: [STORY_ID],
      acceptance_criterion_ids: [CRITERION_ID],
      user_twin_references: [TWIN_REFERENCE],
      workflows: [
        {
          id: "00000000-0000-4000-8000-000000000131",
          code: "FLOW-002",
          title: "Review and create reservations",
          steps: ["Review status.", "Open the action panel.", "Confirm the update."],
          requirement_ids: [REQUIREMENT_ID],
          user_story_ids: [STORY_ID],
        },
      ],
      information_architecture: ["Overview", "Work queue", "Action panel"],
      accessibility_considerations: ["Expose status changes programmatically."],
      security_considerations: ["Reveal detailed guest data deliberately."],
      advantages: ["Frequent actions remain close to status information."],
      trade_offs: ["Higher information density may increase scanning effort."],
      assumptions: [],
      open_questions: [],
    },
  ],
  critiques: [
    {
      id: "00000000-0000-4000-8000-000000000140",
      code: "CRQ-001",
      kind: "SYNTHETIC_USER_TWIN",
      design_alternative_id: DESIGN_ALTERNATIVE_ID,
      user_twin_reference: TWIN_REFERENCE,
      strengths: ["The primary task remains visible."],
      concerns: ["The guided flow may slow down frequent users."],
      unmet_needs: [],
      accessibility_observations: ["Persistent labels support recovery."],
      trust_concerns: ["Real-user trust has not been established."],
      questions: ["Does this sequence match reception work during peak periods?"],
      suggested_changes: ["Validate optional keyboard shortcuts."],
      provenance: [
        {
          source_kind: "MODEL_OUTPUT",
          source_id: "fake-deterministic-design",
          source_version: 1,
          content_hash: null,
          locator: "alternatives.DES-001",
          summary: "Deterministic synthetic critique.",
        },
      ],
      confidence: 0.6,
      epistemic_status: "MODEL_INFERRED",
      human_validation: "REQUIRED",
      rationale: "This is simulated feedback derived from the approved User Twin profile.",
    },
  ],
  recommended_alternative_id: DESIGN_ALTERNATIVE_ID,
  owner_selected_alternative_id: null,
  prototype: null,
  concerns: [
    {
      id: "00000000-0000-4000-8000-000000000150",
      code: "DRK-001",
      summary: "Experienced users may find the guided flow slower.",
      mitigation: "Evaluate keyboard-efficient shortcuts after owner selection.",
      requirement_ids: [REQUIREMENT_ID],
      design_alternative_ids: [DESIGN_ALTERNATIVE_ID],
    },
  ],
  open_questions: ["Which direction should proceed to architecture planning?"],
};

export const SELECTED_DESIGN_PACKAGE = buildSelectedDesignPackage(
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
);

export const UNSELECTED_DESIGN_VERSION: DesignPackageVersionPayload = {
  id: DESIGN_VERSION_ID,
  project_id: DESIGN_PROJECT_ID,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "f".repeat(64),
  package: BASE_DESIGN_PACKAGE,
  created_by_user_id: DESIGN_OWNER_ID,
  created_at: DESIGN_CREATED_AT,
  ready_for_gate: false,
};

export const SELECTED_DESIGN_VERSION: DesignPackageVersionPayload = {
  ...UNSELECTED_DESIGN_VERSION,
  id: "00000000-0000-4000-8000-000000000160",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "1".repeat(64),
  package: SELECTED_DESIGN_PACKAGE,
  ready_for_gate: true,
};

export const PROPOSED_DESIGN_DIFF: DesignPackageDiffPayload = {
  id: DESIGN_DIFF_ID,
  project_id: DESIGN_PROJECT_ID,
  owner_user_id: DESIGN_OWNER_ID,
  base_version_id: DESIGN_VERSION_ID,
  base_version_number: 1,
  base_content_hash: UNSELECTED_DESIGN_VERSION.content_hash,
  proposed_package: SELECTED_DESIGN_PACKAGE,
  proposal_hash: "2".repeat(64),
  changes: [
    {
      kind: "REPLACE",
      artifact_kind: "SELECTION",
      artifact_id: DESIGN_ALTERNATIVE_ID,
      before: null,
      after: {
        owner_selected_alternative_id: DESIGN_ALTERNATIVE_ID,
      },
    },
    {
      kind: "ADD",
      artifact_kind: "PROTOTYPE",
      artifact_id: SELECTED_DESIGN_PACKAGE.prototype?.id ?? DESIGN_ALTERNATIVE_ID,
      before: null,
      after:
        SELECTED_DESIGN_PACKAGE.prototype === null
          ? null
          : { ...SELECTED_DESIGN_PACKAGE.prototype },
    },
  ],
  status: "PROPOSED",
  created_at: DESIGN_CREATED_AT,
  decided_by_user_id: null,
  decided_at: null,
  decision_reason: null,
  applied_version_id: null,
  content_hash: "3".repeat(64),
};

export const PENDING_DESIGN_GATE: HumanGatePayload = {
  id: DESIGN_GATE_ID,
  project_id: DESIGN_PROJECT_ID,
  owner_user_id: DESIGN_OWNER_ID,
  gate_type: "DESIGN",
  artifact: {
    project_id: DESIGN_PROJECT_ID,
    gate_type: "DESIGN",
    artifact_id: SELECTED_DESIGN_VERSION.id,
    version: SELECTED_DESIGN_VERSION.version_number,
    content_hash: SELECTED_DESIGN_VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "PENDING_APPROVAL",
  created_at: DESIGN_CREATED_AT,
  updated_at: DESIGN_CREATED_AT,
  event_sequence: 1,
  resume_status: null,
};
