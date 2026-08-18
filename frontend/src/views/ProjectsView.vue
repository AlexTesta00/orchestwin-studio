<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { ProjectMode } from "@/api/contracts";
import { useAuthStore } from "@/stores/auth";
import { useProjectsStore } from "@/stores/projects";

const { t } = useI18n({
  useScope: "global",
});
const router = useRouter();
const auth = useAuthStore();
const projectStore = useProjectsStore();

const { projects, loading, errorDetail } = storeToRefs(projectStore);

const displayName = ref("");
const mode = ref<ProjectMode>("GREENFIELD_GENERATION");

onMounted(() => {
  void projectStore.loadProjects(apiClient, auth);
});

async function createProject(): Promise<void> {
  const project = await projectStore.createProject(apiClient, auth, {
    display_name: displayName.value,
    mode: mode.value,
  });

  if (project !== null) {
    displayName.value = "";

    await router.push({
      name: "project-detail",
      params: {
        projectId: project.id,
      },
    });
  }
}
</script>

<template>
  <section class="grid gap-10" aria-labelledby="projects-title">
    <header class="grid max-w-3xl gap-4">
      <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
        {{ t("projects.eyebrow") }}
      </p>

      <h1
        id="projects-title"
        class="m-0 text-4xl font-black tracking-tight text-slate-950 sm:text-5xl"
      >
        {{ t("projects.title") }}
      </h1>

      <p class="m-0 text-lg leading-7 text-slate-600">
        {{ t("projects.description") }}
      </p>
    </header>

    <div
      v-if="errorDetail"
      class="rounded-xl border border-red-300 bg-red-50 p-4 font-semibold text-red-900"
      role="alert"
    >
      {{ t(`projects.errors.${errorDetail}`) }}
    </div>

    <section
      class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      aria-labelledby="create-project-title"
    >
      <h2 id="create-project-title" class="m-0 text-2xl font-black text-slate-950">
        {{ t("projects.create.title") }}
      </h2>

      <form
        class="grid gap-4 md:grid-cols-[1fr_auto_auto] md:items-end"
        @submit.prevent="createProject"
      >
        <div class="grid gap-2">
          <label class="font-bold text-slate-800" for="project-name">
            {{ t("projects.create.name") }}
          </label>

          <input
            id="project-name"
            v-model="displayName"
            class="min-h-12 rounded-xl border border-slate-300 px-4 py-3 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:outline-none"
            maxlength="120"
            required
          />
        </div>

        <div class="grid gap-2">
          <label class="font-bold text-slate-800" for="project-mode">
            {{ t("projects.create.mode") }}
          </label>

          <select
            id="project-mode"
            v-model="mode"
            class="min-h-12 rounded-xl border border-slate-300 bg-white px-4 py-3 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:outline-none"
          >
            <option value="GREENFIELD_GENERATION">
              {{ t("projects.modes.greenfield") }}
            </option>

            <option value="BROWNFIELD_ASSESSMENT">
              {{ t("projects.modes.brownfield") }}
            </option>
          </select>
        </div>

        <button
          class="min-h-12 rounded-xl bg-slate-950 px-5 py-3 font-bold text-white hover:bg-slate-800 disabled:opacity-60"
          type="submit"
          :disabled="loading"
        >
          {{ t("projects.create.submit") }}
        </button>
      </form>
    </section>

    <section class="grid gap-5" aria-labelledby="project-list-title">
      <h2 id="project-list-title" class="m-0 text-2xl font-black text-slate-950">
        {{ t("projects.listTitle") }}
      </h2>

      <div
        v-if="projects.length === 0 && !loading"
        class="rounded-2xl border border-dashed border-slate-300 bg-white p-8"
      >
        <h3 class="m-0 text-xl font-black">
          {{ t("projects.emptyTitle") }}
        </h3>

        <p class="mt-3 mb-0 text-slate-600">
          {{ t("projects.emptyDescription") }}
        </p>
      </div>

      <ul v-else class="m-0 grid list-none gap-4 p-0 sm:grid-cols-2">
        <li v-for="project in projects" :key="project.id">
          <RouterLink
            class="grid h-full gap-3 rounded-2xl border border-slate-200 bg-white p-6 text-slate-950 shadow-sm transition-transform hover:-translate-y-1 hover:shadow-md focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:outline-none"
            :to="{
              name: 'project-detail',
              params: {
                projectId: project.id,
              },
            }"
          >
            <span class="text-xl font-black">
              {{ project.display_name }}
            </span>

            <span class="text-sm font-semibold text-slate-600">
              {{
                t(
                  `projects.modes.${project.mode === "GREENFIELD_GENERATION" ? "greenfield" : "brownfield"}`,
                )
              }}
            </span>

            <span class="text-sm text-slate-600">
              {{
                t("projects.currentVersion", {
                  version: project.current_brief_version,
                })
              }}
            </span>
          </RouterLink>
        </li>
      </ul>
    </section>
  </section>
</template>
