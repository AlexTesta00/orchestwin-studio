import { createPinia } from "pinia";
import { reactive } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { projectImportsApi } from "@/api/projectImports";
import { sectionsApi } from "@/api/sections";
import GuidanceModeSelector from "@/components/GuidanceModeSelector.vue";
import ProjectWorkflowInputsPanel from "@/components/ProjectWorkflowInputsPanel.vue";
import UiStepHeader from "@/components/UiStepHeader.vue";
import { createAppI18n } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { useGuidanceStore } from "@/stores/guidance";
import ProjectDetailView from "./ProjectDetailView.vue";

const state = vi.hoisted(() => ({ route: { params: { projectId: "project" } } }));
vi.mock("vue-router", () => ({ useRoute: () => state.route }));

function render(expert = false) {
  const pinia = createPinia();
  const auth = useAuthStore(pinia);
  auth.user = {
    id: "owner",
    email: "owner@example.test",
    is_active: true,
    created_at: "2026-10-03T00:00:00Z",
  };
  auth.accessToken = "token";
  auth.status = "authenticated";
  const guidance = useGuidanceStore(pinia);
  guidance.select(expert ? "EXPERT" : "GUIDED");
  const wrapper = shallowMount(ProjectDetailView, {
    global: {
      plugins: [pinia, createAppI18n("en")],
      stubs: { UiStepper: false, GuidanceModeSelector: false, UiStepHeader: false },
    },
  });
  return { wrapper, guidance };
}

describe("expert section access in sprint 36", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    state.route = reactive({ params: { projectId: "project" } });
    vi.spyOn(apiClient, "getProject").mockResolvedValue({
      id: "project",
      display_name: "Example",
      mode: "GREENFIELD_GENERATION",
      current_brief_version: 0,
      is_archived: false,
      created_at: "2026-10-03T00:00:00Z",
      updated_at: "2026-10-03T00:00:00Z",
    });
    vi.spyOn(apiClient, "listBriefVersions").mockResolvedValue([]);
    vi.spyOn(projectImportsApi, "origin").mockResolvedValue(null);
    vi.spyOn(sectionsApi, "read").mockResolvedValue(null);
  });
  afterEach(() => vi.restoreAllMocks());

  it("opens every expert section before the first loop while preserving truthful empty states", async () => {
    const { wrapper } = render(true);
    await flushPromises();
    const buttons = wrapper.get('[data-testid="stepper"]').findAll("button");
    expect(buttons).toHaveLength(6);
    expect(buttons.every((button) => !button.attributes("disabled"))).toBe(true);
    expect(buttons.map((button) => button.attributes("data-state"))).toEqual(
      Array(6).fill("NOT_STARTED"),
    );
    await buttons[4]!.trigger("click");
    expect(wrapper.findComponent(UiStepHeader).props("title")).toBe("Design & Evaluation");
    expect(wrapper.findComponent(UiStepHeader).props("description")).toBe("");
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("stage")).toBe(4);
    expect(wrapper.find('[data-testid="stage-design"]').isVisible()).toBe(true);
  });

  it("keeps the guided sequence and changes preference without requests or lost selection", async () => {
    const { wrapper, guidance } = render();
    await flushPromises();
    expect(wrapper.findComponent(UiStepHeader).props("description")).not.toBe("");
    expect(
      wrapper.get('[data-testid="stepper"]').findAll("button")[4]!.attributes("disabled"),
    ).toBeDefined();
    const getCount = vi.mocked(apiClient.getProject).mock.calls.length;
    const fetchImpl = vi.spyOn(globalThis, "fetch");
    guidance.select("EXPERT");
    await flushPromises();
    await wrapper.get('[data-testid="stepper"]').findAll("button")[3]!.trigger("click");
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("stage")).toBe(3);
    guidance.select("GUIDED");
    await flushPromises();
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("stage")).toBe(0);
    guidance.select("EXPERT");
    await flushPromises();
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("stage")).toBe(3);
    expect(vi.mocked(apiClient.getProject).mock.calls.length).toBe(getCount);
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(wrapper.findComponent(GuidanceModeSelector).exists()).toBe(true);
  });
});
