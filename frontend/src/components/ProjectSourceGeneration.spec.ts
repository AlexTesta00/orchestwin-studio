import { createPinia, setActivePinia } from "pinia";
import { createAppI18n } from "@/i18n";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { useArchitectureStore } from "@/stores/architecture";
import { useWebExecutionStore } from "@/stores/webExecution";
import type {
  ArchitecturePackageVersionPayload,
  ArchitectureReadinessPayload,
} from "@/types/architecture";
import type { ExecutionProfilePayload } from "@/types/execution";
import type { GeneratedSource, SourceGenerationApi } from "@/api/sourceGeneration";
import { SourceGenerationApiError } from "@/api/sourceGeneration";
import ProjectSourceGeneration from "./ProjectSourceGeneration.vue";
import { expectAccessible } from "@/test/axe";

function setup(approved = true) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useArchitectureStore().$patch({
    projectId: "project",
    current: {
      id: "architecture",
      content_hash: "a".repeat(64),
    } as ArchitecturePackageVersionPayload,
    readiness: {
      status: approved ? "READY_FOR_IMPLEMENTATION" : "HUMAN_DECISION_REQUIRED",
    } as ArchitectureReadinessPayload,
  });
  const api: SourceGenerationApi = {
    source: vi.fn().mockResolvedValue({ version_number: 1 }),
    repair: vi.fn(),
  };
  const webReload = vi.spyOn(useWebExecutionStore(), "loadProject").mockResolvedValue();
  const wrapper = mount(ProjectSourceGeneration, {
    props: {
      projectId: "project",
      api,
      authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      catalogApi: {
        profiles: async () => [
          {
            supported_targets: ["WEB_STATIC", "WEB_VUE"],
            capability_status: "VALIDATED_LEVEL_D",
          } as ExecutionProfilePayload,
        ],
      },
    },
    global: { plugins: [pinia, createAppI18n("en")] },
  });
  return { wrapper, api, webReload };
}

describe("source generation", () => {
  it("explains a rejected model output and leaves retry available", async () => {
    const { wrapper, api } = setup();
    await wrapper.setProps({ locale: "it" });
    vi.mocked(api.source).mockRejectedValue(
      new SourceGenerationApiError("Source generation request failed", {
        status: 502,
        code: "INVALID_PROVIDER_OUTPUT",
        payload: null,
      }),
    );
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Il modello ha restituito una proposta non valida");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeUndefined();
  });
  it("requires the approved architecture before making a model request", async () => {
    const { wrapper, api } = setup(false);
    await flushPromises();
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.source).not.toHaveBeenCalled();
  });

  it.each(["WEB_STATIC", "WEB_VUE"] as const)(
    "generates %s with its approved architecture and refreshes source review",
    async (target) => {
      const { wrapper, api, webReload } = setup();
      await flushPromises();
      await wrapper.get("select").setValue(target);
      await wrapper.get("form").trigger("submit");
      await flushPromises();
      const platform = "web";
      expect(api.source).toHaveBeenCalledWith(
        "project",
        platform,
        expect.objectContaining({
          target,
          architecture_version_id: "architecture",
          architecture_content_hash: "a".repeat(64),
        }),
        "token",
      );
      expect(webReload).toHaveBeenCalledTimes(1);
      expect(wrapper.text()).toContain("Generated revision 1");
    },
  );

  it("does not replace the new project's state when an earlier generation finishes", async () => {
    const { wrapper, api, webReload } = setup();
    let finish!: (value: GeneratedSource) => void;
    vi.mocked(api.source).mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await wrapper.setProps({ projectId: "other-project" });
    finish({ version_number: 1 } as GeneratedSource);
    await flushPromises();
    expect(webReload).not.toHaveBeenCalled();
    expect(wrapper.text()).not.toContain("Generated revision 1");
  });

  it("keeps successful generation distinct from a failed refresh and prevents resubmission", async () => {
    const { wrapper, api, webReload } = setup();
    webReload.mockRejectedValue(new Error("connection interrupted"));
    await flushPromises();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.text()).toContain("Generated revision 1");
    expect(wrapper.text()).toContain("Sources were saved");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    await wrapper.get("form").trigger("submit");
    expect(api.source).toHaveBeenCalledTimes(1);
    await wrapper.get("select").setValue("WEB_VUE");
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("Generated revision 1");
  });

  it("has no axe violations", async () => {
    const { wrapper } = setup();
    await flushPromises();
    await expectAccessible(wrapper.element);
  });
});
