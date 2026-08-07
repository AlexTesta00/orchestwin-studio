import { createPinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App.vue";
import { createAppI18n, type SupportedLocale } from "./i18n";
import { createAppRouter } from "./router";

enableAutoUnmount(afterEach);

afterEach(() => {
  document.documentElement.lang = "en";
});

async function mountApplication(
  initialPath = "/",
  initialLocale: SupportedLocale = "en",
) {
  const router = createAppRouter(createMemoryHistory());
  const i18n = createAppI18n(initialLocale);

  document.documentElement.lang = initialLocale;

  await router.push(initialPath);
  await router.isReady();

  const wrapper = mount(App, {
    global: {
      plugins: [createPinia(), i18n, router],
    },
  });

  return {
    router,
    wrapper,
  };
}

describe("App", () => {
  it("renders a localized keyboard-accessible application shell", async () => {
    const { wrapper } = await mountApplication();

    expect(wrapper.get('[data-testid="skip-link"]').attributes("href")).toBe(
      "#main-content",
    );
    expect(wrapper.get('[data-testid="skip-link"]').text()).toBe("Skip to main content");
    expect(wrapper.get("nav").attributes("aria-label")).toBe("Primary navigation");
    expect(wrapper.get("main").attributes("tabindex")).toBe("-1");
    expect(wrapper.get("h1").text()).toBe("OrchesTwin Studio");
    expect(document.documentElement.lang).toBe("en");
  });

  it("opens and closes the responsive navigation through Pinia state", async () => {
    const { wrapper } = await mountApplication();
    const toggle = wrapper.get('[data-testid="navigation-toggle"]');
    const navigation = wrapper.get("#primary-navigation");

    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(navigation.classes()).toContain("hidden");

    await toggle.trigger("click");

    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(navigation.classes()).toContain("flex");
    expect(navigation.classes()).not.toContain("hidden");

    await wrapper.get('[data-testid="projects-link"]').trigger("click");
    await flushPromises();

    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(navigation.classes()).toContain("hidden");
    expect(navigation.classes()).not.toContain("flex");
  });

  it("navigates between localized foundation routes", async () => {
    const { router, wrapper } = await mountApplication();

    expect(wrapper.get('[data-testid="overview-link"]').attributes("aria-current")).toBe(
      "page",
    );

    await wrapper.get('[data-testid="projects-link"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("projects");
    expect(wrapper.get("h1").text()).toBe("Projects");
    expect(wrapper.get('[data-testid="projects-link"]').attributes("aria-current")).toBe(
      "page",
    );
  });

  it("switches the shell and active view to Italian without reloading", async () => {
    const { wrapper } = await mountApplication();

    await wrapper.get('[data-testid="language-selector"]').setValue("it");
    await flushPromises();

    expect(wrapper.get('[data-testid="overview-link"]').text()).toBe("Panoramica");
    expect(wrapper.get('[data-testid="projects-link"]').text()).toBe("Progetti");
    expect(wrapper.text()).toContain("Workspace frontend operativo");
    expect(document.documentElement.lang).toBe("it");
  });
});