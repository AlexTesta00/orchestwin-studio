<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import UserModelingProvenanceInspector from "./UserModelingProvenanceInspector.vue";

import { useUserModelingStore } from "../stores/userModeling";

import type {
  GateDecisionAction,
  ObservationValueKind,
  PersonaOwnerDecision,
  PersonaVersionPayload,
  ProfileObservationPayload,
  ProfileReplacementRequest,
  ProfileRevisionDecision,
  UserTwinField,
  UserTwinProfileDiffPayload,
  UserTwinVersionPayload,
} from "../types/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    accessToken: string;
    locale?: Locale;
    autoLoad?: boolean;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const store = useUserModelingStore();

const personaReasons = reactive<Record<string, string>>({});

const diffReasons = reactive<Record<string, string>>({});

const gateReason = ref("");

const localError = ref<string | null>(null);

const editingTwinId = ref<string | null>(null);

const editingField = ref<UserTwinField | null>(null);

const editingOriginalKind = ref<ObservationValueKind>("TEXT");

const editingValue = ref("");

const revisionEpistemicStatus = ref<"USER_PROVIDED" | "HUMAN_VALIDATED">("USER_PROVIDED");

const userTwinFields = new Set<UserTwinField>([
  "role",
  "age_range",
  "expertise",
  "goals",
  "recurring_tasks",
  "context_of_use",
  "information_needs",
  "decision_criteria",
  "preferred_vocabulary",
  "frustrations",
  "pain_points",
  "trust_concerns",
  "accessibility_needs",
  "operational_constraints",
  "technical_literacy",
  "risk_sensitivity",
  "assumptions",
]);

const multiValueFields = new Set<UserTwinField>([
  "expertise",
  "goals",
  "recurring_tasks",
  "context_of_use",
  "information_needs",
  "decision_criteria",
  "preferred_vocabulary",
  "frustrations",
  "pain_points",
  "trust_concerns",
  "accessibility_needs",
  "operational_constraints",
  "assumptions",
]);

const fieldLabels: Record<Locale, Record<UserTwinField, string>> = {
  en: {
    role: "Role",
    age_range: "Age range",
    expertise: "Expertise",
    goals: "Goals",
    recurring_tasks: "Recurring tasks",
    context_of_use: "Context of use",
    information_needs: "Information needs",
    decision_criteria: "Decision criteria",
    preferred_vocabulary: "Preferred vocabulary",
    frustrations: "Frustrations",
    pain_points: "Pain points",
    trust_concerns: "Trust concerns",
    accessibility_needs: "Accessibility needs",
    operational_constraints: "Operational constraints",
    technical_literacy: "Technical literacy",
    risk_sensitivity: "Risk sensitivity",
    assumptions: "Assumptions",
  },

  it: {
    role: "Ruolo",
    age_range: "Fascia di età",
    expertise: "Competenze",
    goals: "Obiettivi",
    recurring_tasks: "Attività ricorrenti",
    context_of_use: "Contesto d'uso",
    information_needs: "Bisogni informativi",
    decision_criteria: "Criteri decisionali",
    preferred_vocabulary: "Vocabolario preferito",
    frustrations: "Frustrazioni",
    pain_points: "Pain point",
    trust_concerns: "Preoccupazioni sulla fiducia",
    accessibility_needs: "Esigenze di accessibilità",
    operational_constraints: "Vincoli operativi",
    technical_literacy: "Competenza tecnica",
    risk_sensitivity: "Sensibilità al rischio",
    assumptions: "Assunzioni",
  },
};

const messages = {
  en: {
    eyebrow: "User Modeling · Gate 3",

    title: "User Twins review and approval",

    intro: "Review personas and User Twins before requirements definition.",

    loading: "Updating User Modeling state…",

    error: "User Modeling operation failed.",

    personas: "Personas and proto-personas",

    proposePersonas: "Propose personas",

    noPersonas: "No personas have been proposed yet.",

    protoWarning: "System-proposed personas remain proto-personas until the owner confirms them.",

    confirm: "Confirm persona",

    reject: "Reject persona",

    rejectionReason: "Reason for rejection",

    reasonPlaceholder: "Explain the requested correction…",

    confirmed: "Confirmed",

    rejected: "Rejected",

    pending: "Pending confirmation",

    generateTwins: "Generate User Twins",

    generationHint:
      "At least one persona must be confirmed and no proto-persona may remain pending.",

    twins: "User Twins",

    snapshot: "User Modeling snapshot",

    version: "Version",

    persistedLifecycle: "Persisted lifecycle",

    effectiveLifecycle: "Effective lifecycle",

    edit: "Propose revision",

    observationUnavailable:
      "This observation cannot be edited through the current typed profile contract.",

    revision: "Profile revision",

    revisionField: "Field",

    revisionValue: "New value",

    revisionItemsHint: "Use one item per line.",

    userProvided: "Owner / user provided",

    humanValidated: "Human validated",

    humanValidatedWarning:
      "Use Human validated only when recording an actual human review. Gate 3 approval alone is not human-validation evidence.",

    proposeRevision: "Create profile diff",

    cancel: "Cancel",

    diffs: "Profile diffs",

    proposedDiff: "Proposed",

    approvedDiff: "Approved",

    rejectedDiff: "Rejected",

    before: "Before",

    after: "After",

    approveDiff: "Approve diff",

    rejectDiff: "Reject diff",

    diffReason: "Decision reason",

    gate: "Gate 3 · User Modeling approval",

    gateStatus: "Gate status",

    submitGate: "Submit current snapshot",

    approveGate: "Approve Gate 3",

    rejectGate: "Reject",

    requestRevision: "Request revision",

    pause: "Pause",

    resume: "Resume",

    cancelGate: "Cancel gate",

    gateReason: "Gate decision reason",

    gateMethodology:
      "Gate 3 approval changes the effective lifecycle to OWNER_APPROVED_UT for the exact approved snapshot. It does not create HUMAN_VALIDATED or EMPIRICALLY_SUPPORTED evidence.",

    currentSnapshotApproved: "The current User Modeling snapshot is owner approved.",

    ready: "Ready for requirements definition.",

    notReady: "User Modeling still requires owner review.",

    stale: "The previous Gate 3 decision does not approve the current snapshot.",

    unknown: "Unknown",

    abstained: "Abstained",

    empty: "No value",

    requiredReason: "A reason is required for this decision.",

    requiredValue: "Enter a value before proposing the revision.",

    invalidField: "The selected observation is not mapped to a User Twin field.",

    projectMissing: "Project and access token are required.",
  },

  it: {
    eyebrow: "User Modeling · Gate 3",

    title: "Revisione e approvazione degli User Twin",

    intro: "Revisiona personas e User Twin prima della definizione dei requisiti.",

    loading: "Aggiornamento dello stato User Modeling…",

    error: "Operazione User Modeling non riuscita.",

    personas: "Personas e proto-personas",

    proposePersonas: "Proponi personas",

    noPersonas: "Non è stata ancora proposta alcuna persona.",

    protoWarning:
      "Le personas proposte dal sistema restano proto-personas finché il proprietario non le conferma.",

    confirm: "Conferma persona",

    reject: "Rifiuta persona",

    rejectionReason: "Motivo del rifiuto",

    reasonPlaceholder: "Spiega la correzione richiesta…",

    confirmed: "Confermata",

    rejected: "Rifiutata",

    pending: "In attesa di conferma",

    generateTwins: "Genera User Twin",

    generationHint:
      "Almeno una persona deve essere confermata e nessuna proto-persona può restare in attesa.",

    twins: "User Twin",

    snapshot: "Snapshot User Modeling",

    version: "Versione",

    persistedLifecycle: "Lifecycle persistito",

    effectiveLifecycle: "Lifecycle effettivo",

    edit: "Proponi revisione",

    observationUnavailable:
      "Questa osservazione non può essere modificata tramite il contratto tipizzato corrente.",

    revision: "Revisione del profilo",

    revisionField: "Campo",

    revisionValue: "Nuovo valore",

    revisionItemsHint: "Inserisci un elemento per riga.",

    userProvided: "Fornito dal proprietario / utente",

    humanValidated: "Validato da una persona",

    humanValidatedWarning:
      "Usa Validato da una persona solo quando stai registrando una reale revisione umana. L'approvazione Gate 3 da sola non costituisce evidenza di human validation.",

    proposeRevision: "Crea ProfileDiff",

    cancel: "Annulla",

    diffs: "ProfileDiff",

    proposedDiff: "Proposta",

    approvedDiff: "Approvata",

    rejectedDiff: "Rifiutata",

    before: "Prima",

    after: "Dopo",

    approveDiff: "Approva diff",

    rejectDiff: "Rifiuta diff",

    diffReason: "Motivazione della decisione",

    gate: "Gate 3 · Approvazione User Modeling",

    gateStatus: "Stato gate",

    submitGate: "Invia snapshot corrente",

    approveGate: "Approva Gate 3",

    rejectGate: "Rifiuta",

    requestRevision: "Richiedi revisione",

    pause: "Pausa",

    resume: "Riprendi",

    cancelGate: "Annulla gate",

    gateReason: "Motivazione decisione Gate",

    gateMethodology:
      "L'approvazione Gate 3 modifica il lifecycle effettivo in OWNER_APPROVED_UT esclusivamente per lo snapshot approvato. Non crea evidenza HUMAN_VALIDATED o EMPIRICALLY_SUPPORTED.",

    currentSnapshotApproved: "Lo snapshot User Modeling corrente è approvato dal proprietario.",

    ready: "Pronto per la definizione dei requisiti.",

    notReady: "Lo User Modeling richiede ancora una revisione del proprietario.",

    stale: "La precedente decisione Gate 3 non approva lo snapshot corrente.",

    unknown: "Sconosciuto",

    abstained: "Astensione",

    empty: "Nessun valore",

    requiredReason: "Per questa decisione è richiesta una motivazione.",

    requiredValue: "Inserisci un valore prima di proporre la revisione.",

    invalidField: "L'osservazione selezionata non corrisponde a un campo User Twin.",

    projectMissing: "Sono richiesti progetto e access token.",
  },
} as const;

const copy = computed(() => messages[props.locale]);

const personas = computed(() => store.currentPersonas);

const twins = computed(() => store.currentTwins);

const pendingPersonas = computed(() =>
  personas.value.filter(
    (persona) => persona.profile.confirmation_status === "PENDING_CONFIRMATION",
  ),
);

const confirmedPersonas = computed(() =>
  personas.value.filter((persona) => persona.profile.confirmation_status === "CONFIRMED"),
);

const canGenerateTwins = computed(
  () =>
    store.currentSnapshot === null &&
    personas.value.length > 0 &&
    pendingPersonas.value.length === 0 &&
    confirmedPersonas.value.length > 0,
);

const profileDiffs = computed(() =>
  Object.values(store.diffs).sort((left, right) => left.created_at.localeCompare(right.created_at)),
);

const gateTargetsCurrentSnapshot = computed(() => {
  const snapshot = store.currentSnapshot;

  const gate = store.currentGate;

  if (snapshot === null || gate === null) {
    return false;
  }

  return (
    gate.artifact.artifact_id === snapshot.id &&
    gate.artifact.version === snapshot.version_number &&
    gate.artifact.content_hash === snapshot.content_hash
  );
});

const canSubmitGate = computed(() => {
  if (store.currentSnapshot === null) {
    return false;
  }

  if (store.currentGate === null) {
    return true;
  }

  if (!gateTargetsCurrentSnapshot.value) {
    return true;
  }

  return store.currentGate.status === "DRAFT" || store.currentGate.status === "STALE";
});

const gatePendingApproval = computed(
  () => gateTargetsCurrentSnapshot.value && store.currentGate?.status === "PENDING_APPROVAL",
);

const gatePaused = computed(
  () => gateTargetsCurrentSnapshot.value && store.currentGate?.status === "PAUSED",
);

function fieldLabel(field: UserTwinField): string {
  return fieldLabels[props.locale][field];
}

function personaStatusLabel(persona: PersonaVersionPayload): string {
  switch (persona.profile.confirmation_status) {
    case "CONFIRMED":
      return copy.value.confirmed;

    case "REJECTED":
      return copy.value.rejected;

    case "PENDING_CONFIRMATION":
      return copy.value.pending;
  }
}

function observationField(observation: ProfileObservationPayload): UserTwinField | null {
  const parts = observation.observation_key.split(".");

  const candidate = parts.pop();

  if (candidate === undefined) {
    return null;
  }

  const typedCandidate = candidate as UserTwinField;

  return userTwinFields.has(typedCandidate) ? typedCandidate : null;
}

function formatObservation(observation: ProfileObservationPayload | null): string {
  if (observation === null) {
    return copy.value.empty;
  }

  switch (observation.value.kind) {
    case "TEXT":
      return observation.value.text ?? copy.value.empty;

    case "ITEMS":
      return observation.value.items.length > 0
        ? observation.value.items.join(", ")
        : copy.value.empty;

    case "UNKNOWN":
      return observation.value.reason ?? copy.value.unknown;

    case "ABSTAINED":
      return observation.value.reason ?? copy.value.abstained;
  }
}

function effectiveLifecycle(twin: UserTwinVersionPayload): string {
  const lifecycle = store.readiness?.twins.find(
    (item) => item.twin_id === twin.twin_id && item.version_number === twin.version_number,
  );

  return lifecycle?.effective_status ?? twin.profile.validation_status;
}

function personaReason(personaId: string): string {
  return personaReasons[personaId] ?? "";
}

function diffReason(diffId: string): string {
  return diffReasons[diffId] ?? "";
}

function gateActionRequiresReason(action: GateDecisionAction): boolean {
  return action === "REJECT" || action === "REQUEST_REVISION";
}

async function runAction(action: () => Promise<unknown>): Promise<boolean> {
  localError.value = null;

  try {
    await action();

    return true;
  } catch (error) {
    if (error instanceof Error) {
      localError.value = error.message;
    } else {
      localError.value = copy.value.error;
    }

    return false;
  }
}

async function loadProject(): Promise<void> {
  if (props.projectId.trim().length === 0 || props.accessToken.trim().length === 0) {
    localError.value = copy.value.projectMissing;

    return;
  }

  await runAction(() => store.load(props.projectId, props.accessToken));
}

async function proposePersonas(): Promise<void> {
  await runAction(() => store.proposePersonas(props.projectId, props.accessToken));
}

async function decidePersona(
  persona: PersonaVersionPayload,
  decision: PersonaOwnerDecision,
): Promise<void> {
  const reason = personaReason(persona.persona_id).trim();

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  await runAction(() =>
    store.decidePersona(
      props.projectId,
      persona.persona_id,
      decision,
      props.accessToken,
      reason.length > 0 ? reason : null,
    ),
  );
}

async function generateTwins(): Promise<void> {
  await runAction(() => store.generateSnapshot(props.projectId, props.accessToken));
}

function startRevision(twin: UserTwinVersionPayload, observation: ProfileObservationPayload): void {
  const field = observationField(observation);

  if (field === null) {
    localError.value = copy.value.invalidField;

    return;
  }

  editingTwinId.value = twin.twin_id;

  editingField.value = field;

  editingOriginalKind.value = observation.value.kind;

  revisionEpistemicStatus.value = "USER_PROVIDED";

  if (observation.value.kind === "ITEMS") {
    editingValue.value = observation.value.items.join("\n");

    return;
  }

  if (observation.value.kind === "TEXT") {
    editingValue.value = observation.value.text ?? "";

    return;
  }

  editingValue.value = "";
}

function cancelRevision(): void {
  editingTwinId.value = null;
  editingField.value = null;
  editingOriginalKind.value = "TEXT";
  editingValue.value = "";
  revisionEpistemicStatus.value = "USER_PROVIDED";
}

function replacementValue(field: UserTwinField) {
  const normalized = editingValue.value.trim();

  if (normalized.length === 0) {
    throw new Error(copy.value.requiredValue);
  }

  const useItems =
    editingOriginalKind.value === "ITEMS" ||
    (editingOriginalKind.value !== "TEXT" && multiValueFields.has(field));

  if (useItems) {
    const items = editingValue.value
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter((item) => item.length > 0);

    if (items.length === 0) {
      throw new Error(copy.value.requiredValue);
    }

    return {
      kind: "ITEMS" as const,
      text: null,
      items,
      reason: null,
    };
  }

  return {
    kind: "TEXT" as const,
    text: normalized,
    items: [],
    reason: null,
  };
}

async function submitRevision(): Promise<void> {
  const twinId = editingTwinId.value;

  const field = editingField.value;

  if (twinId === null || field === null) {
    localError.value = copy.value.invalidField;

    return;
  }

  let value;

  try {
    value = replacementValue(field);
  } catch (error) {
    localError.value = error instanceof Error ? error.message : copy.value.requiredValue;

    return;
  }

  const humanValidated = revisionEpistemicStatus.value === "HUMAN_VALIDATED";

  const replacement: ProfileReplacementRequest = {
    field,

    value,

    epistemic_status: revisionEpistemicStatus.value,

    confidence: 1,

    provenance: [
      {
        source_kind: humanValidated ? "HUMAN_REVIEW" : "OWNER_INPUT",

        source_id: humanValidated ? "owner-human-review" : "owner-input",

        source_version: null,
        content_hash: null,

        locator: `user_twin.${field}`,

        summary: humanValidated
          ? props.locale === "it"
            ? "Revisione umana registrata dal proprietario."
            : "Human review recorded by the owner."
          : props.locale === "it"
            ? "Modifica fornita dal proprietario."
            : "Owner-provided profile revision.",
      },
    ],

    human_validation: "NOT_REQUIRED",

    rationale: null,
  };

  const applied = await runAction(() =>
    store.proposeRevision(props.projectId, twinId, [replacement], props.accessToken),
  );

  if (applied) {
    cancelRevision();
  }
}

async function decideDiff(
  diff: UserTwinProfileDiffPayload,
  decision: ProfileRevisionDecision,
): Promise<void> {
  const reason = diffReason(diff.id).trim();

  if (decision === "REJECT" && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  await runAction(() =>
    store.decideRevision(
      props.projectId,
      diff.id,
      decision,
      props.accessToken,
      reason.length > 0 ? reason : null,
    ),
  );
}

async function submitGate(): Promise<void> {
  await runAction(() => store.submitGate(props.projectId, props.accessToken));
}

async function decideGate(action: GateDecisionAction): Promise<void> {
  const reason = gateReason.value.trim();

  if (gateActionRequiresReason(action) && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  await runAction(() =>
    store.decideGate(props.projectId, action, props.accessToken, reason.length > 0 ? reason : null),
  );
}

watch(
  () => [props.projectId, props.accessToken, props.autoLoad] as const,

  ([projectId, accessToken, autoLoad]) => {
    if (!autoLoad || projectId.trim().length === 0 || accessToken.trim().length === 0) {
      return;
    }

    void loadProject();
  },

  {
    immediate: true,
  },
);
</script>

<template>
  <section class="space-y-8" aria-labelledby="user-modeling-title">
    <header class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <p class="text-xs font-semibold tracking-[0.16em] text-slate-500 uppercase">
        {{ copy.eyebrow }}
      </p>

      <h2 id="user-modeling-title" class="mt-2 text-2xl font-bold tracking-tight text-slate-950">
        {{ copy.title }}
      </h2>

      <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
        {{ copy.intro }}
      </p>

      <p v-if="store.isBusy" class="mt-4 text-sm font-medium text-slate-600" role="status">
        {{ copy.loading }}
      </p>

      <div
        v-if="localError !== null || store.error !== null"
        class="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        role="alert"
      >
        {{ localError ?? store.error?.message ?? copy.error }}
      </div>
    </header>

    <section
      class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      aria-labelledby="personas-heading"
    >
      <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 id="personas-heading" class="text-lg font-bold text-slate-950">
            {{ copy.personas }}
          </h3>

          <p class="mt-1 max-w-2xl text-sm leading-6 text-slate-600">
            {{ copy.protoWarning }}
          </p>
        </div>

        <button
          v-if="personas.length === 0 && store.currentSnapshot === null"
          type="button"
          class="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="store.isBusy"
          data-testid="propose-personas"
          @click="proposePersonas"
        >
          {{ copy.proposePersonas }}
        </button>
      </div>

      <p v-if="personas.length === 0" class="mt-5 text-sm text-slate-500">
        {{ copy.noPersonas }}
      </p>

      <div v-else class="mt-5 grid gap-4">
        <article
          v-for="persona in personas"
          :key="persona.id"
          class="rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4 class="font-semibold text-slate-950">
                {{ persona.profile.name }}
              </h4>

              <p class="mt-1 text-xs font-medium tracking-wide text-slate-500 uppercase">
                {{ persona.profile.kind }}
                ·
                {{ personaStatusLabel(persona) }}
                · v{{ persona.version_number }}
              </p>
            </div>
          </div>

          <div class="mt-4 space-y-3">
            <div
              v-for="observation in persona.profile.observations"
              :key="observation.observation_key"
              class="rounded-lg bg-slate-50 p-3"
            >
              <p class="text-xs font-semibold tracking-wide text-slate-500 uppercase">
                {{ observation.observation_key }}
              </p>

              <p class="mt-1 text-sm text-slate-900">
                {{ formatObservation(observation) }}
              </p>

              <div class="mt-3">
                <UserModelingEpistemicBadge
                  :status="observation.epistemic_status"
                  :confidence="observation.confidence"
                  :human-validation="observation.human_validation"
                  :locale="locale"
                />
              </div>

              <div class="mt-3">
                <UserModelingProvenanceInspector :observation="observation" :locale="locale" />
              </div>
            </div>
          </div>

          <div
            v-if="persona.profile.confirmation_status === 'PENDING_CONFIRMATION'"
            class="mt-4 border-t border-slate-200 pt-4"
          >
            <label
              class="block text-sm font-medium text-slate-700"
              :for="`persona-reason-${persona.persona_id}`"
            >
              {{ copy.rejectionReason }}
            </label>

            <textarea
              :id="`persona-reason-${persona.persona_id}`"
              v-model="personaReasons[persona.persona_id]"
              rows="2"
              class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 shadow-sm focus:border-slate-500 focus:ring-2 focus:ring-slate-200 focus:outline-none"
              :placeholder="copy.reasonPlaceholder"
            />

            <div class="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
                :disabled="store.isBusy"
                data-testid="confirm-persona"
                @click="decidePersona(persona, 'CONFIRM')"
              >
                {{ copy.confirm }}
              </button>

              <button
                type="button"
                class="rounded-lg border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                :disabled="store.isBusy || personaReason(persona.persona_id).trim().length === 0"
                data-testid="reject-persona"
                @click="decidePersona(persona, 'REJECT')"
              >
                {{ copy.reject }}
              </button>
            </div>
          </div>
        </article>
      </div>

      <div v-if="store.currentSnapshot === null" class="mt-5">
        <button
          type="button"
          class="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canGenerateTwins || store.isBusy"
          data-testid="generate-twins"
          @click="generateTwins"
        >
          {{ copy.generateTwins }}
        </button>

        <p class="mt-2 text-xs text-slate-500">
          {{ copy.generationHint }}
        </p>
      </div>
    </section>

    <section
      v-if="store.currentSnapshot !== null"
      class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      aria-labelledby="twins-heading"
    >
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 id="twins-heading" class="text-lg font-bold text-slate-950">
            {{ copy.twins }}
          </h3>

          <p class="mt-1 text-sm text-slate-500">
            {{ copy.snapshot }}
            ·
            {{ copy.version }}
            {{ store.currentSnapshot.version_number }}
          </p>
        </div>

        <code class="max-w-full rounded-md bg-slate-100 px-2 py-1 text-xs break-all text-slate-500">
          {{ store.currentSnapshot.content_hash }}
        </code>
      </div>

      <div class="mt-5 grid gap-5">
        <article
          v-for="twin in twins"
          :key="twin.id"
          class="rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4 class="text-base font-bold text-slate-950">
                {{ twin.profile.name }}
              </h4>

              <dl class="mt-2 grid gap-1 text-xs text-slate-600">
                <div>
                  <dt class="inline font-semibold">{{ copy.persistedLifecycle }}:</dt>

                  <dd class="inline">
                    {{ twin.profile.validation_status }}
                  </dd>
                </div>

                <div>
                  <dt class="inline font-semibold">{{ copy.effectiveLifecycle }}:</dt>

                  <dd class="inline" data-testid="effective-lifecycle">
                    {{ effectiveLifecycle(twin) }}
                  </dd>
                </div>
              </dl>
            </div>
          </div>

          <div class="mt-5 grid gap-4">
            <article
              v-for="observation in twin.profile.observations"
              :key="observation.observation_key"
              class="rounded-xl border border-slate-200 bg-slate-50 p-4"
            >
              <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h5 class="text-sm font-semibold text-slate-900">
                    {{
                      observationField(observation) !== null
                        ? fieldLabel(observationField(observation) as UserTwinField)
                        : observation.observation_key
                    }}
                  </h5>

                  <p class="mt-1 text-sm leading-6 whitespace-pre-line text-slate-700">
                    {{ formatObservation(observation) }}
                  </p>
                </div>

                <button
                  v-if="observationField(observation) !== null"
                  type="button"
                  class="shrink-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                  :disabled="store.isBusy"
                  data-testid="edit-twin-observation"
                  @click="startRevision(twin, observation)"
                >
                  {{ copy.edit }}
                </button>

                <span v-else class="text-xs text-slate-500">
                  {{ copy.observationUnavailable }}
                </span>
              </div>

              <div class="mt-3">
                <UserModelingEpistemicBadge
                  :status="observation.epistemic_status"
                  :confidence="observation.confidence"
                  :human-validation="observation.human_validation"
                  :locale="locale"
                />
              </div>

              <div class="mt-3">
                <UserModelingProvenanceInspector :observation="observation" :locale="locale" />
              </div>
            </article>
          </div>
        </article>
      </div>

      <form
        v-if="editingTwinId !== null && editingField !== null"
        class="mt-6 rounded-xl border border-slate-300 bg-slate-50 p-4"
        @submit.prevent="submitRevision"
      >
        <h4 class="font-bold text-slate-950">
          {{ copy.revision }}
        </h4>

        <p class="mt-2 text-sm text-slate-600">
          {{ copy.revisionField }}:
          <strong>
            {{ fieldLabel(editingField) }}
          </strong>
        </p>

        <label for="user-twin-revision-value" class="mt-4 block text-sm font-medium text-slate-700">
          {{ copy.revisionValue }}
        </label>

        <textarea
          id="user-twin-revision-value"
          v-model="editingValue"
          rows="5"
          class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-950 shadow-sm focus:border-slate-500 focus:ring-2 focus:ring-slate-200 focus:outline-none"
          data-testid="revision-value"
        />

        <p
          v-if="
            editingOriginalKind === 'ITEMS' ||
            (editingField !== null && multiValueFields.has(editingField))
          "
          class="mt-1 text-xs text-slate-500"
        >
          {{ copy.revisionItemsHint }}
        </p>

        <fieldset class="mt-4 space-y-2">
          <legend class="text-sm font-semibold text-slate-700">Epistemic status</legend>

          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input v-model="revisionEpistemicStatus" type="radio" value="USER_PROVIDED" />

            {{ copy.userProvided }}
          </label>

          <label class="flex items-center gap-2 text-sm text-slate-700">
            <input v-model="revisionEpistemicStatus" type="radio" value="HUMAN_VALIDATED" />

            {{ copy.humanValidated }}
          </label>
        </fieldset>

        <p
          class="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900"
        >
          {{ copy.humanValidatedWarning }}
        </p>

        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="submit"
            class="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            :disabled="store.isBusy"
            data-testid="submit-revision"
          >
            {{ copy.proposeRevision }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white"
            @click="cancelRevision"
          >
            {{ copy.cancel }}
          </button>
        </div>
      </form>
    </section>

    <section
      v-if="profileDiffs.length > 0"
      class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      aria-labelledby="diffs-heading"
    >
      <h3 id="diffs-heading" class="text-lg font-bold text-slate-950">
        {{ copy.diffs }}
      </h3>

      <div class="mt-5 grid gap-4">
        <article
          v-for="diff in profileDiffs"
          :key="diff.id"
          class="rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <code class="text-xs text-slate-500">
              {{ diff.id }}
            </code>

            <span
              class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700"
            >
              {{
                diff.status === "PROPOSED"
                  ? copy.proposedDiff
                  : diff.status === "APPROVED"
                    ? copy.approvedDiff
                    : copy.rejectedDiff
              }}
            </span>
          </div>

          <div class="mt-4 grid gap-4">
            <div
              v-for="operation in diff.operations"
              :key="operation.field"
              class="grid gap-3 rounded-lg bg-slate-50 p-3 md:grid-cols-2"
            >
              <div>
                <p class="text-xs font-semibold tracking-wide text-slate-500 uppercase">
                  {{ copy.before }}
                  ·
                  {{ fieldLabel(operation.field) }}
                </p>

                <p class="mt-1 text-sm text-slate-700">
                  {{ formatObservation(operation.before) }}
                </p>
              </div>

              <div>
                <p class="text-xs font-semibold tracking-wide text-slate-500 uppercase">
                  {{ copy.after }}
                  ·
                  {{ fieldLabel(operation.field) }}
                </p>

                <p class="mt-1 text-sm text-slate-900">
                  {{ formatObservation(operation.after) }}
                </p>

                <div class="mt-3">
                  <UserModelingEpistemicBadge
                    :status="operation.after.epistemic_status"
                    :confidence="operation.after.confidence"
                    :human-validation="operation.after.human_validation"
                    :locale="locale"
                  />
                </div>

                <div class="mt-3">
                  <UserModelingProvenanceInspector
                    :observation="operation.after"
                    :locale="locale"
                  />
                </div>
              </div>
            </div>
          </div>

          <div v-if="diff.status === 'PROPOSED'" class="mt-4 border-t border-slate-200 pt-4">
            <label :for="`diff-reason-${diff.id}`" class="block text-sm font-medium text-slate-700">
              {{ copy.diffReason }}
            </label>

            <textarea
              :id="`diff-reason-${diff.id}`"
              v-model="diffReasons[diff.id]"
              rows="2"
              class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />

            <div class="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
                :disabled="store.isBusy"
                data-testid="approve-diff"
                @click="decideDiff(diff, 'APPROVE')"
              >
                {{ copy.approveDiff }}
              </button>

              <button
                type="button"
                class="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                :disabled="store.isBusy || diffReason(diff.id).trim().length === 0"
                data-testid="reject-diff"
                @click="decideDiff(diff, 'REJECT')"
              >
                {{ copy.rejectDiff }}
              </button>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section
      v-if="store.currentSnapshot !== null"
      class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      aria-labelledby="gate-three-heading"
    >
      <h3 id="gate-three-heading" class="text-lg font-bold text-slate-950">
        {{ copy.gate }}
      </h3>

      <p
        class="mt-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-900"
      >
        {{ copy.gateMethodology }}
      </p>

      <dl class="mt-4 grid gap-2 text-sm text-slate-700">
        <div>
          <dt class="inline font-semibold">{{ copy.gateStatus }}:</dt>

          <dd class="inline">
            {{ store.currentGate?.status ?? "—" }}
          </dd>
        </div>

        <div>
          <dt class="inline font-semibold">Workflow:</dt>

          <dd class="inline">
            {{ store.readiness?.workflow_state ?? "—" }}
          </dd>
        </div>
      </dl>

      <p
        v-if="store.readiness?.approved_current_snapshot"
        class="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm font-medium text-emerald-800"
      >
        {{ copy.currentSnapshotApproved }}
      </p>

      <p
        v-else-if="store.currentGate !== null && !gateTargetsCurrentSnapshot"
        class="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
      >
        {{ copy.stale }}
      </p>

      <p
        class="mt-4 text-sm font-semibold"
        :class="store.isReadyForRequirements ? 'text-emerald-700' : 'text-amber-700'"
        data-testid="requirements-readiness"
      >
        {{ store.isReadyForRequirements ? copy.ready : copy.notReady }}
      </p>

      <div v-if="canSubmitGate" class="mt-5">
        <button
          type="button"
          class="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          :disabled="store.isBusy"
          data-testid="submit-gate"
          @click="submitGate"
        >
          {{ copy.submitGate }}
        </button>
      </div>

      <div v-if="gatePendingApproval || gatePaused" class="mt-5">
        <label for="gate-three-reason" class="block text-sm font-medium text-slate-700">
          {{ copy.gateReason }}
        </label>

        <textarea
          id="gate-three-reason"
          v-model="gateReason"
          rows="2"
          class="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
        />

        <div v-if="gatePendingApproval" class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-50"
            :disabled="store.isBusy"
            data-testid="approve-gate"
            @click="decideGate('APPROVE')"
          >
            {{ copy.approveGate }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50"
            :disabled="store.isBusy || gateReason.trim().length === 0"
            @click="decideGate('REQUEST_REVISION')"
          >
            {{ copy.requestRevision }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
            :disabled="store.isBusy || gateReason.trim().length === 0"
            @click="decideGate('REJECT')"
          >
            {{ copy.rejectGate }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            :disabled="store.isBusy"
            @click="decideGate('PAUSE')"
          >
            {{ copy.pause }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            :disabled="store.isBusy"
            @click="decideGate('CANCEL')"
          >
            {{ copy.cancelGate }}
          </button>
        </div>

        <div v-else-if="gatePaused" class="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            :disabled="store.isBusy"
            @click="decideGate('RESUME')"
          >
            {{ copy.resume }}
          </button>

          <button
            type="button"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            :disabled="store.isBusy"
            @click="decideGate('CANCEL')"
          >
            {{ copy.cancelGate }}
          </button>
        </div>
      </div>
    </section>
  </section>
</template>
