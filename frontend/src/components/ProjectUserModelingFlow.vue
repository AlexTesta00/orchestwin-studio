<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";

import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import UserModelingProvenanceInspector from "./UserModelingProvenanceInspector.vue";
import TwinIdentity from "./TwinIdentity.vue";
import { workflowStatusLabel } from "./workflowLabels";

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
    authorize?: <T>(operation: (token: string) => Promise<T>) => Promise<T>;
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
    eyebrow: "Understand your users",

    title: "Who will use your product?",

    intro:
      "Review the proposed user profiles. Their digital representatives, called User Twins, will help explore the product from different perspectives.",

    loading: "Updating user profiles…",
    generating: "Preparing the profiles. This may take a few minutes; keep this page open.",

    error: "User Modeling operation failed.",

    personas: "Proposed user profiles",

    proposePersonas: "Suggest user profiles",

    noPersonas: "No personas have been proposed yet.",

    protoWarning:
      "These profiles are suggestions. Confirm that they represent your audience before continuing.",

    confirm: "Confirm this profile",

    reject: "Reject this profile",

    rejectionReason: "Reason for rejection",

    reasonPlaceholder: "Explain the requested correction…",

    confirmed: "Confirmed",

    rejected: "Rejected",

    pending: "Pending confirmation",

    generateTwins: "Create their User Twins",

    generationHint:
      "Confirm at least one profile and review every remaining suggestion before continuing.",

    twins: "Your users' digital representatives",

    snapshot: "User profiles",
    technicalDetails: "Technical details and sources",
    profileDetails: "View profile",
    evidenceDetails: "Why we think this",
    knowledgeSource: "Where does this information come from?",

    version: "Version",

    persistedLifecycle: "Persisted lifecycle",

    effectiveLifecycle: "Effective lifecycle",

    edit: "Propose revision",

    observationUnavailable: "This information is read-only.",

    revision: "Profile revision",

    revisionField: "Field",

    revisionValue: "New value",

    revisionItemsHint: "Use one item per line.",

    userProvided: "Owner / user provided",

    humanValidated: "Human validated",

    humanValidatedWarning:
      "Choose Human validated only if a person has checked this information. Approving a profile alone does not verify its assumptions.",

    proposeRevision: "Propose this change",

    cancel: "Cancel",

    diffs: "Suggested profile changes",

    proposedDiff: "Proposed",

    approvedDiff: "Approved",

    rejectedDiff: "Rejected",

    before: "Before",

    after: "After",

    approveDiff: "Approve change",

    rejectDiff: "Reject change",

    diffReason: "Decision reason",

    gate: "Confirm your user profiles",

    gateStatus: "Approval",

    submitGate: "Review these profiles for approval",

    approveGate: "Approve user profiles",

    rejectGate: "Reject",

    requestRevision: "Request revision",

    pause: "Pause",

    resume: "Resume",

    cancelGate: "Cancel approval",

    gateReason: "Reason for your decision",

    gateMethodology:
      "Your approval allows the project to use these profiles. It does not mean their assumptions have been verified with real users.",

    currentSnapshotApproved: "You have approved these user profiles.",

    ready: "Ready for requirements definition.",

    notReady: "Review and approve your user profiles to continue.",

    stale: "The profiles have changed since your last approval. Review them again.",

    unknown: "Unknown",

    abstained: "Abstained",

    empty: "No value",

    requiredReason: "A reason is required for this decision.",

    requiredValue: "Enter a value before proposing the revision.",

    invalidField: "The selected observation is not mapped to a User Twin field.",

    projectMissing: "Project and access token are required.",
  },

  it: {
    eyebrow: "Conosci i tuoi utenti",

    title: "Chi userà il tuo prodotto?",

    intro:
      "Controlla i profili proposti. I loro rappresentanti digitali, chiamati User Twin, aiuteranno a esplorare il prodotto da punti di vista diversi.",

    loading: "Aggiornamento dei profili…",
    generating:
      "Preparazione dei profili in corso. Può richiedere alcuni minuti; mantieni aperta questa pagina.",

    error: "Operazione User Modeling non riuscita.",

    personas: "Profili degli utenti proposti",

    proposePersonas: "Proponi i profili degli utenti",

    noPersonas: "Non è stata ancora proposta alcuna persona.",

    protoWarning:
      "Questi profili sono proposte. Conferma che rappresentino il tuo pubblico prima di proseguire.",

    confirm: "Conferma questo profilo",

    reject: "Rifiuta questo profilo",

    rejectionReason: "Motivo del rifiuto",

    reasonPlaceholder: "Spiega la correzione richiesta…",

    confirmed: "Confermata",

    rejected: "Rifiutata",

    pending: "In attesa di conferma",

    generateTwins: "Crea i loro User Twin",

    generationHint:
      "Conferma almeno un profilo e valuta tutte le altre proposte prima di proseguire.",

    twins: "I rappresentanti digitali dei tuoi utenti",

    snapshot: "Profili degli utenti",
    technicalDetails: "Dettagli tecnici e fonti",
    profileDetails: "Vedi il profilo",
    evidenceDetails: "Da dove nasce questa informazione",
    knowledgeSource: "Da dove proviene questa informazione?",

    version: "Versione",

    persistedLifecycle: "Lifecycle persistito",

    effectiveLifecycle: "Lifecycle effettivo",

    edit: "Proponi revisione",

    observationUnavailable: "Questa informazione è di sola lettura.",

    revision: "Revisione del profilo",

    revisionField: "Campo",

    revisionValue: "Nuovo valore",

    revisionItemsHint: "Inserisci un elemento per riga.",

    userProvided: "Fornito dal proprietario / utente",

    humanValidated: "Validato da una persona",

    humanValidatedWarning:
      "Scegli Validato da una persona solo se qualcuno ha verificato questa informazione. Approvare il profilo, da solo, non conferma le sue ipotesi.",

    proposeRevision: "Proponi questa modifica",

    cancel: "Annulla",

    diffs: "Modifiche proposte ai profili",

    proposedDiff: "Proposta",

    approvedDiff: "Approvata",

    rejectedDiff: "Rifiutata",

    before: "Prima",

    after: "Dopo",

    approveDiff: "Approva modifica",

    rejectDiff: "Rifiuta modifica",

    diffReason: "Motivazione della decisione",

    gate: "Conferma i profili degli utenti",

    gateStatus: "Approvazione",

    submitGate: "Porta questi profili all'approvazione",

    approveGate: "Approva i profili degli utenti",

    rejectGate: "Rifiuta",

    requestRevision: "Richiedi revisione",

    pause: "Pausa",

    resume: "Riprendi",

    cancelGate: "Annulla approvazione",

    gateReason: "Motivazione della decisione",

    gateMethodology:
      "La tua approvazione permette al progetto di usare questi profili. Non significa che le loro ipotesi siano state verificate con utenti reali.",

    currentSnapshotApproved: "Hai approvato questi profili degli utenti.",

    ready: "Pronto per la definizione dei requisiti.",

    notReady: "Controlla e approva i profili degli utenti per proseguire.",

    stale: "I profili sono cambiati dalla tua ultima approvazione. Controllali di nuovo.",

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

const errorMessage = computed(() => {
  const code = localError.value ?? store.error?.code ?? store.error?.message;
  if (!code) return null;
  const errors: Record<string, [string, string]> = {
    INVALID_PROVIDER_OUTPUT: [
      "The model returned an incomplete or invalid proposal. No artifact was accepted. You can try again.",
      "Il modello ha restituito una proposta incompleta o non valida. Nessun artefatto è stato accettato. Puoi riprovare.",
    ],
    INCOMPLETE_OUTPUT: [
      "The model reached its generation limit. Try again with a smaller scope.",
      "Il modello ha raggiunto il limite di generazione. Riprova con un ambito più contenuto.",
    ],
    PROVIDER_UNAVAILABLE: [
      "The local model is unavailable. Check model status above.",
      "Il modello locale non è disponibile. Controlla lo stato dei modelli qui sopra.",
    ],
    TIMEOUT: [
      "Model generation timed out. Check model availability before retrying.",
      "La generazione ha superato il tempo disponibile. Controlla il modello prima di riprovare.",
    ],
    CONTEXT_BUDGET_EXCEEDED: [
      "These profiles exceed the model context window. Use fewer target groups or configure a larger context.",
      "Questi profili superano il contesto del modello. Riduci i gruppi target oppure configura un contesto maggiore.",
    ],
  };
  return errors[code]?.[props.locale === "it" ? 1 : 0] ?? code;
});

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
    (store.currentSnapshot === null || store.readiness?.context_current === false) &&
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

function profileDescription(observations: ProfileObservationPayload[]): string | undefined {
  const role = observations.find((observation) => observationField(observation) === "role");
  return role && ["TEXT", "ITEMS"].includes(role.value.kind) ? formatObservation(role) : undefined;
}

function observationSummary(observation: ProfileObservationPayload): string {
  const labels = {
    MODEL_INFERRED: ["Ipotesi del modello", "Model suggestion"],
    UNSUPPORTED_ASSUMPTION: ["Ipotesi da verificare", "Unverified assumption"],
    USER_PROVIDED: ["Informazione fornita dall'utente", "Provided by a user"],
    HUMAN_VALIDATED: ["Verificato da una persona", "Reviewed by a person"],
    EMPIRICALLY_SUPPORTED: ["Supportato da osservazioni reali", "Supported by real observations"],
  };
  const label = labels[observation.epistemic_status][props.locale === "it" ? 0 : 1];
  return observation.human_validation === "REQUIRED"
    ? `${label} · ${props.locale === "it" ? "da verificare" : "needs review"}`
    : (label ?? copy.value.unknown);
}

function lifecycleLabel(twin: UserTwinVersionPayload): string {
  const labels: Record<string, readonly [string, string]> = {
    PROTO_UT: ["Prima proposta", "Initial proposal"],
    PROJECT_GROUNDED_UT: ["Basato sul progetto", "Based on the project"],
    OWNER_APPROVED_UT: ["Profilo approvato", "Approved profile"],
    EMPIRICALLY_GROUNDED_UT: ["Basato su osservazioni reali", "Based on real observations"],
    EMPIRICALLY_VALIDATED_UT: [
      "Verificato con osservazioni reali",
      "Validated with real observations",
    ],
  };
  return labels[effectiveLifecycle(twin)]?.[props.locale === "it" ? 0 : 1] ?? copy.value.unknown;
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

async function runAction(action: (token: string) => Promise<unknown>): Promise<boolean> {
  localError.value = null;

  try {
    await (props.authorize ? props.authorize(action) : action(props.accessToken));

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

  await runAction((token) => store.load(props.projectId, token));
}

async function proposePersonas(): Promise<void> {
  await runAction((token) => store.proposePersonas(props.projectId, token));
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

  await runAction((token) =>
    store.decidePersona(
      props.projectId,
      persona.persona_id,
      decision,
      token,
      reason.length > 0 ? reason : null,
    ),
  );
}

async function generateTwins(): Promise<void> {
  await runAction((token) => store.generateSnapshot(props.projectId, token));
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

  const applied = await runAction((token) =>
    store.proposeRevision(props.projectId, twinId, [replacement], token),
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

  await runAction((token) =>
    store.decideRevision(
      props.projectId,
      diff.id,
      decision,
      token,
      reason.length > 0 ? reason : null,
    ),
  );
}

async function submitGate(): Promise<void> {
  await runAction((token) => store.submitGate(props.projectId, token));
}

async function decideGate(action: GateDecisionAction): Promise<void> {
  const reason = gateReason.value.trim();

  if (gateActionRequiresReason(action) && reason.length === 0) {
    localError.value = copy.value.requiredReason;

    return;
  }

  await runAction((token) =>
    store.decideGate(props.projectId, action, token, reason.length > 0 ? reason : null),
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
        {{
          store.pending["propose-personas"] || store.pending["generate-snapshot"]
            ? copy.generating
            : copy.loading
        }}
      </p>

      <div
        v-if="localError !== null || store.error !== null"
        class="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        role="alert"
      >
        {{ errorMessage }}
      </div>
    </header>

    <details
      class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      aria-labelledby="personas-heading"
      data-testid="starting-personas"
      :open="
        twins.length === 0 ||
        store.readiness?.context_current === false ||
        personas.some((persona) => persona.profile.confirmation_status === 'PENDING_CONFIRMATION')
      "
    >
      <summary id="personas-heading" class="cursor-pointer text-base font-semibold text-slate-950">
        {{
          twins.length > 0
            ? locale === "it"
              ? "Profili di partenza"
              : "Starting profiles"
            : copy.personas
        }}
      </summary>
      <div class="mt-3 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
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
              <h4>
                <TwinIdentity
                  :identity-key="persona.persona_id"
                  :name="persona.profile.name"
                  :description="profileDescription(persona.profile.observations)"
                  :locale="locale"
                />
              </h4>

              <p class="mt-1 text-xs font-medium tracking-wide text-slate-500 uppercase">
                {{ personaStatusLabel(persona) }}
                · v{{ persona.version_number }}
              </p>
            </div>
          </div>

          <details
            class="mt-4"
            :open="persona.profile.confirmation_status === 'PENDING_CONFIRMATION'"
          >
            <summary class="cursor-pointer text-sm font-semibold text-slate-600">
              {{ copy.profileDetails }}
            </summary>
            <div class="mt-3 space-y-3">
              <div
                v-for="observation in persona.profile.observations"
                :key="observation.observation_key"
                class="rounded-lg bg-slate-50 p-3"
              >
                <p class="text-xs font-semibold tracking-wide text-slate-500 uppercase">
                  {{
                    observationField(observation)
                      ? fieldLabel(observationField(observation) as UserTwinField)
                      : locale === "it"
                        ? "Informazione sul profilo"
                        : "Profile information"
                  }}
                </p>

                <p class="mt-1 text-sm text-slate-900">
                  {{ formatObservation(observation) }}
                </p>

                <p class="mt-2 text-xs text-slate-600">{{ observationSummary(observation) }}</p>
                <details class="mt-3">
                  <summary class="cursor-pointer text-xs font-medium text-slate-500">
                    {{ copy.evidenceDetails }}
                  </summary>
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
                </details>
              </div>
            </div>
          </details>
          <details class="mt-3 text-xs text-slate-500" data-testid="persona-technical-details">
            <summary class="cursor-pointer">{{ copy.technicalDetails }}</summary>
            <p class="mt-2">{{ persona.profile.kind }} · {{ persona.persona_id }}</p>
          </details>

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

      <div
        v-if="store.currentSnapshot === null || store.readiness?.context_current === false"
        class="mt-5"
      >
        <p v-if="store.readiness?.context_current === false" role="status">
          {{
            locale === "it"
              ? "Brief o team sono cambiati: genera una nuova versione degli User Twin e approvala prima di proseguire."
              : "The brief or team changed: generate and approve a new User Twin version before continuing."
          }}
        </p>
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
    </details>

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

        <details class="max-w-full text-xs text-slate-500" data-testid="profiles-technical-details">
          <summary class="cursor-pointer">{{ copy.technicalDetails }}</summary>
          <code class="mt-2 block break-all">
            {{ store.currentSnapshot.content_hash }}
          </code>
        </details>
      </div>

      <div class="mt-5 grid gap-5">
        <article
          v-for="twin in twins"
          :key="twin.id"
          class="rounded-xl border border-slate-200 p-4"
        >
          <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h4>
                <TwinIdentity
                  :identity-key="twin.profile.persona_reference.persona_id"
                  :name="twin.profile.name"
                  :description="profileDescription(twin.profile.observations)"
                  :locale="locale"
                />
              </h4>
              <p class="mt-2 text-xs font-medium text-slate-600">{{ lifecycleLabel(twin) }}</p>

              <details class="mt-2 text-xs text-slate-500" data-testid="twin-technical-details">
                <summary class="cursor-pointer">{{ copy.technicalDetails }}</summary>
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
              </details>
            </div>
          </div>

          <details
            class="mt-4"
            :open="!store.readiness?.approved_current_snapshot"
            data-testid="twin-profile-details"
          >
            <summary class="cursor-pointer text-sm font-semibold text-slate-600">
              {{ copy.profileDetails }}
            </summary>
            <div class="mt-3 grid gap-4">
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

                <p class="mt-2 text-xs text-slate-600">{{ observationSummary(observation) }}</p>
                <details class="mt-3">
                  <summary class="cursor-pointer text-xs font-medium text-slate-500">
                    {{ copy.evidenceDetails }}
                  </summary>
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
                </details>
              </article>
            </div>
          </details>
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
          <legend class="text-sm font-semibold text-slate-700">{{ copy.knowledgeSource }}</legend>

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
            <details class="text-xs text-slate-500">
              <summary class="cursor-pointer">{{ copy.technicalDetails }}</summary>
              <code class="mt-2 block break-all">
                {{ diff.id }}
              </code>
            </details>

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
            {{ workflowStatusLabel(store.currentGate?.status, locale) }}
          </dd>
        </div>
      </dl>

      <details class="mt-3 text-xs text-slate-500">
        <summary class="cursor-pointer">{{ copy.technicalDetails }}</summary>
        <p class="mt-2">
          {{ store.currentGate?.status ?? "—" }} · {{ store.readiness?.workflow_state ?? "—" }}
        </p>
      </details>

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
