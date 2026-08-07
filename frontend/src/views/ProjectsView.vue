<script setup lang="ts">
import { useI18n } from "vue-i18n";

const { t } = useI18n({
  useScope: "global",
});
</script>

<template>
  <section
    class="grid gap-10"
    aria-labelledby="projects-title"
  >
    <header class="grid max-w-3xl gap-4">
      <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
        {{ t("projects.eyebrow") }}
      </p>

      <h1
        id="projects-title"
        class="m-0 text-4xl leading-tight font-black tracking-tight text-slate-950 sm:text-5xl lg:text-6xl"
      >
        {{ t("projects.title") }}
      </h1>

      <p class="m-0 max-w-2xl text-xl leading-relaxed font-semibold text-slate-700">
        {{ t("projects.description") }}
      </p>
    </header>

    <section
      class="max-w-2xl rounded-2xl border border-dashed border-slate-300 bg-white p-6 shadow-sm sm:p-8"
      aria-labelledby="projects-empty-title"
    >
      <div
        class="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-xl font-black text-slate-700"
        aria-hidden="true"
      >
        0
      </div>

      <h2
        id="projects-empty-title"
        class="m-0 text-2xl font-black tracking-tight text-slate-950"
      >
        {{ t("projects.emptyTitle") }}
      </h2>

      <p class="mt-3 mb-0 max-w-xl text-base leading-7 text-slate-600">
        {{ t("projects.emptyDescription") }}
      </p>
    </section>
  </section>
</template>