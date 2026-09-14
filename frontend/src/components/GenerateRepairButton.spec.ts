import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import GenerateRepairButton from "./GenerateRepairButton.vue";

describe("model repair proposal", () => {
  it("binds the proposal to the failure and emits for review without applying it", async () => {
    const api = { source: vi.fn(), repair: vi.fn().mockResolvedValue({ id: "proposal" }) };
    const wrapper = mount(GenerateRepairButton, {
      props: {
        projectId: "project",
        platform: "web",
        executionId: "execution",
        baseRevisionHash: "base-hash",
        failureSignature: "failure-hash",
        api,
        authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      },
      global: { plugins: [createPinia()] },
    });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(api.repair).toHaveBeenCalledExactlyOnceWith(
      "project",
      "web",
      "execution",
      { base_revision_content_hash: "base-hash", failure_signature_digest: "failure-hash" },
      "token",
    );
    expect(wrapper.emitted("generated")).toHaveLength(1);
    expect(wrapper.text()).toContain("Review the changes before applying them");
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
  });

  it("does not generate repairs for stale attempts", async () => {
    const api = { source: vi.fn(), repair: vi.fn() };
    const wrapper = mount(GenerateRepairButton, {
      props: {
        projectId: "project",
        platform: "jvm",
        executionId: "old",
        baseRevisionHash: "base",
        failureSignature: "failure",
        disabled: true,
        api,
      },
      global: { plugins: [createPinia()] },
    });
    await wrapper.get("button").trigger("click");
    expect(api.repair).not.toHaveBeenCalled();
  });
});
