<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { ProjectBriefInput } from "@/api/contracts";
import ProjectBriefEditor from "@/components/ProjectBriefEditor.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectsStore } from "@/stores/projects";

const route = useRoute();
const { t } = useI18n({
  useScope: "global",
});
const auth = useAuthStore();
const projects = useProjectsStore();

const { currentProject, currentBrief, briefVersions, loading, errorDetail } = storeToRefs(projects);

const projectId = computed(() => String(route.params.projectId));

async function load(): Promise<void> {
  await projects.loadProject(apiClient, auth, projectId.value);
}

async function saveBrief(brief: ProjectBriefInput): Promise<void> {
  await projects.saveBrief(apiClient, auth, projectId.value, brief);
}

onMounted(() => {
  void load();
});

watch(projectId, () => {
  projects.clearCurrentProject();
  void load();
});
</script>

<template>
  <section class="grid gap-10" aria-labelledby="project-detail-title">
    <div
      v-if="errorDetail"
      class="rounded-xl border border-red-300 bg-red-50 p-4 font-semibold text-red-900"
      role="alert"
    >
      {{ t(`projects.errors.${errorDetail}`) }}
    </div>

    <template v-if="currentProject">
      <header class="grid gap-4">
        <RouterLink
          class="w-fit font-bold text-slate-700 underline decoration-2 underline-offset-4"
          to="/projects"
        >
          {{ t("projects.detail.back") }}
        </RouterLink>

        <p class="m-0 text-sm font-black tracking-[0.12em] text-slate-600 uppercase">
          {{ t("projects.detail.eyebrow") }}
        </p>

        <h1
          id="project-detail-title"
          class="m-0 text-4xl font-black tracking-tight text-slate-950 sm:text-5xl"
        >
          {{ currentProject.display_name }}
        </h1>

        <p class="m-0 text-slate-600">
          {{
            t("projects.currentVersion", {
              version: currentProject.current_brief_version,
            })
          }}
        </p>
      </header>

      <div class="grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <section
          class="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
          aria-labelledby="brief-editor-title"
        >
          <h2 id="brief-editor-title" class="mb-6 text-2xl font-black text-slate-950">
            {{ t("brief.editorTitle") }}
          </h2>

          <ProjectBriefEditor
            :initial="currentBrief?.brief ?? null"
            :busy="loading"
            @submit="saveBrief"
          />
        </section>

        <aside
          class="grid content-start gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
          aria-labelledby="brief-history-title"
        >
          <h2 id="brief-history-title" class="m-0 text-2xl font-black text-slate-950">
            {{ t("brief.historyTitle") }}
          </h2>

          <p v-if="briefVersions.length === 0" class="m-0 text-slate-600">
            {{ t("brief.noVersions") }}
          </p>

          <ol v-else class="m-0 grid list-none gap-3 p-0">
            <li
              v-for="version in briefVersions"
              :key="version.id"
              class="rounded-xl border border-slate-200 p-4"
            >
              <p class="m-0 font-black text-slate-950">
                {{
                  t("brief.version", {
                    version: version.version_number,
                  })
                }}
              </p>

              <p class="mt-2 mb-0 text-sm text-slate-600">
                {{ new Date(version.created_at).toLocaleString() }}
              </p>
            </li>
          </ol>
        </aside>
      </div>
    </template>
  </section>
</template>
