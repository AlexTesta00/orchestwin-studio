import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDesignPackagePanel from "./ProjectDesignPackagePanel.vue";
import { createAppI18n } from "@/i18n";
import { expectAccessible } from "@/test/axe";
import { SELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import { KnowledgePackagesApiError, type KnowledgePackagesApi } from "../api/knowledgePackages";
import { useDesignStore } from "../stores/design";
import { useUserModelingStore } from "../stores/userModeling";
import type { KnowledgePackageVersionPayload } from "../types/knowledgePackages";
import type { UserTwinVersionPayload } from "../types/userModeling";

const PROJECT_ID = SELECTED_DESIGN_VERSION.project_id;
const STAGES = [
  { label: "Brief", version: 2, approved: true },
  { label: "Team", version: 1, approved: true },
  { label: "User Twins", version: 1, approved: true },
  { label: "Requirements", version: 3, approved: true },
  { label: "Design", version: 1, approved: true },
];

function twin(name: string): UserTwinVersionPayload {
  return { id: `twin-${name}`, profile: { name } } as unknown as UserTwinVersionPayload;
}

function version(number: number): KnowledgePackageVersionPayload {
  return {
    id: `00000000-0000-4000-8000-00000000c00${number}`,
    project_id: PROJECT_ID,
    project_name: "Lista ospiti workshop",
    version_number: number,
    schema_version: 2,
    content_hash: String(number).repeat(64),
    archive_hash: "a".repeat(64),
    file_name: `orchestwin-${PROJECT_ID}-knowledge-v${number}.zip`,
    file_count: 54,
    archive_size: 150000,
    created_at: "2026-09-27T20:00:00Z",
    stages: [],
    twins: [
      {
        twin_id: "00000000-0000-4000-8000-0000000000a1",
        name: "Addetti all'accoglienza",
        slug: "addetti-all-accoglienza-00000000",
        version_number: 1,
        document: "twins/addetti-all-accoglienza-00000000/twin.json",
      },
    ],
    feedback: { reviews: 5, findings: 44, decisions: 2, discussions: 6, insights: 1 },
    diagram_count: 7,
    table_count: 14,
    entries: ["ORCHESTWIN.md"],
  };
}

function knowledgeApi(overrides: Partial<KnowledgePackagesApi> = {}): KnowledgePackagesApi {
  return {
    publish: vi.fn(() => Promise.resolve({ reused: false, version: version(2) })),
    history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [version(1)] })),
    download: vi.fn((_project: string, number: number) =>
      Promise.resolve({
        blob: new Blob(["PK"], { type: "application/zip" }),
        fileName: `orchestwin-${PROJECT_ID}-knowledge-v${number}.zip`,
        archiveHash: "a".repeat(64),
      }),
    ),
    ...overrides,
  };
}

function mountPanel(
  api: KnowledgePackagesApi,
  options: { stages?: typeof STAGES; locale?: "en" | "it"; saveExport?: () => void } = {},
) {
  const saveExport = options.saveExport ?? vi.fn();
  const wrapper = mount(ProjectDesignPackagePanel, {
    global: { plugins: [createAppI18n(options.locale ?? "en")] },
    props: {
      projectId: PROJECT_ID,
      stages: options.stages ?? STAGES,
      locale: options.locale ?? "en",
      authorize: (operation) => operation("access-token"),
      api,
      saveExport,
    },
    attachTo: document.body,
  });
  return { wrapper, saveExport };
}

describe("ProjectDesignPackagePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    const design = useDesignStore();
    design.$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    const modeling = useUserModelingStore();
    modeling.$patch({
      projectId: PROJECT_ID,
      twinVersions: [twin("Receptionist"), twin("Manager")],
    });
  });

  it("summarises the approved path, the chosen design with its mockup and the twins", async () => {
    const { wrapper } = mountPanel(knowledgeApi());
    await flushPromises();

    const stages = wrapper.findAll('[data-testid="package-stage"]');
    expect(stages).toHaveLength(5);
    expect(stages[0]?.text()).toContain("1. Brief");
    expect(stages[0]?.text()).toContain("version 2");
    expect(stages[0]?.text()).toContain("approved");
    expect(wrapper.get('[data-testid="package-alternative"]').text()).toContain(
      SELECTED_DESIGN_VERSION.package.alternatives[0]?.title ?? "",
    );
    expect(wrapper.findComponent({ name: "DeclarativePrototypePreview" }).exists()).toBe(true);
    expect(wrapper.findAll('[data-testid="package-twin"]').map((item) => item.text())).toEqual([
      "Receptionist",
      "Manager",
    ]);
    expect(wrapper.findAll('[data-testid="package-step"]')).toHaveLength(4);
    wrapper.unmount();
  });

  it("lists the versions already prepared and what the latest one contains", async () => {
    const api = knowledgeApi({
      history: vi.fn(() =>
        Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
      ),
    });
    const { wrapper } = mountPanel(api, { locale: "it" });
    await flushPromises();

    const versions = wrapper.findAll('[data-testid="package-version"]');
    expect(api.history).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(
      wrapper.findAll('[data-testid="package-version-title"]').map((item) => item.text()),
    ).toEqual(["Versione 2", "Versione 1"]);
    expect(versions[0]!.text()).toContain("54 file");
    expect(versions[0]!.get("button").attributes("aria-label")).toBe("Scarica la versione 2");
    const contents = wrapper.get('[data-testid="package-contents"]').text();
    expect(contents).toContain("1 twin, ciascuno con un proprio file riutilizzabile");
    expect(contents).toContain("7 diagrammi e 14 tabelle di requisiti e design");
    expect(contents).toContain("5 revisioni dei twin, 2 tue decisioni, 6 discussioni approvate");
    wrapper.unmount();
  });

  it("prepares a new version and downloads it", async () => {
    const api = knowledgeApi();
    const { wrapper, saveExport } = mountPanel(api);
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(api.publish).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(api.download).toHaveBeenCalledWith(PROJECT_ID, 2, "access-token");
    expect(saveExport).toHaveBeenCalledTimes(1);
    expect(saveExport).toHaveBeenCalledWith(
      expect.any(Blob),
      `orchestwin-${PROJECT_ID}-knowledge-v2.zip`,
    );
    expect(wrapper.get('[data-testid="download-done"]').text()).toBe(
      `Version 2 of the folder is ready and downloaded: orchestwin-${PROJECT_ID}-knowledge-v2.zip`,
    );
    expect(
      wrapper.findAll('[data-testid="package-version-title"]').map((item) => item.text()),
    ).toEqual(["Version 2", "Version 1"]);
    wrapper.unmount();
  });

  it("says that nothing changed when the latest version is reused", async () => {
    const api = knowledgeApi({
      publish: vi.fn(() => Promise.resolve({ reused: true, version: version(1) })),
    });
    const { wrapper, saveExport } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(saveExport).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="download-done"]').text()).toContain(
      "Non è cambiato nulla dalla versione 1",
    );
    expect(wrapper.findAll('[data-testid="package-version"]')).toHaveLength(1);
    wrapper.unmount();
  });

  it("downloads an earlier version exactly as it was", async () => {
    const api = knowledgeApi({
      history: vi.fn(() =>
        Promise.resolve({ project_id: PROJECT_ID, versions: [version(2), version(1)] }),
      ),
    });
    const { wrapper, saveExport } = mountPanel(api);
    await flushPromises();

    await wrapper.findAll('[data-testid="download-version"]')[1]!.trigger("click");
    await flushPromises();

    expect(api.publish).not.toHaveBeenCalled();
    expect(api.download).toHaveBeenCalledWith(PROJECT_ID, 1, "access-token");
    expect(saveExport).toHaveBeenCalledWith(
      expect.any(Blob),
      `orchestwin-${PROJECT_ID}-knowledge-v1.zip`,
    );
    wrapper.unmount();
  });

  it("waits for the five approvals before preparing the folder", async () => {
    const stages = STAGES.map((stage, index) => ({ ...stage, approved: index < 4 }));
    const api = knowledgeApi({
      history: vi.fn(() => Promise.resolve({ project_id: PROJECT_ID, versions: [] })),
    });
    const { wrapper } = mountPanel(api, { stages, locale: "it" });
    await flushPromises();

    expect(wrapper.get('[data-testid="download-package"]').attributes("disabled")).toBeDefined();
    expect(wrapper.get('[data-testid="package-not-ready"]').text()).toContain(
      "quando tutti e cinque i passi sono approvati",
    );
    expect(wrapper.get('[data-testid="package-no-history"]').text()).toBe(
      "Non hai ancora preparato nessuna versione.",
    );
    expect(wrapper.find('[data-testid="package-contents"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("explains a missing approval reported by the server and other failures", async () => {
    const refused = knowledgeApi({
      publish: vi.fn(() =>
        Promise.reject(
          new KnowledgePackagesApiError("The knowledge package request failed", {
            status: 409,
            code: "DESIGN_APPROVAL_REQUIRED",
            payload: null,
          }),
        ),
      ),
    });
    const broken = knowledgeApi({
      publish: vi.fn(() => Promise.reject(new Error("network down"))),
    });
    const first = mountPanel(refused);
    await flushPromises();
    await first.wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();
    const refusedText = first.wrapper.get('[data-testid="download-error"]').text();
    first.wrapper.unmount();
    setActivePinia(createPinia());
    const second = mountPanel(broken);
    await flushPromises();
    await second.wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(refusedText).toContain("when all five steps are approved");
    expect(first.saveExport).not.toHaveBeenCalled();
    expect(second.wrapper.get('[data-testid="download-error"]').text()).toBe(
      "The folder could not be prepared.",
    );
    expect(second.wrapper.get('[data-testid="download-error"]').attributes("role")).toBe("alert");
    second.wrapper.unmount();
  });

  it.each([
    ["TEAM_OUTDATED", "Apri il passo Squadra"],
    ["USER_TWINS_OUTDATED", "Apri il passo User Twin"],
    ["REQUIREMENTS_OUTDATED", "aggiornali ai twin attuali"],
    ["DESIGN_OUTDATED", "rigenera le alternative"],
  ])("says which step to update when the server reports %s", async (code, expected) => {
    const api = knowledgeApi({
      publish: vi.fn(() =>
        Promise.reject(
          new KnowledgePackagesApiError("The knowledge package request failed", {
            status: 409,
            code,
            payload: null,
          }),
        ),
      ),
    });
    const { wrapper, saveExport } = mountPanel(api, { locale: "it" });
    await flushPromises();

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="download-error"]').text()).toContain(expected);
    expect(saveExport).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    const { wrapper } = mountPanel(knowledgeApi(), { locale: "it" });
    await flushPromises();

    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
