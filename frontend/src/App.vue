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
</script>

<template>
  <div class="application-shell">
    <a class="skip-link" href="#main-content">
      {{ t("navigation.skip") }}
    </a>

    <header class="site-header">
      <RouterLink class="brand" to="/" :aria-label="t('app.homeAriaLabel')">
        {{ t("app.title") }}
      </RouterLink>

      <button
        class="navigation-toggle"
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
          'primary-navigation',
          {
            'primary-navigation--open': isNavigationOpen,
          },
        ]"
        :aria-label="t('navigation.label')"
      >
        <RouterLink
          class="primary-navigation__link"
          data-testid="overview-link"
          to="/"
          @click="shellStore.closeNavigation"
        >
          {{ t("navigation.overview") }}
        </RouterLink>

        <RouterLink
          class="primary-navigation__link"
          data-testid="projects-link"
          to="/projects"
          @click="shellStore.closeNavigation"
        >
          {{ t("navigation.projects") }}
        </RouterLink>
      </nav>

      <LanguageSwitcher />
    </header>

    <main id="main-content" class="main-content" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
