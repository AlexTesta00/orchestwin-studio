<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import DesignAlternativeComparison from "./DesignAlternativeComparison.vue";
import DeclarativePrototypePreview from "./DeclarativePrototypePreview.vue";
import { buildSelectedDesignPackage } from "./designPrototype";
import { designApi, type DesignApi } from "../api/design";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useDesignStore } from "../stores/design";
import type {
  DesignGateDecisionAction,
  DesignPackageDiffPayload,
  DesignRevisionDecision,
} from "../types/design";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedRequest;
    api?: DesignApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useDesignStore();
const localError = ref<string | null>(null);
const selectedAlternativeId = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});

const messages = {
  en: {
    eyebrow: "Design exploration · Gate 5",
    title: "Design alternatives and declarative prototype",
    intro:
      "Compare traceable alternatives, review simulated User Twin critiques, select one direction, and approve the exact Design Package version.",
    loading: "Updating Design state…",
    generate: "Generate design alternatives",
    noPackage: "No Design Package has been generated yet.",
    version: "Version",
    contentHash: "Content hash",
    readyForGate: "Package ready for Gate 5",
    notReadyForGate: "Selection and prototype are still required",
    proposeSelection: "Create selection and prototype diff",
    selectionHelp:
      "The selection is proposed as an immutable diff. It is not applied until the owner approves that diff.",
    diffs: "Reviewable Design Package diffs",
    noDiffs: "No design revision is waiting for a decision.",
    changes: "Changes",
    approveDiff: "Approve diff",
    rejectDiff: "Reject diff",
    reason: "Decision reason",
    reasonRequired: "A reason is required for rejection or a Gate 5 revision request.",
    prototype: "Trusted declarative prototype",
    concerns: "Design concerns",
    openQuestions: "Open questions",
    gate: "Gate 5 · Design approval",
    gateStatus: "Gate status",
    submitGate: "Submit current Design Package",
    approveGate: "Approve Gate 5",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel gate",
    ready: "Ready for architecture and test planning.",
    notReady: "Design approval is still required.",
    methodology:
      "Gate 5 approves the exact Design Package ID, version, and content hash. Owner approval is governance, not empirical validation. Synthetic User Twin feedback remains a design hypothesis.",
    history: "Design Package history",
    createdAt: "Created {date}",
    loadError: "The Design stage could not be loaded.",
    chooseAlternative: "Choose one design alternative before creating the revision.",
    pendingDiff: "Decide the existing proposed diff before creating another revision.",
  },
  it: {
    eyebrow: "Esplorazione design · Gate 5",
    title: "Alternative di design e prototipo dichiarativo",
    intro:
      "Confronta alternative tracciabili, revisiona le critiche simulate dei User Twin, seleziona una direzione e approva la versione esatta del Design Package.",
    loading: "Aggiornamento dello stato del design…",
    generate: "Genera le alternative di design",
    noPackage: "Non è stato ancora generato alcun Design Package.",
    version: "Versione",
    contentHash: "Hash del contenuto",
    readyForGate: "Package pronto per il Gate 5",
    notReadyForGate: "Sono ancora necessari selezione e prototipo",
    proposeSelection: "Crea diff di selezione e prototipo",
    selectionHelp:
      "La selezione viene proposta come diff immutabile. Non viene applicata finché il proprietario non approva il diff.",
    diffs: "Diff del Design Package da revisionare",
    noDiffs: "Nessuna revisione del design è in attesa di una decisione.",
    changes: "Modifiche",
    approveDiff: "Approva diff",
    rejectDiff: "Rifiuta diff",
    reason: "Motivazione della decisione",
    reasonRequired:
      "Per il rifiuto o per una richiesta di revisione del Gate 5 è necessaria una motivazione.",
    prototype: "Prototipo dichiarativo affidabile",
    concerns: "Criticità di design",
    openQuestions: "Domande aperte",
    gate: "Gate 5 · Approvazione design",
    gateStatus: "Stato gate",
    submitGate: "Invia il Design Package corrente",
    approveGate: "Approva Gate 5",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla gate",
    ready: "Pronto per architettura e piano di test.",
    notReady: "È ancora necessaria l'approvazione del design.",
    methodology:
      "Il Gate 5 approva ID, versione e hash esatti del Design Package. L'approvazione del proprietario è governance, non validazione empirica. Il feedback sintetico dei User Twin resta un'ipotesi progettuale.",
    history: "Cronologia Design Package",
    createdAt: "Creata {date}",
    loadError: "Non è stato possibile caricare la fase di design.",
    chooseAlternative: "Seleziona un'alternativa di design prima di creare la revisione.",
    pendingDiff: "Decidi il diff proposto esistente prima di creare un'altra revisione.",
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
const canProposeSelection = computed(() => {
  if (packageValue.value === null || selectedAlternativeId.value === null) {
    return false;
  }

  if (pendingDiff.value !== null) {
    return false;
  }

  return (
    packageValue.value.owner_selected_alternative_id !== selectedAlternativeId.value ||
    packageValue.value.prototype === null ||
    packageValue.value.prototype.design_alternative_id !== selectedAlternativeId.value
  );
});

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
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
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

  const proposed = buildSelectedDesignPackage(packageValue.value, selectedAlternativeId.value);

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
  <section class="grid gap-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
    <header class="grid gap-2">
      <p class="m-0 text-xs font-black tracking-widest text-indigo-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-2xl font-black text-slate-950">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-slate-600">{{ copy.intro }}</p>
    </header>

    <p class="m-0 rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950">
      {{ copy.methodology }}
    </p>

    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ copy.loading }}
    </p>

    <p
      v-if="localError !== null || store.error !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.error?.message ?? copy.loadError }}
    </p>

    <template v-if="current === null">
      <p class="m-0 text-slate-600">{{ copy.noPackage }}</p>
      <button
        type="button"
        class="justify-self-start rounded-xl bg-indigo-700 px-5 py-3 font-black text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
        :disabled="store.isBusy"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </template>

    <template v-else>
      <section class="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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
      </section>

      <DesignAlternativeComparison
        :alternatives="current.package.alternatives"
        :critiques="current.package.critiques"
        :recommended-alternative-id="current.package.recommended_alternative_id"
        :selected-alternative-id="selectedAlternativeId"
        :disabled="store.isBusy || pendingDiff !== null"
        :locale="locale"
        @select="selectedAlternativeId = $event"
      />

      <section class="grid gap-3 rounded-2xl border border-indigo-200 bg-indigo-50 p-4">
        <p class="m-0 text-sm text-indigo-950">{{ copy.selectionHelp }}</p>
        <button
          type="button"
          class="justify-self-start rounded-xl bg-indigo-700 px-5 py-3 font-black text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
          :disabled="store.isBusy || !canProposeSelection"
          @click="proposeSelection"
        >
          {{ copy.proposeSelection }}
        </button>
      </section>

      <section class="grid gap-4" aria-labelledby="design-diffs-title">
        <h3 id="design-diffs-title" class="text-xl font-black text-slate-950">
          {{ copy.diffs }}
        </h3>

        <p v-if="diffs.length === 0" class="m-0 text-slate-600">{{ copy.noDiffs }}</p>

        <article
          v-for="diff in diffs"
          :key="diff.id"
          class="grid gap-4 rounded-2xl border border-slate-200 p-4"
        >
          <header class="flex flex-wrap items-center justify-between gap-3">
            <p class="m-0 font-black text-slate-950">{{ diff.status }} · {{ diff.id }}</p>
            <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-700">
              {{ diff.changes.length }} {{ copy.changes }}
            </span>
          </header>

          <ul class="grid gap-2 text-sm text-slate-700">
            <li
              v-for="change in diff.changes"
              :key="`${change.artifact_kind}:${change.artifact_id}`"
              class="rounded-lg bg-slate-50 p-3"
            >
              {{ change.kind }} · {{ change.artifact_kind }} · {{ change.artifact_id }}
            </li>
          </ul>

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

      <section v-if="current.package.prototype !== null" class="grid gap-4">
        <h3 class="text-xl font-black text-slate-950">{{ copy.prototype }}</h3>
        <DeclarativePrototypePreview :prototype="current.package.prototype" :locale="locale" />
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
          {{ copy.gateStatus }}: {{ store.gate?.status ?? "NOT_SUBMITTED" }}
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

      <section class="grid gap-3">
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
      </section>
    </template>
  </section>
</template>
