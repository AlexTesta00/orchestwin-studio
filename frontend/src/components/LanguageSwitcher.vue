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
    class="inline-flex items-center rounded-pill border border-line-strong bg-surface p-0.5"
    role="group"
    :aria-label="t('locale.label')"
    data-testid="language-switcher"
  >
    <button
      v-for="option in localeOptions"
      :key="option.value"
      type="button"
      :class="[
        'min-w-11 rounded-pill px-3 py-1.5 font-mono text-xs font-medium uppercase transition-colors',
        option.value === selectedLocale ? 'bg-ink text-white' : 'text-ink-2 hover:bg-surface-3',
      ]"
      :aria-pressed="option.value === selectedLocale ? 'true' : 'false'"
      :aria-label="option.label"
      :lang="option.value"
      @click="selectedLocale = option.value"
    >
      {{ option.value }}
    </button>
  </div>
</template>
