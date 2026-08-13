import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { userModelingApi } from "../api/userModeling";

import ProjectUserModelingFlow from "./ProjectUserModelingFlow.vue";

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

const PERSONA_VERSION_ONE_ID = "00000000-0000-4000-8000-000000000021";

const PERSONA_VERSION_TWO_ID = "00000000-0000-4000-8000-000000000022";

const TWIN_ID = "00000000-0000-4000-8000-000000000030";

const TWIN_VERSION_ONE_ID = "00000000-0000-4000-8000-000000000031";

const TWIN_VERSION_TWO_ID = "00000000-0000-4000-8000-000000000032";

const SNAPSHOT_ONE_ID = "00000000-0000-4000-8000-000000000040";

const SNAPSHOT_TWO_ID = "00000000-0000-4000-8000-000000000041";

const DIFF_ID = "00000000-0000-4000-8000-000000000050";

const GATE_ONE_ID = "00000000-0000-4000-8000-000000000060";

const GATE_TWO_ID = "00000000-0000-4000-8000-000000000061";

const BRIEF_VERSION_ID = "00000000-0000-4000-8000-000000000070";

const TEAM_VERSION_ID = "00000000-0000-4000-8000-000000000080";

const ACCESS_TOKEN = "test-access-token";

const CREATED_AT = "2026-08-13T15:00:00+00:00";

const DECIDED_AT = "2026-08-13T15:10:00+00:00";

const briefReference = {
  artifact_id: BRIEF_VERSION_ID,

  version_number: 1,

  content_hash: "b".repeat(64),
};

const teamReference = {
  artifact_id: TEAM_VERSION_ID,

  version_number: 1,

  content_hash: "c".repeat(64),
};

const personaRoleObservation: ProfileObservationPayload = {
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

      source_id: BRIEF_VERSION_ID,

      source_version: 1,

      content_hash: briefReference.content_hash,

      locator: "target_users[0]",

      summary: "Role stated in the approved Project Brief.",
    },
  ],

  human_validation: "NOT_REQUIRED",

  rationale: null,
};

const pendingPersona: PersonaVersionPayload = {
  id: PERSONA_VERSION_ONE_ID,

  project_id: PROJECT_ID,

  persona_id: PERSONA_ID,

  version_number: 1,

  based_on_version_number: null,

  content_hash: "d".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  profile: {
    name: "Hotel Receptionist",

    source: "SYSTEM_PROPOSED",

    kind: "PROTO_PERSONA",

    confirmation_status: "PENDING_CONFIRMATION",

    rejection_reason: null,

    observations: [personaRoleObservation],
  },
};

const confirmedPersona: PersonaVersionPayload = {
  ...pendingPersona,

  id: PERSONA_VERSION_TWO_ID,

  version_number: 2,

  based_on_version_number: 1,

  content_hash: "e".repeat(64),

  profile: {
    ...pendingPersona.profile,

    confirmation_status: "CONFIRMED",
  },
};

const initialGoalsObservation: ProfileObservationPayload = {
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

      source_id: "fake-deterministic-user-modeling",

      source_version: 1,

      content_hash: "f".repeat(64),

      locator: "user_twin.goals",

      summary: "Deterministic User Modeling proposal.",
    },
  ],

  human_validation: "REQUIRED",

  rationale: "The approved brief does not directly state this goal.",
};

const revisedGoalsObservation: ProfileObservationPayload = {
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

      source_id: OWNER_ID,

      source_version: null,

      content_hash: null,

      locator: "user_twin.goals",

      summary: "Owner-provided profile revision.",
    },
  ],

  human_validation: "NOT_REQUIRED",

  rationale: null,
};

const twinVersionOne: UserTwinVersionPayload = {
  id: TWIN_VERSION_ONE_ID,

  project_id: PROJECT_ID,

  twin_id: TWIN_ID,

  version_number: 1,

  based_on_version_number: null,

  content_hash: "1".repeat(64),

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

    project_brief_reference: briefReference,

    agent_team_reference: teamReference,

    catalog_version: 1,

    catalog_content_hash: "2".repeat(64),

    validation_status: "PROJECT_GROUNDED_UT",

    observations: [initialGoalsObservation],
  },
};

const twinVersionTwo: UserTwinVersionPayload = {
  ...twinVersionOne,

  id: TWIN_VERSION_TWO_ID,

  version_number: 2,

  based_on_version_number: 1,

  content_hash: "3".repeat(64),

  profile: {
    ...twinVersionOne.profile,

    validation_status: "PROJECT_GROUNDED_UT",

    observations: [revisedGoalsObservation],
  },
};

const snapshotOne: UserModelingSnapshotVersionPayload = {
  id: SNAPSHOT_ONE_ID,

  project_id: PROJECT_ID,

  version_number: 1,

  based_on_version_number: null,

  content_hash: "4".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  snapshot: {
    project_id: PROJECT_ID,

    project_brief_reference: briefReference,

    agent_team_reference: teamReference,

    catalog_version: 1,

    catalog_content_hash: "2".repeat(64),

    persona_count: 1,

    twin_count: 1,

    persona_versions: [confirmedPersona],

    twin_versions: [twinVersionOne],
  },
};

const snapshotTwo: UserModelingSnapshotVersionPayload = {
  id: SNAPSHOT_TWO_ID,

  project_id: PROJECT_ID,

  version_number: 2,

  based_on_version_number: 1,

  content_hash: "5".repeat(64),

  created_by_user_id: OWNER_ID,

  created_at: DECIDED_AT,

  snapshot: {
    ...snapshotOne.snapshot,

    twin_versions: [twinVersionTwo],
  },
};

const proposedDiff: UserTwinProfileDiffPayload = {
  id: DIFF_ID,

  project_id: PROJECT_ID,

  base_snapshot_version_id: SNAPSHOT_ONE_ID,

  base_snapshot_version_number: 1,

  base_snapshot_content_hash: snapshotOne.content_hash,

  twin_id: TWIN_ID,

  base_twin_version_id: TWIN_VERSION_ONE_ID,

  base_twin_version_number: 1,

  base_twin_content_hash: twinVersionOne.content_hash,

  proposal_hash: "6".repeat(64),

  status: "PROPOSED",

  operations: [
    {
      field: "goals",

      before: initialGoalsObservation,

      after: revisedGoalsObservation,
    },
  ],

  created_by_user_id: OWNER_ID,

  created_at: CREATED_AT,

  decided_by_user_id: null,

  decided_at: null,

  decision_reason: null,

  applied_snapshot_version_id: null,
};

const approvedDiff: UserTwinProfileDiffPayload = {
  ...proposedDiff,

  status: "APPROVED",

  decided_by_user_id: OWNER_ID,

  decided_at: DECIDED_AT,

  decision_reason: null,

  applied_snapshot_version_id: SNAPSHOT_TWO_ID,
};

const approvedGateOne: HumanGatePayload = {
  id: GATE_ONE_ID,

  project_id: PROJECT_ID,

  owner_user_id: OWNER_ID,

  gate_type: "USER_MODELING",

  artifact: {
    project_id: PROJECT_ID,

    gate_type: "USER_MODELING",

    artifact_id: SNAPSHOT_ONE_ID,

    version: 1,

    content_hash: snapshotOne.content_hash,
  },

  iteration: 1,

  max_iterations: 3,

  status: "APPROVED",

  created_at: CREATED_AT,

  updated_at: DECIDED_AT,

  event_sequence: 2,
};

const pendingGateTwo: HumanGatePayload = {
  id: GATE_TWO_ID,

  project_id: PROJECT_ID,

  owner_user_id: OWNER_ID,

  gate_type: "USER_MODELING",

  artifact: {
    project_id: PROJECT_ID,

    gate_type: "USER_MODELING",

    artifact_id: SNAPSHOT_TWO_ID,

    version: 2,

    content_hash: snapshotTwo.content_hash,
  },

  iteration: 2,

  max_iterations: 3,

  status: "PENDING_APPROVAL",

  created_at: DECIDED_AT,

  updated_at: DECIDED_AT,

  event_sequence: 1,
};

const approvedGateTwo: HumanGatePayload = {
  ...pendingGateTwo,

  status: "APPROVED",

  event_sequence: 2,
};

const readinessSnapshotOne: UserModelingReadinessPayload = {
  snapshot_exists: true,

  snapshot_version_id: SNAPSHOT_ONE_ID,

  snapshot_version_number: 1,

  snapshot_content_hash: snapshotOne.content_hash,

  gate_exists: false,

  gate_id: null,

  gate_status: null,

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

const readinessSnapshotTwo: UserModelingReadinessPayload = {
  snapshot_exists: true,

  snapshot_version_id: SNAPSHOT_TWO_ID,

  snapshot_version_number: 2,

  snapshot_content_hash: snapshotTwo.content_hash,

  gate_exists: false,

  gate_id: null,

  gate_status: null,

  approved_current_snapshot: false,

  workflow_state: "USER_MODELING_REVIEW_REQUIRED",

  twins: [
    {
      twin_id: TWIN_ID,

      version_number: 2,

      persisted_status: "PROJECT_GROUNDED_UT",

      effective_status: "PROJECT_GROUNDED_UT",
    },
  ],
};

const readinessPendingGateTwo: UserModelingReadinessPayload = {
  ...readinessSnapshotTwo,

  gate_exists: true,

  gate_id: GATE_TWO_ID,

  gate_status: "PENDING_APPROVAL",
};

const readinessApprovedGateTwo: UserModelingReadinessPayload = {
  ...readinessPendingGateTwo,

  gate_status: "APPROVED",

  approved_current_snapshot: true,

  workflow_state: "READY_FOR_REQUIREMENTS_DEFINITION",

  twins: [
    {
      twin_id: TWIN_ID,

      version_number: 2,

      persisted_status: "PROJECT_GROUNDED_UT",

      effective_status: "OWNER_APPROVED_UT",
    },
  ],
};

const readinessStaleGate: UserModelingReadinessPayload = {
  ...readinessSnapshotTwo,

  gate_exists: true,

  gate_id: GATE_ONE_ID,

  gate_status: "APPROVED",

  approved_current_snapshot: false,

  workflow_state: "USER_MODELING_REVIEW_REQUIRED",
};

function mountJourney() {
  return mount(ProjectUserModelingFlow, {
    props: {
      projectId: PROJECT_ID,

      accessToken: ACCESS_TOKEN,

      locale: "en",

      autoLoad: false,
    },
  });
}

function requireValue<T>(value: T | null | undefined, label: string): T {
  if (value === null || value === undefined) {
    throw new Error(`${label} was expected but not found`);
  }

  return value;
}

describe("governed User Modeling journey", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("moves from proto-persona to an owner-approved User Twin snapshot without empirical overclaiming", async () => {
    let readinessResponse: UserModelingReadinessPayload = readinessSnapshotOne;

    const proposePersonas = vi.spyOn(userModelingApi, "proposePersonas").mockResolvedValue({
      status: "CREATED",

      issue: null,

      candidate_issue: null,

      proposal_issue: null,

      versions: [pendingPersona],
    });

    const decidePersona = vi.spyOn(userModelingApi, "decidePersona").mockResolvedValue({
      status: "APPLIED",

      issue: null,

      decision_issue: null,

      version: confirmedPersona,
    });

    const generateSnapshot = vi.spyOn(userModelingApi, "generateSnapshot").mockResolvedValue({
      status: "CREATED",

      issue: null,

      proposal_issue: null,

      snapshot_version: snapshotOne,

      twin_versions: [twinVersionOne],
    });

    const proposeRevision = vi.spyOn(userModelingApi, "proposeRevision").mockResolvedValue({
      status: "CREATED",

      issue: null,

      proposal_issue: null,

      diff: proposedDiff,

      twin_version: null,

      snapshot_version: null,
    });

    const decideRevision = vi.spyOn(userModelingApi, "decideRevision").mockResolvedValue({
      status: "APPLIED",

      issue: null,

      proposal_issue: null,

      diff: approvedDiff,

      twin_version: twinVersionTwo,

      snapshot_version: snapshotTwo,
    });

    const submitGate = vi.spyOn(userModelingApi, "submitGate").mockResolvedValue({
      outcome: "APPLIED",

      gate: pendingGateTwo,

      events: [],

      issue: null,
    });

    const decideGate = vi.spyOn(userModelingApi, "decideGate").mockResolvedValue({
      outcome: "APPLIED",

      gate: approvedGateTwo,

      events: [],

      issue: null,
    });

    vi.spyOn(userModelingApi, "getReadiness").mockImplementation(async () => readinessResponse);

    const store = useUserModelingStore();

    const wrapper = mountJourney();

    await wrapper.get('[data-testid="propose-personas"]').trigger("click");

    await flushPromises();

    expect(proposePersonas).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);

    expect(wrapper.text()).toContain("PROTO_PERSONA");

    expect(wrapper.text()).toContain("Pending confirmation");

    expect(wrapper.get('[data-testid="generate-twins"]').attributes("disabled")).toBeDefined();

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

    const confirmed = store.currentPersonas.find((persona) => persona.persona_id === PERSONA_ID);

    expect(requireValue(confirmed, "Confirmed persona").profile.confirmation_status).toBe(
      "CONFIRMED",
    );

    readinessResponse = readinessSnapshotOne;

    await wrapper.get('[data-testid="generate-twins"]').trigger("click");

    await flushPromises();

    expect(generateSnapshot).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);

    expect(store.currentSnapshot?.version_number).toBe(1);

    expect(store.currentTwins).toHaveLength(1);

    const initialTwin = requireValue(
      store.currentTwins.find((twin) => twin.twin_id === TWIN_ID),
      "Initial User Twin",
    );

    expect(initialTwin.profile.validation_status).toBe("PROJECT_GROUNDED_UT");

    const initialGoals = requireValue(
      initialTwin.profile.observations.find(
        (observation) => observation.observation_key === "user_twin.goals",
      ),
      "Initial goals observation",
    );

    expect(initialGoals.epistemic_status).toBe("MODEL_INFERRED");

    expect(initialGoals.human_validation).toBe("REQUIRED");

    await wrapper.get('[data-testid="edit-twin-observation"]').trigger("click");

    await wrapper
      .get('[data-testid="revision-value"]')
      .setValue("Reduce booking errors\nReduce check-in delays");

    await wrapper.get("form").trigger("submit");

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

    expect(store.diffs[DIFF_ID]?.status).toBe("PROPOSED");

    expect(store.currentSnapshot?.version_number).toBe(1);

    readinessResponse = readinessSnapshotTwo;

    await wrapper.get('[data-testid="approve-diff"]').trigger("click");

    await flushPromises();

    expect(decideRevision).toHaveBeenCalledWith(
      PROJECT_ID,
      DIFF_ID,
      {
        decision: "APPROVE",

        reason: null,
      },
      ACCESS_TOKEN,
    );

    expect(store.currentSnapshot?.id).toBe(SNAPSHOT_TWO_ID);

    expect(store.currentSnapshot?.version_number).toBe(2);

    expect(store.diffs[DIFF_ID]?.status).toBe("APPROVED");

    const revisedTwin = requireValue(
      store.currentTwins.find((twin) => twin.twin_id === TWIN_ID),
      "Revised User Twin",
    );

    expect(revisedTwin.version_number).toBe(2);

    expect(revisedTwin.profile.validation_status).toBe("PROJECT_GROUNDED_UT");

    const revisedGoals = requireValue(
      revisedTwin.profile.observations.find(
        (observation) => observation.observation_key === "user_twin.goals",
      ),
      "Revised goals observation",
    );

    expect(revisedGoals.epistemic_status).toBe("USER_PROVIDED");

    expect(revisedGoals.epistemic_status).not.toBe("HUMAN_VALIDATED");

    expect(revisedGoals.epistemic_status).not.toBe("EMPIRICALLY_SUPPORTED");

    const ownerEvidence = revisedGoals.provenance.find(
      (reference) => reference.source_kind === "OWNER_INPUT",
    );

    expect(ownerEvidence).toBeDefined();

    readinessResponse = readinessPendingGateTwo;

    await wrapper.get('[data-testid="submit-gate"]').trigger("click");

    await flushPromises();

    expect(submitGate).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);

    expect(store.currentGate?.artifact.artifact_id).toBe(SNAPSHOT_TWO_ID);

    expect(store.currentGate?.artifact.version).toBe(2);

    expect(store.currentGate?.artifact.content_hash).toBe(snapshotTwo.content_hash);

    expect(store.currentGate?.status).toBe("PENDING_APPROVAL");

    readinessResponse = readinessApprovedGateTwo;

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

    expect(store.currentGate?.status).toBe("APPROVED");

    expect(store.readiness?.approved_current_snapshot).toBe(true);

    expect(store.readiness?.snapshot_version_id).toBe(SNAPSHOT_TWO_ID);

    expect(store.isReadyForRequirements).toBe(true);

    const effectiveLifecycle = store.readiness?.twins.find((twin) => twin.twin_id === TWIN_ID);

    expect(requireValue(effectiveLifecycle, "Effective lifecycle").persisted_status).toBe(
      "PROJECT_GROUNDED_UT",
    );

    expect(requireValue(effectiveLifecycle, "Effective lifecycle").effective_status).toBe(
      "OWNER_APPROVED_UT",
    );

    expect(revisedTwin.profile.validation_status).toBe("PROJECT_GROUNDED_UT");

    expect(revisedGoals.epistemic_status).toBe("USER_PROVIDED");

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "Ready for requirements definition",
    );
  });

  it("does not carry an approved Gate 3 decision across a newer User Modeling snapshot", () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.applySnapshot(snapshotTwo);

    store.currentGate = approvedGateOne;

    store.readiness = readinessStaleGate;

    const wrapper = mountJourney();

    expect(store.currentSnapshot?.id).toBe(SNAPSHOT_TWO_ID);

    expect(store.currentGate?.artifact.artifact_id).toBe(SNAPSHOT_ONE_ID);

    expect(store.readiness?.approved_current_snapshot).toBe(false);

    expect(store.isReadyForRequirements).toBe(false);

    expect(wrapper.text()).toContain(
      "The previous Gate 3 decision does not approve the current snapshot.",
    );

    expect(wrapper.get('[data-testid="effective-lifecycle"]').text()).toContain(
      "PROJECT_GROUNDED_UT",
    );

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "User Modeling still requires owner review.",
    );
  });
});
