import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";

import AuthenticationForm from "./AuthenticationForm.vue";

enableAutoUnmount(afterEach);

describe("AuthenticationForm", () => {
  it("explains a short registration password without sending credentials", async () => {
    const wrapper = mount(AuthenticationForm, {
      props: { mode: "register", busy: false, error: null },
      global: { plugins: [createAppI18n()] },
    });
    await wrapper.get('input[name="email"]').setValue("owner@example.com");
    await wrapper.get('input[name="password"]').setValue("short");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toBeUndefined();
    expect(wrapper.get('[role="alert"]').text()).toContain("15 characters");
    await wrapper.get('input[name="password"]').setValue("a valid long passphrase");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toHaveLength(1);
  });
  it("emits accessible login credentials", async () => {
    const wrapper = mount(AuthenticationForm, {
      props: {
        mode: "login",
        busy: false,
        error: null,
      },
      global: {
        plugins: [createAppI18n()],
      },
    });

    await wrapper.get('input[name="email"]').setValue("owner@example.com");
    await wrapper.get('input[name="password"]').setValue("correct horse battery staple");
    await wrapper.get("form").trigger("submit");

    expect(wrapper.emitted("submit")).toEqual([
      [
        {
          email: "owner@example.com",
          password: "correct horse battery staple",
        },
      ],
    ]);
  });

  it("shows a focusable localized error summary", async () => {
    const wrapper = mount(AuthenticationForm, {
      props: {
        mode: "login",
        busy: false,
        error: "invalid_authentication",
      },
      attachTo: document.body,
      global: {
        plugins: [createAppI18n()],
      },
    });

    const alert = wrapper.get('[role="alert"]');

    expect(alert.text()).toBe("The email or password is not valid.");
    expect(alert.attributes("tabindex")).toBe("-1");
  });
});
