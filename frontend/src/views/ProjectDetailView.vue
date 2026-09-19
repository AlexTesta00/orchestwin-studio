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
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import { useDesignStore } from "@/stores/design";
import { useAuthStore } from "@/stores/auth";
import { useClarificationStore } from "@/stores/clarification";
import { useArchitectureStore } from "@/stores/architecture";
import { useWebExecutionStore } from "@/stores/webExecution";
import { useJvmExecutionStore } from "@/stores/jvmExecution";

const route = useRoute();
const auth = useAuthStore();
const team = useTeamStore();
const modeling = useUserModelingStore();
const requirements = useRequirementsStore();
const design = useDesignStore();
const clarification = useClarificationStore();
const architecture = useArchitectureStore();
const web = useWebExecutionStore();
const jvm = useJvmExecutionStore();
// Reload downstream state when its approved inputs change on this page.
const briefContext = computed(() => `${currentBrief.value?.id}:${clarification.gate?.status}`);
const teamContext = computed(
  () => `${briefContext.value}:${team.currentVersion?.id}:${team.gate?.status}`,
);
const twinContext = computed(
  () => `${teamContext.value}:${modeling.currentSnapshot?.id}:${modeling.currentGate?.status}`,
);
const requirementsContext = computed(
  () => `${twinContext.value}:${requirements.current?.id}:${requirements.gate?.status}`,
);
const designContext = computed(
  () => `${requirementsContext.value}:${design.current?.id}:${design.gate?.status}`,
);

const { t, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      detail: {
        loading: "Loading project…",
        loadError: "The project could not be loaded.",
        saveError: "The Project Brief version could not be saved.",
        mode: "Mode",
        currentBrief: "Your idea",
        noBrief: "Describe what you would like to create to get started.",
        versionHistory: "Previous descriptions",
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
        currentBrief: "La tua idea",
        noBrief: "Descrivi cosa vuoi realizzare per iniziare.",
        versionHistory: "Descrizioni precedenti",
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
const selectedStage = ref<number | null>(null);
let projectEpoch = 0;

const projectId = computed(() => {
  const value = route.params.projectId ?? route.params.id;

  if (Array.isArray(value)) {
    return value[0] ?? "";
  }

  return value ?? "";
});

function approved(
  gate: { status: string; artifact: { artifact_id: string; content_hash: string } } | null,
  version: { id: string; content_hash: string } | null,
): boolean {
  return !!(
    gate?.status === "APPROVED" &&
    version &&
    gate.artifact.artifact_id === version.id &&
    gate.artifact.content_hash === version.content_hash
  );
}

const hasWebSource = computed(
  () => web.activeProjectId === projectId.value && web.currentSourceRevision !== null,
);
const hasJvmSource = computed(
  () => jvm.activeProjectId === projectId.value && jvm.currentSourceRevision !== null,
);
const completedStages = computed(() => [
  clarification.projectId === projectId.value && approved(clarification.gate, currentBrief.value),
  team.projectId === projectId.value &&
    team.readiness?.status === "READY_FOR_MAIN_WORKFLOW" &&
    team.currentVersion?.brief_version_number === currentBrief.value?.version_number &&
    team.currentVersion?.brief_content_hash === currentBrief.value?.content_hash &&
    approved(team.gate, team.currentVersion),
  modeling.projectId === projectId.value &&
    modeling.isReadyForRequirements &&
    approved(modeling.currentGate, modeling.currentSnapshot),
  requirements.projectId === projectId.value &&
    requirements.isReadyForDesign &&
    approved(requirements.gate, requirements.current),
  design.projectId === projectId.value &&
    design.isReadyForArchitecture &&
    approved(design.gate, design.current),
  architecture.projectId === projectId.value &&
    architecture.isReadyForImplementation &&
    approved(architecture.gate, architecture.current),
  hasWebSource.value || hasJvmSource.value,
]);
const currentStage = computed(() => {
  const incomplete = completedStages.value.findIndex((complete) => !complete);
  return incomplete < 0 ? 7 : incomplete;
});
const activeStage = computed(() =>
  Math.min(selectedStage.value ?? currentStage.value, currentStage.value),
);
const stageLabels = computed(() =>
  locale.value === "it"
    ? ["Idea", "Team", "Utenti", "Funzionalità", "Aspetto", "Soluzione", "Creazione", "Risultato"]
    : ["Idea", "Team", "Users", "Features", "Look & feel", "Solution", "Creation", "Result"],
);
const stageDescriptions = computed(() =>
  locale.value === "it"
    ? [
        "Racconta cosa vuoi realizzare e per chi.",
        "Scegli gli assistenti che lavoreranno al tuo progetto.",
        "Conosci i profili simulati delle persone che useranno il prodotto.",
        "Decidi cosa deve fare la tua applicazione.",
        "Esplora le schermate e scegli l’esperienza da realizzare.",
        "Rivedi come verrà costruita la soluzione.",
        "Trasforma le scelte approvate in una prima applicazione.",
        "Prova la tua applicazione e confrontala con le scelte fatte.",
      ]
    : [
        "Describe what you want to create and who it is for.",
        "Choose the assistants who will work on your project.",
        "Meet the simulated profiles of the people who will use your product.",
        "Decide what your application needs to do.",
        "Explore the screens and choose the experience to build.",
        "Review how your solution will be built.",
        "Turn your approved choices into a first application.",
        "Try your application and compare it with your choices.",
      ],
);
const visibleStages = computed(() => stageLabels.value.slice(0, currentStage.value + 1));
const activeVersion = computed(
  () =>
    [
      currentBrief.value?.version_number,
      team.currentVersion?.version_number,
      modeling.currentSnapshot?.version_number,
      requirements.current?.version_number,
      design.current?.version_number,
      architecture.current?.version_number,
      hasWebSource.value
        ? web.currentSourceRevision?.version_number
        : jvm.currentSourceRevision?.version_number,
    ][activeStage.value],
);

watch(currentStage, (next, previous) => {
  // Follow progress unless the owner deliberately revisited an earlier stage.
  if (
    selectedStage.value === previous ||
    (selectedStage.value !== null && selectedStage.value > next)
  ) {
    selectedStage.value = null;
  }
});

watch(
  () => [
    clarification.lastRoundAnswer?.brief_version,
    clarification.lastAssumptionDecision?.brief_version,
  ],
  (versions) => {
    for (const version of versions) {
      if (
        version?.project_id === projectId.value &&
        version.version_number > (currentBrief.value?.version_number ?? 0)
      ) {
        currentBrief.value = version;
        briefHistory.value = [
          ...briefHistory.value.filter((item) => item.id !== version.id),
          version,
        ];
      }
    }
  },
);

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
  selectedStage.value = null;
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
  <div class="studio-workspace mx-auto grid w-full max-w-5xl gap-5">
    <p v-if="loading" class="m-0 text-slate-700" aria-live="polite">{{ t("detail.loading") }}</p>
    <p
      v-else-if="errorDetail !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ errorDetail === "brief_save_failed" ? t("detail.saveError") : t("detail.loadError") }}
    </p>

    <template v-else-if="project !== null">
      <header
        class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 pb-4"
      >
        <div class="min-w-0 flex-1">
          <p class="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">
            {{ locale === "it" ? "Il tuo progetto" : "Your project" }}
          </p>
          <h1 class="m-0 text-xl font-bold tracking-tight text-slate-950 sm:text-2xl">
            {{ project.display_name }}
          </h1>
        </div>
        <span class="rounded-full bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700">
          {{ locale === "it" ? "L’AI propone, decidi tu" : "AI proposes, you decide" }}
        </span>
      </header>

      <nav
        class="flex flex-wrap gap-1.5"
        :aria-label="locale === 'it' ? 'Fasi del progetto' : 'Project stages'"
        data-testid="project-stage-navigation"
      >
        <button
          v-for="(label, index) in visibleStages"
          :key="index"
          type="button"
          :aria-current="activeStage === index ? 'step' : undefined"
          :aria-controls="`studio-stage-${index}`"
          :data-stage="index"
          class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          :class="
            activeStage === index
              ? 'border-slate-950 bg-slate-950 text-white'
              : 'border-slate-200 bg-white text-slate-600 hover:border-slate-400 hover:text-slate-950'
          "
          @click="selectedStage = index"
        >
          <span aria-hidden="true">{{ index < currentStage ? "✓" : `${index + 1}.` }}</span>
          {{ label }}
          <span v-if="index < currentStage" class="sr-only">{{
            locale === "it" ? "completato" : "completed"
          }}</span>
        </button>
      </nav>

      <div
        class="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-100 px-4 py-3"
        aria-live="polite"
      >
        <div class="min-w-0">
          <p class="m-0 text-sm text-slate-700">
            <strong>{{ stageLabels[activeStage] }}</strong>
            <span v-if="activeStage < currentStage">
              · {{ locale === "it" ? "Completato" : "Completed"
              }}<template v-if="activeVersion"> · v{{ activeVersion }}</template></span
            >
            <span v-else>
              ·
              {{
                locale === "it"
                  ? activeStage === 7
                    ? "Pronto da aprire"
                    : "Passaggio corrente"
                  : activeStage === 7
                    ? "Ready to open"
                    : "Current step"
              }}</span
            >
          </p>
          <p class="mt-1 mb-0 text-sm text-slate-500">{{ stageDescriptions[activeStage] }}</p>
        </div>
        <button
          v-if="activeStage < currentStage"
          type="button"
          class="text-sm font-semibold text-indigo-700 underline-offset-4 hover:underline"
          @click="selectedStage = null"
        >
          {{ locale === "it" ? "Continua con" : "Continue to" }} {{ stageLabels[currentStage] }} →
        </button>
        <span v-else-if="activeStage < 7" class="text-xs text-slate-500">{{
          locale === "it"
            ? "Il prossimo passaggio si sblocca dopo l’approvazione."
            : "The next step unlocks after approval."
        }}</span>
      </div>

      <!-- Keep the flows mounted: their read-only loaders hydrate saved work and their
           context keys refresh dependent approvals. Only the selected panel is exposed. -->
      <div
        id="studio-stage-0"
        v-show="activeStage === 0"
        class="grid gap-5"
        data-testid="stage-brief"
      >
        <section
          class="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5"
          aria-labelledby="current-brief-title"
        >
          <h2 id="current-brief-title" class="m-0 text-lg font-bold text-slate-950">
            {{ t("detail.currentBrief") }}
          </h2>
          <p v-if="currentBrief" class="m-0 text-sm leading-relaxed text-slate-600">
            {{ currentBrief.brief.description ?? currentBrief.brief.problem }}
          </p>
          <p v-else class="m-0 text-sm text-slate-600">{{ t("detail.noBrief") }}</p>
          <details :open="currentBrief === null">
            <summary class="cursor-pointer text-sm font-semibold text-indigo-700">
              {{
                locale === "it"
                  ? currentBrief
                    ? "Modifica la descrizione"
                    : "Descrivi la tua idea"
                  : currentBrief
                    ? "Edit description"
                    : "Describe your idea"
              }}
            </summary>
            <div class="mt-4">
              <ProjectBriefEditor
                :key="currentBrief?.version_number ?? 0"
                :initial="currentBrief?.brief ?? null"
                :busy="saving"
                @submit="saveBrief"
              />
            </div>
          </details>
          <details v-if="briefHistory.length" class="border-t border-slate-100 pt-3">
            <summary class="cursor-pointer text-xs font-semibold text-slate-500">
              {{ t("detail.versionHistory") }} ({{ briefHistory.length }})
            </summary>
            <ol class="mt-3 grid gap-2">
              <li
                v-for="version in briefHistory"
                :key="version.id"
                class="grid gap-1 rounded-lg bg-slate-50 p-3 text-xs text-slate-500"
              >
                <strong class="text-slate-700"
                  >{{ t("detail.version", { number: version.version_number }) }} ·
                  {{ formatDate(version.created_at) }}</strong
                >
                <code class="break-all">{{ version.content_hash }}</code>
              </li>
            </ol>
          </details>
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
          v-show="currentBrief !== null"
          :key="`${projectId}:${currentBrief?.version_number ?? 0}:clarification`"
          :project-id="projectId"
          :current-brief="currentBrief"
        />
      </div>
      <div id="studio-stage-1" v-show="activeStage === 1" data-testid="stage-team">
        <ProjectTeamSelectionFlow
          id="studio-team"
          :key="`${projectId}:${briefContext}:team`"
          :project-id="projectId"
        />
      </div>
      <div id="studio-stage-2" v-show="activeStage === 2" data-testid="stage-twins">
        <ProjectUserModelingFlow
          id="studio-twins"
          v-if="auth.accessToken"
          :key="`${projectId}:${teamContext}:user-modeling`"
          :project-id="projectId"
          :access-token="auth.accessToken"
          :authorize="authorized"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
      </div>
      <div id="studio-stage-3" v-show="activeStage === 3" data-testid="stage-requirements">
        <ProjectRequirementsFlow
          id="studio-requirements"
          :prerequisite-ready="modeling.isReadyForRequirements"
          :key="`${projectId}:${twinContext}:requirements`"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
      </div>
      <div id="studio-stage-4" v-show="activeStage === 4" data-testid="stage-design">
        <ProjectDesignFlow
          id="studio-design"
          @show-result="selectedStage = 7"
          :prerequisite-ready="requirements.isReadyForDesign"
          :key="`${projectId}:${requirementsContext}:design`"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
      </div>
      <div id="studio-stage-5" v-show="activeStage === 5" data-testid="stage-architecture">
        <ProjectArchitectureFlow
          id="studio-architecture"
          :prerequisite-ready="design.isReadyForArchitecture"
          :key="`${projectId}:${designContext}:architecture`"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
      </div>
      <div id="studio-stage-6" v-show="activeStage === 6" data-testid="stage-source">
        <ProjectSourceGeneration
          id="studio-source"
          v-if="project.mode === 'GREENFIELD_GENERATION'"
          :key="`${projectId}:source-generation`"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
        <p v-else class="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
          {{
            locale === "it"
              ? "Consulta i sorgenti importati e autorizza la verifica nei dettagli tecnici."
              : "Review imported sources and authorize verification in the technical details."
          }}
        </p>
      </div>
      <div
        id="studio-stage-7"
        v-show="activeStage === 7"
        class="grid gap-4"
        data-testid="stage-result"
      >
        <ProjectWebPreview
          id="studio-preview"
          v-show="hasWebSource"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
        <p
          v-if="hasJvmSource && !hasWebSource"
          class="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600"
        >
          {{
            locale === "it"
              ? "Sorgenti JVM disponibili. Apri i dettagli tecnici per revisionarli e autorizzarne l’esecuzione."
              : "JVM sources are available. Open technical details to review them and authorize execution."
          }}
        </p>
      </div>

      <details
        class="rounded-xl border border-slate-200 bg-white px-4 py-3"
        data-testid="technical-details"
      >
        <summary class="cursor-pointer text-sm font-semibold text-slate-600">
          {{ locale === "it" ? "Strumenti e dettagli del progetto" : "Project tools and details" }}
        </summary>
        <div class="mt-4 grid gap-4">
          <ModelRuntimeStatus :locale="locale === 'it' ? 'it' : 'en'" />
          <details class="rounded-xl border border-slate-200 p-4">
            <summary class="cursor-pointer text-sm font-semibold">
              {{
                locale === "it"
                  ? "Sorgenti, autorizzazioni ed evidenze Web"
                  : "Web sources, authorizations and evidence"
              }}
            </summary>
            <div class="mt-4 grid gap-4">
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
          <details class="rounded-xl border border-slate-200 p-4">
            <summary class="cursor-pointer text-sm font-semibold">
              {{
                locale === "it"
                  ? "Sorgenti, autorizzazioni ed evidenze JVM"
                  : "JVM sources, authorizations and evidence"
              }}
            </summary>
            <div class="mt-4 grid gap-4">
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
          <details class="rounded-xl border border-slate-200 p-4">
            <summary class="cursor-pointer text-sm font-semibold">
              {{ locale === "it" ? "Tracciabilità degli artefatti" : "Artifact traceability" }}
            </summary>
            <div class="mt-4">
              <ProjectArtifactGraph
                :key="`${projectId}:${currentBrief?.version_number ?? 0}:artifact-graph`"
                :project-id="projectId"
                :locale="locale === 'it' ? 'it' : 'en'"
              />
            </div>
          </details>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
/* A single compact work area; long review content still remains available inside its stage. */
.studio-workspace :deep(section.rounded-3xl) {
  border-radius: 1rem;
  padding: 1.25rem;
}
.studio-workspace :deep(h2) {
  font-size: 1.25rem;
  line-height: 1.5;
}
.studio-workspace :deep(h3) {
  font-size: 1rem;
  line-height: 1.5;
}
</style>
