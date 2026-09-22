<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import LanguageSwitcher from "@/components/LanguageSwitcher.vue";
import UiBrandMark from "@/components/UiBrandMark.vue";
import { useAuthStore } from "@/stores/auth";
import { useShellStore } from "@/stores/shell";

const router = useRouter();
const shellStore = useShellStore();
const authStore = useAuthStore();

const { isNavigationOpen } = storeToRefs(shellStore);
const { isAuthenticated, status: authenticationStatus, user } = storeToRefs(authStore);

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
    "block rounded-control px-3 py-2 text-sm font-semibold transition-colors duration-150",
    isExactActive ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
  ];
}

async function logout(): Promise<void> {
  await authStore.logout(apiClient);
  shellStore.closeNavigation();
  await router.push({
    name: "overview",
  });
}
</script>

<template>
  <div class="min-h-screen bg-page text-ink">
    <a
      class="fixed top-4 left-4 z-50 -translate-y-32 rounded-control bg-ink px-4 py-3 font-semibold text-white shadow-decision transition-transform focus:translate-y-0"
      data-testid="skip-link"
      href="#main-content"
    >
      {{ t("navigation.skip") }}
    </a>

    <header
      class="sticky top-0 z-40 border-b border-topbar-line bg-surface/78 backdrop-blur-xl backdrop-saturate-150"
    >
      <div
        class="mx-auto grid max-w-[1180px] grid-cols-[1fr_auto] items-center gap-4 px-4 py-3 sm:px-6 md:grid-cols-[auto_1fr_auto]"
      >
        <RouterLink
          class="inline-flex items-center gap-2.5 rounded-control text-[15px] font-semibold tracking-block"
          to="/"
          :aria-label="t('app.homeAriaLabel')"
        >
          <UiBrandMark :size="26" />
          <span>{{ t("app.title") }}</span>
        </RouterLink>

        <button
          class="inline-flex min-h-11 items-center justify-center rounded-control border border-button-line bg-surface px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-3 md:hidden"
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
            'col-span-full w-full flex-col gap-1 md:col-span-1 md:w-auto md:flex-row md:items-center md:justify-self-end',
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

          <RouterLink
            v-if="isAuthenticated"
            v-slot="{ href, navigate, isExactActive }"
            custom
            to="/projects"
          >
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

          <RouterLink
            v-if="!isAuthenticated"
            :class="navigationLinkClasses(false)"
            to="/login"
            data-testid="login-link"
          >
            {{ t("navigation.login") }}
          </RouterLink>

          <RouterLink
            v-if="!isAuthenticated"
            :class="navigationLinkClasses(false)"
            to="/register"
            data-testid="register-link"
          >
            {{ t("navigation.register") }}
          </RouterLink>

          <button
            v-if="isAuthenticated"
            class="rounded-control px-3 py-2 text-left text-sm font-semibold text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            type="button"
            :disabled="authenticationStatus === 'loading'"
            data-testid="logout-button"
            @click="logout"
          >
            {{ t("navigation.logout") }}
          </button>
        </nav>

        <div
          class="col-span-full flex items-center justify-between gap-4 md:col-span-1 md:justify-end"
        >
          <span v-if="user" class="hidden font-mono text-xs text-ink-3 lg:inline">
            {{ user.email }}
          </span>

          <LanguageSwitcher />
        </div>
      </div>
    </header>

    <main
      id="main-content"
      class="mx-auto min-h-[calc(100vh-4.5rem)] w-full max-w-[1180px] px-4 py-8 focus:outline-none sm:px-6 sm:py-10"
      tabindex="-1"
    >
      <RouterView />
    </main>
  </div>
</template>
