import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { AGENT_IDENTIFIERS } from "@/api/team-contracts";
import TwinIdentity from "./TwinIdentity.vue";
import { identityInitials, twinIdentity } from "./twinIdentity";

describe("TwinIdentity", () => {
  it("gives every catalog role a distinct icon and a localized explanation", () => {
    const identities = AGENT_IDENTIFIERS.map((role) => twinIdentity(role, "", "it"));
    expect(new Set(identities.map((identity) => identity.path)).size).toBe(
      AGENT_IDENTIFIERS.length,
    );
    for (const role of AGENT_IDENTIFIERS) {
      const italian = twinIdentity(role, "", "it");
      const english = twinIdentity(role, "", "en");
      expect(italian.name).not.toBe(role);
      expect(italian.description.length).toBeGreaterThan(20);
      expect(english.description).not.toBe(italian.description);
      expect(italian.accent).toBe(english.accent);
      expect(italian.path).toBe(english.path);
    }
  });

  it("keeps a visible name beside decorative icons for screen readers", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "UX_UI_DESIGNER", locale: "it" } });
    expect(wrapper.text()).toContain("Designer UX/UI");
    expect(wrapper.text()).toContain("Disegna schermate semplici");
    expect(wrapper.get("svg").attributes("focusable")).toBe("false");
    expect(wrapper.get("svg").element.parentElement?.getAttribute("aria-hidden")).toBe("true");
  });

  it("keeps the user's identity stable across profile revisions and locales", () => {
    const italian = twinIdentity(undefined, "same-persona-id", "it");
    const english = twinIdentity(undefined, "same-persona-id", "en");
    expect(italian.accent).toBe(english.accent);
    const wrapper = mount(TwinIdentity, {
      props: { identityKey: "same-persona-id", name: "Alex Testa", locale: "it" },
    });
    expect(wrapper.text()).toContain("AT");
    expect(wrapper.text()).toContain("Alex Testa");
    expect(wrapper.text()).toContain("punto di vista");
  });

  it("uses a safe generic identity for an unknown role", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "__proto__", locale: "it" } });
    expect(wrapper.text()).toContain("Specialista");
    expect(wrapper.text()).not.toContain("__proto__");
    expect(wrapper.find("svg").exists()).toBe(true);
  });

  it("does not repeat a profile's name as its description", () => {
    const wrapper = mount(TwinIdentity, {
      props: { name: "Utenti principianti", description: " utenti principianti " },
    });
    expect(wrapper.text().match(/utenti principianti/gi)).toHaveLength(1);
  });

  it("supports compact labels without relying on color alone", () => {
    const wrapper = mount(TwinIdentity, { props: { role: "QA_TEST_ENGINEER", compact: true } });
    expect(wrapper.text()).toBe("Specialista della qualità");
    expect(wrapper.find("svg").exists()).toBe(true);
  });

  it("uses initials for user names without guessing a demographic avatar", () => {
    expect(identityInitials("  Éva  Rossi  ")).toBe("ÉR");
    expect(identityInitials("李")).toBe("李");
    expect(identityInitials("  ")).toBe("");
  });
});
