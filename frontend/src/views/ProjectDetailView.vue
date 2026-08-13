<script setup lang="ts">
import {
  computed,
  onMounted,
  ref,
  watch,
} from "vue";
import {
  useI18n,
} from "vue-i18n";
import {
  useRoute,
} from "vue-router";

import {
  apiClient,
  ApiError,
} from "@/api/client";
import type {
  ProjectBriefInput,
  ProjectBriefVersionResponse,
  ProjectResponse,
} from "@/api/contracts";
import ProjectBriefEditor from "@/components/ProjectBriefEditor.vue";
import ProjectClarificationFlow from "@/components/ProjectClarificationFlow.vue";
import ProjectTeamSelectionFlow from "@/components/ProjectTeamSelectionFlow.vue";
import {
  useAuthStore,
} from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();

const {
  t,
  locale,
} = useI18n({
  useScope: "local",
  messages: {
    en: {
      detail: {
        loading: "Loading project…",
        loadError:
          "The project could not be loaded.",
        saveError:
          "The Project Brief version could not be saved.",
        mode: "Mode",
        currentBrief: "Current Project Brief",
        noBrief:
          "No Project Brief version has been created.",
        versionHistory: "Brief version history",
        noVersions:
          "No Project Brief version is available.",
        version: "Version {number}",
        createdAt: "Created {date}",
        contentHash: "Content hash",
      },
    },
    it: {
      detail: {
        loading: "Caricamento progetto…",
        loadError:
          "Non è stato possibile caricare il progetto.",
        saveError:
          "Non è stato possibile salvare la versione del Project Brief.",
        mode: "Modalità",
        currentBrief: "Project Brief corrente",
        noBrief:
          "Non è stata ancora creata una versione del Project Brief.",
        versionHistory:
          "Cronologia versioni del brief",
        noVersions:
          "Non è disponibile alcuna versione del Project Brief.",
        version: "Versione {number}",
        createdAt: "Creata {date}",
        contentHash: "Hash del contenuto",
      },
    },
  },
});

const project = ref<ProjectResponse | null>(
  null,
);
const currentBrief =
  ref<ProjectBriefVersionResponse | null>(
    null,
  );
const briefHistory =
  ref<
    readonly ProjectBriefVersionResponse[]
  >([]);

const loading = ref(true);
const saving = ref(false);
const errorDetail =
  ref<string | null>(null);

const projectId = computed(() => {
  const value =
    route.params.projectId ??
    route.params.id;

  if (Array.isArray(value)) {
    return value[0] ?? "";
  }

  return value ?? "";
});

function errorCode(
  error: unknown,
  fallback: string,
): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  return fallback;
}

function formatDate(
  value: string,
): string {
  return new Intl.DateTimeFormat(
    locale.value,
    {
      dateStyle: "medium",
      timeStyle: "short",
    },
  ).format(new Date(value));
}

async function authorized<T>(
  operation: (
    accessToken: string,
  ) => Promise<T>,
): Promise<T> {
  return auth.withAccessToken(
    apiClient,
    operation,
  );
}

async function loadProject(): Promise<void> {
  if (!projectId.value) {
    errorDetail.value =
      "project_not_found";
    loading.value = false;

    return;
  }

  loading.value = true;
  errorDetail.value = null;

  try {
    const [
      projectResult,
      versions,
    ] = await Promise.all([
      authorized((accessToken) =>
        apiClient.getProject(
          accessToken,
          projectId.value,
        ),
      ),
      authorized((accessToken) =>
        apiClient.listBriefVersions(
          accessToken,
          projectId.value,
        ),
      ),
    ]);

    project.value = projectResult;
    briefHistory.value = [
      ...versions,
    ];

    currentBrief.value =
      versions.length > 0
        ? versions[
            versions.length - 1
          ] ?? null
        : null;
  } catch (error: unknown) {
    errorDetail.value = errorCode(
      error,
      "project_load_failed",
    );
  } finally {
    loading.value = false;
  }
}

async function saveBrief(
  brief: ProjectBriefInput,
): Promise<void> {
  if (!projectId.value) {
    return;
  }

  saving.value = true;
  errorDetail.value = null;

  try {
    await authorized(
      (accessToken) =>
        apiClient.createBriefVersion(
          accessToken,
          projectId.value,
          brief,
        ),
    );

    await loadProject();
  } catch (error: unknown) {
    errorDetail.value = errorCode(
      error,
      "brief_save_failed",
    );
  } finally {
    saving.value = false;
  }
}

watch(
  projectId,
  async () => {
    await loadProject();
  },
);

onMounted(loadProject);
</script>

<template>
  <main
    class="mx-auto grid w-full max-w-7xl gap-10 px-4 py-8 sm:px-6 lg:px-8"
  >
    <p
      v-if="loading"
      class="m-0 text-slate-700"
      aria-live="polite"
    >
      {{ t("detail.loading") }}
    </p>

    <p
      v-else-if="errorDetail !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{
        errorDetail ===
        "brief_save_failed"
          ? t("detail.saveError")
          : t("detail.loadError")
      }}
    </p>

    <template
      v-else-if="project !== null"
    >
      <header
        class="grid gap-3 border-b border-slate-200 pb-8"
      >
        <h1
          class="text-3xl font-black tracking-tight text-slate-950 sm:text-4xl"
        >
          {{ project.display_name }}
        </h1>

        <p
          class="m-0 text-sm font-semibold uppercase tracking-wide text-slate-600"
        >
          {{ t("detail.mode") }}:
          {{ project.mode }}
        </p>
      </header>

      <section
        class="grid gap-5"
        aria-labelledby="current-brief-title"
      >
        <h2
          id="current-brief-title"
          class="text-2xl font-black text-slate-950"
        >
          {{ t("detail.currentBrief") }}
        </h2>

        <div
          v-if="currentBrief !== null"
          class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <p class="m-0 font-bold text-slate-900">
            {{
              t("detail.version", {
                number:
                  currentBrief.version_number,
              })
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              t("detail.createdAt", {
                date: formatDate(
                  currentBrief.created_at,
                ),
              })
            }}
          </p>

          <p class="m-0 break-all text-xs text-slate-500">
            {{ t("detail.contentHash") }}:
            <code>
              {{ currentBrief.content_hash }}
            </code>
          </p>
        </div>

        <p
          v-else
          class="m-0 text-slate-600"
        >
          {{ t("detail.noBrief") }}
        </p>

        <ProjectBriefEditor
          :key="
            currentBrief?.version_number ??
            0
          "
          :initial="
            currentBrief?.brief ?? null
          "
          :busy="saving"
          @submit="saveBrief"
        />
      </section>

      <section
        class="grid gap-4"
        aria-labelledby="brief-history-title"
      >
        <h2
          id="brief-history-title"
          class="text-2xl font-black text-slate-950"
        >
          {{ t("detail.versionHistory") }}
        </h2>

        <ol
          v-if="
            briefHistory.length > 0
          "
          class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
        >
          <li
            v-for="version in briefHistory"
            :key="version.id"
            class="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <p class="m-0 font-black text-slate-900">
              {{
                t("detail.version", {
                  number:
                    version.version_number,
                })
              }}
            </p>

            <p class="m-0 text-sm text-slate-600">
              {{
                formatDate(
                  version.created_at,
                )
              }}
            </p>

            <code
              class="break-all text-xs text-slate-500"
            >
              {{ version.content_hash }}
            </code>
          </li>
        </ol>

        <p
          v-else
          class="m-0 text-slate-600"
        >
          {{ t("detail.noVersions") }}
        </p>
      </section>

      <ProjectClarificationFlow
        :key="
          `${projectId}:${
            currentBrief?.version_number ??
            0
          }:clarification`
        "
        :project-id="projectId"
      />

      <ProjectTeamSelectionFlow
        :key="
          `${projectId}:${
            currentBrief?.version_number ??
            0
          }:team`
        "
        :project-id="projectId"
      />
    </template>
  </main>
</template>