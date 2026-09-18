<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { apiClient, ApiError } from "@/api/client";
import type {
  ProjectBriefInput,
  ProjectBriefVersionResponse,
  ProjectResponse,
} from "@/api/contracts";
import ProjectArchitectureFlow from "@/components/ProjectArchitectureFlow.vue";
import ProjectArtifactGraph from "@/components/ProjectArtifactGraph.vue";
import ProjectBriefEditor from "@/components/ProjectBriefEditor.vue";
import ProjectBrownfieldSourceFlow from "@/components/ProjectBrownfieldSourceFlow.vue";
import ProjectClarificationFlow from "@/components/ProjectClarificationFlow.vue";
import ProjectDesignFlow from "@/components/ProjectDesignFlow.vue";
import ProjectRequirementsFlow from "@/components/ProjectRequirementsFlow.vue";
import ProjectJvmEvidenceReview from "@/components/ProjectJvmEvidenceReview.vue";
import ProjectJvmSourceReview from "@/components/ProjectJvmSourceReview.vue";
import ProjectExecutionLaunch from "@/components/ProjectExecutionLaunch.vue";
import ProjectSandboxGovernanceFlow from "@/components/ProjectSandboxGovernanceFlow.vue";
import ProjectSourceGeneration from "@/components/ProjectSourceGeneration.vue";
import ModelRuntimeStatus from "@/components/ModelRuntimeStatus.vue";
import ProjectUserModelingFlow from "@/components/ProjectUserModelingFlow.vue";
import ProjectWebPreview from "@/components/ProjectWebPreview.vue";
import ProjectTeamSelectionFlow from "@/components/ProjectTeamSelectionFlow.vue";
import ProjectWebEvidenceReview from "@/components/ProjectWebEvidenceReview.vue";
import ProjectWebSourceReview from "@/components/ProjectWebSourceReview.vue";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();

const { t, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      detail: {
        loading: "Loading project…",
        loadError: "The project could not be loaded.",
        saveError: "The Project Brief version could not be saved.",
        mode: "Mode",
        currentBrief: "Current Project Brief",
        noBrief: "No Project Brief version has been created.",
        versionHistory: "Brief version history",
        noVersions: "No Project Brief version is available.",
        version: "Version {number}",
        createdAt: "Created {date}",
        contentHash: "Content hash",
      },
    },
    it: {
      detail: {
        loading: "Caricamento progetto…",
        loadError: "Non è stato possibile caricare il progetto.",
        saveError: "Non è stato possibile salvare la versione del Project Brief.",
        mode: "Modalità",
        currentBrief: "Project Brief corrente",
        noBrief: "Non è stata ancora creata una versione del Project Brief.",
        versionHistory: "Cronologia versioni del brief",
        noVersions: "Non è disponibile alcuna versione del Project Brief.",
        version: "Versione {number}",
        createdAt: "Creata {date}",
        contentHash: "Hash del contenuto",
      },
    },
  },
});

const project = ref<ProjectResponse | null>(null);
const currentBrief = ref<ProjectBriefVersionResponse | null>(null);
const briefHistory = ref<readonly ProjectBriefVersionResponse[]>([]);

const loading = ref(true);
const saving = ref(false);
const errorDetail = ref<string | null>(null);
let projectEpoch = 0;

const projectId = computed(() => {
  const value = route.params.projectId ?? route.params.id;

  if (Array.isArray(value)) {
    return value[0] ?? "";
  }

  return value ?? "";
});

function errorCode(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.detail;
  }

  return fallback;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(locale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

async function authorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return auth.withAccessToken(apiClient, operation);
}

async function loadProject(): Promise<void> {
  const id = projectId.value;
  const epoch = ++projectEpoch;
  project.value = null;
  currentBrief.value = null;
  briefHistory.value = [];
  if (!id) {
    errorDetail.value = "project_not_found";
    loading.value = false;

    return;
  }

  loading.value = true;
  errorDetail.value = null;

  try {
    const [projectResult, versions] = await Promise.all([
      authorized((accessToken) => apiClient.getProject(accessToken, id)),
      authorized((accessToken) => apiClient.listBriefVersions(accessToken, id)),
    ]);
    if (epoch !== projectEpoch) return;
    project.value = projectResult;
    briefHistory.value = [...versions];
    currentBrief.value = versions.length > 0 ? (versions[versions.length - 1] ?? null) : null;
  } catch (error: unknown) {
    if (epoch === projectEpoch) errorDetail.value = errorCode(error, "project_load_failed");
  } finally {
    if (epoch === projectEpoch) loading.value = false;
  }
}

async function saveBrief(brief: ProjectBriefInput): Promise<void> {
  const id = projectId.value;
  const epoch = projectEpoch;
  if (!id || saving.value) {
    return;
  }

  saving.value = true;
  errorDetail.value = null;

  try {
    await authorized((accessToken) => apiClient.createBriefVersion(accessToken, id, brief));
    if (epoch === projectEpoch) await loadProject();
  } catch (error: unknown) {
    if (epoch === projectEpoch) errorDetail.value = errorCode(error, "brief_save_failed");
  } finally {
    saving.value = false;
  }
}

watch(projectId, loadProject, { immediate: true });
onUnmounted(() => {
  projectEpoch++;
});
</script>

<template>
  <main class="mx-auto grid w-full max-w-7xl gap-10 px-4 py-8 sm:px-6 lg:px-8">
    <p v-if="loading" class="m-0 text-slate-700" aria-live="polite">
      {{ t("detail.loading") }}
    </p>

    <p
      v-else-if="errorDetail !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ errorDetail === "brief_save_failed" ? t("detail.saveError") : t("detail.loadError") }}
    </p>

    <template v-else-if="project !== null">
      <header class="grid gap-3 border-b border-slate-200 pb-8">
        <h1 class="text-3xl font-black tracking-tight text-slate-950 sm:text-4xl">
          {{ project.display_name }}
        </h1>

        <p class="m-0 text-sm font-semibold tracking-wide text-slate-600 uppercase">
          {{ t("detail.mode") }}:
          {{ project.mode }}
        </p>
      </header>

      <ModelRuntimeStatus :locale="locale === 'it' ? 'it' : 'en'" />

      <nav
        class="flex flex-wrap gap-2 rounded-xl bg-slate-100 p-4"
        :aria-label="locale === 'it' ? 'Fasi del progetto' : 'Project stages'"
      >
        <a
          v-for="(step, index) in [
            ['current-brief-title', 'Brief'],
            ['studio-team', 'Team'],
            ['studio-twins', 'User Twin'],
            ['studio-requirements', locale === 'it' ? 'Requisiti' : 'Requirements'],
            ['studio-design', 'Design'],
            ['studio-architecture', locale === 'it' ? 'Architettura' : 'Architecture'],
            ['studio-source', locale === 'it' ? 'Generazione' : 'Generation'],
            ['studio-preview', locale === 'it' ? 'Risultato' : 'Result'],
          ]"
          :key="step[0]"
          :href="`#${step[0]}`"
          class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-bold text-slate-800 hover:bg-slate-200"
        >
          {{ index + 1 }}. {{ step[1] }}
        </a>
      </nav>

      <section class="grid gap-5" aria-labelledby="current-brief-title">
        <h2 id="current-brief-title" class="text-2xl font-black text-slate-950">
          {{ t("detail.currentBrief") }}
        </h2>

        <div
          v-if="currentBrief !== null"
          class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <p class="m-0 font-bold text-slate-900">
            {{
              t("detail.version", {
                number: currentBrief.version_number,
              })
            }}
          </p>

          <p class="m-0 text-sm text-slate-600">
            {{
              t("detail.createdAt", {
                date: formatDate(currentBrief.created_at),
              })
            }}
          </p>

          <p class="m-0 text-xs break-all text-slate-500">
            {{ t("detail.contentHash") }}:
            <code>
              {{ currentBrief.content_hash }}
            </code>
          </p>
        </div>

        <p v-else class="m-0 text-slate-600">
          {{ t("detail.noBrief") }}
        </p>

        <ProjectBriefEditor
          :key="currentBrief?.version_number ?? 0"
          :initial="currentBrief?.brief ?? null"
          :busy="saving"
          @submit="saveBrief"
        />
      </section>

      <section class="grid gap-4" aria-labelledby="brief-history-title">
        <h2 id="brief-history-title" class="text-2xl font-black text-slate-950">
          {{ t("detail.versionHistory") }}
        </h2>

        <ol v-if="briefHistory.length > 0" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <li
            v-for="version in briefHistory"
            :key="version.id"
            class="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <p class="m-0 font-black text-slate-900">
              {{
                t("detail.version", {
                  number: version.version_number,
                })
              }}
            </p>

            <p class="m-0 text-sm text-slate-600">
              {{ formatDate(version.created_at) }}
            </p>

            <code class="text-xs break-all text-slate-500">
              {{ version.content_hash }}
            </code>
          </li>
        </ol>

        <p v-else class="m-0 text-slate-600">
          {{ t("detail.noVersions") }}
        </p>
      </section>

      <ProjectBrownfieldSourceFlow
        v-if="project.mode === 'BROWNFIELD_ASSESSMENT'"
        :key="`${projectId}:brownfield-source`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectSandboxGovernanceFlow
        v-if="project.mode === 'BROWNFIELD_ASSESSMENT'"
        :key="`${projectId}:sandbox-governance`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectClarificationFlow
        :key="`${projectId}:${currentBrief?.version_number ?? 0}:clarification`"
        :project-id="projectId"
      />

      <ProjectTeamSelectionFlow
        id="studio-team"
        :key="`${projectId}:${currentBrief?.version_number ?? 0}:team`"
        :project-id="projectId"
      />

      <ProjectUserModelingFlow
        id="studio-twins"
        v-if="auth.accessToken"
        :key="`${projectId}:user-modeling`"
        :project-id="projectId"
        :access-token="auth.accessToken"
        :authorize="authorized"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectRequirementsFlow
        id="studio-requirements"
        :key="`${projectId}:${currentBrief?.version_number ?? 0}:requirements`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectDesignFlow
        id="studio-design"
        :key="`${projectId}:${currentBrief?.version_number ?? 0}:design`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectArchitectureFlow
        id="studio-architecture"
        :key="`${projectId}:${currentBrief?.version_number ?? 0}:architecture`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectSourceGeneration
        id="studio-source"
        v-if="project.mode === 'GREENFIELD_GENERATION'"
        :key="`${projectId}:source-generation`"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <ProjectWebPreview
        id="studio-preview"
        :project-id="projectId"
        :locale="locale === 'it' ? 'it' : 'en'"
      />

      <details class="rounded-2xl border border-slate-200 bg-white p-6">
        <summary class="cursor-pointer text-lg font-bold">
          {{
            locale === "it"
              ? "Sorgenti, autorizzazioni ed evidenze JVM"
              : "JVM sources, authorizations and evidence"
          }}
        </summary>
        <div class="mt-6 space-y-6">
          <ProjectJvmSourceReview
            :key="`${projectId}:${currentBrief?.version_number ?? 0}:jvm-source`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />

          <ProjectJvmEvidenceReview
            :key="`${projectId}:${currentBrief?.version_number ?? 0}:jvm-evidence`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />

          <ProjectExecutionLaunch
            :project-id="projectId"
            platform="jvm"
            :locale="locale === 'it' ? 'it' : 'en'"
          />
        </div>
      </details>

      <details class="rounded-2xl border border-slate-200 bg-white p-6">
        <summary class="cursor-pointer text-lg font-bold">
          {{
            locale === "it"
              ? "Sorgenti, autorizzazioni ed evidenze Web"
              : "Web sources, authorizations and evidence"
          }}
        </summary>
        <div class="mt-6 space-y-6">
          <ProjectWebSourceReview
            :key="`${projectId}:${currentBrief?.version_number ?? 0}:web-source`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />

          <ProjectWebEvidenceReview
            :key="`${projectId}:${currentBrief?.version_number ?? 0}:web-evidence`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />

          <ProjectExecutionLaunch
            :project-id="projectId"
            platform="web"
            :locale="locale === 'it' ? 'it' : 'en'"
          />
        </div>
      </details>

      <details class="rounded-2xl border border-slate-200 bg-white p-6">
        <summary class="cursor-pointer text-lg font-bold">
          {{ locale === "it" ? "Tracciabilità degli artefatti" : "Artifact traceability" }}
        </summary>
        <div class="mt-6">
          <ProjectArtifactGraph
            :key="`${projectId}:${currentBrief?.version_number ?? 0}:artifact-graph`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />
        </div>
      </details>
    </template>
  </main>
</template>
