<script setup lang="ts">
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import LanguageSwitcher from "@/components/LanguageSwitcher.vue";
import UiBrandMark from "@/components/UiBrandMark.vue";
import { useAuthStore } from "@/stores/auth";
import { useShellStore } from "@/stores/shell";

const router = useRouter();
const route = useRoute();
const shellStore = useShellStore();
const authStore = useAuthStore();

const { isNavigationOpen } = storeToRefs(shellStore);
const { isAuthenticated, isLocal, status: authenticationStatus, user } = storeToRefs(authStore);

const { t } = useI18n({
  useScope: "global",
});

const navigationToggleLabel = computed(() =>
  isNavigationOpen.value ? t("navigation.closeLabel") : t("navigation.openLabel"),
);

const navigationToggleText = computed(() =>
  isNavigationOpen.value ? t("navigation.close") : t("navigation.menu"),
);

const inProjects = computed(() => route.name === "projects" || route.name === "project-detail");

const initials = computed(() => {
  const name = (user.value?.email ?? "").split("@")[0] ?? "";
  const parts = name.split(/[^\p{L}\p{N}]+/u).filter((part) => part.length > 0);
  return parts
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("")
    .toUpperCase();
});

function navigationLinkClasses(isActive: boolean): string[] {
  return [
    "inline-flex min-h-11 items-center rounded-control px-3.5 text-[15px] font-medium text-ink transition-colors duration-150",
    isActive ? "bg-surface-3" : "hover:bg-surface-3/70",
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

    <header class="sticky top-0 z-40 border-b border-topbar-line bg-page/94 backdrop-blur-sm">
      <div
        class="mx-auto flex min-h-16 max-w-[1240px] flex-wrap items-center gap-x-6 px-4 py-2.5 sm:px-6 md:flex-nowrap lg:px-8"
      >
        <RouterLink
          class="inline-flex min-h-11 shrink-0 items-center rounded-control"
          to="/"
          :aria-label="t('app.homeAriaLabel')"
          data-testid="home-link"
        >
          <UiBrandMark wordmark />
        </RouterLink>

        <button
          class="ml-auto inline-flex min-h-11 items-center justify-center rounded-pill border border-line-strong bg-surface px-4 text-sm font-semibold text-ink transition-colors duration-150 hover:bg-surface-3 md:hidden"
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
            'mt-2.5 w-full flex-col gap-3 border-t border-line pt-3 md:mt-0 md:ml-auto md:w-auto md:flex-row md:items-center md:gap-1 md:border-0 md:pt-0',
            isNavigationOpen ? 'flex' : 'hidden md:flex',
          ]"
          :aria-label="t('navigation.label')"
          @click="shellStore.closeNavigation"
        >
          <div class="flex flex-col gap-1 md:flex-row md:items-center">
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
                :class="navigationLinkClasses(inProjects)"
                :aria-current="isExactActive ? 'page' : undefined"
                data-testid="projects-link"
                @click="navigate"
              >
                {{ t("navigation.projects") }}
              </a>
            </RouterLink>

            <RouterLink
              v-if="!isAuthenticated && !isLocal"
              v-slot="{ href, navigate, isExactActive }"
              custom
              to="/login"
            >
              <a
                :href="href"
                :class="navigationLinkClasses(isExactActive)"
                :aria-current="isExactActive ? 'page' : undefined"
                data-testid="login-link"
                @click="navigate"
              >
                {{ t("navigation.login") }}
              </a>
            </RouterLink>

            <RouterLink
              v-if="!isAuthenticated && !isLocal"
              class="inline-flex min-h-11 items-center justify-center rounded-control border border-ink bg-ink px-4 text-[15px] font-semibold text-white transition-colors duration-150 hover:bg-ink-2 md:ml-1.5"
              to="/register"
              data-testid="register-link"
            >
              {{ t("navigation.register") }}
            </RouterLink>
          </div>

          <span aria-hidden="true" class="mx-2 hidden h-5 w-px bg-line-strong md:block" />

          <div class="flex items-center gap-1">
            <LanguageSwitcher />

            <template v-if="isAuthenticated">
              <span
                class="ml-auto inline-flex min-h-11 items-center px-1 md:ml-1"
                :title="user?.email"
                data-testid="user-initials"
              >
                <span
                  aria-hidden="true"
                  class="inline-flex h-8 min-w-8 items-center justify-center rounded-full bg-ink px-1 text-[13px] font-semibold text-white"
                >
                  {{ initials }}
                </span>
                <span class="sr-only">{{ t("navigation.account", { email: user?.email }) }}</span>
              </span>

              <button
                v-if="!isLocal"
                class="inline-flex min-h-11 items-center rounded-control px-3 text-[15px] font-medium text-ink-3 transition-colors duration-150 hover:bg-surface-3/70 hover:text-ink disabled:cursor-not-allowed"
                type="button"
                :disabled="authenticationStatus === 'loading'"
                data-testid="logout-button"
                @click="logout"
              >
                {{ t("navigation.logout") }}
              </button>
            </template>

            <span
              v-if="isLocal"
              class="inline-flex min-h-8 items-center rounded-pill border border-action-soft-line bg-action-soft px-3 text-[13px] font-semibold whitespace-nowrap text-action"
              :title="t('navigation.localStudioTitle')"
              data-testid="local-studio-badge"
            >
              {{ t("navigation.localStudio") }}
            </span>
          </div>
        </nav>
      </div>
    </header>

    <main
      id="main-content"
      class="mx-auto min-h-[calc(100vh-4rem)] w-full max-w-[1320px] px-4 pt-4 pb-12 focus:outline-none sm:px-6"
      tabindex="-1"
    >
      <RouterView />
    </main>
  </div>
</template>
