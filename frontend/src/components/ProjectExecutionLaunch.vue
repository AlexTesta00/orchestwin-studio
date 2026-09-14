<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/api/client";
import { ApiRequestError } from "@/api/requestError";
import {
  executionLaunchApi,
  type ExecutionLaunchApi,
  type ExecutionOperation,
  type BrowserExecutionChecks as BrowserChecks,
} from "@/api/executionLaunch";
import BrowserExecutionChecks from "./BrowserExecutionChecks.vue";
import type { SourcePlatform } from "@/api/sourceGeneration";
import { useAuthStore } from "@/stores/auth";
import { useWebExecutionStore } from "@/stores/webExecution";
import { useJvmExecutionStore } from "@/stores/jvmExecution";

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
const jvm = useJvmExecutionStore();
const store = computed(() => (props.platform === "web" ? web : jvm));
const source = computed(() =>
  store.value.activeProjectId === props.projectId ? store.value.currentSourceRevision : null,
);
const operation = ref<ExecutionOperation | null>(null);
const pending = ref(false);
const error = ref<string | null>(null);
const result = ref<string | null>(null);
const browserChecks = ref<BrowserChecks | null>(null);
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
    if (source.value) void refresh();
  },
  { immediate: true },
);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <section
    v-if="source"
    class="space-y-4 rounded-2xl border border-slate-200 bg-white p-6"
    :aria-busy="pending"
  >
    <h2 class="text-2xl font-black">{{ copy.title }} · {{ platform.toUpperCase() }}</h2>
    <p>{{ copy.intro }}</p>
    <p>{{ copy.revision }} {{ source.version_number }} · {{ source.target_selection.target }}</p>
    <BrowserExecutionChecks
      v-if="needsBrowser"
      :key="`${projectId}:${source.id}`"
      :locale="locale"
      :disabled="pending || operation?.state === 'PENDING' || operation?.state === 'RUNNING'"
      @change="browserChecks = $event"
    />
    <div class="flex flex-wrap gap-3">
      <button class="rounded border p-2 disabled:opacity-50" :disabled="pending" @click="refresh">
        {{ copy.refresh }}
      </button>
      <button
        class="rounded border p-2 disabled:opacity-50"
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
      </button>
    </div>
    <template v-if="operation">
      <p>{{ copy.state }}: {{ operation.state }} · {{ operation.gate.status }}</p>
      <p v-if="operation.payload.effective_phases">
        {{ copy.phases }}: {{ operation.payload.effective_phases.join(" → ") }}
      </p>
      <p>
        Gate 7 · {{ operation.kind }} · <code>{{ operation.id }}</code>
      </p>
      <details>
        <summary>{{ copy.details }}</summary>
        <pre class="max-h-80 overflow-auto text-xs whitespace-pre-wrap">{{
          JSON.stringify(operation.payload, null, 2)
        }}</pre>
      </details>
      <div class="flex flex-wrap gap-3">
        <button
          class="rounded border p-2 disabled:opacity-50"
          :disabled="pending || !active || operation.gate.status !== 'PENDING_APPROVAL'"
          @click="decide('APPROVE')"
        >
          {{ copy.approve }}
        </button>
        <button
          class="rounded border p-2 disabled:opacity-50"
          :disabled="
            pending ||
            !operation.gate_current ||
            operation.state !== 'PENDING' ||
            !['PENDING_APPROVAL', 'APPROVED'].includes(operation.gate.status)
          "
          @click="decide('CANCEL')"
        >
          {{ copy.cancel }}
        </button>
        <button
          v-if="operation.kind === 'EXECUTION'"
          class="rounded bg-slate-900 p-2 text-white disabled:opacity-50"
          :disabled="pending || !active || operation.gate.status !== 'APPROVED'"
          @click="start"
        >
          {{ copy.start }}
        </button>
        <button
          v-else-if="operation.kind === 'REPAIR'"
          class="rounded bg-slate-900 p-2 text-white disabled:opacity-50"
          :disabled="pending || !active || operation.gate.status !== 'APPROVED'"
          @click="applyRepair"
        >
          {{ copy.applyRepair }}
        </button>
      </div>
    </template>
    <p v-if="pending" role="status">{{ copy.running }}</p>
    <p v-if="result" role="status">{{ copy.saved }}: {{ result }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
