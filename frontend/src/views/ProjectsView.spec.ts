import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import type { ProjectResponse } from "@/api/contracts";
import ProjectImportDialog from "@/components/ProjectImportDialog.vue";
import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import { expectAccessible } from "@/test/axe";
import type { ProjectImportPayload } from "@/types/projectImports";
import ProjectsView from "./ProjectsView.vue";

function project(id: string, name: string): ProjectResponse {
  return {
    id,
    display_name: name,
    mode: "GREENFIELD_GENERATION",
    current_brief_version: 1,
    is_archived: false,
    created_at: "2026-09-27T09:00:00Z",
    updated_at: "2026-09-27T09:00:00Z",
  };
}

const EXISTING = project("existing", "Workshop guest list");

const IMPORTED: ProjectImportPayload = {
  project: {
    id: "imported",
    display_name: "Reception desk",
    mode: "GREENFIELD_GENERATION",
    created_at: "2026-09-27T10:00:00Z",
  },
  origin: {
    project_id: "source",
    project_name: "Reception desk",
    package_version: 3,
    package_content_hash: "a".repeat(64),
    schema_version: 2,
  },
  stages: {},
  twins: [],
  imported_at: "2026-09-27T10:00:00Z",
  approval_required: ["brief", "team", "twins", "requirements", "design"],
};

async function mountProjects() {
  const router = createAppRouter(createMemoryHistory());
  const pinia = createPinia();
  useAuthStore(pinia).$patch({
    status: "authenticated",
    user: {
      id: "00000000-0000-4000-8000-000000000001",
      email: "owner@example.com",
      is_active: true,
      created_at: "2026-08-10T12:00:00Z",
    },
    accessToken: "access-token",
    expiresAt: "2026-08-10T12:15:00Z",
  });
  await router.push("/");
  await router.isReady();
  const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
  const wrapper = mount(ProjectsView, {
    global: { plugins: [pinia, createAppI18n("it"), router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, push };
}

describe("projects page", () => {
  beforeEach(() => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([EXISTING]);
  });

  it("offers to start from a knowledge folder next to the usual new project", async () => {
    const { wrapper } = await mountProjects();
    const start = wrapper.get('[data-testid="import-project"]');
    expect(start.text()).toBe("Parti da una cartella di conoscenza");
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);

    await start.trigger("click");
    const dialog = wrapper.getComponent(ProjectImportDialog);
    expect(dialog.props("locale")).toBe("it");
    expect(dialog.get("h2").text()).toBe("Parti da una cartella di conoscenza");

    await wrapper.get('[data-testid="new-project"]').trigger("click");
    expect(wrapper.find("#project-name").exists()).toBe(true);
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);

    await wrapper.get('[data-testid="import-project"]').trigger("click");
    expect(wrapper.find("#project-name").exists()).toBe(false);
    wrapper.getComponent(ProjectImportDialog).vm.$emit("cancel");
    await flushPromises();
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);
    wrapper.unmount();
  });

  it("reloads the projects and opens the imported one", async () => {
    const list = vi
      .spyOn(apiClient, "listProjects")
      .mockResolvedValueOnce([EXISTING])
      .mockResolvedValueOnce([project("imported", "Reception desk"), EXISTING]);
    const { wrapper, push } = await mountProjects();
    await wrapper.get('[data-testid="import-project"]').trigger("click");

    wrapper.getComponent(ProjectImportDialog).vm.$emit("imported", IMPORTED);
    await flushPromises();

    expect(list).toHaveBeenCalledTimes(2);
    expect(list).toHaveBeenLastCalledWith("access-token");
    expect(wrapper.get('[data-testid="project-rows"]').text()).toContain("Reception desk");
    expect(push).toHaveBeenCalledWith({
      name: "project-detail",
      params: { projectId: "imported" },
    });
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);
    wrapper.unmount();
  });

  it("names every project link and keeps the column titles out of the reading order", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      EXISTING,
      project("second", "Workshop guest list"),
    ]);
    const { wrapper } = await mountProjects();
    const links = wrapper.get('[data-testid="project-rows"]').findAll("a");

    expect(links.map((link) => link.text())).toEqual(["Apri", "Apri"]);
    expect(links.map((link) => link.attributes("aria-label"))).toEqual([
      "Apri Workshop guest list",
      "Apri Workshop guest list",
    ]);
    expect(wrapper.get('[data-testid="project-columns"]').attributes("aria-hidden")).toBe("true");
    expect(wrapper.find('[role="row"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("has no axe violations with projects in the list and the knowledge folder card open", async () => {
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="import-project"]').trigger("click");

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
