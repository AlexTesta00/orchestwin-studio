<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import LanguageSwitcher from "@/components/LanguageSwitcher.vue";
import { useShellStore } from "@/stores/shell";

const shellStore = useShellStore();
const { isNavigationOpen } = storeToRefs(shellStore);
const { t } = useI18n({
  useScope: "global",
});

const navigationToggleLabel = computed(() =>
  isNavigationOpen.value ? t("navigation.closeLabel") : t("navigation.openLabel"),
);

const navigationToggleText = computed(() =>
  isNavigationOpen.value ? t("navigation.close") : t("navigation.menu"),
);

function navigationLinkClasses(isExactActive: boolean): string[] {
  return [
    "block rounded-lg px-3 py-2 text-sm font-semibold transition-colors duration-150",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900",
    "focus-visible:ring-offset-2 focus-visible:ring-offset-white",
    isExactActive
      ? "bg-slate-900 text-white shadow-sm"
      : "text-slate-700 hover:bg-slate-100 hover:text-slate-950",
  ];
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-950">
    <a
      class="fixed top-4 left-4 z-50 -translate-y-32 rounded-lg bg-slate-950 px-4 py-3 font-semibold text-white shadow-lg transition-transform focus:translate-y-0 focus:ring-2 focus:ring-slate-950 focus:ring-offset-2 focus:outline-none"
      data-testid="skip-link"
      href="#main-content"
    >
      {{ t("navigation.skip") }}
    </a>

    <header class="border-b border-slate-200 bg-white/95 shadow-sm backdrop-blur">
      <div
        class="mx-auto grid max-w-7xl grid-cols-[1fr_auto] items-center gap-4 px-4 py-3 sm:px-6 md:grid-cols-[auto_1fr_auto] lg:px-8"
      >
        <RouterLink
          class="rounded-md text-lg font-black tracking-tight text-slate-950 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2 focus-visible:outline-none"
          to="/"
          :aria-label="t('app.homeAriaLabel')"
        >
          {{ t("app.title") }}
        </RouterLink>

        <button
          class="inline-flex min-h-11 items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-800 shadow-sm transition-colors hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2 focus-visible:outline-none md:hidden"
          type="button"
          aria-controls="primary-navigation"
          :aria-expanded="isNavigationOpen"
          :aria-label="navigationToggleLabel"
          data-testid="navigation-toggle"
          @click="shellStore.toggleNavigation"
        >
          {{ navigationToggleText }}
        </button>

        <nav
          id="primary-navigation"
          :class="[
            'col-span-full w-full flex-col gap-2 md:col-span-1 md:w-auto md:flex-row md:items-center md:justify-self-end',
            isNavigationOpen ? 'flex' : 'hidden md:flex',
          ]"
          :aria-label="t('navigation.label')"
          @click="shellStore.closeNavigation"
        >
          <RouterLink v-slot="{ href, navigate, isExactActive }" custom to="/">
            <a
              :href="href"
              :class="navigationLinkClasses(isExactActive)"
              :aria-current="isExactActive ? 'page' : undefined"
              data-testid="overview-link"
              @click="navigate"
            >
              {{ t("navigation.overview") }}
            </a>
          </RouterLink>

          <RouterLink v-slot="{ href, navigate, isExactActive }" custom to="/projects">
            <a
              :href="href"
              :class="navigationLinkClasses(isExactActive)"
              :aria-current="isExactActive ? 'page' : undefined"
              data-testid="projects-link"
              @click="navigate"
            >
              {{ t("navigation.projects") }}
            </a>
          </RouterLink>
        </nav>

        <LanguageSwitcher />
      </div>
    </header>

    <main
      id="main-content"
      class="mx-auto min-h-[calc(100vh-4.5rem)] w-full max-w-7xl px-4 py-10 focus:outline-none sm:px-6 sm:py-14 lg:px-8 lg:py-20"
      tabindex="-1"
    >
      <RouterView />
    </main>
  </div>
</template>
