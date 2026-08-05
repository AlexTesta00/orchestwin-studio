<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { defaultLocale, isSupportedLocale, supportedLocales, type SupportedLocale } from "@/i18n";

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
  <div class="language-switcher">
    <label class="language-switcher__label" for="language-selector" hidden>
      {{ t("locale.label") }}
    </label>

    <select
      id="language-selector"
      v-model="selectedLocale"
      class="language-switcher__select"
      data-testid="language-selector"
    >
      <option v-for="option in localeOptions" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
  </div>
</template>
