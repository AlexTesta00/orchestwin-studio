<script setup lang="ts">
import { computed, nextTick, provide, reactive, ref, watch } from "vue";
import UiButton from "./UiButton.vue";
import ResearchEvidenceCitation from "./ResearchEvidenceCitation.vue";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import { researchEvidenceCopy } from "./researchEvidenceCopy";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import {
  researchEvidenceApi,
  ResearchEvidenceApiError,
  type ResearchEvidenceApi,
} from "../api/researchEvidence";
import { twinLearningApi, type TwinLearningApi } from "../api/twinLearning";
import type { GenerationJobsApi } from "../api/generationJobs";
import { useGenerationResume, type GenerationSettlement } from "../stores/generationJobs";
import { useTwinLearningStore, type AuthorizedRequest } from "../stores/twinLearning";
import type {
  ApprovedEvidenceCitationPayload,
  ResearchEvidenceInput,
  ResearchEvidencePayload,
} from "../types/researchEvidence";
import type { TwinUpdatePayload } from "../types/twinLearning";
import type { EvidenceFocus } from "../types/humanValidation";
import type { EvidenceSourceKind } from "../types/userModeling";

const props = withDefaults(
  defineProps<{
    projectId: string;
    authorize: AuthorizedRequest;
    twins: readonly { id: string; name: string }[];
    ready?: boolean;
    active?: boolean;
    locale?: "en" | "it";
    api?: ResearchEvidenceApi | undefined;
    learningApi?: TwinLearningApi | undefined;
    generationApi?: GenerationJobsApi | undefined;
    focusSource?: EvidenceFocus | null;
  }>(),
  {
    ready: false,
    active: true,
    locale: "en",
    api: undefined,
    learningApi: undefined,
    generationApi: undefined,
    focusSource: null,
  },
);
const emit = defineEmits<{ changed: [] }>();
provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);
const copy = computed(() => researchEvidenceCopy[props.locale]);
const sources = ref<ResearchEvidencePayload[]>([]);
const latestVersions = computed(() => {
  const versions = new Map<string, number>();
  for (const source of sources.value)
    versions.set(source.id, Math.max(versions.get(source.id) ?? 0, source.version));
  return versions;
});
const citations = ref<ApprovedEvidenceCitationPayload[]>([]);
const busy = ref(false);
const loading = ref(false);
const failure = ref<string | null>(null);
const notice = ref<string | null>(null);
const editor = ref(false);
const revisionId = ref<string | null>(null);
const acknowledged = ref(false);
const selectedTwin = ref("");
const proposal = ref<TwinUpdatePayload | null>(null);
const kept = reactive<Record<number, boolean>>({});
const statements = reactive<Record<number, string>>({});
const originalTexts = reactive<Record<string, string>>({});
const retireTarget = ref<ResearchEvidencePayload | null>(null);
const retireReason = ref("");
const deleteTarget = ref<ResearchEvidencePayload | null>(null);
const root = ref<HTMLElement | null>(null);
const deletionAcknowledged = ref(false);
const form = reactive({
  title: "",
  source_kind: "OWNER_INPUT" as EvidenceSourceKind,
  source_ref: "",
  context: "",
  method: "",
  collected_at: "",
  limitations: "",
  empirical: false,
  text: "",
});
let epoch = 0;
let editorSequence = 0;
let loaded = false;
const api = computed(() => props.api ?? researchEvidenceApi);
const learningStore = useTwinLearningStore();
const sourceKinds: EvidenceSourceKind[] = [
  "OWNER_INPUT",
  "EMPIRICAL_RESEARCH",
  "HUMAN_REVIEW",
  "PROJECT_BRIEF",
  "SYSTEM_ARTIFACT",
  "MODEL_OUTPUT",
];
const fields = ["title", "source_ref", "context", "method", "collected_at", "limitations"] as const;
const labels = computed(() => ({
  title: copy.value.titleLabel,
  source_ref: copy.value.sourceRef,
  context: copy.value.context,
  method: copy.value.method,
  collected_at: copy.value.date,
  limitations: copy.value.limitations,
}));
const canDecide = computed(() => proposal.value?.status === "PROPOSED");
const hasKept = computed(() => {
  const selected =
    proposal.value?.observations.filter((observation) => kept[observation.index]) ?? [];
  return (
    selected.length > 0 &&
    selected.every((observation) => (statements[observation.index]?.trim().length ?? 0) > 0)
  );
});
const generating = ref(false);
const {
  job: generationJob,
  failure: generationFailure,
  dismiss: dismissGeneration,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["TWIN_UPDATE"],
  authorize: (operation) => props.authorize(operation),
  api: props.generationApi,
  onSettled: settled,
});

async function settled(settlement: GenerationSettlement): Promise<void> {
  if (settlement.kind === "finished") {
    const body = settlement.job.response?.body;
    if (typeof body === "object" && body !== null && "update" in body) {
      const update = body.update;
      if (
        typeof update === "object" &&
        update !== null &&
        "evidence" in update &&
        "observations" in update &&
        Array.isArray(update.observations)
      )
        resetReview(update as TwinUpdatePayload);
    }
  }
  await load();
}

function key(source: ResearchEvidencePayload): string {
  return `${source.id}:${source.version}`;
}

function report(error: unknown): string {
  const code = error instanceof ResearchEvidenceApiError ? error.code : null;
  if (code === "EVIDENCE_LIMIT") return copy.value.limitError;
  if (code === "EVIDENCE_INVALID_TEXT") return copy.value.invalidFile;
  if (code === "EVIDENCE_TEXT_UNAVAILABLE") return copy.value.unavailable;
  if (
    code === "EVIDENCE_CONTEXT_CHANGED" ||
    code === "EVIDENCE_RETIRED" ||
    code === "TWIN_UPDATE_CONTEXT_CHANGED"
  )
    return copy.value.stale;
  return copy.value.failed;
}

function resetReview(update: TwinUpdatePayload | null): void {
  proposal.value = update;
  for (const item of Object.keys(kept)) delete kept[Number(item)];
  for (const item of Object.keys(statements)) delete statements[Number(item)];
  for (const observation of update?.observations ?? []) {
    kept[observation.index] = true;
    statements[observation.index] = observation.statement;
  }
}

async function load(refreshLearning = false): Promise<void> {
  const project = props.projectId;
  const current = epoch;
  loading.value = true;
  failure.value = null;
  try {
    const result = await props.authorize((token) => api.value.list(project, token));
    if (epoch !== current) return;
    sources.value = result.evidence;
    citations.value = result.citations ?? [];
    loaded = true;
    if (!props.ready || sources.value.length === 0) {
      if (proposal.value?.status === "PROPOSED") resetReview(null);
      return;
    }
    const learning = await learningStore[refreshLearning ? "reload" : "load"](
      project,
      props.authorize,
      props.learningApi ?? twinLearningApi,
    );
    if (epoch !== current) return;
    const pending =
      learning?.twins
        .map((twin) => twin.pending_update)
        .find((update) => update?.evidence !== undefined) ?? null;
    if (pending !== null || proposal.value?.status === "PROPOSED") resetReview(pending);
  } catch (error) {
    if (epoch === current) failure.value = report(error);
  } finally {
    if (epoch === current) loading.value = false;
  }
}

async function act(operation: (project: string) => Promise<void>): Promise<void> {
  if (busy.value) return;
  const current = epoch;
  busy.value = true;
  failure.value = null;
  notice.value = null;
  try {
    await operation(props.projectId);
  } catch (error) {
    if (epoch === current) failure.value = report(error);
  } finally {
    if (epoch === current) {
      busy.value = false;
      generating.value = false;
    }
  }
}

function edit(source: ResearchEvidencePayload | null): void {
  editorSequence += 1;
  revisionId.value = source?.id ?? null;
  acknowledged.value = false;
  Object.assign(form, {
    title: source?.title ?? "",
    source_kind: source?.source_kind ?? "OWNER_INPUT",
    source_ref: source?.source_ref ?? "",
    context: source?.context ?? "",
    method: source?.method ?? "",
    collected_at: source?.collected_at ?? "",
    limitations: source?.limitations ?? "",
    empirical: source?.empirical ?? false,
    text: "",
  });
  failure.value = null;
  editor.value = true;
}

function validText(text: string): boolean {
  const normalized = text.replace(/\r\n?/g, "\n");
  if (
    Array.from(normalized).length > 24000 ||
    new TextEncoder().encode(normalized).byteLength > 32768
  ) {
    failure.value = copy.value.limitError;
    return false;
  }
  if (normalized.length === 0 || normalized.includes("\0")) {
    failure.value = copy.value.invalidFile;
    return false;
  }
  return true;
}

async function readFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file === undefined) return;
  failure.value = null;
  const current = epoch;
  const editing = editorSequence;
  form.text = "";
  if (!/\.(txt|md)$/i.test(file.name)) {
    failure.value = copy.value.invalidFile;
    input.value = "";
    return;
  }
  if (file.size > 65536) {
    failure.value = copy.value.limitError;
    input.value = "";
    return;
  }
  try {
    const text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
      await file.arrayBuffer(),
    );
    if (current === epoch && editing === editorSequence && editor.value && validText(text))
      form.text = text;
  } catch {
    if (current === epoch) failure.value = copy.value.invalidFile;
  }
  input.value = "";
}

async function save(): Promise<void> {
  if (!acknowledged.value || !validText(form.text)) return;
  if (fields.some((field) => field !== "collected_at" && form[field].trim().length === 0)) {
    failure.value = copy.value.missingFields;
    return;
  }
  const input: ResearchEvidenceInput = {
    ...form,
    collected_at: form.collected_at.trim() || null,
    empirical: form.source_kind === "EMPIRICAL_RESEARCH" && form.empirical,
    acknowledged: true,
  };
  const current = epoch;
  const id = revisionId.value;
  await act(async (project) => {
    await props.authorize((token) =>
      id === null
        ? api.value.add(project, input, token)
        : api.value.revise(project, id, input, token),
    );
    if (epoch !== current) return;
    editor.value = false;
    form.text = "";
    acknowledged.value = false;
    notice.value = id === null ? copy.value.saved : copy.value.revised;
    await load(true);
  });
}

async function original(source: ResearchEvidencePayload): Promise<void> {
  const sourceKey = key(source);
  if (originalTexts[sourceKey] !== undefined) {
    delete originalTexts[sourceKey];
    return;
  }
  const current = epoch;
  await act(async (project) => {
    const result = await props.authorize((token) =>
      api.value.show(project, source.id, source.version, true, token),
    );
    if (epoch !== current) return;
    if (result.text === undefined) failure.value = copy.value.unavailable;
    else originalTexts[sourceKey] = result.text;
  });
}

async function propose(source: ResearchEvidencePayload): Promise<void> {
  if (!props.ready || selectedTwin.value.length === 0) return;
  const current = epoch;
  await act(async (project) => {
    generating.value = true;
    const result = await props.authorize((token) =>
      api.value.propose(
        project,
        selectedTwin.value,
        source,
        props.locale === "it" ? "it-IT" : "en-GB",
        token,
      ),
    );
    if (epoch !== current) return;
    resetReview(result.update);
  });
}

async function decide(approval: boolean): Promise<void> {
  const update = proposal.value;
  if (update === null || !canDecide.value || (approval && !hasKept.value)) return;
  const selected = approval
    ? update.observations
        .filter((observation) => kept[observation.index])
        .map((observation) => ({
          index: observation.index,
          ...(statements[observation.index] === observation.statement
            ? {}
            : { statement: statements[observation.index]?.trim() ?? "" }),
        }))
    : [];
  const current = epoch;
  await act(async (project) => {
    const result = await props.authorize((token) =>
      api.value.decide(
        project,
        update.id,
        { decision: approval ? "APPROVE" : "REJECT", kept: selected },
        token,
      ),
    );
    if (epoch !== current) return;
    resetReview(result.update);
    notice.value = approval ? copy.value.approved : copy.value.discarded;
    emit("changed");
    await load(true);
  });
}

async function retire(): Promise<void> {
  const source = retireTarget.value;
  if (source === null || retireReason.value.trim().length === 0) return;
  const current = epoch;
  await act(async (project) => {
    const result = await props.authorize((token) =>
      api.value.retire(project, source.id, retireReason.value.trim(), token),
    );
    if (epoch !== current) return;
    retireTarget.value = null;
    notice.value =
      result.review_required === true ? copy.value.retiredReview : copy.value.retiredDone;
    emit("changed");
    await load(true);
  });
}

async function deleteText(): Promise<void> {
  const source = deleteTarget.value;
  if (source === null || !deletionAcknowledged.value) return;
  const current = epoch;
  await act(async (project) => {
    await props.authorize((token) => api.value.deleteText(project, source.id, token));
    if (epoch !== current) return;
    for (const item of sources.value.filter((item) => item.id === source.id))
      delete originalTexts[key(item)];
    deleteTarget.value = null;
    notice.value = copy.value.deletedDone;
    emit("changed");
    await load();
  });
}

function sourceForUpdate(update: TwinUpdatePayload): ResearchEvidencePayload | undefined {
  return sources.value.find(
    (source) =>
      source.id === update.evidence?.source_id && source.version === update.evidence.source_version,
  );
}

function approvedQuotes(source: ResearchEvidencePayload): ApprovedEvidenceCitationPayload[] {
  return citations.value.filter(
    (item) =>
      item.citation.source_id === source.id && item.citation.source_version === source.version,
  );
}

watch(
  () => props.projectId,
  () => {
    epoch += 1;
    editorSequence += 1;
    loaded = false;
    sources.value = [];
    citations.value = [];
    proposal.value = null;
    failure.value = null;
    notice.value = null;
    busy.value = false;
    loading.value = false;
    generating.value = false;
    editor.value = false;
    form.text = "";
    retireTarget.value = null;
    deleteTarget.value = null;
    for (const item of Object.keys(originalTexts)) delete originalTexts[item];
    void load();
  },
  { immediate: true },
);
watch(
  () => props.active,
  (active) => {
    if (active && !loaded && !loading.value) void load();
  },
);
watch(
  () => props.twins,
  (twins) => {
    if (!twins.some((twin) => twin.id === selectedTwin.value))
      selectedTwin.value = twins[0]?.id ?? "";
  },
  { immediate: true },
);
watch(
  () => form.source_kind,
  () => {
    form.empirical = false;
  },
);
watch(
  () => [props.focusSource, props.active, sources.value] as const,
  async () => {
    if (!props.focusSource || !props.active) return;
    await nextTick();
    const target = [
      ...(root.value?.querySelectorAll<HTMLElement>('[data-testid="evidence-source"]') ?? []),
    ].find(
      (element) =>
        element.dataset.sourceKey === `${props.focusSource?.id}:${props.focusSource?.version}`,
    );
    if (!target) return;
    const details = target.querySelector<HTMLDetailsElement>("details");
    if (details) details.open = true;
    target.focus({ preventScroll: true });
    target.scrollIntoView?.({ behavior: "smooth", block: "start" });
  },
);
</script>

<template>
  <section
    ref="root"
    class="mt-7 grid gap-4 rounded-panel border border-night-line bg-night-raised p-5 text-on-night sm:p-7"
    aria-labelledby="research-evidence-title"
    data-testid="research-evidence-panel"
    :aria-busy="busy || loading"
  >
    <div class="flex flex-col items-start justify-between gap-3 sm:flex-row">
      <div class="w-full min-w-0 flex-1 sm:w-auto">
        <h2 id="research-evidence-title" class="m-0 text-[22px] leading-tight font-semibold">
          {{ copy.title }}
        </h2>
        <p class="m-0 mt-2 text-sm leading-normal text-on-night-2">{{ copy.intro }}</p>
      </div>
      <UiButton
        class="self-start"
        variant="outline"
        :disabled="busy"
        data-testid="evidence-add"
        @click="edit(null)"
        >{{ copy.add }}</UiButton
      >
    </div>
    <p
      v-if="failure !== null"
      role="alert"
      class="m-0 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 p-3 text-sm text-fail-on-night"
      data-testid="evidence-error"
    >
      {{ failure }}
    </p>
    <p
      v-if="notice !== null"
      role="status"
      class="m-0 text-sm text-petrol-on-night-2"
      data-testid="evidence-notice"
    >
      {{ notice }}
    </p>
    <form
      v-if="editor"
      class="grid gap-3 rounded-field border border-night-line bg-night-panel p-4"
      data-testid="evidence-form"
      @submit.prevent="save"
    >
      <p
        class="m-0 text-sm leading-normal text-warn-on-night"
        data-testid="evidence-privacy-warning"
      >
        {{ copy.warning }}
      </p>
      <label class="flex min-h-11 items-center gap-3 text-sm"
        ><input
          v-model="acknowledged"
          type="checkbox"
          class="size-4 accent-petrol-on-night"
          data-testid="evidence-acknowledge"
        />{{ copy.acknowledge }}</label
      >
      <template v-if="acknowledged">
        <label v-for="field in fields" :key="field" class="grid gap-1.5 text-sm text-on-night-2"
          >{{ labels[field]
          }}<input
            v-model="form[field]"
            :required="field !== 'collected_at'"
            :data-testid="`evidence-${field}`"
            class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-on-night"
        /></label>
        <label class="grid gap-1.5 text-sm text-on-night-2"
          >{{ copy.sourceKind
          }}<select
            v-model="form.source_kind"
            class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-on-night"
            data-testid="evidence-kind"
          >
            <option v-for="kind in sourceKinds" :key="kind" :value="kind">
              {{ copy.kinds[kind] }}
            </option>
          </select></label
        >
        <label
          v-if="form.source_kind === 'EMPIRICAL_RESEARCH'"
          class="flex min-h-11 items-center gap-3 text-sm text-warn-on-night"
          ><input
            v-model="form.empirical"
            type="checkbox"
            required
            class="size-4 accent-petrol-on-night"
            data-testid="evidence-empirical"
          />{{ copy.empirical }}</label
        >
        <label class="grid gap-1.5 text-sm text-on-night-2"
          >{{ copy.text
          }}<textarea
            v-model="form.text"
            required
            rows="7"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2 text-on-night"
            data-testid="evidence-text"
          />
        </label>
        <label class="grid gap-1.5 text-sm text-on-night-2"
          >{{ copy.file
          }}<input
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            class="min-h-11 py-2 text-sm"
            data-testid="evidence-file"
            @change="readFile"
        /></label>
        <p class="m-0 text-xs text-on-night-3">{{ copy.limit }}</p>
      </template>
      <div class="flex flex-wrap gap-2">
        <UiButton
          type="submit"
          :disabled="
            busy || !acknowledged || (form.source_kind === 'EMPIRICAL_RESEARCH' && !form.empirical)
          "
          data-testid="evidence-save"
          >{{ copy.save }}</UiButton
        ><UiButton
          variant="quiet"
          :disabled="busy"
          @click="
            editor = false;
            form.text = '';
          "
          >{{ copy.cancel }}</UiButton
        >
      </div>
    </form>
    <p v-if="!props.ready" class="m-0 text-sm text-on-night-3">{{ copy.prerequisite }}</p>
    <label v-if="twins.length > 0" class="grid gap-1.5 text-sm text-on-night-2"
      >{{ copy.selectTwin
      }}<select
        v-model="selectedTwin"
        :disabled="busy"
        class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2 text-on-night"
        data-testid="evidence-twin"
      >
        <option v-for="twin in twins" :key="twin.id" :value="twin.id">{{ twin.name }}</option>
      </select></label
    >
    <p v-if="sources.length === 0 && !loading" class="m-0 text-sm text-on-night-3">
      {{ copy.empty }}
    </p>
    <article
      v-for="source in sources"
      :key="key(source)"
      class="grid gap-3 rounded-field border border-night-line bg-night-panel p-4"
      data-testid="evidence-source"
      :data-source-key="key(source)"
      tabindex="-1"
    >
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 class="m-0 text-base font-semibold wrap-anywhere">{{ source.title }}</h3>
        <span class="text-xs text-on-night-3"
          >{{ copy.version }} {{ source.version }} ·
          {{ source.version === latestVersions.get(source.id) ? copy.latest : copy.earlier }} ·
          {{ source.status === "ACTIVE" ? copy.active : copy.retired }}</span
        >
      </div>
      <p class="m-0 text-xs text-on-night-3">
        {{ source.empirical ? copy.empiricalSource : copy.nonEmpirical }}
      </p>
      <p v-if="!source.text_available" class="m-0 text-xs text-on-night-3">
        {{ copy.unavailable }}
      </p>
      <details class="text-sm">
        <summary class="min-h-11 cursor-pointer py-3 font-medium text-on-night-2">
          {{ copy.details }}
        </summary>
        <dl class="m-0 grid gap-3 text-sm text-on-night-2">
          <div v-for="field in fields.filter((field) => field !== 'title')" :key="field">
            <dt class="font-semibold">{{ labels[field] }}</dt>
            <dd class="m-0 mt-1 wrap-anywhere whitespace-pre-wrap">{{ source[field] }}</dd>
          </div>
          <div>
            <dt class="font-semibold">{{ copy.sourceKind }}</dt>
            <dd class="m-0">{{ copy.kinds[source.source_kind] }}</dd>
          </div>
          <div>
            <dt class="font-semibold">{{ copy.hash }}</dt>
            <dd class="m-0 font-mono text-xs break-all">{{ source.content_hash }}</dd>
          </div>
          <div>
            <dt class="font-semibold">{{ copy.sourceRef }}</dt>
            <dd class="m-0">
              {{ source.code }} · {{ source.character_count }} {{ copy.chars }} ·
              {{ source.byte_count }} B
            </dd>
          </div>
        </dl>
        <div
          v-for="(item, index) in approvedQuotes(source)"
          :key="`${item.twin_id}:${item.twin_version}:${item.field}:${index}`"
          class="mt-3 grid gap-2"
          data-testid="evidence-approved-citation"
        >
          <p class="m-0 text-xs text-on-night-3">
            {{ twins.find((twin) => twin.id === item.twin_id)?.name ?? item.twin_id }} ·
            {{ copy.version }} {{ item.twin_version }} · {{ copy.effects[item.effect] }} ·
            {{ item.status === "ACTIVE" ? copy.active : copy.retired }}
          </p>
          <ResearchEvidenceCitation :citation="item.citation" :locale="locale" />
        </div>
      </details>
      <pre
        v-if="originalTexts[key(source)] !== undefined"
        class="m-0 max-h-80 overflow-auto rounded-field border border-night-line p-3 font-mono text-xs wrap-anywhere whitespace-pre-wrap"
        data-testid="evidence-original"
        >{{ originalTexts[key(source)] }}</pre>
      <div class="flex flex-wrap gap-2">
        <UiButton
          v-if="source.text_available"
          variant="quiet"
          :disabled="busy"
          data-testid="evidence-read-original"
          @click="original(source)"
          >{{
            originalTexts[key(source)] === undefined ? copy.original : copy.hideOriginal
          }}</UiButton
        >
        <UiButton
          v-if="source.status === 'ACTIVE' && source.text_available"
          variant="outline"
          :disabled="
            busy || generationJob !== null || !ready || selectedTwin.length === 0 || canDecide
          "
          data-testid="evidence-propose"
          @click="propose(source)"
          >{{ copy.propose }}</UiButton
        >
        <UiButton
          v-if="source.status === 'ACTIVE'"
          variant="quiet"
          :disabled="busy"
          data-testid="evidence-revise"
          @click="edit(source)"
          >{{ copy.revise }}</UiButton
        >
        <UiButton
          v-if="source.status === 'ACTIVE'"
          variant="quiet"
          :disabled="busy"
          data-testid="evidence-retire"
          @click="
            retireTarget = source;
            retireReason = '';
          "
          >{{ copy.retire }}</UiButton
        >
        <UiButton
          v-if="source.status === 'RETIRED' && source.text_available"
          variant="danger"
          :disabled="busy"
          data-testid="evidence-delete-text"
          @click="
            deleteTarget = source;
            deletionAcknowledged = false;
          "
          >{{ copy.deleteText }}</UiButton
        >
      </div>
    </article>
    <p
      v-if="generating && generationJob === null"
      role="status"
      class="m-0 text-sm text-on-night-2"
      data-testid="evidence-generating"
    >
      {{ copy.generating }}
    </p>
    <GenerationJobNotice
      :job="generationJob"
      :failure="generationFailure"
      :locale="locale"
      @dismiss="dismissGeneration"
    />
    <section
      v-if="proposal !== null"
      class="grid gap-3 rounded-field border border-violet-on-night/60 bg-violet-on-night/6 p-4"
      data-testid="evidence-review"
    >
      <h3 class="m-0 text-base font-semibold">{{ copy.reviewing }} · {{ proposal.twin_name }}</h3>
      <p class="m-0 text-sm leading-normal">{{ proposal.comment }}</p>
      <p
        v-if="proposal.evidence !== undefined"
        class="m-0 text-sm text-warn-on-night"
        data-testid="evidence-rejected-count"
      >
        {{ copy.rejected.replace("{count}", String(proposal.evidence.rejected_changes)) }}
      </p>
      <p
        v-if="proposal.status === 'EMPTY'"
        class="m-0 text-sm text-on-night-2"
        data-testid="evidence-empty-proposal"
      >
        {{ copy.noChanges }}
      </p>
      <p v-if="sourceForUpdate(proposal) !== undefined" class="m-0 text-sm text-on-night-3">
        {{ sourceForUpdate(proposal)?.title }} · {{ copy.version }}
        {{ proposal.evidence?.source_version }}
      </p>
      <article
        v-for="observation in proposal.observations"
        :key="observation.index"
        class="grid gap-2 rounded-field border border-night-line p-3"
        data-testid="evidence-change"
      >
        <p
          v-if="observation.evidence !== undefined"
          class="m-0 text-xs font-semibold text-on-night-2"
        >
          {{ copy.effects[observation.evidence.effect] }}
        </p>
        <label v-if="canDecide" class="flex min-h-11 items-center gap-3 text-sm"
          ><input
            v-model="kept[observation.index]"
            type="checkbox"
            class="size-4 accent-petrol-on-night"
            data-testid="evidence-keep"
          />{{ copy.keep }}</label
        >
        <label v-if="canDecide" class="grid gap-1.5 text-sm text-on-night-2"
          >{{ observation.evidence?.effect === "ADDS" ? copy.correctAddition : copy.correct
          }}<textarea
            v-model="statements[observation.index]"
            rows="2"
            maxlength="400"
            :disabled="busy"
            class="rounded-field border border-night-line-strong bg-night-panel px-3 py-2 text-on-night"
            data-testid="evidence-correct"
          />
        </label>
        <p v-else class="m-0 text-sm">{{ observation.statement }}</p>
        <details class="text-sm">
          <summary class="min-h-11 cursor-pointer py-3 text-on-night-2">{{ copy.basis }}</summary>
          <p class="m-0 text-sm text-on-night-2">{{ observation.basis }}</p>
          <ResearchEvidenceCitation
            v-if="observation.evidence !== undefined"
            :citation="observation.evidence.citation"
            :locale="locale"
            class="mt-2"
          />
        </details>
      </article>
      <template v-if="canDecide"
        ><p class="m-0 text-sm text-warn-on-night">{{ copy.decisionWarning }}</p>
        <div class="flex flex-wrap gap-2">
          <UiButton
            :disabled="busy || !hasKept"
            data-testid="evidence-approve"
            @click="decide(true)"
            >{{ copy.approve }}</UiButton
          ><UiButton
            variant="outline"
            :disabled="busy"
            data-testid="evidence-discard"
            @click="decide(false)"
            >{{ copy.discard }}</UiButton
          >
        </div></template
      >
    </section>
    <form
      v-if="retireTarget !== null"
      class="grid gap-3 rounded-field border border-warn-on-night/40 p-4"
      data-testid="evidence-retire-form"
      @submit.prevent="retire"
    >
      <p class="m-0 text-sm leading-normal text-warn-on-night">{{ copy.retireWarning }}</p>
      <label class="grid gap-1.5 text-sm text-on-night-2"
        >{{ copy.reason
        }}<textarea
          v-model="retireReason"
          required
          rows="2"
          class="rounded-field border border-night-line-strong bg-night-panel px-3 py-2 text-on-night"
          data-testid="evidence-retire-reason"
        />
      </label>
      <div class="flex flex-wrap gap-2">
        <UiButton
          type="submit"
          :disabled="busy || retireReason.trim().length === 0"
          data-testid="evidence-retire-confirm"
          >{{ copy.retire }}</UiButton
        ><UiButton variant="quiet" :disabled="busy" @click="retireTarget = null">{{
          copy.cancel
        }}</UiButton>
      </div>
    </form>
    <form
      v-if="deleteTarget !== null"
      class="grid gap-3 rounded-field border border-fail-on-night/40 p-4"
      data-testid="evidence-delete-form"
      @submit.prevent="deleteText"
    >
      <p class="m-0 text-sm leading-normal text-warn-on-night">{{ copy.deleteWarning }}</p>
      <label class="flex min-h-11 items-center gap-3 text-sm"
        ><input
          v-model="deletionAcknowledged"
          type="checkbox"
          class="size-4 accent-petrol-on-night"
          data-testid="evidence-delete-acknowledge"
        />{{ copy.deleteAcknowledge }}</label
      >
      <div class="flex flex-wrap gap-2">
        <UiButton
          type="submit"
          variant="danger"
          :disabled="busy || !deletionAcknowledged"
          data-testid="evidence-delete-confirm"
          >{{ copy.deleteText }}</UiButton
        ><UiButton variant="quiet" :disabled="busy" @click="deleteTarget = null">{{
          copy.cancel
        }}</UiButton>
      </div>
    </form>
    <UiButton
      variant="quiet"
      class="justify-self-start"
      :disabled="busy || loading"
      @click="load(true)"
      >{{ copy.refresh }}</UiButton
    >
  </section>
</template>
