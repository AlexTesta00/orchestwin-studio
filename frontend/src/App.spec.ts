import { createPinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App.vue";
import { createAppI18n, type SupportedLocale } from "./i18n";
import { createAppRouter } from "./router";
import { useAuthStore } from "./stores/auth";

enableAutoUnmount(afterEach);

afterEach(() => {
  document.documentElement.lang = "en";
});

async function mountApplication(
  initialPath = "/",
  initialLocale: SupportedLocale = "en",
  authenticated = false,
) {
  const router = createAppRouter(createMemoryHistory());
  const i18n = createAppI18n(initialLocale);
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

  document.documentElement.lang = initialLocale;

  await router.push(initialPath);
  await router.isReady();

  const wrapper = mount(App, {
    global: {
      plugins: [pinia, i18n, router],
    },
  });

  return {
    router,
    wrapper,
  };
}

describe("App", () => {
  it("shows authentication links to anonymous users", async () => {
    const { wrapper } = await mountApplication();

    expect(wrapper.get('[data-testid="login-link"]').text()).toBe("Log in");
    expect(wrapper.get('[data-testid="register-link"]').text()).toBe("Register");
    expect(wrapper.find('[data-testid="projects-link"]').exists()).toBe(false);
  });

  it("shows project navigation to authenticated users", async () => {
    const { wrapper } = await mountApplication("/", "en", true);

    expect(wrapper.get('[data-testid="projects-link"]').text()).toBe("Projects");
    expect(wrapper.get('[data-testid="logout-button"]').text()).toBe("Log out");
    expect(wrapper.find('[data-testid="login-link"]').exists()).toBe(false);
  });

  it("keeps the responsive navigation controlled by Pinia", async () => {
    const { wrapper } = await mountApplication("/", "en", true);
    const toggle = wrapper.get('[data-testid="navigation-toggle"]');
    const navigation = wrapper.get("#primary-navigation");

    expect(toggle.attributes("aria-expanded")).toBe("false");

    await toggle.trigger("click");

    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(navigation.classes()).toContain("flex");

    await wrapper.get('[data-testid="projects-link"]').trigger("click");
    await flushPromises();

    expect(toggle.attributes("aria-expanded")).toBe("false");
  });
});