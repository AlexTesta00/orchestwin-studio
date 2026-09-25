import { createPinia } from "pinia";
import { reactive } from "vue";
import { createI18n } from "vue-i18n";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ProjectBriefVersionResponse, ProjectResponse } from "@/api/contracts";
import { useClarificationStore } from "@/stores/clarification";
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

describe("progressive project workspace", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    state.route = reactive({ params: { projectId: "first" } });
    vi.spyOn(apiClient, "getProject").mockResolvedValue(project("first"));
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([BRIEF]);
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
    expect(wrapper.findComponent({ name: "ProjectBriefDialogue" }).isVisible()).toBe(false);
    await wrapper.get('[data-testid="brief-open-dialogue"]').trigger("click");
    expect(wrapper.findComponent({ name: "ProjectBriefDialogue" }).isVisible()).toBe(true);
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

  it("has no axe violations in the workspace shell", async () => {
    const wrapper = mountWorkspace(createPinia());
    await flushPromises();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
