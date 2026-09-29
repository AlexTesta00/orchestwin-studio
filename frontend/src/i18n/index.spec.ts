import { mount } from "@vue/test-utils";
import { defineComponent, h, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAppI18n, preferredLocale, saveLocale } from "./index";

const Page = defineComponent({ render: () => h("p") });

function browser(languages: readonly string[], language: string): void {
  vi.spyOn(window.navigator, "languages", "get").mockReturnValue(languages);
  vi.spyOn(window.navigator, "language", "get").mockReturnValue(language);
}

function storage(saved: Record<string, string> = {}): Map<string, string> {
  const values = new Map(Object.entries(saved));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  });
  return values;
}

function blockedStorage(): void {
  const blocked = () => {
    throw new DOMException("Storage is disabled", "SecurityError");
  };
  vi.stubGlobal("localStorage", { getItem: blocked, setItem: blocked });
}

afterEach(() => {
  document.documentElement.removeAttribute("lang");
});

describe("the language of the interface", () => {
  it("keeps the language the person chose over the language of the browser", () => {
    const values = storage();
    browser(["it-IT", "it"], "it-IT");
    saveLocale("en");
    expect(values.get("orchestwin.locale")).toBe("en");
    expect(preferredLocale()).toBe("en");

    browser(["de-DE", "de"], "de-DE");
    saveLocale("it");
    expect(preferredLocale()).toBe("it");
    expect(createAppI18n().global.locale.value).toBe("it");
  });

  it("starts in Italian in a browser whose first supported language is Italian", () => {
    storage();
    browser(["it-IT", "en-US"], "it-IT");
    expect(preferredLocale()).toBe("it");
    expect(createAppI18n().global.locale.value).toBe("it");

    browser(["fr-FR", "it", "en"], "fr-FR");
    expect(preferredLocale()).toBe("it");
  });

  it("uses the language of the browser when no list of languages is given", () => {
    storage();
    browser([], "it-CH");
    expect(preferredLocale()).toBe("it");
  });

  it("ignores a saved value that the Studio does not support", () => {
    storage({ "orchestwin.locale": "fr" });
    browser(["it-IT"], "it-IT");
    expect(preferredLocale()).toBe("it");
  });

  it("starts in English in a German browser", () => {
    storage();
    browser(["de-DE", "de"], "de-DE");
    expect(preferredLocale()).toBe("en");
    expect(createAppI18n().global.locale.value).toBe("en");
  });

  it("starts in English when the browser gives no language", () => {
    storage();
    browser([], "");
    expect(preferredLocale()).toBe("en");
    expect(createAppI18n().global.locale.value).toBe("en");
  });

  it("follows the browser and keeps working when the storage throws", () => {
    blockedStorage();
    browser(["it-IT"], "it-IT");
    expect(preferredLocale()).toBe("it");
    expect(() => saveLocale("en")).not.toThrow();
    expect(preferredLocale()).toBe("it");

    browser([], "");
    expect(preferredLocale()).toBe("en");
  });

  it("gives the document the language in use and follows every change", async () => {
    const i18n = createAppI18n("it");
    const wrapper = mount(Page, { global: { plugins: [i18n] } });
    expect(document.documentElement.lang).toBe("it");

    i18n.global.locale.value = "en";
    await nextTick();
    expect(document.documentElement.lang).toBe("en");

    wrapper.unmount();
    i18n.global.locale.value = "it";
    await nextTick();
    expect(document.documentElement.lang).toBe("en");
  });
});

describe("the sentences that count", () => {
  it.each([
    ["it", 1, "1 informazione essenziale ancora da chiedere"],
    ["it", 3, "3 informazioni essenziali ancora da chiedere"],
    ["en", 1, "1 essential detail still to ask"],
    ["en", 3, "3 essential details still to ask"],
  ] as const)("counts the essentials still to ask in %s with %i", (locale, count, sentence) => {
    expect(createAppI18n(locale).global.t("briefDialogue.essentialsLeft", { count }, count)).toBe(
      sentence,
    );
  });

  it.each([
    ["it", 1, "1 informazione da chiarire: puoi completarla nei prossimi passaggi."],
    ["it", 3, "3 informazioni da chiarire: puoi completarle nei prossimi passaggi."],
    ["en", 1, "1 detail to clarify: you can complete it in the next steps."],
    ["en", 3, "3 details to clarify: you can complete them in the next steps."],
  ] as const)("counts the details to clarify in %s with %i", (locale, count, sentence) => {
    expect(createAppI18n(locale).global.t("brief.missingSummary", { count })).toBe(sentence);
  });
});

describe("the sentences that name a twin", () => {
  it("titles the conversation with the name and asks without the name or a gendered pronoun", () => {
    const italian = createAppI18n("it").global;
    const english = createAppI18n("en").global;
    const name = "Twin del volontario della mensa solidale";

    expect(italian.t("twinChat.title", { name })).toBe(
      "Conversazione con Twin del volontario della mensa solidale",
    );
    expect(english.t("twinChat.title", { name })).toBe(
      "Conversation with Twin del volontario della mensa solidale",
    );
    expect(italian.t("twinChat.empty", { name })).toBe(
      "Nessuna domanda ancora. Chiedi come lavora, che cosa rende difficile il suo lavoro o che cosa si aspetta dall'applicazione.",
    );
    expect(english.t("twinChat.empty", { name })).toBe(
      "No questions yet. Ask how they work, what makes their work hard or what they expect from the application.",
    );
    expect(italian.t("twinChat.thinking", { name })).toBe("Il twin sta rispondendo…");
    expect(english.t("twinChat.thinking", { name })).toBe("The twin is answering…");
    expect(italian.t("twinChat.questionLabel", { name })).toBe("La tua domanda per il twin");
    expect(english.t("twinChat.questionLabel", { name })).toBe("Your question for the twin");
  });
});
