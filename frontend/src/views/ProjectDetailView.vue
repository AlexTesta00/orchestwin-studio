<script setup lang="ts">
import { computed, nextTick, onUnmounted, provide, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute } from "vue-router";

import { apiClient, ApiError } from "@/api/client";
import {
  PROJECT_STAGES,
  type ProjectBriefInput,
  type ProjectBriefVersionResponse,
  type ProjectResponse,
  type ProjectStage,
} from "@/api/contracts";
import { projectImportsApi } from "@/api/projectImports";
import { whyApi } from "@/api/why";
import { whyContextKey } from "@/components/whyContext";
import ProjectImportVerification from "@/components/ProjectImportVerification.vue";
import { projectImportResult } from "@/stores/projectImportResults";
import GeneratedMockupFrame from "@/components/GeneratedMockupFrame.vue";
import InsightBriefTray from "@/components/InsightBriefTray.vue";
import ProjectArtifactGraph from "@/components/ProjectArtifactGraph.vue";
import ProjectBriefDialogue from "@/components/ProjectBriefDialogue.vue";
import ProjectBriefEditor from "@/components/ProjectBriefEditor.vue";
import ProjectClarificationFlow from "@/components/ProjectClarificationFlow.vue";
import ProjectDesignFlow from "@/components/ProjectDesignFlow.vue";
import ProjectDesignPackagePanel from "@/components/ProjectDesignPackagePanel.vue";
import ProjectRequirementsFlow from "@/components/ProjectRequirementsFlow.vue";
import ModelRuntimeStatus from "@/components/ModelRuntimeStatus.vue";
import ProjectSectionsNotice from "@/components/ProjectSectionsNotice.vue";
import ProjectUserModelingFlow from "@/components/ProjectUserModelingFlow.vue";
import ProjectResearchEvidencePanel from "@/components/ProjectResearchEvidencePanel.vue";
import type { EvidenceFocus } from "@/types/humanValidation";
import TwinChatPanel from "@/components/TwinChatPanel.vue";
import ProjectTeamSelectionFlow from "@/components/ProjectTeamSelectionFlow.vue";
import UiButton from "@/components/UiButton.vue";
import UiStateBlock from "@/components/UiStateBlock.vue";
import UiSidePanel from "@/components/UiSidePanel.vue";
import UiStepHeader from "@/components/UiStepHeader.vue";
import UiStepper, {
  type StepItem,
  type StepSection,
  type StepStatus,
} from "@/components/UiStepper.vue";
import { surfaceKey, type SurfaceContext } from "@/components/UiSurface.vue";
import UiTechnicalDetails from "@/components/UiTechnicalDetails.vue";
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import { useDesignStore } from "@/stores/design";
import { useDesignMockupsStore } from "@/stores/designMockups";
import { useAuthStore } from "@/stores/auth";
import { useClarificationStore } from "@/stores/clarification";
import { useInsightTrayStore } from "@/stores/insightTray";
import { useKnowledgePackagesStore } from "@/stores/knowledgePackages";
import { useSectionsStore } from "@/stores/sections";
import type { ProjectImportOriginPayload } from "@/types/projectImports";
import type { SectionState, SectionsAlignmentPayload } from "@/types/sections";
import type { UserTwinVersionPayload } from "@/types/userModeling";

const SECTION_STATUSES: Readonly<Record<SectionState, StepStatus>> = {
  NOT_STARTED: "pending",
  IN_PROGRESS: "current",
  FINE: "approved",
  UPDATE_AVAILABLE: "approved",
  TO_UPDATE: "approved",
};
const SECTION_SEGMENTS: Readonly<Record<SectionState, string>> = {
  NOT_STARTED: "bg-on-night/14",
  IN_PROGRESS: "bg-on-night",
  FINE: "bg-petrol-on-night",
  UPDATE_AVAILABLE: "bg-petrol-on-night",
  TO_UPDATE: "bg-warn-on-night",
};
const APPROVED_STATES: ReadonlySet<SectionState> = new Set([
  "FINE",
  "UPDATE_AVAILABLE",
  "TO_UPDATE",
]);
const NO_SECTION: StepSection = { state: "NOT_STARTED", version: null };

const route = useRoute();
const auth = useAuthStore();
const team = useTeamStore();
const modeling = useUserModelingStore();
const requirements = useRequirementsStore();
const design = useDesignStore();
const clarification = useClarificationStore();
const tray = useInsightTrayStore();
const packages = useKnowledgePackagesStore();
const mockups = useDesignMockupsStore();
const sectionsStore = useSectionsStore();
const remounts = ref<readonly number[]>([0, 0, 0, 0, 0, 0]);
// Reload downstream state when its approved inputs change on this page.
const briefContext = computed(() =>
  briefKnown.value && clarificationSettled.value
    ? `${currentBrief.value?.id}:${clarification.gate?.status}`
    : null,
);
const teamContext = computed(() =>
  briefContext.value !== null && teamSettled.value
    ? `${briefContext.value}:${team.currentVersion?.id}:${team.gate?.status}`
    : null,
);
const twinContext = computed(() =>
  teamContext.value !== null && modelingSettled.value
    ? `${teamContext.value}:${modeling.currentSnapshot?.id}:${modeling.currentGate?.status}`
    : null,
);
const requirementsContext = computed(() =>
  twinContext.value !== null && requirementsSettled.value
    ? `${twinContext.value}:${requirements.current?.id}:${requirements.gate?.status}`
    : null,
);

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { t: tg } = useI18n({ useScope: "global" });
const { t, locale } = useI18n({
  useScope: "local",
  messages: {
    en: {
      detail: {
        loading: "Loading project…",
        loadError: "The project could not be loaded.",
        saveError: "The Project Brief version could not be saved.",
        allProjects: "All projects",
        principle: "AI proposes, you decide",
        readOnly:
          "You already approved this step: you can read it again. Any change makes a new version that you approve again.",
        readOnlyBrief:
          "You already approved the brief: you can read it again. If you change it, a new version is made that you approve again, and the steps after it need another look.",
        readOnlyTeam:
          "You already approved the perspectives: you can read them again. You can still switch on or off the ones left to your choice: every change you save makes a new version that you approve again.",
        readOnlyTwins:
          "You already approved the user twins: you can read them again and talk to them. If you correct a twin or reuse one from another project, a new version is made that you approve again.",
        readOnlyRequirements:
          "You already approved the requirements: you can read them again. If you change one, a new version is made that you approve again.",
        readOnlyDesign:
          "You already approved the design: you can read it again and try the mockup. If you change the choice or the design, a new version is made that you approve again.",
        packagePreview: "Preview of {code} · {title}",
        backToCurrent: "Back to the current step",
        editBrief: "Edit the brief yourself",
        describeIdea: "Describe your idea in the form",
        openDialogue: "Back to the dialogue with the analyst",
        showSteps: "All steps",
        showSections: "All sections",
        readyToDownload: "Ready to download",
        partialFolder: "Partial folder",
        packageAhead:
          "The project goes on at the {step} step: the folder holds only the steps approved so far.",
        techVersion: "Version {number}",
        techApproved: "approved by you",
        techPending: "waiting for your decision",
        techNone: "No version yet",
        hash: "Content hash",
        origin: "Knowledge folder",
        originValue: "{project}, version {version}",
        archiveHash: "Archive hash",
        briefVersions: "Brief versions",
        version: "Version {number} · {date}",
        provenance: "Open the provenance graph",
        provenanceTitle: "Provenance",
        projectDetails: "Project details",
        folderVersion: "Folder version {number}",
        noFolder: "No folder prepared yet",
        folderContents: "Contents",
        folderSummary:
          "{files} files · {steps} approved step | {files} files · {steps} approved steps",
      },
    },
    it: {
      detail: {
        loading: "Caricamento progetto…",
        loadError: "Non è stato possibile caricare il progetto.",
        saveError: "Non è stato possibile salvare la versione del Project Brief.",
        allProjects: "Tutti i progetti",
        principle: "L'AI propone, decidi tu",
        readOnly:
          "Hai già approvato questo passo: puoi rileggerlo. Ogni modifica crea una nuova versione da approvare di nuovo.",
        readOnlyBrief:
          "Hai già approvato il brief: puoi rileggerlo. Se lo modifichi nasce una nuova versione da approvare di nuovo, e i passi successivi andranno rivisti.",
        readOnlyTeam:
          "Hai già approvato le prospettive: puoi rileggerle. Puoi ancora attivare o togliere quelle a tua scelta: ogni cambio che salvi crea una nuova versione da approvare di nuovo.",
        readOnlyTwins:
          "Hai già approvato gli user twin: puoi rileggerli e parlarci. Se correggi un twin o ne riusi uno da un altro progetto, nasce una nuova versione da approvare di nuovo.",
        readOnlyRequirements:
          "Hai già approvato i requisiti: puoi rileggerli. Se ne modifichi uno, nasce una nuova versione da approvare di nuovo.",
        readOnlyDesign:
          "Hai già approvato il design: puoi rileggerlo e provare il mockup. Se cambi la scelta o il design, nasce una nuova versione da approvare di nuovo.",
        packagePreview: "Anteprima di {code} · {title}",
        backToCurrent: "Torna al passo attuale",
        editBrief: "Modifica il brief di persona",
        describeIdea: "Descrivi la tua idea nel modulo",
        openDialogue: "Torna al dialogo con l'analista",
        showSteps: "Tutti i passi",
        showSections: "Tutte le sezioni",
        readyToDownload: "Pronto da scaricare",
        partialFolder: "Cartella parziale",
        packageAhead:
          "Il progetto continua dal passo {step}: la cartella contiene solo i passi approvati finora.",
        techVersion: "Versione {number}",
        techApproved: "approvata da te",
        techPending: "in attesa della tua decisione",
        techNone: "Nessuna versione ancora",
        hash: "Hash del contenuto",
        origin: "Cartella di conoscenza",
        originValue: "{project}, versione {version}",
        archiveHash: "Hash dell'archivio",
        briefVersions: "Versioni del brief",
        version: "Versione {number} · {date}",
        provenance: "Apri il grafo della provenienza",
        provenanceTitle: "Provenienza",
        projectDetails: "Dettagli del progetto",
        folderVersion: "Cartella versione {number}",
        noFolder: "Nessuna cartella preparata",
        folderContents: "Contenuto",
        folderSummary:
          "{files} file · {steps} passo approvato | {files} file · {steps} passi approvati",
      },
    },
  },
});

const project = ref<ProjectResponse | null>(null);
const currentBrief = ref<ProjectBriefVersionResponse | null>(null);
const briefHistory = ref<readonly ProjectBriefVersionResponse[]>([]);
const importOrigin = ref<ProjectImportOriginPayload | null>(null);
let originSequence = 0;

const loading = ref(true);
const reloading = ref(false);
const briefReloads = ref(0);
const saving = ref(false);
const errorDetail = ref<string | null>(null);
const selectedStage = ref<number | null>(null);
const briefMode = ref<"dialogue" | "form" | null>(null);
const briefView = computed(
  () => briefMode.value ?? (currentBrief.value === null ? "dialogue" : "form"),
);
const stepsOpen = ref(false);
const editorOpen = ref(false);
let projectEpoch = 0;

function onDialogueActive(active: boolean): void {
  if (active && briefMode.value === null) briefMode.value = "dialogue";
}

async function onDialogueSynthesized(): Promise<void> {
  await reloadProject();
  briefMode.value = "form";
  onSectionsChanged();
}

const projectId = computed(() => {
  const value = route.params.projectId ?? route.params.id;

  if (Array.isArray(value)) {
    return value[0] ?? "";
  }

  return value ?? "";
});
const trayVisible = computed(() => tray.isVisible(projectId.value));
const importResult = computed(() => projectImportResult(projectId.value));
provide(whyContextKey, { projectId: () => projectId.value, authorize: authorized, api: whyApi });
const briefKnown = computed(() => !loading.value && !reloading.value && project.value !== null);

function settledOnPage(
  owner: () => string | null,
  busy: () => boolean,
  generation: () => number = () => 0,
) {
  const ran = ref(false);
  watch(
    () => owner() === projectId.value && busy(),
    (running) => {
      if (running) ran.value = true;
    },
    { flush: "sync", immediate: true },
  );
  watch(
    [projectId, generation],
    () => {
      ran.value = owner() === projectId.value && busy();
    },
    { flush: "sync" },
  );
  return computed(() => ran.value && owner() === projectId.value && !busy());
}

const clarificationSettled = settledOnPage(
  () => clarification.projectId,
  () => clarification.busy,
);
const teamSettled = settledOnPage(
  () => team.projectId,
  () => team.busy,
);
const modelingSettled = settledOnPage(
  () => modeling.projectId,
  () => modeling.isBusy,
  () => remounts.value[2] ?? 0,
);
const requirementsSettled = settledOnPage(
  () => requirements.projectId,
  () => requirements.isBusy,
  () => remounts.value[3] ?? 0,
);

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

const designApproved = computed(
  () =>
    design.projectId === projectId.value &&
    design.isReadyForArchitecture &&
    approved(design.gate, design.current),
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
  designApproved.value,
  designApproved.value,
]);
const currentStage = computed(() => {
  const incomplete = completedStages.value.findIndex((complete) => !complete);
  return incomplete < 0 ? 5 : incomplete;
});
const packageOpen = computed(() => completedStages.value[0] === true);
const sectionsData = computed(() =>
  sectionsStore.projectId === projectId.value ? sectionsStore.sections : null,
);
const sectionsMode = computed(() => sectionsData.value?.first_pass_complete === true);
const evidenceReviewSections = computed<ReadonlySet<ProjectStage>>(
  () =>
    new Set(
      (sectionsData.value?.sections ?? [])
        .filter(
          (section) =>
            section.state !== "NOT_STARTED" &&
            section.version_number !== null &&
            Object.values(section.affected_codes ?? {}).some((codes) => codes.length > 0),
        )
        .map((section) => section.key),
    ),
);
const evidenceReviewNotice = computed(() => evidenceReviewSections.value.size > 0);
const sectionSteps = computed<StepSection[]>(() =>
  PROJECT_STAGES.map((key) => {
    const section = sectionsData.value?.sections.find((item) => item.key === key);
    return section === undefined
      ? NO_SECTION
      : { state: section.state, version: section.version_number };
  }),
);
const defaultSection = computed(() => {
  const states = sectionSteps.value.map((section) => section.state);
  const waiting = states.indexOf("IN_PROGRESS");
  if (waiting >= 0) return waiting;
  const behind = states.indexOf("TO_UPDATE");
  return behind >= 0 ? behind : 5;
});
const activeStage = computed(() => {
  if (sectionsMode.value) {
    return selectedStage.value ?? defaultSection.value;
  }
  if (selectedStage.value === 5 && packageOpen.value) {
    return 5;
  }
  return Math.min(selectedStage.value ?? currentStage.value, currentStage.value);
});
const activeKey = computed<ProjectStage>(() => PROJECT_STAGES[activeStage.value] ?? "PACKAGE");
const activeSection = computed(() => sectionSteps.value[activeStage.value] ?? NO_SECTION);
const activeSectionShown = computed(
  () => sectionsMode.value || evidenceReviewSections.value.has(activeKey.value),
);
const stageLabels = computed(() =>
  locale.value === "it"
    ? ["Brief", "Prospettive", "User Twin", "Definizione", "Design e valutazione", "Dossier"]
    : ["Brief", "Perspectives", "User Twin", "Definition", "Design & Evaluation", "Dossier"],
);
const stageDescriptions = computed(() =>
  locale.value === "it"
    ? [
        "Racconta cosa vuoi realizzare e per chi. Quello che manca arriva come proposta: decidi tu se tenerla.",
        "Le competenze con cui guardare il tuo progetto: ognuna porta le sue considerazioni quando si scrivono requisiti e design.",
        "I profili simulati delle persone che useranno il prodotto. Confermali, correggili, parlaci.",
        "Che cosa deve fare la tua applicazione, per chi, e come controlleremo che lo faccia.",
        "Le alternative, i mockup e il parere dei twin.",
        "La cartella con tutto ciò che hai approvato.",
      ]
    : [
        "Tell what you want to build and for whom. What is missing arrives as a proposal: you decide whether to keep it.",
        "The competences through which your project is looked at: each one adds its considerations when the requirements and the design are written.",
        "The simulated profiles of the people who will use the product. Confirm them, correct them, talk to them.",
        "What your application must do, for whom, and how we will check that it does.",
        "The alternatives, the mockups and what the twins say.",
        "The folder with everything you approved.",
      ],
);
const stepItems = computed<StepItem[]>(() =>
  stageLabels.value.map((label, index) => {
    if (sectionsMode.value) {
      const section = sectionSteps.value[index] ?? NO_SECTION;
      return {
        key: `step-${index}`,
        label,
        index,
        status: SECTION_STATUSES[section.state],
        section,
      };
    }
    const status: StepStatus =
      index < currentStage.value
        ? "approved"
        : index === currentStage.value
          ? "current"
          : "pending";
    const item: StepItem = { key: `step-${index}`, label, index, status };
    if (index === 5 && status === "current") item.note = t("detail.readyToDownload");
    if (index === 5 && status === "pending" && packageOpen.value) {
      item.open = true;
      item.note = t("detail.partialFolder");
    }
    const key = PROJECT_STAGES[index];
    if (key !== undefined && evidenceReviewSections.value.has(key)) {
      const section = sectionSteps.value[index] ?? NO_SECTION;
      if (index <= currentStage.value || (index === 5 && packageOpen.value)) {
        item.section = section;
        if (index === 5 && !designApproved.value) {
          item.label = `${label} · ${t("detail.partialFolder")}`;
        }
      } else {
        item.note = tg(`ui.sections.states.${section.state}`);
      }
    }
    return item;
  }),
);
const headerStatus = computed<StepStatus>(() => {
  if (activeStage.value === currentStage.value) {
    return "current";
  }
  return activeStage.value < currentStage.value ? "approved" : "pending";
});
const readOnlyText = computed(() =>
  t(
    [
      "detail.readOnlyBrief",
      "detail.readOnlyTeam",
      "detail.readOnlyTwins",
      "detail.readOnlyRequirements",
      "detail.readOnlyDesign",
    ][activeStage.value] ?? "detail.readOnly",
  ),
);
const provenanceOpen = ref(false);
const chatTwin = ref<UserTwinVersionPayload | null>(null);

function segmentClass(index: number): string {
  const key = PROJECT_STAGES[index];
  if (sectionsMode.value || (key !== undefined && evidenceReviewSections.value.has(key))) {
    return SECTION_SEGMENTS[(sectionSteps.value[index] ?? NO_SECTION).state];
  }
  if (index < currentStage.value) return "bg-petrol-on-night";
  if (index === currentStage.value) return "bg-on-night";
  return "bg-on-night/14";
}

function selectStep(key: string): void {
  const index = Number(key.replace("step-", ""));
  const followed = sectionsMode.value ? defaultSection.value : currentStage.value;
  selectedStage.value = index === followed ? null : index;
  stepsOpen.value = false;
}

function openSection(key: ProjectStage): void {
  selectStep(`step-${PROJECT_STAGES.indexOf(key)}`);
}

function remountFrom(stage: number): void {
  remounts.value = remounts.value.map((count, index) => (index >= stage ? count + 1 : count));
}

function firstAligned(result: SectionsAlignmentPayload): number | null {
  const stages = result.results
    .filter((item) => item.outcome === "ALIGNED")
    .map((item) => PROJECT_STAGES.indexOf(item.key));
  return stages.length === 0 ? null : Math.min(...stages);
}

const stageVersions = computed(() => [
  currentBrief.value?.version_number,
  team.currentVersion?.version_number,
  modeling.currentSnapshot?.version_number,
  requirements.current?.version_number,
  design.current?.version_number,
  design.current?.version_number,
]);
const activeVersion = computed(() => stageVersions.value[activeStage.value]);
const stageSummaries = computed(() =>
  stageLabels.value.slice(0, 5).map((label, index) => ({
    label,
    version: stageVersions.value[index] ?? null,
    approved: completedStages.value[index] === true,
  })),
);
const stageArtifacts = computed(() => {
  const id = projectId.value;
  const designVersion = design.projectId === id ? design.current : null;
  return [
    currentBrief.value,
    team.projectId === id ? team.currentVersion : null,
    modeling.projectId === id ? modeling.currentSnapshot : null,
    requirements.projectId === id ? requirements.current : null,
    designVersion,
    designVersion,
  ];
});
const latestFolder = computed(() =>
  packages.projectId === projectId.value ? packages.latest : null,
);
const chosenGenerated = computed(() => {
  const version = design.projectId === projectId.value ? design.current : null;
  if (version === null || !version.package?.generated_mockup) {
    return null;
  }
  const alternativeId = version.package.owner_selected_alternative_id;
  const alternative = version.package.alternatives.find((item) => item.id === alternativeId);
  return alternative === undefined ? null : { version, alternative };
});
const packagePreview = computed(() => {
  const chosen = chosenGenerated.value;
  if (chosen === null || mockups.projectId !== projectId.value) {
    return null;
  }
  const document = mockups.documentFor(chosen.alternative.id, { source: "applied" });
  return document === null
    ? null
    : {
        html: document.html,
        title: t("detail.packagePreview", {
          code: chosen.alternative.code,
          title: chosen.alternative.title,
        }),
      };
});
const technicalSummary = computed(() => {
  if (activeStage.value === 5) {
    const folder = latestFolder.value;
    return folder === null
      ? t("detail.noFolder")
      : t("detail.folderVersion", { number: folder.version_number });
  }
  const version = activeVersion.value;
  if (version === undefined || version === null) return t("detail.techNone");
  const approvedNow = sectionsMode.value
    ? APPROVED_STATES.has(activeSection.value.state)
    : completedStages.value[activeStage.value];
  const state = approvedNow ? t("detail.techApproved") : t("detail.techPending");
  return `${t("detail.techVersion", { number: version })} · ${state}`;
});
const technicalRows = computed(() => {
  const rows: { label: string; value: string }[] = [];
  if (activeStage.value === 5) {
    const folder = latestFolder.value;
    if (folder !== null) {
      rows.push({ label: t("detail.hash"), value: folder.content_hash });
      rows.push({ label: t("detail.archiveHash"), value: folder.archive_hash });
      rows.push({
        label: t("detail.folderContents"),
        value: t(
          "detail.folderSummary",
          { files: folder.file_count, steps: folder.stages.length },
          folder.stages.length,
        ),
      });
    }
    return rows;
  }
  const artifact = stageArtifacts.value[activeStage.value];
  if (artifact) rows.push({ label: t("detail.hash"), value: artifact.content_hash });
  return rows;
});
const projectRows = computed(() => {
  const origin = importOrigin.value;
  if (origin === null) return [];
  return [
    {
      label: t("detail.origin"),
      value: t("detail.originValue", {
        project: origin.origin.project_name,
        version: origin.origin.package_version,
      }),
    },
    { label: t("detail.archiveHash"), value: origin.archive_hash },
  ];
});

watch(currentStage, (next, previous) => {
  // Follow progress unless the owner deliberately revisited an earlier stage.
  if (sectionsMode.value || (selectedStage.value === 5 && packageOpen.value)) {
    return;
  }
  if (
    selectedStage.value === previous ||
    (selectedStage.value !== null && selectedStage.value > next)
  ) {
    selectedStage.value = null;
  }
});

watch(
  () => [clarification.lastAssumptionDecision?.brief_version],
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

watch(
  () => currentBrief.value?.version_number,
  () => {
    editorOpen.value = false;
  },
);

watch(
  () => tray.resultOf(projectId.value)?.briefVersionNumber ?? null,
  (version) => {
    if (version !== null && version > (currentBrief.value?.version_number ?? 0)) {
      void refreshBrief().then(onSectionsChanged);
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
  briefMode.value = null;
  project.value = null;
  currentBrief.value = null;
  briefHistory.value = [];
  reloading.value = false;
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

async function reloadProject(): Promise<void> {
  const id = projectId.value;
  const epoch = ++projectEpoch;
  reloading.value = true;
  errorDetail.value = null;

  try {
    const [projectResult, versions] = await Promise.all([
      authorized((accessToken) => apiClient.getProject(accessToken, id)),
      authorized((accessToken) => apiClient.listBriefVersions(accessToken, id)),
    ]);
    if (epoch !== projectEpoch) return;
    selectedStage.value = sectionsMode.value ? 0 : null;
    briefMode.value = null;
    project.value = projectResult;
    briefHistory.value = [...versions];
    currentBrief.value = versions[versions.length - 1] ?? null;
    briefReloads.value += 1;
  } catch (error: unknown) {
    if (epoch === projectEpoch) errorDetail.value = errorCode(error, "project_load_failed");
  } finally {
    if (epoch === projectEpoch) reloading.value = false;
  }
}

async function refreshBrief(): Promise<void> {
  const id = projectId.value;
  const epoch = projectEpoch;
  try {
    const versions = await authorized((accessToken) =>
      apiClient.listBriefVersions(accessToken, id),
    );
    if (epoch !== projectEpoch) return;
    briefHistory.value = [...versions];
    currentBrief.value = versions[versions.length - 1] ?? null;
  } catch {
    if (epoch === projectEpoch) await loadProject();
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
    if (epoch === projectEpoch) {
      await reloadProject();
      onSectionsChanged();
    }
  } catch (error: unknown) {
    if (epoch === projectEpoch) errorDetail.value = errorCode(error, "brief_save_failed");
  } finally {
    saving.value = false;
  }
}

async function loadImportOrigin(): Promise<void> {
  const id = projectId.value;
  const sequence = ++originSequence;
  importOrigin.value = null;
  if (!id) return;

  const request = authorized((accessToken) => projectImportsApi.origin(id, accessToken));
  const origin = await request.catch(() => null);
  if (sequence === originSequence) importOrigin.value = origin;
}

async function refreshSections(): Promise<void> {
  const id = projectId.value;
  if (!id) return;
  await sectionsStore.read(id, authorized).catch(() => null);
}

function onSectionsChanged(): void {
  sectionsStore.clearAlignment();
  void refreshSections();
}

async function onEvidenceChanged(): Promise<void> {
  const id = projectId.value;
  if (!id) return;
  await authorized((token) => modeling.load(id, token)).catch(() => null);
  if (id === projectId.value) {
    validationRefreshKey.value += 1;
    onSectionsChanged();
  }
}

const evidenceFocus = ref<EvidenceFocus | null>(null);
const validationRefreshKey = ref(0);
async function openValidationEvidence(source: EvidenceFocus | null): Promise<void> {
  evidenceFocus.value = source;
  selectedStage.value = 2;
  await nextTick();
  const target = window.document.querySelector<HTMLElement>(
    '[data-testid="research-evidence-panel"]',
  );
  target?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

async function alignSections(): Promise<void> {
  const id = projectId.value;
  if (!id || sectionsStore.pending.align) return;
  selectedStage.value = activeStage.value;
  const result = await sectionsStore.align(id, authorized).catch(() => null);
  if (result === null || id !== projectId.value) return;
  const first = firstAligned(result);
  if (first !== null) remountFrom(first);
  await refreshSections();
}

const stagesRoot = ref<HTMLElement | null>(null);
const technicalRow = ref<HTMLElement | null>(null);
const stageOwnDetails = ref<readonly boolean[]>([]);
const stepRowPlaced = ref(false);
let stageDetailsObserver: MutationObserver | null = null;

function scanStageDetails(): void {
  const root = stagesRoot.value;
  const next = Array.from({ length: 6 }, (_, index) =>
    Boolean(root?.querySelector(`#studio-stage-${index} [data-testid="step-technical-details"]`)),
  );
  if (next.some((value, index) => value !== stageOwnDetails.value[index])) {
    stageOwnDetails.value = next;
  }
  const placed = Boolean(
    technicalRow.value?.querySelector('[data-testid="step-technical-details"]'),
  );
  if (stepRowPlaced.value !== placed) {
    stepRowPlaced.value = placed;
  }
}

const pageDetailsVisible = computed(
  () =>
    project.value !== null &&
    stageOwnDetails.value[activeStage.value] !== true &&
    !stepRowPlaced.value,
);

watch([stagesRoot, technicalRow], ([root, row]) => {
  stageDetailsObserver?.disconnect();
  stageDetailsObserver = null;
  scanStageDetails();
  if (typeof MutationObserver === "undefined") return;
  stageDetailsObserver = new MutationObserver(scanStageDetails);
  for (const element of [root, row]) {
    if (element !== null) {
      stageDetailsObserver.observe(element, { childList: true, subtree: true });
    }
  }
});

watch(
  () =>
    [
      activeStage.value === 5 && designApproved.value,
      chosenGenerated.value?.version.content_hash,
      mockups.projectId === projectId.value,
      mockups.design?.contentHash,
    ] as const,
  ([packageShown, contentHash, active, drawnFor]) => {
    const chosen = chosenGenerated.value;
    if (!packageShown || contentHash === undefined || !active || chosen === null) return;
    if (drawnFor !== contentHash) return;
    if (mockups.documentFor(chosen.alternative.id, { source: "applied" }) !== null) return;
    void mockups
      .loadDocument(chosen.alternative.id, authorized, { source: "applied" })
      .catch(() => undefined);
  },
  { immediate: true },
);

watch(projectId, loadProject, { immediate: true });
watch(projectId, loadImportOrigin, { immediate: true });
watch(projectId, refreshSections, { immediate: true });
onUnmounted(() => {
  projectEpoch++;
  originSequence++;
  stageDetailsObserver?.disconnect();
});
</script>

<template>
  <div
    class="relative mx-auto grid w-full gap-x-12 gap-y-6 rounded-stage bg-night px-5 pt-6 text-on-night sm:px-8 sm:pt-10 lg:grid-cols-[260px_minmax(0,1fr)] lg:items-start lg:px-[clamp(24px,4vw,56px)]"
    data-surface="night"
    data-testid="project-workspace"
  >
    <aside v-if="project !== null" class="flex min-w-0 flex-col lg:sticky lg:top-24">
      <RouterLink
        class="inline-flex min-h-11 items-center gap-1.5 self-start text-sm font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
        to="/projects"
      >
        <span aria-hidden="true">←</span>
        {{ t("detail.allProjects") }}
      </RouterLink>
      <div class="pt-1 pb-5">
        <p class="text-lg leading-tight font-semibold tracking-block text-on-night">
          {{ project.display_name }}
        </p>
        <p class="mt-1 text-[13px] text-on-night-3">{{ t("detail.principle") }}</p>
      </div>
      <button
        type="button"
        class="mb-3 grid min-h-11 w-full gap-2.5 rounded-field border border-night-line bg-night-raised px-4 py-3 text-left transition-colors duration-150 hover:bg-night-hover lg:hidden"
        :aria-expanded="stepsOpen ? 'true' : 'false'"
        aria-controls="project-steps"
        data-testid="project-steps-toggle"
        @click="stepsOpen = !stepsOpen"
      >
        <span class="flex items-center justify-between gap-3">
          <span class="text-[15px] font-semibold text-on-night">
            {{ sectionsMode ? t("detail.showSections") : t("detail.showSteps") }}
          </span>
          <span
            aria-hidden="true"
            :class="[
              'mr-1 inline-block h-2 w-2 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150',
              stepsOpen ? 'translate-y-0.5 -rotate-135' : '-translate-y-0.5 rotate-45',
            ]"
          />
        </span>
        <span class="flex gap-1" aria-hidden="true">
          <span
            v-for="(item, index) in stepItems"
            :key="item.key"
            :class="['h-1 flex-1 rounded-[2px]', segmentClass(index)]"
          />
        </span>
      </button>
      <div id="project-steps" :class="stepsOpen ? '' : 'max-lg:hidden'">
        <UiStepper :steps="stepItems" :active="`step-${activeStage}`" @select="selectStep" />
      </div>
    </aside>

    <div class="min-w-0 pb-16 lg:pb-24" :class="{ 'lg:col-span-2': project === null }">
      <UiStateBlock v-if="loading" kind="loading" :title="t('detail.loading')" />
      <UiStateBlock
        v-else-if="errorDetail !== null"
        kind="error"
        :title="errorDetail === 'brief_save_failed' ? t('detail.saveError') : t('detail.loadError')"
      />

      <template v-else-if="project !== null">
        <UiStepHeader
          :step="activeStage + 1"
          :total="6"
          :title="stageLabels[activeStage] ?? ''"
          :description="stageDescriptions[activeStage]"
          :status="activeSectionShown ? undefined : headerStatus"
          :section="activeSectionShown ? activeSection : undefined"
        />
        <p
          v-if="importOrigin"
          class="mt-4 max-w-[720px] rounded-field border border-petrol-on-night/35 bg-petrol-on-night/8 px-4 py-3 text-sm leading-normal text-on-night-2"
          data-testid="project-import-origin"
        >
          {{
            tg("projects.detail.importedFrom", {
              project: importOrigin.origin.project_name,
              version: importOrigin.origin.package_version,
            })
          }}
        </p>

        <ProjectImportVerification
          v-if="
            importResult ||
            importOrigin?.import_limits?.length ||
            importOrigin?.omitted_sections?.length
          "
          :result="importResult"
          :origin="importOrigin ?? undefined"
          :locale="locale === 'it' ? 'it' : 'en'"
        />
        <ProjectSectionsNotice
          v-if="(sectionsMode || evidenceReviewNotice) && sectionsData !== null"
          :sections="sectionsData"
          :labels="stageLabels"
          :open-key="activeKey"
          :locale="locale === 'it' ? 'it' : 'en'"
          :busy="sectionsStore.pending.align"
          :result="sectionsStore.alignment"
          :failed="sectionsStore.alignmentFailure !== null"
          @align="alignSections"
          @open="openSection"
        />
        <div
          v-if="!sectionsMode && activeStage < currentStage"
          class="mt-7 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-panel border border-night-line bg-night-raised py-3 pr-3 pl-5"
          aria-live="polite"
          data-testid="step-read-only"
        >
          <p class="min-w-[min(100%,16rem)] flex-1 text-[15px] leading-normal text-on-night-3">
            {{ readOnlyText }}
          </p>
          <UiButton variant="outline" data-testid="back-to-current" @click="selectedStage = null">
            {{ t("detail.backToCurrent") }}
          </UiButton>
        </div>
        <div
          v-else-if="!sectionsMode && activeStage > currentStage"
          class="mt-7 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-panel border border-night-line bg-night-raised py-3 pr-3 pl-5"
          aria-live="polite"
          data-testid="step-ahead"
        >
          <p class="min-w-[min(100%,16rem)] flex-1 text-[15px] leading-normal text-on-night-3">
            {{ t("detail.packageAhead", { step: stageLabels[currentStage] ?? "" }) }}
          </p>
          <UiButton variant="outline" data-testid="back-to-current" @click="selectedStage = null">
            {{ t("detail.backToCurrent") }}
          </UiButton>
        </div>

        <div ref="stagesRoot" class="mt-7">
          <div
            id="studio-stage-0"
            v-show="activeStage === 0"
            class="flex min-w-0 flex-col gap-6"
            data-testid="stage-brief"
          >
            <ProjectBriefDialogue
              v-show="briefView === 'dialogue'"
              :key="`${projectId}:${briefReloads}:brief-dialogue`"
              :project-id="projectId"
              :current-brief="currentBrief"
              :authorize="authorized"
              @active="onDialogueActive"
              @synthesized="onDialogueSynthesized"
              @open-form="briefMode = 'form'"
              @unavailable="briefMode = 'form'"
            />
            <template v-if="briefView === 'form'">
              <ProjectClarificationFlow
                v-if="currentBrief !== null"
                :key="`${projectId}:${currentBrief.version_number}:clarification`"
                :project-id="projectId"
                :current-brief="currentBrief"
                :history="briefHistory"
                :active="activeStage === 0"
                :sections-mode="sectionsMode"
                @sections-changed="onSectionsChanged"
              />
              <div
                v-if="currentBrief !== null || !completedStages[0]"
                class="flex flex-wrap items-center gap-x-6"
              >
                <button
                  v-if="currentBrief !== null"
                  type="button"
                  class="group inline-flex min-h-11 items-center gap-2.5 text-sm font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
                  :aria-expanded="editorOpen ? 'true' : 'false'"
                  aria-controls="brief-editor-panel"
                  data-testid="brief-edit-toggle"
                  @click="editorOpen = !editorOpen"
                >
                  <span
                    aria-hidden="true"
                    :class="[
                      'inline-block h-1.5 w-1.5 shrink-0 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150',
                      editorOpen ? 'rotate-45' : '-rotate-45',
                    ]"
                  />
                  {{ t("detail.editBrief") }}
                </button>
                <button
                  v-if="!completedStages[0]"
                  type="button"
                  class="inline-flex min-h-11 items-center text-sm font-semibold text-on-night-3 underline-offset-4 hover:text-on-night hover:underline"
                  data-testid="brief-open-dialogue"
                  @click="briefMode = 'dialogue'"
                >
                  {{ t("detail.openDialogue") }}
                </button>
              </div>
              <section
                id="brief-editor-panel"
                v-show="currentBrief === null || editorOpen"
                class="rounded-tile border border-night-line bg-night-raised px-5 py-6 sm:p-7"
                aria-labelledby="brief-editor-title"
                data-testid="brief-editor"
              >
                <h2
                  id="brief-editor-title"
                  class="mb-5 text-[22px] leading-tight font-semibold tracking-block text-on-night"
                >
                  {{ currentBrief ? t("detail.editBrief") : t("detail.describeIdea") }}
                </h2>
                <ProjectBriefEditor
                  :key="currentBrief?.version_number ?? 0"
                  :initial="currentBrief?.brief ?? null"
                  :busy="saving"
                  @submit="saveBrief"
                />
              </section>
            </template>
          </div>
          <div id="studio-stage-1" v-show="activeStage === 1" data-testid="stage-team">
            <ProjectTeamSelectionFlow
              id="studio-team"
              :key="`${projectId}:team`"
              :project-id="projectId"
              :upstream="briefContext"
              :active="activeStage === 1"
              :sections-mode="sectionsMode"
              @sections-changed="onSectionsChanged"
            />
          </div>
          <div id="studio-stage-2" v-show="activeStage === 2" data-testid="stage-twins">
            <ProjectUserModelingFlow
              id="studio-twins"
              v-if="auth.accessToken"
              :key="`${projectId}:user-modeling:${remounts[2]}`"
              :project-id="projectId"
              :access-token="auth.accessToken"
              :authorize="authorized"
              :locale="locale === 'it' ? 'it' : 'en'"
              :upstream="teamContext"
              :active="activeStage === 2"
              :sections-mode="sectionsMode"
              @open-chat="chatTwin = $event"
              @sections-changed="onSectionsChanged"
            />
            <ProjectResearchEvidencePanel
              v-if="auth.accessToken"
              :key="`${projectId}:evidence`"
              :project-id="projectId"
              :authorize="authorized"
              :twins="
                modeling.currentTwins.map((twin) => ({ id: twin.twin_id, name: twin.profile.name }))
              "
              :ready="modeling.isCurrentSnapshotApproved"
              :active="activeStage === 2"
              :focus-source="evidenceFocus"
              :locale="locale === 'it' ? 'it' : 'en'"
              @changed="onEvidenceChanged"
            />
          </div>
          <div id="studio-stage-3" v-show="activeStage === 3" data-testid="stage-requirements">
            <ProjectRequirementsFlow
              id="studio-requirements"
              :prerequisite-ready="modeling.isReadyForRequirements"
              :key="`${projectId}:requirements:${remounts[3]}`"
              :project-id="projectId"
              :locale="locale === 'it' ? 'it' : 'en'"
              :upstream="twinContext"
              :active="activeStage === 3"
              :sections-mode="sectionsMode"
              @sections-changed="onSectionsChanged"
            />
          </div>
          <div id="studio-stage-4" v-show="activeStage === 4" data-testid="stage-design">
            <ProjectDesignFlow
              id="studio-design"
              :prerequisite-ready="requirements.isReadyForDesign"
              :key="`${projectId}:design:${remounts[4]}`"
              :project-id="projectId"
              :locale="locale === 'it' ? 'it' : 'en'"
              :upstream="requirementsContext"
              :validation-refresh-key="validationRefreshKey"
              :active="activeStage === 4"
              :sections-mode="sectionsMode"
              @sections-changed="onSectionsChanged"
              @open-evidence="openValidationEvidence"
            />
          </div>
          <div id="studio-stage-5" v-show="activeStage === 5" data-testid="stage-package">
            <ProjectDesignPackagePanel
              id="studio-package"
              :key="`${projectId}:package:${remounts[5]}`"
              :project-id="projectId"
              :stages="stageSummaries"
              :authorize="authorized"
              :locale="locale === 'it' ? 'it' : 'en'"
              :sections-mode="sectionsMode"
              @sections-changed="onSectionsChanged"
            >
              <template v-if="packagePreview !== null" #preview>
                <GeneratedMockupFrame
                  :html="packagePreview.html"
                  :title="packagePreview.title"
                  :interactive="false"
                  data-testid="package-preview-generated"
                />
              </template>
            </ProjectDesignPackagePanel>
          </div>
        </div>
      </template>

      <div class="sticky bottom-4 z-30 flex flex-col" data-testid="step-dock">
        <InsightBriefTray
          v-if="projectId"
          class="mt-10"
          :project-id="projectId"
          :locale="locale === 'it' ? 'it' : 'en'"
          :authorize="authorized"
        />
        <div
          id="step-decision-bar"
          v-show="project !== null && (sectionsMode || activeStage === currentStage)"
          :class="['flex flex-col', trayVisible ? '[&_[data-testid=decision-bar]]:mt-3' : '']"
          data-testid="step-decision-bar"
        />
      </div>

      <div
        id="step-technical-row"
        ref="technicalRow"
        v-show="project !== null"
        data-testid="step-technical-row"
      />

      <UiTechnicalDetails
        v-if="pageDetailsVisible"
        :key="`step-details-${activeStage}`"
        :summary="technicalSummary"
        :rows="technicalRows"
        data-testid="technical-details"
      >
        <div v-if="activeStage === 0 && briefHistory.length > 0" class="grid gap-2">
          <p class="text-on-night-3">{{ t("detail.briefVersions") }}</p>
          <ol class="m-0 grid list-none gap-1.5 p-0">
            <li
              v-for="version in briefHistory"
              :key="version.id"
              class="grid gap-0.5 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-x-5"
            >
              <span class="text-on-night-2">
                {{
                  t("detail.version", {
                    number: version.version_number,
                    date: formatDate(version.created_at),
                  })
                }}
              </span>
              <code class="font-mono text-xs leading-[1.6] wrap-anywhere">
                {{ version.content_hash }}
              </code>
            </li>
          </ol>
        </div>
      </UiTechnicalDetails>

      <UiTechnicalDetails
        v-if="project !== null"
        :class="pageDetailsVisible || stepRowPlaced ? 'mt-0! border-t-0! pt-0!' : ''"
        :summary="t('detail.projectDetails')"
        :rows="projectRows"
        data-testid="project-details"
      >
        <ModelRuntimeStatus :locale="locale === 'it' ? 'it' : 'en'" />
        <div>
          <UiButton variant="outline" data-testid="open-provenance" @click="provenanceOpen = true">
            {{ t("detail.provenance") }}
          </UiButton>
        </div>
      </UiTechnicalDetails>
    </div>

    <template v-if="project !== null">
      <UiSidePanel
        :open="provenanceOpen"
        :title="t('detail.provenanceTitle')"
        surface="night"
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
        :title="chatTwin ? tg('twinChat.title', { name: chatTwin.profile.name }) : ''"
        surface="night"
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
