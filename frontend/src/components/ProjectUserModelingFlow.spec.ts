import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectUserModelingFlow from "./ProjectUserModelingFlow.vue";
import TwinImportPanel from "./TwinImportPanel.vue";
import { createAppI18n } from "@/i18n";

import { userModelingApi } from "../api/userModeling";

import { useTeamStore } from "../stores/team";
import { useUserModelingStore } from "../stores/userModeling";

import type {
  HumanGatePayload,
  PersonaProposalCommandPayload,
  PersonaVersionPayload,
  ProfileObservationPayload,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinProfileDiffPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";
import type { TwinImportPayload } from "../types/twinImports";
import { expectAccessible } from "@/test/axe";

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
    global: {
      plugins: [createAppI18n("en")],
    },
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
    expect(wrapper.get('[data-testid="starting-personas"]').attributes("open")).toBeDefined();

    await wrapper.get('[data-testid="confirm-persona"]').trigger("click");

    await flushPromises();
    await expectAccessible(wrapper.element);

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
    expect(wrapper.findAll('[data-testid="twin-identity"]').length).toBeGreaterThan(0);
    expect(
      wrapper.get('[data-testid="profiles-technical-details"]').attributes("open"),
    ).toBeUndefined();
    expect(
      wrapper.get('[data-testid="twin-technical-details"]').attributes("open"),
    ).toBeUndefined();
    expect(wrapper.get('[data-testid="twin-profile-details"]').attributes("open")).toBeDefined();

    const details = wrapper.findAll('[data-testid="provenance-inspector"]');

    expect(details.length).toBeGreaterThan(0);
  });

  it("replaces an unknown context of use with text accepted by the domain", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    const value = structuredClone(snapshot);
    value.snapshot.twin_versions[0]!.profile.observations = [
      {
        ...goalsObservation,
        observation_key: "user_twin.context_of_use",
        value: { kind: "UNKNOWN", text: null, items: [], reason: null },
      },
    ];
    store.applySnapshot(value);
    const propose = vi.spyOn(store, "proposeRevision").mockResolvedValue({
      status: "CREATED",
      issue: null,
      proposal_issue: null,
      diff: proposedDiff,
      twin_version: null,
      snapshot_version: null,
    });
    const wrapper = mountFlow();
    await wrapper.get('[data-testid="edit-twin-observation"]').trigger("click");
    await wrapper.get('[data-testid="revision-value"]').setValue("At the reception desk");
    await wrapper.get('[data-testid="submit-revision"]').trigger("submit");
    await flushPromises();
    expect(propose).toHaveBeenCalledWith(
      PROJECT_ID,
      TWIN_ID,
      [
        expect.objectContaining({
          field: "context_of_use",
          value: { kind: "TEXT", text: "At the reception desk", items: [], reason: null },
        }),
      ],
      ACCESS_TOKEN,
    );
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
    expect(wrapper.get('[data-testid="twin-profile-details"]').attributes("open")).toBeUndefined();
    expect(wrapper.text()).toContain("Approved profile");
    expect(wrapper.get('[data-testid="starting-personas"]').attributes("open")).toBeUndefined();
  });

  it("offers a conversation with every User Twin and hands the twin to the owner", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const wrapper = mountFlow();
    await flushPromises();

    const button = wrapper.get('[data-testid="open-twin-chat"]');
    expect(button.text()).toBe(`Talk to ${twinVersion.profile.name}`);
    await button.trigger("click");
    expect(wrapper.emitted("open-chat")?.[0]?.[0]).toEqual(twinVersion);
  });

  it("proposes the user profiles by itself once the team is approved and no profile exists", async () => {
    const team = useTeamStore();
    team.projectId = PROJECT_ID;
    team.readiness = { status: "READY_FOR_MAIN_WORKFLOW" };
    const store = useUserModelingStore();
    const load = vi.spyOn(store, "load").mockResolvedValue(undefined);
    const propose = vi
      .spyOn(store, "proposePersonas")
      .mockResolvedValue({} as PersonaProposalCommandPayload);

    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("en")] },
      props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale: "en", autoLoad: true },
    });
    await flushPromises();

    expect(load).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(propose).toHaveBeenCalledTimes(1);
    expect(propose).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);

    await flushPromises();

    expect(propose).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("does not propose by itself before the team approval or when profiles already exist", async () => {
    const team = useTeamStore();
    team.projectId = PROJECT_ID;
    team.readiness = { status: "TEAM_APPROVAL_REQUIRED" };
    const store = useUserModelingStore();
    vi.spyOn(store, "load").mockResolvedValue(undefined);
    const propose = vi
      .spyOn(store, "proposePersonas")
      .mockResolvedValue({} as PersonaProposalCommandPayload);

    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("en")] },
      props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale: "en", autoLoad: true },
    });
    await flushPromises();

    expect(propose).not.toHaveBeenCalled();

    store.activateProject(PROJECT_ID);
    store.personaVersions = [pendingPersona];
    team.readiness = { status: "READY_FOR_MAIN_WORKFLOW" };
    await flushPromises();

    expect(propose).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="propose-personas"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("offers a twin from another project only after the list of twins of this project", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.personaVersions = [confirmedPersona];
    const wrapper = mountFlow();

    expect(wrapper.findComponent(TwinImportPanel).exists()).toBe(false);

    store.applySnapshot({
      ...snapshot,
      snapshot: { ...snapshot.snapshot, twin_count: 0, twin_versions: [] },
    });
    await flushPromises();

    expect(wrapper.find('[aria-labelledby="twins-heading"]').exists()).toBe(true);
    expect(wrapper.findComponent(TwinImportPanel).exists()).toBe(false);

    store.applySnapshot(snapshot);
    await flushPromises();

    const panel = wrapper.findComponent(TwinImportPanel);
    const twinsSection = wrapper.get('[aria-labelledby="twins-heading"]');
    const lastTwin = twinsSection.findAll('[data-testid="open-twin-chat"]').at(-1);
    expect(panel.exists()).toBe(true);
    expect(panel.props("projectId")).toBe(PROJECT_ID);
    expect(panel.props("locale")).toBe("en");
    expect(panel.text()).toContain("Add a twin from another project");
    expect(twinsSection.element.contains(panel.element)).toBe(true);
    expect(
      (lastTwin?.element.compareDocumentPosition(panel.element) ?? 0) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("gives the twin import the language and the authorization of the step", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const authorize = <T>(operation: (token: string) => Promise<T>) => operation(ACCESS_TOKEN);

    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("it")] },
      props: {
        projectId: PROJECT_ID,
        accessToken: ACCESS_TOKEN,
        authorize,
        locale: "it",
        autoLoad: false,
      },
    });

    const panel = wrapper.findComponent(TwinImportPanel);
    expect(panel.props("locale")).toBe("it");
    expect(panel.props("authorize")).toBe(authorize);
    expect(panel.text()).toContain("Aggiungi un twin da un altro progetto");
  });

  it("reloads the step after an import so that the new twin appears and needs a new approval", async () => {
    const importedTwinId = "00000000-0000-4000-8000-000000000032";
    const importedTwin: UserTwinVersionPayload = {
      ...twinVersion,
      id: "00000000-0000-4000-8000-000000000033",
      twin_id: importedTwinId,
      content_hash: "5".repeat(64),
      profile: { ...twinVersion.profile, name: "Night Porter User Twin" },
    };
    const snapshotTwo: UserModelingSnapshotVersionPayload = {
      ...snapshot,
      id: "00000000-0000-4000-8000-000000000041",
      version_number: 2,
      based_on_version_number: 1,
      content_hash: "6".repeat(64),
      snapshot: { ...snapshot.snapshot, twin_count: 2, twin_versions: [twinVersion, importedTwin] },
    };
    const readinessAfterImport: UserModelingReadinessPayload = {
      ...readinessApproved,
      snapshot_version_id: snapshotTwo.id,
      snapshot_version_number: 2,
      snapshot_content_hash: snapshotTwo.content_hash,
      approved_current_snapshot: false,
      workflow_state: "USER_MODELING_REVIEW_REQUIRED",
      twins: [
        ...readinessReview.twins,
        {
          twin_id: importedTwinId,
          version_number: 1,
          persisted_status: "PROJECT_GROUNDED_UT",
          effective_status: "PROJECT_GROUNDED_UT",
        },
      ],
    };
    const importPayload: TwinImportPayload = {
      status: "TWIN_IMPORTED",
      twin: {
        twin_id: importedTwinId,
        version_id: importedTwin.id,
        version_number: 1,
        name: importedTwin.profile.name,
        content_hash: importedTwin.content_hash,
        validation_status: "PROJECT_GROUNDED_UT",
      },
      persona: {
        persona_id: "00000000-0000-4000-8000-000000000022",
        version_id: "00000000-0000-4000-8000-000000000023",
        version_number: 1,
        name: "Night Porter",
      },
      snapshot: {
        version_id: snapshotTwo.id,
        version_number: 2,
        content_hash: snapshotTwo.content_hash,
        twin_count: 2,
      },
      origin: {
        project_id: "00000000-0000-4000-8000-000000000090",
        project_name: "Hotel night desk",
        twin_id: "00000000-0000-4000-8000-000000000091",
        twin_version_number: 3,
        twin_content_hash: "7".repeat(64),
        persona_id: "00000000-0000-4000-8000-000000000092",
        persona_version_number: 2,
        persona_content_hash: "8".repeat(64),
      },
      gate_approval_required: true,
    };
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = readinessApproved;
    store.currentGate = approvedGate;
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessAfterImport);
    vi.spyOn(userModelingApi, "getCurrentSnapshot").mockResolvedValue(snapshotTwo);
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockResolvedValue([snapshot, snapshotTwo]);
    vi.spyOn(userModelingApi, "getCurrentGate").mockResolvedValue(approvedGate);
    vi.spyOn(userModelingApi, "getGateEvents").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([confirmedPersona]);
    const load = vi.spyOn(store, "load");
    const wrapper = mountFlow();

    expect(wrapper.text()).toContain("You have approved these user profiles.");
    expect(wrapper.find('[data-testid="submit-gate"]').exists()).toBe(false);

    wrapper.findComponent(TwinImportPanel).vm.$emit("imported", importPayload);
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(store.currentSnapshot?.id).toBe(snapshotTwo.id);
    expect(
      wrapper.findAll('[data-testid="open-twin-chat"]').map((button) => button.text()),
    ).toEqual([`Talk to ${twinVersion.profile.name}`, "Talk to Night Porter User Twin"]);
    expect(wrapper.text()).not.toContain("You have approved these user profiles.");
    expect(wrapper.text()).toContain(
      "The profiles have changed since your last approval. Review them again.",
    );
    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "Review and approve your user profiles to continue.",
    );
    expect(wrapper.find('[data-testid="submit-gate"]').exists()).toBe(true);
    expect(wrapper.findComponent(TwinImportPanel).exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });
});
