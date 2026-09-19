<script setup lang="ts">
import TwinIdentity from "./TwinIdentity.vue";
import { modelFeedback, generationProgress } from "./modelFeedback";
import { workflowStatusLabel } from "./workflowLabels";
import { computed, onUnmounted, reactive, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import { designApi, type DesignApi } from "../api/design";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useDesignStore } from "../stores/design";
import { useWebExecutionStore } from "../stores/webExecution";
import {
  sourceDesignApi,
  type SourceDesignApi,
  type SourceDesignReferencePayload,
} from "../api/webDesignReference";
import type {
  DesignGateDecisionAction,
  DesignMockupPayload,
  DesignPackageDiffPayload,
  DesignRevisionDecision,
} from "../types/design";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    prerequisiteReady?: boolean;
    authorize?: AuthorizedRequest;
    api?: DesignApi;
    sourceApi?: SourceDesignApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
    prerequisiteReady: true,
  },
);

const emit = defineEmits<{ "show-result": [] }>();

const auth = useAuthStore();
const store = useDesignStore();
const web = useWebExecutionStore();
const localError = ref<string | null>(null);
const selectedAlternativeId = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});
const mockup = ref<DesignMockupPayload | null>(null);
const mockupBusy = ref(false);
let mockupEpoch = 0;
const sourceDesign = ref<SourceDesignReferencePayload | null>(null);
const sourceDesignBusy = ref(false);
const sourceDesignFailed = ref(false);
let sourceDesignEpoch = 0;

const messages = {
  en: {
    eyebrow: "Your app's look",
    title: "Choose how your app will look",
    intro: "Compare the ideas, explore a visual preview, and choose the design you want to build.",
    loading: "Updating Design state…",
    generate: "Generate design alternatives",
    noPackage: "The designer is ready to propose a look for your app.",
    version: "Version",
    contentHash: "Content hash",
    readyForGate: "Ready for your approval",
    notReadyForGate: "Selection and prototype are still required",
    proposeSelection: "Review this design choice",
    selectionHelp: "Review the proposed design choice, then confirm to apply it.",
    diffs: "Design changes to review",
    noDiffs: "No design revision is waiting for a decision.",
    changes: "Changes",
    approveDiff: "Apply this design",
    rejectDiff: "Discard changes",
    reason: "Decision reason",
    reasonRequired: "A reason is required to reject or request changes.",
    prototype: "Visual preview",
    concerns: "Design concerns",
    openQuestions: "Open questions",
    gate: "Confirm the design",
    gateStatus: "Status",
    submitGate: "Prepare for approval",
    approveGate: "Approve design",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel approval",
    ready: "The design is approved. Continue to the solution.",
    notReady: "Design approval is still required.",
    methodology:
      "Gate 5 approves the exact Design Package ID, version, and content hash. Owner approval is governance, not empirical validation. Synthetic User Twin feedback remains a design hypothesis.",
    history: "Previous designs",
    createdAt: "Created {date}",
    loadError: "The Design stage could not be loaded.",
    chooseAlternative: "Choose one design alternative before creating the revision.",
    pendingDiff: "Review the pending changes before proposing more.",
    createMockup: "Create visual preview",
    mockupTitle: "Design preview",
    mockupDraft: "Model-generated draft · not applied",
    mockupHelp:
      "Explore the screens and controls. Example results illustrate the design; the generated application is tested in the Result step.",
    mockupRequired: "Generate and review a visual mockup before proposing this design.",
    alternativeDetails: "Choose or compare a design",
    audit: "Version and review details",
    approvedPrototype: "Current design prototype",
    sourceMockup: "Preview chosen for app version {version}",
    sourcePrototype: "Design used for app version {version}",
    sourceLoading: "Loading the design used for this app…",
    sourceUnavailable:
      "The design linked to this app could not be loaded. The draft below may use a different design.",
    sourceNoPrototype: "No visual preview is available for this app version.",
    sourceOlderDesign:
      "This app uses an earlier design version. New design changes are not applied to it automatically.",
    ownerReference:
      "You selected this preview for this app version. The previously approved design remains unchanged.",
    visualNotAssessed:
      "This is the selected design reference. Visual correspondence is not automatically verified.",
    structureVerified:
      "The app includes the preview's screens and controls. Open the app to compare their appearance and try it.",
    compareResult: "Try the app",
    separateDraft: "New design draft · not applied to this app",
  },
  it: {
    eyebrow: "L'aspetto della tua app",
    title: "Scegli come apparirà la tua app",
    intro: "Confronta le idee, esplora l'anteprima e scegli l'aspetto che vuoi realizzare.",
    loading: "Aggiornamento dello stato del design…",
    generate: "Genera le alternative di design",
    noPackage: "Il designer è pronto a proporti un aspetto per la tua app.",
    version: "Versione",
    contentHash: "Hash del contenuto",
    readyForGate: "Pronto per la tua approvazione",
    notReadyForGate: "Sono ancora necessari selezione e prototipo",
    proposeSelection: "Controlla questa scelta",
    selectionHelp: "Controlla la scelta proposta, poi conferma per applicarla.",
    diffs: "Modifiche al design da valutare",
    noDiffs: "Nessuna revisione del design è in attesa di una decisione.",
    changes: "Modifiche",
    approveDiff: "Applica questo design",
    rejectDiff: "Scarta modifiche",
    reason: "Motivazione della decisione",
    reasonRequired: "Scrivi una motivazione per rifiutare o richiedere modifiche.",
    prototype: "Anteprima visiva",
    concerns: "Criticità di design",
    openQuestions: "Domande aperte",
    gate: "Conferma l'aspetto",
    gateStatus: "Stato",
    submitGate: "Prepara per l'approvazione",
    approveGate: "Approva l'aspetto",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla approvazione",
    ready: "L'aspetto è approvato. Continua con la soluzione.",
    notReady: "È ancora necessaria l'approvazione del design.",
    methodology:
      "Il Gate 5 approva ID, versione e hash esatti del Design Package. L'approvazione del proprietario è governance, non validazione empirica. Il feedback sintetico dei User Twin resta un'ipotesi progettuale.",
    history: "Design precedenti",
    createdAt: "Creata {date}",
    loadError: "Non è stato possibile caricare la fase di design.",
    chooseAlternative: "Seleziona un'alternativa di design prima di creare la revisione.",
    pendingDiff: "Valuta le modifiche in attesa prima di proporne altre.",
    createMockup: "Crea anteprima visiva",
    mockupTitle: "Anteprima del design",
    mockupDraft: "Bozza generata dal modello · non applicata",
    mockupHelp:
      "Esplora schermate e controlli. I risultati di esempio illustrano il design; l'applicazione generata si prova nel passaggio Risultato.",
    mockupRequired: "Genera e revisiona un mockup visivo prima di proporre questo design.",
    alternativeDetails: "Scegli o confronta un design",
    audit: "Dettagli di versione e revisione",
    approvedPrototype: "Prototipo del design corrente",
    sourceMockup: "Anteprima scelta per l'app, versione {version}",
    sourcePrototype: "Design usato per l'app, versione {version}",
    sourceLoading: "Caricamento del design usato per questa app…",
    sourceUnavailable:
      "Non è stato possibile caricare il design collegato all'app. La bozza qui sotto potrebbe usare un design diverso.",
    sourceNoPrototype: "Non è disponibile un'anteprima visiva per questa versione dell'app.",
    sourceOlderDesign:
      "Questa app usa una versione precedente del design. Le nuove modifiche al design non vengono applicate automaticamente.",
    ownerReference:
      "Hai scelto questa anteprima per questa versione dell'app. Il design approvato in precedenza resta invariato.",
    visualNotAssessed:
      "Il riferimento è registrato; la corrispondenza visiva non è verificata automaticamente.",
    structureVerified:
      "L'app include schermate e controlli dell'anteprima. Aprila per confrontare l'aspetto e provarla.",
    compareResult: "Prova l'app",
    separateDraft: "Nuova bozza di design · non applicata all'app",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designApi);
const current = computed(() => store.current);
const packageValue = computed(() => store.current?.package ?? null);
const diffs = computed(() => store.diffHistory);
const pendingDiff = computed(() => store.pendingDiffs[0] ?? null);
const sourceRevision = computed(() =>
  web.activeProjectId === props.projectId ? web.currentSourceRevision : null,
);
const sourcePrototype = computed(
  () => sourceDesign.value?.owner_mockup?.prototype ?? sourceDesign.value?.prototype ?? null,
);
const hasSeparateDraft = computed(
  () =>
    mockup.value !== null &&
    mockup.value.generation_id !== sourceDesign.value?.owner_mockup?.generation_id,
);
const gateTargetsCurrent = computed(() => {
  if (store.gate === null || store.current === null) {
    return false;
  }

  return (
    store.gate.artifact.artifact_id === store.current.id &&
    store.gate.artifact.version === store.current.version_number &&
    store.gate.artifact.content_hash === store.current.content_hash
  );
});
const canSubmitGate = computed(() => {
  if (store.current === null || !store.current.ready_for_gate) {
    return false;
  }

  if (store.gate === null || !gateTargetsCurrent.value) {
    return true;
  }

  return store.gate.status === "DRAFT" || store.gate.status === "STALE";
});
const gatePending = computed(
  () => gateTargetsCurrent.value && store.gate?.status === "PENDING_APPROVAL",
);
const gatePaused = computed(() => gateTargetsCurrent.value && store.gate?.status === "PAUSED");
const canProposeSelection = computed(() => {
  if (packageValue.value === null || selectedAlternativeId.value === null) {
    return false;
  }

  if (pendingDiff.value !== null) {
    return false;
  }

  return (
    mockup.value !== null &&
    mockup.value.design_version_id === current.value?.id &&
    mockup.value.design_content_hash === current.value?.content_hash &&
    mockup.value.package.owner_selected_alternative_id === selectedAlternativeId.value
  );
});

async function generateMockup(): Promise<void> {
  if (current.value === null || selectedAlternativeId.value === null || mockupBusy.value) return;
  const epoch = ++mockupEpoch;
  const projectId = props.projectId;
  const body = {
    design_version_id: current.value.id,
    design_content_hash: current.value.content_hash,
    alternative_id: selectedAlternativeId.value,
  };
  mockupBusy.value = true;
  localError.value = null;
  try {
    const result = await authorizedRequest((token) =>
      api.value.generateMockup(projectId, body, token),
    );
    if (epoch === mockupEpoch) mockup.value = result;
  } catch (error) {
    if (epoch === mockupEpoch)
      localError.value =
        error instanceof Error
          ? (modelFeedback(error.message, props.locale) ?? error.message)
          : copy.value.loadError;
  } finally {
    if (epoch === mockupEpoch) mockupBusy.value = false;
  }
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(apiClient, operation);
}

async function run(operation: () => Promise<unknown>): Promise<boolean> {
  localError.value = null;

  try {
    await operation();
    return true;
  } catch (error) {
    localError.value =
      modelFeedback(store.error?.code, props.locale) ??
      (error instanceof Error
        ? (modelFeedback(error.message, props.locale) ?? error.message)
        : copy.value.loadError);
    return false;
  }
}

async function load(): Promise<void> {
  if (props.projectId.trim().length === 0) {
    return;
  }

  await run(() => store.load(props.projectId, authorizedRequest, api.value));
}

async function generate(): Promise<void> {
  if (!props.prerequisiteReady || store.isBusy) return;
  await run(() => store.generate(props.projectId, authorizedRequest, api.value));
}

async function proposeSelection(): Promise<void> {
  if (pendingDiff.value !== null) {
    localError.value = copy.value.pendingDiff;
    return;
  }

  if (packageValue.value === null || selectedAlternativeId.value === null) {
    localError.value = copy.value.chooseAlternative;
    return;
  }

  if (!canProposeSelection.value || mockup.value === null) {
    localError.value = copy.value.mockupRequired;
    return;
  }
  const proposed = mockup.value.package;

  await run(() => store.proposeRevision(props.projectId, proposed, authorizedRequest, api.value));
}

async function decideDiff(
  diff: DesignPackageDiffPayload,
  decision: DesignRevisionDecision,
): Promise<void> {
  const reason = (diffReasons[diff.id] ?? "").trim().replace(/\s+/g, " ");

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }

  await run(() =>
    store.decideRevision(
      props.projectId,
      diff.id,
      decision,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );
}

async function submitGate(): Promise<void> {
  await run(() => store.submitGate(props.projectId, authorizedRequest, api.value));
}

async function decideGate(action: DesignGateDecisionAction): Promise<void> {
  const reason = gateReason.value.trim().replace(/\s+/g, " ");

  if ((action === "REJECT" || action === "REQUEST_REVISION") && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }

  const applied = await run(() =>
    store.decideGate(
      props.projectId,
      action,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );

  if (applied) {
    gateReason.value = "";
  }
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(props.locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

watch(
  () => [props.projectId, sourceRevision.value?.id, current.value?.content_hash] as const,
  async ([projectId, revisionId]) => {
    const epoch = ++sourceDesignEpoch;
    sourceDesign.value = null;
    sourceDesignFailed.value = false;
    sourceDesignBusy.value = revisionId !== undefined;
    if (revisionId === undefined) return;
    try {
      const result = await authorizedRequest((token) =>
        (props.sourceApi ?? sourceDesignApi).reference(projectId, revisionId, token),
      );
      if (epoch !== sourceDesignEpoch) return;
      if (
        result.source.revision_id !== revisionId ||
        result.source.content_hash !== sourceRevision.value?.content_hash
      )
        throw new Error("SOURCE_DESIGN_REFERENCE_CHANGED");
      sourceDesign.value = result;
    } catch {
      if (epoch === sourceDesignEpoch) sourceDesignFailed.value = true;
    } finally {
      if (epoch === sourceDesignEpoch) sourceDesignBusy.value = false;
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  sourceDesignEpoch++;
  mockupEpoch++;
});

watch(
  () => [props.projectId, current.value?.id, selectedAlternativeId.value] as const,
  async ([projectId, versionId, alternativeId]) => {
    const epoch = ++mockupEpoch;
    mockup.value = null;
    mockupBusy.value = false;
    if (versionId === undefined || alternativeId === null) return;
    try {
      const saved = await authorizedRequest((token) =>
        api.value.currentMockup(projectId, alternativeId, token),
      );
      if (epoch === mockupEpoch) mockup.value = saved;
    } catch (error) {
      if (epoch === mockupEpoch)
        localError.value = error instanceof Error ? error.message : copy.value.loadError;
    }
  },
  { immediate: true },
);

watch(
  () => store.current?.id,
  () => {
    selectedAlternativeId.value = store.current?.package.owner_selected_alternative_id ?? null;
  },
  { immediate: true },
);

watch(
  () => props.projectId,
  async () => {
    if (props.autoLoad) {
      await load();
    }
  },
  { immediate: true },
);
</script>

<template>
  <section class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
    <header class="grid gap-2">
      <TwinIdentity role="UX_UI_DESIGNER" :locale="locale" compact />
      <p class="m-0 text-xs font-black tracking-widest text-indigo-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-xl font-bold text-slate-950">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-slate-600">{{ copy.intro }}</p>
    </header>

    <p v-if="store.isBusy || mockupBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ store.pending.generate || mockupBusy ? generationProgress(locale) : copy.loading }}
    </p>

    <p
      v-if="localError !== null || store.error !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{
        localError ??
        modelFeedback(store.error?.code, locale) ??
        store.error?.message ??
        copy.loadError
      }}
    </p>

    <template v-if="current === null">
      <p class="m-0 text-slate-600">{{ copy.noPackage }}</p>
      <p v-if="!prerequisiteReady" role="status" class="text-sm text-slate-700">
        {{
          locale === "it"
            ? "Approva le funzionalità per vedere le proposte del designer."
            : "Approve the features to see the designer's proposals."
        }}
      </p>
      <button
        type="button"
        class="justify-self-start rounded-xl bg-indigo-700 px-5 py-3 font-black text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
        :disabled="store.isBusy || !prerequisiteReady"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </template>

    <template v-else>
      <details class="rounded-xl border border-slate-200 p-3 text-sm">
        <summary class="cursor-pointer font-semibold text-slate-700">{{ copy.audit }}</summary>
        <p class="my-3 text-slate-600">{{ copy.methodology }}</p>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p class="m-0 font-black text-slate-950">
            {{ copy.version }} {{ current.version_number }}
          </p>
          <span
            class="rounded-full px-3 py-1 text-xs font-black"
            :class="
              current.ready_for_gate
                ? 'bg-emerald-100 text-emerald-800'
                : 'bg-amber-100 text-amber-900'
            "
          >
            {{ current.ready_for_gate ? copy.readyForGate : copy.notReadyForGate }}
          </span>
        </div>
        <p class="m-0 text-xs break-all text-slate-500">
          {{ copy.contentHash }}: <code>{{ current.content_hash }}</code>
        </p>
      </details>

      <details :open="current.package.owner_selected_alternative_id === null">
        <summary class="mb-3 cursor-pointer font-semibold text-slate-900">
          {{ copy.alternativeDetails }}
        </summary>
        <DesignAlternativeComparison
          :alternatives="current.package.alternatives"
          :critiques="current.package.critiques"
          :recommended-alternative-id="current.package.recommended_alternative_id"
          :selected-alternative-id="selectedAlternativeId"
          :disabled="store.isBusy || mockupBusy || pendingDiff !== null"
          :locale="locale"
          @select="selectedAlternativeId = $event"
        />
      </details>

      <section v-if="sourceRevision" class="grid gap-3" data-source-design>
        <h3 class="text-lg font-bold text-slate-950">
          {{
            (sourceDesign?.owner_mockup ? copy.sourceMockup : copy.sourcePrototype).replace(
              "{version}",
              String(sourceRevision.version_number),
            )
          }}
        </h3>
        <p v-if="sourceDesignBusy" role="status" class="m-0 text-sm text-slate-600">
          {{ copy.sourceLoading }}
        </p>
        <p
          v-else-if="sourceDesignFailed"
          role="alert"
          class="m-0 rounded-lg bg-amber-50 p-3 text-sm text-amber-950"
        >
          {{ copy.sourceUnavailable }}
        </p>
        <template v-else-if="sourceDesign">
          <p v-if="sourceDesign.owner_mockup" class="m-0 text-sm text-slate-600">
            {{ copy.ownerReference }}
          </p>
          <p
            v-if="sourceDesign.design_status === 'STALE'"
            class="m-0 rounded-lg bg-amber-50 p-3 text-sm text-amber-950"
          >
            {{ copy.sourceOlderDesign }}
          </p>
          <DeclarativePrototypePreview
            v-if="sourcePrototype"
            :key="sourceDesign.owner_mockup?.generation_id ?? sourceDesign.design.content_hash"
            :prototype="sourcePrototype"
            :locale="locale"
          />
          <p v-else class="m-0 text-sm text-slate-600">{{ copy.sourceNoPrototype }}</p>
          <p class="m-0 text-xs text-slate-500">
            {{
              sourceDesign.structure_contract === "VERIFIED"
                ? copy.structureVerified
                : copy.visualNotAssessed
            }}
          </p>
          <button
            type="button"
            class="justify-self-start rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-800"
            @click="emit('show-result')"
          >
            {{ copy.compareResult }}
          </button>
        </template>
      </section>

      <section v-if="selectedAlternativeId !== null" class="grid gap-3" data-design-mockup>
        <header class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-lg font-bold text-slate-950">{{ copy.mockupTitle }}</h3>
          <button
            type="button"
            class="rounded-lg bg-indigo-700 px-4 py-2 text-sm font-semibold text-white disabled:bg-slate-400"
            :disabled="store.isBusy || mockupBusy || pendingDiff !== null"
            @click="generateMockup"
          >
            {{ copy.createMockup }}
          </button>
        </header>
        <details
          v-if="sourceRevision && hasSeparateDraft && mockup?.package.prototype"
          class="rounded-xl border border-slate-200 p-3"
          data-unapplied-mockup
        >
          <summary class="cursor-pointer text-sm font-semibold text-slate-700">
            {{ copy.separateDraft }}
          </summary>
          <p class="my-3 text-sm text-slate-600">{{ copy.mockupHelp }}</p>
          <DeclarativePrototypePreview
            :key="mockup.generation_id"
            :prototype="mockup.package.prototype"
            :locale="locale"
          />
          <details class="mt-3 text-xs text-slate-500">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="break-all">{{ mockup.generation_id }}</p>
          </details>
        </details>
        <template v-else-if="!sourceRevision && mockup?.package.prototype">
          <p class="m-0 text-xs font-semibold text-indigo-700">{{ copy.mockupDraft }}</p>
          <p class="m-0 text-sm text-slate-600">{{ copy.mockupHelp }}</p>
          <DeclarativePrototypePreview
            :key="mockup.generation_id"
            :prototype="mockup.package.prototype"
            :locale="locale"
          />
          <details class="text-xs text-slate-500">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="break-all">{{ mockup.generation_id }}</p>
          </details>
        </template>
        <template
          v-else-if="
            !sourceRevision &&
            current.package.prototype?.design_alternative_id === selectedAlternativeId
          "
        >
          <p class="m-0 text-sm text-slate-600">{{ copy.approvedPrototype }}</p>
          <DeclarativePrototypePreview :prototype="current.package.prototype" :locale="locale" />
        </template>
        <p v-else-if="!sourceRevision" class="m-0 text-sm text-slate-600">
          {{ copy.mockupRequired }}
        </p>
      </section>

      <section
        v-if="mockup !== null && (!sourceRevision || hasSeparateDraft)"
        class="grid gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4"
      >
        <p class="m-0 text-sm text-indigo-950">{{ copy.selectionHelp }}</p>
        <button
          type="button"
          class="justify-self-start rounded-xl bg-indigo-700 px-5 py-3 font-black text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
          :disabled="store.isBusy || mockupBusy || !canProposeSelection"
          @click="proposeSelection"
        >
          {{ copy.proposeSelection }}
        </button>
      </section>

      <section v-if="pendingDiff !== null" class="grid gap-4" aria-labelledby="design-diffs-title">
        <h3 id="design-diffs-title" class="text-xl font-black text-slate-950">
          {{ copy.diffs }}
        </h3>

        <p v-if="diffs.length === 0" class="m-0 text-slate-600">{{ copy.noDiffs }}</p>

        <article
          v-for="diff in store.pendingDiffs"
          :key="diff.id"
          class="grid gap-4 rounded-2xl border border-slate-200 p-4"
        >
          <header class="flex flex-wrap items-center justify-between gap-3">
            <p class="m-0 font-black text-slate-950">
              {{ workflowStatusLabel(diff.status, locale) }}
            </p>
            <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-700">
              {{ diff.changes.length }} {{ copy.changes }}
            </span>
          </header>

          <details class="text-sm text-slate-600">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="text-xs break-all">{{ diff.id }} · {{ diff.status }}</p>
            <ul class="mt-3 grid gap-2 text-sm text-slate-700">
              <li
                v-for="change in diff.changes"
                :key="`${change.artifact_kind}:${change.artifact_id}`"
                class="rounded-lg bg-slate-50 p-3"
              >
                {{ change.kind }} · {{ change.artifact_kind }} · {{ change.artifact_id }}
              </li>
            </ul>
          </details>

          <template v-if="diff.status === 'PROPOSED'">
            <label class="grid gap-2 text-sm font-black text-slate-900">
              {{ copy.reason }}
              <textarea
                v-model="diffReasons[diff.id]"
                rows="3"
                class="rounded-xl border border-slate-300 px-3 py-2 font-normal"
              />
            </label>

            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="rounded-xl bg-emerald-700 px-4 py-2 font-black text-white hover:bg-emerald-600 disabled:bg-slate-400"
                :disabled="store.isBusy"
                @click="decideDiff(diff, 'APPROVE')"
              >
                {{ copy.approveDiff }}
              </button>
              <button
                type="button"
                class="rounded-xl border border-red-300 px-4 py-2 font-black text-red-800 hover:bg-red-50 disabled:text-slate-400"
                :disabled="store.isBusy"
                @click="decideDiff(diff, 'REJECT')"
              >
                {{ copy.rejectDiff }}
              </button>
            </div>
          </template>
        </article>
      </section>

      <div class="grid gap-5 lg:grid-cols-2">
        <section v-if="current.package.concerns.length > 0">
          <h3 class="text-xl font-black text-slate-950">{{ copy.concerns }}</h3>
          <ul class="mt-3 grid gap-3">
            <li
              v-for="concern in current.package.concerns"
              :key="concern.id"
              class="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950"
            >
              <p class="m-0 font-black">{{ concern.code }} · {{ concern.summary }}</p>
              <p class="mt-2 mb-0">{{ concern.mitigation }}</p>
            </li>
          </ul>
        </section>

        <section v-if="current.package.open_questions.length > 0">
          <h3 class="text-xl font-black text-slate-950">{{ copy.openQuestions }}</h3>
          <ul class="mt-3 list-disc space-y-2 pl-5 text-slate-700">
            <li v-for="question in current.package.open_questions" :key="question">
              {{ question }}
            </li>
          </ul>
        </section>
      </div>

      <section class="grid gap-4 rounded-2xl border border-slate-300 bg-slate-50 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.gate }}</h3>
        <p class="m-0 text-sm text-slate-700">
          {{ copy.gateStatus }}: {{ workflowStatusLabel(store.gate?.status, locale) }}
        </p>

        <p
          class="m-0 rounded-xl p-3 font-bold"
          :class="
            store.isReadyForArchitecture
              ? 'bg-emerald-100 text-emerald-900'
              : 'bg-amber-100 text-amber-950'
          "
          aria-live="polite"
        >
          {{ store.isReadyForArchitecture ? copy.ready : copy.notReady }}
        </p>

        <button
          v-if="canSubmitGate"
          type="button"
          class="justify-self-start rounded-xl bg-indigo-700 px-5 py-3 font-black text-white hover:bg-indigo-600 disabled:bg-slate-400"
          :disabled="store.isBusy"
          @click="submitGate"
        >
          {{ copy.submitGate }}
        </button>

        <template v-if="gatePending || gatePaused">
          <label class="grid gap-2 text-sm font-black text-slate-900">
            {{ copy.reason }}
            <textarea
              v-model="gateReason"
              rows="3"
              class="rounded-xl border border-slate-300 px-3 py-2 font-normal"
            />
          </label>

          <div class="flex flex-wrap gap-3">
            <button
              v-if="gatePending"
              type="button"
              class="rounded-xl bg-emerald-700 px-4 py-2 font-black text-white hover:bg-emerald-600 disabled:bg-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('APPROVE')"
            >
              {{ copy.approveGate }}
            </button>
            <button
              v-if="gatePending"
              type="button"
              class="rounded-xl border border-amber-400 px-4 py-2 font-black text-amber-900 hover:bg-amber-50 disabled:text-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('REQUEST_REVISION')"
            >
              {{ copy.requestRevision }}
            </button>
            <button
              v-if="gatePending"
              type="button"
              class="rounded-xl border border-red-300 px-4 py-2 font-black text-red-800 hover:bg-red-50 disabled:text-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('REJECT')"
            >
              {{ copy.rejectGate }}
            </button>
            <button
              v-if="gatePending"
              type="button"
              class="rounded-xl border border-slate-300 px-4 py-2 font-black text-slate-700 hover:bg-white disabled:text-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('PAUSE')"
            >
              {{ copy.pause }}
            </button>
            <button
              v-if="gatePaused"
              type="button"
              class="rounded-xl border border-slate-300 px-4 py-2 font-black text-slate-700 hover:bg-white disabled:text-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('RESUME')"
            >
              {{ copy.resume }}
            </button>
            <button
              type="button"
              class="rounded-xl border border-slate-300 px-4 py-2 font-black text-slate-700 hover:bg-white disabled:text-slate-400"
              :disabled="store.isBusy"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancelGate }}
            </button>
          </div>
        </template>
      </section>

      <details class="grid gap-3">
        <summary class="cursor-pointer text-sm font-semibold text-slate-700">
          {{ copy.history }}
        </summary>
        <h3 class="text-xl font-black text-slate-950">{{ copy.history }}</h3>
        <ol class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <li
            v-for="version in store.history"
            :key="version.id"
            class="grid gap-2 rounded-xl border border-slate-200 p-4"
          >
            <p class="m-0 font-black text-slate-950">
              {{ copy.version }} {{ version.version_number }}
            </p>
            <p class="m-0 text-sm text-slate-600">
              {{ copy.createdAt.replace("{date}", formatDate(version.created_at)) }}
            </p>
            <code class="text-xs break-all text-slate-500">{{ version.content_hash }}</code>
          </li>
        </ol>
      </details>
    </template>
  </section>
</template>
