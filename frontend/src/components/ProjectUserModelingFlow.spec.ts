import { createPinia, getActivePinia, setActivePinia } from "pinia";

import { DOMWrapper, flushPromises, mount } from "@vue/test-utils";

import { defineComponent, h, vShow, withDirectives } from "vue";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectUserModelingFlow from "./ProjectUserModelingFlow.vue";
import TwinImportPanel from "./TwinImportPanel.vue";
import { createAppI18n } from "@/i18n";

import {
  clearFollowedGenerations,
  GenerationJobsApiError,
  generationJobsApi,
  type GenerationRequestJob,
} from "../api/generationJobs";
import { UserModelingApiError, userModelingApi } from "../api/userModeling";

import { useTeamStore } from "../stores/team";
import { useUserModelingStore } from "../stores/userModeling";

import type {
  ArchetypePayload,
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

function mountFlow(attachTo?: HTMLElement) {
  return mount(ProjectUserModelingFlow, {
    ...(attachTo === undefined ? {} : { attachTo }),
    global: {
      plugins: [getActivePinia()!, createAppI18n("en")],
    },
    props: {
      projectId: PROJECT_ID,

      accessToken: ACCESS_TOKEN,

      locale: "en",

      autoLoad: false,
    },
  });
}

type FlowWrapper = ReturnType<typeof mountFlow>;

function decisionPrimary(wrapper: FlowWrapper, decision: string) {
  return wrapper.get(
    `[data-testid="twins-decision"][data-decision="${decision}"] [data-testid="decision-primary"]`,
  );
}

async function openTechnicalDetails(wrapper: FlowWrapper): Promise<void> {
  const toggle = wrapper.get(
    '[data-testid="user-modeling-technical-details"] [data-testid="step-technical-details-toggle"]',
  );
  if (toggle.attributes("aria-expanded") !== "true") {
    await toggle.trigger("click");
  }
}

function profilePanel(): DOMWrapper<Element> {
  const panel = document.body.querySelector('[data-testid="side-panel"]');
  if (panel === null) {
    throw new Error("The profile panel is not open");
  }
  return new DOMWrapper(panel);
}

function openProfileInPage(): boolean {
  return document.body.querySelector('[data-testid="twin-profile-details"]') !== null;
}

function emulateVisibility(): () => void {
  const original = Object.getOwnPropertyDescriptor(Element.prototype, "checkVisibility");
  Object.defineProperty(Element.prototype, "checkVisibility", {
    configurable: true,
    value(this: Element) {
      return this.closest('[style*="display: none"]') === null;
    },
  });
  return () => {
    if (original === undefined) {
      Reflect.deleteProperty(Element.prototype, "checkVisibility");
    } else {
      Object.defineProperty(Element.prototype, "checkVisibility", original);
    }
  };
}

describe("ProjectUserModelingFlow", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
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

    expect(wrapper.text()).toContain("Pending confirmation");
    expect(
      wrapper.get('[data-testid="starting-personas"]').element.closest("details:not([open])"),
    ).toBeNull();
    const card = wrapper.get('[data-testid="persona-card"]');
    expect(card.attributes("data-claim-status")).toBe("hypothesis");
    expect(card.text()).toContain("From the brief");

    await openTechnicalDetails(wrapper);
    expect(wrapper.text()).toContain("PROTO_PERSONA");

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
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);

    expect(
      store.currentPersonas.some((persona) => persona.profile.confirmation_status === "CONFIRMED"),
    ).toBe(true);
    expect(wrapper.get('[data-testid="persona-card"]').attributes("data-claim-status")).toBe(
      "confirmed",
    );
    expect(wrapper.get('[data-testid="persona-card"]').text()).toContain("Confirmed by you");
  });

  it("sets a proposed profile aside only with a reason", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.personaVersions = [pendingPersona];
    const decidePersona = vi.spyOn(userModelingApi, "decidePersona").mockResolvedValue({
      status: "APPLIED",
      issue: null,
      decision_issue: null,
      version: {
        ...pendingPersona,
        version_number: 2,
        profile: {
          ...pendingPersona.profile,
          confirmation_status: "REJECTED",
          rejection_reason: "Not our audience",
        },
      },
    });
    const wrapper = mountFlow(document.body.appendChild(document.createElement("div")));

    expect(wrapper.find('[data-testid="reject-persona"]').exists()).toBe(false);
    await wrapper.get('[data-testid="reject-persona-start"]').trigger("click");
    await flushPromises();
    expect(document.activeElement?.id).toBe(`persona-reason-${PERSONA_ID}`);
    expect(wrapper.get(`#persona-reason-${PERSONA_ID}`).attributes("placeholder")).toBe(
      "Explain why this archetype does not describe who will use the product…",
    );

    await wrapper.get('[data-testid="persona-card"] [data-variant="quiet"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="reject-persona"]').exists()).toBe(false);
    expect(document.activeElement?.getAttribute("data-testid")).toBe("reject-persona-start");

    await wrapper.get('[data-testid="reject-persona-start"]').trigger("click");
    await flushPromises();
    const reject = wrapper.get('[data-testid="reject-persona"]');
    expect(reject.attributes("disabled")).toBeDefined();

    await wrapper.get(`#persona-reason-${PERSONA_ID}`).setValue("Not our audience");
    await wrapper.get('[data-testid="reject-persona"]').trigger("click");
    await flushPromises();

    expect(decidePersona).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      { decision: "REJECT", reason: "Not our audience" },
      ACCESS_TOKEN,
    );
    const card = wrapper.get('[data-testid="persona-card"]');
    expect(card.attributes("data-confirmation")).toBe("REJECTED");
    expect(card.text()).toContain("Set aside: Not our audience");
    expect(card.find('[data-testid="confirm-persona"]').exists()).toBe(false);
  });

  it("creates the twins from the bar once every profile is decided", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.personaVersions = [pendingPersona];
    const generate = vi.spyOn(store, "generateSnapshot").mockResolvedValue({
      status: "CREATED",
      issue: null,
      proposal_issue: null,
      snapshot_version: snapshot,
      twin_versions: [twinVersion],
    });
    const wrapper = mountFlow();

    const bar = wrapper.get('[data-testid="twins-decision"][data-decision="generate"]');
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(decisionPrimary(wrapper, "generate").text()).toBe("Create the twins");
    expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeDefined();
    expect(bar.text()).toContain("Confirm or set aside every proposed archetype");

    store.personaVersions = [confirmedPersona];
    await flushPromises();

    expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeUndefined();
    expect(bar.text()).toContain("Confirmed archetypes: 1.");
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await decisionPrimary(wrapper, "generate").trigger("click");
    await flushPromises();

    expect(generate).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it("renders User Twin epistemic status, confidence, validation requirement and provenance", async () => {
    const store = useUserModelingStore();

    store.activateProject(PROJECT_ID);

    store.applySnapshot(snapshot);

    store.readiness = readinessReview;

    store.currentGate = pendingGate;

    const wrapper = mountFlow();

    expect(wrapper.findAll('[data-testid="twin-identity"]').length).toBeGreaterThan(0);
    expect(
      wrapper
        .get(
          '[data-testid="user-modeling-technical-details"] [data-testid="step-technical-details-toggle"]',
        )
        .attributes("aria-expanded"),
    ).toBe("false");
    expect(openProfileInPage()).toBe(false);

    await wrapper.get('[data-testid="open-twin-profile"]').trigger("click");

    expect(openProfileInPage()).toBe(true);
    const profile = profilePanel().get('[data-testid="twin-profile-details"]');
    expect(profile.text()).toContain("Inferred");

    expect(profile.text()).toContain("42%");

    expect(profile.text()).toContain("Human validation required");

    const details = profilePanel().findAll('[data-testid="provenance-inspector"]');

    expect(details.length).toBeGreaterThan(0);

    await profilePanel().get('[data-testid="side-panel-close"]').trigger("click");
    expect(openProfileInPage()).toBe(false);

    await openTechnicalDetails(wrapper);
    expect(wrapper.text()).toContain("PROJECT_GROUNDED_UT");
    expect(wrapper.find('[data-testid="twin-technical-details"]').exists()).toBe(true);
  });

  it("shows every twin as a card with its origin, open hypotheses, goals and a way to talk", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = readinessReview;
    const wrapper = mountFlow();

    const card = wrapper.get('[data-testid="twin-card"]');
    expect(card.attributes("data-claim-status")).toBe("hypothesis");
    expect(card.attributes("data-twin-id")).toBe(TWIN_ID);
    expect(card.get("h3").text()).toBe("Receptionist User Twin");
    expect(card.text()).toContain("From the brief");
    expect(card.get('[data-testid="hypothesis-chip"]').text()).toBe("1 hypothesis to verify");
    expect(card.text()).toContain("Goals");
    expect(card.text()).toContain("Reduce booking errors");
    expect(card.text()).toContain("Unknown");
    expect(wrapper.get('[data-testid="user-modeling-count"]').text()).toBe(
      "1 twin to approve. The twins' answers are simulated: hypotheses to weigh, not opinions of real people.",
    );
  });

  it("frames an approved twin with a confirmed border and names a reused twin by its project", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    const importedTwin: UserTwinVersionPayload = {
      ...twinVersion,
      profile: {
        ...twinVersion.profile,
        observations: [
          {
            ...goalsObservation,
            provenance: [
              ...goalsObservation.provenance,
              {
                source_kind: "SYSTEM_ARTIFACT",
                source_id: "user-twin:00000000-0000-4000-8000-000000000099",
                source_version: 2,
                content_hash: "9".repeat(64),
                locator: "project:00000000-0000-4000-8000-000000000098",
                summary: "Imported from the project Hotel night desk",
              },
            ],
          },
        ],
      },
    };
    store.applySnapshot({
      ...snapshot,
      snapshot: { ...snapshot.snapshot, twin_versions: [importedTwin] },
    });
    store.readiness = readinessApproved;
    store.currentGate = approvedGate;
    const wrapper = mountFlow();

    const card = wrapper.get('[data-testid="twin-card"]');
    expect(card.attributes("data-claim-status")).toBe("confirmed");
    expect(card.text()).toContain("Approved profile");
    expect(card.text()).toContain("Reused from “Hotel night desk”");
    expect(card.find('[data-testid="hypothesis-chip"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="user-modeling-count"]').text()).toContain(
      "1 twin approved by you.",
    );
  });

  it("gives a profile and the twin born from it the same robot", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.personaVersions = [confirmedPersona];
    const wrapper = mountFlow();

    const personaAvatar = wrapper
      .get('[data-testid="persona-card"] [data-testid="twin-identity"]')
      .attributes("data-avatar");

    store.applySnapshot(snapshot);
    await flushPromises();

    expect(
      wrapper
        .get('[data-testid="twin-card"] [data-testid="twin-identity"]')
        .attributes("data-avatar"),
    ).toBe(personaAvatar);
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
    await wrapper.get('[data-testid="open-twin-profile"]').trigger("click");
    const panel = profilePanel();
    await panel.get('[data-testid="edit-twin-observation"]').trigger("click");
    await panel.get('[data-testid="revision-value"]').setValue("At the reception desk");
    await panel.get('[data-testid="submit-revision"]').trigger("submit");
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

    await wrapper.get('[data-testid="open-twin-profile"]').trigger("click");

    const panel = profilePanel();

    await panel.get('[data-testid="edit-twin-observation"]').trigger("click");

    await panel
      .get('[data-testid="revision-value"]')
      .setValue("Reduce booking errors\nReduce check-in delays");

    await panel.get('[data-testid="submit-revision"]').trigger("submit");

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

    expect(panel.get('[data-testid="profile-diff"]').attributes("data-diff-status")).toBe(
      "PROPOSED",
    );
    expect(wrapper.get('[data-testid="twin-pending-diffs"]').text()).toBe(
      "1 change to approve in the profile",
    );
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

    expect(wrapper.get('[data-testid="twins-decision"][data-decision="approve"]').text()).toContain(
      "It does not mean their assumptions have been verified with real users.",
    );

    await decisionPrimary(wrapper, "approve").trigger("click");

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

    await openTechnicalDetails(wrapper);

    expect(wrapper.get('[data-testid="effective-lifecycle"]').text()).toContain(
      "OWNER_APPROVED_UT",
    );

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toBe(
      "Ready for the Definition.",
    );

    expect(twinVersion.profile.validation_status).toBe("PROJECT_GROUNDED_UT");
    expect(openProfileInPage()).toBe(false);
    expect(wrapper.text()).toContain("Approved profile");
    expect(wrapper.text()).toContain("You have approved these user profiles.");
    expect(wrapper.get('[data-testid="starting-personas"]').attributes("open")).toBeUndefined();
    expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(false);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });

  it.each(["en", "it"] as const)(
    "names the region of the step User Twin for screen readers in %s",
    (locale) => {
      const wrapper = mount(ProjectUserModelingFlow, {
        global: { plugins: [createAppI18n(locale)] },
        props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale, autoLoad: false },
      });

      expect(wrapper.get('[data-testid="user-modeling-step"]').attributes("aria-label")).toBe(
        "User Twin",
      );
      wrapper.unmount();
    },
  );

  it.each([
    ["en", " · Decision no. 1"],
    ["it", " · Decisione n. 1"],
  ] as const)(
    "numbers the decision on the twins in %s without a limit of attempts",
    async (locale, counter) => {
      const store = useUserModelingStore();
      store.activateProject(PROJECT_ID);
      store.applySnapshot(snapshot);
      store.readiness = readinessReview;
      store.currentGate = pendingGate;
      const wrapper = mount(ProjectUserModelingFlow, {
        global: { plugins: [createAppI18n(locale)] },
        props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale, autoLoad: false },
      });

      await openTechnicalDetails(wrapper);

      const details = wrapper.get('[data-testid="user-modeling-technical-details"]').text();
      expect(details).toContain(counter);
      expect(details).not.toMatch(/ of 3| di 3/);
      wrapper.unmount();
    },
  );

  it("says in Italian that the approved twins are ready for the Definition", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = readinessApproved;
    store.currentGate = approvedGate;
    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("it")] },
      props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale: "it", autoLoad: false },
    });

    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toBe(
      "Pronto per la Definizione.",
    );
    wrapper.unmount();
  });

  it.each([
    [
      "en",
      "The model did not complete its response. Your project has been preserved. You can try again.",
    ],
    [
      "it",
      "Il modello non ha completato la risposta. Il progetto è stato conservato. Puoi riprovare.",
    ],
  ] as const)(
    "says in %s that the model, not an assistant, did not complete its response",
    async (locale, sentence) => {
      const store = useUserModelingStore();
      store.activateProject(PROJECT_ID);
      store.applySnapshot(snapshot);
      store.readiness = {
        ...readinessReview,
        gate_exists: false,
        gate_id: null,
        gate_status: null,
      };
      vi.spyOn(userModelingApi, "submitGate").mockRejectedValue(new Error("INCOMPLETE_OUTPUT"));
      const wrapper = mount(ProjectUserModelingFlow, {
        global: { plugins: [createAppI18n(locale)] },
        props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale, autoLoad: false },
      });

      await decisionPrimary(wrapper, "approve").trigger("click");
      await flushPromises();

      expect(wrapper.get('[role="alert"]').text()).toContain(sentence);
      expect(wrapper.text()).not.toMatch(/assistant|assistente/i);
      expect(wrapper.emitted("sections-changed")).toBeUndefined();
      wrapper.unmount();
    },
  );

  it("confirms the twins with one press that submits them and then approves them", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const noGate = { ...readinessReview, gate_exists: false, gate_id: null, gate_status: null };
    store.readiness = noGate;
    const submitGate = vi.spyOn(userModelingApi, "submitGate").mockResolvedValue({
      outcome: "APPLIED",
      gate: pendingGate,
      events: [],
      issue: null,
    });
    const decideGate = vi.spyOn(userModelingApi, "decideGate").mockResolvedValue({
      outcome: "APPLIED",
      gate: approvedGate,
      events: [],
      issue: null,
    });
    vi.spyOn(userModelingApi, "getReadiness").mockImplementation(async () =>
      decideGate.mock.calls.length > 0 ? readinessApproved : readinessReview,
    );
    const wrapper = mountFlow();

    const bar = wrapper.get('[data-testid="twins-decision"][data-decision="approve"]');
    expect(bar.attributes("data-gate-pending")).toBe("false");
    expect(bar.find('[data-testid="decision-secondary"]').exists()).toBe(false);
    expect(decisionPrimary(wrapper, "approve").text()).toBe("Confirm the twins and continue");
    expect(wrapper.text()).not.toContain("Prepare for approval");
    expect(wrapper.find('[data-testid="twins-other-decisions"]').exists()).toBe(false);

    await decisionPrimary(wrapper, "approve").trigger("click");
    await flushPromises();

    expect(submitGate).toHaveBeenCalledTimes(1);
    expect(submitGate).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(decideGate).toHaveBeenCalledTimes(1);
    expect(decideGate).toHaveBeenCalledWith(
      PROJECT_ID,
      { action: "APPROVE", reason: null },
      ACCESS_TOKEN,
    );
    expect(submitGate.mock.invocationCallOrder[0]!).toBeLessThan(
      decideGate.mock.invocationCallOrder[0]!,
    );
    expect(store.isReadyForRequirements).toBe(true);
    expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(false);
  });

  it("asks for changes while the twins wait for approval and closes the note once recorded", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = readinessReview;
    store.currentGate = pendingGate;
    const submitGate = vi.spyOn(userModelingApi, "submitGate");
    const decideGate = vi.spyOn(userModelingApi, "decideGate").mockResolvedValue({
      outcome: "APPLIED",
      gate: { ...pendingGate, status: "REVISION_REQUESTED", event_sequence: 2 },
      events: [],
      issue: null,
    });
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessReview);
    const wrapper = mountFlow();

    const approve = wrapper.get('[data-testid="twins-decision"][data-decision="approve"]');
    expect(approve.attributes("data-gate-pending")).toBe("true");
    expect(wrapper.get('[data-testid="twins-other-decisions"]').attributes("open")).toBeUndefined();

    await approve.get('[data-testid="decision-secondary"]').trigger("click");
    const note = approve.get('[data-testid="decision-note"]');
    expect(note.attributes("placeholder")).toBe(
      "Write what does not convince you in the profiles: the note stays in the history of the decisions.",
    );
    await note.setValue("The receptionist works at night");
    await approve.get('[data-testid="decision-send"]').trigger("click");
    await flushPromises();

    expect(submitGate).not.toHaveBeenCalled();
    expect(decideGate).toHaveBeenCalledWith(
      PROJECT_ID,
      { action: "REQUEST_REVISION", reason: "The receptionist works at night" },
      ACCESS_TOKEN,
    );
    expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="user-modeling-gate-notice"]').text()).toContain(
      "You asked for changes.",
    );
  });

  it("shows a failed approval and only approves on the next press", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = { ...readinessReview, gate_exists: false, gate_id: null, gate_status: null };
    const submitGate = vi.spyOn(userModelingApi, "submitGate").mockResolvedValue({
      outcome: "APPLIED",
      gate: pendingGate,
      events: [],
      issue: null,
    });
    const decideGate = vi
      .spyOn(userModelingApi, "decideGate")
      .mockRejectedValueOnce(new Error("TIMEOUT"))
      .mockResolvedValue({ outcome: "APPLIED", gate: approvedGate, events: [], issue: null });
    vi.spyOn(userModelingApi, "getReadiness").mockImplementation(async () =>
      decideGate.mock.calls.length > 1 ? readinessApproved : readinessReview,
    );
    const wrapper = mountFlow();

    await decisionPrimary(wrapper, "approve").trigger("click");
    await flushPromises();

    expect(submitGate).toHaveBeenCalledTimes(1);
    expect(decideGate).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "Model generation timed out. Check model availability before retrying.",
    );
    expect(
      wrapper
        .get('[data-testid="twins-decision"][data-decision="approve"]')
        .attributes("data-gate-pending"),
    ).toBe("true");

    await decisionPrimary(wrapper, "approve").trigger("click");
    await flushPromises();

    expect(submitGate).toHaveBeenCalledTimes(1);
    expect(decideGate).toHaveBeenCalledTimes(2);
    expect(decideGate).toHaveBeenLastCalledWith(
      PROJECT_ID,
      { action: "APPROVE", reason: null },
      ACCESS_TOKEN,
    );
  });

  it("makes no approval when the submission fails", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = { ...readinessReview, gate_exists: false, gate_id: null, gate_status: null };
    const submitGate = vi
      .spyOn(userModelingApi, "submitGate")
      .mockRejectedValue(new Error("PROVIDER_UNAVAILABLE"));
    const decideGate = vi.spyOn(userModelingApi, "decideGate");
    const wrapper = mountFlow();

    await decisionPrimary(wrapper, "approve").trigger("click");
    await flushPromises();

    expect(submitGate).toHaveBeenCalledTimes(1);
    expect(decideGate).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toContain(
      "The local model is unavailable. Check model status above.",
    );
    expect(
      wrapper
        .get('[data-testid="twins-decision"][data-decision="approve"]')
        .attributes("data-gate-pending"),
    ).toBe("false");
  });

  it("rejects the profiles from the other decisions only with a reason", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = readinessReview;
    store.currentGate = pendingGate;
    const decideGate = vi.spyOn(userModelingApi, "decideGate").mockResolvedValue({
      outcome: "APPLIED",
      gate: { ...pendingGate, status: "REJECTED", event_sequence: 2 },
      events: [],
      issue: null,
    });
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue(readinessReview);
    const wrapper = mountFlow();

    const reject = wrapper.get('[data-testid="twins-reject"]');
    expect(reject.attributes("disabled")).toBeDefined();
    await wrapper.get("#gate-three-reason").setValue("Wrong audience");
    await wrapper.get('[data-testid="twins-reject"]').trigger("click");
    await flushPromises();

    expect(decideGate).toHaveBeenCalledWith(
      PROJECT_ID,
      { action: "REJECT", reason: "Wrong audience" },
      ACCESS_TOKEN,
    );
  });

  it("asks to create the twins again when the brief or the perspectives changed", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.readiness = { ...readinessReview, context_current: false };
    store.currentGate = pendingGate;
    const wrapper = mountFlow();

    expect(wrapper.get('[data-testid="user-modeling-stale-context"]').text()).toBe(
      "The brief or the perspectives changed: generate and approve a new User Twin version before continuing.",
    );
    expect(decisionPrimary(wrapper, "generate").text()).toBe("Create the twins again");
    expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[data-testid="twins-other-decisions"]').exists()).toBe(false);
  });

  it.each([
    [
      "en",
      "The brief or the perspectives changed: generate and approve a new User Twin version before continuing.",
      "The brief or the perspectives changed: use «Update and confirm» above to keep these twins and re-anchor them, or create them again.",
    ],
    [
      "it",
      "Brief o prospettive sono cambiati: genera una nuova versione degli User Twin e approvala prima di proseguire.",
      "Brief o prospettive sono cambiati: usa «Aggiorna e conferma» qui sopra per tenere questi twin e riagganciarli, oppure creali di nuovo.",
    ],
  ] as const)(
    "names in %s the gesture above for twins behind the brief or the perspectives only in sections mode",
    async (locale, firstPass, sections) => {
      const store = useUserModelingStore();
      store.activateProject(PROJECT_ID);
      store.applySnapshot(snapshot);
      store.readiness = { ...readinessReview, context_current: false };
      store.currentGate = pendingGate;
      const wrapper = mount(ProjectUserModelingFlow, {
        global: { plugins: [createAppI18n(locale)] },
        props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale, autoLoad: false },
      });

      const notice = () => wrapper.get('[data-testid="user-modeling-stale-context"]').text();
      const bar = () => wrapper.get('[data-testid="twins-decision"][data-decision="generate"]');
      expect(notice()).toBe(firstPass);
      expect(bar().text()).toContain(firstPass);
      expect(notice()).not.toMatch(/team|squadra/i);

      await wrapper.setProps({ sectionsMode: true });

      expect(notice()).toBe(sections);
      expect(bar().text()).toContain(sections);
      expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeUndefined();
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it("mounts its decision in the bar of the page when the page offers one", async () => {
    const target = document.createElement("div");
    target.id = "step-decision-bar";
    document.body.appendChild(target);
    const host = document.createElement("div");
    document.body.appendChild(host);
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.personaVersions = [pendingPersona];
    const wrapper = mountFlow(host);
    await flushPromises();

    expect(target.querySelector('[data-testid="twins-decision"]')).not.toBeNull();
    expect(wrapper.element.querySelector('[data-testid="decision-bar"]')).toBeNull();
    wrapper.unmount();
  });

  it("puts its technical row after the bar of the page and back in the step without it", async () => {
    const row = document.createElement("div");
    row.id = "step-technical-row";
    const host = document.createElement("div");
    document.body.append(row, host);
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const wrapper = mountFlow(host);
    await flushPromises();

    expect(
      row.querySelector(
        '[data-testid="user-modeling-technical-details"] [data-testid="step-technical-details"]',
      ),
    ).not.toBeNull();
    expect(
      wrapper.element.querySelector('[data-testid="user-modeling-technical-details"]'),
    ).toBeNull();
    wrapper.unmount();
    expect(row.childElementCount).toBe(0);
    row.remove();

    const alone = mountFlow(host);
    await flushPromises();
    expect(
      alone.element.querySelector('[data-testid="user-modeling-technical-details"]'),
    ).not.toBeNull();
    alone.unmount();
    host.remove();
  });

  it("takes the bar and the row of the page as soon as its hidden step is shown and active", async () => {
    const bar = document.createElement("div");
    bar.id = "step-decision-bar";
    const row = document.createElement("div");
    row.id = "step-technical-row";
    const host = document.createElement("div");
    document.body.append(bar, row, host);
    const restore = emulateVisibility();
    try {
      vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
      const store = useUserModelingStore();
      store.activateProject(PROJECT_ID);
      store.applySnapshot(snapshot);
      store.readiness = readinessReview;
      store.currentGate = pendingGate;
      const Stage = defineComponent({
        props: { shown: { type: Boolean, required: true } },
        setup(stage) {
          return () =>
            withDirectives(
              h("div", [
                h(ProjectUserModelingFlow, {
                  projectId: PROJECT_ID,
                  accessToken: ACCESS_TOKEN,
                  locale: "en",
                  autoLoad: false,
                  active: stage.shown,
                }),
              ]),
              [[vShow, stage.shown]],
            );
        },
      });
      const wrapper = mount(Stage, {
        attachTo: host,
        props: { shown: false },
        global: { plugins: [createAppI18n("en")] },
      });
      await flushPromises();

      expect(bar.childElementCount).toBe(0);
      expect(row.childElementCount).toBe(0);
      expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(true);

      await wrapper.setProps({ shown: true });
      await flushPromises();

      expect(
        bar.querySelector('[data-testid="twins-decision"] [data-testid="decision-bar"]'),
      ).not.toBeNull();
      expect(row.querySelector('[data-testid="user-modeling-technical-details"]')).not.toBeNull();
      expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(false);
      wrapper.unmount();
    } finally {
      restore();
      bar.remove();
      row.remove();
      host.remove();
    }
  });

  it("takes the bar of the page when it is mounted while its step is being shown", async () => {
    const bar = document.createElement("div");
    bar.id = "step-decision-bar";
    const row = document.createElement("div");
    row.id = "step-technical-row";
    const host = document.createElement("div");
    document.body.append(bar, row, host);
    const restore = emulateVisibility();
    try {
      vi.spyOn(generationJobsApi, "list").mockResolvedValue([]);
      const store = useUserModelingStore();
      store.activateProject(PROJECT_ID);
      store.applySnapshot(snapshot);
      store.readiness = readinessReview;
      store.currentGate = pendingGate;
      const Stage = defineComponent({
        props: { shown: { type: Boolean, required: true } },
        setup(stage) {
          return () =>
            withDirectives(
              h("div", [
                stage.shown
                  ? h(ProjectUserModelingFlow, {
                      projectId: PROJECT_ID,
                      accessToken: ACCESS_TOKEN,
                      locale: "en",
                      autoLoad: false,
                      active: true,
                    })
                  : null,
              ]),
              [[vShow, stage.shown]],
            );
        },
      });
      const wrapper = mount(Stage, {
        attachTo: host,
        props: { shown: false },
        global: { plugins: [createAppI18n("en")] },
      });
      await flushPromises();

      await wrapper.setProps({ shown: true });
      await flushPromises();

      expect(
        bar.querySelector('[data-testid="twins-decision"] [data-testid="decision-bar"]'),
      ).not.toBeNull();
      expect(row.querySelector('[data-testid="user-modeling-technical-details"]')).not.toBeNull();
      wrapper.unmount();
    } finally {
      restore();
      bar.remove();
      row.remove();
      host.remove();
    }
  });

  it("names what gets in the way of a twin without a gendered pronoun", () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    const value = structuredClone(snapshot);
    value.snapshot.twin_versions[0]!.profile.observations = [
      {
        ...goalsObservation,
        observation_key: "user_twin.frustrations",
        value: { kind: "ITEMS", text: null, items: ["Code all'ingresso"], reason: null },
      },
    ];
    store.applySnapshot(value);
    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("it")] },
      props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale: "it", autoLoad: false },
    });

    const card = wrapper.get('[data-testid="twin-card"]');
    expect(card.text()).toContain("Che cosa è di ostacolo");
    expect(card.text()).toContain("Code all'ingresso");
    expect(card.text()).not.toContain("lo frena");
    wrapper.unmount();
  });

  it("offers a conversation with every User Twin and hands the twin to the owner", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const wrapper = mountFlow();
    await flushPromises();

    const button = wrapper.get('[data-testid="open-twin-chat"]');
    expect(button.text()).toBe(`Talk to the twin: ${twinVersion.profile.name}`);
    await button.trigger("click");
    expect(wrapper.emitted("open-chat")?.[0]?.[0]).toEqual(twinVersion);
  });

  it("proposes the user profiles by itself only right after the owner approves the team", async () => {
    const team = useTeamStore();
    team.projectId = PROJECT_ID;
    team.readiness = { status: "TEAM_APPROVAL_REQUIRED" };
    const store = useUserModelingStore();
    const load = vi.spyOn(store, "load").mockResolvedValue(undefined);
    const propose = vi
      .spyOn(store, "proposePersonas")
      .mockResolvedValue({} as PersonaProposalCommandPayload);

    const wrapper = mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("en")] },
      props: {
        projectId: PROJECT_ID,
        accessToken: ACCESS_TOKEN,
        locale: "en",
        autoLoad: true,
        upstream: "team-1:PENDING_APPROVAL",
      },
    });
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(1);
    expect(propose).not.toHaveBeenCalled();

    team.readiness = { status: "READY_FOR_MAIN_WORKFLOW" };
    await wrapper.setProps({ upstream: "team-1:APPROVED" });
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(2);
    expect(propose).toHaveBeenCalledTimes(1);
    expect(propose).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);

    await wrapper.setProps({ upstream: null });
    await wrapper.setProps({ upstream: "team-1:APPROVED" });
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(2);
    expect(propose).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("offers the proposal of the user profiles instead of starting it when the team was approved before", async () => {
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
      props: {
        projectId: PROJECT_ID,
        accessToken: ACCESS_TOKEN,
        locale: "en",
        autoLoad: true,
        upstream: "team-1:APPROVED",
      },
    });
    await flushPromises();

    await wrapper.setProps({ upstream: "team-2:APPROVED" });
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(2);
    expect(propose).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="propose-personas"]').exists()).toBe(true);

    await wrapper.get('[data-testid="propose-personas"]').trigger("click");
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

  it("offers a twin from another project only once the project has twins, before their cards", async () => {
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
    const firstTwin = wrapper.get('[data-testid="twin-card"]');
    expect(panel.exists()).toBe(true);
    expect(panel.props("projectId")).toBe(PROJECT_ID);
    expect(panel.props("locale")).toBe("en");
    expect(panel.text()).toContain("Add a twin from another project");
    expect(
      panel.element.compareDocumentPosition(firstTwin.element) & Node.DOCUMENT_POSITION_FOLLOWING,
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
    expect(wrapper.find('[data-testid="twins-decision"]').exists()).toBe(false);

    wrapper.findComponent(TwinImportPanel).vm.$emit("imported", importPayload);
    await flushPromises();

    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(store.currentSnapshot?.id).toBe(snapshotTwo.id);
    expect(
      wrapper.findAll('[data-testid="open-twin-chat"]').map((button) => button.text()),
    ).toEqual([
      `Talk to the twin: ${twinVersion.profile.name}`,
      "Talk to the twin: Night Porter User Twin",
    ]);
    expect(wrapper.text()).not.toContain("You have approved these user profiles.");
    expect(wrapper.text()).toContain(
      "The profiles have changed since your last approval. Review them again.",
    );
    expect(wrapper.get('[data-testid="requirements-readiness"]').text()).toContain(
      "Review and approve your user profiles to continue.",
    );
    expect(
      wrapper
        .find('[data-testid="twins-decision"][data-decision="approve"][data-gate-pending="false"]')
        .exists(),
    ).toBe(true);
    expect(wrapper.findComponent(TwinImportPanel).exists()).toBe(true);
    await expectAccessible(wrapper.element);
  });
});

describe("ProjectUserModelingFlow archetypes", () => {
  const data = {
    name: "Receptionist",
    description: "Checks in hotel guests",
    role: "Receptionist",
    goals: ["Fast check-in"],
    context: null,
  };
  const archetype: ArchetypePayload = {
    ...data,
    persona_id: PERSONA_ID,
    version_id: PERSONA_VERSION_ID,
    version_number: 2,
    source: "OWNER_PROVIDED",
    confirmation_status: "CONFIRMED",
    archived: false,
  };
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
  });
  afterEach(() => vi.restoreAllMocks());

  it("creates a manual archetype and refreshes the flow without generating twins", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.archetypes = [];
    const create = vi.spyOn(userModelingApi, "createArchetype").mockResolvedValue(archetype);
    vi.spyOn(userModelingApi, "getArchetypes").mockResolvedValue([archetype]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([confirmedPersona]);
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue({
      ...readinessReview,
      snapshot_exists: false,
      archetypes_current: false,
    });
    const generate = vi.spyOn(store, "generateSnapshot");
    const wrapper = mountFlow();
    await wrapper.get('[data-testid="archetype-add"]').trigger("click");
    await wrapper.get('[data-testid="archetype-name"]').setValue(data.name);
    await wrapper.get('[data-testid="archetype-description"]').setValue(data.description);
    await wrapper.get('[data-testid="archetype-role"]').setValue(data.role);
    await wrapper.get('[data-testid="archetype-goals"]').setValue("Fast check-in");
    await wrapper.get('[data-testid="archetype-save"]').trigger("submit");
    await flushPromises();
    expect(create).toHaveBeenCalledWith(PROJECT_ID, data, ACCESS_TOKEN);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(wrapper.find('[data-testid="archetype-save"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("Archetypes");
    expect(decisionPrimary(wrapper, "generate").text()).toContain("Create the twins");
    expect(decisionPrimary(wrapper, "generate").text()).not.toContain("again");
    expect(wrapper.text()).not.toContain("The archetypes changed.");
    expect(generate).not.toHaveBeenCalled();
    await expectAccessible(wrapper.element);
  });

  it("edits with the displayed version and keeps the old snapshot for reference", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.archetypes = [archetype];
    const edited = {
      ...archetype,
      version_number: 3,
      description: "Works the morning reception shift",
    };
    const edit = vi.spyOn(userModelingApi, "editArchetype").mockResolvedValue(edited);
    vi.spyOn(userModelingApi, "getArchetypes").mockResolvedValue([edited]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([
      { ...confirmedPersona, version_number: 3 },
    ]);
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue({
      ...readinessReview,
      context_current: true,
      archetypes_current: false,
    });
    const generate = vi.spyOn(store, "generateSnapshot").mockResolvedValue({
      status: "CREATED",
      issue: null,
      proposal_issue: null,
      snapshot_version: snapshot,
      twin_versions: [twinVersion],
    });
    const wrapper = mountFlow();
    await wrapper.get(`[data-testid="archetype-edit-${PERSONA_ID}"]`).trigger("click");
    await wrapper.get('[data-testid="archetype-description"]').setValue(edited.description);
    await wrapper.get('[data-testid="archetype-save"]').trigger("submit");
    await flushPromises();
    expect(edit).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      { ...data, description: edited.description, based_on_version_number: 2 },
      ACCESS_TOKEN,
    );
    expect(store.currentSnapshot).toEqual(snapshot);
    expect(store.snapshotHistory).toEqual([snapshot]);
    expect(wrapper.text()).toContain("The archetypes changed.");
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeUndefined();
    await decisionPrimary(wrapper, "generate").trigger("click");
    await flushPromises();
    expect(generate).toHaveBeenCalledWith(PROJECT_ID, ACCESS_TOKEN);
    expect(wrapper.emitted("sections-changed")).toHaveLength(2);
  });

  it("requires explicit archival confirmation and preserves snapshot history", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    store.archetypes = [archetype];
    const archive = vi
      .spyOn(userModelingApi, "archiveArchetype")
      .mockResolvedValue({ ...archetype, archived: true, version_number: 3 });
    vi.spyOn(userModelingApi, "getArchetypes").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue({
      ...readinessReview,
      archetypes_current: false,
    });
    const wrapper = mountFlow();
    await wrapper.get(`[data-testid="archetype-delete-${PERSONA_ID}"]`).trigger("click");
    expect(archive).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("history preserved");
    expect(wrapper.text()).toContain("requirements and design");
    await wrapper.get('[data-testid="archetype-delete-confirm"]').trigger("click");
    await flushPromises();
    expect(archive).toHaveBeenCalledWith(
      PROJECT_ID,
      PERSONA_ID,
      { based_on_version_number: 2 },
      ACCESS_TOKEN,
    );
    expect(store.currentSnapshot).toEqual(snapshot);
    expect(store.currentTwins).toEqual([twinVersion]);
    expect(store.currentPersonas).toEqual([]);
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
    expect(decisionPrimary(wrapper, "generate").attributes("disabled")).toBeDefined();
  });

  it("explains a conflict and discards the stale draft only after reloading", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.archetypes = [archetype];
    const edit = vi.spyOn(userModelingApi, "editArchetype").mockRejectedValue(
      new UserModelingApiError("ARCHETYPE_VERSION_CONFLICT", {
        code: "ARCHETYPE_VERSION_CONFLICT",
        status: 409,
        payload: null,
      }),
    );
    vi.spyOn(userModelingApi, "getReadiness").mockResolvedValue({
      ...readinessReview,
      snapshot_exists: false,
      gate_exists: false,
      archetypes_current: false,
    });
    vi.spyOn(userModelingApi, "getCurrentPersonas").mockResolvedValue([confirmedPersona]);
    vi.spyOn(userModelingApi, "getSnapshotHistory").mockResolvedValue([]);
    vi.spyOn(userModelingApi, "getArchetypes").mockResolvedValue([
      { ...archetype, version_number: 3, description: "Current description" },
    ]);
    const wrapper = mountFlow();
    await wrapper.get(`[data-testid="archetype-edit-${PERSONA_ID}"]`).trigger("click");
    await wrapper.get('[data-testid="archetype-save"]').trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("This archetype changed.");
    expect(edit).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted("sections-changed")).toBeUndefined();
    await wrapper.get('[data-testid="archetype-reload"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="archetype-save"]').exists()).toBe(false);
    await wrapper.get(`[data-testid="archetype-edit-${PERSONA_ID}"]`).trigger("click");
    expect(
      (wrapper.get('[data-testid="archetype-description"]').element as HTMLTextAreaElement).value,
    ).toBe("Current description");
  });

  it("makes contestation an explicit choice with a required explanation", async () => {
    const store = useUserModelingStore();
    store.activateProject(PROJECT_ID);
    store.applySnapshot(snapshot);
    const propose = vi.spyOn(store, "proposeRevision").mockResolvedValue({
      status: "CREATED",
      issue: null,
      proposal_issue: null,
      diff: proposedDiff,
      twin_version: null,
      snapshot_version: null,
    });
    const wrapper = mountFlow();
    await wrapper.get('[data-testid="open-twin-profile"]').trigger("click");
    const panel = profilePanel();
    await panel.get('[data-testid="edit-twin-observation"]').trigger("click");
    expect((panel.get('input[value="USER_PROVIDED"]').element as HTMLInputElement).checked).toBe(
      true,
    );
    await panel.get('input[value="CONTESTED"]').setValue(true);
    await panel.get('[data-testid="submit-revision"]').trigger("submit");
    expect(propose).not.toHaveBeenCalled();
    await panel
      .get('[data-testid="revision-rationale"]')
      .setValue("Guests are served by several roles");
    await panel.get('[data-testid="submit-revision"]').trigger("submit");
    await flushPromises();
    expect(propose).toHaveBeenCalledWith(
      PROJECT_ID,
      TWIN_ID,
      [
        expect.objectContaining({
          field: "goals",
          epistemic_status: "CONTESTED",
          rationale: "Guests are served by several roles",
          human_validation: "REQUIRED",
        }),
      ],
      ACCESS_TOKEN,
    );
    expect(wrapper.emitted("sections-changed")).toHaveLength(1);
  });
});

describe("ProjectUserModelingFlow and a generation still running", () => {
  function modelingJob(
    operation: "PERSONA_PROPOSAL" | "USER_TWIN_GENERATION",
    overrides: Partial<GenerationRequestJob> = {},
  ): GenerationRequestJob {
    return {
      job_id: "00000000-0000-4000-8000-0000000009dd",
      kind: "REQUEST",
      operation,
      status: "RUNNING",
      stage: "GENERATING",
      attempt: 1,
      started_at: CREATED_AT,
      finished_at: null,
      alternative_id: null,
      failure: null,
      response: null,
      ...overrides,
    };
  }

  function mountAutomatic() {
    return mount(ProjectUserModelingFlow, {
      global: { plugins: [createAppI18n("en")] },
      props: { projectId: PROJECT_ID, accessToken: ACCESS_TOKEN, locale: "en", autoLoad: true },
    });
  }

  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    clearFollowedGenerations();
    vi.useFakeTimers();
    const team = useTeamStore();
    team.projectId = PROJECT_ID;
    team.readiness = { status: "READY_FOR_MAIN_WORKFLOW" };
  });

  afterEach(() => {
    vi.useRealTimers();
    clearFollowedGenerations();
    vi.restoreAllMocks();
  });

  it("waits for the profiles of a proposal started before a reload and never proposes twice", async () => {
    const store = useUserModelingStore();
    const load = vi.spyOn(store, "load").mockResolvedValue(undefined);
    const propose = vi
      .spyOn(store, "proposePersonas")
      .mockResolvedValue({} as PersonaProposalCommandPayload);
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([modelingJob("PERSONA_PROPOSAL")]);
    vi.spyOn(generationJobsApi, "job")
      .mockResolvedValueOnce(modelingJob("PERSONA_PROPOSAL"))
      .mockResolvedValueOnce(
        modelingJob("PERSONA_PROPOSAL", {
          status: "SUCCEEDED",
          stage: null,
          response: { status_code: 200, body: { status: "CREATED" } },
        }),
      );
    const wrapper = mountAutomatic();
    await vi.advanceTimersByTimeAsync(50);

    const notice = wrapper.get('[data-testid="generation-job-notice"]');
    expect(notice.text()).toContain("The Studio is generating the user profiles.");
    expect(wrapper.find('[data-testid="user-modeling-busy"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="propose-personas"]').attributes("disabled")).toBeDefined();
    expect(propose).not.toHaveBeenCalled();
    const loads = load.mock.calls.length;

    await vi.advanceTimersByTimeAsync(4000);

    expect(wrapper.find('[data-testid="generation-job-notice"]').exists()).toBe(false);
    expect(load.mock.calls.length).toBeGreaterThan(loads);
    expect(propose).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("says that an interrupted generation of the twins can be started again and waits for the owner", async () => {
    const store = useUserModelingStore();
    vi.spyOn(store, "load").mockResolvedValue(undefined);
    const propose = vi
      .spyOn(store, "proposePersonas")
      .mockResolvedValue({} as PersonaProposalCommandPayload);
    const generate = vi.spyOn(store, "generateSnapshot");
    vi.spyOn(generationJobsApi, "list").mockResolvedValue([modelingJob("USER_TWIN_GENERATION")]);
    vi.spyOn(generationJobsApi, "job").mockRejectedValue(
      new GenerationJobsApiError("GENERATION_JOB_NOT_FOUND", {
        status: 404,
        code: "GENERATION_JOB_NOT_FOUND",
        payload: null,
      }),
    );
    const wrapper = mountAutomatic();
    await vi.advanceTimersByTimeAsync(2050);

    const failure = wrapper.get('[data-testid="generation-job-failure"]');
    expect(failure.attributes("data-lost")).toBe("true");
    expect(failure.text()).toContain("The generation of the user twins stopped");
    expect(failure.text()).toContain("you can start it again whenever you want");
    await vi.advanceTimersByTimeAsync(4000);
    expect(generate).not.toHaveBeenCalled();
    expect(propose).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
