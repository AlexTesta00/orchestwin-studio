import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import { createAppI18n } from "@/i18n";

import ProjectBriefEditor from "./ProjectBriefEditor.vue";

enableAutoUnmount(afterEach);

describe("ProjectBriefEditor", () => {
  it("emits provided, unknown, and missing-compatible input", async () => {
    const wrapper = mount(ProjectBriefEditor, {
      props: {
        initial: null,
        busy: false,
      },
      global: {
        plugins: [createAppI18n()],
      },
    });

    await wrapper.get("#brief-name").setValue("Project");

    const budgetCheckbox = wrapper
      .get("#brief-budget")
      .element.parentElement?.querySelector<HTMLInputElement>('input[type="checkbox"]');

    budgetCheckbox?.click();

    await wrapper.get("form").trigger("submit");

    const submitted = wrapper.emitted("submit")?.[0]?.[0];

    expect(submitted).toEqual(
      expect.objectContaining({
        name: "Project",
        budget: null,
        unknown_fields: ["budget"],
      }),
    );
  });
});
