<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { architectureApi, type ArchitectureApi } from "../api/architecture";
import { useArchitectureStore, type AuthorizedRequest } from "../stores/architecture";
import { useAuthStore } from "../stores/auth";
import type {
  ArchitectureGateDecisionAction,
  ArchitecturePackageDiffPayload,
  ArchitectureRevisionDecision,
} from "../types/architecture";
import ArchitecturePlanReview from "./ArchitecturePlanReview.vue";
import { buildArchitecturePackageRevision } from "./architecturePlanning";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedRequest;
    api?: ArchitectureApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useArchitectureStore();
const localError = ref<string | null>(null);
const openQuestionsDraft = ref("");
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});

const messages = {
  en: {
    eyebrow: "Architecture and test planning · Gate 6",
    title: "Architecture Package and implementation readiness",
    intro:
      "Review the architecture, its exact approved grounding, the traceable test plan, owner-controlled revisions, and Gate 6.",
    methodology:
      "Gate 6 approves one exact Architecture Package ID, version, and content hash. The decision authorizes the next workflow stage but does not validate simulated user behavior.",
    loading: "Updating Architecture state…",
    generate: "Generate architecture and test plan",
    noPackage: "No Architecture Package has been generated yet.",
    version: "Version",
    contentHash: "Content hash",
    createdAt: "Created {date}",
    revision: "Owner-controlled revision",
    revisionHelp:
      "Edit the package-level open questions. The change becomes an immutable diff and is applied only after owner approval.",
    questionsLabel: "One open question per line",
    proposeRevision: "Propose Architecture Package revision",
    pendingRevision: "Decide the current proposed diff before creating another revision.",
    noChanges: "Change at least one package-level open question before proposing a revision.",
    diffs: "Architecture Package diffs",
    noDiffs: "No Architecture Package diff is waiting for review.",
    changes: "Changes",
    reason: "Decision reason",
    approveDiff: "Approve diff",
    rejectDiff: "Reject diff",
    reasonRequired: "A reason is required for rejection or a Gate 6 revision request.",
    gate: "Gate 6 · Architecture and test plan approval",
    gateStatus: "Gate status",
    submitGate: "Submit current Architecture Package",
    approveGate: "Approve Gate 6",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel gate",
    ready: "Ready for implementation.",
    notReady: "Architecture and test plan approval is still required.",
    history: "Architecture Package history",
    loadError: "The Architecture stage could not be loaded.",
  },
  it: {
    eyebrow: "Architettura e piano di test · Gate 6",
    title: "Architecture Package e readiness per l'implementazione",
    intro:
      "Revisiona l'architettura, il grounding approvato esatto, il piano di test tracciabile, le revisioni controllate dal proprietario e il Gate 6.",
    methodology:
      "Il Gate 6 approva ID, versione e hash esatti dell'Architecture Package. La decisione autorizza la fase successiva del workflow, ma non valida il comportamento simulato degli utenti.",
    loading: "Aggiornamento dello stato dell'architettura…",
    generate: "Genera architettura e piano di test",
    noPackage: "Non è stato ancora generato alcun Architecture Package.",
    version: "Versione",
    contentHash: "Hash del contenuto",
    createdAt: "Creata {date}",
    revision: "Revisione controllata dal proprietario",
    revisionHelp:
      "Modifica le domande aperte a livello di package. La modifica diventa un diff immutabile e viene applicata solo dopo l'approvazione del proprietario.",
    questionsLabel: "Una domanda aperta per riga",
    proposeRevision: "Proponi revisione dell'Architecture Package",
    pendingRevision: "Decidi il diff proposto corrente prima di creare un'altra revisione.",
    noChanges: "Modifica almeno una domanda aperta del package prima di proporre la revisione.",
    diffs: "Diff dell'Architecture Package",
    noDiffs: "Nessun diff dell'Architecture Package è in attesa di revisione.",
    changes: "Modifiche",
    reason: "Motivazione della decisione",
    approveDiff: "Approva diff",
    rejectDiff: "Rifiuta diff",
    reasonRequired:
      "Per il rifiuto o per una richiesta di revisione del Gate 6 è necessaria una motivazione.",
    gate: "Gate 6 · Approvazione architettura e piano di test",
    gateStatus: "Stato gate",
    submitGate: "Invia l'Architecture Package corrente",
    approveGate: "Approva Gate 6",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla gate",
    ready: "Pronto per l'implementazione.",
    notReady: "È ancora necessaria l'approvazione di architettura e piano di test.",
    history: "Cronologia Architecture Package",
    loadError: "Non è stato possibile caricare la fase di architettura.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? architectureApi);
const current = computed(() => store.current);
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
  if (store.current === null) {
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

async function proposeRevision(): Promise<void> {
  if (pendingDiff.value !== null) {
    localError.value = copy.value.pendingRevision;
    return;
  }

  if (current.value === null) {
    return;
  }

  const proposed = buildArchitecturePackageRevision(
    current.value.package,
    openQuestionsDraft.value,
  );

  if (
    JSON.stringify(proposed.open_questions) === JSON.stringify(current.value.package.open_questions)
  ) {
    localError.value = copy.value.noChanges;
    return;
  }

  await run(() => store.proposeRevision(props.projectId, proposed, authorizedRequest, api.value));
}

async function decideDiff(
  diff: ArchitecturePackageDiffPayload,
  decision: ArchitectureRevisionDecision,
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

async function decideGate(action: ArchitectureGateDecisionAction): Promise<void> {
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
    openQuestionsDraft.value = store.current?.package.open_questions.join("\n") ?? "";
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
  <section
    class="grid gap-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7"
    data-testid="project-architecture-flow"
  >
    <header class="grid gap-2">
      <p class="m-0 text-xs font-black tracking-widest text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-2xl font-black text-slate-950">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-slate-600">{{ copy.intro }}</p>
    </header>

    <p class="m-0 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm text-violet-950">
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

    <div v-if="current === null" class="grid justify-items-start gap-4">
      <p class="m-0 text-slate-600">{{ copy.noPackage }}</p>
      <button
        type="button"
        class="rounded-xl bg-violet-700 px-4 py-3 font-black text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="store.isBusy"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </div>

    <template v-else>
      <div class="grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
        <p class="m-0 font-black text-slate-900">{{ copy.version }} {{ current.version_number }}</p>
        <p class="m-0 text-slate-600">
          {{ copy.createdAt.replace("{date}", formatDate(current.created_at)) }}
        </p>
        <p class="m-0 text-xs break-all text-slate-500">
          {{ copy.contentHash }}: <code>{{ current.content_hash }}</code>
        </p>
      </div>

      <ArchitecturePlanReview :package-value="current.package" :locale="locale" />

      <section class="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <div class="grid gap-1">
          <h3 class="text-xl font-black text-slate-950">{{ copy.revision }}</h3>
          <p class="m-0 text-sm text-slate-600">{{ copy.revisionHelp }}</p>
        </div>
        <label class="grid gap-2 font-bold text-slate-900">
          {{ copy.questionsLabel }}
          <textarea
            v-model="openQuestionsDraft"
            class="min-h-32 rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal text-slate-900"
            :disabled="pendingDiff !== null || store.isBusy"
          />
        </label>
        <button
          type="button"
          class="justify-self-start rounded-xl bg-slate-950 px-4 py-3 font-black text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="pendingDiff !== null || store.isBusy"
          @click="proposeRevision"
        >
          {{ copy.proposeRevision }}
        </button>
      </section>

      <section class="grid gap-4" aria-labelledby="architecture-diff-title">
        <h3 id="architecture-diff-title" class="text-xl font-black text-slate-950">
          {{ copy.diffs }}
        </h3>
        <p v-if="store.diffHistory.length === 0" class="m-0 text-slate-600">
          {{ copy.noDiffs }}
        </p>
        <article
          v-for="diff in store.diffHistory"
          :key="diff.id"
          class="grid gap-4 rounded-2xl border border-slate-200 p-5"
        >
          <div class="grid gap-1">
            <p class="m-0 text-xs font-bold break-all text-slate-500">{{ diff.id }}</p>
            <p class="m-0 font-black text-slate-950">
              {{ diff.status }} · {{ copy.changes }}: {{ diff.changes.length }}
            </p>
          </div>
          <ul class="list-disc pl-5 text-sm text-slate-700">
            <li
              v-for="change in diff.changes"
              :key="`${change.artifact_kind}:${change.artifact_id}`"
            >
              {{ change.kind }} · {{ change.artifact_kind }} · {{ change.artifact_id }}
            </li>
          </ul>
          <template v-if="diff.status === 'PROPOSED'">
            <label class="grid gap-2 font-bold text-slate-900">
              {{ copy.reason }}
              <textarea
                v-model="diffReasons[diff.id]"
                class="min-h-24 rounded-xl border border-slate-300 px-3 py-2 font-normal"
              />
            </label>
            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="rounded-xl bg-emerald-700 px-4 py-2 font-black text-white hover:bg-emerald-800"
                @click="decideDiff(diff, 'APPROVE')"
              >
                {{ copy.approveDiff }}
              </button>
              <button
                type="button"
                class="rounded-xl border border-red-300 bg-red-50 px-4 py-2 font-black text-red-800 hover:bg-red-100"
                @click="decideDiff(diff, 'REJECT')"
              >
                {{ copy.rejectDiff }}
              </button>
            </div>
          </template>
        </article>
      </section>

      <section class="grid gap-4 rounded-2xl border border-violet-200 bg-violet-50 p-5">
        <div class="grid gap-1">
          <h3 class="text-xl font-black text-violet-950">{{ copy.gate }}</h3>
          <p class="m-0 font-bold text-violet-900">
            {{ copy.gateStatus }}: {{ store.gate?.status ?? "NOT_SUBMITTED" }}
          </p>
        </div>

        <button
          v-if="canSubmitGate"
          type="button"
          class="justify-self-start rounded-xl bg-violet-700 px-4 py-3 font-black text-white hover:bg-violet-800"
          @click="submitGate"
        >
          {{ copy.submitGate }}
        </button>

        <template v-if="gatePending || gatePaused">
          <label class="grid gap-2 font-bold text-violet-950">
            {{ copy.reason }}
            <textarea
              v-model="gateReason"
              class="min-h-24 rounded-xl border border-violet-300 bg-white px-3 py-2 font-normal text-slate-900"
            />
          </label>
          <div class="flex flex-wrap gap-3">
            <template v-if="gatePending">
              <button
                type="button"
                class="rounded-xl bg-emerald-700 px-4 py-2 font-black text-white hover:bg-emerald-800"
                @click="decideGate('APPROVE')"
              >
                {{ copy.approveGate }}
              </button>
              <button
                type="button"
                class="rounded-xl border border-amber-300 bg-amber-50 px-4 py-2 font-black text-amber-900"
                @click="decideGate('REQUEST_REVISION')"
              >
                {{ copy.requestRevision }}
              </button>
              <button
                type="button"
                class="rounded-xl border border-red-300 bg-red-50 px-4 py-2 font-black text-red-800"
                @click="decideGate('REJECT')"
              >
                {{ copy.rejectGate }}
              </button>
              <button
                type="button"
                class="rounded-xl border border-slate-300 bg-white px-4 py-2 font-black text-slate-800"
                @click="decideGate('PAUSE')"
              >
                {{ copy.pause }}
              </button>
            </template>
            <button
              v-if="gatePaused"
              type="button"
              class="rounded-xl bg-violet-700 px-4 py-2 font-black text-white"
              @click="decideGate('RESUME')"
            >
              {{ copy.resume }}
            </button>
            <button
              type="button"
              class="rounded-xl border border-slate-300 bg-white px-4 py-2 font-black text-slate-800"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancelGate }}
            </button>
          </div>
        </template>

        <p
          class="m-0 font-black"
          :class="store.isReadyForImplementation ? 'text-emerald-800' : 'text-violet-900'"
        >
          {{ store.isReadyForImplementation ? copy.ready : copy.notReady }}
        </p>
      </section>

      <section class="grid gap-3" aria-labelledby="architecture-history-title">
        <h3 id="architecture-history-title" class="text-xl font-black text-slate-950">
          {{ copy.history }}
        </h3>
        <ol class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <li
            v-for="version in store.history"
            :key="version.id"
            class="grid gap-2 rounded-xl border border-slate-200 p-4"
          >
            <p class="m-0 font-black text-slate-900">
              {{ copy.version }} {{ version.version_number }}
            </p>
            <p class="m-0 text-sm text-slate-600">{{ formatDate(version.created_at) }}</p>
            <code class="text-xs break-all text-slate-500">{{ version.content_hash }}</code>
          </li>
        </ol>
      </section>
    </template>
  </section>
</template>
