<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { AuthenticationInput } from "@/api/contracts";
import AuthenticationForm from "@/components/AuthenticationForm.vue";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n({
  useScope: "global",
});
const router = useRouter();
const auth = useAuthStore();
const { errorDetail, status } = storeToRefs(auth);

const busy = computed(
  () => status.value === "loading",
);

async function register(
  credentials: AuthenticationInput,
): Promise<void> {
  const succeeded = await auth.register(
    apiClient,
    credentials,
  );

  if (succeeded) {
    await router.replace({
      name: "projects",
    });
  }
}
</script>

<template>
  <section
    class="mx-auto grid max-w-lg gap-8"
    aria-labelledby="register-title"
  >
    <header class="grid gap-3">
      <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
        {{ t("auth.register.eyebrow") }}
      </p>

      <h1
        id="register-title"
        class="m-0 text-4xl font-black tracking-tight text-slate-950"
      >
        {{ t("auth.register.title") }}
      </h1>

      <p class="m-0 leading-7 text-slate-600">
        {{ t("auth.register.description") }}
      </p>
    </header>

    <div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
      <AuthenticationForm
        mode="register"
        :busy="busy"
        :error="errorDetail"
        @submit="register"
      />
    </div>

    <p class="m-0 text-center text-sm text-slate-600">
      {{ t("auth.register.hasAccount") }}

      <RouterLink
        class="font-bold text-slate-950 underline decoration-2 underline-offset-4"
        to="/login"
      >
        {{ t("auth.register.loginLink") }}
      </RouterLink>
    </p>
  </section>
</template>