import { createPinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { describe, expect, it, vi } from "vitest";

import { apiClient, ApiError } from "@/api/client";
import type { AuthenticationResponse } from "@/api/contracts";
import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { expectAccessible } from "@/test/axe";
import LoginView from "./LoginView.vue";

const AUTHENTICATED: AuthenticationResponse = {
  access_token: "test-token-not-real",
  token_type: "bearer",
  expires_at: "2026-09-28T12:15:00Z",
  user: {
    id: "00000000-0000-4000-8000-000000000001",
    email: "owner@example.com",
    is_active: true,
    created_at: "2026-08-10T12:00:00Z",
  },
};

async function mountLogin(path = "/login", locale: "it" | "en" = "it") {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
  const wrapper = mount(LoginView, {
    global: { plugins: [createPinia(), createAppI18n(locale), router] },
    attachTo: document.body,
  });
  await flushPromises();
  return { wrapper, replace };
}

async function signIn(wrapper: Awaited<ReturnType<typeof mountLogin>>["wrapper"]) {
  await wrapper.get("#authentication-email").setValue("owner@example.com");
  await wrapper.get("#authentication-password").setValue("test-password-not-real");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

describe("sign in page", () => {
  it("welcomes the owner back on a dark surface with the three promises", async () => {
    const { wrapper } = await mountLogin();
    const screen = wrapper.get('[data-testid="authentication-screen"]');

    expect(screen.attributes("data-surface")).toBe("night");
    expect(wrapper.findAll("h1")).toHaveLength(1);
    expect(wrapper.get("h1").text()).toBe("Bentornato");
    expect(wrapper.text()).toContain("Continua verso i tuoi progetti OrchesTwin Studio.");
    expect(wrapper.findAll("li")).toHaveLength(3);
    expect(wrapper.get('[data-testid="authentication-image"]').attributes("alt")).toBe(
      "Un twin, robot da compagnia bianco con il viso a schermo, in uno studio scuro",
    );
    expect(wrapper.get('button[type="submit"]').text()).toBe("Accedi");
    wrapper.unmount();
  });

  it("brings the picture in after the first frame", async () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frames.push(callback);
      return frames.length;
    });
    const { wrapper } = await mountLogin();
    const image = wrapper.get('[data-testid="authentication-image"]');

    expect(image.classes()).toContain("motion-safe:opacity-0");
    expect(image.classes()).toContain("motion-safe:scale-110");
    for (const callback of frames.splice(0)) callback(0);
    await flushPromises();
    expect(image.classes()).toContain("opacity-100");
    expect(image.classes()).not.toContain("motion-safe:opacity-0");
    wrapper.unmount();
  });

  it("marks the sign in tab as the current page and links the registration", async () => {
    const { wrapper } = await mountLogin();
    const login = wrapper.get('[data-testid="authentication-tab-login"]');
    const register = wrapper.get('[data-testid="authentication-tab-register"]');

    expect(wrapper.get("nav").attributes("aria-label")).toBe("Accedi o registrati");
    expect(login.text()).toBe("Accedi");
    expect(login.attributes("aria-current")).toBe("page");
    expect(register.text()).toBe("Registrati");
    expect(register.attributes("href")).toBe("/register");
    expect(register.attributes("aria-current")).toBeUndefined();
    const invitation = wrapper.get("p.text-center");
    expect(invitation.text()).toContain("Non hai ancora un account?");
    expect(invitation.get("a").attributes("href")).toBe("/register");
    wrapper.unmount();
  });

  it("opens the projects after signing in", async () => {
    const login = vi.spyOn(apiClient, "login").mockResolvedValue(AUTHENTICATED);
    const { wrapper, replace } = await mountLogin();

    await signIn(wrapper);

    expect(login).toHaveBeenCalledWith({
      email: "owner@example.com",
      password: "test-password-not-real",
    });
    expect(replace).toHaveBeenCalledWith("/projects");
    wrapper.unmount();
  });

  it.each([
    [
      "/login?redirect=/projects/00000000-0000-4000-8000-000000000002",
      "/projects/00000000-0000-4000-8000-000000000002",
    ],
    ["/login?redirect=//example.com", "/projects"],
    ["/login?redirect=https://example.com", "/projects"],
  ])("returns from %s to %s", async (path, target) => {
    vi.spyOn(apiClient, "login").mockResolvedValue(AUTHENTICATED);
    const { wrapper, replace } = await mountLogin(path);

    await signIn(wrapper);

    expect(replace).toHaveBeenCalledWith(target);
    wrapper.unmount();
  });

  it("stays on the page and explains a refused sign in", async () => {
    vi.spyOn(apiClient, "login").mockRejectedValue(new ApiError(401, "invalid_authentication"));
    const { wrapper, replace } = await mountLogin();

    await signIn(wrapper);

    expect(replace).not.toHaveBeenCalled();
    expect(wrapper.get('[role="alert"]').text()).toBe("L'email o la password non sono valide.");
    wrapper.unmount();
  });

  it("speaks English when the owner chose it", async () => {
    const { wrapper } = await mountLogin("/login", "en");
    expect(wrapper.get("h1").text()).toBe("Welcome back");
    expect(wrapper.get('[data-testid="authentication-tab-login"]').text()).toBe("Log in");
    expect(wrapper.text()).toContain("You decide at every step");
    wrapper.unmount();
  });

  it("has no axe violations", { timeout: 30000 }, async () => {
    const { wrapper } = await mountLogin();
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
