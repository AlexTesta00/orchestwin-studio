import { createPinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App.vue";
import { createAppI18n, type SupportedLocale } from "./i18n";
import { createAppRouter } from "./router";
import { useAuthStore } from "./stores/auth";
import { expectAccessible } from "@/test/axe";

enableAutoUnmount(afterEach);

afterEach(() => {
  document.documentElement.lang = "en";
});

async function mountApplication(
  initialPath = "/",
  initialLocale: SupportedLocale = "en",
  authenticated = false,
  email = "owner@example.com",
  stubPages = false,
) {
  const router = createAppRouter(createMemoryHistory());
  const i18n = createAppI18n(initialLocale);
  const pinia = createPinia();

  if (authenticated) {
    useAuthStore(pinia).$patch({
      status: "authenticated",
      user: {
        id: "00000000-0000-4000-8000-000000000001",
        email,
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
      stubs: stubPages ? { RouterView: true } : {},
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

  it("shows the logo with its wordmark and the language switcher inside the navigation", async () => {
    const { wrapper } = await mountApplication("/", "it");
    const home = wrapper.get('[data-testid="home-link"]');
    expect(home.attributes("aria-label")).toBe("Pagina iniziale di OrchesTwin Studio");
    expect(home.find('[data-testid="brand-mark"]').exists()).toBe(true);
    expect(home.get('[data-testid="brand-wordmark"]').text()).toContain("OrchesTwin");
    expect(
      wrapper.get("#primary-navigation").find('[data-testid="language-switcher"]').exists(),
    ).toBe(true);
    expect(wrapper.find('[data-testid="user-initials"]').exists()).toBe(false);
  });

  it("shows the initials of the signed in owner and says who is signed in", async () => {
    const { wrapper } = await mountApplication("/", "it", true, "maria.bianchi@example.com");
    const account = wrapper.get('[data-testid="user-initials"]');
    expect(account.get('[aria-hidden="true"]').text()).toBe("MB");
    expect(account.get(".sr-only").text()).toBe(
      "Hai effettuato l'accesso come maria.bianchi@example.com",
    );
    expect(account.attributes("title")).toBe("maria.bianchi@example.com");
    const single = await mountApplication("/", "en", true, "owner@example.com");
    expect(single.wrapper.get('[data-testid="user-initials"] [aria-hidden="true"]').text()).toBe(
      "O",
    );
  });

  it(
    "highlights the page where the owner is, also inside a project",
    { timeout: 30000 },
    async () => {
      const { wrapper, router } = await mountApplication("/", "en", true, undefined, true);
      expect(wrapper.get('[data-testid="overview-link"]').attributes("aria-current")).toBe("page");
      expect(wrapper.get('[data-testid="overview-link"]').classes()).toContain("bg-surface-3");
      expect(wrapper.get('[data-testid="projects-link"]').classes()).not.toContain("bg-surface-3");
      await router.push("/projects/00000000-0000-4000-8000-000000000002");
      await flushPromises();
      const projects = wrapper.get('[data-testid="projects-link"]');
      expect(projects.classes()).toContain("bg-surface-3");
      expect(projects.attributes("aria-current")).toBeUndefined();
      expect(wrapper.get('[data-testid="overview-link"]').classes()).not.toContain("bg-surface-3");
    },
  );

  it(
    "has no axe violations in the shell for an authenticated owner",
    { timeout: 30000 },
    async () => {
      const { wrapper } = await mountApplication("/", "it", true);
      await flushPromises();
      await expectAccessible(wrapper.element, { page: true });
    },
  );
});
