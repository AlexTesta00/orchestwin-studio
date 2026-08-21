import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { SELECTED_DESIGN_PACKAGE } from "../test/designFixtures";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";

describe("DeclarativePrototypePreview", () => {
  it("renders trusted data and follows declared transitions", async () => {
    const prototype = SELECTED_DESIGN_PACKAGE.prototype;

    if (prototype === null) {
      throw new Error("The selected Design fixture requires a prototype");
    }

    const wrapper = mount(DeclarativePrototypePreview, {
      props: {
        prototype,
      },
    });

    expect(wrapper.text()).toContain("Availability");
    expect(wrapper.html()).not.toContain("v-html");

    await wrapper.get("button[data-trigger-element-id]").trigger("click");

    expect(wrapper.text()).toContain("Reservation");
    expect(wrapper.get("article[data-screen-id]").attributes("data-screen-id")).toBe(
      prototype.screens[1]?.id,
    );
  });
});
