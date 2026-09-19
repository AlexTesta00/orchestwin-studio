import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import ModelRuntimeStatus from "./ModelRuntimeStatus.vue";

describe("model runtime status", () => {
  it("shows development mode and refreshes from a fresh readiness response", async () => {
    const query = vi
      .fn()
      .mockResolvedValueOnce({ mode: "DEVELOPMENT_FIXTURES", ready: false })
      .mockResolvedValueOnce({ mode: "REAL_REQUIRED", ready: true });
    const wrapper = mount(ModelRuntimeStatus, {
      props: {
        query,
        authorize: <T>(operation: (token: string) => Promise<T>) => operation("token"),
      },
      global: { plugins: [createPinia()] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("Real AI assistants are not connected");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("assistants are connected and ready");
    expect(query).toHaveBeenCalledTimes(2);
  });
});
