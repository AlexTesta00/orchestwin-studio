import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";
import UiProgressBar from "./UiProgressBar.vue";
import { expectAccessible } from "@/test/axe";

function states(wrapper: ReturnType<typeof mount>): (string | undefined)[] {
  return wrapper.findAll("[data-step-state]").map((node) => node.attributes("data-step-state"));
}

describe("progress bar", () => {
  it("shows the step position with one segment per step", () => {
    const wrapper = mount(UiProgressBar, {
      props: { current: 3, total: 8 },
      global: { plugins: [createAppI18n("it")] },
    });
    expect(wrapper.text()).toContain("Passo 3 di 8");
    const bar = wrapper.get("[role='progressbar']");
    expect(bar.attributes("aria-valuenow")).toBe("3");
    expect(bar.attributes("aria-valuemax")).toBe("8");
    expect(bar.attributes("aria-valuetext")).toBe("Passo 3 di 8");
    expect(states(wrapper)).toEqual([
      "done",
      "done",
      "current",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("keeps later closed steps marked as done while an earlier step is reread", () => {
    const wrapper = mount(UiProgressBar, {
      props: { current: 2, reached: 5, total: 8 },
      global: { plugins: [createAppI18n("en")] },
    });
    expect(wrapper.text()).toContain("Step 2 of 8");
    expect(states(wrapper)).toEqual([
      "done",
      "current",
      "done",
      "done",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("has no axe violations", async () => {
    const wrapper = mount(UiProgressBar, {
      props: { current: 3, total: 8 },
      global: { plugins: [createAppI18n("it")] },
    });
    await expectAccessible(wrapper.element);
  });
});
