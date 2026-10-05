<script setup lang="ts">
import { computed, inject, ref, useId, watch } from "vue";
import ArtifactWhy from "./ArtifactWhy.vue";
import UiButton from "./UiButton.vue";
import { whyContextKey } from "./whyContext";
import { humanValidationCopy } from "./humanValidationCopy";
import { whyGapLabel, whyNodeTitle } from "./whyCopy";
import { humanValidationApi, type HumanValidationApi } from "../api/humanValidation";
import type { ScenarioWalkthrough } from "../types/humanValidation";
import type { WhyNode } from "../types/why";

const props = withDefaults(
  defineProps<{
    alternativeId: string;
    documentHash: string;
    locale: "it" | "en";
    screenCodes?: readonly string[];
    api?: HumanValidationApi | undefined;
  }>(),
  { screenCodes: () => [], api: undefined },
);
const emit = defineEmits<{ screen: [code: string] }>();
const context = inject(whyContextKey, null);
const prefix = `scenario-walkthrough-${useId()}`;
const copy = computed(() => humanValidationCopy[props.locale]);
const scenarios = ref<WhyNode[]>([]);
const selected = ref("");
const opened = ref(false);
const loading = ref(false);
const failure = ref(false);
const walkthrough = ref<ScenarioWalkthrough | null>(null);
const stepNumber = ref(1);
let epoch = 0;
const step = computed(() =>
  walkthrough.value?.steps.find((item) => item.number === stepNumber.value),
);
const api = computed(() => props.api ?? humanValidationApi);

function gapLabel(code: string): string {
  return copy.value.gaps[code as keyof typeof copy.value.gaps] ?? whyGapLabel(code, props.locale);
}

async function loadScenarios(): Promise<void> {
  if (!context) return;
  const request = ++epoch;
  const project = context.projectId();
  loading.value = true;
  failure.value = false;
  try {
    const document = await context.authorize((token) => context.api.document(project, token));
    if (request !== epoch || project !== context.projectId()) return;
    scenarios.value = document.nodes.filter((node) => node.kind === "SCENARIO" && node.current);
  } catch {
    if (request === epoch) failure.value = true;
  } finally {
    if (request === epoch) loading.value = false;
  }
}

async function openWalkthrough(preserveStep = false): Promise<void> {
  if (!context || !selected.value || loading.value) return;
  const request = ++epoch;
  const project = context.projectId();
  const requestedStep = preserveStep ? stepNumber.value : null;
  loading.value = true;
  failure.value = false;
  walkthrough.value = null;
  try {
    const result = await context.authorize((token) =>
      api.value.walkthrough(
        project,
        selected.value,
        { alternativeId: props.alternativeId, documentHash: props.documentHash },
        token,
      ),
    );
    if (request !== epoch || project !== context.projectId()) return;
    walkthrough.value = result;
    stepNumber.value =
      result.steps.find((item) => item.number === requestedStep)?.number ??
      result.steps[0]?.number ??
      1;
  } catch {
    if (request === epoch) failure.value = true;
  } finally {
    if (request === epoch) loading.value = false;
  }
}

function toggle(event: Event): void {
  if (event.target !== event.currentTarget || !(event.target instanceof HTMLDetailsElement)) return;
  opened.value = event.target.open;
  if (opened.value && scenarios.value.length === 0 && !loading.value) void loadScenarios();
}

watch(
  () => [props.alternativeId, context?.projectId()] as const,
  () => {
    epoch += 1;
    walkthrough.value = null;
    failure.value = false;
    loading.value = false;
    scenarios.value = [];
    selected.value = "";
    if (opened.value) void loadScenarios();
  },
);
watch(
  () => props.documentHash,
  () => {
    if (!opened.value || !selected.value) return;
    epoch += 1;
    walkthrough.value = null;
    loading.value = false;
    void openWalkthrough(true);
  },
);
watch(selected, () => {
  epoch += 1;
  walkthrough.value = null;
  loading.value = false;
});
</script>

<template>
  <details
    v-if="context"
    class="min-w-0 border-t border-night-line p-4"
    data-testid="mockup-scenario-walkthrough"
    @toggle="toggle"
  >
    <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center text-base font-semibold">
      {{ copy.walkthrough }}
    </summary>
    <div class="grid min-w-0 gap-3 pt-2">
      <p class="m-0 text-xs leading-normal text-on-night-2">{{ copy.walkthroughIntro }}</p>
      <p v-if="loading" role="status" class="m-0 text-sm">{{ copy.loading }}</p>
      <p v-if="failure" role="alert" class="m-0 text-sm text-fail-on-night">{{ copy.failed }}</p>
      <p v-if="scenarios.length === 0 && !loading && !failure" class="m-0 text-sm">
        {{ copy.noScenarios }}
      </p>
      <label v-if="scenarios.length" :for="`${prefix}-scenario`" class="grid gap-1.5 text-sm"
        >{{ copy.scenario
        }}<select
          :id="`${prefix}-scenario`"
          v-model="selected"
          class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-raised px-3"
          data-testid="walkthrough-scenario"
        >
          <option value="">{{ copy.select }}</option>
          <option v-for="scenario in scenarios" :key="scenario.key" :value="scenario.key">
            {{ whyNodeTitle(scenario, locale) }}
          </option>
        </select></label
      >
      <UiButton
        v-if="scenarios.length"
        variant="outline"
        class="justify-self-start"
        :disabled="loading || !selected"
        data-testid="walkthrough-open"
        @click="openWalkthrough()"
        >{{ copy.openWalkthrough }}</UiButton
      >
      <template v-if="walkthrough">
        <h4 class="m-0 text-sm font-semibold [overflow-wrap:anywhere]">
          {{ whyNodeTitle(walkthrough.scenario, locale) }}
        </h4>
        <p class="m-0 text-xs text-on-night-2">
          {{ copy.version }} {{ walkthrough.reference.version_number }} · {{ copy.twin }}:
          {{
            walkthrough.twin_references.map((node) => whyNodeTitle(node, locale)).join(", ") ||
            copy.linkMissing
          }}
        </p>
        <div class="grid gap-1 text-sm">
          <strong>{{ copy.task }}</strong>
          <p class="m-0 whitespace-pre-wrap" data-testid="walkthrough-task">
            {{ walkthrough.task ?? copy.noTask }}
          </p>
        </div>
        <div v-if="walkthrough.steps.length" class="grid gap-3">
          <h5 class="m-0 text-sm font-semibold">{{ copy.steps }}</h5>
          <ol class="m-0 flex list-none flex-wrap gap-2 p-0" :aria-label="copy.steps">
            <li v-for="item in walkthrough.steps" :key="item.number">
              <button
                type="button"
                :aria-current="item.number === stepNumber ? 'step' : undefined"
                :class="[
                  'min-h-11 min-w-11 rounded-field border px-3 text-sm',
                  item.number === stepNumber
                    ? 'border-petrol-on-night bg-petrol-on-night/15'
                    : 'border-night-line-strong',
                ]"
                data-testid="walkthrough-step-button"
                @click="stepNumber = item.number"
              >
                {{ item.number }}
              </button>
            </li>
          </ol>
          <article
            v-if="step"
            class="grid gap-2 rounded-field border border-night-line p-3 text-sm"
            data-testid="walkthrough-step"
          >
            <p class="m-0 whitespace-pre-wrap">{{ step.number }}. {{ step.text }}</p>
            <strong>{{ copy.observe }}</strong>
            <ul v-if="step.observe.length" class="m-0 list-disc pl-5">
              <li v-for="(item, index) in step.observe" :key="index">{{ item }}</li>
            </ul>
            <p v-else class="m-0 text-xs text-on-night-2">{{ copy.noObserve }}</p>
            <ul v-if="step.gaps.length" class="m-0 list-disc pl-5 text-xs text-warn-on-night">
              <li v-for="(gap, index) in step.gaps" :key="index">{{ gapLabel(gap.code) }}</li>
            </ul>
            <div v-for="anchor in step.anchors" :key="anchor.key" class="grid gap-1">
              <strong>{{ whyNodeTitle(anchor, locale) }}</strong
              ><UiButton
                v-if="
                  anchor.declared_context.mockup &&
                  screenCodes.includes(anchor.declared_context.mockup.screen_code)
                "
                variant="quiet"
                class="justify-self-start"
                @click="emit('screen', anchor.declared_context.mockup.screen_code)"
                >{{ copy.screen }}</UiButton
              ><ArtifactWhy :code="anchor.key" :locale="locale" />
            </div>
          </article>
        </div>
        <p v-else class="m-0 text-xs text-warn-on-night">{{ copy.noSteps }}</p>
        <div v-if="walkthrough.expected_outcome" class="grid gap-1 text-sm">
          <strong>{{ copy.expected }}</strong>
          <p class="m-0 whitespace-pre-wrap" data-testid="walkthrough-expected">
            {{ walkthrough.expected_outcome }}
          </p>
        </div>
        <details
          v-if="walkthrough.anchor_candidates.length"
          class="min-w-0 text-sm"
          data-testid="walkthrough-anchor-candidates"
        >
          <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
            {{ copy.anchorCandidates }} · {{ walkthrough.anchor_candidates.length }}
          </summary>
          <p class="m-0 mb-3 text-xs text-on-night-2">{{ copy.anchorCandidatesHelp }}</p>
          <div class="grid gap-3">
            <article
              v-for="anchor in walkthrough.anchor_candidates"
              :key="anchor.key"
              class="grid min-w-0 gap-1"
              data-testid="walkthrough-anchor"
            >
              <strong class="text-sm [overflow-wrap:anywhere]">{{
                whyNodeTitle(anchor, locale)
              }}</strong>
              <p class="m-0 text-xs">
                {{ anchor.declared_context.mockup?.screen_code }} · {{ copy.version }}
                {{ anchor.reference.version_number }}
              </p>
              <UiButton
                v-if="
                  anchor.declared_context.mockup &&
                  screenCodes.includes(anchor.declared_context.mockup.screen_code)
                "
                variant="quiet"
                class="justify-self-start"
                data-testid="walkthrough-show-screen"
                @click="emit('screen', anchor.declared_context.mockup.screen_code)"
                >{{ copy.screen }}</UiButton
              ><ArtifactWhy :code="anchor.key" :locale="locale" />
            </article>
          </div>
        </details>
        <ul v-if="walkthrough.gaps.length" class="m-0 list-disc pl-5 text-xs text-warn-on-night">
          <li v-for="(gap, index) in walkthrough.gaps" :key="index">{{ gapLabel(gap.code) }}</li>
        </ul>
        <ArtifactWhy
          :code="walkthrough.scenario.key"
          :locale="locale"
          test-id="walkthrough-scenario-why"
        />
        <details class="text-xs">
          <summary tabindex="0" class="flex min-h-11 cursor-pointer items-center font-semibold">
            {{ copy.details }}
          </summary>
          <p class="m-0 font-mono break-all">{{ walkthrough.reference.content_hash }}</p>
          <p class="m-0 font-mono break-all">{{ documentHash }}</p>
          <ul class="m-0 list-disc pl-5">
            <li v-for="limit in walkthrough.limits" :key="limit">{{ gapLabel(limit) }}</li>
          </ul>
        </details>
      </template>
    </div>
  </details>
</template>
