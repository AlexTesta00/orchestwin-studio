<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { ProjectMode } from "@/api/contracts";
import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
import UiStateBlock from "@/components/UiStateBlock.vue";
import UiStatusChip from "@/components/UiStatusChip.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectsStore } from "@/stores/projects";

const { t, te, locale } = useI18n({
  useScope: "global",
});
const router = useRouter();
const auth = useAuthStore();
const projectStore = useProjectsStore();

const { projects, loading, errorDetail } = storeToRefs(projectStore);

const creating = ref(false);
const displayName = ref("");
const mode = ref<ProjectMode>("GREENFIELD_GENERATION");

onMounted(() => {
  void projectStore.loadProjects(apiClient, auth);
});

function updatedOn(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat(locale.value, { dateStyle: "medium" }).format(parsed);
}

async function createProject(): Promise<void> {
  const project = await projectStore.createProject(apiClient, auth, {
    display_name: displayName.value,
    mode: mode.value,
  });

  if (project !== null) {
    displayName.value = "";
    creating.value = false;

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
  <section class="grid gap-8" aria-labelledby="projects-title">
    <header class="flex flex-wrap items-end justify-between gap-5">
      <div class="grid max-w-3xl gap-2">
        <h1 id="projects-title" class="m-0 text-[34px] leading-[1.2] font-semibold tracking-title">
          {{ t("projects.listTitle") }}
        </h1>
        <p class="m-0 text-[15px] leading-6 text-ink-2">
          {{ t("projects.description") }}
        </p>
      </div>
      <UiButton data-testid="new-project" @click="creating = !creating">
        {{ creating ? t("projects.cancel") : t("projects.new") }}
      </UiButton>
    </header>

    <UiStateBlock
      v-if="errorDetail"
      kind="error"
      :title="
        t(
          te(`projects.errors.${errorDetail}`)
            ? `projects.errors.${errorDetail}`
            : 'projects.errors.unexpected_error',
        )
      "
    />

    <UiCard v-if="creating" tone="elevated">
      <h2 id="create-project-title" class="m-0 text-2xl font-semibold tracking-card">
        {{ t("projects.create.title") }}
      </h2>

      <form
        class="mt-5 grid gap-4 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end"
        @submit.prevent="createProject"
      >
        <div class="grid gap-2">
          <label class="text-sm font-semibold" for="project-name">
            {{ t("projects.create.name") }}
          </label>

          <input
            id="project-name"
            v-model="displayName"
            class="min-h-11 rounded-control border border-field bg-surface px-4 py-2.5 text-[15px]"
            maxlength="120"
            required
          />
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-semibold" for="project-mode">
            {{ t("projects.create.mode") }}
          </label>

          <select
            id="project-mode"
            v-model="mode"
            class="min-h-11 rounded-control border border-field bg-surface px-4 py-2.5 text-[15px]"
          >
            <option value="GREENFIELD_GENERATION">
              {{ t("projects.modes.greenfield") }}
            </option>

            <option value="BROWNFIELD_ASSESSMENT">
              {{ t("projects.modes.brownfield") }}
            </option>
          </select>
        </div>

        <UiButton type="submit" :disabled="loading">
          {{ t("projects.create.submit") }}
        </UiButton>
      </form>
    </UiCard>

    <UiStateBlock
      v-if="projects.length === 0 && !loading"
      kind="empty"
      :title="t('projects.emptyTitle')"
      :text="t('projects.emptyDescription')"
    />

    <UiCard v-else tone="table">
      <div
        class="grid grid-cols-[minmax(0,2.2fr)_minmax(0,1.5fr)_minmax(0,1fr)_84px] gap-4 border-b border-line-soft bg-surface-3 px-5 py-3 font-mono text-[11px] tracking-wide text-ink-3 uppercase"
        role="row"
      >
        <span>{{ t("projects.table.name") }}</span>
        <span>{{ t("projects.table.mode") }}</span>
        <span>{{ t("projects.table.updated") }}</span>
        <span class="sr-only">{{ t("projects.table.open") }}</span>
      </div>
      <ul class="m-0 list-none p-0" data-testid="project-rows">
        <li
          v-for="project in projects"
          :key="project.id"
          class="grid grid-cols-[minmax(0,2.2fr)_minmax(0,1.5fr)_minmax(0,1fr)_84px] items-center gap-4 border-b border-line-soft px-5 py-4 last:border-b-0"
        >
          <span class="min-w-0">
            <span class="block truncate text-[15px] font-semibold">{{ project.display_name }}</span>
            <span class="block font-mono text-[11px] text-ink-3">
              {{ t("projects.currentVersion", { version: project.current_brief_version }) }}
            </span>
          </span>
          <span class="min-w-0">
            <UiStatusChip
              status="pending"
              :label="
                t(
                  `projects.modes.${project.mode === 'GREENFIELD_GENERATION' ? 'greenfield' : 'brownfield'}`,
                )
              "
            />
          </span>
          <span class="font-mono text-xs text-ink-3">{{ updatedOn(project.updated_at) }}</span>
          <RouterLink
            class="inline-flex min-h-9 items-center justify-center rounded-control border border-button-line bg-surface px-3 text-sm font-semibold text-ink hover:bg-surface-3"
            :to="{
              name: 'project-detail',
              params: {
                projectId: project.id,
              },
            }"
          >
            {{ t("projects.table.open") }}
          </RouterLink>
        </li>
      </ul>
    </UiCard>

    <p class="m-0 font-mono text-xs text-ink-3">{{ t("projects.note") }}</p>
  </section>
</template>
