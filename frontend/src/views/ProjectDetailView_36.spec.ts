import { createPinia } from "pinia";
import { reactive } from "vue";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import type { GuidanceMode } from "@/api/contracts";
import { projectImportsApi } from "@/api/projectImports";
import { sectionsApi } from "@/api/sections";
import GuidanceModeNote from "@/components/GuidanceModeNote.vue";
import ProjectWorkflowInputsPanel from "@/components/ProjectWorkflowInputsPanel.vue";
import UiStepHeader from "@/components/UiStepHeader.vue";
import { createAppI18n } from "@/i18n";
import { useActivityJournalStore } from "@/stores/activityJournal";
import { useAuthStore } from "@/stores/auth";
import ProjectDetailView from "./ProjectDetailView.vue";

const state = vi.hoisted(() => ({ route: { params: { projectId: "project" } } }));
vi.mock("vue-router", () => ({ useRoute: () => state.route }));

function render(guidanceMode: GuidanceMode = "GUIDED") {
  const pinia = createPinia();
  const auth = useAuthStore(pinia);
  auth.user = {
    id: "owner",
    email: "owner@example.com",
    is_active: true,
    created_at: "2026-10-03T00:00:00Z",
    guidance_mode: guidanceMode,
  };
  auth.accessToken = "token";
  auth.status = "authenticated";
  const observe = vi.spyOn(useActivityJournalStore(pinia), "observe");
  const wrapper = shallowMount(ProjectDetailView, {
    global: {
      plugins: [pinia, createAppI18n("en")],
      stubs: { UiStepper: false, GuidanceModeNote: false, UiStepHeader: false },
    },
  });
  return { wrapper, observe };
}

describe("expert section access in sprint 36", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
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
    const { wrapper } = render("EXPERT");
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
    expect(wrapper.get('[data-testid="guidance-mode"]').attributes("data-mode")).toBe("EXPERT");
  });

  it("keeps the guided sequence of the account and shows its mode without a control to change it", async () => {
    const { wrapper } = render("GUIDED");
    await flushPromises();
    expect(wrapper.findComponent(UiStepHeader).props("description")).not.toBe("");
    expect(
      wrapper.get('[data-testid="stepper"]').findAll("button")[4]!.attributes("disabled"),
    ).toBeDefined();
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("stage")).toBe(0);
    expect(wrapper.findComponent(ProjectWorkflowInputsPanel).props("expert")).toBe(false);
    const note = wrapper.getComponent(GuidanceModeNote);
    expect(note.attributes("data-testid")).toBe("guidance-mode");
    expect(note.attributes("data-mode")).toBe("GUIDED");
    expect(note.text()).toContain("Guided mode");
    expect(note.text()).toContain("Chosen once for this account: it cannot be changed.");
    expect(note.findAll("button, input, select")).toHaveLength(0);
    expect(wrapper.find('[data-testid="guidance-selector"]').exists()).toBe(false);
  });

  it.each<GuidanceMode>(["GUIDED", "EXPERT"])(
    "tells the activity journal the %s mode of the account from the start",
    async (mode) => {
      const { observe } = render(mode);
      await flushPromises();
      expect(observe.mock.calls[0]?.[0]).toMatchObject({ mode, locale: "en" });
      expect(observe.mock.calls.every(([context]) => context.mode === mode)).toBe(true);
    },
  );
});
