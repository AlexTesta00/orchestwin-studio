import { mount } from "@vue/test-utils";
import { h } from "vue";
import { describe, expect, it } from "vitest";

import { expectAccessible } from "@/test/axe";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiSurface from "./UiSurface.vue";

describe("agent message", () => {
  it("shows the avatar of the assistant, its role and the message", () => {
    const wrapper = mount(UiAgentMessage, {
      props: { roleLabel: "Designer UX/UI", avatar: "/team/ux.webp" },
      slots: { default: "Ho preparato due alternative." },
    });
    const image = wrapper.get("img");
    expect(image.attributes("src")).toBe("/team/ux.webp");
    expect(image.attributes("alt")).toBe("");
    expect(image.attributes("width")).toBe("52");
    const role = wrapper.get("p");
    expect(role.text()).toBe("Designer UX/UI");
    expect(role.classes()).toEqual(
      expect.arrayContaining(["font-mono", "uppercase", "tracking-label", "text-action"]),
    );
    expect(wrapper.text()).toContain("Ho preparato due alternative.");
  });

  it("describes the avatar when asked to", () => {
    const wrapper = mount(UiAgentMessage, {
      props: {
        roleLabel: "Analista delle esigenze",
        avatar: "/team/an.webp",
        avatarAlt: "Il robot dell'analista",
      },
    });
    expect(wrapper.get("img").attributes("alt")).toBe("Il robot dell'analista");
  });

  it("uses the colours for dark surfaces inside a dark surface", () => {
    const wrapper = mount(UiSurface, {
      slots: {
        default: () =>
          h(UiAgentMessage, { roleLabel: "Designer UX/UI", avatar: "/team/ux.webp" }, () => "Ciao"),
      },
    });
    const message = wrapper.get("[data-testid='agent-message']");
    expect(message.attributes("data-surface-context")).toBe("night");
    expect(message.classes()).toEqual(
      expect.arrayContaining(["bg-night-raised", "border-night-line"]),
    );
    expect(message.get("p").classes()).toContain("text-petrol-on-night-2");
  });

  it("has no axe violations", async () => {
    const wrapper = mount(UiAgentMessage, {
      props: { roleLabel: "Designer UX/UI", avatar: "/team/ux.webp" },
      slots: { default: "Ho preparato due alternative." },
    });
    await expectAccessible(wrapper.element);
  });
});
