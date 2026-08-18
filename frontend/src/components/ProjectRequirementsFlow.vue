<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { requirementsApi, type RequirementsApi } from "../api/requirements";
import { useAuthStore } from "../stores/auth";
import { type AuthorizedRequest, useRequirementsStore } from "../stores/requirements";
import type {
  RequirementKind,
  RequirementPayload,
  RequirementPriority,
  RequirementsArtifactEnvelope,
  RequirementsGateDecisionAction,
  RequirementsSpecificationDiffPayload,
  RequirementsSpecificationPayload,
} from "../types/requirements";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedRequest;
    api?: RequirementsApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useRequirementsStore();
const localError = ref<string | null>(null);
const editingRequirementId = ref<string | null>(null);
const gateReason = ref("");
const diffReasons = reactive<Record<string, string>>({});
const edit = reactive({
  title: "",
  statement: "",
  kind: "FUNCTIONAL" as RequirementKind,
  priority: "MUST" as RequirementPriority,
});

const messages = {
  en: {
    eyebrow: "Requirements · Gate 4",
    title: "Requirements and Definition of Done",
    intro:
      "Review the specification grounded in the approved Brief, Agent Team, and User Modeling snapshot.",
    loading: "Updating Requirements state…",
    generate: "Generate requirements specification",
    noSpecification: "No requirements specification has been generated yet.",
    version: "Version",
    current: "Current specification",
    requirements: "Requirements",
    userStories: "User stories",
    criteria: "Acceptance criteria",
    scenarios: "Usage scenarios",
    risks: "Project risks",
    done: "Definition of Done",
    edit: "Propose revision",
    saveRevision: "Create specification diff",
    cancel: "Cancel",
    titleLabel: "Title",
    statementLabel: "Statement",
    kindLabel: "Kind",
    priorityLabel: "Priority",
    sources: "Sources",
    twins: "User Twins",
    goal: "Goal",
    benefit: "Benefit",
    verification: "Verification",
    trigger: "Trigger",
    outcome: "Expected outcome",
    mitigation: "Mitigation",
    condition: "Condition",
    none: "None",
    diffs: "Reviewable specification diffs",
    proposed: "Proposed",
    approved: "Approved",
    rejected: "Rejected",
    before: "Before",
    after: "After",
    approveDiff: "Approve diff",
    rejectDiff: "Reject diff",
    reason: "Decision reason",
    reasonRequired: "A reason is required for rejection or revision.",
    invalidEdit: "Enter a normalized title and statement before proposing the revision.",
    gate: "Gate 4 · Requirements approval",
    gateStatus: "Gate status",
    submitGate: "Submit current specification",
    approveGate: "Approve Gate 4",
    rejectGate: "Reject",
    requestRevision: "Request revision",
    pause: "Pause",
    resume: "Resume",
    cancelGate: "Cancel gate",
    ready: "Ready for design exploration.",
    notReady: "Requirements approval is still required.",
    methodology:
      "Gate 4 approves the exact specification ID, version, and content hash. A later version requires a new approval.",
    loadError: "The Requirements stage could not be loaded.",
  },
  it: {
    eyebrow: "Requisiti · Gate 4",
    title: "Requisiti e Definition of Done",
    intro:
      "Revisiona la specifica fondata su Project Brief, Agent Team e snapshot User Modeling approvati.",
    loading: "Aggiornamento dello stato dei requisiti…",
    generate: "Genera la specifica dei requisiti",
    noSpecification: "Non è stata ancora generata alcuna specifica dei requisiti.",
    version: "Versione",
    current: "Specifica corrente",
    requirements: "Requisiti",
    userStories: "User story",
    criteria: "Criteri di accettazione",
    scenarios: "Scenari d'uso",
    risks: "Rischi di progetto",
    done: "Definition of Done",
    edit: "Proponi revisione",
    saveRevision: "Crea diff della specifica",
    cancel: "Annulla",
    titleLabel: "Titolo",
    statementLabel: "Dichiarazione",
    kindLabel: "Tipo",
    priorityLabel: "Priorità",
    sources: "Fonti",
    twins: "User Twin",
    goal: "Obiettivo",
    benefit: "Beneficio",
    verification: "Verifica",
    trigger: "Evento iniziale",
    outcome: "Risultato atteso",
    mitigation: "Mitigazione",
    condition: "Condizione",
    none: "Nessuno",
    diffs: "Diff della specifica da revisionare",
    proposed: "Proposta",
    approved: "Approvata",
    rejected: "Rifiutata",
    before: "Prima",
    after: "Dopo",
    approveDiff: "Approva diff",
    rejectDiff: "Rifiuta diff",
    reason: "Motivazione della decisione",
    reasonRequired: "Per rifiuto o richiesta di revisione è necessaria una motivazione.",
    invalidEdit: "Inserisci titolo e dichiarazione normalizzati prima della revisione.",
    gate: "Gate 4 · Approvazione requisiti",
    gateStatus: "Stato gate",
    submitGate: "Invia la specifica corrente",
    approveGate: "Approva Gate 4",
    rejectGate: "Rifiuta",
    requestRevision: "Richiedi revisione",
    pause: "Pausa",
    resume: "Riprendi",
    cancelGate: "Annulla gate",
    ready: "Pronto per l'esplorazione del design.",
    notReady: "È ancora necessaria l'approvazione dei requisiti.",
    methodology:
      "Gate 4 approva ID, versione e hash esatti della specifica. Una versione successiva richiede una nuova approvazione.",
    loadError: "Non è stato possibile caricare la fase dei requisiti.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? requirementsApi);
const current = computed(() => store.current);
const specification = computed(() => store.current?.specification ?? null);
const diffs = computed(() => store.diffHistory);
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

function startEdit(requirement: RequirementPayload): void {
  editingRequirementId.value = requirement.id;
  edit.title = requirement.title;
  edit.statement = requirement.statement;
  edit.kind = requirement.kind;
  edit.priority = requirement.priority;
}

function cancelEdit(): void {
  editingRequirementId.value = null;
  edit.title = "";
  edit.statement = "";
  edit.kind = "FUNCTIONAL";
  edit.priority = "MUST";
}

function proposedSpecification(): RequirementsSpecificationPayload | null {
  const value = specification.value;
  const requirementId = editingRequirementId.value;

  if (
    value === null ||
    requirementId === null ||
    edit.title.trim().length === 0 ||
    edit.statement.trim().length === 0
  ) {
    return null;
  }

  return {
    ...value,
    requirements: value.requirements.map((requirement) =>
      requirement.id === requirementId
        ? {
            ...requirement,
            title: edit.title.trim().replace(/\s+/g, " "),
            statement: edit.statement.trim().replace(/\s+/g, " "),
            kind: edit.kind,
            priority: edit.priority,
          }
        : requirement,
    ),
  };
}

async function submitRevision(): Promise<void> {
  const proposed = proposedSpecification();

  if (proposed === null) {
    localError.value = copy.value.invalidEdit;
    return;
  }

  const applied = await run(() =>
    store.proposeRevision(props.projectId, proposed, authorizedRequest, api.value),
  );

  if (applied) {
    cancelEdit();
  }
}

function diffReason(diffId: string): string {
  return diffReasons[diffId] ?? "";
}

async function decideDiff(
  diff: RequirementsSpecificationDiffPayload,
  decision: "APPROVE" | "REJECT",
): Promise<void> {
  const reason = diffReason(diff.id).trim();

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

async function decideGate(action: RequirementsGateDecisionAction): Promise<void> {
  const reason = gateReason.value.trim();

  if ((action === "REJECT" || action === "REQUEST_REVISION") && reason.length === 0) {
    localError.value = copy.value.reasonRequired;
    return;
  }

  await run(() =>
    store.decideGate(
      props.projectId,
      action,
      authorizedRequest,
      reason.length === 0 ? null : reason,
      api.value,
    ),
  );
}

function envelopeSummary(envelope: RequirementsArtifactEnvelope | null): string {
  if (envelope === null) {
    return copy.value.none;
  }

  switch (envelope.kind) {
    case "REQUIREMENT":
      return envelope.requirement?.statement ?? copy.value.none;
    case "USER_STORY":
      return envelope.user_story?.goal ?? copy.value.none;
    case "ACCEPTANCE_CRITERION":
      return envelope.acceptance_criterion?.statement ?? copy.value.none;
    case "SCENARIO":
      return envelope.scenario?.expected_outcome ?? copy.value.none;
    case "RISK":
      return envelope.risk?.summary ?? copy.value.none;
    case "DEFINITION_OF_DONE":
      return envelope.definition_of_done?.statement ?? copy.value.none;
  }
}

function diffStatusLabel(status: RequirementsSpecificationDiffPayload["status"]): string {
  if (status === "APPROVED") {
    return copy.value.approved;
  }

  if (status === "REJECTED") {
    return copy.value.rejected;
  }

  return copy.value.proposed;
}

watch(
  () => [props.projectId, props.autoLoad] as const,
  ([projectId, autoLoad]) => {
    if (autoLoad && projectId.trim().length > 0) {
      void load();
    }
  },
  {
    immediate: true,
  },
);
</script>

<template>
  <section class="grid gap-6" aria-labelledby="requirements-flow-title">
    <header class="grid gap-2 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <p class="m-0 text-xs font-bold tracking-[0.16em] text-slate-500 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="requirements-flow-title" class="text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-sm leading-6 text-slate-600">
        {{ copy.intro }}
      </p>
      <p v-if="store.isBusy" class="m-0 text-sm font-semibold text-slate-600" role="status">
        {{ copy.loading }}
      </p>
      <p
        v-if="localError !== null || store.error !== null"
        class="m-0 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-semibold text-red-800"
        role="alert"
      >
        {{ localError ?? store.error?.message ?? copy.loadError }}
      </p>
    </header>

    <section
      v-if="current === null"
      class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <p class="m-0 text-slate-600">
        {{ copy.noSpecification }}
      </p>
      <button
        type="button"
        class="w-fit rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white hover:bg-slate-800 disabled:opacity-50"
        :disabled="store.isBusy"
        data-testid="generate-requirements"
        @click="generate"
      >
        {{ copy.generate }}
      </button>
    </section>

    <template v-else-if="specification !== null">
      <section class="grid gap-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 class="text-xl font-black text-slate-950">
              {{ copy.current }}
            </h3>
            <p class="m-0 text-sm text-slate-600">
              {{ copy.version }} {{ current.version_number }}
            </p>
          </div>
          <code class="max-w-full rounded bg-slate-100 px-2 py-1 text-xs break-all text-slate-500">
            {{ current.content_hash }}
          </code>
        </div>

        <section class="grid gap-3" aria-labelledby="requirements-list-title">
          <h4 id="requirements-list-title" class="text-lg font-black text-slate-950">
            {{ copy.requirements }}
          </h4>
          <article
            v-for="requirement in specification.requirements"
            :key="requirement.id"
            class="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4"
          >
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p class="m-0 text-xs font-bold tracking-wide text-slate-500 uppercase">
                  {{ requirement.code }} · {{ requirement.kind }} · {{ requirement.priority }}
                </p>
                <h5 class="mt-1 font-black text-slate-950">
                  {{ requirement.title }}
                </h5>
                <p class="mt-2 text-sm leading-6 text-slate-700">
                  {{ requirement.statement }}
                </p>
              </div>
              <button
                type="button"
                class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-100"
                data-testid="edit-requirement"
                @click="startEdit(requirement)"
              >
                {{ copy.edit }}
              </button>
            </div>
            <p class="m-0 text-xs text-slate-500">
              {{ copy.sources }}:
              {{
                requirement.sources.map((source) => source.locator ?? source.source_id).join(", ")
              }}
            </p>
            <p class="m-0 text-xs text-slate-500">
              {{ copy.twins }}:
              {{
                requirement.user_twin_references.length === 0
                  ? copy.none
                  : requirement.user_twin_references.map((twin) => twin.name).join(", ")
              }}
            </p>
          </article>
        </section>

        <form
          v-if="editingRequirementId !== null"
          class="grid gap-4 rounded-xl border border-slate-300 bg-slate-50 p-4"
          @submit.prevent="submitRevision"
        >
          <label class="grid gap-1 text-sm font-bold text-slate-700">
            {{ copy.titleLabel }}
            <input v-model="edit.title" class="rounded-lg border border-slate-300 px-3 py-2" />
          </label>
          <label class="grid gap-1 text-sm font-bold text-slate-700">
            {{ copy.statementLabel }}
            <textarea
              v-model="edit.statement"
              rows="4"
              class="rounded-lg border border-slate-300 px-3 py-2"
              data-testid="requirement-statement"
            />
          </label>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="grid gap-1 text-sm font-bold text-slate-700">
              {{ copy.kindLabel }}
              <select v-model="edit.kind" class="rounded-lg border border-slate-300 px-3 py-2">
                <option value="FUNCTIONAL">FUNCTIONAL</option>
                <option value="NON_FUNCTIONAL">NON_FUNCTIONAL</option>
                <option value="CONSTRAINT">CONSTRAINT</option>
              </select>
            </label>
            <label class="grid gap-1 text-sm font-bold text-slate-700">
              {{ copy.priorityLabel }}
              <select v-model="edit.priority" class="rounded-lg border border-slate-300 px-3 py-2">
                <option value="MUST">MUST</option>
                <option value="SHOULD">SHOULD</option>
                <option value="COULD">COULD</option>
                <option value="WONT_FOR_NOW">WONT_FOR_NOW</option>
              </select>
            </label>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              type="submit"
              class="rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white"
              data-testid="submit-requirements-revision"
            >
              {{ copy.saveRevision }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-bold"
              @click="cancelEdit"
            >
              {{ copy.cancel }}
            </button>
          </div>
        </form>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-slate-950">{{ copy.userStories }}</h4>
          <article
            v-for="story in specification.user_stories"
            :key="story.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ story.code }} · {{ story.user_twin_reference.name }}</strong>
            <p class="mt-2 text-sm text-slate-700">{{ copy.goal }}: {{ story.goal }}</p>
            <p class="m-0 text-sm text-slate-700">{{ copy.benefit }}: {{ story.benefit }}</p>
          </article>
        </section>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-slate-950">{{ copy.criteria }}</h4>
          <article
            v-for="criterion in specification.acceptance_criteria"
            :key="criterion.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ criterion.code }}</strong>
            <p class="mt-2 text-sm text-slate-700">{{ criterion.statement }}</p>
            <p class="m-0 text-xs text-slate-500">
              {{ copy.verification }}: {{ criterion.verification_method }}
            </p>
          </article>
        </section>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-slate-950">{{ copy.scenarios }}</h4>
          <article
            v-for="scenario in specification.scenarios"
            :key="scenario.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ scenario.code }} · {{ scenario.title }}</strong>
            <p class="mt-2 text-sm text-slate-700">{{ copy.trigger }}: {{ scenario.trigger }}</p>
            <ol class="mt-2 list-decimal pl-5 text-sm text-slate-700">
              <li v-for="step in scenario.steps" :key="step">{{ step }}</li>
            </ol>
            <p class="mt-2 text-sm text-slate-700">
              {{ copy.outcome }}: {{ scenario.expected_outcome }}
            </p>
          </article>
        </section>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-slate-950">{{ copy.risks }}</h4>
          <p v-if="specification.risks.length === 0" class="m-0 text-sm text-slate-500">
            {{ copy.none }}
          </p>
          <article
            v-for="risk in specification.risks"
            :key="risk.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ risk.code }} · {{ risk.likelihood }} / {{ risk.impact }}</strong>
            <p class="mt-2 text-sm text-slate-700">{{ risk.summary }}</p>
            <p class="m-0 text-sm text-slate-700">{{ copy.mitigation }}: {{ risk.mitigation }}</p>
          </article>
        </section>

        <section class="grid gap-3">
          <h4 class="text-lg font-black text-slate-950">{{ copy.done }}</h4>
          <article
            v-for="item in specification.definition_of_done"
            :key="item.id"
            class="rounded-xl border border-slate-200 p-4"
          >
            <strong>{{ item.code }} · {{ item.applicability }}</strong>
            <p class="mt-2 text-sm text-slate-700">{{ item.statement }}</p>
            <p v-if="item.condition !== null" class="m-0 text-xs text-slate-500">
              {{ copy.condition }}: {{ item.condition }}
            </p>
          </article>
        </section>
      </section>

      <section
        v-if="diffs.length > 0"
        class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h3 class="text-xl font-black text-slate-950">{{ copy.diffs }}</h3>
        <article
          v-for="diff in diffs"
          :key="diff.id"
          class="grid gap-4 rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-wrap justify-between gap-2">
            <code class="text-xs text-slate-500">{{ diff.id }}</code>
            <strong>{{ diffStatusLabel(diff.status) }}</strong>
          </div>
          <div
            v-for="operation in diff.operations"
            :key="`${operation.artifact_kind}:${operation.artifact_id}`"
            class="grid gap-3 rounded-lg bg-slate-50 p-3 md:grid-cols-2"
          >
            <div>
              <strong class="text-xs tracking-wide text-slate-500 uppercase">
                {{ copy.before }} · {{ operation.display_code }}
              </strong>
              <p class="mt-2 text-sm text-slate-700">{{ envelopeSummary(operation.before) }}</p>
            </div>
            <div>
              <strong class="text-xs tracking-wide text-slate-500 uppercase">
                {{ copy.after }} · {{ operation.operation }}
              </strong>
              <p class="mt-2 text-sm text-slate-700">{{ envelopeSummary(operation.after) }}</p>
            </div>
          </div>
          <div v-if="diff.status === 'PROPOSED'" class="grid gap-3 border-t pt-4">
            <label class="grid gap-1 text-sm font-bold text-slate-700">
              {{ copy.reason }}
              <textarea
                v-model="diffReasons[diff.id]"
                rows="2"
                class="rounded-lg border px-3 py-2"
              />
            </label>
            <div class="flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-bold text-white"
                data-testid="approve-requirements-diff"
                @click="decideDiff(diff, 'APPROVE')"
              >
                {{ copy.approveDiff }}
              </button>
              <button
                type="button"
                class="rounded-lg border border-red-300 px-3 py-2 text-sm font-bold text-red-700"
                :disabled="diffReason(diff.id).trim().length === 0"
                @click="decideDiff(diff, 'REJECT')"
              >
                {{ copy.rejectDiff }}
              </button>
            </div>
          </div>
        </article>
      </section>

      <section class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 class="text-xl font-black text-slate-950">{{ copy.gate }}</h3>
        <p class="m-0 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
          {{ copy.methodology }}
        </p>
        <p class="m-0 text-sm text-slate-700">
          {{ copy.gateStatus }}: <strong>{{ store.gate?.status ?? "—" }}</strong>
        </p>
        <p
          class="m-0 text-sm font-black"
          :class="store.isReadyForDesign ? 'text-emerald-700' : 'text-amber-700'"
          data-testid="requirements-readiness"
        >
          {{ store.isReadyForDesign ? copy.ready : copy.notReady }}
        </p>
        <button
          v-if="canSubmitGate"
          type="button"
          class="w-fit rounded-lg bg-slate-950 px-4 py-2 text-sm font-bold text-white"
          data-testid="submit-requirements-gate"
          @click="submitGate"
        >
          {{ copy.submitGate }}
        </button>
        <div v-if="gatePending || gatePaused" class="grid gap-3">
          <label class="grid gap-1 text-sm font-bold text-slate-700">
            {{ copy.reason }}
            <textarea v-model="gateReason" rows="2" class="rounded-lg border px-3 py-2" />
          </label>
          <div v-if="gatePending" class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-bold text-white"
              data-testid="approve-requirements-gate"
              @click="decideGate('APPROVE')"
            >
              {{ copy.approveGate }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-amber-300 px-3 py-2 text-sm font-bold text-amber-800"
              :disabled="gateReason.trim().length === 0"
              @click="decideGate('REQUEST_REVISION')"
            >
              {{ copy.requestRevision }}
            </button>
            <button
              type="button"
              class="rounded-lg border border-red-300 px-3 py-2 text-sm font-bold text-red-700"
              :disabled="gateReason.trim().length === 0"
              @click="decideGate('REJECT')"
            >
              {{ copy.rejectGate }}
            </button>
            <button
              type="button"
              class="rounded-lg border px-3 py-2 text-sm font-bold"
              @click="decideGate('PAUSE')"
            >
              {{ copy.pause }}
            </button>
            <button
              type="button"
              class="rounded-lg border px-3 py-2 text-sm font-bold"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancelGate }}
            </button>
          </div>
          <div v-else class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg bg-slate-950 px-3 py-2 text-sm font-bold text-white"
              @click="decideGate('RESUME')"
            >
              {{ copy.resume }}
            </button>
            <button
              type="button"
              class="rounded-lg border px-3 py-2 text-sm font-bold"
              @click="decideGate('CANCEL')"
            >
              {{ copy.cancelGate }}
            </button>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>
