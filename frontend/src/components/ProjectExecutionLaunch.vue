<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/api/client";
import { ApiRequestError } from "@/api/requestError";
import {
  executionLaunchApi,
  type ExecutionLaunchApi,
  type ExecutionOperation,
  type ExecutionJourney,
  type JourneyStep,
  type BrowserExecutionChecks as BrowserChecks,
} from "@/api/executionLaunch";
import BrowserExecutionChecks from "./BrowserExecutionChecks.vue";
import { journeySentence } from "./journeyText";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import type { SourcePlatform } from "@/api/sourceGeneration";
import { useAuthStore } from "@/stores/auth";
import { useWebExecutionStore } from "@/stores/webExecution";

const props = withDefaults(
  defineProps<{
    projectId: string;
    platform: SourcePlatform;
    locale?: "it" | "en";
    api?: ExecutionLaunchApi;
    authorize?: <T>(operation: (token: string) => Promise<T>) => Promise<T>;
  }>(),
  { locale: "en" },
);
const auth = useAuthStore();
const web = useWebExecutionStore();
const store = computed(() => web);
const source = computed(() =>
  store.value.activeProjectId === props.projectId ? store.value.currentSourceRevision : null,
);
const operation = ref<ExecutionOperation | null>(null);
const pending = ref(false);
const error = ref<string | null>(null);
const result = ref<string | null>(null);
const browserChecks = ref<BrowserChecks | null>(null);
const journey = ref<ExecutionJourney | null>(null);
const manualChecks = ref(false);
const derived = computed(
  () =>
    journey.value?.status === "DERIVED" &&
    journey.value.source_revision_id === source.value?.id &&
    !manualChecks.value,
);
function journeyChecks(current: ExecutionJourney): BrowserChecks {
  return {
    declared_routes: current.declared_routes ?? [],
    browser_interactions: current.browser_interactions ?? [],
  };
}
const sentence = (step: JourneyStep) => journeySentence(step, props.locale);
function editSample(index: number, next: string) {
  const current = journey.value;
  if (!current?.steps || !current.browser_interactions) return;
  const previous = current.steps[index]?.action.value ?? "";
  const steps = current.steps.map((step, position) => {
    const own = position === index && step.action.kind === "fill";
    const linked = step.action.kind === "expect_contains" && step.action.value === previous;
    return own || linked ? { ...step, action: { ...step.action, value: next } } : step;
  });
  journey.value = {
    ...current,
    steps,
    browser_interactions: [
      {
        route_id: current.browser_interactions[0]?.route_id ?? "root",
        actions: steps.map((step) => step.action),
      },
    ],
  };
}
watch(
  [journey, manualChecks],
  () => {
    if (derived.value && journey.value) browserChecks.value = journeyChecks(journey.value);
    else if (journey.value?.status === "DERIVED" && manualChecks.value) browserChecks.value = null;
  },
  { deep: true },
);
async function loadJourney() {
  const revision = source.value;
  if (!revision || props.platform !== "web" || revision.target_selection.target !== "WEB_STATIC") {
    journey.value = null;
    return;
  }
  const generation = epoch;
  try {
    const loaded = await authorized((token) =>
      (props.api ?? executionLaunchApi).journey(props.projectId, token),
    );
    if (generation === epoch) journey.value = loaded;
  } catch {
    if (generation === epoch) journey.value = null;
  }
}
const needsBrowser = computed(
  () => props.platform === "web" && source.value?.target_selection.target !== "WEB_NODE_EXPRESS",
);
let epoch = 0;
const exact = computed(
  () =>
    operation.value?.source_revision_id === source.value?.id &&
    (operation.value?.payload.source_revision?.content_hash ??
      operation.value?.payload.proposal?.base_revision.content_hash) === source.value?.content_hash,
);
const active = computed(
  () => exact.value && operation.value?.gate_current && operation.value.state === "PENDING",
);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Esegui e raccogli evidenze",
        intro: "Prepara il piano, controllalo e approva l’esecuzione della revisione corrente.",
        prepare: "Prepara piano",
        refresh: "Aggiorna stato",
        approve: "Approva questo piano",
        cancel: "Annulla piano",
        start: "Avvia esecuzione approvata",
        applyRepair: "Applica riparazione approvata",
        repaired: "Riparazione applicata",
        phases: "Fasi previste",
        revision: "Revisione",
        details: "Dettagli del piano e riferimenti esatti",
        state: "Stato",
        saved: "Esito registrato",
        failed: "Operazione non completata. Aggiorna lo stato prima di riprovare.",
        unavailable: "Il runtime di esecuzione non è disponibile o non è configurato.",
        running: "Operazione in corso…",
        pending: "È necessario decidere sul piano esistente prima di prepararne un altro.",
        journey: "Percorso di verifica nel browser, derivato dal design approvato",
        journeyIntro:
          "La piattaforma proverà questi passi sulla pagina generata. Puoi cambiare solo i valori di esempio.",
        sample: "Valore di esempio",
        manual: "Definisci i passi manualmente",
        automatic: "Torna al percorso derivato",
        notDerivable:
          "Il percorso non può essere derivato dal design: definisci i passi manualmente.",
      }
    : {
        title: "Run and collect evidence",
        intro: "Prepare the plan, review it and approve execution of the current source revision.",
        prepare: "Prepare plan",
        refresh: "Refresh state",
        approve: "Approve this plan",
        cancel: "Cancel plan",
        start: "Start approved execution",
        applyRepair: "Apply approved repair",
        repaired: "Repair applied",
        phases: "Planned phases",
        revision: "Revision",
        details: "Plan details and exact references",
        state: "State",
        saved: "Recorded outcome",
        failed: "The operation did not complete. Refresh its state before retrying.",
        unavailable: "The execution runtime is unavailable or not configured.",
        running: "Operation in progress…",
        pending: "Decide on the existing plan before preparing another one.",
        journey: "Browser verification journey, derived from the approved design",
        journeyIntro:
          "The platform will try these steps on the generated page. Only the sample values can be changed.",
        sample: "Sample value",
        manual: "Define the steps manually",
        automatic: "Back to the derived journey",
        notDerivable: "The journey cannot be derived from the design: define the steps manually.",
      },
);
function authorized<T>(fn: (token: string) => Promise<T>): Promise<T> {
  return props.authorize?.(fn) ?? auth.withAccessToken(apiClient, fn);
}
async function act(
  fn: (
    api: ExecutionLaunchApi,
    project: string,
    platform: SourcePlatform,
    currentEpoch: number,
  ) => Promise<void>,
) {
  if (pending.value) return;
  const currentEpoch = epoch;
  const project = props.projectId;
  const platform = props.platform;
  pending.value = true;
  error.value = null;
  try {
    await fn(props.api ?? executionLaunchApi, project, platform, currentEpoch);
  } catch (cause) {
    if (currentEpoch === epoch)
      error.value =
        cause instanceof ApiRequestError && cause.status === 503
          ? copy.value.unavailable
          : copy.value.failed;
  } finally {
    if (currentEpoch === epoch) pending.value = false;
  }
}
async function refresh() {
  await act(async (api, project, platform, generation) => {
    const history = await authorized((token) => api.history(project, platform, token));
    if (generation === epoch)
      operation.value = history.filter((item) => item.gate_current).at(-1) ?? null;
  });
}
async function prepare() {
  const revision = source.value;
  const checks = needsBrowser.value ? browserChecks.value : undefined;
  if (!revision || checks === null) return;
  await act(async (api, project, platform, generation) => {
    const prepared = await authorized((token) =>
      api.prepare(project, platform, revision, token, checks),
    );
    if (generation === epoch) {
      operation.value = prepared;
      result.value = null;
    }
  });
}
async function decide(action: "APPROVE" | "CANCEL") {
  const current = operation.value;
  if (
    !current ||
    !current.gate_current ||
    current.state !== "PENDING" ||
    (action === "APPROVE" && !active.value)
  )
    return;
  await act(async (api, project, platform, generation) => {
    const updated = await authorized((token) =>
      api.decide(project, platform, current, action, token),
    );
    if (generation === epoch) operation.value = updated;
  });
}
async function start() {
  const current = operation.value;
  if (
    !current ||
    current.kind !== "EXECUTION" ||
    !active.value ||
    current.gate.status !== "APPROVED"
  )
    return;
  await act(async (api, project, platform, generation) => {
    const executionStore = store.value;
    const executed = await authorized((token) => api.start(project, platform, current, token));
    if (generation !== epoch) return;
    result.value = executed.report.status;
    operation.value = { ...current, state: "COMPLETED" };
    await executionStore.loadProject(project, authorized);
    if (generation !== epoch) return;
    await executionStore.loadExecution(project, executed.id, authorized);
  });
}
async function applyRepair() {
  const current = operation.value;
  if (!current || current.kind !== "REPAIR" || !active.value || current.gate.status !== "APPROVED")
    return;
  await act(async (api, project, platform, generation) => {
    const executionStore = store.value;
    const revision = await authorized((token) => api.applyRepair(platform, current, token));
    if (generation !== epoch) return;
    operation.value = { ...current, state: "COMPLETED" };
    result.value = `${copy.value.repaired}: ${revision.id}`;
    await executionStore.loadProject(project, authorized);
  });
}
watch(
  [
    () => props.projectId,
    () => props.platform,
    () => source.value?.id,
    () => source.value?.content_hash,
  ],
  () => {
    epoch++;
    operation.value = null;
    pending.value = false;
    result.value = null;
    error.value = null;
    journey.value = null;
    manualChecks.value = false;
    if (source.value) {
      void refresh();
      void loadJourney();
    }
  },
  { immediate: true },
);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <UiCard v-if="source" :aria-busy="pending">
    <div class="grid gap-5">
      <div class="grid gap-2">
        <h2 class="m-0 text-2xl font-semibold tracking-card">
          {{ copy.title }} · {{ platform.toUpperCase() }}
        </h2>
        <p class="m-0 text-[15px] text-ink-2">{{ copy.intro }}</p>
        <p class="m-0 font-mono text-xs text-ink-3">
          {{ copy.revision }} {{ source.version_number }} · {{ source.target_selection.target }}
        </p>
      </div>
      <UiCard v-if="needsBrowser && journey?.status === 'DERIVED'" tone="soft">
        <h3 class="m-0 text-lg font-semibold tracking-block">{{ copy.journey }}</h3>
        <p class="mt-1 mb-0 text-sm text-ink-2">{{ copy.journeyIntro }}</p>
        <ol v-if="derived" class="m-0 mt-3 grid list-none gap-0 p-0 text-[15px]">
          <li
            v-for="(step, index) in journey.steps"
            :key="index"
            class="grid grid-cols-[28px_minmax(0,1fr)] items-center gap-2 rounded-control px-2 py-2 odd:bg-row-alt"
          >
            <span class="font-mono text-xs text-ink-3">{{ index + 1 }}</span>
            <span class="flex flex-wrap items-center gap-2">
              <span>{{ sentence(step) }}</span>
              <label v-if="step.action.kind === 'fill'" class="inline-flex items-center gap-1">
                <span class="sr-only">{{ copy.sample }}</span>
                <input
                  :value="step.action.value ?? ''"
                  maxlength="1000"
                  class="min-h-9 rounded-control border border-dashed border-sample-line bg-sample-bg px-2 font-mono text-[13px] text-ink"
                  :disabled="
                    pending || operation?.state === 'PENDING' || operation?.state === 'RUNNING'
                  "
                  @input="editSample(index, ($event.target as HTMLInputElement).value)"
                />
              </label>
            </span>
          </li>
        </ol>
        <div class="mt-4">
          <UiButton variant="secondary" @click="manualChecks = !manualChecks">
            {{ manualChecks ? copy.automatic : copy.manual }}
          </UiButton>
        </div>
      </UiCard>
      <p
        v-else-if="needsBrowser && journey?.status === 'NOT_DERIVABLE'"
        class="m-0 text-[15px] text-ink-2"
      >
        {{ copy.notDerivable }}
      </p>
      <BrowserExecutionChecks
        v-if="needsBrowser && !derived"
        :key="`${projectId}:${source.id}`"
        :locale="locale"
        :disabled="pending || operation?.state === 'PENDING' || operation?.state === 'RUNNING'"
        @change="browserChecks = $event"
      />
      <div class="flex flex-wrap gap-3">
        <UiButton variant="secondary" :disabled="pending" @click="refresh">
          {{ copy.refresh }}
        </UiButton>
        <UiButton
          :disabled="
            pending ||
            (needsBrowser && !browserChecks) ||
            operation?.state === 'RUNNING' ||
            (operation?.gate_current &&
              operation.state === 'PENDING' &&
              !['CANCELLED', 'REJECTED'].includes(operation.gate.status))
          "
          @click="prepare"
        >
          {{ copy.prepare }}
        </UiButton>
      </div>
      <template v-if="operation">
        <div class="grid gap-1 font-mono text-xs text-ink-3">
          <p class="m-0">{{ copy.state }}: {{ operation.state }} · {{ operation.gate.status }}</p>
          <p v-if="operation.payload.effective_phases" class="m-0">
            {{ copy.phases }}: {{ operation.payload.effective_phases.join(" → ") }}
          </p>
          <p class="m-0">
            Gate 7 · {{ operation.kind }} · <code>{{ operation.id }}</code>
          </p>
        </div>
        <details class="rounded-panel border border-line px-4 py-3">
          <summary class="cursor-pointer text-sm font-semibold text-ink-2">
            {{ copy.details }}
          </summary>
          <pre class="mt-3 max-h-80 overflow-auto font-mono text-xs whitespace-pre-wrap">{{
            JSON.stringify(operation.payload, null, 2)
          }}</pre>
        </details>
        <div class="flex flex-wrap gap-3">
          <UiButton
            variant="secondary"
            :disabled="pending || !active || operation.gate.status !== 'PENDING_APPROVAL'"
            @click="decide('APPROVE')"
          >
            {{ copy.approve }}
          </UiButton>
          <UiButton
            variant="secondary"
            :disabled="
              pending ||
              !operation.gate_current ||
              operation.state !== 'PENDING' ||
              !['PENDING_APPROVAL', 'APPROVED'].includes(operation.gate.status)
            "
            @click="decide('CANCEL')"
          >
            {{ copy.cancel }}
          </UiButton>
          <UiButton
            v-if="operation.kind === 'EXECUTION'"
            :disabled="pending || !active || operation.gate.status !== 'APPROVED'"
            @click="start"
          >
            {{ copy.start }}
          </UiButton>
          <UiButton
            v-else-if="operation.kind === 'REPAIR'"
            :disabled="pending || !active || operation.gate.status !== 'APPROVED'"
            @click="applyRepair"
          >
            {{ copy.applyRepair }}
          </UiButton>
        </div>
      </template>
      <p v-if="pending" class="m-0 font-mono text-xs text-ink-3" role="status">
        {{ copy.running }}
      </p>
      <p v-if="result" class="m-0 text-[15px] font-semibold text-ok-dark" role="status">
        {{ copy.saved }}: {{ result }}
      </p>
      <p v-if="error" class="m-0 text-[15px] font-semibold text-fail-dark" role="alert">
        {{ error }}
      </p>
    </div>
  </UiCard>
</template>
