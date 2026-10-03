<script setup lang="ts">
import { computed, provide, reactive, ref, useId, watch } from "vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import ArtifactWhyNode from "./ArtifactWhyNode.vue";
import UiButton from "./UiButton.vue";
import ValidationOutcomeCard from "./ValidationOutcomeCard.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { humanValidationCopy } from "./humanValidationCopy";
import { whyGapLabel, whyNodeTitle } from "./whyCopy";
import {
  humanValidationApi,
  HumanValidationApiError,
  type HumanValidationApi,
} from "../api/humanValidation";
import { whyApi as defaultWhyApi, type WhyApi } from "../api/why";
import { researchEvidenceApi, type ResearchEvidenceApi } from "../api/researchEvidence";
import type { AuthorizedRequest } from "../stores/twinLearning";
import type {
  EvidenceFocus,
  HumanValidationOverview,
  HypothesisInput,
  OperationalHypothesis,
  ValidationCandidate,
  ValidationCoverage,
  ValidationOutcomeValue,
  ValidationSessionKind,
} from "../types/humanValidation";
import type { ResearchEvidencePayload } from "../types/researchEvidence";
import type { WhyDocument } from "../types/why";

const props = withDefaults(
  defineProps<{
    projectId: string;
    authorize: AuthorizedRequest;
    locale?: "it" | "en";
    active?: boolean;
    refreshKey?: string;
    api?: HumanValidationApi | undefined;
    whyApi?: WhyApi | undefined;
    evidenceApi?: ResearchEvidenceApi | undefined;
  }>(),
  {
    locale: "en",
    active: true,
    refreshKey: "",
    api: undefined,
    whyApi: undefined,
    evidenceApi: undefined,
  },
);
const emit = defineEmits<{ "open-evidence": [source: EvidenceFocus | null] }>();
provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);
const prefix = `validation-${useId()}`;
const copy = computed(() => humanValidationCopy[props.locale]);
const overview = ref<HumanValidationOverview | null>(null);
const document = ref<WhyDocument | null>(null);
const sources = ref<ResearchEvidencePayload[]>([]);
const loading = ref(false);
const busy = ref(false);
const failure = ref<string | null>(null);
const notice = ref<string | null>(null);
const candidatesShown = ref(false);
const allCandidates = ref(false);
const selected = ref<ValidationCandidate | null>(null);
const revision = ref<OperationalHypothesis | null>(null);
const outcomeTarget = ref<OperationalHypothesis | null>(null);
const originalText = ref<string | null>(null);
const form = reactive({
  twin_key: "",
  scenario_key: "",
  design_key: "",
  alternative_id: "",
  anchor_keys: [] as string[],
  question: "",
  task: "",
  observe: "",
  limitations: "",
});
const outcomeForm = reactive({
  session_ref: "",
  session_kind: "HUMAN_SESSION" as ValidationSessionKind,
  outcome: "UNCERTAIN" as ValidationOutcomeValue,
  coverage: "PARTIAL" as ValidationCoverage,
  source_key: "",
  quote: "",
  line: 1,
  limitations: "",
});
let epoch = 0;
let sourcesRequest = 0;
let loadedContext = "";
const api = computed(() => props.api ?? humanValidationApi);
const why = computed(() => props.whyApi ?? defaultWhyApi);
const evidence = computed(() => props.evidenceApi ?? researchEvidenceApi);
const currentNodes = computed(() => document.value?.nodes.filter((node) => node.current) ?? []);
const nodes = computed(() => new Map(document.value?.nodes.map((node) => [node.key, node]) ?? []));
const currentHypotheses = computed(
  () => overview.value?.hypotheses.filter((item) => item.current) ?? [],
);
const previousHypotheses = computed(
  () => overview.value?.hypotheses.filter((item) => !item.current) ?? [],
);
const visibleCandidates = computed(() =>
  allCandidates.value
    ? (overview.value?.candidates ?? [])
    : (overview.value?.candidates.slice(0, 3) ?? []),
);
const scenarioOptions = computed(() =>
  currentNodes.value.filter(
    (node) =>
      node.kind === "SCENARIO" &&
      document.value?.links.some(
        (link) =>
          link.source === node.key && link.target === form.twin_key && link.kind === "ACTOR",
      ),
  ),
);
const designOptions = computed(() =>
  currentNodes.value.filter(
    (node) => node.kind === "DESIGN_PACKAGE" || node.kind === "DESIGN_ALTERNATIVE",
  ),
);
const alternatives = computed(() =>
  currentNodes.value.filter(
    (node) =>
      node.kind === "DESIGN_ALTERNATIVE" &&
      node.reference.content_hash === nodes.value.get(form.design_key)?.reference.content_hash,
  ),
);
const anchorOptions = computed(() =>
  currentNodes.value.filter(
    (node) =>
      node.kind === "PROTOTYPE_ELEMENT" &&
      (!form.alternative_id ||
        node.declared_context.mockup?.alternative_id === form.alternative_id) &&
      (node.declared_context.base_reference?.content_hash ?? node.reference.content_hash) ===
        nodes.value.get(form.design_key)?.reference.content_hash,
  ),
);
const availableSources = computed(() => {
  const latest = new Map<string, number>();
  for (const source of sources.value)
    latest.set(source.id, Math.max(latest.get(source.id) ?? 0, source.version));
  return sources.value.filter(
    (source) =>
      source.status === "ACTIVE" &&
      source.text_available &&
      source.version === latest.get(source.id) &&
      (outcomeForm.session_kind === "HUMAN_SESSION"
        ? source.source_kind === "EMPIRICAL_RESEARCH" && source.empirical
        : !source.empirical),
  );
});
const selectedSource = computed(() =>
  availableSources.value.find((source) => sourceKey(source) === outcomeForm.source_key),
);
const formValid = computed(
  () =>
    !!selected.value &&
    selected.value.twin_references.some((node) => node.key === form.twin_key && node.current) &&
    scenarioOptions.value.some((node) => node.key === form.scenario_key) &&
    designOptions.value.some((node) => node.key === form.design_key) &&
    !!(form.question.trim() || form.task.trim()) &&
    !!form.observe.trim() &&
    form.observe.split(/\r?\n/).filter((value) => value.trim()).length <= 24 &&
    form.observe.split(/\r?\n/).every((value) => value.trim().length <= 500) &&
    !!form.limitations.trim(),
);
const outcomeValid = computed(
  () =>
    !!outcomeTarget.value &&
    !!selectedSource.value &&
    /^(?:SES|SESSION|SYN|TEST)-[A-Za-z0-9_.:-]{1,70}$/.test(outcomeForm.session_ref) &&
    !!outcomeForm.quote &&
    outcomeForm.quote.length <= 1000 &&
    Number.isInteger(outcomeForm.line) &&
    outcomeForm.line >= 1 &&
    !!outcomeForm.limitations.trim(),
);

function title(key: string): string {
  const node = nodes.value.get(key);
  return node ? whyNodeTitle(node, props.locale) : copy.value.linkMissing;
}
function sourceKey(source: ResearchEvidencePayload): string {
  return `${source.id}:${source.version}`;
}
function gapLabel(code: string): string {
  return copy.value.gaps[code as keyof typeof copy.value.gaps] ?? whyGapLabel(code, props.locale);
}
function state(hypothesis: OperationalHypothesis): string {
  return copy.value.states[hypothesis.state ?? "TO_VERIFY"];
}
function sourceFor(id: string, version: number): ResearchEvidencePayload | undefined {
  return sources.value.find((source) => source.id === id && source.version === version);
}
function report(error: unknown): string {
  const code = error instanceof HumanValidationApiError ? error.code : null;
  if (code === "VALIDATION_CONTEXT_CHANGED" || code === "HYPOTHESIS_VERSION_CONFLICT")
    return copy.value.stale;
  if (code === "VALIDATION_SOURCE_RETIRED") return copy.value.sourceRetired;
  if (code === "VALIDATION_SOURCE_TEXT_UNAVAILABLE") return copy.value.sourceUnavailable;
  if (code === "VALIDATION_CITATION_INVALID") return copy.value.citationInvalid;
  if (code === "VALIDATION_SESSION_SOURCE_INVALID") return copy.value.sourceInvalid;
  if (code === "VALIDATION_INPUT_INVALID")
    return outcomeTarget.value ? copy.value.outcomeInvalid : copy.value.invalid;
  return copy.value.failed;
}

async function loadSources(): Promise<void> {
  const current = epoch;
  const request = ++sourcesRequest;
  const result = await props.authorize((token) => evidence.value.list(props.projectId, token));
  if (current === epoch && request === sourcesRequest) sources.value = result.evidence;
}

async function load(): Promise<void> {
  if (!props.active) return;
  const current = ++epoch;
  const project = props.projectId;
  loading.value = true;
  failure.value = null;
  try {
    const [result, graph] = await Promise.all([
      props.authorize((token) => api.value.overview(project, token)),
      props.authorize((token) => why.value.document(project, token)),
    ]);
    if (current !== epoch) return;
    overview.value = result;
    document.value = graph;
    loadedContext = `${project}:${props.refreshKey}`;
    if (result.outcomes.length > 0 || outcomeTarget.value) await loadSources();
  } catch (error) {
    if (current === epoch) failure.value = report(error);
  } finally {
    if (current === epoch) loading.value = false;
  }
}

function choose(
  candidate: ValidationCandidate,
  hypothesis: OperationalHypothesis | null = null,
): void {
  hypothesis ??= revision.value;
  selected.value = candidate;
  revision.value = hypothesis;
  outcomeTarget.value = null;
  notice.value = null;
  failure.value = null;
  Object.assign(form, {
    twin_key: hypothesis?.twin_key ?? "",
    scenario_key: hypothesis?.scenario_key ?? "",
    design_key: hypothesis?.design_key ?? "",
    alternative_id: hypothesis?.alternative_id ?? "",
    anchor_keys: [...(hypothesis?.anchor_keys ?? [])],
    question: hypothesis?.question ?? "",
    task: hypothesis?.task ?? "",
    observe: hypothesis?.observe.join("\n") ?? "",
    limitations: hypothesis?.limitations ?? "",
  });
}

function revise(hypothesis: OperationalHypothesis): void {
  const candidate = overview.value?.candidates.find(
    (candidate) => candidate.key === hypothesis.origin_key,
  );
  if (candidate) choose(candidate, hypothesis);
  else {
    failure.value = copy.value.stale;
    revision.value = hypothesis;
    selected.value = null;
    candidatesShown.value = true;
  }
}

async function saveHypothesis(): Promise<void> {
  if (busy.value || !formValid.value || !selected.value) return;
  const current = epoch;
  const previous = revision.value;
  const input: HypothesisInput = {
    candidate_key: selected.value.key,
    twin_key: form.twin_key,
    scenario_key: form.scenario_key,
    design_key: form.design_key,
    ...(form.alternative_id ? { alternative_id: form.alternative_id } : {}),
    anchor_keys: [...form.anchor_keys],
    question: form.question.trim() || null,
    task: form.task.trim() || null,
    observe: form.observe
      .split(/\r?\n/)
      .map((value) => value.trim())
      .filter(Boolean),
    limitations: form.limitations.trim(),
  };
  busy.value = true;
  failure.value = null;
  try {
    if (previous) {
      await props.authorize((token) =>
        api.value.reviseHypothesis(
          props.projectId,
          previous.id,
          {
            ...input,
            based_on_version_number: previous.version_number,
            based_on_content_hash: previous.content_hash,
          },
          token,
        ),
      );
    } else {
      await props.authorize((token) => api.value.createHypothesis(props.projectId, input, token));
    }
    if (current !== epoch) return;
    selected.value = null;
    revision.value = null;
    notice.value = previous ? copy.value.revised : copy.value.saved;
    await load();
  } catch (error) {
    if (current === epoch) failure.value = report(error);
  } finally {
    busy.value = false;
  }
}

async function beginOutcome(hypothesis: OperationalHypothesis): Promise<void> {
  outcomeTarget.value = hypothesis;
  selected.value = null;
  revision.value = null;
  originalText.value = null;
  failure.value = null;
  notice.value = null;
  Object.assign(outcomeForm, {
    session_ref: "",
    session_kind: "HUMAN_SESSION",
    outcome: "UNCERTAIN",
    coverage: "PARTIAL",
    source_key: "",
    quote: "",
    line: 1,
    limitations: "",
  });
  try {
    await loadSources();
  } catch (error) {
    failure.value = report(error);
  }
}

async function showOriginal(): Promise<void> {
  const source = selectedSource.value;
  if (!source || busy.value) return;
  const current = epoch;
  const selection = outcomeForm.source_key;
  busy.value = true;
  failure.value = null;
  try {
    const result = await props.authorize((token) =>
      evidence.value.show(props.projectId, source.id, source.version, true, token),
    );
    if (current !== epoch || selection !== outcomeForm.source_key) return;
    originalText.value = result.text ?? null;
    if (originalText.value === null) failure.value = copy.value.sourceUnavailable;
  } catch (error) {
    if (current === epoch) failure.value = report(error);
  } finally {
    busy.value = false;
  }
}

async function saveOutcome(): Promise<void> {
  const hypothesis = outcomeTarget.value;
  const source = selectedSource.value;
  if (busy.value || !outcomeValid.value || !hypothesis || !source) return;
  const current = epoch;
  busy.value = true;
  failure.value = null;
  try {
    await props.authorize((token) =>
      api.value.recordOutcome(
        props.projectId,
        {
          hypothesis_id: hypothesis.id,
          hypothesis_version_number: hypothesis.version_number,
          hypothesis_content_hash: hypothesis.content_hash,
          session_ref: outcomeForm.session_ref,
          session_kind: outcomeForm.session_kind,
          outcome: outcomeForm.outcome,
          coverage: outcomeForm.coverage,
          limitations: outcomeForm.limitations.trim(),
          evidence_id: source.id,
          evidence_version: source.version,
          quote: outcomeForm.quote,
          line: outcomeForm.line,
        },
        token,
      ),
    );
    if (current !== epoch) return;
    outcomeTarget.value = null;
    originalText.value = null;
    outcomeForm.quote = "";
    notice.value = copy.value.recorded;
    await load();
  } catch (error) {
    if (current === epoch) failure.value = report(error);
  } finally {
    busy.value = false;
  }
}

watch(
  () => form.twin_key,
  () => {
    if (!scenarioOptions.value.some((node) => node.key === form.scenario_key))
      form.scenario_key = "";
  },
);
watch(
  () => form.design_key,
  () => {
    const design = nodes.value.get(form.design_key);
    if (design?.kind === "DESIGN_ALTERNATIVE") form.alternative_id = design.reference.artifact_id;
    else if (!alternatives.value.some((node) => node.reference.artifact_id === form.alternative_id))
      form.alternative_id = "";
    form.anchor_keys = form.anchor_keys.filter((key) =>
      anchorOptions.value.some((node) => node.key === key),
    );
  },
);
watch(
  () => form.alternative_id,
  () => {
    form.anchor_keys = form.anchor_keys.filter((key) =>
      anchorOptions.value.some((node) => node.key === key),
    );
  },
);
watch(
  () => outcomeForm.session_kind,
  () => {
    outcomeForm.source_key = "";
  },
);
watch(
  () => outcomeForm.source_key,
  () => {
    originalText.value = null;
    outcomeForm.quote = "";
    outcomeForm.line = 1;
  },
);
watch(
  () => [props.projectId, props.active, props.refreshKey] as const,
  ([project], previous) => {
    const previousProject = previous?.[0];
    if (project !== previousProject) {
      epoch += 1;
      overview.value = null;
      document.value = null;
      sources.value = [];
      selected.value = null;
      revision.value = null;
      outcomeTarget.value = null;
      originalText.value = null;
      notice.value = null;
      candidatesShown.value = false;
      allCandidates.value = false;
    }
    if (props.active && loadedContext !== `${project}:${props.refreshKey}`) void load();
  },
  { immediate: true },
);
</script>

<template>
  <section
    class="grid gap-5 rounded-panel border border-night-line bg-night-raised p-5 text-on-night sm:p-7"
    :aria-labelledby="`${prefix}-title`"
    :aria-busy="busy || loading"
    data-testid="human-validation-panel"
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <h2 :id="`${prefix}-title`" class="m-0 text-[22px] leading-tight font-semibold">
          {{ copy.title }}
        </h2>
        <p class="m-0 mt-2 text-sm text-on-night-2">{{ copy.noPromotion }}</p>
      </div>
      <UiButton
        variant="outline"
        :disabled="busy || loading"
        data-testid="validation-refresh"
        @click="load"
        >{{ copy.refresh }}</UiButton
      >
    </div>
    <p v-if="loading" role="status" class="m-0 text-sm">{{ copy.loading }}</p>
    <p
      v-if="failure"
      role="alert"
      class="m-0 rounded-field border border-fail-on-night/40 p-3 text-sm text-fail-on-night"
      data-testid="validation-error"
    >
      {{ failure }}
    </p>
    <p v-if="notice" role="status" class="m-0 text-sm text-petrol-on-night-2">{{ notice }}</p>
    <template v-if="overview">
      <section class="grid gap-3" data-testid="validation-candidates-summary">
        <h3 class="m-0 text-base font-semibold">
          {{ copy.candidates }} ·
          <span data-testid="validation-candidate-count">{{ overview.candidate_count }}</span>
        </h3>
        <p class="m-0 text-sm text-on-night-2">{{ copy.candidateIntro }}</p>
        <p
          v-if="revision && !selected"
          class="m-0 text-sm text-warn-on-night"
          data-testid="validation-revision-selection"
        >
          {{ copy.chooseForRevision }} · {{ revision.question ?? revision.task }}
        </p>
        <UiButton
          v-if="revision && !selected"
          variant="quiet"
          class="justify-self-start"
          @click="revision = null"
          >{{ copy.cancel }}</UiButton
        >
        <UiButton
          v-if="overview.candidate_count > 0"
          variant="quiet"
          class="justify-self-start"
          :aria-expanded="candidatesShown"
          :aria-controls="`${prefix}-candidates`"
          data-testid="validation-show-candidates"
          @click="candidatesShown = !candidatesShown"
          >{{ candidatesShown ? copy.hide : copy.showCandidates }}</UiButton
        >
        <p v-else class="m-0 text-sm">{{ copy.noCandidates }}</p>
        <div v-if="candidatesShown" :id="`${prefix}-candidates`" class="grid gap-3">
          <article
            v-for="candidate in visibleCandidates"
            :key="candidate.key"
            class="grid min-w-0 gap-2 rounded-field border border-dashed border-violet-on-night/60 p-4"
            data-testid="validation-candidate"
          >
            <h4 class="m-0 text-sm font-semibold [overflow-wrap:anywhere]">
              {{ whyNodeTitle(candidate.origin, locale) }}
            </h4>
            <p class="m-0 text-xs text-violet-on-night-2">
              {{
                candidate.kind === "USER_TWIN_CLAIM" ? copy.states.TO_VERIFY : copy.prevalidation
              }}
            </p>
            <details class="min-w-0 text-sm">
              <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
                {{ copy.details }}
              </summary>
              <div class="grid gap-3">
                <ArtifactWhyNode :node="candidate.origin" :locale="locale" />
                <p v-if="candidate.twin_references.length" class="m-0">
                  {{ copy.twin }}:
                  {{
                    candidate.twin_references.map((node) => whyNodeTitle(node, locale)).join(", ")
                  }}
                </p>
                <p v-if="candidate.scenario_candidates.length" class="m-0">
                  {{ copy.scenario }}:
                  {{
                    candidate.scenario_candidates
                      .map((node) => whyNodeTitle(node, locale))
                      .join(", ")
                  }}
                </p>
                <p v-if="candidate.design_references.length" class="m-0">
                  {{ copy.design }}:
                  {{
                    candidate.design_references.map((node) => whyNodeTitle(node, locale)).join(", ")
                  }}
                </p>
                <ul v-if="candidate.gaps.length" class="m-0 list-disc pl-5 text-xs">
                  <li v-for="(gap, index) in candidate.gaps" :key="index">
                    {{ gapLabel(gap.code) }}
                  </li>
                </ul>
                <ArtifactWhy
                  :code="candidate.key"
                  :locale="locale"
                  test-id="validation-candidate-why"
                />
              </div>
            </details>
            <UiButton
              variant="outline"
              class="justify-self-start"
              :disabled="busy || candidate.twin_references.length === 0"
              data-testid="validation-select-candidate"
              @click="choose(candidate)"
              >{{ copy.choose }}</UiButton
            >
          </article>
          <UiButton
            v-if="!allCandidates && overview.candidate_count > 3"
            variant="quiet"
            class="justify-self-start"
            data-testid="validation-show-all"
            @click="allCandidates = true"
            >{{ copy.showAll }} · {{ overview.candidate_count }}</UiButton
          >
        </div>
      </section>
      <form
        v-if="selected"
        class="grid min-w-0 gap-3 rounded-field border border-petrol-on-night/60 bg-night-panel p-4"
        data-testid="validation-hypothesis-form"
        @submit.prevent="saveHypothesis"
      >
        <h3 class="m-0 font-semibold">
          {{ copy.operational }} · {{ whyNodeTitle(selected.origin, locale) }}
        </h3>
        <p class="m-0 text-sm text-on-night-2">{{ copy.concrete }}</p>
        <p class="m-0 text-xs text-on-night-2">{{ copy.explicitLink }}</p>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="grid gap-1.5 text-sm"
            >{{ copy.twin
            }}<select
              v-model="form.twin_key"
              required
              class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-twin"
            >
              <option value="">{{ copy.select }}</option>
              <option
                v-for="node in selected.twin_references.filter((node) => node.current)"
                :key="node.key"
                :value="node.key"
              >
                {{ whyNodeTitle(node, locale) }}
              </option>
            </select></label
          >
          <label class="grid gap-1.5 text-sm"
            >{{ copy.scenario
            }}<select
              v-model="form.scenario_key"
              required
              class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-scenario"
            >
              <option value="">{{ copy.select }}</option>
              <option v-for="node in scenarioOptions" :key="node.key" :value="node.key">
                {{ whyNodeTitle(node, locale) }}
              </option>
            </select></label
          >
          <label class="grid gap-1.5 text-sm"
            >{{ copy.design
            }}<select
              v-model="form.design_key"
              required
              class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-design"
            >
              <option value="">{{ copy.select }}</option>
              <option v-for="node in designOptions" :key="node.key" :value="node.key">
                {{ whyNodeTitle(node, locale) }} · {{ copy.version }}
                {{ node.reference.version_number }}
              </option>
            </select></label
          >
          <label class="grid gap-1.5 text-sm"
            >{{ copy.alternative
            }}<select
              v-model="form.alternative_id"
              class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-alternative"
            >
              <option value="">{{ copy.select }}</option>
              <option
                v-for="node in alternatives"
                :key="node.key"
                :value="node.reference.artifact_id"
              >
                {{ whyNodeTitle(node, locale) }}
              </option>
            </select></label
          >
        </div>
        <p
          v-if="form.twin_key && scenarioOptions.length === 0"
          class="m-0 text-xs text-warn-on-night"
        >
          {{ copy.linkMissing }} · {{ copy.scenario }}
        </p>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.question
          }}<textarea
            v-model="form.question"
            rows="2"
            maxlength="4000"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-question"
          />
        </label>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.task
          }}<textarea
            v-model="form.task"
            rows="2"
            maxlength="4000"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-task"
          />
        </label>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.observe
          }}<textarea
            v-model="form.observe"
            required
            rows="3"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-observe"
          /><span class="text-xs text-on-night-2">{{ copy.observeHelp }}</span></label
        >
        <label class="grid gap-1.5 text-sm"
          >{{ copy.limitations
          }}<textarea
            v-model="form.limitations"
            required
            rows="2"
            maxlength="4000"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-limitations"
          />
        </label>
        <details v-if="anchorOptions.length" class="min-w-0 text-sm">
          <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
            {{ copy.anchors }}
          </summary>
          <p class="m-0 mb-2 text-xs text-on-night-2">{{ copy.anchorHelp }}</p>
          <label
            v-for="node in anchorOptions"
            :key="node.key"
            class="flex min-h-11 items-center gap-3 [overflow-wrap:anywhere]"
            ><input
              v-model="form.anchor_keys"
              :value="node.key"
              type="checkbox"
              class="size-4 accent-petrol-on-night"
            />{{ whyNodeTitle(node, locale) }} ·
            {{ node.declared_context.mockup?.screen_code }}</label
          >
        </details>
        <div class="flex flex-wrap gap-2">
          <UiButton
            type="submit"
            :disabled="busy || !formValid"
            data-testid="validation-save-hypothesis"
            >{{ revision ? copy.saveVersion : copy.save }}</UiButton
          ><UiButton
            variant="quiet"
            :disabled="busy"
            @click="
              selected = null;
              revision = null;
            "
            >{{ copy.cancel }}</UiButton
          >
        </div>
      </form>
      <section class="grid gap-3" data-testid="validation-operational">
        <h3 class="m-0 text-base font-semibold">
          {{ copy.operationalPlural }} · {{ overview.summary.hypotheses }}
        </h3>
        <p v-if="currentHypotheses.length === 0" class="m-0 text-sm text-on-night-2">
          {{ copy.empty }}
        </p>
        <article
          v-for="hypothesis in currentHypotheses"
          :key="`${hypothesis.id}:${hypothesis.version_number}`"
          class="grid min-w-0 gap-3 rounded-field border border-night-line bg-night-panel p-4"
          data-testid="validation-hypothesis"
        >
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <h4 class="m-0 text-base font-semibold [overflow-wrap:anywhere]">
              {{ hypothesis.question ?? hypothesis.task }}
            </h4>
            <strong class="text-sm" data-testid="validation-hypothesis-state">{{
              state(hypothesis)
            }}</strong>
          </div>
          <p class="m-0 text-xs text-on-night-2">
            {{ copy.version }} {{ hypothesis.version_number }} · {{ copy.twin }}:
            {{ title(hypothesis.twin_key) }} · {{ copy.scenario }}:
            {{ title(hypothesis.scenario_key) }}
          </p>
          <p v-if="hypothesis.task" class="m-0 text-sm whitespace-pre-wrap">
            <strong>{{ copy.task }}:</strong> {{ hypothesis.task }}
          </p>
          <div class="grid gap-1 text-sm">
            <strong>{{ copy.observe }}</strong>
            <ul class="m-0 list-disc pl-5">
              <li v-for="(item, index) in hypothesis.observe" :key="index">{{ item }}</li>
            </ul>
          </div>
          <p class="m-0 text-sm whitespace-pre-wrap">
            <strong>{{ copy.limitations }}:</strong> {{ hypothesis.limitations }}
          </p>
          <p v-if="hypothesis.partial_evidence" class="m-0 text-sm text-warn-on-night">
            {{ copy.partial }}
          </p>
          <ul v-if="hypothesis.gaps?.length" class="m-0 list-disc pl-5 text-xs text-warn-on-night">
            <li v-for="(gap, index) in hypothesis.gaps" :key="index">{{ gapLabel(gap.code) }}</li>
          </ul>
          <details class="text-sm">
            <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
              {{ copy.details }}
            </summary>
            <div class="grid gap-2 text-xs">
              <p class="m-0">{{ copy.origin }}: {{ title(hypothesis.origin_key) }}</p>
              <p class="m-0">
                {{ copy.design }}: {{ title(hypothesis.design_key) }} · {{ copy.version }}
                {{ hypothesis.design_reference.version_number }}
              </p>
              <p class="m-0 font-mono break-all">{{ hypothesis.design_reference.content_hash }}</p>
              <p class="m-0 font-mono break-all">{{ hypothesis.content_hash }}</p>
            </div>
          </details>
          <div class="flex flex-wrap gap-2">
            <UiButton
              variant="outline"
              :disabled="busy"
              data-testid="validation-record-outcome"
              @click="beginOutcome(hypothesis)"
              >{{ copy.record }}</UiButton
            ><UiButton
              variant="quiet"
              :disabled="busy"
              data-testid="validation-revise-hypothesis"
              @click="revise(hypothesis)"
              >{{ copy.revise }}</UiButton
            >
          </div>
          <ArtifactWhy
            :code="hypothesis.code"
            kind="VALIDATION_HYPOTHESIS"
            :artifact-id="hypothesis.id"
            :version-number="hypothesis.version_number"
            :content-hash="hypothesis.content_hash"
            :locale="locale"
            test-id="validation-hypothesis-why"
          />
          <details class="grid gap-2">
            <summary
              tabindex="0"
              class="flex min-h-11 cursor-pointer items-center text-sm font-semibold"
            >
              {{ copy.outcomes }} · {{ hypothesis.outcomes?.length ?? 0 }}
            </summary>
            <div class="grid gap-3">
              <p v-if="!hypothesis.outcomes?.length" class="m-0 text-sm">{{ copy.noOutcomes }}</p>
              <ValidationOutcomeCard
                v-for="outcome in hypothesis.outcomes"
                :key="outcome.id"
                :outcome="outcome"
                :source="sourceFor(outcome.evidence_id, outcome.evidence_version)"
                :locale="locale"
                @open-evidence="emit('open-evidence', $event)"
              />
            </div>
          </details>
        </article>
      </section>
      <form
        v-if="outcomeTarget"
        class="grid min-w-0 gap-3 rounded-field border border-petrol-on-night/60 bg-night-panel p-4"
        data-testid="validation-outcome-form"
        @submit.prevent="saveOutcome"
      >
        <h3 class="m-0 font-semibold">
          {{ copy.record }} · {{ outcomeTarget.question ?? outcomeTarget.task }} ·
          {{ copy.version }} {{ outcomeTarget.version_number }}
        </h3>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.sessionKind
          }}<select
            v-model="outcomeForm.session_kind"
            class="min-h-11 w-full rounded-field border border-night-line-strong bg-night-raised px-3"
            data-testid="validation-session-kind"
          >
            <option value="HUMAN_SESSION">{{ copy.human }}</option>
            <option value="SYNTHETIC_EXERCISE">{{ copy.synthetic }}</option>
          </select></label
        >
        <label class="grid gap-1.5 text-sm"
          >{{ copy.sessionRef
          }}<input
            v-model="outcomeForm.session_ref"
            required
            maxlength="80"
            pattern="(SES|SESSION|SYN|TEST)-[A-Za-z0-9_.:\-]{1,70}"
            class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3"
            data-testid="validation-session-ref"
          /><span class="text-xs text-on-night-2">{{ copy.sessionRefHelp }}</span></label
        >
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="grid gap-1.5 text-sm"
            >{{ copy.outcome
            }}<select
              v-model="outcomeForm.outcome"
              class="min-h-11 w-full rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-outcome-value"
            >
              <option
                v-for="value in ['CONFIRMED', 'REFUTED', 'UNCERTAIN'] as const"
                :key="value"
                :value="value"
              >
                {{ copy.states[value] }}
              </option>
            </select></label
          ><label class="grid gap-1.5 text-sm"
            >{{ copy.coverage
            }}<select
              v-model="outcomeForm.coverage"
              class="min-h-11 w-full rounded-field border border-night-line-strong bg-night-raised px-3"
              data-testid="validation-coverage"
            >
              <option value="PARTIAL">{{ copy.partial }}</option>
              <option value="COMPLETE">{{ copy.complete }}</option>
            </select></label
          >
        </div>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.source
          }}<select
            v-model="outcomeForm.source_key"
            required
            class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
            data-testid="validation-source"
          >
            <option value="">{{ copy.select }}</option>
            <option
              v-for="source in availableSources"
              :key="sourceKey(source)"
              :value="sourceKey(source)"
            >
              {{ source.title }} · {{ copy.version }} {{ source.version }}
            </option>
          </select></label
        >
        <p v-if="availableSources.length === 0" class="m-0 text-sm text-warn-on-night">
          {{ copy.noSources }}
        </p>
        <div
          v-if="selectedSource"
          class="grid min-w-0 gap-2 rounded-field border border-night-line p-3 text-xs"
        >
          <p class="m-0 whitespace-pre-wrap">
            <strong>{{ copy.sourceContext }}:</strong> {{ selectedSource.context }}
          </p>
          <p class="m-0 whitespace-pre-wrap">
            <strong>{{ copy.sourceMethod }}:</strong> {{ selectedSource.method }}
          </p>
          <p v-if="selectedSource.collected_at" class="m-0">
            <strong>{{ copy.sourceDate }}:</strong> {{ selectedSource.collected_at }}
          </p>
          <p class="m-0 whitespace-pre-wrap">
            <strong>{{ copy.limitations }}:</strong> {{ selectedSource.limitations }}
          </p>
          <UiButton
            variant="quiet"
            class="justify-self-start"
            :disabled="busy"
            data-testid="validation-show-original"
            @click="showOriginal"
            >{{ copy.showOriginal }}</UiButton
          >
          <pre
            v-if="originalText !== null"
            class="m-0 max-h-64 overflow-auto font-sans [overflow-wrap:anywhere] whitespace-pre-wrap"
            data-testid="validation-original-text"
            >{{ originalText }}</pre>
        </div>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.quote
          }}<textarea
            v-model="outcomeForm.quote"
            required
            rows="3"
            maxlength="1000"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-outcome-quote"
          />
        </label>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.line
          }}<input
            v-model.number="outcomeForm.line"
            type="number"
            min="1"
            step="1"
            required
            class="min-h-11 rounded-field border border-night-line-strong bg-night-raised px-3"
            data-testid="validation-outcome-line"
        /></label>
        <label class="grid gap-1.5 text-sm"
          >{{ copy.limitations
          }}<textarea
            v-model="outcomeForm.limitations"
            required
            rows="2"
            maxlength="4000"
            class="rounded-field border border-night-line-strong bg-night-raised px-3 py-2"
            data-testid="validation-outcome-limitations"
          />
        </label>
        <div class="flex flex-wrap gap-2">
          <UiButton
            type="submit"
            :disabled="busy || !outcomeValid"
            data-testid="validation-save-outcome"
            >{{ copy.saveOutcome }}</UiButton
          ><UiButton
            variant="quiet"
            :disabled="busy"
            @click="
              outcomeTarget = null;
              originalText = null;
              outcomeForm.quote = '';
            "
            >{{ copy.cancel }}</UiButton
          ><UiButton
            variant="outline"
            :disabled="busy"
            data-testid="validation-add-evidence"
            @click="emit('open-evidence', null)"
            >{{ copy.addEvidence }}</UiButton
          >
        </div>
      </form>
      <details v-if="previousHypotheses.length" class="grid gap-3" data-testid="validation-history">
        <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
          {{ copy.history }} · {{ previousHypotheses.length }}
        </summary>
        <article
          v-for="hypothesis in previousHypotheses"
          :key="`${hypothesis.id}:${hypothesis.version_number}`"
          class="grid min-w-0 gap-3 rounded-field border border-dashed border-night-line-strong p-4"
        >
          <strong class="text-sm">{{ hypothesis.question ?? hypothesis.task }}</strong>
          <p class="m-0 text-xs">
            {{ copy.previous }} {{ hypothesis.version_number }} · {{ state(hypothesis) }}
          </p>
          <p v-if="hypothesis.task" class="m-0 text-sm whitespace-pre-wrap">
            {{ hypothesis.task }}
          </p>
          <p class="m-0 text-sm whitespace-pre-wrap">{{ hypothesis.limitations }}</p>
          <ul class="m-0 list-disc pl-5 text-sm">
            <li v-for="(item, index) in hypothesis.observe" :key="index">{{ item }}</li>
          </ul>
          <ArtifactWhy
            :code="hypothesis.code"
            kind="VALIDATION_HYPOTHESIS"
            :artifact-id="hypothesis.id"
            :version-number="hypothesis.version_number"
            :content-hash="hypothesis.content_hash"
            :locale="locale"
          /><ValidationOutcomeCard
            v-for="outcome in hypothesis.outcomes"
            :key="outcome.id"
            :outcome="outcome"
            :source="sourceFor(outcome.evidence_id, outcome.evidence_version)"
            :locale="locale"
            @open-evidence="emit('open-evidence', $event)"
          />
        </article>
      </details>
      <div
        class="grid gap-2 border-t border-night-line pt-3 text-xs"
        data-testid="validation-empirical-summary"
      >
        <p class="m-0">
          {{ copy.humanSummary }}: {{ overview.empirical_summary.human_session_outcomes }}
        </p>
        <p class="m-0">
          {{ copy.syntheticSummary }}: {{ overview.empirical_summary.synthetic_exercise_outcomes }}
        </p>
        <p
          v-if="overview.empirical_summary.human_session_outcomes === 0"
          class="m-0 text-on-night-2"
        >
          {{ copy.noHuman }}
        </p>
        <p v-if="overview.omitted_sections.length" class="m-0 text-warn-on-night">
          {{ copy.omitted }}
        </p>
      </div>
    </template>
  </section>
</template>
