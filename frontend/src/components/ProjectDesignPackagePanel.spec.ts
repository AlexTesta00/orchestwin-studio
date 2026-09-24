import { createPinia, setActivePinia } from "pinia";

import { flushPromises, mount } from "@vue/test-utils";

import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDesignPackagePanel from "./ProjectDesignPackagePanel.vue";
import { createAppI18n } from "@/i18n";
import { SELECTED_DESIGN_VERSION } from "@/test/designFixtures";

import type { DesignPackageApi } from "../api/designPackage";
import { useDesignStore } from "../stores/design";
import { useUserModelingStore } from "../stores/userModeling";
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

function mountPanel(api: DesignPackageApi, saveExport = vi.fn()) {
  const wrapper = mount(ProjectDesignPackagePanel, {
    global: { plugins: [createAppI18n("en")] },
    props: {
      projectId: PROJECT_ID,
      stages: STAGES,
      locale: "en",
      authorize: (operation) => operation("access-token"),
      api,
      saveExport,
    },
  });
  return { wrapper, saveExport };
}

describe("ProjectDesignPackagePanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const design = useDesignStore();
    design.$patch({ projectId: PROJECT_ID, current: SELECTED_DESIGN_VERSION });
    const modeling = useUserModelingStore();
    modeling.$patch({
      projectId: PROJECT_ID,
      twinVersions: [twin("Receptionist"), twin("Manager")],
    });
  });

  it("summarises the approved path, the chosen design with its mockup and the twins", async () => {
    const api: DesignPackageApi = { download: vi.fn() };
    const { wrapper } = mountPanel(api);
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
    wrapper.unmount();
  });

  it("downloads the package through the authorised request and hands the file to the saver", async () => {
    const blob = new Blob(["PK"], { type: "application/zip" });
    const download = vi.fn(async () => ({
      blob,
      fileName: "orchestwin-demo-design-package.zip",
      contentHash: null,
    }));
    const { wrapper, saveExport } = mountPanel({ download });

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(download).toHaveBeenCalledWith(PROJECT_ID, "access-token");
    expect(saveExport).toHaveBeenCalledWith(blob, "orchestwin-demo-design-package.zip");
    expect(wrapper.get('[data-testid="download-done"]').text()).toBe(
      "Package downloaded: orchestwin-demo-design-package.zip",
    );
    expect(wrapper.find('[data-testid="download-error"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("shows the failure without saving anything when the package is refused", async () => {
    const download = vi.fn(async () => {
      throw new Error("The design package request failed");
    });
    const { wrapper, saveExport } = mountPanel({ download });

    await wrapper.get('[data-testid="download-package"]').trigger("click");
    await flushPromises();

    expect(saveExport).not.toHaveBeenCalled();
    expect(wrapper.get('[data-testid="download-error"]').text()).toBe(
      "The design package request failed",
    );
    expect(wrapper.get('[data-testid="download-package"]').attributes("disabled")).toBeUndefined();
    wrapper.unmount();
  });
});
