import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { apiClient, ApiError } from "@/api/client";
import type { AuthenticationResponse } from "@/api/contracts";
import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { expectAccessible } from "@/test/axe";
import RegisterView from "./RegisterView.vue";

const AUTHENTICATED: AuthenticationResponse = {
  access_token: "test-token-not-real",
  token_type: "bearer",
  expires_at: "2026-09-28T12:15:00Z",
  user: {
    id: "00000000-0000-4000-8000-000000000001",
    email: "owner@example.com",
    is_active: true,
    created_at: "2026-08-10T12:00:00Z",
    guidance_mode: null,
  },
};

async function mountRegister() {
  const router = createAppRouter(createMemoryHistory());
  await router.push("/register");
  await router.isReady();
  const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
  const wrapper = mount(RegisterView, {
    global: { plugins: [createPinia(), createAppI18n("it"), router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, replace };
}

async function register(wrapper: Awaited<ReturnType<typeof mountRegister>>["wrapper"]) {
  await wrapper.get("#authentication-email").setValue("owner@example.com");
  await wrapper.get("#authentication-password").setValue("Test-password-not-real!");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

describe("registration page", () => {
  it("invites the owner to create an account with the password rule in view", async () => {
    const { wrapper } = await mountRegister();

    expect(wrapper.get('[data-testid="authentication-screen"]').attributes("data-surface")).toBe(
      "night",
    );
    expect(wrapper.findAll("h1")).toHaveLength(1);
    expect(wrapper.get("h1").text()).toBe("Crea il tuo account");
    expect(wrapper.text()).toContain("Uno spazio personale per dare forma alle tue idee.");
    expect(wrapper.get("#password-hint").text()).toBe(
      "Almeno 8 caratteri, con una lettera maiuscola e un carattere speciale.",
    );
    expect(wrapper.get('button[type="submit"]').text()).toBe("Registrati");
    wrapper.unmount();
  });

  it("marks the registration tab as the current page and links the sign in", async () => {
    const { wrapper } = await mountRegister();
    const login = wrapper.get('[data-testid="authentication-tab-login"]');
    const tab = wrapper.get('[data-testid="authentication-tab-register"]');

    expect(tab.attributes("aria-current")).toBe("page");
    expect(login.attributes("href")).toBe("/login");
    expect(login.attributes("aria-current")).toBeUndefined();
    const invitation = wrapper.get("p.text-center");
    expect(invitation.text()).toContain("Hai già un account?");
    expect(invitation.get("a").attributes("href")).toBe("/login");
    wrapper.unmount();
  });

  it("opens the choice of the working mode once the account exists", async () => {
    const create = vi.spyOn(apiClient, "register").mockResolvedValue(AUTHENTICATED);
    const { wrapper, replace } = await mountRegister();

    await register(wrapper);

    expect(create).toHaveBeenCalledWith({
      email: "owner@example.com",
      password: "Test-password-not-real!",
    });
    expect(replace).toHaveBeenCalledOnce();
    expect(replace).toHaveBeenCalledWith({ name: "guidance-choice" });
    wrapper.unmount();
  });

  it("stays on the page and explains a refused registration", async () => {
    vi.spyOn(apiClient, "register").mockRejectedValue(
      new ApiError(409, "email_already_registered"),
    );
    const { wrapper, replace } = await mountRegister();

    await register(wrapper);

    expect(replace).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toBe(
      "Esiste già un account con questo indirizzo email.",
    );
    wrapper.unmount();
  });

  it("has no axe violations", { timeout: 30000 }, async () => {
    const { wrapper } = await mountRegister();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
