<script setup lang="ts">
import { useI18n } from "vue-i18n";

const capabilityKeys = ["backend", "api", "frontend"] as const;

const { t } = useI18n({
  useScope: "global",
});
</script>

<template>
  <section
    class="grid gap-10"
    aria-labelledby="overview-title"
  >
    <header class="grid max-w-3xl gap-4">
      <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
        {{ t("overview.eyebrow") }}
      </p>

      <h1
        id="overview-title"
        class="m-0 text-4xl leading-tight font-black tracking-tight text-slate-950 sm:text-5xl lg:text-6xl"
      >
        {{ t("overview.title") }}
      </h1>

      <p class="m-0 text-xl leading-relaxed font-semibold text-slate-700">
        {{ t("overview.status") }}
      </p>

      <p class="m-0 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
        {{ t("overview.description") }}
      </p>
    </header>

    <section
      class="grid gap-5"
      aria-labelledby="foundation-capabilities-title"
    >
      <h2
        id="foundation-capabilities-title"
        class="m-0 text-2xl font-black tracking-tight text-slate-950 sm:text-3xl"
      >
        {{ t("overview.capabilitiesTitle") }}
      </h2>

      <ul class="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
        <li
          v-for="capabilityKey in capabilityKeys"
          :key="capabilityKey"
          class="rounded-2xl border border-slate-200 bg-white p-6 font-bold text-slate-800 shadow-sm transition-transform duration-200 hover:-translate-y-1 hover:shadow-md"
        >
          <span
            class="mb-5 block h-2 w-12 rounded-full bg-slate-900"
            aria-hidden="true"
          ></span>

          {{ t(`overview.capabilities.${capabilityKey}`) }}
        </li>
      </ul>
    </section>
  </section>
</template>