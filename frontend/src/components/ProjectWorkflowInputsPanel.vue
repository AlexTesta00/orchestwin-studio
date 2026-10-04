<script setup lang="ts">
import { computed, reactive, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError } from "@/api/client";
import { requirementsApi } from "@/api/requirements";
import {
  workflowInputsApi,
  WorkflowInputsApiError,
  type WorkflowInputsApi,
} from "@/api/workflowInputs";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import UiButton from "./UiButton.vue";
import UiStateBlock from "./UiStateBlock.vue";
import { useTeamStore } from "@/stores/team";
import { useUserModelingStore } from "@/stores/userModeling";
import { useRequirementsStore } from "@/stores/requirements";
import type { HumanGatePayload } from "@/types/design";
import type {
  OwnerDefinitionInput,
  OwnerProfilesInput,
  OwnerTeamInput,
  ProvidedPrototype,
  ProvidedPrototypeInput,
  WorkflowInputsPayload,
  WorkflowReference,
  WorkflowTarget,
} from "@/types/workflowInputs";

const props = withDefaults(
  defineProps<{
    projectId: string;
    stage: number;
    expert: boolean;
    definitionReady?: boolean;
    locale?: "it" | "en";
    authorize: <T>(operation: (token: string) => Promise<T>) => Promise<T>;
    baseContext: Partial<Record<WorkflowTarget, WorkflowReference>>;
    api?: WorkflowInputsApi;
  }>(),
  { locale: "en", api: () => workflowInputsApi, definitionReady: true },
);
const emit = defineEmits<{
  changed: [];
  "prototype-changed": [prototype: ProvidedPrototype | null, gate: HumanGatePayload | null];
}>();
const team = useTeamStore();
const { t } = useI18n({ useScope: "global" });
const modeling = useUserModelingStore();
const requirements = useRequirementsStore();
const id = useId();
const records = ref<WorkflowInputsPayload | null>(null);
const prototype = ref<ProvidedPrototype | null>(null);
const gate = ref<HumanGatePayload | null>(null);
const document = ref<{ html: string; title: string } | null>(null);
const busy = ref(false);
const error = ref<string | null>(null);
const saved = ref(false);
const editors = reactive<Record<number, string>>({});
const reasons = reactive<Partial<Record<WorkflowTarget, string>>>({});
const target = ref<WorkflowTarget>("BRIEF");
const origin = ref("");
const gateReason = ref("");
let epoch = 0;
const stageTargets: WorkflowTarget[][] = [
  ["BRIEF"],
  ["TEAM"],
  ["USER_TWINS", "EVIDENCE"],
  ["SCENARIOS", "NEEDS", "REQUIREMENTS", "JOURNEYS"],
  ["DESIGN", "EVALUATION"],
  ["PACKAGE"],
];
const targets = computed<WorkflowTarget[]>(() => stageTargets[props.stage] ?? ["PACKAGE"]);
const copy = computed(() =>
  props.locale === "it"
    ? {
        owner: "Fornito dal proprietario",
        gap: "Lacuna dichiarata",
        missing: "Non disponibile",
        resolve: "Risolvi la lacuna",
        declare: "Dichiara la lacuna",
        target: "Contenuto",
        reason: "Motivo e limiti",
        save: "Salva una nuova versione",
        saved: "Salvato e riletto dal server. L'approvazione resta un passaggio separato.",
        json: "Contenuto strutturato (JSON)",
        template: "Prepara il modulo dal contesto attuale",
        team: "Scegli le prospettive del catalogo e scrivi i tuoi motivi. Le regole di composizione vengono controllate al salvataggio.",
        catalog: "Prospettive del catalogo",
        twins:
          "Fornisci i profili di tutti gli archetipi attivi e confermati. Riusa il modulo degli archetipi o importa twin esistenti qui sotto. Le informazioni del proprietario non sono prove empiriche.",
        definition:
          "Fornisci una Definizione completa: scenari, bisogni, requisiti, storie, criteri di accettazione e Definition of Done con i riferimenti coerenti. I journey restano facoltativi. Una revisione torna alla tua approvazione.",
        prototype:
          "Fornisci un prototipo con 2–8 schermate, stili e scelte visive del catalogo. Una sola schermata viene rifiutata. Il server controlla sicurezza, accessibilità e collegamenti ai requisiti.",
        origin: "Origine dichiarata",
        originHint: "Facoltativa, per esempio lo strumento usato per realizzarlo.",
        evaluation:
          "La valutazione dei twin sul prototipo fornito non è disponibile nello sprint 36.",
        future:
          "La struttura è la stessa dei mockup generati. Per questo Design non sono disponibili nemmeno ut code e il percorso sugli scenari.",
        submit: "Invia il prototipo all'approvazione",
        approve: "Approva questo prototipo",
        reject: "Rifiuta",
        revise: "Chiedi una revisione",
        history: "Versioni del prototipo",
        preview: "Anteprima convalidata",
        current: "Versione {n}",
        prerequisites:
          "Il salvataggio richiede gli input approvati della sezione precedente. Una lacuna non li sostituisce.",
        refresh: "Rileggi",
        unresolved:
          "Le lacune restano visibili nel Perché? e nel Dossier. Non creano contenuti o approvazioni.",
        statuses: {
          DRAFT: "Bozza",
          PENDING_APPROVAL: "In attesa della tua approvazione",
          APPROVED: "Approvato",
          REJECTED: "Rifiutato",
          REVISION_REQUESTED: "Revisione richiesta",
          STALE: "Da aggiornare",
        },
      }
    : {
        owner: "Owner supplied",
        gap: "Declared gap",
        missing: "Unavailable",
        resolve: "Resolve the gap",
        declare: "Declare the gap",
        target: "Content",
        reason: "Reason and limits",
        save: "Save a new version",
        saved: "Saved and reread from the server. Approval remains a separate step.",
        json: "Structured content (JSON)",
        template: "Prepare the form from the current context",
        team: "Select perspectives from the catalog and write your reasons. Composition rules are checked when saving.",
        catalog: "Catalog perspectives",
        twins:
          "Supply profiles for all active confirmed archetypes. Reuse the archetype form or import existing twins below. Owner information is not empirical evidence.",
        definition:
          "Supply a complete Definition: scenarios, needs, requirements, stories, acceptance criteria and Definition of Done with coherent references. Journeys remain optional. A revision returns for your approval.",
        prototype:
          "Supply a prototype with 2–8 screens, styles and catalog visual choices. A single screen is rejected. The server checks safety, accessibility and requirement links.",
        origin: "Declared origin",
        originHint: "Optional, for example the tool used to create it.",
        evaluation: "Twin evaluation of the supplied prototype is unavailable in sprint 36.",
        future:
          "Its structure matches generated mockups. ut code and the scenario walkthrough are also unavailable for this Design.",
        submit: "Submit the prototype for approval",
        approve: "Approve this prototype",
        reject: "Reject",
        revise: "Request a revision",
        history: "Prototype versions",
        preview: "Validated preview",
        current: "Version {n}",
        prerequisites:
          "Saving requires the previous section's approved inputs. A gap does not replace them.",
        refresh: "Reread",
        unresolved:
          "Gaps remain visible in Why? and the Dossier. They create no content or approvals.",
        statuses: {
          DRAFT: "Draft",
          PENDING_APPROVAL: "Waiting for your approval",
          APPROVED: "Approved",
          REJECTED: "Rejected",
          REVISION_REQUESTED: "Revision requested",
          STALE: "Needs updating",
        },
      },
);
const labels = computed<Record<WorkflowTarget, string>>(() =>
  props.locale === "it"
    ? {
        BRIEF: "Brief",
        TEAM: "Prospettive",
        USER_TWINS: "User Twin",
        EVIDENCE: "Evidenze",
        SCENARIOS: "Scenari",
        NEEDS: "Bisogni",
        REQUIREMENTS: "Definizione",
        JOURNEYS: "Journey",
        DESIGN: "Design",
        EVALUATION: "Valutazione",
        PACKAGE: "Dossier",
      }
    : {
        BRIEF: "Brief",
        TEAM: "Perspectives",
        USER_TWINS: "User Twin",
        EVIDENCE: "Evidence",
        SCENARIOS: "Scenarios",
        NEEDS: "Needs",
        REQUIREMENTS: "Definition",
        JOURNEYS: "Journeys",
        DESIGN: "Design",
        EVALUATION: "Evaluation",
        PACKAGE: "Dossier",
      },
);
const latestDecisions = computed(() => {
  const latest = new Map<WorkflowTarget, NonNullable<WorkflowInputsPayload["decisions"][number]>>();
  for (const decision of records.value?.decisions ?? []) latest.set(decision.target, decision);
  return [...latest.values()].filter((decision) => decision.action === "DECLARE_MISSING");
});
const hasEditor = computed(() => props.stage >= 1 && props.stage <= 4);
const instruction = computed(
  () =>
    ["", copy.value.team, copy.value.twins, copy.value.definition, copy.value.prototype][
      props.stage
    ] ?? "",
);
const editor = computed({
  get: () => editors[props.stage] ?? "",
  set: (value: string) => (editors[props.stage] = value),
});
const reason = computed({
  get: () => reasons[target.value] ?? "",
  set: (value: string) => (reasons[target.value] = value),
});
const currentGate = computed(() =>
  gate.value &&
  prototype.value &&
  gate.value.artifact.artifact_id === prototype.value.id &&
  gate.value.artifact.content_hash === prototype.value.content_hash
    ? gate.value
    : null,
);
const prototypeAligned = computed(() => {
  const reference = props.baseContext.REQUIREMENTS;
  return !!(
    props.definitionReady &&
    reference &&
    prototype.value &&
    reference.artifact_id === prototype.value.definition_reference.artifact_id &&
    reference.version_number === prototype.value.definition_reference.version_number &&
    reference.content_hash === prototype.value.definition_reference.content_hash
  );
});
const gateStatus = computed(() =>
  !prototypeAligned.value
    ? copy.value.statuses.STALE
    : currentGate.value
      ? (copy.value.statuses[currentGate.value.status as keyof typeof copy.value.statuses] ??
        currentGate.value.status)
      : copy.value.statuses.DRAFT,
);

async function optional<T>(operation: () => Promise<T>): Promise<T | null> {
  try {
    return await operation();
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404) return null;
    throw failure;
  }
}

async function load(): Promise<void> {
  const currentEpoch = ++epoch;
  const projectId = props.projectId;
  try {
    const [nextRecords, nextPrototype, nextGate] = await Promise.all([
      props.authorize((token) => props.api.read(projectId, token)),
      optional(() => props.authorize((token) => props.api.currentPrototype(projectId, token))),
      optional(() => props.authorize((token) => props.api.prototypeGate(projectId, token))),
    ]);
    if (currentEpoch !== epoch || props.projectId !== projectId) return;
    records.value = nextRecords;
    prototype.value = nextPrototype;
    gate.value = nextGate;
    emit("prototype-changed", nextPrototype, nextGate);
  } catch (failure) {
    if (currentEpoch === epoch)
      error.value = failure instanceof ApiError ? failure.detail : "WORKFLOW_INPUTS_READ_FAILED";
  }
}

async function perform(operation: () => Promise<unknown>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  saved.value = false;
  const projectId = props.projectId;
  try {
    const result = await operation();
    const outcome = result as { issue?: string | null; status?: string; outcome?: string } | null;
    if (outcome?.issue || outcome?.status === "REJECTED" || outcome?.outcome === "REJECTED")
      throw new Error(outcome.issue ?? "OWNER_INPUT_REJECTED");
    if (projectId !== props.projectId) return;
    await load();
    if (error.value === null) {
      saved.value = true;
      emit("changed");
    }
  } catch (failure) {
    if (projectId === props.projectId)
      error.value =
        failure instanceof WorkflowInputsApiError && failure.message !== failure.detail
          ? `${failure.detail} · ${failure.message}`
          : failure instanceof ApiError
            ? failure.detail
            : failure instanceof Error
              ? failure.message
              : "OWNER_INPUT_REJECTED";
  } finally {
    if (projectId === props.projectId) busy.value = false;
  }
}

function prepareForm(): void {
  if (editor.value.trim()) return;
  let value: unknown;
  if (props.stage === 1) {
    value = {
      selected_agent_ids:
        team.catalog?.agents
          .filter((agent) => agent.is_always_present)
          .map((agent) => agent.agent_id) ?? [],
      owner_rationales: [],
    };
  } else if (props.stage === 2) {
    value = {
      profiles: (modeling.projectId === props.projectId ? modeling.currentPersonas : [])
        .filter(
          (persona) =>
            !persona.profile.archived && persona.profile.confirmation_status === "CONFIRMED",
        )
        .map((persona) => ({
          persona_id: persona.persona_id,
          name: persona.profile.name,
          observations: [],
        })),
    };
  } else if (props.stage === 3) {
    const specification = (requirements.projectId === props.projectId
      ? requirements.current?.specification
      : null) ?? {
      schema_version: 2,
      project_id: props.projectId,
      ...(props.baseContext.BRIEF
        ? { project_brief_reference: { kind: "PROJECT_BRIEF", ...props.baseContext.BRIEF } }
        : {}),
      ...(props.baseContext.TEAM
        ? { agent_team_reference: { kind: "AGENT_TEAM", ...props.baseContext.TEAM } }
        : {}),
      ...(props.baseContext.USER_TWINS
        ? { user_modeling_reference: { kind: "USER_MODELING", ...props.baseContext.USER_TWINS } }
        : {}),
      catalog_version: team.catalog?.catalog_version,
      catalog_content_hash: team.catalog?.content_hash,
      user_twin_references: (modeling.projectId === props.projectId
        ? modeling.currentTwins
        : []
      ).map((twin) => ({
        twin_id: twin.twin_id,
        version_number: twin.version_number,
        content_hash: twin.content_hash,
        name: twin.profile.name,
      })),
      scenarios: [],
      needs: [],
      requirements: [],
      user_stories: [],
      acceptance_criteria: [],
      risks: [],
      definition_of_done: [],
    };
    value = { specification: { ...specification, schema_version: 2 } };
  } else {
    value = prototype.value
      ? {
          title: prototype.value.title,
          visual_choices: prototype.value.visual_choices,
          mockup: {
            title: prototype.value.mockup.mockup.title,
            styles: prototype.value.mockup.mockup.styles,
            screens: prototype.value.mockup.mockup.screens,
          },
        }
      : { title: "", visual_choices: {}, mockup: { styles: "", screens: [] } };
  }
  editor.value = JSON.stringify(value, null, 2);
}

async function saveInput(): Promise<void> {
  await perform(async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(editor.value);
    } catch {
      throw new Error("OWNER_INPUT_INVALID_JSON");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      throw new Error("OWNER_INPUT_OBJECT_REQUIRED");
    if (props.stage === 1)
      return props.authorize((token) =>
        props.api.team(props.projectId, parsed as OwnerTeamInput, token),
      );
    if (props.stage === 2)
      return props.authorize((token) =>
        props.api.profiles(props.projectId, parsed as OwnerProfilesInput, token),
      );
    if (props.stage === 3) {
      const input = parsed as OwnerDefinitionInput;
      if (input.specification?.schema_version !== 2)
        throw new Error("OWNER_DEFINITION_SCHEMA_2_REQUIRED");
      return requirements.projectId === props.projectId && requirements.current
        ? props.authorize((token) =>
            requirementsApi.proposeRevision(
              props.projectId,
              { specification: input.specification },
              token,
            ),
          )
        : props.authorize((token) => props.api.definition(props.projectId, input, token));
    }
    const reference = props.baseContext.REQUIREMENTS;
    if (!reference) throw new Error("REQUIREMENTS_APPROVAL_REQUIRED");
    const input = parsed as ProvidedPrototypeInput;
    const { declared_origin: discardedOrigin, ...contents } = input;
    void discardedOrigin;
    return props.authorize((token) =>
      props.api.savePrototype(
        props.projectId,
        {
          ...contents,
          ...(origin.value.trim() ? { declared_origin: origin.value.trim() } : {}),
          expected_definition_reference: reference,
          expected_version_number: prototype.value?.version_number ?? 0,
        },
        token,
      ),
    );
  });
}

async function decideGap(action: "DECLARE_MISSING" | "RESOLVE_MISSING"): Promise<void> {
  await perform(() =>
    props.authorize((token) =>
      props.api.decide(
        props.projectId,
        { target: target.value, action, reason: reason.value, base_context: props.baseContext },
        token,
      ),
    ),
  );
}

async function showPreview(screen?: string): Promise<void> {
  const version = prototype.value;
  if (!version) return;
  error.value = null;
  const currentEpoch = epoch;
  try {
    const next = await props.authorize((token) =>
      props.api.prototypeDocument(props.projectId, version.id, token, screen),
    );
    if (epoch === currentEpoch && prototype.value?.id === version.id) document.value = next;
  } catch (failure) {
    error.value =
      failure instanceof ApiError ? failure.detail : "PROVIDED_PROTOTYPE_DOCUMENT_UNAVAILABLE";
  }
}

async function decidePrototype(action: "APPROVE" | "REJECT" | "REQUEST_REVISION"): Promise<void> {
  await perform(() =>
    props.authorize((token) =>
      props.api.decidePrototype(
        props.projectId,
        { action, ...(gateReason.value.trim() ? { reason: gateReason.value } : {}) },
        token,
      ),
    ),
  );
}

watch(
  () => props.projectId,
  () => {
    epoch++;
    records.value = null;
    prototype.value = null;
    gate.value = null;
    document.value = null;
    error.value = null;
    saved.value = false;
    busy.value = false;
    origin.value = "";
    Object.keys(editors).forEach((key) => delete editors[Number(key)]);
    Object.keys(reasons).forEach((key) => delete reasons[key as WorkflowTarget]);
    void load();
  },
  { immediate: true },
);
watch(
  targets,
  (values) => {
    if (!values.includes(target.value)) target.value = values[0] ?? "PACKAGE";
  },
  { immediate: true },
);
watch(
  () => prototype.value?.id,
  () => {
    document.value = null;
    origin.value = prototype.value?.declared_origin ?? "";
  },
);
</script>

<template>
  <section
    class="mt-6 grid min-w-0 gap-4"
    data-testid="workflow-inputs-panel"
    :aria-label="copy.owner"
  >
    <UiStateBlock v-if="error" kind="error" :text="error" data-testid="workflow-inputs-error" />
    <p v-if="saved" role="status" class="text-sm text-petrol-on-night-2">{{ copy.saved }}</p>
    <ul
      v-if="latestDecisions.length"
      class="m-0 grid list-none gap-2 p-0"
      data-testid="declared-gaps"
    >
      <li
        v-for="decision in latestDecisions"
        :key="decision.id"
        class="rounded-field border border-warn-on-night/40 px-4 py-3 text-sm"
      >
        <strong>{{ copy.gap }} · {{ labels[decision.target] }}</strong>
        <p class="mt-1 whitespace-pre-line">{{ decision.reason }}</p>
        <ArtifactWhy
          :code="`GAP-${String(decision.sequence).padStart(3, '0')}`"
          kind="WORKFLOW_DECISION"
          :artifact-id="decision.id"
          :version-number="decision.sequence"
          :content-hash="decision.content_hash"
          :locale="locale"
        />
      </li>
    </ul>
    <details
      v-if="expert"
      class="rounded-panel border border-night-line p-4"
      data-testid="workflow-gap-editor"
    >
      <summary class="min-h-11 cursor-pointer text-sm font-semibold">{{ copy.declare }}</summary>
      <div class="mt-3 grid gap-3">
        <p class="text-sm text-on-night-3">{{ copy.unresolved }}</p>
        <label :for="`${id}-target`">{{ copy.target }}</label>
        <select
          :id="`${id}-target`"
          v-model="target"
          class="min-h-11 rounded-field border border-night-line bg-night px-3"
          :disabled="busy"
        >
          <option v-for="value in targets" :key="value" :value="value">{{ labels[value] }}</option>
        </select>
        <label :for="`${id}-reason`">{{ copy.reason }}</label>
        <textarea
          :id="`${id}-reason`"
          v-model="reason"
          class="min-h-24 rounded-field border border-night-line bg-night p-3"
          maxlength="4000"
          :disabled="busy"
          data-testid="workflow-gap-reason"
        />
        <div class="flex flex-wrap gap-3">
          <UiButton
            :disabled="busy || !reason.trim()"
            @click="decideGap('DECLARE_MISSING')"
            data-testid="declare-workflow-gap"
            >{{ copy.declare }}</UiButton
          ><UiButton
            variant="outline"
            :disabled="busy || !reason.trim()"
            @click="decideGap('RESOLVE_MISSING')"
            data-testid="resolve-workflow-gap"
            >{{ copy.resolve }}</UiButton
          >
        </div>
      </div>
    </details>
    <details
      v-if="expert && hasEditor"
      class="rounded-panel border border-night-line p-4"
      data-testid="owner-input-editor"
    >
      <summary class="min-h-11 cursor-pointer text-sm font-semibold">
        {{ copy.owner }} · {{ labels[targets[0] ?? "PACKAGE"] }}
      </summary>
      <form class="mt-3 grid gap-3" @submit.prevent="saveInput">
        <p class="text-sm text-on-night-2">{{ instruction }}</p>
        <details
          v-if="stage === 1 && team.catalog"
          class="rounded-field border border-night-line p-3"
        >
          <summary class="min-h-11 cursor-pointer text-sm font-semibold">
            {{ copy.catalog }}
          </summary>
          <ul class="m-0 grid gap-2 p-0 pt-3">
            <li
              v-for="agent in team.catalog.agents"
              :key="agent.agent_id"
              class="grid gap-1 text-sm"
            >
              <span>{{ t(agent.name_key) }}</span
              ><code class="text-xs wrap-anywhere">{{ agent.agent_id }}</code>
            </li>
          </ul>
        </details>
        <p class="text-sm text-on-night-3">{{ copy.prerequisites }}</p>
        <UiButton
          type="button"
          variant="outline"
          :disabled="busy"
          @click="prepareForm"
          data-testid="prepare-owner-input"
          >{{ copy.template }}</UiButton
        >
        <label :for="`${id}-json`">{{ copy.json }}</label>
        <textarea
          :id="`${id}-json`"
          v-model="editor"
          class="min-h-64 max-w-full rounded-field border border-night-line bg-night p-3 font-mono text-xs"
          spellcheck="false"
          :disabled="busy"
          data-testid="owner-input-json"
        />
        <template v-if="stage === 4"
          ><label :for="`${id}-origin`">{{ copy.origin }}</label
          ><input
            :id="`${id}-origin`"
            v-model="origin"
            maxlength="200"
            class="min-h-11 rounded-field border border-night-line bg-night px-3"
            data-testid="provided-prototype-origin"
          />
          <p class="text-xs text-on-night-3">{{ copy.originHint }}</p></template
        >
        <UiButton type="submit" :disabled="busy || !editor.trim()" data-testid="save-owner-input">{{
          copy.save
        }}</UiButton>
      </form>
    </details>
    <div
      v-if="prototype && (stage === 4 || stage === 5)"
      class="grid gap-4 rounded-panel border border-night-line p-4"
      data-testid="provided-prototype"
    >
      <h2 class="text-lg font-semibold">{{ prototype.title }} · {{ copy.owner }}</h2>
      <ArtifactWhy
        :code="prototype.code"
        kind="PROVIDED_PROTOTYPE"
        :artifact-id="prototype.id"
        :version-number="prototype.version_number"
        :content-hash="prototype.content_hash"
        :locale="locale"
      />
      <p>
        {{ prototype.code }} · {{ copy.current.replace("{n}", String(prototype.version_number)) }} ·
        {{ gateStatus }}
      </p>
      <p v-if="prototype.declared_origin">{{ copy.origin }}: {{ prototype.declared_origin }}</p>
      <p class="text-sm text-warn-on-night" data-testid="provided-prototype-evaluation-limit">
        {{ copy.evaluation }}
      </p>
      <p class="text-sm text-on-night-3">{{ copy.future }}</p>
      <div class="flex flex-wrap gap-2">
        <UiButton
          v-for="screen in prototype.mockup.mockup.screens"
          :key="screen.code"
          variant="outline"
          @click="showPreview(screen.code)"
          >{{ copy.preview }} · {{ screen.title }}</UiButton
        >
      </div>
      <div v-if="document" class="h-[min(70vh,640px)] min-h-80">
        <GeneratedMockupFrame :html="document.html" :title="document.title" />
      </div>
      <template v-if="stage === 4">
        <UiButton
          v-if="
            !currentGate ||
            currentGate.status === 'DRAFT' ||
            currentGate.status === 'REVISION_REQUESTED'
          "
          :disabled="busy || !prototypeAligned"
          @click="perform(() => authorize((token) => api.submitPrototype(projectId, token)))"
          data-testid="submit-provided-prototype"
          >{{ copy.submit }}</UiButton
        >
        <div
          v-if="prototypeAligned && currentGate?.status === 'PENDING_APPROVAL'"
          class="grid gap-3"
        >
          <label :for="`${id}-gate-reason`">{{ copy.reason }}</label
          ><textarea
            :id="`${id}-gate-reason`"
            v-model="gateReason"
            maxlength="4000"
            class="min-h-24 rounded-field border border-night-line bg-night p-3"
          />
          <div class="flex flex-wrap gap-3">
            <UiButton
              :disabled="busy"
              @click="decidePrototype('APPROVE')"
              data-testid="approve-provided-prototype"
              >{{ copy.approve }}</UiButton
            ><UiButton
              variant="outline"
              :disabled="busy || !gateReason.trim()"
              @click="decidePrototype('REJECT')"
              >{{ copy.reject }}</UiButton
            ><UiButton
              variant="outline"
              :disabled="busy || !gateReason.trim()"
              @click="decidePrototype('REQUEST_REVISION')"
              >{{ copy.revise }}</UiButton
            >
          </div>
        </div>
      </template>
      <details v-if="records?.prototypes.length">
        <summary>{{ copy.history }}</summary>
        <ol class="mt-2 grid gap-2">
          <li
            v-for="version in records.prototypes"
            :key="`${version.id}:${version.version_number}:${version.content_hash}`"
            class="text-sm"
          >
            {{ version.code }} · {{ version.title }} · {{ version.created_at
            }}<code class="block text-xs wrap-anywhere">{{ version.content_hash }}</code>
          </li>
        </ol>
      </details>
    </div>
  </section>
</template>
