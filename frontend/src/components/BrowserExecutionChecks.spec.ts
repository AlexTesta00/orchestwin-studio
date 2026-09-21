import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BrowserExecutionChecks from "./BrowserExecutionChecks.vue";

describe("browser behavior checks", () => {
  it("requires real selectors and expected outcomes for both input modes", async () => {
    const wrapper = mount(BrowserExecutionChecks);
    expect(wrapper.emitted("change")!.at(-1)).toEqual([null]);
    const steps = wrapper.findAll("li");
    await steps[0]!.find("input").setValue("#submit");
    await steps[1]!.findAll("input")[0]!.setValue("#result");
    await steps[1]!.findAll("input")[1]!.setValue("Saved once");
    await steps[2]!.findAll("input")[0]!.setValue("#submit");
    await steps[3]!.findAll("input")[0]!.setValue("#result");
    await steps[3]!.findAll("input")[1]!.setValue("Saved twice");
    await flushPromises();
    const checks = wrapper.emitted("change")!.at(-1)![0];
    expect(checks).toEqual({
      declared_routes: [],
      browser_interactions: [
        {
          route_id: "root",
          actions: [
            { kind: "click", selector: "#submit", value: null },
            { kind: "expect_text", selector: "#result", value: "Saved once" },
            { kind: "press", selector: "#submit", value: "Enter" },
            { kind: "expect_text", selector: "#result", value: "Saved twice" },
          ],
        },
      ],
    });
    await steps[3]!.find("select").setValue("click");
    await flushPromises();
    expect(wrapper.emitted("change")!.at(-1)).toEqual([null]);
  });
});
