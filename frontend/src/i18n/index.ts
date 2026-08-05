import { createI18n } from "vue-i18n";

import enMessages from "./locales/en";
import itMessages from "./locales/it";

export const supportedLocales = ["en", "it"] as const;

export type SupportedLocale = (typeof supportedLocales)[number];

export const defaultLocale: SupportedLocale = "en";

export function isSupportedLocale(value: string): value is SupportedLocale {
  return value === "en" || value === "it";
}

export function createAppI18n(initialLocale: SupportedLocale = defaultLocale) {
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
