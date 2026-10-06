import { createPinia } from "pinia";
import { defineComponent, h, reactive } from "vue";
import { createI18n } from "vue-i18n";
import { flushPromises, mount, RouterLinkStub, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ProjectBriefVersionResponse, ProjectResponse, ProjectStage } from "@/api/contracts";
import { designMockupsApi } from "@/api/designMockups";
import { clearFollowedGenerations } from "@/api/generationJobs";
import { projectImportsApi } from "@/api/projectImports";
import { sectionsApi } from "@/api/sections";
import type {
  AgentCatalogResponse,
  ProjectReadinessResponse,
  TeamProposalVersionResponse,
} from "@/api/team-contracts";
import type { HumanGateResponse } from "@/api/workflow-contracts";
import GeneratedMockupFrame from "@/components/GeneratedMockupFrame.vue";
import { createAppI18n } from "@/i18n";
import { useActivityJournalStore } from "@/stores/activityJournal";
import { useDesignMockupsStore } from "@/stores/designMockups";
import {
  BASE_DESIGN_PACKAGE,
  DESIGN_ALTERNATIVE_ID,
  DESIGN_CREATED_AT,
  DESIGN_GATE_ID,
  DESIGN_OWNER_ID,
  DESIGN_PROJECT_ID,
  SECOND_DESIGN_ALTERNATIVE_ID,
  SELECTED_DESIGN_VERSION,
  UNSELECTED_DESIGN_VERSION,
} from "@/test/designFixtures";
import { buildSelectedDesignPackage } from "@/test/prototypeFixtures";
import type {
  DesignPackageDiffPayload,
  DesignPackagePayload,
  DesignPackageVersionPayload,
  DesignReadinessPayload,
  HumanGatePayload as DesignGatePayload,
} from "@/types/design";
import type { DesignEvaluationRunPayload } from "@/types/designLoop";
import type {
  DesignMockupCapabilitiesPayload,
  MockupDocumentPayload,
  MockupResultPayload,
  ModelUsagePayload,
} from "@/types/designMockups";
import type { ProjectImportOriginPayload } from "@/types/projectImports";
import type {
  HumanGatePayload as RequirementsGatePayload,
  RequirementsCoveragePayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationVersionPayload,
  RequirementsTraceabilityPayload,
} from "@/types/requirements";
import type { RequirementsAlignmentPayload } from "@/types/requirementsAlignment";
import type {
  ProjectSectionPayload,
  ProjectSectionsPayload,
  SectionsAlignmentPayload,
  SectionsAlignmentSummaryPayload,
} from "@/types/sections";
import type {
  HumanGatePayload as TwinsGatePayload,
  PersonaVersionPayload,
  UserModelingReadinessPayload,
  UserModelingSnapshotVersionPayload,
  UserTwinVersionPayload,
} from "@/types/userModeling";
import { useClarificationStore } from "@/stores/clarification";
import { useInsightTrayStore } from "@/stores/insightTray";
import { useKnowledgePackagesStore } from "@/stores/knowledgePackages";
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import { useDesignStore } from "@/stores/design";
import ProjectDetailView from "./ProjectDetailView.vue";
import { expectAccessible } from "@/test/axe";
import { validationOverview } from "@/test/humanValidationFixtures";
import { whyDocument } from "@/test/whyFixtures";

const state = vi.hoisted(() => {
  const shared = {
    route: {} as { params: { projectId: string } },
    fetch: null as ((input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) | null,
  };
  const original = globalThis.fetch;
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) =>
    shared.fetch === null ? original.call(globalThis, input, init) : shared.fetch(input, init);
  return shared;
});
vi.mock("vue-router", () => ({ useRoute: () => state.route }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    accessToken: "token",
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-09-14T00:00:00Z",
      guidance_mode: "GUIDED",
    },
    withAccessToken: (_api: unknown, fn: (token: string) => unknown) => fn("token"),
  }),
}));

function project(id: string): ProjectResponse {
  return {
    id,
    display_name: `Project ${id}`,
    mode: "GREENFIELD_GENERATION",
    current_brief_version: 0,
    is_archived: false,
    created_at: "2026-09-14T00:00:00Z",
    updated_at: "2026-09-14T00:00:00Z",
  };
}

describe("project route requests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: "first" } });
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([]);
    vi.spyOn(projectImportsApi, "origin").mockResolvedValue(null);
    vi.spyOn(sectionsApi, "read").mockResolvedValue(null);
  });

  it.each(["success", "failure"])(
    "ignores a late %s from the previous project",
    async (outcome) => {
      let resolve!: (value: ProjectResponse) => void;
      let reject!: (error: Error) => void;
      const oldRequest = new Promise<ProjectResponse>((yes, no) => {
        resolve = yes;
        reject = no;
      });
      vi.spyOn(apiClient, "getProject").mockImplementation(async (_token, id) =>
        id === "first" ? oldRequest : project(id),
      );
      const wrapper = shallowMount(ProjectDetailView, {
        global: {
          plugins: [createPinia(), createI18n({ legacy: false, locale: "en" })],
          stubs: { UiStepper: false, UiCard: false },
        },
      });
      state.route.params.projectId = "second";
      await flushPromises();
      expect(wrapper.text()).toContain("Project second");
      if (outcome === "success") resolve(project("first"));
      else reject(new Error("late failure"));
      await flushPromises();
      expect(wrapper.text()).toContain("Project second");
      expect(wrapper.text()).not.toContain("Project first");
      expect(wrapper.find('[role="alert"]').exists()).toBe(false);
      wrapper.unmount();
    },
  );
});

const BRIEF = {
  id: "brief",
  project_id: "first",
  version_number: 1,
  content_hash: "brief-hash",
  created_at: "2026-09-14T00:00:00Z",
  brief: { description: "An accessible calculator" },
} as ProjectBriefVersionResponse;

function gate(id: string) {
  return { status: "APPROVED" as const, artifact: { artifact_id: id, content_hash: `${id}-hash` } };
}

function hydrateStages(pinia: ReturnType<typeof createPinia>) {
  const clarification = useClarificationStore(pinia);
  const team = useTeamStore(pinia);
  const modeling = useUserModelingStore(pinia);
  const requirements = useRequirementsStore(pinia);
  const design = useDesignStore(pinia);
  clarification.$patch({ projectId: "first", gate: gate("brief") });
  team.$patch({
    projectId: "first",
    currentVersion: {
      id: "team",
      content_hash: "team-hash",
      version_number: 1,
      brief_version_number: 1,
      brief_content_hash: "brief-hash",
    },
    gate: gate("team"),
    readiness: { status: "READY_FOR_MAIN_WORKFLOW" },
  });
  modeling.$patch({
    projectId: "first",
    currentSnapshot: {
      id: "twins",
      content_hash: "twins-hash",
      version_number: 1,
      snapshot: { twin_versions: [] },
    },
    currentGate: gate("twins"),
    readiness: { workflow_state: "READY_FOR_REQUIREMENTS_DEFINITION" },
  });
  requirements.$patch({
    projectId: "first",
    current: { id: "requirements", content_hash: "requirements-hash", version_number: 1 },
    gate: gate("requirements"),
    readiness: { status: "READY_FOR_DESIGN_EXPLORATION" },
  });
  design.$patch({
    projectId: "first",
    current: { id: "design", content_hash: "design-hash", version_number: 1 },
    gate: gate("design"),
    readiness: { status: "READY_FOR_ARCHITECTURE_PLANNING" },
  });
  return { clarification, team, modeling, requirements, design };
}

const ORIGIN: ProjectImportOriginPayload = {
  origin: {
    project_id: "source",
    project_name: "Reception desk",
    package_version: 3,
    package_content_hash: "a".repeat(64),
    schema_version: 2,
  },
  stages: {},
  imported_at: "2026-09-27T10:00:00Z",
  archive_hash: "b".repeat(64),
};

describe("progressive project workspace", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: "first" } });
    vi.spyOn(apiClient, "getProject").mockResolvedValue(project("first"));
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([BRIEF]);
    vi.spyOn(projectImportsApi, "origin").mockResolvedValue(null);
    vi.spyOn(sectionsApi, "read").mockResolvedValue(null);
  });

  function mountWorkspace(pinia = createPinia()) {
    return shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createI18n({ legacy: false, locale: "en" })],
        stubs: { UiStepper: false, UiCard: false },
      },
    });
  }

  it("shows only unlocked steps while keeping saved-state loaders mounted", async () => {
    const pinia = createPinia();
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectDesignFlow" }).exists()).toBe(true);
    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "5",
    ]);
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(false);
    wrapper.unmount();
  });

  it("opens the design package after hydration and allows revisiting approved work", async () => {
    const pinia = createPinia();
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    hydrateStages(pinia);
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(false);
    expect(wrapper.findAll("[data-stage]")).toHaveLength(6);
    expect(wrapper.findComponent({ name: "ProjectDesignPackagePanel" }).props("stages")).toEqual([
      { label: "Brief", version: 1, approved: true },
      { label: "Perspectives", version: 1, approved: true },
      { label: "User Twin", version: 1, approved: true },
      { label: "Definition", version: 1, approved: true },
      { label: "Design & Evaluation", version: 1, approved: true },
    ]);
    await wrapper.get('[data-stage="0"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    await wrapper.get('[data-stage="4"]').trigger("click");
    expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(false);
    await wrapper.get('[data-stage="5"]').trigger("click");
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="technical-details"]').attributes("open")).toBeUndefined();
    wrapper.unmount();
    const reloaded = mountWorkspace(pinia);
    await flushPromises();
    expect(reloaded.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    reloaded.unmount();
  });

  it("relocks downstream steps when approvals no longer match current artifacts", async () => {
    const pinia = createPinia();
    const stores = hydrateStages(pinia);
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(6);
    stores.requirements.$patch({ current: { content_hash: "revised-hash" } });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "2",
      "3",
      "5",
    ]);
    expect(wrapper.get('[data-testid="stage-requirements"]').isVisible()).toBe(true);
    stores.clarification.$patch({ projectId: "another-project" });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    wrapper.unmount();
  });

  it("opens the package step as soon as the brief is approved while the later steps keep their own rules", async () => {
    const pinia = createPinia();
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    const packageStep = () => wrapper.get('[data-testid="stepper"] li:last-child button');
    const header = () => wrapper.findComponent({ name: "UiStepHeader" });
    expect(packageStep().attributes("disabled")).toBeDefined();

    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();

    expect(packageStep().attributes("disabled")).toBeUndefined();
    expect(packageStep().attributes("data-status")).toBe("pending");
    expect(packageStep().attributes("aria-current")).toBeUndefined();
    expect(packageStep().text()).toContain("Partial folder");
    expect(wrapper.find('[data-stage="2"]').exists()).toBe(false);
    expect(header().props("status")).toBe("current");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);

    await wrapper.get('[data-stage="5"]').trigger("click");

    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(false);
    expect(header().props("title")).toBe("Dossier");
    expect(header().props("status")).toBe("pending");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(false);
    expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="step-ahead"] p').text()).toBe(
      "The project goes on at the Perspectives step: the folder holds only the steps approved so far.",
    );
    expect(wrapper.findComponent({ name: "ProjectDesignPackagePanel" }).props("stages")).toEqual([
      { label: "Brief", version: 1, approved: true },
      { label: "Perspectives", version: null, approved: false },
      { label: "User Twin", version: null, approved: false },
      { label: "Definition", version: null, approved: false },
      { label: "Design & Evaluation", version: null, approved: false },
    ]);
    expect(
      wrapper
        .findAllComponents({ name: "UiTechnicalDetails" })
        .find((row) => row.attributes("data-testid") === "technical-details")
        ?.props("summary"),
    ).toBe("No folder prepared yet");

    await wrapper.get('[data-testid="back-to-current"]').trigger("click");

    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(false);
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="step-ahead"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the opened package step while a later step is approved and closes it with the approval of the brief", async () => {
    const pinia = createPinia();
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();
    await wrapper.get('[data-stage="5"]').trigger("click");
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);

    useTeamStore(pinia).$patch({
      projectId: "first",
      currentVersion: {
        id: "team",
        content_hash: "team-hash",
        version_number: 1,
        brief_version_number: 1,
        brief_content_hash: "brief-hash",
      },
      gate: gate("team"),
      readiness: { status: "READY_FOR_MAIN_WORKFLOW" },
    });
    await flushPromises();

    expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "2",
      "5",
    ]);
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="step-ahead"] p').text()).toContain(
      "goes on at the User Twin step",
    );

    useClarificationStore(pinia).$patch({ projectId: "another-project" });
    await flushPromises();

    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(false);
    expect(wrapper.find('[data-testid="step-ahead"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("names the partial folder and the way back in Italian", async () => {
    const pinia = createPinia();
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("it")],
        stubs: { UiStepper: false },
      },
    });
    await flushPromises();
    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();

    expect(wrapper.get('[data-stage="5"]').text()).toContain("Cartella parziale");
    await wrapper.get('[data-stage="5"]').trigger("click");

    expect(wrapper.get('[data-testid="step-ahead"] p').text()).toBe(
      "Il progetto continua dal passo Prospettive: la cartella contiene solo i passi approvati finora.",
    );
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("reads the drawn mockup of the package only once the design is approved", async () => {
    const pinia = createPinia();
    const { design } = hydrateStages(pinia);
    const version = {
      ...SELECTED_DESIGN_VERSION,
      id: "design",
      project_id: "first",
      content_hash: "design-hash",
      package: {
        ...SELECTED_DESIGN_VERSION.package,
        generated_mockup: {
          mockup: {
            contract_version: 1,
            design_alternative_id: DESIGN_ALTERNATIVE_ID,
            title: "Reservation desk",
            styles: ".desk{display:grid}",
            screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT" as const, markup: "" }],
          },
          requirement_ids_by_code: {},
        },
      },
    };
    design.$patch({ current: version, readiness: { status: "DESIGN_APPROVAL_REQUIRED" } });
    useDesignMockupsStore(pinia).activate("first", version);
    const readDocument = vi.spyOn(designMockupsApi, "document").mockResolvedValue({
      html: "<!doctype html><html><body><h1>Desk</h1></body></html>",
      content_hash: "c".repeat(64),
      source: "applied",
      alternative_id: DESIGN_ALTERNATIVE_ID,
      title: "Reservation desk",
      entry_screen: "SCR-001",
      screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT" }],
    });
    const PackageStep = defineComponent({
      name: "ProjectDesignPackagePanel",
      setup(_props, { slots }) {
        return () => h("div", { "data-testid": "package-stub" }, slots.preview?.({}));
      },
    });
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("en")],
        stubs: { UiStepper: false, ProjectDesignPackagePanel: PackageStep },
      },
    });
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);

    await wrapper.get('[data-stage="5"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(readDocument).not.toHaveBeenCalled();

    design.$patch({ readiness: { status: "READY_FOR_ARCHITECTURE_PLANNING" } });
    await flushPromises();

    expect(readDocument).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="step-ahead"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("follows brief versions created by accepted assumptions instead of retaining an obsolete approval", async () => {
    const pinia = createPinia();
    const { clarification } = hydrateStages(pinia);
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    clarification.$patch({
      lastAssumptionDecision: {
        brief_version: {
          ...BRIEF,
          id: "clarified-brief",
          version_number: 2,
          content_hash: "clarified-brief-hash",
        },
      },
    });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).props("initial")).toEqual(
      BRIEF.brief,
    );
    clarification.$patch({ gate: gate("clarified-brief") });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
      "0",
      "1",
      "5",
    ]);
    wrapper.unmount();
  });

  it("opens the dialogue for a project without a brief and switches to the form on request", async () => {
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([]);
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    const dialogue = wrapper.findComponent({ name: "ProjectBriefDialogue" });
    expect(dialogue.exists()).toBe(true);
    expect(dialogue.isVisible()).toBe(true);
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).exists()).toBe(false);
    dialogue.vm.$emit("open-form");
    await flushPromises();
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).exists()).toBe(true);
    expect(wrapper.get('[data-testid="brief-editor"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="brief-edit-toggle"]').exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectBriefDialogue" }).isVisible()).toBe(false);
    await wrapper.get('[data-testid="brief-open-dialogue"]').trigger("click");
    expect(wrapper.findComponent({ name: "ProjectBriefDialogue" }).isVisible()).toBe(true);
    wrapper.unmount();
  });

  it("keeps the manual editor of the brief closed until the owner opens it", async () => {
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    const toggle = wrapper.get('[data-testid="brief-edit-toggle"]');
    const panel = wrapper.get('[data-testid="brief-editor"]');
    expect(toggle.attributes("aria-controls")).toBe(panel.attributes("id"));
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(panel.isVisible()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).props("initial")).toEqual(
      BRIEF.brief,
    );
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(panel.isVisible()).toBe(true);
    const saved = { ...BRIEF, id: "saved", version_number: 2, content_hash: "saved-hash" };
    const create = vi.spyOn(apiClient, "createBriefVersion").mockResolvedValue(saved);
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([BRIEF, saved]);
    wrapper.findComponent({ name: "ProjectBriefEditor" }).vm.$emit("submit", BRIEF.brief);
    await flushPromises();
    expect(create).toHaveBeenCalledWith("token", "first", BRIEF.brief);
    expect(wrapper.get('[data-testid="brief-edit-toggle"]').attributes("aria-expanded")).toBe(
      "false",
    );
    expect(wrapper.get('[data-testid="brief-editor"]').isVisible()).toBe(false);
    wrapper.unmount();
  });

  it("returns to the form with the synthesized brief when the dialogue completes", async () => {
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).exists()).toBe(true);
    const dialogue = wrapper.findComponent({ name: "ProjectBriefDialogue" });
    dialogue.vm.$emit("active", true);
    await flushPromises();
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).exists()).toBe(false);
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([
      BRIEF,
      { ...BRIEF, id: "synthesized", version_number: 2, content_hash: "synthesized-hash" },
    ]);
    dialogue.vm.$emit("synthesized", { ...BRIEF, id: "synthesized", version_number: 2 });
    await flushPromises();
    expect(wrapper.findComponent({ name: "ProjectBriefEditor" }).props("initial")).toEqual(
      BRIEF.brief,
    );
    expect(
      wrapper.findComponent({ name: "ProjectClarificationFlow" }).props("currentBrief"),
    ).toMatchObject({
      id: "synthesized",
      version_number: 2,
    });
    wrapper.unmount();
  });

  it("mounts the insight tray once and keeps it hidden while it is empty", async () => {
    const pinia = createPinia();
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createI18n({ legacy: false, locale: "en" })],
        stubs: { UiStepper: false, UiCard: false, InsightBriefTray: false },
      },
    });
    await flushPromises();
    const trays = wrapper.findAllComponents({ name: "InsightBriefTray" });
    expect(trays).toHaveLength(1);
    expect(trays[0]!.props("projectId")).toBe("first");
    expect(wrapper.find('[data-testid="insight-brief-tray"]').exists()).toBe(false);
    const target = wrapper.get("#step-decision-bar");
    expect(target.classes()).not.toContain("[&_[data-testid=decision-bar]]:mt-3");
    useInsightTrayStore(pinia).add("first", {
      sourceKind: "TWIN_CHAT_INSIGHT",
      sourceId: "turn-1:0",
      sourceTwinId: null,
      text: "Guests arrive in groups.",
      briefField: "goals",
    });
    await flushPromises();
    const trayElement = wrapper.get('[data-testid="insight-brief-tray"]');
    expect(trayElement.isVisible()).toBe(true);
    expect(trayElement.classes()).not.toContain("fixed");
    const dock = wrapper.get('[data-testid="step-dock"]');
    expect(dock.classes()).toEqual(expect.arrayContaining(["sticky", "bottom-4"]));
    expect(dock.element.contains(trayElement.element)).toBe(true);
    expect(dock.element.contains(target.element)).toBe(true);
    expect(
      trayElement.element.compareDocumentPosition(target.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(target.classes()).toContain("[&_[data-testid=decision-bar]]:mt-3");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("offers the decision target before the steps mount and shows it only on the current step", async () => {
    let foundOnMount: boolean | null = null;
    const TeamStep = defineComponent({
      name: "ProjectTeamSelectionFlow",
      setup() {
        foundOnMount = document.getElementById("step-decision-bar") !== null;
        return () => h("div");
      },
    });
    const pinia = createPinia();
    let finish!: (value: ProjectResponse) => void;
    vi.spyOn(apiClient, "getProject").mockImplementation(
      () => new Promise<ProjectResponse>((resolve) => (finish = resolve)),
    );
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createI18n({ legacy: false, locale: "en" })],
        stubs: { UiStepper: false, UiCard: false, ProjectTeamSelectionFlow: TeamStep },
      },
    });
    await flushPromises();
    expect(document.getElementById("step-decision-bar")).not.toBeNull();
    expect(foundOnMount).toBeNull();
    finish(project("first"));
    await flushPromises();
    expect(foundOnMount).toBe(true);
    const target = wrapper.get("#step-decision-bar");
    expect(target.isVisible()).toBe(true);
    const stages = wrapper.get('[data-testid="stage-design"]').element;
    expect(
      stages.compareDocumentPosition(target.element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      target.element.compareDocumentPosition(
        wrapper.get('[data-testid="technical-details"]').element,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    hydrateStages(pinia);
    await flushPromises();
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);
    await wrapper.get('[data-stage="1"]').trigger("click");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(false);
    expect(wrapper.get('[data-testid="step-read-only"]').text()).toContain(
      "You already approved the perspectives: you can read them again. You can still switch on or off the ones left to your choice",
    );
    expect(wrapper.get('[data-testid="step-read-only"]').text()).not.toMatch(/not change/i);
    await wrapper.get('[data-testid="back-to-current"]').trigger("click");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says for every approved step what can still change and that a change is approved again", async () => {
    const pinia = createPinia();
    hydrateStages(pinia);
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("it")],
        stubs: { UiStepper: false },
      },
    });
    await flushPromises();
    expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
    const sentences = [
      "Hai già approvato il brief: puoi rileggerlo. Se lo modifichi, nasce una nuova versione da approvare di nuovo, e i passi successivi andranno rivisti.",
      "Hai già approvato le prospettive: puoi rileggerle. Puoi ancora attivare o togliere quelle a tua scelta: ogni cambio che salvi crea una nuova versione da approvare di nuovo.",
      "Hai già approvato gli User Twin: puoi rileggerli e parlarci. Se correggi un twin o ne riusi uno da un altro progetto, nasce una nuova versione da approvare di nuovo.",
      "Hai già approvato i requisiti: puoi rileggerli. Se ne modifichi uno, nasce una nuova versione da approvare di nuovo.",
      "Hai già approvato il design: puoi rileggerlo e provare il mockup. Se cambi la scelta o il design, nasce una nuova versione da approvare di nuovo.",
    ];
    for (const [stage, sentence] of sentences.entries()) {
      await wrapper.get(`[data-stage="${stage}"]`).trigger("click");
      await flushPromises();
      expect(wrapper.get('[data-testid="step-read-only"] p').text()).toBe(sentence);
    }
    await wrapper.get('[data-stage="5"]').trigger("click");
    expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("gives the versions of the brief to the brief step for its technical row", async () => {
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    expect(wrapper.findComponent({ name: "ProjectClarificationFlow" }).props("history")).toEqual([
      BRIEF,
    ]);
    wrapper.unmount();
  });

  it("keeps the details of the project on every step, under the row of a step that has one", async () => {
    const TeamStep = defineComponent({
      name: "ProjectTeamSelectionFlow",
      setup() {
        return () => h("div", [h("div", { "data-testid": "step-technical-details" })]);
      },
    });
    const pinia = createPinia();
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("en")],
        stubs: { UiStepper: false, UiTechnicalDetails: false, ProjectTeamSelectionFlow: TeamStep },
      },
    });
    await flushPromises();
    const project = () => wrapper.get('[data-testid="project-details"]');
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(true);
    expect(project().text()).toContain("Project details");
    expect(project().find('[data-testid="open-provenance"]').exists()).toBe(false);
    expect(project().classes()).toEqual(expect.arrayContaining(["mt-0!", "border-t-0!"]));
    await project().get('[data-testid="step-technical-details-toggle"]').trigger("click");
    expect(project().find("model-runtime-status-stub").exists()).toBe(true);
    expect(project().find('[data-testid="open-provenance"]').exists()).toBe(true);
    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(false);
    expect(project().classes()).not.toContain("mt-0!");
    expect(
      wrapper
        .get('[data-testid="stage-team"] [data-testid="step-technical-details"]')
        .element.compareDocumentPosition(project().element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await wrapper.get('[data-stage="0"]').trigger("click");
    await flushPromises();
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="project-details"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("offers the row of the technical details after the bar and hides the page row when a step fills it", async () => {
    let foundOnMount: boolean | null = null;
    const DesignStep = defineComponent({
      name: "ProjectDesignFlow",
      setup() {
        foundOnMount = document.getElementById("step-technical-row") !== null;
        return () => h("div");
      },
    });
    const pinia = createPinia();
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("en")],
        stubs: { UiStepper: false, UiTechnicalDetails: false, ProjectDesignFlow: DesignStep },
      },
    });
    await flushPromises();
    expect(foundOnMount).toBe(true);
    const row = wrapper.get("#step-technical-row");
    const bar = wrapper.get("#step-decision-bar");
    expect(row.isVisible()).toBe(true);
    expect(
      bar.element.compareDocumentPosition(row.element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      row.element.compareDocumentPosition(wrapper.get('[data-testid="project-details"]').element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(true);

    const placed = document.createElement("div");
    placed.dataset.testid = "step-technical-details";
    row.element.append(placed);
    await flushPromises();
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="project-details"]').classes()).toContain("mt-0!");

    placed.remove();
    await flushPromises();
    expect(wrapper.find('[data-testid="technical-details"]').exists()).toBe(true);
    hydrateStages(pinia);
    await flushPromises();
    await wrapper.get('[data-stage="1"]').trigger("click");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(false);
    expect(wrapper.get("#step-technical-row").isVisible()).toBe(true);
    wrapper.unmount();
  });

  it("fills the preview of the package with the drawn mockup of the chosen design", async () => {
    const pinia = createPinia();
    const { design } = hydrateStages(pinia);
    const version = {
      ...SELECTED_DESIGN_VERSION,
      id: "design",
      project_id: "first",
      content_hash: "design-hash",
      package: {
        ...SELECTED_DESIGN_VERSION.package,
        generated_mockup: {
          mockup: {
            contract_version: 1,
            design_alternative_id: DESIGN_ALTERNATIVE_ID,
            title: "Reservation desk",
            styles: ".desk{display:grid}",
            screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT" as const, markup: "" }],
          },
          requirement_ids_by_code: {},
        },
      },
    };
    design.$patch({ current: version });
    useDesignMockupsStore(pinia).activate("first", version);
    const readDocument = vi.spyOn(designMockupsApi, "document").mockResolvedValue({
      html: "<!doctype html><html><body><h1>Desk</h1></body></html>",
      content_hash: "c".repeat(64),
      source: "applied",
      alternative_id: DESIGN_ALTERNATIVE_ID,
      title: "Reservation desk",
      entry_screen: "SCR-001",
      screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT" }],
    });
    const PackageStep = defineComponent({
      name: "ProjectDesignPackagePanel",
      setup(_props, { slots }) {
        return () => h("div", { "data-testid": "package-stub" }, slots.preview?.({}));
      },
    });
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("it")],
        stubs: { UiStepper: false, ProjectDesignPackagePanel: PackageStep },
      },
    });
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(readDocument).toHaveBeenCalledWith(
      "first",
      { alternative_id: DESIGN_ALTERNATIVE_ID, source: "applied" },
      "token",
    );
    const frame = wrapper.getComponent(GeneratedMockupFrame);
    expect(frame.props()).toMatchObject({
      html: "<!doctype html><html><body><h1>Desk</h1></body></html>",
      interactive: false,
      title: "Anteprima di DES-001 · Guided reservation flow",
    });
    wrapper.unmount();
  });

  it("keeps the default preview of the package when the chosen design has no drawn mockup", async () => {
    const pinia = createPinia();
    hydrateStages(pinia);
    const readDocument = vi.spyOn(designMockupsApi, "document");
    const PackageStep = defineComponent({
      name: "ProjectDesignPackagePanel",
      setup(_props, { slots }) {
        return () =>
          h("div", { "data-testid": "package-stub" }, slots.preview ? "filled" : "default");
      },
    });
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("en")],
        stubs: { UiStepper: false, ProjectDesignPackagePanel: PackageStep },
      },
    });
    await flushPromises();
    expect(wrapper.get('[data-testid="package-stub"]').text()).toBe("default");
    expect(readDocument).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("shows the knowledge folder in the row of the package step", async () => {
    const pinia = createPinia();
    hydrateStages(pinia);
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    const details = () =>
      wrapper
        .findAllComponents({ name: "UiTechnicalDetails" })
        .find((row) => row.attributes("data-testid") === "technical-details")!;
    expect(details().props("summary")).toBe("No folder prepared yet");
    expect(details().props("rows")).toEqual([]);
    useKnowledgePackagesStore(pinia).$patch({
      projectId: "first",
      versions: [
        {
          id: "folder-2",
          version_number: 2,
          content_hash: "c".repeat(64),
          archive_hash: "d".repeat(64),
          file_count: 56,
          stages: [
            { stage: "brief", label: "Brief", version_number: 1, content_hash: "1" },
            { stage: "team", label: "Team", version_number: 1, content_hash: "2" },
            { stage: "twins", label: "Twins", version_number: 1, content_hash: "3" },
            { stage: "requirements", label: "Requirements", version_number: 1, content_hash: "4" },
            { stage: "design", label: "Design", version_number: 1, content_hash: "5" },
          ],
        },
      ],
    } as never);
    await flushPromises();
    expect(details().props("summary")).toBe("Folder version 2");
    expect(details().props("rows")).toEqual([
      { label: "Content hash", value: "c".repeat(64) },
      { label: "Archive hash", value: "d".repeat(64) },
      { label: "Contents", value: "56 files · 5 approved steps" },
    ]);
    useKnowledgePackagesStore(pinia).$patch({ projectId: "another" });
    await flushPromises();
    expect(details().props("summary")).toBe("No folder prepared yet");
    wrapper.unmount();
  });

  it("keeps the list of steps closed on small screens until the owner opens it", async () => {
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [createPinia(), createAppI18n("en")],
        stubs: { UiStepper: false },
      },
    });
    await flushPromises();
    const toggle = wrapper.get('[data-testid="project-steps-toggle"]');
    const steps = wrapper.get("#project-steps");
    expect(toggle.attributes("aria-controls")).toBe("project-steps");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(toggle.text()).toBe("All steps");
    expect(steps.classes()).toContain("max-lg:hidden");
    await toggle.trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(steps.classes()).not.toContain("max-lg:hidden");
    await wrapper.get('[data-stage="0"]').trigger("click");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(steps.classes()).toContain("max-lg:hidden");
    wrapper.unmount();
  });

  it("reloads the brief in place after the tray brings insights into it", async () => {
    const pinia = createPinia();
    hydrateStages(pinia);
    const wrapper = mountWorkspace(pinia);
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(6);
    const tray = useInsightTrayStore(pinia);
    tray.$patch({ results: { first: { count: 1, briefVersionNumber: 1 } } });
    await flushPromises();
    expect(apiClient.listBriefVersions).toHaveBeenCalledTimes(1);
    const trayBrief = {
      ...BRIEF,
      id: "tray-brief",
      version_number: 2,
      content_hash: "tray-brief-hash",
    };
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([BRIEF, trayBrief]);
    tray.$patch({ results: { first: { count: 3, briefVersionNumber: 2 } } });
    await flushPromises();
    expect(apiClient.getProject).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    expect(
      wrapper.findComponent({ name: "ProjectClarificationFlow" }).props("currentBrief"),
    ).toMatchObject({ id: "tray-brief", version_number: 2 });
    wrapper.unmount();
  });

  it("has no axe violations in the workspace shell", async () => {
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("tells once per project which knowledge folder an imported project started from", async () => {
    const origin = vi.spyOn(projectImportsApi, "origin").mockResolvedValue(ORIGIN);
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [createPinia(), createAppI18n("it")],
        stubs: { UiStepper: false, UiCard: false },
      },
    });
    await flushPromises();
    expect(origin).toHaveBeenCalledWith("first", "token");
    expect(wrapper.get('[data-testid="project-import-origin"]').text()).toBe(
      "Nato dalla cartella di conoscenza di Reception desk, versione 3. Rivedi e approva ogni passo.",
    );
    await expectAccessible(wrapper.element);
    wrapper.findComponent({ name: "ProjectBriefDialogue" }).vm.$emit("synthesized", BRIEF);
    await flushPromises();
    expect(apiClient.listBriefVersions).toHaveBeenCalledTimes(2);
    expect(origin).toHaveBeenCalledTimes(1);
    state.route.params.projectId = "second";
    await flushPromises();
    expect(origin).toHaveBeenCalledTimes(2);
    expect(origin).toHaveBeenLastCalledWith("second", "token");
    wrapper.unmount();
  });

  it.each([
    ["was not imported", () => Promise.resolve(null)],
    ["cannot tell its origin", () => Promise.reject(new Error("network down"))],
  ])("shows no origin and keeps the page usable when the project %s", async (_label, origin) => {
    vi.spyOn(projectImportsApi, "origin").mockImplementation(origin);
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    expect(wrapper.text()).toContain("Project first");
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="project-import-origin"]').exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("tells every step whether it is the step on screen", async () => {
    const names = [
      "ProjectClarificationFlow",
      "ProjectTeamSelectionFlow",
      "ProjectUserModelingFlow",
      "ProjectRequirementsFlow",
      "ProjectDesignFlow",
    ] as const;
    const stubs = Object.fromEntries(
      names.map((name) => [
        name,
        defineComponent({
          name,
          props: { active: { type: Boolean, default: undefined } },
          setup(step) {
            return () => h("div", { "data-step": name, "data-active": String(step.active) });
          },
        }),
      ]),
    );
    const pinia = createPinia();
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n("en")],
        stubs: { UiStepper: false, ...stubs },
      },
    });
    await flushPromises();
    const passed = () =>
      names.map((name) => wrapper.get(`[data-step="${name}"]`).attributes("data-active"));

    expect(passed()).toEqual(["true", "false", "false", "false", "false"]);
    useClarificationStore(pinia).$patch({ projectId: "first", gate: gate("brief") });
    await flushPromises();
    expect(passed()).toEqual(["false", "true", "false", "false", "false"]);
    hydrateStages(pinia);
    await flushPromises();
    expect(passed()).toEqual(["false", "false", "false", "false", "false"]);
    await wrapper.get('[data-stage="3"]').trigger("click");
    expect(passed()).toEqual(["false", "false", "false", "true", "false"]);
    await wrapper.get('[data-stage="4"]').trigger("click");
    expect(passed()).toEqual(["false", "false", "false", "false", "true"]);
    await wrapper.get('[data-stage="2"]').trigger("click");
    expect(passed()).toEqual(["false", "false", "true", "false", "false"]);
    wrapper.unmount();
  });

  it("titles the conversation with a twin without a verb that depends on its name", async () => {
    const wrapper = shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [createPinia(), createAppI18n("it")],
        stubs: { UiStepper: false },
      },
    });
    await flushPromises();
    const twin = {
      id: "twin-version",
      profile: { name: "Twin del volontario della mensa solidale" },
    } as UserTwinVersionPayload;

    wrapper.findComponent({ name: "ProjectUserModelingFlow" }).vm.$emit("open-chat", twin);
    await flushPromises();

    const panel = wrapper
      .findAllComponents({ name: "UiSidePanel" })
      .find((item) => item.props("open") === true);
    expect(panel?.props("title")).toBe(
      "Conversazione con Twin del volontario della mensa solidale",
    );
    wrapper.unmount();
  });
});

const STAGE_KEYS: ProjectStage[] = [
  "BRIEF",
  "TEAM",
  "USER_TWINS",
  "REQUIREMENTS",
  "DESIGN",
  "PACKAGE",
];

const FLOWS = [
  "ProjectClarificationFlow",
  "ProjectTeamSelectionFlow",
  "ProjectUserModelingFlow",
  "ProjectRequirementsFlow",
  "ProjectDesignFlow",
  "ProjectDesignPackagePanel",
] as const;

function pageSections(
  overrides: Partial<Record<ProjectStage, Partial<ProjectSectionPayload>>> = {},
  alignment: Partial<SectionsAlignmentSummaryPayload> = {},
  firstPassComplete = true,
): ProjectSectionsPayload {
  return {
    first_pass_complete: firstPassComplete,
    sections: STAGE_KEYS.map((key, index) => ({
      key,
      state: "FINE",
      version_number: index + 1,
      reasons: [],
      blocked: null,
      codes: [],
      ...overrides[key],
    })),
    alignment: { available: false, sections: [], uncovered_codes: [], ...alignment },
  };
}

const BEHIND_SECTIONS = pageSections(
  {
    USER_TWINS: { state: "TO_UPDATE", reasons: ["PERSPECTIVES_CHANGED"] },
    REQUIREMENTS: { state: "TO_UPDATE", reasons: ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"] },
    DESIGN: { state: "TO_UPDATE", reasons: ["REQUIREMENTS_CHANGED"] },
  },
  { available: true, sections: ["USER_TWINS", "REQUIREMENTS", "DESIGN"] },
);

const ALIGNED_SECTIONS = pageSections({
  DESIGN: { state: "UPDATE_AVAILABLE", reasons: ["EVALUATION_MISSING"] },
});

const ALIGNED_ANSWER: SectionsAlignmentPayload = {
  status: "ALIGNED",
  results: [
    { key: "USER_TWINS", outcome: "ALIGNED", issue: null, version_number: 4, codes: [] },
    { key: "REQUIREMENTS", outcome: "ALIGNED", issue: null, version_number: 5, codes: [] },
    { key: "DESIGN", outcome: "ALIGNED", issue: null, version_number: 6, codes: [] },
  ],
  sections: ALIGNED_SECTIONS,
};

function countingFlows(setups: Record<string, number>) {
  return Object.fromEntries(
    FLOWS.map((name) => [
      name,
      defineComponent({
        name,
        props: { sectionsMode: { type: Boolean, default: undefined } },
        emits: ["sections-changed"],
        setup(step) {
          setups[name] = (setups[name] ?? 0) + 1;
          return () =>
            h("div", { "data-flow": name, "data-sections-mode": String(step.sectionsMode) });
        },
      }),
    ]),
  );
}

describe("sections after the first pass", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: "first" } });
    vi.spyOn(apiClient, "getProject").mockResolvedValue(project("first"));
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([BRIEF]);
    vi.spyOn(projectImportsApi, "origin").mockResolvedValue(null);
  });

  function mountSections(
    locale: "en" | "it" = "en",
    stubs: Record<string, unknown> = {},
    pinia = createPinia(),
  ) {
    return shallowMount(ProjectDetailView, {
      attachTo: document.body,
      global: {
        plugins: [pinia, createAppI18n(locale)],
        stubs: { UiStepper: false, UiStepHeader: false, UiButton: false, ...stubs },
      },
    });
  }

  const states = pageSections({
    USER_TWINS: { state: "UPDATE_AVAILABLE", reasons: ["TWINS_LEARNED"] },
    REQUIREMENTS: { state: "IN_PROGRESS" },
    DESIGN: {
      state: "TO_UPDATE",
      reasons: ["REQUIREMENTS_CHANGED"],
      blocked: "UPSTREAM_NOT_READY",
    },
    PACKAGE: { state: "NOT_STARTED", version_number: null },
  });

  it.each<["en" | "it", string[], string, string]>([
    [
      "en",
      [
        "✓ Up to date · v1",
        "✓ Up to date · v2",
        "+ Update available · v3",
        "● Your turn · v4",
        "↻ To update · v5",
        "○ Waiting",
      ],
      "Sections",
      "All sections",
    ],
    [
      "it",
      [
        "✓ A posto · v1",
        "✓ A posto · v2",
        "+ Aggiornamento disponibile · v3",
        "● Tocca a te · v4",
        "↻ Da aggiornare · v5",
        "○ In attesa",
      ],
      "Sezioni",
      "Tutte le sezioni",
    ],
  ])(
    "shows in %s every section with its state and version and locks none of them",
    async (locale, lines, navigation, toggle) => {
      vi.spyOn(sectionsApi, "read").mockResolvedValue(states);
      const wrapper = mountSections(locale);
      await flushPromises();

      const stepper = wrapper.get('[data-testid="stepper"]');
      expect(stepper.attributes("aria-label")).toBe(navigation);
      expect(
        wrapper
          .findAll('[data-testid="stepper-section"]')
          .map((line) => line.text().replace(/\s+/g, " ")),
      ).toEqual(lines);
      expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",
      ]);
      expect(stepper.findAll("button[disabled]")).toHaveLength(0);
      expect(wrapper.get('[data-testid="project-steps-toggle"]').text()).toBe(toggle);
      wrapper.unmount();
    },
  );

  it.each<["en" | "it", string, string]>([
    ["en", "● Your turn", "v4"],
    ["it", "● Tocca a te", "v4"],
  ])(
    "shows in %s the state and the version of the open section in place of its position",
    async (locale, chip, version) => {
      vi.spyOn(sectionsApi, "read").mockResolvedValue(states);
      const wrapper = mountSections(locale);
      await flushPromises();

      const header = wrapper.get('[data-testid="step-header"]');
      expect(header.text()).not.toMatch(/Step \d of 6|Passo \d di 6/);
      expect(header.get('[data-testid="step-section-state"]').text().replace(/\s+/g, " ")).toBe(
        chip,
      );
      expect(header.get('[data-testid="step-version"]').text()).toBe(version);
      expect(header.find('[data-testid="step-status"]').exists()).toBe(false);
      expect(header.get("h1").text()).toBe(locale === "it" ? "Definizione" : "Definition");
      wrapper.unmount();
    },
  );

  it.each<[string, ProjectSectionsPayload, string]>([
    [
      "the first section in progress",
      pageSections({
        TEAM: { state: "IN_PROGRESS" },
        USER_TWINS: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
        DESIGN: { state: "IN_PROGRESS" },
      }),
      "stage-team",
    ],
    [
      "the first section to update when none is in progress",
      pageSections({
        REQUIREMENTS: { state: "TO_UPDATE" },
        DESIGN: { state: "TO_UPDATE" },
        PACKAGE: { state: "TO_UPDATE", reasons: ["FOLDER_BEHIND"] },
      }),
      "stage-requirements",
    ],
    [
      "the Dossier when every section is fine",
      pageSections({ USER_TWINS: { state: "UPDATE_AVAILABLE", reasons: ["TWINS_LEARNED"] } }),
      "stage-package",
    ],
  ])("opens on %s when the person chose nothing", async (_label, sections, stage) => {
    vi.spyOn(sectionsApi, "read").mockResolvedValue(sections);
    const wrapper = mountSections();
    await flushPromises();

    const visible = [
      "stage-brief",
      "stage-team",
      "stage-twins",
      "stage-requirements",
      "stage-design",
      "stage-package",
    ].filter((name) => wrapper.get(`[data-testid="${name}"]`).isVisible());
    expect(visible).toEqual([stage]);
    wrapper.unmount();
  });

  it("shows the decision area and the technical row on an approved section that the person opens", async () => {
    vi.spyOn(sectionsApi, "read").mockResolvedValue(pageSections());
    const pinia = createPinia();
    const wrapper = mountSections("en", {}, pinia);
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);

    for (const stage of [1, 0, 3]) {
      await wrapper.get(`[data-stage="${stage}"]`).trigger("click");
      expect(wrapper.get(`#studio-stage-${stage}`).isVisible()).toBe(true);
      expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);
      expect(wrapper.get("#step-technical-row").isVisible()).toBe(true);
      expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="step-ahead"]').exists()).toBe(false);
      expect(wrapper.find('[data-testid="back-to-current"]').exists()).toBe(false);
    }
    hydrateStages(pinia);
    await flushPromises();
    await wrapper.get('[data-stage="1"]').trigger("click");
    expect(wrapper.get("#step-decision-bar").isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="step-read-only"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("keeps the section the person chose and otherwise follows the section that needs attention", async () => {
    const read = vi
      .spyOn(sectionsApi, "read")
      .mockResolvedValueOnce(pageSections({ REQUIREMENTS: { state: "IN_PROGRESS" } }))
      .mockResolvedValueOnce(pageSections({ DESIGN: { state: "TO_UPDATE" } }))
      .mockResolvedValue(pageSections({ BRIEF: { state: "IN_PROGRESS" } }));
    const setups: Record<string, number> = {};
    const wrapper = mountSections("en", countingFlows(setups));
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-requirements"]').isVisible()).toBe(true);

    wrapper.findComponent({ name: "ProjectRequirementsFlow" }).vm.$emit("sections-changed");
    await flushPromises();
    expect(read).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);

    await wrapper.get('[data-stage="2"]').trigger("click");
    wrapper.findComponent({ name: "ProjectDesignFlow" }).vm.$emit("sections-changed");
    await flushPromises();
    expect(read).toHaveBeenCalledTimes(3);
    expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
    wrapper.unmount();
  });

  it("reads the sections once when it opens and once after every change a flow reports", async () => {
    const read = vi.spyOn(sectionsApi, "read").mockResolvedValue(pageSections());
    const setups: Record<string, number> = {};
    const wrapper = mountSections("en", countingFlows(setups));
    await flushPromises();

    expect(read).toHaveBeenCalledTimes(1);
    expect(read).toHaveBeenCalledWith("first", "token");
    expect(
      FLOWS.map((name) => wrapper.get(`[data-flow="${name}"]`).attributes("data-sections-mode")),
    ).toEqual(["true", "true", "true", "true", "true", "true"]);
    for (const [index, name] of FLOWS.entries()) {
      wrapper.findComponent({ name }).vm.$emit("sections-changed");
      await flushPromises();
      expect(read).toHaveBeenCalledTimes(index + 2);
    }
    expect(Object.values(setups)).toEqual([1, 1, 1, 1, 1, 1]);
    wrapper.unmount();
  });

  it("keeps every flow in the first pass until the first design is approved", async () => {
    const read = vi.spyOn(sectionsApi, "read").mockResolvedValue(pageSections({}, {}, false));
    const wrapper = mountSections("en", countingFlows({}));
    await flushPromises();

    expect(
      FLOWS.map((name) => wrapper.get(`[data-flow="${name}"]`).attributes("data-sections-mode")),
    ).toEqual(["false", "false", "false", "false", "false", "false"]);
    expect(wrapper.find('[data-testid="sections-notice"]').exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectSectionsNotice" }).exists()).toBe(false);
    expect(wrapper.get('[data-testid="step-header"]').text()).toContain("Step 1 of 6");
    wrapper.findComponent({ name: "ProjectTeamSelectionFlow" }).vm.$emit("sections-changed");
    await flushPromises();
    expect(read).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it.each(["it", "en"] as const)(
    "shows evidence review codes and real downstream states before the first design approval in %s",
    async (locale) => {
      const affected = { scenarios: ["SCN-001"], needs: ["NED-001"], requirements: ["REQ-001"] };
      const data = pageSections(
        {
          REQUIREMENTS: {
            state: "TO_UPDATE",
            version_number: 3,
            reasons: ["USER_TWINS_CHANGED"],
            affected_codes: affected,
          },
          DESIGN: {
            state: "IN_PROGRESS",
            version_number: 1,
            reasons: ["USER_TWINS_CHANGED"],
            affected_codes: affected,
          },
          PACKAGE: {
            state: "TO_UPDATE",
            version_number: 5,
            reasons: ["FOLDER_BEHIND"],
            affected_codes: affected,
          },
        },
        { available: true, sections: ["REQUIREMENTS"] },
        false,
      );
      vi.spyOn(sectionsApi, "read").mockResolvedValue(data);
      const align = vi.spyOn(sectionsApi, "align");
      const pinia = createPinia();
      const stores = hydrateStages(pinia);
      stores.design.$patch({ gate: null, readiness: { status: "DESIGN_APPROVAL_REQUIRED" } });
      const wrapper = mountSections(
        locale,
        { ProjectSectionsNotice: false, ...countingFlows({}) },
        pinia,
      );
      await flushPromises();

      expect(
        FLOWS.map((name) => wrapper.get(`[data-flow="${name}"]`).attributes("data-sections-mode")),
      ).toEqual(["false", "false", "false", "false", "false", "false"]);
      expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);
      const notice = wrapper.get('[data-testid="sections-notice"]');
      for (const code of ["SCN-001", "NED-001", "REQ-001"]) expect(notice.text()).toContain(code);
      expect(notice.get('[data-kind="affected"]').text()).toContain(
        locale === "it" ? "controlla ciò che dicono" : "review what these items say",
      );
      const definition = wrapper.get('[data-stage="3"]');
      expect(definition.attributes("data-state")).toBe("TO_UPDATE");
      expect(definition.text()).toContain(locale === "it" ? "Da aggiornare" : "To update");
      expect(wrapper.get('[data-stage="4"]').attributes("data-state")).toBe("IN_PROGRESS");
      expect(wrapper.get('[data-testid="step-section-state"]').attributes("data-state")).toBe(
        "IN_PROGRESS",
      );
      expect(wrapper.get('[data-stage="5"]').text()).toContain(
        locale === "it" ? "Cartella parziale" : "Partial folder",
      );
      expect(wrapper.get('[data-stage="5"]').attributes("data-state")).toBe("TO_UPDATE");
      expect(align).not.toHaveBeenCalled();

      await definition.trigger("click");
      expect(wrapper.get('[data-testid="step-section-state"]').attributes("data-state")).toBe(
        "TO_UPDATE",
      );
      expect(wrapper.get('[data-testid="step-read-only"]').isVisible()).toBe(true);
      await wrapper.get('[data-testid="back-to-current"]').trigger("click");
      expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);
      await wrapper.get('[data-stage="5"]').trigger("click");
      expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
      expect(wrapper.get('[data-testid="step-section-state"]').attributes("data-state")).toBe(
        "TO_UPDATE",
      );
      expect(wrapper.get('[data-testid="step-ahead"]').isVisible()).toBe(true);
      expect(align).not.toHaveBeenCalled();
      await expectAccessible(wrapper.element);
      wrapper.unmount();
    },
  );

  it("keeps future steps locked when evidence reopens an existing Definition during the first pass", async () => {
    const data = pageSections(
      {
        REQUIREMENTS: {
          state: "TO_UPDATE",
          version_number: 3,
          reasons: ["USER_TWINS_CHANGED"],
          affected_codes: { scenarios: ["SCN-001"], needs: ["NED-001"], requirements: ["REQ-001"] },
        },
        DESIGN: { state: "NOT_STARTED", version_number: null },
      },
      {},
      false,
    );
    vi.spyOn(sectionsApi, "read").mockResolvedValue(data);
    const pinia = createPinia();
    const stores = hydrateStages(pinia);
    stores.requirements.$patch({
      gate: null,
      readiness: { status: "REQUIREMENTS_APPROVAL_REQUIRED" },
    });
    stores.design.$patch({ current: null, gate: null, readiness: null });
    const wrapper = mountSections(
      "it",
      { ProjectSectionsNotice: false, ...countingFlows({}) },
      pinia,
    );
    await flushPromises();
    expect(wrapper.get('[data-testid="sections-notice"]').text()).toContain("REQ-001");
    expect(wrapper.get('[data-testid="stage-requirements"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="step-section-state"]').attributes("data-state")).toBe(
      "TO_UPDATE",
    );
    const future = wrapper.findAll('[data-testid="stepper"] button')[4];
    expect(future?.attributes("disabled")).toBeDefined();
    expect(future?.attributes("data-state")).toBeUndefined();
    expect(wrapper.find('[data-stage="4"]').exists()).toBe(false);
    expect(wrapper.findComponent({ name: "ProjectDesignFlow" }).props("sectionsMode")).toBe(false);
    wrapper.unmount();
  });

  it.each([
    ["answers 404", () => Promise.resolve(null)],
    ["cannot be reached", () => Promise.reject(new Error("network down"))],
  ])("keeps the page of today when the sections route %s", async (_label, answer) => {
    vi.spyOn(sectionsApi, "read").mockImplementation(answer);
    const wrapper = mountSections("en");
    await flushPromises();

    expect(wrapper.findAll("[data-stage]").map((step) => step.attributes("data-stage"))).toEqual([
      "0",
    ]);
    expect(wrapper.get('[data-testid="stepper"]').attributes("aria-label")).toBe("Steps");
    expect(wrapper.get('[data-testid="step-header"]').text()).toContain("Step 1 of 6");
    expect(wrapper.get('[data-testid="step-status"]').text()).toBe("Your turn");
    expect(wrapper.get('[data-testid="project-steps-toggle"]').text()).toBe("All steps");
    expect(wrapper.findComponent({ name: "ProjectSectionsNotice" }).exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("runs the one gesture from the notice above the open section and mounts again the sections it updated", async () => {
    const read = vi
      .spyOn(sectionsApi, "read")
      .mockResolvedValueOnce(BEHIND_SECTIONS)
      .mockResolvedValue(ALIGNED_SECTIONS);
    let finish!: (value: SectionsAlignmentPayload) => void;
    const align = vi.spyOn(sectionsApi, "align").mockImplementation(
      () =>
        new Promise<SectionsAlignmentPayload>((resolve) => {
          finish = resolve;
        }),
    );
    const setups: Record<string, number> = {};
    const wrapper = mountSections("en", { ProjectSectionsNotice: false, ...countingFlows(setups) });
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
    const notice = wrapper.get('[data-testid="sections-notice"]');
    expect(
      wrapper.get('[data-testid="step-header"]').element.compareDocumentPosition(notice.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      notice.element.compareDocumentPosition(wrapper.get('[data-testid="stage-brief"]').element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(notice.get('[data-kind="behind"]').text()).toBe(
      "User Twin, Definition and Design & Evaluation to update: something upstream changed. The content you approved stays the same; it is only re-anchored to the new versions.",
    );

    await wrapper.get('[data-testid="sections-align"]').trigger("click");
    await wrapper.get('[data-testid="sections-align"]').trigger("click");
    await flushPromises();
    expect(align).toHaveBeenCalledTimes(1);
    expect(align).toHaveBeenCalledWith("first", "token");
    expect(wrapper.get('[data-testid="sections-align"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="sections-notice-running"]').text()).toBe(
      "Updating the sections…",
    );

    finish(ALIGNED_ANSWER);
    await flushPromises();

    expect(read).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-kind="done"]').text()).toBe(
      "✓ Sections updated: User Twin, Definition and Design & Evaluation.",
    );
    expect(wrapper.get('[data-kind="evaluation"]').text()).toBe(
      "The design was re-anchored to the new Definition: you can ask the twins for a new evaluation.",
    );
    expect(wrapper.find('[data-testid="sections-align"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
    expect(wrapper.findAll('[data-testid="stepper-section"]').map((line) => line.text())).toEqual(
      expect.arrayContaining([expect.stringContaining("Update available")]),
    );
    expect(setups).toEqual({
      ProjectClarificationFlow: 1,
      ProjectTeamSelectionFlow: 1,
      ProjectUserModelingFlow: 2,
      ProjectRequirementsFlow: 2,
      ProjectDesignFlow: 2,
      ProjectDesignPackagePanel: 2,
    });

    wrapper.findComponent({ name: "ProjectDesignFlow" }).vm.$emit("sections-changed");
    await flushPromises();
    expect(read).toHaveBeenCalledTimes(3);
    expect(wrapper.find('[data-kind="done"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("mounts again only the sections from the first one that the gesture updated", async () => {
    vi.spyOn(sectionsApi, "read").mockResolvedValue(
      pageSections({ DESIGN: { state: "TO_UPDATE" } }, { available: true, sections: ["DESIGN"] }),
    );
    vi.spyOn(sectionsApi, "align").mockResolvedValue({
      status: "ALIGNED",
      results: [{ key: "DESIGN", outcome: "ALIGNED", issue: null, version_number: 6, codes: [] }],
      sections: pageSections(),
    });
    const setups: Record<string, number> = {};
    const wrapper = mountSections("it", { ProjectSectionsNotice: false, ...countingFlows(setups) });
    await flushPromises();

    await wrapper.get('[data-testid="sections-align"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-kind="done"]').text()).toBe(
      "✓ Sezioni aggiornate: Design e valutazione.",
    );
    expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);
    expect(setups).toEqual({
      ProjectClarificationFlow: 1,
      ProjectTeamSelectionFlow: 1,
      ProjectUserModelingFlow: 1,
      ProjectRequirementsFlow: 1,
      ProjectDesignFlow: 2,
      ProjectDesignPackagePanel: 2,
    });
    wrapper.unmount();
  });

  it("says that the gesture failed, mounts nothing again and keeps the gesture available", async () => {
    const read = vi.spyOn(sectionsApi, "read").mockResolvedValue(BEHIND_SECTIONS);
    vi.spyOn(sectionsApi, "align").mockRejectedValue(new Error("network down"));
    const setups: Record<string, number> = {};
    const wrapper = mountSections("it", { ProjectSectionsNotice: false, ...countingFlows(setups) });
    await flushPromises();

    await wrapper.get('[data-testid="sections-align"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-kind="failed"]').text()).toBe(
      "Non è stato possibile aggiornare le sezioni: riprova.",
    );
    expect(wrapper.get('[data-testid="sections-align"]').attributes("disabled")).toBeUndefined();
    expect(read).toHaveBeenCalledTimes(1);
    expect(Object.values(setups)).toEqual([1, 1, 1, 1, 1, 1]);
    wrapper.unmount();
  });

  it("opens the Perspectives section from the notice when the brief changed", async () => {
    vi.spyOn(sectionsApi, "read").mockResolvedValue(
      pageSections({
        BRIEF: { state: "FINE" },
        TEAM: { state: "TO_UPDATE", reasons: ["BRIEF_CHANGED"], blocked: "PREPARE_AGAIN" },
        USER_TWINS: { state: "TO_UPDATE", blocked: "UPSTREAM_NOT_READY" },
      }),
    );
    const wrapper = mountSections("it", { ProjectSectionsNotice: false });
    await flushPromises();
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    await wrapper.get('[data-stage="0"]').trigger("click");

    expect(wrapper.get('[data-kind="blocked"]').text()).toBe(
      "La sezione Prospettive non si aggiorna da sola: il brief è cambiato: prepara di nuovo le prospettive.",
    );
    await wrapper.get('[data-testid="sections-notice-open"]').trigger("click");
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    expect(wrapper.find('[data-testid="sections-notice-open"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("has no axe violations in sections mode with the notice", async () => {
    vi.spyOn(sectionsApi, "read").mockResolvedValue(BEHIND_SECTIONS);
    const wrapper = mountSections("it", { ProjectSectionsNotice: false });
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});

const OPEN = DESIGN_PROJECT_ID;
const OWNER = DESIGN_OWNER_ID;
const AT = DESIGN_CREATED_AT;

const OPEN_PROJECT: ProjectResponse = {
  id: OPEN,
  display_name: "Loan register",
  mode: "GREENFIELD_GENERATION",
  current_brief_version: 1,
  is_archived: false,
  created_at: AT,
  updated_at: AT,
};

const OPEN_BRIEF: ProjectBriefVersionResponse = {
  id: "00000000-0000-4000-8000-000000000201",
  project_id: OPEN,
  version_number: 1,
  schema_version: 1,
  content_hash: "4".repeat(64),
  created_by_user_id: OWNER,
  created_at: AT,
  brief: {
    name: "Loan register",
    description: "A register of the loans of a small library.",
    problem: null,
    goals: ["Know who has each book"],
    target_users: ["Librarian"],
    domain: null,
    technical_constraints: null,
    temporal_constraints: null,
    budget: null,
    functional_requirements: ["Record a loan"],
    non_functional_requirements: null,
    risks: null,
    stakeholders: null,
    available_artifacts: null,
    definition_of_done: null,
    unknown_fields: [],
    provided_fields: ["name", "description", "goals", "target_users", "functional_requirements"],
    missing_fields: [],
  },
};

function workflowGate(
  id: string,
  type: "PROJECT_BRIEF" | "AGENT_TEAM",
  artifact: { id: string; version_number: number; content_hash: string },
  status: HumanGateResponse["status"] = "APPROVED",
): HumanGateResponse {
  return {
    id,
    project_id: OPEN,
    owner_user_id: OWNER,
    gate_type: type,
    artifact: {
      project_id: OPEN,
      gate_type: type,
      artifact_id: artifact.id,
      version: artifact.version_number,
      content_hash: artifact.content_hash,
    },
    iteration: 1,
    max_iterations: 3,
    status,
    created_at: AT,
    updated_at: AT,
    event_sequence: 2,
    resume_status: null,
  };
}

const BRIEF_GATE = workflowGate(
  "00000000-0000-4000-8000-000000000202",
  "PROJECT_BRIEF",
  OPEN_BRIEF,
);

const TEAM_CATALOG: AgentCatalogResponse = {
  catalog_version: 1,
  content_hash: "5".repeat(64),
  agents: [
    {
      agent_id: "REQUIREMENTS_ANALYST",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "ALWAYS_PRESENT",
      capabilities: ["REQUIREMENTS_ANALYSIS"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.requirements_analyst.name",
      description_key: "agentCatalog.roles.requirements_analyst.description",
      is_always_present: true,
    },
    {
      agent_id: "MOBILE_ENGINEER",
      catalog_version: 1,
      kind: "SPECIALIST",
      selection_policy: "OWNER_SELECTABLE",
      capabilities: ["MOBILE_ENGINEERING"],
      supported_project_modes: ["GREENFIELD_GENERATION"],
      name_key: "agentCatalog.roles.mobile_engineer.name",
      description_key: "agentCatalog.roles.mobile_engineer.description",
      is_always_present: false,
    },
  ],
};

const TEAM_VERSION: TeamProposalVersionResponse = {
  id: "00000000-0000-4000-8000-000000000211",
  project_id: OPEN,
  version_number: 1,
  revision_kind: "PROPOSER_GENERATED",
  based_on_version_number: null,
  schema_version: 1,
  provider_kind: "FAKE_DETERMINISTIC",
  provider_id: "fake-deterministic-team-proposal",
  provider_version: 1,
  project_mode: "GREENFIELD_GENERATION",
  brief_version_id: OPEN_BRIEF.id,
  brief_version_number: OPEN_BRIEF.version_number,
  brief_content_hash: OPEN_BRIEF.content_hash,
  catalog_version: 1,
  catalog_content_hash: TEAM_CATALOG.content_hash,
  constraints_content_hash: "6".repeat(64),
  content_hash: "7".repeat(64),
  selected_agent_ids: ["REQUIREMENTS_ANALYST"],
  role_constraints: [
    {
      agent_id: "REQUIREMENTS_ANALYST",
      kind: "MANDATORY",
      owner_editable: false,
      reasons: [{ code: "CORE_REQUIREMENTS_DISCIPLINE", evidence: { fields: [], terms: [] } }],
    },
    { agent_id: "MOBILE_ENGINEER", kind: "OPTIONAL", owner_editable: true, reasons: [] },
  ],
  constraint_issues: [],
  members: [
    {
      agent_id: "REQUIREMENTS_ANALYST",
      source: "DETERMINISTIC_MANDATORY",
      justifications: [
        {
          kind: "DETERMINISTIC_RULE",
          code: "CORE_REQUIREMENTS_DISCIPLINE",
          evidence_fields: [],
          evidence_terms: [],
          statement: null,
        },
      ],
    },
  ],
  created_by_user_id: OWNER,
  created_at: AT,
};

const TEAM_GATE = workflowGate("00000000-0000-4000-8000-000000000212", "AGENT_TEAM", TEAM_VERSION);

const PERSONA: PersonaVersionPayload = {
  id: "00000000-0000-4000-8000-000000000221",
  project_id: OPEN,
  persona_id: "00000000-0000-4000-8000-000000000222",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "8".repeat(64),
  created_by_user_id: OWNER,
  created_at: AT,
  profile: {
    name: "Librarian",
    source: "SYSTEM_PROPOSED",
    kind: "PROTO_PERSONA",
    confirmation_status: "CONFIRMED",
    rejection_reason: null,
    observations: [
      {
        observation_key: "persona.role",
        value: { kind: "TEXT", text: "Librarian", items: [], reason: null },
        epistemic_status: "USER_PROVIDED",
        confidence: 1,
        provenance: [
          {
            source_kind: "PROJECT_BRIEF",
            source_id: OPEN_BRIEF.id,
            source_version: 1,
            content_hash: OPEN_BRIEF.content_hash,
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

const TWIN: UserTwinVersionPayload = {
  id: "00000000-0000-4000-8000-000000000223",
  project_id: OPEN,
  twin_id: "00000000-0000-4000-8000-000000000113",
  version_number: 1,
  based_on_version_number: null,
  content_hash: "9".repeat(64),
  created_by_user_id: OWNER,
  created_at: AT,
  profile: {
    name: "Librarian User Twin",
    persona_reference: {
      persona_id: PERSONA.persona_id,
      version_number: PERSONA.version_number,
      content_hash: PERSONA.content_hash,
      source: "SYSTEM_PROPOSED",
      kind: "PROTO_PERSONA",
      confirmation_status: "CONFIRMED",
    },
    project_brief_reference: {
      artifact_id: OPEN_BRIEF.id,
      version_number: 1,
      content_hash: OPEN_BRIEF.content_hash,
    },
    agent_team_reference: {
      artifact_id: TEAM_VERSION.id,
      version_number: 1,
      content_hash: TEAM_VERSION.content_hash,
    },
    catalog_version: 1,
    catalog_content_hash: TEAM_CATALOG.content_hash,
    validation_status: "OWNER_APPROVED_UT",
    observations: [
      {
        observation_key: "user_twin.goals",
        value: { kind: "ITEMS", text: null, items: ["Find a loan quickly"], reason: null },
        epistemic_status: "MODEL_INFERRED",
        confidence: 0.5,
        provenance: [
          {
            source_kind: "MODEL_OUTPUT",
            source_id: "fake-user-modeling",
            source_version: 1,
            content_hash: null,
            locator: "user_twin.goals",
            summary: "Deterministic model proposal",
          },
        ],
        human_validation: "REQUIRED",
        rationale: "The brief does not state this goal directly.",
      },
    ],
  },
};

const SNAPSHOT: UserModelingSnapshotVersionPayload = {
  id: "00000000-0000-4000-8000-000000000224",
  project_id: OPEN,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a1".repeat(32),
  created_by_user_id: OWNER,
  created_at: AT,
  snapshot: {
    project_id: OPEN,
    project_brief_reference: TWIN.profile.project_brief_reference,
    agent_team_reference: TWIN.profile.agent_team_reference,
    catalog_version: 1,
    catalog_content_hash: TEAM_CATALOG.content_hash,
    persona_count: 1,
    twin_count: 1,
    persona_versions: [PERSONA],
    twin_versions: [TWIN],
  },
};

const TWINS_GATE: TwinsGatePayload = {
  id: "00000000-0000-4000-8000-000000000225",
  project_id: OPEN,
  owner_user_id: OWNER,
  gate_type: "USER_MODELING",
  artifact: {
    project_id: OPEN,
    gate_type: "USER_MODELING",
    artifact_id: SNAPSHOT.id,
    version: 1,
    content_hash: SNAPSHOT.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "APPROVED",
  created_at: AT,
  updated_at: AT,
  event_sequence: 2,
};

const TWINS_READINESS: UserModelingReadinessPayload = {
  snapshot_exists: true,
  snapshot_version_id: SNAPSHOT.id,
  snapshot_version_number: 1,
  snapshot_content_hash: SNAPSHOT.content_hash,
  gate_exists: true,
  gate_id: TWINS_GATE.id,
  gate_status: "APPROVED",
  approved_current_snapshot: true,
  context_current: true,
  workflow_state: "READY_FOR_REQUIREMENTS_DEFINITION",
  twins: [
    {
      twin_id: TWIN.twin_id,
      version_number: 1,
      persisted_status: "OWNER_APPROVED_UT",
      effective_status: "OWNER_APPROVED_UT",
    },
  ],
};

const REQUIREMENT_ID = "00000000-0000-4000-8000-000000000110";

const REQUIREMENTS_VERSION: RequirementsSpecificationVersionPayload = {
  id: "00000000-0000-4000-8000-000000000120",
  project_id: OPEN,
  version_number: 1,
  based_on_version_number: null,
  content_hash: "a".repeat(64),
  created_by_user_id: OWNER,
  created_at: AT,
  specification: {
    project_id: OPEN,
    project_brief_reference: {
      kind: "PROJECT_BRIEF",
      artifact_id: OPEN_BRIEF.id,
      version_number: 1,
      content_hash: OPEN_BRIEF.content_hash,
    },
    agent_team_reference: {
      kind: "AGENT_TEAM",
      artifact_id: TEAM_VERSION.id,
      version_number: 1,
      content_hash: TEAM_VERSION.content_hash,
    },
    user_modeling_reference: {
      kind: "USER_MODELING",
      artifact_id: SNAPSHOT.id,
      version_number: 1,
      content_hash: SNAPSHOT.content_hash,
    },
    catalog_version: 1,
    catalog_content_hash: TEAM_CATALOG.content_hash,
    user_twin_references: [
      {
        twin_id: TWIN.twin_id,
        version_number: 1,
        content_hash: TWIN.content_hash,
        name: TWIN.profile.name,
      },
    ],
    requirements: [
      {
        id: REQUIREMENT_ID,
        code: "REQ-001",
        title: "Record a loan",
        statement: "The system must record who borrows each book.",
        kind: "FUNCTIONAL",
        priority: "MUST",
        sources: [
          {
            kind: "PROJECT_BRIEF",
            source_id: OPEN_BRIEF.id,
            source_version: 1,
            content_hash: OPEN_BRIEF.content_hash,
            locator: "functional_requirements[0]",
          },
        ],
        user_twin_references: [],
      },
    ],
    user_stories: [],
    acceptance_criteria: [],
    scenarios: [],
    risks: [],
    definition_of_done: [],
  },
};

const REQUIREMENTS_GATE: RequirementsGatePayload = {
  id: "00000000-0000-4000-8000-000000000231",
  project_id: OPEN,
  owner_user_id: OWNER,
  gate_type: "REQUIREMENTS",
  artifact: {
    project_id: OPEN,
    gate_type: "REQUIREMENTS",
    artifact_id: REQUIREMENTS_VERSION.id,
    version: 1,
    content_hash: REQUIREMENTS_VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "APPROVED",
  created_at: AT,
  updated_at: AT,
  event_sequence: 2,
  resume_status: null,
};

const REQUIREMENTS_READINESS: RequirementsReadinessPayload = {
  status: "READY_FOR_DESIGN_EXPLORATION",
  version: REQUIREMENTS_VERSION,
  gate: REQUIREMENTS_GATE,
  approved_current_specification: true,
};

const TRACEABILITY: RequirementsTraceabilityPayload = {
  project_id: OPEN,
  specification_version_id: REQUIREMENTS_VERSION.id,
  specification_version_number: 1,
  specification_content_hash: REQUIREMENTS_VERSION.content_hash,
  content_hash: "b".repeat(64),
  nodes: [],
  links: [],
};

const COVERAGE: RequirementsCoveragePayload = {
  project_id: OPEN,
  specification_version_id: REQUIREMENTS_VERSION.id,
  requirement_count: 1,
  user_story_count: 0,
  acceptance_criterion_count: 0,
  requirement_ids_without_user_stories: [REQUIREMENT_ID],
  requirement_ids_without_acceptance_criteria: [REQUIREMENT_ID],
  user_story_ids_without_acceptance_criteria: [],
  acceptance_criterion_ids_without_scenarios: [],
  has_full_acceptance_coverage: false,
};

const ALIGNMENT: RequirementsAlignmentPayload = {
  aligned: true,
  issue: null,
  requirements_version_number: 1,
  snapshot_version_number: 1,
  twins_approved: true,
};

const DESIGN_VERSION: DesignPackageVersionPayload = {
  ...SELECTED_DESIGN_VERSION,
  package: {
    ...SELECTED_DESIGN_VERSION.package,
    generated_mockup: {
      mockup: {
        contract_version: 1,
        design_alternative_id: DESIGN_ALTERNATIVE_ID,
        title: "Loan desk",
        styles: ".desk{display:grid}",
        screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "" }],
      },
      requirement_ids_by_code: {},
    },
  },
};

const OPEN_DESIGN_GATE: DesignGatePayload = {
  id: DESIGN_GATE_ID,
  project_id: OPEN,
  owner_user_id: OWNER,
  gate_type: "DESIGN",
  artifact: {
    project_id: OPEN,
    gate_type: "DESIGN",
    artifact_id: DESIGN_VERSION.id,
    version: DESIGN_VERSION.version_number,
    content_hash: DESIGN_VERSION.content_hash,
  },
  iteration: 1,
  max_iterations: 3,
  status: "APPROVED",
  created_at: AT,
  updated_at: AT,
  event_sequence: 2,
  resume_status: null,
};

const DESIGN_READINESS: DesignReadinessPayload = {
  status: "READY_FOR_ARCHITECTURE_PLANNING",
  version: DESIGN_VERSION,
  gate: OPEN_DESIGN_GATE,
  has_package: true,
  package_ready_for_gate: true,
  approved_current_package: true,
};

const CAPABILITIES: DesignMockupCapabilitiesPayload = {
  generated_mockups: true,
  iterations: true,
  model: "hosted-model",
  static_check: true,
};

const USAGE: ModelUsagePayload = {
  items: [],
  totals: { generations: 0, input_tokens: 0, output_tokens: 0, cost_microusd: 0 },
};

function mockupDocument(
  alternativeId: string,
  source: "applied" | "latest",
): MockupDocumentPayload {
  return {
    html: "<!doctype html><html><body><h1>Desk</h1></body></html>",
    content_hash: `${source === "applied" ? "c" : "d"}`.repeat(64),
    source,
    alternative_id: alternativeId,
    title: "Loan desk",
    entry_screen: "SCR-001",
    screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT" }],
  };
}

const PENDING_TEAM_GATE = workflowGate(
  TEAM_GATE.id,
  "AGENT_TEAM",
  TEAM_VERSION,
  "PENDING_APPROVAL",
);

const EDITED_TEAM: TeamProposalVersionResponse = {
  ...TEAM_VERSION,
  id: "00000000-0000-4000-8000-000000000213",
  version_number: 2,
  revision_kind: "OWNER_EDITED",
  based_on_version_number: 1,
  content_hash: "7a".repeat(32),
};

const NO_TWINS: UserModelingReadinessPayload = {
  snapshot_exists: false,
  snapshot_version_id: null,
  snapshot_version_number: null,
  snapshot_content_hash: null,
  gate_exists: false,
  gate_id: null,
  gate_status: null,
  approved_current_snapshot: false,
  workflow_state: "USER_MODELING_REQUIRED",
  twins: [],
};

const PROPOSED_PERSONA: PersonaVersionPayload = {
  ...PERSONA,
  version_number: 1,
  based_on_version_number: null,
  profile: { ...PERSONA.profile, confirmation_status: "PENDING_CONFIRMATION" },
};

const NO_REQUIREMENTS: RequirementsReadinessPayload = {
  status: "REQUIREMENTS_REQUIRED",
  version: null,
  gate: null,
  approved_current_specification: false,
};

const REVISED_REQUIREMENTS: RequirementsSpecificationVersionPayload = {
  ...REQUIREMENTS_VERSION,
  id: "00000000-0000-4000-8000-000000000121",
  version_number: 2,
  based_on_version_number: 1,
  content_hash: "a2".repeat(32),
};

function approvedRequirements(
  version: RequirementsSpecificationVersionPayload,
): RequirementsReadinessPayload {
  return {
    status: "READY_FOR_DESIGN_EXPLORATION",
    version,
    gate: {
      ...REQUIREMENTS_GATE,
      artifact: {
        ...REQUIREMENTS_GATE.artifact,
        artifact_id: version.id,
        version: version.version_number,
        content_hash: version.content_hash,
      },
    },
    approved_current_specification: true,
  };
}

const NO_DESIGN: DesignReadinessPayload = {
  status: "DESIGN_REQUIRED",
  version: null,
  gate: null,
  has_package: false,
  package_ready_for_gate: false,
  approved_current_package: false,
};

const DRAFT_DESIGN_READINESS: DesignReadinessPayload = {
  status: "DESIGN_REVIEW_REQUIRED",
  version: UNSELECTED_DESIGN_VERSION,
  gate: null,
  has_package: true,
  package_ready_for_gate: false,
  approved_current_package: false,
};

const CHOICE_DIFF_ID = "00000000-0000-4000-8000-000000000241";
const CHOSEN_DESIGN_ID = "00000000-0000-4000-8000-000000000242";

function drawnMockup(alternativeId: string): MockupResultPayload {
  return {
    status: "MOCKUP_GENERATED",
    generation_id: `${alternativeId}-generation`,
    design_version_id: UNSELECTED_DESIGN_VERSION.id,
    design_content_hash: UNSELECTED_DESIGN_VERSION.content_hash,
    package: {
      ...buildSelectedDesignPackage(BASE_DESIGN_PACKAGE, alternativeId),
      generated_mockup: {
        mockup: {
          contract_version: 1,
          design_alternative_id: alternativeId,
          title: "Loan desk",
          styles: ".desk{display:grid}",
          screens: [{ code: "SCR-001", title: "Desk", state: "DEFAULT", markup: "" }],
        },
        requirement_ids_by_code: {},
      },
    },
    approach: null,
    changes: [],
    warnings: [],
    cost_microusd: null,
  };
}

function twinReview(versionId: string, contentHash: string): DesignEvaluationRunPayload {
  return {
    schema_version: 1,
    id: "00000000-0000-4000-8000-000000000251",
    project_id: OPEN,
    owner_user_id: OWNER,
    design_version_id: versionId,
    design_version_number: 2,
    design_content_hash: contentHash,
    alternative_id: DESIGN_ALTERNATIVE_ID,
    alternative_code: "DES-001",
    bundle: {},
    responses: [
      {
        evaluation_run_id: "00000000-0000-4000-8000-000000000251",
        artifact_bundle_id: "00000000-0000-4000-8000-000000000252",
        artifact_bundle_hash: "b2".repeat(32),
        twin_id: TWIN.twin_id,
        twin_version: 1,
        evaluator: {
          evaluator_id: "proposer-design-twin-review",
          evaluator_version: "1",
          model_config_ref: "hosted-model",
          prompt_version_ref: "twin-review-1",
        },
        findings: [],
        summary: "The desk reads clearly.",
        evidence_gaps: [],
        is_simulated_feedback: true,
        completed_at: AT,
        content_hash: "b3".repeat(32),
        disclaimer: "Simulated feedback.",
      },
    ],
    started_at: AT,
    completed_at: AT,
    content_hash: "b4".repeat(32),
  };
}

interface Served {
  briefs: ProjectBriefVersionResponse[];
  team: TeamProposalVersionResponse;
  teamGate: HumanGateResponse;
  teamReadiness: ProjectReadinessResponse["status"];
  snapshot: UserModelingSnapshotVersionPayload | null;
  twinsGate: TwinsGatePayload | null;
  personas: PersonaVersionPayload[];
  twinsReadiness: UserModelingReadinessPayload;
  requirements: RequirementsReadinessPayload;
  design: DesignReadinessPayload;
  designHistory: DesignPackageVersionPayload[];
  designDiffs: DesignPackageDiffPayload[];
  latest: Record<string, MockupResultPayload>;
  runs: DesignEvaluationRunPayload[];
  sections?: ProjectSectionsPayload;
  alignment?: SectionsAlignmentPayload;
}

function approvedProject(): Served {
  return {
    briefs: [OPEN_BRIEF],
    team: TEAM_VERSION,
    teamGate: TEAM_GATE,
    teamReadiness: "READY_FOR_MAIN_WORKFLOW",
    snapshot: SNAPSHOT,
    twinsGate: TWINS_GATE,
    personas: [PERSONA],
    twinsReadiness: TWINS_READINESS,
    requirements: REQUIREMENTS_READINESS,
    design: DESIGN_READINESS,
    designHistory: [DESIGN_VERSION],
    designDiffs: [],
    latest: {},
    runs: [],
  };
}

function teamApprovedProject(): Served {
  return {
    ...approvedProject(),
    snapshot: null,
    twinsGate: null,
    personas: [],
    twinsReadiness: NO_TWINS,
    requirements: NO_REQUIREMENTS,
    design: NO_DESIGN,
    designHistory: [],
  };
}

function teamWaitingProject(): Served {
  return {
    ...teamApprovedProject(),
    teamGate: PENDING_TEAM_GATE,
    teamReadiness: "TEAM_APPROVAL_REQUIRED",
  };
}

function requirementsApprovedProject(): Served {
  return { ...approvedProject(), design: NO_DESIGN, designHistory: [] };
}

function designToChooseProject(): Served {
  return {
    ...approvedProject(),
    design: DRAFT_DESIGN_READINESS,
    designHistory: [UNSELECTED_DESIGN_VERSION],
    latest: {
      [DESIGN_ALTERNATIVE_ID]: drawnMockup(DESIGN_ALTERNATIVE_ID),
      [SECOND_DESIGN_ALTERNATIVE_ID]: drawnMockup(SECOND_DESIGN_ALTERNATIVE_ID),
    },
  };
}

interface Reply {
  status: number;
  body: unknown;
}

function ok(body: unknown): Reply {
  return { status: 200, body };
}

function missing(code: string): Reply {
  return { status: 404, body: { detail: { code } } };
}

const DEVELOPMENT_STATE = {
  project_id: OPEN,
  reference: { requirements: null, design: null },
  aligned: null,
  pending_changes: 0,
  latest_change: null,
  tasks: [],
  review_available: false,
};

const ACCEPTANCE_TESTS = {
  project_id: OPEN,
  reference: { requirements: null, design: null },
  plan_available: false,
  plans: 0,
  runs: 0,
  latest_run: null,
};

const TWIN_LEARNING = {
  project_id: OPEN,
  update_available: false,
  twins: [],
};

type StoreGroup = "clarification" | "team" | "twins" | "requirements" | "design";

const ORDERS: [string, StoreGroup[]][] = [
  ["as they come", []],
  ["from the first step to the last", ["clarification", "team", "twins", "requirements", "design"]],
  ["from the last step to the first", ["design", "requirements", "twins", "team", "clarification"]],
  ["with the team last", ["team"]],
  ["with the brief last", ["clarification"]],
];

const authorize = <T>(operation: (accessToken: string) => Promise<T>): Promise<T> =>
  operation("token");

function fakeStudio(served: Served) {
  const base = `/projects/${OPEN}`;
  const calls: string[] = [];
  const holds: { group: StoreGroup; gate: Promise<void> }[] = [];
  const groups: Record<StoreGroup, (path: string) => boolean> = {
    clarification: (path) =>
      path.startsWith(`${base}/brief-assumptions`) ||
      path.startsWith(`${base}/gates/project-brief/`),
    team: (path) =>
      path === "/agent-catalog" ||
      path === `${base}/readiness` ||
      path.startsWith(`${base}/team-proposals`) ||
      path.startsWith(`${base}/gates/agent-team/`),
    twins: (path) => path.startsWith(`${base}/user-modeling/`),
    requirements: (path) => path.startsWith(`${base}/requirements`),
    design: (path) =>
      path === `${base}/design` ||
      ["readiness", "revisions", "gate"].some((part) => path.startsWith(`${base}/design/${part}`)),
  };

  function documentOf(query: URLSearchParams): Reply {
    const alternative = query.get("alternative_id") ?? "";
    const version = served.design.version;
    if (
      query.get("source") === "applied" &&
      (version?.package.generated_mockup ?? null) !== null &&
      version?.package.owner_selected_alternative_id === alternative
    ) {
      return ok(mockupDocument(alternative, "applied"));
    }
    if (query.get("source") === "latest" && served.latest[alternative] !== undefined) {
      return ok(mockupDocument(alternative, "latest"));
    }
    return missing("MOCKUP_NOT_FOUND");
  }

  function read(path: string, query: URLSearchParams): Reply {
    const readings: Record<string, () => Reply> = {
      [base]: () => ok(OPEN_PROJECT),
      [`${base}/brief-versions`]: () => ok(served.briefs),
      [`${base}/import`]: () => missing("PROJECT_IMPORT_NOT_FOUND"),
      [`${base}/workflow-inputs`]: () =>
        ok({
          kind: "orchestwin.workflow-inputs",
          schema_version: 1,
          project_id: OPEN,
          decisions: [],
          prototypes: [],
          limits: [],
        }),
      [`${base}/provided-prototypes/current`]: () => missing("PROVIDED_PROTOTYPE_NOT_FOUND"),
      [`${base}/provided-prototypes/gate/current`]: () => missing("HUMAN_GATE_NOT_FOUND"),
      [`${base}/brief-dialogue`]: () => missing("BRIEF_DIALOGUE_NOT_FOUND"),
      [`${base}/brief-assumptions`]: () => ok([]),
      [`${base}/gates/project-brief/current`]: () => ok(BRIEF_GATE),
      "/agent-catalog": () => ok(TEAM_CATALOG),
      [`${base}/team-proposals`]: () => ok([served.team]),
      [`${base}/team-proposals/current`]: () => ok(served.team),
      [`${base}/gates/agent-team/current`]: () => ok(served.teamGate),
      [`${base}/readiness`]: () => ok({ status: served.teamReadiness }),
      [`${base}/generation-jobs`]: () => ok({ items: [] }),
      [`${base}/user-modeling/readiness`]: () => ok(served.twinsReadiness),
      [`${base}/user-modeling/snapshots/current`]: () =>
        served.snapshot === null ? missing("SNAPSHOT_NOT_FOUND") : ok(served.snapshot),
      [`${base}/user-modeling/snapshots`]: () =>
        ok(served.snapshot === null ? [] : [served.snapshot]),
      [`${base}/user-modeling/gate`]: () =>
        served.twinsGate === null ? missing("GATE_NOT_FOUND") : ok(served.twinsGate),
      [`${base}/user-modeling/gate/events`]: () => ok([]),
      [`${base}/user-modeling/personas`]: () => ok(served.personas),
      [`${base}/requirements/readiness`]: () => ok(served.requirements),
      [`${base}/requirements`]: () =>
        ok(served.requirements.version === null ? [] : [served.requirements.version]),
      [`${base}/requirements/revisions`]: () => ok([]),
      [`${base}/requirements/traceability`]: () => ok(TRACEABILITY),
      [`${base}/requirements/coverage`]: () => ok(COVERAGE),
      [`${base}/requirements/gate`]: () =>
        served.requirements.gate === null
          ? missing("GATE_NOT_FOUND")
          : ok(served.requirements.gate),
      [`${base}/requirements/gate/events`]: () => ok([]),
      [`${base}/requirements/twin-alignment`]: () => ok(ALIGNMENT),
      [`${base}/design/readiness`]: () => ok(served.design),
      [`${base}/design`]: () => ok(served.designHistory),
      [`${base}/design/revisions`]: () => ok(served.designDiffs),
      [`${base}/design/gate`]: () =>
        served.design.gate === null ? missing("GATE_NOT_FOUND") : ok(served.design.gate),
      [`${base}/design/gate/events`]: () => ok([]),
      [`${base}/design/evaluations`]: () => ok(served.runs),
      [`${base}/design/evaluations/comparison`]: () => missing("DESIGN_COMPARISON_NOT_FOUND"),
      [`${base}/design/evaluations/validations`]: () => ok([]),
      [`${base}/design/discussions`]: () => ok([]),
      [`${base}/insight-applications`]: () => ok([]),
      [`${base}/knowledge-packages`]: () => ok({ project_id: OPEN, versions: [] }),
      [`${base}/alignment`]: () => ok(DEVELOPMENT_STATE),
      [`${base}/alignment/proposals`]: () => ok({ items: [], latest_run: null }),
      [`${base}/alignment/runs`]: () => ok({ items: [] }),
      [`${base}/code-changes`]: () => ok({ items: [] }),
      [`${base}/code-tasks`]: () => ok({ items: [] }),
      [`${base}/twin-learning`]: () => ok(TWIN_LEARNING),
      [`${base}/evidence`]: () => ok({ project_id: OPEN, evidence: [], citations: [] }),
      [`${base}/validation`]: () =>
        ok(validationOverview({ project_id: OPEN, candidates: [], candidate_count: 0 })),
      [`${base}/artifacts/why/document`]: () => ok({ ...whyDocument([]), project_id: OPEN }),
      [`${base}/acceptance-tests`]: () => ok(ACCEPTANCE_TESTS),
      [`${base}/design/mockups/capabilities`]: () => ok(CAPABILITIES),
      [`${base}/design/mockups`]: () =>
        ok(served.latest[query.get("alternative_id") ?? ""] ?? null),
      [`${base}/design/mockups/document`]: () => documentOf(query),
      [`${base}/design/iterations`]: () => ok({ items: [] }),
      [`${base}/model-usage`]: () => ok(USAGE),
      [`${base}/sections`]: () =>
        served.sections === undefined ? missing("UNKNOWN_ADDRESS") : ok(served.sections),
    };
    const reading = readings[path];
    if (reading !== undefined) return reading();
    if (path.startsWith(`${base}/gates/`) && path.endsWith("/events")) return ok([]);
    return missing("UNKNOWN_ADDRESS");
  }

  function saveBrief(): Reply {
    const saved: ProjectBriefVersionResponse = {
      ...OPEN_BRIEF,
      id: "00000000-0000-4000-8000-000000000203",
      version_number: served.briefs.length + 1,
      content_hash: "4b".repeat(32),
    };
    served.briefs = [...served.briefs, saved];
    return ok(saved);
  }

  function approveTeam(): Reply {
    served.teamGate = workflowGate(TEAM_GATE.id, "AGENT_TEAM", served.team);
    served.teamReadiness = "READY_FOR_MAIN_WORKFLOW";
    return ok({ status: "APPLIED", gate: served.teamGate, event: null, issue: null });
  }

  function proposePersonas(): Reply {
    served.personas = [PROPOSED_PERSONA];
    return ok({
      status: "CREATED",
      issue: null,
      candidate_issue: null,
      proposal_issue: null,
      versions: served.personas,
    });
  }

  function proposeDesign(): Reply {
    served.design = DRAFT_DESIGN_READINESS;
    served.designHistory = [UNSELECTED_DESIGN_VERSION];
    return ok({
      status: "CREATED",
      version: UNSELECTED_DESIGN_VERSION,
      issue: null,
      proposal_issue: null,
      persistence_status: null,
    });
  }

  function drawMockup(body: unknown): Reply {
    const alternative = (body as { alternative_id: string }).alternative_id;
    const result = drawnMockup(alternative);
    served.latest[alternative] = result;
    return ok({
      job_id: `${alternative}-job`,
      kind: "MOCKUP",
      status: "SUCCEEDED",
      stage: null,
      attempt: 1,
      started_at: AT,
      finished_at: AT,
      alternative_id: alternative,
      result,
      failure: null,
    });
  }

  function proposeRevision(body: unknown): Reply {
    const proposed = (body as { package: DesignPackagePayload }).package;
    const diff: DesignPackageDiffPayload = {
      id: CHOICE_DIFF_ID,
      project_id: OPEN,
      owner_user_id: OWNER,
      base_version_id: UNSELECTED_DESIGN_VERSION.id,
      base_version_number: 1,
      base_content_hash: UNSELECTED_DESIGN_VERSION.content_hash,
      proposed_package: proposed,
      proposal_hash: "5".repeat(64),
      changes: [
        {
          kind: "REPLACE",
          artifact_kind: "SELECTION",
          artifact_id: proposed.owner_selected_alternative_id ?? "",
          before: null,
          after: { owner_selected_alternative_id: proposed.owner_selected_alternative_id },
        },
      ],
      status: "PROPOSED",
      created_at: AT,
      decided_by_user_id: null,
      decided_at: null,
      decision_reason: null,
      applied_version_id: null,
      content_hash: "6".repeat(64),
    };
    served.designDiffs = [diff];
    return ok({
      status: "CREATED",
      diff,
      version: null,
      issue: null,
      domain_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    });
  }

  function applyRevision(): Reply {
    const diff = served.designDiffs[0];
    if (diff === undefined) return missing("DESIGN_DIFF_NOT_FOUND");
    const version: DesignPackageVersionPayload = {
      ...UNSELECTED_DESIGN_VERSION,
      id: CHOSEN_DESIGN_ID,
      version_number: 2,
      based_on_version_number: 1,
      content_hash: "2".repeat(64),
      package: diff.proposed_package,
      ready_for_gate: true,
    };
    const applied: DesignPackageDiffPayload = {
      ...diff,
      status: "APPROVED",
      decided_by_user_id: OWNER,
      decided_at: AT,
      applied_version_id: version.id,
    };
    served.designDiffs = [applied];
    served.designHistory = [UNSELECTED_DESIGN_VERSION, version];
    served.design = {
      status: "DESIGN_APPROVAL_REQUIRED",
      version,
      gate: null,
      has_package: true,
      package_ready_for_gate: true,
      approved_current_package: false,
    };
    return ok({
      status: "APPLIED",
      diff: applied,
      version,
      issue: null,
      domain_issue: null,
      diff_persistence_status: null,
      version_persistence_status: null,
    });
  }

  function reviewDesign(body: unknown): Reply {
    const request = body as { design_version_id: string; design_content_hash: string };
    const run = twinReview(request.design_version_id, request.design_content_hash);
    served.runs = [run];
    return ok(run);
  }

  function alignSections(): Reply {
    const answer = served.alignment;
    if (answer === undefined) return missing("UNKNOWN_ADDRESS");
    served.sections = answer.sections;
    return ok(answer);
  }

  function write(path: string, body: unknown): Reply {
    const commands: Record<string, () => Reply> = {
      [`${base}/sections/alignment`]: alignSections,
      [`${base}/brief-versions`]: saveBrief,
      [`${base}/gates/agent-team/decisions`]: approveTeam,
      [`${base}/user-modeling/personas/proposals`]: proposePersonas,
      [`${base}/design/proposals`]: proposeDesign,
      [`${base}/design/mockups/jobs`]: () => drawMockup(body),
      [`${base}/design/revisions`]: () => proposeRevision(body),
      [`${base}/design/revisions/${CHOICE_DIFF_ID}/decision`]: applyRevision,
      [`${base}/design/evaluations`]: () => reviewDesign(body),
    };
    return commands[path]?.() ?? missing("UNKNOWN_ADDRESS");
  }

  async function fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const raw =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(raw, "http://studio.test");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api\/v1/, "");
    calls.push(`${method} ${path}${url.search}`);
    await Promise.all(
      holds.filter((entry) => groups[entry.group](path)).map((entry) => entry.gate),
    );
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : null;
    const reply = method === "GET" ? read(path, url.searchParams) : write(path, body);
    return new Response(JSON.stringify(reply.body), {
      status: reply.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  function hold(group: StoreGroup): () => void {
    let open: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      open = resolve;
    });
    const entry = { group, gate };
    holds.push(entry);
    return () => {
      holds.splice(holds.indexOf(entry), 1);
      open();
    };
  }

  function readings(from = 0): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const call of calls.slice(from)) {
      if (call.startsWith("GET ")) {
        const address = call.slice(4).replace(base, "…");
        counts[address] = (counts[address] ?? 0) + 1;
      }
    }
    return counts;
  }

  function writes(from = 0): string[] {
    return calls
      .slice(from)
      .filter((call) => !call.startsWith("GET "))
      .map((call) => call.replace(base, "…"));
  }

  return { served, calls, fetch, hold, readings, writes };
}

type Studio = ReturnType<typeof fakeStudio>;

async function settle(): Promise<void> {
  for (let round = 0; round < 30; round += 1) {
    await flushPromises();
  }
}

const openedPages: { unmount: () => void }[] = [];

function openStudio(studio: Studio, pinia = createPinia()) {
  state.fetch = studio.fetch;
  const wrapper = mount(ProjectDetailView, {
    attachTo: document.body,
    global: {
      plugins: [pinia, createAppI18n("en")],
      stubs: { RouterLink: RouterLinkStub },
    },
  });
  openedPages.push(wrapper);
  return wrapper;
}

async function openInOrder(studio: Studio, order: readonly StoreGroup[], pinia = createPinia()) {
  const releases = order.map((group) => studio.hold(group));
  const wrapper = openStudio(studio, pinia);
  await settle();
  for (const release of releases) {
    release();
    await settle();
  }
  return wrapper;
}

const OPENING_READINGS: Record<string, number> = {
  "…/workflow-inputs": 1,
  "…/provided-prototypes/current": 1,
  "…/provided-prototypes/gate/current": 1,
  "…": 1,
  "…/brief-versions": 1,
  "…/import": 1,
  "…/brief-dialogue": 1,
  "…/brief-assumptions": 1,
  "…/gates/project-brief/current": 1,
  [`…/gates/project-brief/${BRIEF_GATE.id}/events`]: 1,
  "/agent-catalog": 1,
  "…/team-proposals": 1,
  "…/team-proposals/current": 1,
  "…/gates/agent-team/current": 1,
  [`…/gates/agent-team/${TEAM_GATE.id}/events`]: 1,
  "…/readiness": 1,
  "…/generation-jobs?status=RUNNING": 2,
  "…/user-modeling/readiness": 1,
  "…/user-modeling/snapshots/current": 1,
  "…/user-modeling/snapshots": 1,
  "…/user-modeling/gate": 1,
  "…/user-modeling/gate/events": 1,
  "…/user-modeling/personas": 1,
  "…/requirements/readiness": 2,
  "…/requirements": 1,
  "…/requirements/revisions": 1,
  "…/requirements/traceability": 1,
  "…/requirements/coverage": 1,
  "…/requirements/gate": 1,
  "…/requirements/gate/events": 1,
  "…/requirements/twin-alignment": 1,
  "…/design/readiness": 1,
  "…/design": 1,
  "…/design/revisions": 1,
  "…/design/gate": 1,
  "…/design/gate/events": 1,
  "…/design/evaluations": 1,
  "…/design/evaluations/comparison": 1,
  "…/design/evaluations/validations": 1,
  "…/design/discussions": 1,
  "…/design/requirements-alignment": 1,
  "…/insight-applications": 1,
  "…/knowledge-packages": 1,
  "…/alignment": 1,
  "…/alignment/proposals?status=waiting": 1,
  "…/alignment/runs": 1,
  "…/code-changes": 1,
  "…/code-tasks?status=all": 1,
  "…/twin-learning": 1,
  "…/evidence?all=true": 1,
  "…/acceptance-tests": 1,
  "…/sections": 1,
  [`…/design/mockups/document?alternative_id=${DESIGN_ALTERNATIVE_ID}&source=applied`]: 1,
};

const TEAM_READINGS: Record<string, number> = {
  "/agent-catalog": 1,
  "…/team-proposals": 1,
  "…/team-proposals/current": 1,
  "…/gates/agent-team/current": 1,
  [`…/gates/agent-team/${TEAM_GATE.id}/events`]: 1,
  "…/readiness": 1,
};

const APPROVED_TWINS_READINGS: Record<string, number> = {
  "…/user-modeling/readiness": 1,
  "…/user-modeling/snapshots/current": 1,
  "…/user-modeling/snapshots": 1,
  "…/user-modeling/gate": 1,
  "…/user-modeling/gate/events": 1,
  "…/user-modeling/personas": 1,
};

const APPROVED_REQUIREMENTS_READINGS: Record<string, number> = {
  "…/requirements/readiness": 1,
  "…/requirements": 1,
  "…/requirements/revisions": 1,
  "…/requirements/traceability": 1,
  "…/requirements/coverage": 1,
  "…/requirements/gate": 1,
  "…/requirements/gate/events": 1,
  "…/requirements/twin-alignment": 1,
};

const APPROVED_DESIGN_READINGS: Record<string, number> = {
  "…/design/readiness": 1,
  "…/design": 1,
  "…/design/revisions": 1,
  "…/design/gate": 1,
  "…/design/gate/events": 1,
  "…/design/requirements-alignment": 1,
};

const FIRST_DESIGN_VIEW: Record<string, number> = {
  "…/validation": 1,
  "…/artifacts/why/document": 1,
  "…/design/mockups/capabilities": 1,
  [`…/design/mockups?alternative_id=${DESIGN_ALTERNATIVE_ID}`]: 1,
  [`…/design/mockups?alternative_id=${SECOND_DESIGN_ALTERNATIVE_ID}`]: 1,
  [`…/design/mockups/document?alternative_id=${SECOND_DESIGN_ALTERNATIVE_ID}&source=latest`]: 1,
  "…/design/distance": 1,
  "…/design/iterations": 1,
  "…/model-usage": 1,
};

describe("readings of the project page", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: OPEN } });
    sessionStorage.clear();
    clearFollowedGenerations();
  });

  afterEach(() => {
    for (const page of openedPages.splice(0)) {
      page.unmount();
    }
    state.fetch = null;
    clearFollowedGenerations();
  });

  it.each(ORDERS)(
    "reads every address of a project with five approved steps once, the stores finishing %s",
    async (_order, order) => {
      const studio = fakeStudio(approvedProject());
      const wrapper = await openInOrder(studio, order);

      expect(studio.readings()).toEqual(OPENING_READINGS);
      expect(studio.writes()).toEqual([]);
      expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
      expect(wrapper.find('[data-testid="package-preview-generated"]').exists()).toBe(true);
    },
  );

  it("asks nothing again when the owner moves along the steps or back to the current one", async () => {
    const studio = fakeStudio(approvedProject());
    const wrapper = await openInOrder(studio, []);
    const firstPass: Record<string, number>[] = [];

    for (const stage of [0, 1, 2, 3, 4, 5]) {
      const from = studio.calls.length;
      await wrapper.get(`[data-stage="${stage}"]`).trigger("click");
      await settle();
      firstPass.push(studio.readings(from));
    }

    expect(firstPass).toEqual([{}, {}, {}, {}, FIRST_DESIGN_VIEW, {}]);
    const secondPass = studio.calls.length;
    for (const stage of [4, 3, 2, 1, 0]) {
      await wrapper.get(`[data-stage="${stage}"]`).trigger("click");
      await settle();
    }
    await wrapper.get('[data-testid="back-to-current"]').trigger("click");
    await settle();

    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(studio.readings(secondPass)).toEqual({});
    expect(studio.writes()).toEqual([]);
  });

  it("opens the folder of a project in progress without reading or writing anything more", async () => {
    const studio = fakeStudio(teamWaitingProject());
    const wrapper = await openInOrder(studio, []);
    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    const from = studio.calls.length;

    await wrapper.get('[data-stage="5"]').trigger("click");
    await settle();

    expect(studio.readings(from)).toEqual({});
    expect(studio.writes()).toEqual([]);
    expect(wrapper.get('[data-testid="stage-package"]').isVisible()).toBe(true);
    expect(wrapper.get('[data-testid="package-partial"]').text().replace(/\s+/g, " ")).toBe(
      "The folder holds 1 of 5 steps: Perspectives, User Twin, Definition and Design & Evaluation are still to be approved. Each step joins the folder when you approve it.",
    );
    expect(wrapper.get('[data-testid="download-package"]').attributes("disabled")).toBeUndefined();
    expect(wrapper.find('[data-testid="development-panel"]').exists()).toBe(false);

    await wrapper.get('[data-testid="back-to-current"]').trigger("click");
    await settle();

    expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
    expect(studio.readings(from)).toEqual({});
    expect(studio.writes()).toEqual([]);
  });

  it("keeps each step mounted once for the project while the stores before it load", async () => {
    const studio = fakeStudio(approvedProject());
    const releaseTeam = studio.hold("team");
    const wrapper = openStudio(studio);
    await settle();
    const steps = [
      "ProjectTeamSelectionFlow",
      "ProjectUserModelingFlow",
      "ProjectRequirementsFlow",
      "ProjectDesignFlow",
    ];
    const instances = steps.map((name) => wrapper.findComponent({ name }).vm);
    const upstream = (name: string) => wrapper.findComponent({ name }).props("upstream");

    expect(upstream("ProjectTeamSelectionFlow")).toBe(`${OPEN_BRIEF.id}:APPROVED`);
    expect(upstream("ProjectUserModelingFlow")).toBeNull();
    expect(upstream("ProjectRequirementsFlow")).toBeNull();
    expect(upstream("ProjectDesignFlow")).toBeNull();

    releaseTeam();
    await settle();

    const team = `${OPEN_BRIEF.id}:APPROVED:${TEAM_VERSION.id}:APPROVED`;
    const twins = `${team}:${SNAPSHOT.id}:APPROVED`;
    expect(upstream("ProjectUserModelingFlow")).toBe(team);
    expect(upstream("ProjectRequirementsFlow")).toBe(twins);
    expect(upstream("ProjectDesignFlow")).toBe(`${twins}:${REQUIREMENTS_VERSION.id}:APPROVED`);
    expect(steps.map((name) => wrapper.findComponent({ name }).vm)).toEqual(instances);
    expect(studio.readings()).toEqual(OPENING_READINGS);
  });

  it("loads the later steps again once when a step before them changes, not when a store only reads again", async () => {
    const studio = fakeStudio(approvedProject());
    const pinia = createPinia();
    const wrapper = await openInOrder(studio, [], pinia);
    const team = useTeamStore(pinia);

    let from = studio.calls.length;
    await team.load(OPEN, apiClient, authorize);
    await settle();
    expect(studio.readings(from)).toEqual(TEAM_READINGS);

    from = studio.calls.length;
    await useUserModelingStore(pinia).load(OPEN, "token");
    await settle();
    expect(studio.readings(from)).toEqual(APPROVED_TWINS_READINGS);

    studio.served.team = EDITED_TEAM;
    studio.served.teamGate = workflowGate(TEAM_GATE.id, "AGENT_TEAM", EDITED_TEAM);
    from = studio.calls.length;
    await team.load(OPEN, apiClient, authorize);
    await settle();

    expect(studio.readings(from)).toEqual({
      ...TEAM_READINGS,
      ...APPROVED_TWINS_READINGS,
      ...APPROVED_REQUIREMENTS_READINGS,
      ...APPROVED_DESIGN_READINGS,
      "…/requirements/readiness": 2,
    });
    expect(wrapper.findComponent({ name: "ProjectUserModelingFlow" }).props("upstream")).toBe(
      `${OPEN_BRIEF.id}:APPROVED:${EDITED_TEAM.id}:APPROVED`,
    );
    expect(studio.writes()).toEqual([]);
  });

  it("keeps the later steps when the owner saves a new brief and loads each of them again once", async () => {
    const studio = fakeStudio(approvedProject());
    const wrapper = await openInOrder(studio, []);
    const steps = [
      "ProjectTeamSelectionFlow",
      "ProjectUserModelingFlow",
      "ProjectRequirementsFlow",
      "ProjectDesignFlow",
    ];
    const instances = steps.map((name) => wrapper.findComponent({ name }).vm);
    const from = studio.calls.length;

    wrapper.findComponent({ name: "ProjectBriefEditor" }).vm.$emit("submit", OPEN_BRIEF.brief);
    await settle();

    expect(studio.writes(from)).toEqual(["POST …/brief-versions"]);
    expect(studio.readings(from)).toEqual({
      "…": 1,
      "…/brief-versions": 1,
      "…/sections": 1,
      "…/brief-dialogue": 1,
      "…/brief-assumptions": 1,
      "…/gates/project-brief/current": 1,
      [`…/gates/project-brief/${BRIEF_GATE.id}/events`]: 1,
      ...TEAM_READINGS,
      ...APPROVED_TWINS_READINGS,
      ...APPROVED_REQUIREMENTS_READINGS,
      ...APPROVED_DESIGN_READINGS,
      "…/requirements/readiness": 2,
    });
    expect(steps.map((name) => wrapper.findComponent({ name }).vm)).toEqual(instances);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
  });

  it.each(ORDERS)(
    "after the owner approves the team the later steps load again once and the first profiles are proposed once, the stores finishing %s",
    async (_order, order) => {
      const studio = fakeStudio(teamWaitingProject());
      const wrapper = await openInOrder(studio, order);
      expect(studio.writes()).toEqual([]);
      expect(wrapper.get('[data-testid="stage-team"]').isVisible()).toBe(true);
      const from = studio.calls.length;

      await wrapper
        .get('[data-testid="team-decision"] [data-testid="decision-primary"]')
        .trigger("click");
      await settle();

      expect(studio.writes(from)).toEqual([
        "POST …/gates/agent-team/decisions",
        "POST …/user-modeling/personas/proposals",
      ]);
      expect(studio.readings(from)).toEqual({
        ...TEAM_READINGS,
        "…/user-modeling/readiness": 1,
        "…/user-modeling/snapshots": 1,
        "…/user-modeling/personas": 1,
        "…/requirements/readiness": 1,
        "…/requirements": 1,
        "…/requirements/revisions": 1,
        "…/design/readiness": 1,
        "…/design": 1,
        "…/design/revisions": 1,
        "…/sections": 2,
      });
      expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
      await settle();
      expect(studio.writes(from)).toHaveLength(2);
    },
  );

  it.each(ORDERS)(
    "does not propose the first profiles by itself when the team was already approved, the stores finishing %s",
    async (_order, order) => {
      const studio = fakeStudio(teamApprovedProject());
      const pinia = createPinia();
      const wrapper = await openInOrder(studio, order, pinia);
      expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
      expect(wrapper.find('[data-testid="propose-personas"]').exists()).toBe(true);

      studio.served.team = EDITED_TEAM;
      studio.served.teamGate = workflowGate(TEAM_GATE.id, "AGENT_TEAM", EDITED_TEAM);
      await useTeamStore(pinia).load(OPEN, apiClient, authorize);
      await settle();
      expect(studio.writes()).toEqual([]);

      await wrapper.get('[data-testid="propose-personas"]').trigger("click");
      await settle();
      expect(studio.writes()).toEqual(["POST …/user-modeling/personas/proposals"]);
    },
  );

  it.each(ORDERS)(
    "draws the two mockups only right after the owner asks for the design alternatives, the stores finishing %s",
    async (_order, order) => {
      const studio = fakeStudio(requirementsApprovedProject());
      const pinia = createPinia();
      const wrapper = await openInOrder(studio, order, pinia);
      const requirements = useRequirementsStore(pinia);
      expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);

      studio.served.requirements = approvedRequirements(REVISED_REQUIREMENTS);
      await requirements.load(OPEN, authorize);
      await settle();
      expect(studio.writes()).toEqual([]);

      await wrapper.get('[data-testid="generate-design"]').trigger("click");
      await settle();
      expect(studio.writes()).toEqual([
        "POST …/design/proposals",
        "POST …/design/mockups/jobs",
        "POST …/design/mockups/jobs",
      ]);
      expect(Object.keys(studio.served.latest).sort()).toEqual(
        [DESIGN_ALTERNATIVE_ID, SECOND_DESIGN_ALTERNATIVE_ID].sort(),
      );

      studio.served.requirements = approvedRequirements(REQUIREMENTS_VERSION);
      await requirements.load(OPEN, authorize);
      await settle();
      expect(studio.writes()).toHaveLength(3);
    },
  );

  it.each(ORDERS)(
    "starts the review of the twins only right after the owner chooses an alternative, the stores finishing %s",
    async (_order, order) => {
      const studio = fakeStudio(designToChooseProject());
      const pinia = createPinia();
      const wrapper = await openInOrder(studio, order, pinia);
      const requirements = useRequirementsStore(pinia);
      expect(wrapper.get('[data-testid="stage-design"]').isVisible()).toBe(true);

      studio.served.requirements = approvedRequirements(REVISED_REQUIREMENTS);
      await requirements.load(OPEN, authorize);
      await settle();
      expect(studio.writes()).toEqual([]);

      await wrapper
        .get(`[data-testid="alternative-choose"][data-alternative-id="${DESIGN_ALTERNATIVE_ID}"]`)
        .trigger("click");
      await settle();
      expect(studio.writes()).toEqual([
        "POST …/design/revisions",
        `POST …/design/revisions/${CHOICE_DIFF_ID}/decision`,
        "POST …/design/evaluations",
      ]);

      studio.served.requirements = approvedRequirements(REQUIREMENTS_VERSION);
      await requirements.load(OPEN, authorize);
      await settle();
      expect(studio.writes()).toHaveLength(3);
    },
  );

  it("after the one gesture reads again, once, what the sections it updated show and generates nothing", async () => {
    const studio = fakeStudio({
      ...approvedProject(),
      sections: BEHIND_SECTIONS,
      alignment: ALIGNED_ANSWER,
    });
    const wrapper = await openInOrder(studio, []);
    expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
    const from = studio.calls.length;

    await wrapper.get('[data-testid="sections-align"]').trigger("click");
    await settle();

    expect(studio.writes(from)).toEqual(["POST …/sections/alignment"]);
    expect(studio.readings(from)).toEqual({
      "…/sections": 1,
      ...APPROVED_TWINS_READINGS,
      ...APPROVED_REQUIREMENTS_READINGS,
      "…/requirements/readiness": 2,
      ...APPROVED_DESIGN_READINGS,
      "…/design/evaluations": 1,
      "…/design/evaluations/comparison": 1,
      "…/design/evaluations/validations": 1,
      "…/design/discussions": 1,
      "…/insight-applications": 1,
      "…/generation-jobs?status=RUNNING": 1,
      "…/knowledge-packages": 1,
      "…/alignment": 1,
      "…/alignment/runs": 1,
      "…/code-changes": 1,
      "…/code-tasks?status=all": 1,
    });
    expect(wrapper.get('[data-kind="done"]').text()).toBe(
      "✓ Sections updated: User Twin, Definition and Design & Evaluation.",
    );
    expect(wrapper.get('[data-testid="stage-twins"]').isVisible()).toBe(true);
    await settle();
    expect(studio.writes(from)).toHaveLength(1);
  });
});

interface ActivityCall {
  method: string;
  path: string;
  body: { events?: { kind: string; section: string | null; target: string | null }[] } | null;
  keepalive: boolean;
}

function withActivity(studio: Studio, active: boolean, hold: Promise<void> = Promise.resolve()) {
  const base = `/projects/${OPEN}/activity`;
  const session = { code: "SES-P01", started_at: AT };
  const calls: ActivityCall[] = [];
  async function fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
    const raw =
      typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const path = new URL(raw, "http://studio.test").pathname.replace(/^\/api\/v1/, "");
    if (!path.startsWith(base)) return studio.fetch(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    const body =
      typeof init?.body === "string" ? (JSON.parse(init.body) as ActivityCall["body"]) : null;
    const address = path.slice(base.length);
    calls.push({ method, path: address, body, keepalive: init?.keepalive === true });
    if (address === "/session") await hold;
    const replies: Record<string, unknown> = {
      "GET /session": { active, session: active ? session : null },
      "POST /sessions": { status: "ACTIVITY_SESSION_STARTED", session },
      "POST /events": { status: "ACTIVITY_EVENTS_RECORDED", recorded: body?.events?.length ?? 0 },
      "POST /sessions/SES-P01/end": {
        status: "ACTIVITY_SESSION_ENDED",
        session: { ...session, ended_at: AT },
      },
    };
    const reply = replies[`${method} ${address}`];
    return new Response(JSON.stringify(reply ?? { detail: { code: "UNKNOWN_ADDRESS" } }), {
      status: reply === undefined ? 404 : 200,
      headers: { "Content-Type": "application/json" },
    });
  }
  const events = () =>
    calls.flatMap((call) =>
      (call.body?.events ?? []).map((event) => [event.kind, event.section, event.target]),
    );
  return { studio: { ...studio, fetch }, calls, events };
}

describe("study session on the project page", () => {
  const key = `orchestwin.activity.${OPEN}`;

  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: OPEN } });
    sessionStorage.clear();
    clearFollowedGenerations();
  });

  afterEach(() => {
    for (const page of openedPages.splice(0)) {
      page.unmount();
    }
    state.fetch = null;
    sessionStorage.clear();
    clearFollowedGenerations();
  });

  it("neither asks nor sends anything about a study session this browser has not started", async () => {
    const { studio, calls } = withActivity(fakeStudio(approvedProject()), true);
    const wrapper = await openInOrder(studio, []);

    for (const stage of [0, 4, 5]) {
      await wrapper.get(`[data-stage="${stage}"]`).trigger("click");
      await settle();
    }
    const panel = wrapper.get('[data-testid="activity-session"]');
    (panel.element as HTMLDetailsElement).open = true;
    panel.element.dispatchEvent(new Event("toggle"));
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    window.dispatchEvent(new Event("pagehide"));
    await expect(apiClient.getProject("token", "missing")).rejects.toMatchObject({ status: 404 });
    await settle();

    expect(calls).toEqual([]);
    expect(studio.calls.filter((call) => call.includes("/activity"))).toEqual([]);
    expect(wrapper.find('[data-testid="activity-session-active"]').exists()).toBe(false);
    expect(
      wrapper
        .get('[data-testid="project-details"]')
        .element.compareDocumentPosition(panel.element) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(sessionStorage.getItem(key)).toBeNull();
  });

  it("starts a session from the bottom of the page and shows its row at the top with the focus on Stop", async () => {
    const { studio, calls, events } = withActivity(fakeStudio(approvedProject()), false);
    const pinia = createPinia();
    const wrapper = await openInOrder(studio, [], pinia);
    expect(studio.readings()).toEqual(OPENING_READINGS);

    await wrapper.get('[data-testid="activity-session-code"]').setValue("SES-P01");
    await wrapper.get('[data-testid="activity-session"] form').trigger("submit");
    await settle();

    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["POST /sessions"]);
    expect(calls[0]?.body).toEqual({ session_code: "SES-P01" });
    expect(sessionStorage.getItem(key)).toBe("SES-P01");
    const row = wrapper.get('[data-testid="activity-session-active"]');
    expect(row.attributes("role")).toBe("status");
    expect(row.text()).toContain("Recording of times and steps is on · SES-P01");
    expect(document.activeElement).toBe(row.get('[data-testid="activity-session-stop"]').element);
    expect(
      row.element.compareDocumentPosition(wrapper.get('[data-testid="guidance-mode"]').element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(wrapper.find('[data-testid="activity-session"]').exists()).toBe(false);

    await useActivityJournalStore(pinia).flush();
    await settle();
    expect(events()).toEqual([
      ["SECTION_OPENED", "PACKAGE", null],
      ["MODE_CHANGED", "PACKAGE", null],
      ["LOCALE_SET", "PACKAGE", null],
    ]);
    expect(calls[1]?.body).toMatchObject({
      session_code: "SES-P01",
      source: "WEB",
      events: [{ status: null }, { status: "GUIDED" }, { status: "en" }],
    });
  });

  it("resumes the session of this browser, records what the owner opens and stops from the row", async () => {
    sessionStorage.setItem(key, "SES-P01");
    let release: () => void = () => undefined;
    const hold = new Promise<void>((resolve) => {
      release = resolve;
    });
    const { studio, calls, events } = withActivity(fakeStudio(approvedProject()), true, hold);
    const pinia = createPinia();
    const wrapper = await openInOrder(studio, [], pinia);
    const journal = useActivityJournalStore(pinia);
    expect(wrapper.find('[data-testid="activity-session-active"]').exists()).toBe(false);
    release();
    await settle();

    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["GET /session"]);
    expect(studio.readings()).toEqual(OPENING_READINGS);
    expect(wrapper.get('[data-testid="activity-session-active"]').text()).toContain(
      "Recording of times and steps is on · SES-P01",
    );

    await wrapper.get('[data-stage="4"]').trigger("click");
    await settle();
    const probe = document.createElement("details");
    probe.dataset.testid = "probe-details";
    wrapper.get('[data-testid="stage-design"]').element.append(probe);
    probe.open = true;
    probe.dispatchEvent(new Event("toggle"));
    probe.dispatchEvent(new Event("toggle"));
    const why = wrapper
      .get('[data-testid="stage-design"]')
      .get<HTMLDetailsElement>('details[data-testid="alternative-why"]');
    why.element.open = true;
    await why.trigger("toggle");
    await expect(apiClient.getProject("token", "missing")).rejects.toMatchObject({ status: 404 });
    await journal.flush();
    await settle();

    expect(events().filter(([kind]) => kind !== "REQUEST_FAILED")).toEqual([
      ["SECTION_OPENED", "PACKAGE", null],
      ["SECTION_OPENED", "DESIGN", null],
      ["DETAIL_OPENED", "DESIGN", "probe-details"],
      ["DETAIL_OPENED", "DESIGN", "alternative-why"],
      ["WHY_OPENED", "DESIGN", why.attributes("data-why-code")],
    ]);
    expect(why.attributes("data-why-code")).toMatch(/^DES-\d{3}$/);
    expect(events()).toContainEqual(["REQUEST_FAILED", "DESIGN", "UNKNOWN_ADDRESS"]);

    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/events", keepalive: true });
    expect(
      calls
        .at(-1)
        ?.body?.events?.map((event) => event.kind)
        .filter((kind) => kind !== "REQUEST_FAILED"),
    ).toEqual(["PAGE_HIDDEN"]);

    const hidden = calls.length;
    vi.restoreAllMocks();
    document.dispatchEvent(new Event("visibilitychange"));
    await wrapper.get('[data-stage="2"]').trigger("click");
    await settle();
    await wrapper.get('[data-testid="activity-session-stop"]').trigger("click");
    await settle();

    expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/sessions/SES-P01/end" });
    expect(calls.at(-2)).toMatchObject({ method: "POST", path: "/events", keepalive: false });
    expect(calls.at(-2)?.body?.events?.at(-1)).toMatchObject({
      kind: "PAGE_HIDDEN",
      section: "USER_TWINS",
    });
    expect(
      calls
        .slice(hidden)
        .flatMap((call) => call.body?.events ?? [])
        .filter((event) => event.kind !== "REQUEST_FAILED")
        .map((event) => [event.kind, event.section]),
    ).toEqual([
      ["PAGE_VISIBLE", "DESIGN"],
      ["SECTION_OPENED", "USER_TWINS"],
      ["PAGE_HIDDEN", "USER_TWINS"],
    ]);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(wrapper.find('[data-testid="activity-session-active"]').exists()).toBe(false);
    expect(document.activeElement).toBe(
      wrapper.get('[data-testid="activity-session"] summary').element,
    );
    const sent = calls.length;
    probe.open = false;
    probe.dispatchEvent(new Event("toggle"));
    probe.open = true;
    probe.dispatchEvent(new Event("toggle"));
    await journal.flush();
    await settle();
    expect(calls).toHaveLength(sent);
  });
});
