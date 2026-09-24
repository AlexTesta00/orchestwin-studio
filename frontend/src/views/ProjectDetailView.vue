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
import ProjectArtifactGraph from "@/components/ProjectArtifactGraph.vue";
import ProjectBriefEditor from "@/components/ProjectBriefEditor.vue";
import ProjectClarificationFlow from "@/components/ProjectClarificationFlow.vue";
import ProjectDesignFlow from "@/components/ProjectDesignFlow.vue";
import ProjectRequirementsFlow from "@/components/ProjectRequirementsFlow.vue";
import ModelRuntimeStatus from "@/components/ModelRuntimeStatus.vue";
import ProjectUserModelingFlow from "@/components/ProjectUserModelingFlow.vue";
import TwinChatPanel from "@/components/TwinChatPanel.vue";
import ProjectTeamSelectionFlow from "@/components/ProjectTeamSelectionFlow.vue";
import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
import UiProgressBar from "@/components/UiProgressBar.vue";
import UiStateBlock from "@/components/UiStateBlock.vue";
import UiSidePanel from "@/components/UiSidePanel.vue";
import UiStepper, { type StepItem } from "@/components/UiStepper.vue";
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import { useDesignStore } from "@/stores/design";
import { useAuthStore } from "@/stores/auth";
import { useClarificationStore } from "@/stores/clarification";
import type { UserTwinVersionPayload } from "@/types/userModeling";

const route = useRoute();
const auth = useAuthStore();
const team = useTeamStore();
const modeling = useUserModelingStore();
const requirements = useRequirementsStore();
const design = useDesignStore();
const clarification = useClarificationStore();
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
        allProjects: "All projects",
        principle: "AI proposes, you decide",
        provenance: "Provenance",
        readOnly: "Step already closed. You can reread it, not change it.",
        backToCurrent: "Back to the current step",
        unlockHint: "The next step unlocks after your approval.",
        editBrief: "Edit the description",
        describeIdea: "Describe your idea",
        brownfieldSources:
          "Review the imported sources and authorise their verification in the technical details.",
        tools: "Project tools and technical details",
        webEvidence: "Web sources, authorisations and evidence",
        traceability: "Artifact traceability",
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
        allProjects: "Tutti i progetti",
        principle: "L'AI propone, decidi tu",
        provenance: "Provenienza",
        readOnly: "Passo già chiuso. Puoi rileggerlo, non modificarlo.",
        backToCurrent: "Torna al passo attuale",
        unlockHint: "Il passo successivo si sblocca dopo la tua approvazione.",
        editBrief: "Modifica la descrizione",
        describeIdea: "Descrivi la tua idea",
        brownfieldSources:
          "Consulta i sorgenti importati e autorizza la verifica nei dettagli tecnici.",
        tools: "Strumenti e dettagli tecnici del progetto",
        webEvidence: "Sorgenti, autorizzazioni ed evidenze Web",
        traceability: "Tracciabilità degli artefatti",
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
]);
const currentStage = computed(() => {
  const incomplete = completedStages.value.findIndex((complete) => !complete);
  return incomplete < 0 ? 4 : incomplete;
});
const activeStage = computed(() =>
  Math.min(selectedStage.value ?? currentStage.value, currentStage.value),
);
const stageLabels = computed(() =>
  locale.value === "it"
    ? [
        "Brief",
        "Squadra",
        "User Twin",
        "Requisiti",
        "Design",
      ]
    : [
        "Brief",
        "Team",
        "User Twins",
        "Requirements",
        "Design",
      ],
);
const stageDescriptions = computed(() =>
  locale.value === "it"
    ? [
        "Racconta cosa vuoi realizzare e per chi.",
        "Scegli gli assistenti che lavoreranno al tuo progetto.",
        "Conosci i profili simulati delle persone che useranno il prodotto.",
        "Decidi cosa deve fare la tua applicazione.",
        "Esplora le schermate e scegli l’esperienza da realizzare.",
      ]
    : [
        "Describe what you want to create and who it is for.",
        "Choose the assistants who will work on your project.",
        "Meet the simulated profiles of the people who will use your product.",
        "Decide what your application needs to do.",
        "Explore the screens and choose the experience to build.",
      ],
);
const stepItems = computed<StepItem[]>(() =>
  stageLabels.value.map((label, index) => ({
    key: `step-${index}`,
    label,
    index,
    status:
      index < currentStage.value
        ? "approved"
        : index === currentStage.value
          ? "current"
          : "pending",
  })),
);
const provenanceOpen = ref(false);
const chatTwin = ref<UserTwinVersionPayload | null>(null);

function selectStep(key: string): void {
  const index = Number(key.replace("step-", ""));
  selectedStage.value = index === currentStage.value ? null : index;
}

const activeVersion = computed(
  () =>
    [
      currentBrief.value?.version_number,
      team.currentVersion?.version_number,
      modeling.currentSnapshot?.version_number,
      requirements.current?.version_number,
      design.current?.version_number,
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
  <div class="studio-workspace mx-auto grid w-full gap-8 lg:grid-cols-[272px_minmax(0,1fr)]">
    <UiStateBlock
      v-if="loading"
      kind="loading"
      :title="t('detail.loading')"
      class="lg:col-span-2"
    />
    <UiStateBlock
      v-else-if="errorDetail !== null"
      kind="error"
      :title="errorDetail === 'brief_save_failed' ? t('detail.saveError') : t('detail.loadError')"
      class="lg:col-span-2"
    />

    <template v-else-if="project !== null">
      <aside class="grid content-start gap-5 lg:sticky lg:top-[76px] lg:self-start">
        <RouterLink
          class="inline-flex items-center gap-1.5 text-sm font-semibold text-action underline-offset-4 hover:underline"
          to="/projects"
        >
          <span aria-hidden="true">←</span>
          {{ t("detail.allProjects") }}
        </RouterLink>
        <div class="grid gap-1">
          <p class="m-0 text-[15px] font-semibold tracking-block">{{ project.display_name }}</p>
          <p class="m-0 font-mono text-[11px] text-ink-3">{{ t("detail.principle") }}</p>
        </div>
        <UiStepper :steps="stepItems" :active="`step-${activeStage}`" @select="selectStep" />
        <button
          type="button"
          class="inline-flex items-center gap-1.5 text-sm font-semibold text-action underline-offset-4 hover:underline"
          data-testid="open-provenance"
          @click="provenanceOpen = true"
        >
          {{ t("detail.provenance") }}
        </button>
      </aside>

      <div class="grid content-start gap-6">
        <header class="grid gap-3">
          <UiProgressBar :current="activeStage + 1" :reached="currentStage + 1" :total="5" />
          <h1 class="m-0 text-[34px] leading-[1.2] font-semibold tracking-title">
            {{ stageLabels[activeStage] }}
          </h1>
          <p class="m-0 text-[17px] leading-7 text-ink-2">{{ stageDescriptions[activeStage] }}</p>
        </header>

        <div
          v-if="activeStage < currentStage"
          class="flex flex-wrap items-center justify-between gap-3 rounded-panel border border-line-strong bg-surface-3 px-4 py-3"
          aria-live="polite"
        >
          <p class="m-0 text-sm text-ink-2">
            {{ t("detail.readOnly") }}
            <template v-if="activeVersion">
              <span class="font-mono text-xs text-ink-3">· v{{ activeVersion }}</span>
            </template>
          </p>
          <UiButton variant="secondary" data-testid="back-to-current" @click="selectedStage = null">
            {{ t("detail.backToCurrent") }}
          </UiButton>
        </div>
        <p v-else-if="activeStage < 4" class="m-0 font-mono text-xs text-ink-3" aria-live="polite">
          {{ t("detail.unlockHint") }}
        </p>

        <div
          id="studio-stage-0"
          v-show="activeStage === 0"
          class="grid gap-5"
          data-testid="stage-brief"
        >
          <UiCard>
            <h2 id="current-brief-title" class="m-0 text-2xl font-semibold tracking-card">
              {{ t("detail.currentBrief") }}
            </h2>
            <p v-if="currentBrief" class="mt-3 mb-0 text-[15px] leading-6 text-ink-2">
              {{ currentBrief.brief.description ?? currentBrief.brief.problem }}
            </p>
            <p v-else class="mt-3 mb-0 text-[15px] text-ink-2">{{ t("detail.noBrief") }}</p>
            <details class="mt-4" :open="currentBrief === null">
              <summary class="cursor-pointer text-sm font-semibold text-action">
                {{ currentBrief ? t("detail.editBrief") : t("detail.describeIdea") }}
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
            <details v-if="briefHistory.length" class="mt-4 border-t border-line-soft pt-3">
              <summary class="cursor-pointer font-mono text-xs text-ink-3">
                {{ t("detail.versionHistory") }} ({{ briefHistory.length }})
              </summary>
              <ol class="mt-3 grid gap-2">
                <li
                  v-for="version in briefHistory"
                  :key="version.id"
                  class="grid gap-1 rounded-panel bg-surface-2 p-3 text-xs text-ink-3"
                >
                  <strong class="text-ink-2"
                    >{{ t("detail.version", { number: version.version_number }) }} ·
                    {{ formatDate(version.created_at) }}</strong
                  >
                  <code class="font-mono break-all">{{ version.content_hash }}</code>
                </li>
              </ol>
            </details>
          </UiCard>
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
            @open-chat="chatTwin = $event"
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
            :prerequisite-ready="requirements.isReadyForDesign"
            :key="`${projectId}:${requirementsContext}:design`"
            :project-id="projectId"
            :locale="locale === 'it' ? 'it' : 'en'"
          />
        </div>
        <details
          class="rounded-panel border border-line bg-surface px-4 py-3"
          data-testid="technical-details"
        >
          <summary class="cursor-pointer text-sm font-semibold text-ink-2">
            {{ t("detail.tools") }}
          </summary>
          <div class="mt-4 grid gap-4">
            <ModelRuntimeStatus :locale="locale === 'it' ? 'it' : 'en'" />
          </div>
        </details>
      </div>
      <UiSidePanel
        :open="provenanceOpen"
        :title="t('detail.provenance')"
        @close="provenanceOpen = false"
      >
        <ProjectArtifactGraph
          v-if="provenanceOpen"
          :key="`${projectId}:${currentBrief?.version_number ?? 0}:artifact-graph`"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
      </UiSidePanel>
      <UiSidePanel
        :open="chatTwin !== null"
        :title="chatTwin ? t('twinChat.title', { name: chatTwin.profile.name }) : ''"
        @close="chatTwin = null"
      >
        <TwinChatPanel
          v-if="chatTwin"
          :key="chatTwin.id"
          :project-id="projectId"
          :twin="chatTwin"
          :authorize="authorized"
        />
      </UiSidePanel>
    </template>
  </div>
</template>

<style scoped>
.studio-workspace :deep(section.rounded-card) {
  border-radius: 18px;
  padding: 1.5rem;
}
.studio-workspace :deep(h2) {
  font-size: 1.5rem;
  line-height: 1.25;
  letter-spacing: -0.025em;
}
.studio-workspace :deep(h3) {
  font-size: 1.0625rem;
  line-height: 1.5;
}
</style>
