<script setup lang="ts">
import TwinIdentity from "./TwinIdentity.vue";
import { modelFeedback, generationProgress } from "./modelFeedback";
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
import { workflowStatusLabel } from "./workflowLabels";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    prerequisiteReady?: boolean;
    authorize?: AuthorizedRequest;
    api?: ArchitectureApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
    prerequisiteReady: true,
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
    eyebrow: "Your solution",
    title: "How we will build your app",
    intro:
      "Review the proposed solution and the checks planned for your app, then confirm to start building.",
    methodology:
      "Gate 6 approves one exact Architecture Package ID, version, and content hash. The decision authorizes the next workflow stage but does not validate simulated user behavior.",
    loading: "Updating the solution…",
    generate: "Prepare the solution",
    noPackage: "The team is ready to plan how to build your app.",
    version: "Version",
    contentHash: "Content hash",
    createdAt: "Created {date}",
    revision: "Questions to resolve",
    revisionHelp:
      "Add or edit the questions the team should resolve. You will review the changes before applying them.",
    questionsLabel: "One open question per line",
    proposeRevision: "Review these changes",
    pendingRevision: "Review the pending changes before proposing more.",
    noChanges: "Edit at least one question before proposing changes.",
    diffs: "Changes to review",
    noDiffs: "No changes are waiting for review.",
    changes: "Changes",
    reason: "Decision reason",
    approveDiff: "Apply changes",
    rejectDiff: "Discard changes",
    reasonRequired: "A reason is required to reject or request changes.",
    gate: "Confirm the solution",
    gateStatus: "Status",
    submitGate: "Prepare for approval",
    approveGate: "Approve solution",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel approval",
    ready: "The solution is approved. You can now create your app.",
    notReady: "Review and approve the solution to continue.",
    history: "Previous versions",
    technical: "Technical plan and checks",
    audit: "Version and decision details",
    loadError: "The Architecture stage could not be loaded.",
  },
  it: {
    eyebrow: "La tua soluzione",
    title: "Come realizzeremo la tua app",
    intro:
      "Esamina la soluzione proposta e le verifiche previste, poi conferma per iniziare a creare la tua app.",
    methodology:
      "Il Gate 6 approva ID, versione e hash esatti dell'Architecture Package. La decisione autorizza la fase successiva del workflow, ma non valida il comportamento simulato degli utenti.",
    loading: "Aggiornamento della soluzione…",
    generate: "Prepara la soluzione",
    noPackage: "Il team è pronto a pianificare come realizzare la tua app.",
    version: "Versione",
    contentHash: "Hash del contenuto",
    createdAt: "Creata {date}",
    revision: "Domande da risolvere",
    revisionHelp:
      "Aggiungi o modifica le domande da chiarire con il team. Potrai controllare le modifiche prima di applicarle.",
    questionsLabel: "Una domanda aperta per riga",
    proposeRevision: "Controlla le modifiche",
    pendingRevision: "Valuta le modifiche in attesa prima di proporne altre.",
    noChanges: "Modifica almeno una domanda prima di proporre una revisione.",
    diffs: "Modifiche da valutare",
    noDiffs: "Nessuna modifica in attesa di una decisione.",
    changes: "Modifiche",
    reason: "Motivazione della decisione",
    approveDiff: "Applica modifiche",
    rejectDiff: "Scarta modifiche",
    reasonRequired: "Scrivi una motivazione per rifiutare o richiedere modifiche.",
    gate: "Conferma la soluzione",
    gateStatus: "Stato",
    submitGate: "Prepara per l'approvazione",
    approveGate: "Approva la soluzione",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla approvazione",
    ready: "La soluzione è approvata. Ora puoi creare la tua app.",
    notReady: "Controlla e approva la soluzione per continuare.",
    history: "Versioni precedenti",
    technical: "Piano tecnico e verifiche",
    audit: "Dettagli di versione e decisioni",
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
    class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
    data-testid="project-architecture-flow"
  >
    <header class="grid gap-2">
      <TwinIdentity role="SOFTWARE_ARCHITECT" :locale="locale" compact />
      <p class="m-0 text-xs font-black tracking-widest text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-xl font-bold text-slate-950">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-slate-600">{{ copy.intro }}</p>
    </header>

    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ store.pending.generate ? generationProgress(locale) : copy.loading }}
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

    <div v-if="current === null" class="grid justify-items-start gap-4">
      <p class="m-0 text-slate-600">{{ copy.noPackage }}</p>
      <p v-if="!prerequisiteReady" role="status" class="text-sm text-slate-700">
        {{
          locale === "it"
            ? "Scegli e approva l'aspetto della tua app per continuare."
            : "Choose and approve your app's design to continue."
        }}
      </p>
      <button
        type="button"
        class="rounded-xl bg-violet-700 px-4 py-3 font-black text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="store.isBusy || !prerequisiteReady"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </div>

    <template v-else>
      <details class="rounded-xl border border-slate-200 p-3 text-sm">
        <summary class="cursor-pointer font-semibold text-slate-700">{{ copy.audit }}</summary>
        <p class="my-3 text-slate-600">{{ copy.methodology }}</p>
        <p class="m-0 font-black text-slate-900">{{ copy.version }} {{ current.version_number }}</p>
        <p class="m-0 text-slate-600">
          {{ copy.createdAt.replace("{date}", formatDate(current.created_at)) }}
        </p>
        <p class="m-0 text-xs break-all text-slate-500">
          {{ copy.contentHash }}: <code>{{ current.content_hash }}</code>
        </p>
      </details>

      <section class="grid gap-2 rounded-xl bg-slate-50 p-4">
        <h3 class="font-semibold text-slate-950">{{ current.package.architecture.title }}</h3>
        <p class="m-0 text-sm leading-6 text-slate-700">
          {{ current.package.architecture.summary }}
        </p>
        <p class="m-0 text-sm leading-6 text-slate-600">{{ current.package.test_plan.strategy }}</p>
      </section>
      <details
        class="rounded-xl border border-slate-200 p-3"
        data-testid="architecture-technical-details"
      >
        <summary class="cursor-pointer font-semibold text-slate-700">{{ copy.technical }}</summary>
        <div class="mt-4">
          <ArchitecturePlanReview :package-value="current.package" :locale="locale" />
        </div>
      </details>

      <details class="rounded-xl border border-slate-200 p-4">
        <summary class="cursor-pointer font-semibold text-slate-900">{{ copy.revision }}</summary>
        <div class="mt-4 grid gap-4">
          <p class="m-0 text-sm text-slate-600">{{ copy.revisionHelp }}</p>
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
        </div>
      </details>

      <details
        v-if="store.diffHistory.length"
        :open="pendingDiff !== null"
        class="rounded-xl border border-slate-200 p-4"
      >
        <summary id="architecture-diff-title" class="cursor-pointer font-semibold text-slate-950">
          {{ copy.diffs }}
        </summary>
        <p v-if="store.diffHistory.length === 0" class="m-0 text-slate-600">
          {{ copy.noDiffs }}
        </p>
        <article
          v-for="diff in store.diffHistory"
          :key="diff.id"
          class="mt-4 grid gap-4 rounded-xl border border-slate-200 p-4"
        >
          <div class="grid gap-1">
            <p class="m-0 font-black text-slate-950">
              {{ workflowStatusLabel(diff.status, locale) }} · {{ copy.changes }}:
              {{ diff.changes.length }}
            </p>
          </div>
          <div
            v-if="diff.changes.some((change) => change.artifact_kind === 'OPEN_QUESTIONS')"
            class="grid gap-2 text-sm text-slate-700"
          >
            <strong>{{ copy.revision }}</strong>
            <ul v-if="diff.proposed_package.open_questions.length" class="list-disc pl-5">
              <li v-for="question in diff.proposed_package.open_questions" :key="question">
                {{ question }}
              </li>
            </ul>
            <p v-else class="m-0">
              {{ locale === "it" ? "Nessuna domanda rimasta." : "No remaining questions." }}
            </p>
          </div>
          <details class="text-sm text-slate-600">
            <summary class="cursor-pointer">{{ copy.audit }}</summary>
            <p class="text-xs break-all">{{ diff.id }} · {{ diff.status }}</p>
            <ul class="list-disc pl-5 text-sm text-slate-700">
              <li
                v-for="change in diff.changes"
                :key="`${change.artifact_kind}:${change.artifact_id}`"
              >
                {{ change.kind }} · {{ change.artifact_kind }} · {{ change.artifact_id }}
              </li>
            </ul>
          </details>
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
      </details>

      <section class="grid gap-4 rounded-2xl border border-violet-200 bg-violet-50 p-5">
        <div class="grid gap-1">
          <h3 class="text-xl font-black text-violet-950">{{ copy.gate }}</h3>
          <p class="m-0 font-bold text-violet-900">
            {{ copy.gateStatus }}: {{ workflowStatusLabel(store.gate?.status, locale) }}
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

      <details class="rounded-xl border border-slate-200 p-4">
        <summary
          id="architecture-history-title"
          class="cursor-pointer font-semibold text-slate-700"
        >
          {{ copy.history }}
        </summary>
        <ol class="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
      </details>
    </template>
  </section>
</template>
