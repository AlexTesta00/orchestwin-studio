import { watch } from "vue";
import { createI18n } from "vue-i18n";

import enMessages from "./locales/en";
import itMessages from "./locales/it";

export const supportedLocales = ["en", "it"] as const;

export type SupportedLocale = (typeof supportedLocales)[number];

export const defaultLocale: SupportedLocale = "en";

const storageKey = "orchestwin.locale";

export function isSupportedLocale(value: string): value is SupportedLocale {
  return value === "en" || value === "it";
}

function savedLocale(): SupportedLocale | null {
  try {
    const saved = localStorage.getItem(storageKey);
    return saved !== null && isSupportedLocale(saved) ? saved : null;
  } catch {
    return null;
  }
}

function browserLocale(): SupportedLocale | null {
  if (typeof navigator === "undefined") return null;
  const languages: readonly (string | undefined)[] = [
    ...(navigator.languages ?? []),
    navigator.language,
  ];
  for (const language of languages) {
    const code = (language ?? "").slice(0, 2).toLowerCase();
    if (isSupportedLocale(code)) return code;
  }
  return null;
}

export function preferredLocale(): SupportedLocale {
  return savedLocale() ?? browserLocale() ?? defaultLocale;
}

export function saveLocale(value: SupportedLocale): void {
  try {
    localStorage.setItem(storageKey, value);
  } catch {
    // Language selection remains usable when browser storage is unavailable.
  }
}

export function createAppI18n(initialLocale: SupportedLocale = preferredLocale()) {
  const i18n = createI18n({
    legacy: false,
    locale: initialLocale,
    fallbackLocale: defaultLocale,
    messages: {
      en: enMessages,
      it: itMessages,
    },
  });
  const install = i18n.install.bind(i18n);
  i18n.install = (app, ...options) => {
    install(app, ...options);
    app.onUnmount(
      watch(
        i18n.global.locale,
        (locale) => {
          document.documentElement.lang = locale;
        },
        { immediate: true },
      ),
    );
  };
  return i18n;
}
