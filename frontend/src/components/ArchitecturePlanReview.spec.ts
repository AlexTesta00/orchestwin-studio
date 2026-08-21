import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { ARCHITECTURE_PACKAGE } from "../test/architectureFixtures";
import ArchitecturePlanReview from "./ArchitecturePlanReview.vue";

describe("ArchitecturePlanReview", () => {
  it("renders exact grounding, architecture components, and traceable tests", () => {
    const wrapper = mount(ArchitecturePlanReview, {
      props: {
        packageValue: ARCHITECTURE_PACKAGE,
      },
    });

    expect(wrapper.text()).toContain("Reservation platform architecture");
    expect(wrapper.text()).toContain("Reservation interface");
    expect(wrapper.text()).toContain("Create a reservation end to end");
    expect(wrapper.text()).toContain(
      ARCHITECTURE_PACKAGE.grounding.design_package_reference.content_hash,
    );
    expect(wrapper.text()).toContain("not empirical user validation");
  });

  it("renders the Italian methodological boundary", () => {
    const wrapper = mount(ArchitecturePlanReview, {
      props: {
        packageValue: ARCHITECTURE_PACKAGE,
        locale: "it",
      },
    });

    expect(wrapper.text()).toContain("Piano di test");
    expect(wrapper.text()).toContain("non è validazione empirica degli utenti");
  });
});
