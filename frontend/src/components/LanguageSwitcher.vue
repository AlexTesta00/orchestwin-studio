<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import {
  defaultLocale,
  isSupportedLocale,
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
    class="col-span-full flex items-center gap-2 md:col-span-1 md:justify-self-end"
  >
    <label
      class="text-sm font-semibold text-slate-700"
      for="language-selector"
      hidden
    >
      {{ t("locale.label") }}
    </label>

    <select
      id="language-selector"
      v-model="selectedLocale"
      class="min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 pr-9 text-sm font-semibold text-slate-800 shadow-sm transition-colors hover:border-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2"
      data-testid="language-selector"
    >
      <option
        v-for="option in localeOptions"
        :key="option.value"
        :value="option.value"
      >
        {{ option.label }}
      </option>
    </select>
  </div>
</template>