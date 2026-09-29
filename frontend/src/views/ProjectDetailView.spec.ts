import { createPinia } from "pinia";
import { defineComponent, h, reactive } from "vue";
import { createI18n } from "vue-i18n";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ProjectBriefVersionResponse, ProjectResponse } from "@/api/contracts";
import { designMockupsApi } from "@/api/designMockups";
import { projectImportsApi } from "@/api/projectImports";
import GeneratedMockupFrame from "@/components/GeneratedMockupFrame.vue";
import { createAppI18n } from "@/i18n";
import { useDesignMockupsStore } from "@/stores/designMockups";
import { DESIGN_ALTERNATIVE_ID, SELECTED_DESIGN_VERSION } from "@/test/designFixtures";
import type { ProjectImportOriginPayload } from "@/types/projectImports";
import type { UserTwinVersionPayload } from "@/types/userModeling";
import { useClarificationStore } from "@/stores/clarification";
import { useInsightTrayStore } from "@/stores/insightTray";
import { useKnowledgePackagesStore } from "@/stores/knowledgePackages";
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import { useDesignStore } from "@/stores/design";
import ProjectDetailView from "./ProjectDetailView.vue";
import { expectAccessible } from "@/test/axe";

const state = vi.hoisted(() => ({ route: {} as { params: { projectId: string } } }));
vi.mock("vue-router", () => ({ useRoute: () => state.route }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    accessToken: "token",
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
    currentSnapshot: { id: "twins", content_hash: "twins-hash", version_number: 1 },
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
    expect(wrapper.findAll("[data-stage]")).toHaveLength(2);
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
      { label: "Team", version: 1, approved: true },
      { label: "User Twins", version: 1, approved: true },
      { label: "Requirements", version: 1, approved: true },
      { label: "Design", version: 1, approved: true },
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
    expect(wrapper.findAll("[data-stage]")).toHaveLength(4);
    expect(wrapper.get('[data-testid="stage-requirements"]').isVisible()).toBe(true);
    stores.clarification.$patch({ projectId: "another-project" });
    await flushPromises();
    expect(wrapper.findAll("[data-stage]")).toHaveLength(1);
    expect(wrapper.get('[data-testid="stage-brief"]').isVisible()).toBe(true);
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
    expect(wrapper.findAll("[data-stage]")).toHaveLength(2);
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
      "You already approved the team: you can read it again. You can still switch the optional roles on or off",
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
      "Hai già approvato il brief: puoi rileggerlo. Se lo modifichi nasce una nuova versione da approvare di nuovo, e i passi successivi andranno rivisti.",
      "Hai già approvato la squadra: puoi rileggerla. Puoi ancora attivare o togliere i ruoli facoltativi: ogni cambio che salvi crea una nuova versione della squadra da approvare di nuovo.",
      "Hai già approvato gli user twin: puoi rileggerli e parlarci. Se correggi un twin o ne riusi uno da un altro progetto, nasce una nuova versione da approvare di nuovo.",
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
