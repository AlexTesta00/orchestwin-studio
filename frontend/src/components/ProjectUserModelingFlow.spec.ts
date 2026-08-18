import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectUserModelingFlow from "./ProjectUserModelingFlow.vue";

import { userModelingApi } from "../api/userModeling";

import { useUserModelingStore } from "../stores/userModeling";

import type {
  HumanGatePayload,
  PersonaVersionPayload,
  ProfileObservationPayload,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinProfileDiffPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";

const PROJECT_ID = "00000000-0000-4000-8000-000000000010";

const OWNER_ID = "00000000-0000-4000-8000-000000000001";

const PERSONA_ID = "00000000-0000-4000-8000-000000000020";

const PERSONA_VERSION_ID = "00000000-0000-4000-8000-000000000021";

const TWIN_ID = "00000000-0000-4000-8000-000000000030";

const TWIN_VERSION_ID = "00000000-0000-4000-8000-000000000031";

const SNAPSHOT_ID = "00000000-0000-4000-8000-000000000040";

const DIFF_ID = "00000000-0000-4000-8000-000000000050";

const GATE_ID = "00000000-0000-4000-8000-000000000060";

const ACCESS_TOKEN = "test-access-token";

const CREATED_AT = "2026-08-13T15:00:00+00:00";

const goalsObservation: ProfileObservationPayload = {
  observation_key: "user_twin.goals",

  value: {
    kind: "ITEMS",
    text: null,
    items: ["Reduce booking errors"],
    reason: null,
  },

  epistemic_status: "MODEL_INFERRED",

  confidence: 0.42,

  provenance: [
    {
      source_kind: "MODEL_OUTPUT",

      source_id: "fake-user-modeling",

      source_version: 1,

      content_hash: "c".repeat(64),

      locator: "user_twin.goals",

      summary: "Deterministic model proposal",
    },
  ],

  human_validation: "REQUIRED",

  rationale: "The brief does not directly state this goal.",
};

const pendingPersona: PersonaVersionPayload = {
  id: PERSONA_VERSION_ID,
  project_id: PROJECT_ID,
  persona_id: PERSONA_ID,
  version_number: 1,
  based_on_version_number: null,

  content_hash: "a".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  profile: {
    name: "Hotel Receptionist",

    source: "SYSTEM_PROPOSED",

    kind: "PROTO_PERSONA",

    confirmation_status: "PENDING_CONFIRMATION",

    rejection_reason: null,

    observations: [
      {
        observation_key: "persona.role",

        value: {
          kind: "TEXT",
          text: "Hotel receptionist",
          items: [],
          reason: null,
        },

        epistemic_status: "USER_PROVIDED",

        confidence: 1,

        provenance: [
          {
            source_kind: "PROJECT_BRIEF",

            source_id: "brief-version",

            source_version: 1,

            content_hash: "b".repeat(64),

            locator: "target_users[0]",

            summary: "Project target user",
          },
        ],

        human_validation: "NOT_REQUIRED",

        rationale: null,
      },
    ],
  },
};

const confirmedPersona: PersonaVersionPayload = {
  ...pendingPersona,

  version_number: 2,

  based_on_version_number: 1,

  content_hash: "d".repeat(64),

  profile: {
    ...pendingPersona.profile,

    confirmation_status: "CONFIRMED",
  },
};

const twinVersion: UserTwinVersionPayload = {
  id: TWIN_VERSION_ID,

  project_id: PROJECT_ID,

  twin_id: TWIN_ID,

  version_number: 1,

  based_on_version_number: null,

  content_hash: "e".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  profile: {
    name: "Receptionist User Twin",

    persona_reference: {
      persona_id: PERSONA_ID,

      version_number: 2,

      content_hash: confirmedPersona.content_hash,

      source: "SYSTEM_PROPOSED",

      kind: "PROTO_PERSONA",

      confirmation_status: "CONFIRMED",
    },

    project_brief_reference: {
      artifact_id: "00000000-0000-4000-8000-000000000070",

      version_number: 1,

      content_hash: "f".repeat(64),
    },

    agent_team_reference: {
      artifact_id: "00000000-0000-4000-8000-000000000080",

      version_number: 1,

      content_hash: "1".repeat(64),
    },

    catalog_version: 1,

    catalog_content_hash: "2".repeat(64),

    validation_status: "PROJECT_GROUNDED_UT",

    observations: [goalsObservation],
  },
};

const snapshot: UserModelingSnapshotVersionPayload = {
  id: SNAPSHOT_ID,

  project_id: PROJECT_ID,

  version_number: 1,

  based_on_version_number: null,

  content_hash: "3".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  snapshot: {
    project_id: PROJECT_ID,

    project_brief_reference: twinVersion.profile.project_brief_reference,

    agent_team_reference: twinVersion.profile.agent_team_reference,

    catalog_version: 1,

    catalog_content_hash: "2".repeat(64),

    persona_count: 1,

    twin_count: 1,

    persona_versions: [confirmedPersona],

    twin_versions: [twinVersion],
  },
};

const readinessReview: UserModelingReadinessPayload = {
  snapshot_exists: true,

  snapshot_version_id: SNAPSHOT_ID,

  snapshot_version_number: 1,

  snapshot_content_hash: snapshot.content_hash,

  gate_exists: true,

  gate_id: GATE_ID,

  gate_status: "PENDING_APPROVAL",

  approved_current_snapshot: false,

  workflow_state: "USER_MODELING_REVIEW_REQUIRED",

  twins: [
    {
      twin_id: TWIN_ID,

      version_number: 1,

      persisted_status: "PROJECT_GROUNDED_UT",

      effective_status: "PROJECT_GROUNDED_UT",
    },
  ],
};

const readinessApproved: UserModelingReadinessPayload = {
  ...readinessReview,

  gate_status: "APPROVED",

  approved_current_snapshot: true,

  workflow_state: "READY_FOR_REQUIREMENTS_DEFINITION",

  twins: [
    {
      twin_id: TWIN_ID,

      version_number: 1,

      persisted_status: "PROJECT_GROUNDED_UT",

      effective_status: "OWNER_APPROVED_UT",
    },
  ],
};

const pendingGate: HumanGatePayload = {
  id: GATE_ID,

  project_id: PROJECT_ID,

  owner_user_id: OWNER_ID,

  gate_type: "USER_MODELING",

  artifact: {
    project_id: PROJECT_ID,

    gate_type: "USER_MODELING",

    artifact_id: SNAPSHOT_ID,

    version: 1,

    content_hash: snapshot.content_hash,
  },

  iteration: 1,

  max_iterations: 3,

  status: "PENDING_APPROVAL",

  created_at: CREATED_AT,

  updated_at: CREATED_AT,

  event_sequence: 1,
};

const approvedGate: HumanGatePayload = {
  ...pendingGate,

  status: "APPROVED",

  event_sequence: 2,
};

const proposedDiff: UserTwinProfileDiffPayload = {
  id: DIFF_ID,

  project_id: PROJECT_ID,

  base_snapshot_version_id: SNAPSHOT_ID,

  base_snapshot_version_number: 1,

  base_snapshot_content_hash: snapshot.content_hash,

  twin_id: TWIN_ID,

  base_twin_version_id: TWIN_VERSION_ID,

  base_twin_version_number: 1,

  base_twin_content_hash: twinVersion.content_hash,

  proposal_hash: "4".repeat(64),

  status: "PROPOSED",

  operations: [
    {
      field: "goals",

      before: goalsObservation,

      after: {
        observation_key: "user_twin.goals",

        value: {
          kind: "ITEMS",

          text: null,

          items: ["Reduce booking errors", "Reduce check-in delays"],

          reason: null,
        },

        epistemic_status: "USER_PROVIDED",

        confidence: 1,

        provenance: [
          {
            source_kind: "OWNER_INPUT",

            source_id: "owner-input",

            source_version: null,

            content_hash: null,

            locator: "user_twin.goals",

            summary: "Owner-provided profile revision.",
          },
        ],

        human_validation: "NOT_REQUIRED",

        rationale: null,
      },
    },
  ],

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  decided_by_user_id: null,

  decided_at: null,

  decision_reason: null,

  applied_snapshot_version_id: null,
};

function mountFlow() {
  return mount(ProjectUserModelingFlow, {
    props: {
      projectId: PROJECT_ID,

      accessToken: ACCESS_TOKEN,

      locale: "en",

      autoLoad: false,
    },
  });
}

describe("ProjectUserModelingFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("confirms a system proposed proto-persona through the owner-controlled action", async () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.personaVersions = [pendingPersona];

    const decidePersona = vi.spyOn(userModelingApi, "decidePersona").mockResolvedValue({
      status: "APPLIED",

      issue: null,

      decision_issue: null,

      version: confirmedPersona,
    });

    const wrapper = mountFlow();

    expect(wrapper.text()).toContain("PROTO_PERSONA");

    expect(wrapper.text()).toContain("Pending confirmation");

    await wrapper.get('[data-testid="confirm-persona"]').trigger("click");

    await flushPromises();

    expect(decidePersona).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      {
        decision: "CONFIRM",

        reason: null,
      },
      ACCESS_TOKEN,
    );

    expect(
      store.currentPersonas.some((persona) => persona.profile.confirmation_status === "CONFIRMED"),
    ).toBe(true);
  });

  it("renders User Twin epistemic status, confidence, validation requirement and provenance", () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.applySnapshot(snapshot);

    store.readiness = readinessReview;

    store.currentGate = pendingGate;

    const wrapper = mountFlow();

    expect(wrapper.text()).toContain("Model inferred");

    expect(wrapper.text()).toContain("42%");

    expect(wrapper.text()).toContain("Human validation required");

    expect(wrapper.text()).toContain("PROJECT_GROUNDED_UT");

    const details = wrapper.findAll('[data-testid="provenance-inspector"]');

    expect(details.length).toBeGreaterThan(0);
  });

  it("creates an explicit ProfileDiff instead of silently mutating a User Twin", async () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.applySnapshot(snapshot);

    store.readiness = readinessReview;

    const proposeRevision = vi.spyOn(userModelingApi, "proposeRevision").mockResolvedValue({
      status: "CREATED",

      issue: null,

      proposal_issue: null,

      diff: proposedDiff,

      twin_version: null,

      snapshot_version: null,
    });

    const wrapper = mountFlow();

    await wrapper.get('[data-testid="edit-twin-observation"]').trigger("click");

    await wrapper
      .get('[data-testid="revision-value"]')
      .setValue("Reduce booking errors\nReduce check-in delays");

    await wrapper.get('[data-testid="submit-revision"]').trigger("submit");

    await flushPromises();

    expect(proposeRevision).toHaveBeenCalledWith(
      PROJECT_ID,
      TWIN_ID,
      {
        replacements: [
          expect.objectContaining({
            field: "goals",

            epistemic_status: "USER_PROVIDED",

            confidence: 1,

            human_validation: "NOT_REQUIRED",
          }),
        ],
      },
      ACCESS_TOKEN,
    );

    expect(store.diffs[DIFF_ID]).toEqual(proposedDiff);

    expect(store.currentSnapshot?.version_number).toBe(1);

    expect(store.currentTwins.some((twin) => twin.version_number === 1)).toBe(true);
  });

  it("derives OWNER_APPROVED_UT after Gate 3 approves the exact current snapshot", async () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.applySnapshot(snapshot);

    store.readiness = readinessReview;

    store.currentGate = pendingGate;

    const decideGate = vi.spyOn(userModelingApi, "decideGate").mockResolvedValue({
      outcome: "APPLIED",

      gate: approvedGate,

      events: [],

      issue: null,
    });

    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessApproved);

    const wrapper = mountFlow();

    await wrapper.get('[data-testid="approve-gate"]').trigger("click");

    await flushPromises();

    expect(decideGate).toHaveBeenCalledWith(
      PROJECT_ID,
      {
        action: "APPROVE",

        reason: null,
      },
      ACCESS_TOKEN,
    );

    expect(store.isReadyForRequirements).toBe(true);

    expect(wrapper.get('[data-testid="effective-lifecycle"]').text()).toContain(
      "OWNER_APPROVED_UT",
    );

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "Ready for requirements definition",
    );

    expect(twinVersion.profile.validation_status).toBe("PROJECT_GROUNDED_UT");
  });
});
