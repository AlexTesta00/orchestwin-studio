import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { SELECTED_DESIGN_PACKAGE } from "../test/designFixtures";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";

describe("DeclarativePrototypePreview", () => {
  it("validates required controls, preserves entered values on return, and resets them", async () => {
    const prototype = structuredClone(SELECTED_DESIGN_PACKAGE.prototype!);
    const first = prototype.screens[0]!;
    first.elements.unshift({
      ...first.elements[0]!,
      id: "name-field",
      code: "ELM-000",
      kind: "TEXT_INPUT",
      content: "Guest name",
      accessible_name: "Guest name",
      field_name: "guest",
      required: true,
    });
    first.elements.unshift({
      ...first.elements[0]!,
      id: "choice-field",
      code: "ELM-CHOICE",
      kind: "SELECT",
      content: "Room",
      accessible_name: "Room",
      field_name: "room",
      required: true,
      options: ["Single", "Double"],
    });
    const wrapper = mount(DeclarativePrototypePreview, {
      props: { prototype },
      attachTo: document.body,
    });
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(first.id);
    expect(wrapper.get('[role="alert"]').text()).toContain("required fields");
    await wrapper.get('input[name="guest"]').setValue("Ada");
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(first.id);
    await wrapper.get('select[name="room"]').setValue("Double");
    await wrapper.get("button[data-trigger-element-id]").trigger("click");
    expect(wrapper.get("article").attributes("data-screen-id")).toBe(prototype.screens[1]!.id);
    expect(document.activeElement).toBe(wrapper.get("h4").element);
    await wrapper.get("nav button").trigger("click");
    expect((wrapper.get('input[name="guest"]').element as HTMLInputElement).value).toBe("Ada");
    await wrapper.get("header button").trigger("click");
    expect((wrapper.get('input[name="guest"]').element as HTMLInputElement).value).toBe("");
    wrapper.unmount();
  });

  it("renders model content as text and exposes phone sizing through accessible controls", async () => {
    const prototype = structuredClone(SELECTED_DESIGN_PACKAGE.prototype!);
    prototype.screens[0]!.elements[0]!.content = '<img src=x onerror="alert(1)">';
    const wrapper = mount(DeclarativePrototypePreview, { props: { prototype, locale: "it" } });
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.text()).toContain('<img src=x onerror="alert(1)">');
    await wrapper.get('[data-viewport="MOBILE"]').trigger("click");
    expect(wrapper.get("article").classes()).toContain("max-w-sm");
    expect(wrapper.get('[data-viewport="MOBILE"]').attributes("aria-pressed")).toBe("true");
    expect(wrapper.get('[data-viewport="MOBILE"]').text()).toBe("Telefono");
  });

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
