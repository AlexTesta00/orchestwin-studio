<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useAuthStore } from "@/stores/auth";

const capabilityKeys = ["backend", "api", "frontend"] as const;
const auth = useAuthStore();

const { t } = useI18n({
  useScope: "global",
});
</script>

<template>
  <section class="grid gap-8 py-4" aria-labelledby="overview-title">
    <header class="grid max-w-2xl gap-4">
      <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
        {{ t("overview.eyebrow") }}
      </p>

      <h1
        id="overview-title"
        class="m-0 text-3xl leading-tight font-bold tracking-tight text-slate-950 sm:text-4xl"
      >
        {{ t("overview.title") }}
      </h1>

      <p class="m-0 text-lg leading-relaxed font-medium text-slate-700">
        {{ t("overview.status") }}
      </p>

      <p class="m-0 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
        {{ t("overview.description") }}
      </p>
      <RouterLink
        :to="auth.isAuthenticated ? '/projects' : '/register'"
        class="mt-2 w-fit rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
        >{{ t(auth.isAuthenticated ? "overview.start" : "overview.begin") }} →</RouterLink
      >
    </header>

    <section class="grid gap-5" aria-labelledby="foundation-capabilities-title">
      <h2
        id="foundation-capabilities-title"
        class="m-0 text-lg font-bold tracking-tight text-slate-950"
      >
        {{ t("overview.capabilitiesTitle") }}
      </h2>

      <ul class="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
        <li
          v-for="(capabilityKey, index) in capabilityKeys"
          :key="capabilityKey"
          class="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-5 text-sm font-semibold text-slate-800"
        >
          <span
            class="flex size-8 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-indigo-700"
            aria-hidden="true"
            >{{ index + 1 }}</span
          >

          {{ t(`overview.capabilities.${capabilityKey}`) }}
        </li>
      </ul>
    </section>
  </section>
</template>
