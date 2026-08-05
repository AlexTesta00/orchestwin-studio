import {
  enableAutoUnmount,
  mount,
} from "@vue/test-utils";
import {
  afterEach,
  describe,
  expect,
  it,
} from "vitest";

import App from "./App.vue";

enableAutoUnmount(afterEach);

describe("App", () => {
  it("renders the frontend bootstrap inside a labelled main landmark", () => {
    const wrapper = mount(App);
    const mainLandmark = wrapper.get("main");

    expect(mainLandmark.attributes("aria-labelledby")).toBe("app-title");
    expect(wrapper.get("#app-title").text()).toBe("OrchesTwin Studio");
    expect(wrapper.text()).toContain("Frontend workspace operational");
  });
});