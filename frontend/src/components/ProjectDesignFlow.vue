<script setup lang="ts">
import TwinIdentity from "./TwinIdentity.vue";
import { modelFeedback, generationProgress } from "./modelFeedback";
import { workflowStatusLabel } from "./workflowLabels";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import { computed, onUnmounted, reactive, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import { designApi, type DesignApi } from "../api/design";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useDesignStore } from "../stores/design";
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
  }>(),
  {
    locale: "en",
    autoLoad: true,
    prerequisiteReady: true,
  },
);

const auth = useAuthStore();
const store = useDesignStore();
const localError = ref<string | null>(null);
const selectedAlternativeId = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});
const mockup = ref<DesignMockupPayload | null>(null);
const mockupBusy = ref(false);
let mockupEpoch = 0;

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
    concerns: "Design concerns",
    openQuestions: "Open questions",
    gate: "Confirm the design",
    gateStatus: "Status",
    submitGate: "Prepare for approval",
    decisionCounter: "Decision {n} of {max}",
    moreActions: "Other actions",
    approveGate: "Approve design",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel approval",
    ready: "The design is approved. Continue to the Package step.",
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
      "Explore the screens and controls. Example results illustrate the design; the application is built from the package with your own tools.",
    mockupRequired: "Generate and review a visual mockup before proposing this design.",
    alternativeDetails: "Choose or compare a design",
    audit: "Version and review details",
    approvedPrototype: "Current design prototype",
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
    concerns: "Criticità di design",
    openQuestions: "Domande aperte",
    gate: "Conferma l'aspetto",
    gateStatus: "Stato",
    submitGate: "Prepara per l'approvazione",
    decisionCounter: "Decisione {n} di {max}",
    moreActions: "Altre azioni",
    approveGate: "Approva l'aspetto",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla approvazione",
    ready: "Il design è approvato. Continua con il passo Pacchetto.",
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
      "Esplora schermate e controlli. I risultati di esempio illustrano il design; l'applicazione si realizza dal pacchetto con i tuoi strumenti.",
    mockupRequired: "Genera e revisiona un mockup visivo prima di proporre questo design.",
    alternativeDetails: "Scegli o confronta un design",
    audit: "Dettagli di versione e revisione",
    approvedPrototype: "Prototipo del design corrente",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designApi);
const current = computed(() => store.current);
const packageValue = computed(() => store.current?.package ?? null);
const diffs = computed(() => store.diffHistory);
const pendingDiff = computed(() => store.pendingDiffs[0] ?? null);
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
const decisionCounter = computed(() =>
  copy.value.decisionCounter
    .replace("{n}", String(store.gate?.iteration ?? 1))
    .replace("{max}", String(store.gate?.max_iterations ?? 1)),
);
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

onUnmounted(() => {
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
  <section class="grid gap-5 rounded-card border border-line bg-white p-4 shadow-sm sm:p-5">
    <header class="grid gap-2">
      <TwinIdentity role="UX_UI_DESIGNER" :locale="locale" compact />
      <p class="m-0 text-xs font-semibold tracking-widest text-action uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-xl font-bold text-ink">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-ink-2">{{ copy.intro }}</p>
    </header>

    <p v-if="store.isBusy || mockupBusy" class="m-0 text-ink-2" aria-live="polite">
      {{ store.pending.generate || mockupBusy ? generationProgress(locale) : copy.loading }}
    </p>

    <p
      v-if="localError !== null || store.error !== null"
      class="m-0 rounded-panel border border-fail-line bg-fail-bg p-4 font-semibold text-fail-dark"
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
      <p class="m-0 text-ink-2">{{ copy.noPackage }}</p>
      <p v-if="!prerequisiteReady" role="status" class="text-sm text-ink-2">
        {{
          locale === "it"
            ? "Approva le funzionalità per vedere le proposte del designer."
            : "Approve the features to see the designer's proposals."
        }}
      </p>
      <button
        type="button"
        class="justify-self-start rounded-panel bg-action px-5 py-3 font-semibold text-white hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3"
        :disabled="store.isBusy || !prerequisiteReady"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </template>

    <template v-else>
      <details class="rounded-panel border border-line p-3 text-sm">
        <summary class="cursor-pointer font-semibold text-ink-2">{{ copy.audit }}</summary>
        <p class="my-3 text-ink-2">{{ copy.methodology }}</p>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p class="m-0 font-semibold text-ink">{{ copy.version }} {{ current.version_number }}</p>
          <span
            class="rounded-full px-3 py-1 text-xs font-semibold"
            :class="current.ready_for_gate ? 'bg-ok-bg text-ok-dark' : 'bg-surface-2 text-warn'"
          >
            {{ current.ready_for_gate ? copy.readyForGate : copy.notReadyForGate }}
          </span>
        </div>
        <p class="m-0 text-xs break-all text-ink-3">
          {{ copy.contentHash }}: <code>{{ current.content_hash }}</code>
        </p>
      </details>

      <details :open="current.package.owner_selected_alternative_id === null">
        <summary class="mb-3 cursor-pointer font-semibold text-ink">
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

      <section v-if="selectedAlternativeId !== null" class="grid gap-3" data-design-mockup>
        <header class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-lg font-bold text-ink">{{ copy.mockupTitle }}</h3>
          <button
            type="button"
            class="rounded-control bg-action px-4 py-2 text-sm font-semibold text-white disabled:bg-surface-3"
            :disabled="store.isBusy || mockupBusy || pendingDiff !== null"
            @click="generateMockup"
          >
            {{ copy.createMockup }}
          </button>
        </header>
        <template v-if="mockup?.package.prototype">
          <p class="m-0 text-xs font-semibold text-action">{{ copy.mockupDraft }}</p>
          <p class="m-0 text-sm text-ink-2">{{ copy.mockupHelp }}</p>
          <DeclarativePrototypePreview
            :key="mockup.generation_id"
            :prototype="mockup.package.prototype"
            :locale="locale"
          />
          <details class="text-xs text-ink-3">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="break-all">{{ mockup.generation_id }}</p>
          </details>
        </template>
        <template
          v-else-if="current.package.prototype?.design_alternative_id === selectedAlternativeId"
        >
          <p class="m-0 text-sm text-ink-2">{{ copy.approvedPrototype }}</p>
          <DeclarativePrototypePreview :prototype="current.package.prototype" :locale="locale" />
        </template>
        <p v-else class="m-0 text-sm text-ink-2">
          {{ copy.mockupRequired }}
        </p>
      </section>

      <section
        v-if="mockup !== null"
        class="grid gap-3 rounded-panel border border-action-soft-line bg-action-soft p-4"
      >
        <p class="m-0 text-sm text-action">{{ copy.selectionHelp }}</p>
        <button
          type="button"
          class="justify-self-start rounded-panel bg-action px-5 py-3 font-semibold text-white hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3"
          :disabled="store.isBusy || mockupBusy || !canProposeSelection"
          @click="proposeSelection"
        >
          {{ copy.proposeSelection }}
        </button>
      </section>

      <section v-if="pendingDiff !== null" class="grid gap-4" aria-labelledby="design-diffs-title">
        <h3 id="design-diffs-title" class="text-xl font-semibold text-ink">
          {{ copy.diffs }}
        </h3>

        <p v-if="diffs.length === 0" class="m-0 text-ink-2">{{ copy.noDiffs }}</p>

        <article
          v-for="diff in store.pendingDiffs"
          :key="diff.id"
          class="grid gap-4 rounded-card border border-line p-4"
        >
          <header class="flex flex-wrap items-center justify-between gap-3">
            <p class="m-0 font-semibold text-ink">
              {{ workflowStatusLabel(diff.status, locale) }}
            </p>
            <span class="rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold text-ink-2">
              {{ diff.changes.length }} {{ copy.changes }}
            </span>
          </header>

          <details class="text-sm text-ink-2">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="text-xs break-all">{{ diff.id }} · {{ diff.status }}</p>
            <ul class="mt-3 grid gap-2 text-sm text-ink-2">
              <li
                v-for="change in diff.changes"
                :key="`${change.artifact_kind}:${change.artifact_id}`"
                class="rounded-control bg-surface-2 p-3"
              >
                {{ change.kind }} · {{ change.artifact_kind }} · {{ change.artifact_id }}
              </li>
            </ul>
          </details>

          <template v-if="diff.status === 'PROPOSED'">
            <label class="grid gap-2 text-sm font-semibold text-ink">
              {{ copy.reason }}
              <textarea
                v-model="diffReasons[diff.id]"
                rows="3"
                class="rounded-panel border border-field px-3 py-2 font-normal"
              />
            </label>

            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="rounded-panel bg-ok px-4 py-2 font-semibold text-white hover:bg-ok-dark disabled:bg-surface-3"
                :disabled="store.isBusy"
                @click="decideDiff(diff, 'APPROVE')"
              >
                {{ copy.approveDiff }}
              </button>
              <button
                type="button"
                class="rounded-panel border border-fail-line px-4 py-2 font-semibold text-fail-dark hover:bg-fail-bg disabled:text-ink-3"
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
          <h3 class="text-xl font-semibold text-ink">{{ copy.concerns }}</h3>
          <ul class="mt-3 grid gap-3">
            <li
              v-for="concern in current.package.concerns"
              :key="concern.id"
              class="rounded-panel border border-line-strong bg-surface-2 p-4 text-sm text-warn"
            >
              <p class="m-0 font-semibold">{{ concern.code }} · {{ concern.summary }}</p>
              <p class="mt-2 mb-0">{{ concern.mitigation }}</p>
            </li>
          </ul>
        </section>

        <section v-if="current.package.open_questions.length > 0">
          <h3 class="text-xl font-semibold text-ink">{{ copy.openQuestions }}</h3>
          <ul class="mt-3 list-disc space-y-2 pl-5 text-ink-2">
            <li v-for="question in current.package.open_questions" :key="question">
              {{ question }}
            </li>
          </ul>
        </section>
      </div>

      <div class="grid gap-4">
        <UiCard tone="elevated">
          <div class="flex flex-wrap items-baseline justify-between gap-3">
            <h3 class="m-0 text-2xl font-semibold tracking-card">{{ copy.gate }}</h3>
            <span v-if="store.gate" class="font-mono text-xs text-ink-3">
              {{ decisionCounter }}
            </span>
          </div>
          <p class="mt-2 mb-0 text-sm text-ink-2">
            {{ copy.gateStatus }}: {{ workflowStatusLabel(store.gate?.status, locale) }}
          </p>
          <p
            class="mt-2 mb-0 text-[15px] font-semibold"
            :class="store.isReadyForArchitecture ? 'text-ok-dark' : 'text-warn'"
            aria-live="polite"
          >
            {{ store.isReadyForArchitecture ? copy.ready : copy.notReady }}
          </p>
          <div v-if="canSubmitGate" class="mt-5">
            <UiButton :disabled="store.isBusy" @click="submitGate">{{ copy.submitGate }}</UiButton>
          </div>
          <div v-if="gatePending || gatePaused" class="mt-5 grid gap-3">
            <div v-if="gatePending" class="flex flex-wrap gap-3">
              <UiButton :disabled="store.isBusy" @click="decideGate('APPROVE')">
                {{ copy.approveGate }}
              </UiButton>
              <UiButton
                variant="secondary"
                :disabled="store.isBusy"
                @click="decideGate('REQUEST_REVISION')"
              >
                {{ copy.requestRevision }}
              </UiButton>
            </div>
            <div v-else class="flex flex-wrap gap-3">
              <UiButton :disabled="store.isBusy" @click="decideGate('RESUME')">
                {{ copy.resume }}
              </UiButton>
              <UiButton variant="secondary" :disabled="store.isBusy" @click="decideGate('CANCEL')">
                {{ copy.cancelGate }}
              </UiButton>
            </div>
            <label class="grid gap-1 text-sm font-semibold">
              {{ copy.reason }}
              <textarea
                v-model="gateReason"
                rows="3"
                class="min-h-20 rounded-control border border-field bg-surface px-3 py-2 text-[15px] font-normal"
              />
            </label>
            <details v-if="gatePending" class="text-sm">
              <summary class="cursor-pointer font-semibold text-ink-2">
                {{ copy.moreActions }}
              </summary>
              <div class="mt-3 flex flex-wrap gap-3">
                <UiButton variant="danger" :disabled="store.isBusy" @click="decideGate('REJECT')">
                  {{ copy.rejectGate }}
                </UiButton>
                <UiButton variant="secondary" :disabled="store.isBusy" @click="decideGate('PAUSE')">
                  {{ copy.pause }}
                </UiButton>
                <UiButton
                  variant="secondary"
                  :disabled="store.isBusy"
                  @click="decideGate('CANCEL')"
                >
                  {{ copy.cancelGate }}
                </UiButton>
              </div>
            </details>
          </div>
        </UiCard>
      </div>

      <details class="grid gap-3">
        <summary class="cursor-pointer text-sm font-semibold text-ink-2">
          {{ copy.history }}
        </summary>
        <h3 class="text-xl font-semibold text-ink">{{ copy.history }}</h3>
        <ol class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <li
            v-for="version in store.history"
            :key="version.id"
            class="grid gap-2 rounded-panel border border-line p-4"
          >
            <p class="m-0 font-semibold text-ink">
              {{ copy.version }} {{ version.version_number }}
            </p>
            <p class="m-0 text-sm text-ink-2">
              {{ copy.createdAt.replace("{date}", formatDate(version.created_at)) }}
            </p>
            <code class="text-xs break-all text-ink-3">{{ version.content_hash }}</code>
          </li>
        </ol>
      </details>
    </template>
  </section>
</template>
