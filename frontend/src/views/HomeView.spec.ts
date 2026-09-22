import { createPinia } from "pinia";
import { mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n } from "@/i18n";
import { createAppRouter } from "@/router";
import { useAuthStore } from "@/stores/auth";
import HomeView from "./HomeView.vue";
import { expectAccessible } from "@/test/axe";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function mountHome(authenticated = false) {
  const router = createAppRouter(createMemoryHistory());
  const pinia = createPinia();

  if (authenticated) {
    useAuthStore(pinia).$patch({
      status: "authenticated",
      user: {
        id: "00000000-0000-4000-8000-000000000001",
        email: "owner@example.com",
        is_active: true,
        created_at: "2026-08-10T12:00:00Z",
      },
      accessToken: "access-token",
      expiresAt: "2026-08-10T12:15:00Z",
    });
  }

  await router.push("/");
  await router.isReady();

  return mount(HomeView, {
    global: {
      plugins: [pinia, createAppI18n("it"), router],
    },
  });
}

describe("home page", () => {
  it("presents the eight-step path with a single h1 and animated twins", async () => {
    const wrapper = await mountHome();

    expect(wrapper.findAll("h1")).toHaveLength(1);
    expect(wrapper.get("h1").text()).toBe(
      "Un'idea diventa un'applicazione. Tu decidi a ogni passo.",
    );
    expect(wrapper.findAll("[data-testid='home-step']")).toHaveLength(8);
    expect(wrapper.findAll("[data-testid='home-twin']")).toHaveLength(3);
    expect(wrapper.findAll("video")).toHaveLength(3);
    expect(wrapper.get("[data-testid='home-enter']").attributes("href")).toBe("/register");
  });

  it("sends an authenticated owner to the projects", async () => {
    const wrapper = await mountHome(true);

    expect(wrapper.get("[data-testid='home-enter']").attributes("href")).toBe("/projects");
    expect(wrapper.get("[data-testid='home-enter-closing']").attributes("href")).toBe("/projects");
  });

  it("shows still posters when the visitor prefers reduced motion", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));

    const wrapper = await mountHome();

    expect(wrapper.findAll("video")).toHaveLength(0);
    expect(wrapper.findAll("figure img")).toHaveLength(3);
  });

  it("has no axe violations", { timeout: 30000 }, async () => {
    const wrapper = await mountHome();
    await expectAccessible(wrapper.element);
  });
});
