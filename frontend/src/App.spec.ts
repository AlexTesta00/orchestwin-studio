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
      plugins: [router],
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
