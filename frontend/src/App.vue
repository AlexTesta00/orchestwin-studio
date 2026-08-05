<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed } from "vue";

import { useShellStore } from "@/stores/shell";

const shellStore = useShellStore();
const { isNavigationOpen } = storeToRefs(shellStore);

const navigationToggleLabel = computed(() =>
  isNavigationOpen.value ? "Close primary navigation" : "Open primary navigation",
);

const navigationToggleText = computed(() => (isNavigationOpen.value ? "Close" : "Menu"));
</script>

<template>
  <div class="application-shell">
    <a class="skip-link" href="#main-content">Skip to main content</a>

    <header class="site-header">
      <RouterLink class="brand" to="/" aria-label="OrchesTwin Studio home">
        OrchesTwin Studio
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
        aria-label="Primary navigation"
      >
        <RouterLink
          class="primary-navigation__link"
          data-testid="overview-link"
          to="/"
          @click="shellStore.closeNavigation"
        >
          Overview
        </RouterLink>

        <RouterLink
          class="primary-navigation__link"
          data-testid="projects-link"
          to="/projects"
          @click="shellStore.closeNavigation"
        >
          Projects
        </RouterLink>
      </nav>
    </header>

    <main id="main-content" class="main-content" tabindex="-1">
      <RouterView />
    </main>
  </div>
</template>
