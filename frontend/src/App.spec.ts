import { createPinia } from "pinia";
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";

import App from "./App.vue";
import { createAppRouter } from "./router";

enableAutoUnmount(afterEach);

async function mountApplication(initialPath = "/") {
  const router = createAppRouter(createMemoryHistory());

  await router.push(initialPath);
  await router.isReady();

  const wrapper = mount(App, {
    global: {
      plugins: [createPinia(), router],
    },
  });

  return {
    router,
    wrapper,
  };
}

describe("App", () => {
  it("renders a keyboard-accessible application shell", async () => {
    const { wrapper } = await mountApplication();

    expect(wrapper.get(".skip-link").attributes("href")).toBe("#main-content");
    expect(wrapper.get("nav").attributes("aria-label")).toBe("Primary navigation");
    expect(wrapper.get("main").attributes("tabindex")).toBe("-1");
    expect(wrapper.get("h1").text()).toBe("OrchesTwin Studio");
  });

  it("opens and closes the responsive navigation through Pinia state", async () => {
    const { wrapper } = await mountApplication();
    const toggle = wrapper.get('[data-testid="navigation-toggle"]');

    expect(toggle.attributes("aria-expanded")).toBe("false");

    await toggle.trigger("click");

    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(wrapper.get("#primary-navigation").classes()).toContain("primary-navigation--open");

    await wrapper.get('[data-testid="projects-link"]').trigger("click");
    await flushPromises();

    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(wrapper.get("#primary-navigation").classes()).not.toContain("primary-navigation--open");
  });

  it("navigates between foundation routes without reloading the page", async () => {
    const { router, wrapper } = await mountApplication();

    await wrapper.get('[data-testid="projects-link"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("projects");
    expect(wrapper.get("h1").text()).toBe("Projects");
    expect(wrapper.get('[data-testid="projects-link"]').classes()).toContain(
      "primary-navigation__link--active",
    );
  });
});
