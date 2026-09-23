import { createI18n } from "vue-i18n";

import enMessages from "./locales/en";
import itMessages from "./locales/it";

export const supportedLocales = ["en", "it"] as const;

export type SupportedLocale = (typeof supportedLocales)[number];

export const defaultLocale: SupportedLocale = "en";

export function isSupportedLocale(value: string): value is SupportedLocale {
  return value === "en" || value === "it";
}

function savedLocale(): SupportedLocale {
  try {
    const saved = localStorage.getItem("orchestwin.locale");
    return saved && isSupportedLocale(saved) ? saved : defaultLocale;
  } catch {
    return defaultLocale;
  }
}

export function saveLocale(value: SupportedLocale): void {
  try {
    localStorage.setItem("orchestwin.locale", value);
  } catch {
    // Language selection remains usable when browser storage is unavailable.
  }
}

export function createAppI18n(initialLocale: SupportedLocale = savedLocale()) {
  return createI18n({
    legacy: false,
    locale: initialLocale,
    fallbackLocale: defaultLocale,
    messages: {
      en: enMessages,
      it: itMessages,
    },
  });
}
