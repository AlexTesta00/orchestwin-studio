<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { AuthenticationInput } from "@/api/contracts";
import AuthenticationForm from "@/components/AuthenticationForm.vue";
import UiBrandMark from "@/components/UiBrandMark.vue";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n({
  useScope: "global",
});
const router = useRouter();
const auth = useAuthStore();
const { errorDetail, status } = storeToRefs(auth);

const busy = computed(() => status.value === "loading");
const points = computed(() => [t("auth.points.one"), t("auth.points.two"), t("auth.points.three")]);

async function register(credentials: AuthenticationInput): Promise<void> {
  const succeeded = await auth.register(apiClient, credentials);

  if (succeeded) {
    await router.replace({
      name: "projects",
    });
  }
}
</script>

<template>
  <section
    class="mx-auto grid max-w-[880px] items-start gap-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]"
    aria-labelledby="register-title"
  >
    <header class="grid gap-5">
      <UiBrandMark :size="44" />
      <h1 id="register-title" class="m-0 text-[42px] leading-[1.15] font-semibold tracking-title">
        {{ t("auth.register.title") }}
      </h1>
      <p class="m-0 text-[17px] leading-7 text-ink-2">
        {{ t("auth.register.description") }}
      </p>
      <ul class="m-0 grid list-none gap-3 p-0">
        <li
          v-for="point in points"
          :key="point"
          class="flex items-start gap-3 text-[15px] text-ink-2"
        >
          <span
            class="mt-2 inline-block h-2 w-2 shrink-0 rounded-full bg-action"
            aria-hidden="true"
          />
          <span>{{ point }}</span>
        </li>
      </ul>
    </header>

    <div class="grid gap-5">
      <div class="rounded-[20px] border border-line bg-surface p-6 shadow-card sm:p-8">
        <AuthenticationForm mode="register" :busy="busy" :error="errorDetail" @submit="register" />
      </div>

      <p class="m-0 text-center text-sm text-ink-2">
        {{ t("auth.register.hasAccount") }}

        <RouterLink class="font-semibold text-action underline underline-offset-4" to="/login">
          {{ t("auth.register.loginLink") }}
        </RouterLink>
      </p>
    </div>
  </section>
</template>
