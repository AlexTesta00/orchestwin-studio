import { enableAutoUnmount, mount } from "@vue/test-utils";
import { h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import { createAppI18n, type SupportedLocale } from "@/i18n";

import AuthenticationForm from "./AuthenticationForm.vue";
import UiSurface from "./UiSurface.vue";
import { expectAccessible } from "@/test/axe";

enableAutoUnmount(afterEach);

function mountForm(
  mode: "login" | "register",
  error: string | null = null,
  locale: SupportedLocale = "en",
) {
  return mount(AuthenticationForm, {
    props: { mode, busy: false, error },
    global: { plugins: [createAppI18n(locale)] },
  });
}

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
    expect(wrapper.get('[role="alert"]').text()).toContain("8 characters");
    await wrapper.get('input[name="password"]').setValue("Abcdef1!");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toHaveLength(1);
  });

  it.each([
    ["seven characters", "Abcde1!", "The password must have at least 8 characters."],
    [
      "no uppercase letter",
      "abcdefg1!",
      "The password must contain at least one uppercase letter.",
    ],
    [
      "no special character",
      "Abcdefg12",
      "The password must contain at least one special character, for example ! ? # @.",
    ],
    [
      "only a space besides letters",
      "Abcdefg h",
      "The password must contain at least one special character, for example ! ? # @.",
    ],
    ["1025 characters", `A!${"a".repeat(1023)}`, "Use at most 1024 characters for your password."],
  ])(
    "rejects a registration password with %s before sending",
    async (_label, password, message) => {
      const wrapper = mountForm("register");
      await wrapper.get('input[name="email"]').setValue("owner@example.com");
      await wrapper.get('input[name="password"]').setValue(password);
      await wrapper.get("form").trigger("submit");
      expect(wrapper.emitted("submit")).toBeUndefined();
      expect(wrapper.get('[role="alert"]').text()).toBe(message);
      expect(wrapper.get('input[name="password"]').attributes("aria-invalid")).toBe("true");
    },
  );

  it.each(["Abcdef1!", "Élan-vital"])(
    "sends the registration password %s that follows the rule",
    async (password) => {
      const wrapper = mountForm("register");
      await wrapper.get('input[name="email"]').setValue("owner@example.com");
      await wrapper.get('input[name="password"]').setValue(password);
      await wrapper.get("form").trigger("submit");
      expect(wrapper.emitted("submit")).toEqual([[{ email: "owner@example.com", password }]]);
    },
  );

  it("describes the registration rule next to the password", () => {
    const wrapper = mountForm("register");
    const input = wrapper.get('input[name="password"]');
    expect(input.attributes("minlength")).toBe("8");
    expect(input.attributes("maxlength")).toBe("1024");
    expect(wrapper.get("#password-hint").text()).toBe(
      "At least 8 characters, with an uppercase letter and a special character.",
    );
  });

  it("shows the Italian password rule messages", async () => {
    const wrapper = mountForm("register", null, "it");
    expect(wrapper.get("#password-hint").text()).toBe(
      "Almeno 8 caratteri, con una lettera maiuscola e un carattere speciale.",
    );
    await wrapper.get('input[name="password"]').setValue("Abcdefg12");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "La password deve contenere almeno un carattere speciale, per esempio ! ? # @.",
    );
  });

  it("does not apply the registration rule when signing in", async () => {
    const wrapper = mountForm("login");
    await wrapper.get('input[name="email"]').setValue("owner@example.com");
    await wrapper.get('input[name="password"]').setValue("legacy");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("submit")).toEqual([
      [{ email: "owner@example.com", password: "legacy" }],
    ]);
  });

  it.each<[SupportedLocale, string]>([
    ["en", "Too many attempts. Try again in a few minutes."],
    ["it", "Troppi tentativi. Riprova tra qualche minuto."],
  ])("explains too many attempts in %s", (locale, message) => {
    const wrapper = mountForm("login", "too_many_attempts", locale);
    expect(wrapper.get('[role="alert"]').text()).toBe(message);
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

  it("follows the dark surface around it and stays light on its own", async () => {
    const light = mountForm("register", "invalid_registration");
    expect(light.get('input[name="email"]').classes()).toContain("bg-surface");
    expect(light.get('[role="alert"]').classes()).toContain("bg-fail-bg");
    expect(light.get("label").classes()).toContain("text-ink-2");

    const night = mount(UiSurface, {
      props: { tone: "night" },
      slots: {
        default: () =>
          h(AuthenticationForm, { mode: "register", busy: false, error: "invalid_registration" }),
      },
      global: { plugins: [createAppI18n("it")] },
    });
    expect(night.get('input[name="email"]').classes()).toContain("bg-on-night/4");
    expect(night.get('input[name="password"]').classes()).toContain("h-[52px]");
    expect(night.get('[role="alert"]').classes()).toContain("text-fail-on-night");
    expect(night.get("label").classes()).toContain("text-on-night-2");
    expect(night.get("#password-hint").classes()).toContain("text-on-night-3");
    const submit = night.get('button[type="submit"]');
    expect(submit.text()).toBe("Registrati");
    expect(submit.classes()).toContain("bg-on-night");
    expect(submit.classes()).toContain("rounded-pill");
  });

  it("shows that the credentials are on their way", () => {
    const wrapper = mount(AuthenticationForm, {
      props: { mode: "login", busy: true, error: null },
      global: { plugins: [createAppI18n("it")] },
    });
    const submit = wrapper.get('button[type="submit"]');
    expect(submit.text()).toBe("Attendi…");
    expect(submit.attributes("disabled")).toBeDefined();
  });

  it("has no axe violations in registration mode", async () => {
    const wrapper = mount(AuthenticationForm, {
      props: { mode: "register", busy: false, error: null },
      global: { plugins: [createAppI18n()] },
    });
    await expectAccessible(wrapper.element);
  });
});
