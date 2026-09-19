import { createPinia } from "pinia";
import { reactive } from "vue";
import { createI18n } from "vue-i18n";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import type { ProjectResponse } from "@/api/contracts";
import ProjectDetailView from "./ProjectDetailView.vue";

const state = vi.hoisted(() => ({ route: {} as { params: { projectId: string } } }));
vi.mock("vue-router", () => ({ useRoute: () => state.route }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
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
        global: { plugins: [createPinia(), createI18n({ legacy: false, locale: "en" })] },
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
