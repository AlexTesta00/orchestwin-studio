<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import {
  defaultLocale,
  isSupportedLocale,
  saveLocale,
  supportedLocales,
  type SupportedLocale,
} from "@/i18n";

const { locale, t } = useI18n({
  useScope: "global",
});

const selectedLocale = computed<SupportedLocale>({
  get() {
    return isSupportedLocale(locale.value) ? locale.value : defaultLocale;
  },
  set(value) {
    locale.value = value;
    saveLocale(value);
    document.documentElement.lang = value;
  },
});

const localeOptions = computed(() =>
  supportedLocales.map((value) => ({
    label: t(`locale.${value}`),
    value,
  })),
);
</script>

<template>
  <div
    class="inline-flex items-center"
    role="group"
    :aria-label="t('locale.label')"
    data-testid="language-switcher"
  >
    <button
      v-for="option in localeOptions"
      :key="option.value"
      type="button"
      class="group inline-flex min-h-11 min-w-11 items-center justify-center rounded-pill"
      :aria-pressed="option.value === selectedLocale ? 'true' : 'false'"
      :aria-label="option.label"
      :lang="option.value"
      @click="selectedLocale = option.value"
    >
      <span
        :class="[
          'inline-flex min-w-9 items-center justify-center rounded-pill px-2 py-1.5 font-mono text-xs leading-none font-medium tracking-eyebrow uppercase transition-colors duration-150',
          option.value === selectedLocale
            ? 'bg-ink text-white'
            : 'text-ink-2 group-hover:bg-surface-3 group-hover:text-ink',
        ]"
      >
        {{ option.value }}
      </span>
    </button>
  </div>
</template>
