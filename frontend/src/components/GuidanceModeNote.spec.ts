import { createPinia } from "pinia";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { GuidanceMode } from "@/api/contracts";
import { createAppI18n } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { expectAccessible } from "@/test/axe";
import GuidanceModeNote from "./GuidanceModeNote.vue";

const HINT = {
  it: "Scelta una volta sola per questo account: non si può cambiare.",
  en: "Chosen once for this account: it cannot be changed.",
} as const;

function mountNote(locale: "it" | "en", mode: GuidanceMode) {
  const pinia = createPinia();
  useAuthStore(pinia).user = {
    id: "00000000-0000-4000-8000-000000000001",
    email: "owner@example.com",
    is_active: true,
    created_at: "2026-10-05T08:00:00Z",
    guidance_mode: mode,
  };
  return mount(GuidanceModeNote, {
    global: { plugins: [pinia, createAppI18n(locale)] },
    attachTo: document.body,
  });
}

describe("guidance mode note", () => {
  it.each([
    ["it", "GUIDED", "Modalità guidata"],
    ["it", "EXPERT", "Modalità esperta"],
    ["en", "GUIDED", "Guided mode"],
    ["en", "EXPERT", "Expert mode"],
  ] as const)("says in %s that the %s mode was chosen once", (locale, mode, value) => {
    const wrapper = mountNote(locale, mode);
    const note = wrapper.get('[data-testid="guidance-mode"]');
    const lines = note.findAll("p").map((line) => line.text());

    expect(note.attributes("data-mode")).toBe(mode);
    expect(lines).toEqual([value, HINT[locale]]);
    expect(note.findAll("button, input, select, textarea, a, [tabindex], [role]").length).toBe(0);
    wrapper.unmount();
  });

  it("has no axe violations", async () => {
    const wrapper = mountNote("it", "EXPERT");
    await expectAccessible(wrapper.element);
    wrapper.unmount();
  });
});
