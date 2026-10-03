import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import type { ProjectNextAction, ProjectResponse, ProjectStage } from "@/api/contracts";
import ProjectImportDialog from "@/components/ProjectImportDialog.vue";
import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import { expectAccessible } from "@/test/axe";
import type { ProjectImportPayload } from "@/types/projectImports";
import ProjectsView from "./ProjectsView.vue";

function project(
  id: string,
  name: string,
  version = 1,
  mode: ProjectResponse["mode"] = "GREENFIELD_GENERATION",
  stage: ProjectStage = "BRIEF",
  action: ProjectNextAction = "APPROVE_BRIEF",
): ProjectResponse {
  return {
    id,
    display_name: name,
    mode,
    current_brief_version: version,
    is_archived: false,
    created_at: "2026-09-27T09:00:00Z",
    updated_at: "2026-09-27T09:00:00Z",
    current_stage: stage,
    next_action: action,
  };
}

function legacy(id: string, name: string): ProjectResponse {
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

async function mountProjects(locale: "it" | "en" = "it") {
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
    global: { plugins: [pinia, createAppI18n(locale), router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, push };
}

function dialog(wrapper: Awaited<ReturnType<typeof mountProjects>>["wrapper"]) {
  return wrapper.find('[role="dialog"]');
}

function checkedStart(wrapper: Awaited<ReturnType<typeof mountProjects>>["wrapper"]): string {
  const checked = wrapper
    .findAll<HTMLInputElement>('input[name="project-start"]')
    .find((input) => input.element.checked);
  return checked?.element.value ?? "";
}

describe("projects page", () => {
  beforeEach(() => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([EXISTING]);
  });

  it.each([
    ["it", "Tocca a te: Aggiorna le sezioni"],
    ["en", "Your turn: Update the sections"],
  ] as const)("shows the available sections gesture in %s", async (locale, expected) => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      project(
        "existing",
        "Workshop guest list",
        2,
        "GREENFIELD_GENERATION",
        "TEAM",
        "UPDATE_SECTIONS",
      ),
    ]);
    const { wrapper } = await mountProjects(locale);
    expect(wrapper.get('[data-testid="project-next"]').text().replace(/\s+/g, " ")).toBe(expected);
    wrapper.unmount();
  });

  it("offers to start from a knowledge folder next to the usual new project", async () => {
    const { wrapper } = await mountProjects();
    const start = wrapper.get('[data-testid="import-project"]');
    expect(start.text()).toBe("Parti da una cartella di conoscenza");
    expect(start.attributes("aria-haspopup")).toBe("dialog");
    expect(dialog(wrapper).exists()).toBe(false);
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);

    await start.trigger("click");
    await flushPromises();
    expect(dialog(wrapper).attributes("aria-modal")).toBe("true");
    expect(wrapper.get(`#${dialog(wrapper).attributes("aria-labelledby")}`).text()).toBe(
      "Nuovo progetto",
    );
    expect(checkedStart(wrapper)).toBe("folder");
    const importDialog = wrapper.getComponent(ProjectImportDialog);
    expect(importDialog.props("locale")).toBe("it");
    expect(wrapper.find("#project-name").exists()).toBe(false);

    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();
    expect(checkedStart(wrapper)).toBe("GREENFIELD_GENERATION");
    expect(wrapper.find("#project-name").exists()).toBe(true);
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);

    await wrapper.get('[data-testid="import-project"]').trigger("click");
    await flushPromises();
    expect(wrapper.find("#project-name").exists()).toBe(false);
    wrapper.getComponent(ProjectImportDialog).vm.$emit("cancel");
    await flushPromises();
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);
    expect(dialog(wrapper).exists()).toBe(false);
    wrapper.unmount();
  });

  it("lets the owner switch the starting point inside the dialog", async () => {
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();
    const labels = wrapper.findAll('[data-testid^="project-start-"]');
    expect(labels.map((label) => label.find("span").text())).toEqual([
      "Una nuova idea",
      "Un prodotto esistente",
      "Una cartella di conoscenza",
    ]);
    expect(dialog(wrapper).get("legend").text()).toBe("Da dove vuoi partire?");

    await wrapper.get('[data-testid="project-start-folder"] input').setValue(true);
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(true);
    expect(wrapper.find("#project-name").exists()).toBe(false);

    await wrapper.get('[data-testid="project-start-idea"] input').setValue(true);
    expect(wrapper.findComponent(ProjectImportDialog).exists()).toBe(false);
    expect(wrapper.get("#project-name").attributes("placeholder")).toBe(
      "Per esempio: Promemoria restituzioni",
    );
    wrapper.unmount();
  });

  it("creates a project with the chosen starting point and opens it", async () => {
    const created = project("created", "Front desk", 0, "BROWNFIELD_ASSESSMENT");
    const create = vi.spyOn(apiClient, "createProject").mockResolvedValue(created);
    const { wrapper, push } = await mountProjects();
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="project-start-existing"] input').setValue(true);
    await wrapper.get("#project-name").setValue("Front desk");
    expect(wrapper.get("#project-name").attributes("maxlength")).toBe("120");
    expect(wrapper.get("#project-name").attributes("required")).toBeDefined();
    await wrapper.get('[data-testid="create-project-submit"]').trigger("submit");
    await flushPromises();

    expect(create).toHaveBeenCalledWith("access-token", {
      display_name: "Front desk",
      mode: "BROWNFIELD_ASSESSMENT",
    });
    expect(push).toHaveBeenCalledWith({
      name: "project-detail",
      params: { projectId: "created" },
    });
    expect(dialog(wrapper).exists()).toBe(false);
    wrapper.unmount();
  });

  it("explains inside the dialog why a project could not be created", async () => {
    const { ApiError } = await import("@/api/client");
    vi.spyOn(apiClient, "createProject").mockRejectedValue(new ApiError(422, "invalid_project"));
    const { wrapper, push } = await mountProjects();
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();
    await wrapper.get("#project-name").setValue("Front desk");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(dialog(wrapper).get('[role="alert"]').text()).toBe(
      "I dati del progetto non sono validi.",
    );
    expect(push).not.toHaveBeenCalled();
    await wrapper.get('[data-testid="create-project-cancel"]').trigger("click");
    expect(dialog(wrapper).exists()).toBe(false);
    expect(wrapper.get('[role="alert"]').text()).toBe("I dati del progetto non sono validi.");
    wrapper.unmount();
  });

  it("closes the dialog with Escape and gives the focus back", async () => {
    const { wrapper } = await mountProjects();
    const opener = wrapper.get('[data-testid="new-project"]');
    (opener.element as HTMLElement).focus();
    await opener.trigger("click");
    await flushPromises();
    expect(document.activeElement).toBe(dialog(wrapper).element);

    await dialog(wrapper).trigger("keydown", { key: "Escape" });
    expect(dialog(wrapper).exists()).toBe(false);
    expect(document.activeElement).toBe(opener.element);
    wrapper.unmount();
  });

  it("keeps the keyboard focus inside the dialog", async () => {
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();
    const container = dialog(wrapper);
    const firstRadio = wrapper.get('[data-testid="project-start-idea"] input');
    const submit = wrapper.get('[data-testid="create-project-submit"]');

    await container.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(submit.element);

    await container.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(firstRadio.element);

    (wrapper.get("#project-name").element as HTMLElement).focus();
    await container.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(wrapper.get("#project-name").element);
    wrapper.unmount();
  });

  it("keeps the dialog open with Escape while the folder is being read", async () => {
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="import-project"]').trigger("click");
    await flushPromises();
    const importDialog = wrapper.getComponent(ProjectImportDialog);
    (importDialog.vm as unknown as { busy: boolean }).busy = true;
    await dialog(wrapper).trigger("keydown", { key: "Escape" });
    expect(dialog(wrapper).exists()).toBe(true);
    (importDialog.vm as unknown as { busy: boolean }).busy = false;
    await dialog(wrapper).trigger("keydown", { key: "Escape" });
    expect(dialog(wrapper).exists()).toBe(false);
    wrapper.unmount();
  });

  it("reloads the projects and opens the imported one", async () => {
    const list = vi
      .spyOn(apiClient, "listProjects")
      .mockResolvedValueOnce([EXISTING])
      .mockResolvedValueOnce([project("imported", "Reception desk"), EXISTING]);
    const { wrapper, push } = await mountProjects();
    await wrapper.get('[data-testid="import-project"]').trigger("click");
    await flushPromises();

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
    expect(dialog(wrapper).exists()).toBe(false);
    wrapper.unmount();
  });

  it("names every project link and keeps the rows free of table roles", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      EXISTING,
      project("second", "Workshop guest list"),
    ]);
    const { wrapper } = await mountProjects();
    const links = wrapper.get('[data-testid="project-rows"]').findAll("a");

    expect(links.map((link) => link.text())).toEqual(["Continua", "Continua"]);
    expect(links.map((link) => link.attributes("aria-label"))).toEqual([
      "Continua il progetto Workshop guest list",
      "Continua il progetto Workshop guest list",
    ]);
    expect(links.map((link) => link.attributes("href"))).toEqual([
      "/projects/existing",
      "/projects/second",
    ]);
    expect(wrapper.find('[role="row"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="project-columns"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows for every project its step out of six, the step and what the owner does next", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      project("fresh", "Guest list", 0, "GREENFIELD_GENERATION", "BRIEF", "DESCRIBE_IDEA"),
      project(
        "drafted",
        "Tip calculator",
        2,
        "GREENFIELD_GENERATION",
        "REQUIREMENTS",
        "APPROVE_REQUIREMENTS",
      ),
      project("legacy", "Front desk", 1, "BROWNFIELD_ASSESSMENT", "PACKAGE", "DOWNLOAD_FOLDER"),
    ]);
    const { wrapper } = await mountProjects();
    const rows = wrapper.findAll('[data-testid="project-row"]');
    const read = (index: number, hook: string) =>
      rows[index]?.get(`[data-testid="${hook}"]`).text().replace(/\s+/g, " ");
    const states = (index: number) =>
      rows[index]
        ?.findAll("[data-step-state]")
        .map((segment) => segment.attributes("data-step-state"));

    expect(rows.map((row) => row.attributes("data-project-stage"))).toEqual([
      "BRIEF",
      "REQUIREMENTS",
      "PACKAGE",
    ]);
    expect([0, 1, 2].map((index) => read(index, "project-step-number"))).toEqual([
      "01 /06",
      "04 /06",
      "06 /06",
    ]);
    expect(rows[0]?.get('[data-testid="project-step-number"]').attributes("aria-hidden")).toBe(
      "true",
    );
    expect([0, 1, 2].map((index) => read(index, "project-stage"))).toEqual([
      "Brief",
      "Definizione",
      "Dossier",
    ]);
    expect([0, 1, 2].map((index) => read(index, "project-next"))).toEqual([
      "Tocca a te: Racconta la tua idea",
      "Tocca a te: Approva i requisiti",
      "Tocca a te: Scarica la cartella",
    ]);
    expect(read(1, "project-step-track")).toBe("Passo 4 di 6");
    expect(states(0)).toEqual(["current", "pending", "pending", "pending", "pending", "pending"]);
    expect(states(1)).toEqual(["done", "done", "done", "current", "pending", "pending"]);
    expect(states(2)).toEqual(["done", "done", "done", "done", "done", "current"]);
    expect(rows[0]?.text()).not.toContain("Un prodotto esistente");
    expect(rows[2]?.text()).toContain("Un prodotto esistente");
    const date = rows[1]?.get("time");
    expect(date?.attributes("datetime")).toBe("2026-09-27T09:00:00Z");
    expect(date?.text()).toBe(
      new Intl.DateTimeFormat("it", { dateStyle: "medium" }).format(
        new Date("2026-09-27T09:00:00Z"),
      ),
    );
    expect(wrapper.get('[data-testid="projects-count"]').text()).toBe(
      "Area di lavoro · 3 progetti",
    );
    wrapper.unmount();
  });

  it.each<[ProjectStage, ProjectNextAction, string, string]>([
    ["BRIEF", "APPROVE_BRIEF", "Brief", "Your turn: Approve the brief"],
    ["TEAM", "APPROVE_TEAM", "Perspectives", "Your turn: Approve the perspectives"],
    ["USER_TWINS", "CONFIRM_TWINS", "User Twin", "Your turn: Confirm the twins"],
    ["USER_TWINS", "PREPARE_TWINS", "User Twin", "Your turn: Prepare the twins again"],
    ["REQUIREMENTS", "APPROVE_REQUIREMENTS", "Definition", "Your turn: Approve the requirements"],
    ["DESIGN", "APPROVE_DESIGN", "Design & Evaluation", "Your turn: Choose and approve the design"],
    ["DESIGN", "PREPARE_DESIGN", "Design & Evaluation", "Your turn: Prepare the design again"],
    ["PACKAGE", "DOWNLOAD_FOLDER", "Dossier", "Your turn: Download the folder"],
  ])("names the step %s and its action in English", async (stage, action, name, next) => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      project("one", "Guest list", 1, "GREENFIELD_GENERATION", stage, action),
    ]);
    const { wrapper } = await mountProjects("en");
    const row = wrapper.get('[data-testid="project-row"]');

    expect(row.get('[data-testid="project-stage"]').text()).toBe(name);
    expect(row.get('[data-testid="project-next"]').text().replace(/\s+/g, " ")).toBe(next);
    wrapper.unmount();
  });

  it.each<[ProjectStage, ProjectNextAction, string, string]>([
    ["TEAM", "APPROVE_TEAM", "Prospettive", "Tocca a te: Approva le prospettive"],
    ["USER_TWINS", "CONFIRM_TWINS", "User Twin", "Tocca a te: Conferma i twin"],
    ["USER_TWINS", "PREPARE_TWINS", "User Twin", "Tocca a te: Prepara di nuovo i twin"],
    ["DESIGN", "APPROVE_DESIGN", "Design e valutazione", "Tocca a te: Scegli e approva il design"],
    ["DESIGN", "PREPARE_DESIGN", "Design e valutazione", "Tocca a te: Prepara di nuovo il design"],
  ])("names the step %s and its action in Italian", async (stage, action, name, next) => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      project("one", "Guest list", 1, "GREENFIELD_GENERATION", stage, action),
    ]);
    const { wrapper } = await mountProjects("it");
    const row = wrapper.get('[data-testid="project-row"]');

    expect(row.get('[data-testid="project-stage"]').text()).toBe(name);
    expect(row.get('[data-testid="project-next"]').text().replace(/\s+/g, " ")).toBe(next);
    wrapper.unmount();
  });

  it.each<["it" | "en", string]>([
    [
      "it",
      "Parti da un prodotto che esiste già: lo Studio ne tiene conto quando prepara le prospettive.",
    ],
    [
      "en",
      "Start from a product that already exists: the Studio takes it into account when it prepares the perspectives.",
    ],
  ])("speaks of perspectives for an existing product in %s", async (locale, text) => {
    const { wrapper } = await mountProjects(locale);
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="project-start-existing"]').text()).toContain(text);
    expect(wrapper.get('[role="dialog"]').text()).not.toMatch(/squadra|\bteam\b/i);
    wrapper.unmount();
  });

  it("keeps a plain row when the server does not say the step yet", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([legacy("old", "Old server")]);
    const { wrapper } = await mountProjects();
    const row = wrapper.get('[data-testid="project-row"]');

    expect(row.attributes("data-project-stage")).toBeUndefined();
    expect(row.find('[data-testid="project-step-number"]').exists()).toBe(false);
    expect(row.find('[data-testid="project-step-track"]').exists()).toBe(false);
    expect(row.find('[data-testid="project-next"]').exists()).toBe(false);
    expect(row.text()).toContain("Old server");
    expect(row.get("a").text()).toBe("Continua");
    wrapper.unmount();
  });

  it("keeps the list short and shows the other projects on request", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue(
      Array.from({ length: 14 }, (_, index) => project(`p${index}`, `Project ${index}`)),
    );
    const { wrapper } = await mountProjects();
    expect(wrapper.findAll('[data-testid="project-row"]')).toHaveLength(12);
    const more = wrapper.get('[data-testid="show-all-projects"]');
    expect(more.text()).toBe("Mostra gli altri 2 progetti");

    await more.trigger("click");
    await flushPromises();
    expect(wrapper.findAll('[data-testid="project-row"]')).toHaveLength(14);
    expect(wrapper.find('[data-testid="show-all-projects"]').exists()).toBe(false);
    expect(document.activeElement?.getAttribute("aria-label")).toBe(
      "Continua il progetto Project 12",
    );
    wrapper.unmount();
  });

  it("names a single project and a single hidden project in the singular", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue(
      Array.from({ length: 13 }, (_, index) => project(`p${index}`, `Project ${index}`)),
    );
    const { wrapper } = await mountProjects("en");
    expect(wrapper.get('[data-testid="show-all-projects"]').text()).toBe("Show the other project");
    expect(wrapper.get('[data-testid="projects-count"]').text()).toBe("Workspace · 13 projects");
    wrapper.unmount();

    vi.spyOn(apiClient, "listProjects").mockResolvedValue([EXISTING]);
    const single = await mountProjects();
    expect(single.wrapper.get('[data-testid="projects-count"]').text()).toBe(
      "Area di lavoro · 1 progetto",
    );
    single.wrapper.unmount();
  });

  it("invites the owner to start when there is no project yet", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([]);
    const { wrapper } = await mountProjects();
    expect(wrapper.find('[data-testid="project-rows"]').exists()).toBe(false);
    expect(wrapper.get('[data-state="empty"]').text()).toContain("Nessun progetto presente");
    expect(wrapper.get('[data-testid="projects-count"]').text()).toBe("Area di lavoro");
    wrapper.unmount();
  });

  it("explains a failed load without claiming that there is no project", async () => {
    const { ApiError } = await import("@/api/client");
    vi.spyOn(apiClient, "listProjects").mockRejectedValue(
      new ApiError(500, "unexpected_api_error"),
    );
    const { wrapper } = await mountProjects();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Il server ha restituito una risposta inattesa.",
    );
    expect(wrapper.find('[data-state="empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="project-rows"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("says that the projects are loading before the list arrives", async () => {
    let resolve!: (value: readonly ProjectResponse[]) => void;
    vi.spyOn(apiClient, "listProjects").mockImplementation(
      () =>
        new Promise<readonly ProjectResponse[]>((done) => {
          resolve = done;
        }),
    );
    const { wrapper } = await mountProjects();
    expect(wrapper.get('[data-state="loading"]').attributes("role")).toBe("status");
    resolve([EXISTING]);
    await flushPromises();
    expect(wrapper.find('[data-state="loading"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="project-row"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("has no axe violations with projects in the list and the knowledge folder card open", async () => {
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="import-project"]').trigger("click");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });

  it("has no axe violations with the new project form open", async () => {
    vi.spyOn(apiClient, "listProjects").mockResolvedValue([
      project("fresh", "Guest list", 0),
      EXISTING,
    ]);
    const { wrapper } = await mountProjects();
    await wrapper.get('[data-testid="new-project"]').trigger("click");
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
