import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { expectAccessible } from "@/test/axe";
import ArchetypeEditor from "./ArchetypeEditor.vue";

describe("ArchetypeEditor", () => {
  it("requires the description and role and saves normalized owner input", async () => {
    const wrapper = mount(ArchetypeEditor);
    expect(wrapper.get('[data-testid="archetype-save"]').attributes("disabled")).toBeDefined();
    await wrapper.get('[data-testid="archetype-name"]').setValue(" Receptionist ");
    await wrapper.get('[data-testid="archetype-description"]').setValue(" Works at reception ");
    await wrapper.get('[data-testid="archetype-role"]').setValue(" Receptionist ");
    await wrapper
      .get('[data-testid="archetype-goals"]')
      .setValue(" Fast check-in \n\n Fewer errors ");
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("save")).toEqual([
      [
        {
          name: "Receptionist",
          description: "Works at reception",
          role: "Receptionist",
          goals: ["Fast check-in", "Fewer errors"],
          context: null,
        },
      ],
    ]);
    await expectAccessible(wrapper.element);
  });
  it("keeps historical unknown fields empty until an explicit save and speaks Italian", async () => {
    const wrapper = mount(ArchetypeEditor, {
      props: {
        locale: "it",
        archetype: {
          persona_id: "persona",
          version_id: "version",
          version_number: 4,
          name: "Receptionist",
          description: null,
          role: null,
          goals: [],
          context: null,
          source: "SYSTEM_PROPOSED",
          confirmation_status: "CONFIRMED",
          archived: false,
        },
      },
    });
    expect(
      (wrapper.get('[data-testid="archetype-description"]').element as HTMLTextAreaElement).value,
    ).toBe("");
    expect(wrapper.emitted("save")).toBeUndefined();
    expect(wrapper.text()).toContain(
      "Il brief e le scelte del proprietario non sono evidenze su utenti reali.",
    );
    await wrapper.setProps({ busy: true });
    await wrapper.get("form").trigger("submit");
    expect(wrapper.emitted("save")).toBeUndefined();
  });
});
