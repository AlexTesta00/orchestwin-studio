<script setup lang="ts">
import { computed, onMounted, ref, useId, watch } from "vue";

import { designDiscussionCopy } from "./designDiscussionCopy";
import GenerationJobNotice from "./GenerationJobNotice.vue";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import UiButton from "./UiButton.vue";
import { observationLabel } from "./observationLabels";
import {
  withScreenNames,
  type ScreenName,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";
import { confidence, fill, formatDateTime } from "./textFormat";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { isGenerationInterrupted } from "@/api/generationJobs";
import { useAuthorizedRequest } from "@/composables/useAuthorizedRequest";
import { type AuthorizedDesignLoopRequest, useDesignLoopStore } from "@/stores/designLoop";
import { useGenerationResume } from "@/stores/generationJobs";
import type {
  DesignDiscussionPayload,
  DiscussionDecisionAction,
  DiscussionProposalPayload,
  DiscussionReactionPayload,
  DiscussionRoundPayload,
  DiscussionStance,
  DiscussionStatementPayload,
  DiscussionVerdict,
  InsightApplicationPayload,
  InsightSource,
} from "@/types/designLoop";

type Locale = "en" | "it";

const NOTE_LIMIT = 500;
const RELOAD_CODES = new Set([
  "DESIGN_DISCUSSION_OPEN",
  "DESIGN_DISCUSSION_CHANGED",
  "DESIGN_DISCUSSION_FULL",
  "DESIGN_DISCUSSION_CLOSED",
]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    designVersionId: string;
    designContentHash: string;
    twinNames?: Record<string, string>;
    screens?: readonly ScreenName[];
    elements?: Readonly<Record<string, string>>;
    workflows?: Readonly<Record<string, readonly WorkflowName[]>>;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: DesignLoopApi | undefined;
  }>(),
  {
    twinNames: () => ({}),
    screens: () => [],
    elements: () => ({}),
    workflows: () => ({}),
    locale: "en",
    authorize: undefined,
    api: undefined,
  },
);

const emit = defineEmits<{ applied: [application: InsightApplicationPayload] }>();

type KnownError = keyof (typeof designDiscussionCopy)["en"]["errors"];

const authorize = useAuthorizedRequest(() => props.authorize);
const store = useDesignLoopStore();
const uid = useId();
const titleId = `discussion-title-${uid}`;
const startNoteId = `discussion-start-note-${uid}`;
const roundNoteId = `discussion-round-note-${uid}`;
const copy = computed(() => designDiscussionCopy[props.locale]);
const api = computed(() => props.api ?? designLoopApi);
const startNote = ref("");
const roundNote = ref("");
const failure = ref<string | null>(null);
const expanded = ref(false);
const bodyId = `discussion-body-${uid}`;

const {
  job: discussionJob,
  failure: discussionJobFailure,
  dismiss: dismissDiscussionJob,
} = useGenerationResume({
  projectId: () => props.projectId,
  operations: ["DISCUSSION_START", "DISCUSSION_ROUND"],
  authorize,
  onSettled: reload,
});

const discussion = computed<DesignDiscussionPayload | null>(() =>
  store.projectId === props.projectId ? (store.discussions[0] ?? null) : null,
);
const rounds = computed<DiscussionRoundPayload[]>(() =>
  [...(discussion.value?.rounds ?? [])].sort((left, right) => left.ordinal - right.ordinal),
);
const lastOrdinal = computed(() => rounds.value.at(-1)?.ordinal ?? 0);
const isOpen = computed(() => discussion.value?.status === "OPEN");
const outdated = computed(
  () =>
    discussion.value !== null &&
    (discussion.value.design_version_id !== props.designVersionId ||
      discussion.value.design_content_hash !== props.designContentHash),
);
const roundsFull = computed(
  () => discussion.value !== null && discussion.value.rounds.length >= discussion.value.max_rounds,
);
const canContinue = computed(() => isOpen.value && !outdated.value && !roundsFull.value);
const running = computed(
  () => store.discussionBusy === "start" || store.discussionBusy === "round",
);
const names = computed(() => {
  const byId: Record<string, string> = { ...props.twinNames };
  for (const round of rounds.value) {
    for (const statement of round.statements) {
      byId[statement.twin_id] = statement.twin_name;
    }
  }
  return byId;
});
const naming = computed<ScreenNaming>(() => ({
  screens: props.screens,
  elements: props.elements,
  workflows: props.workflows[discussion.value?.alternative_id ?? ""] ?? [],
  locale: props.locale,
}));
const failureIsNotice = computed(() => failure.value !== null && isKnownError(failure.value));
const failureMessage = computed(() =>
  failure.value !== null && isKnownError(failure.value)
    ? copy.value.errors[failure.value]
    : copy.value.error,
);

function twinName(id: string): string {
  return names.value[id] ?? id.slice(0, 8);
}

function listOf(ids: readonly string[]): string {
  return new Intl.ListFormat(props.locale, { style: "long", type: "conjunction" }).format(
    ids.map(twinName),
  );
}

function named(text: string): string {
  return withScreenNames(text, naming.value);
}

function groundingOf(keys: readonly string[]): string {
  const labels = keys.map((key) =>
    observationLabel(key, props.locale).toLocaleLowerCase(props.locale),
  );
  return new Intl.ListFormat(props.locale, { style: "long", type: "conjunction" }).format([
    ...new Set(labels),
  ]);
}

function stanceClass(stance: DiscussionStance): string {
  if (stance === "SUPPORT") return "border-petrol-on-night/60 text-petrol-on-night-2";
  if (stance === "CONCERN") return "border-dashed border-violet-on-night text-violet-on-night-2";
  return "border-fail-on-night/60 text-fail-on-night";
}

function verdictClass(verdict: DiscussionVerdict): string {
  if (verdict === "AGREE") return "border-petrol-on-night/60 text-petrol-on-night-2";
  if (verdict === "PARTLY") return "border-dashed border-violet-on-night text-violet-on-night-2";
  return "border-fail-on-night/60 text-fail-on-night";
}

function reactionsOf(statement: DiscussionStatementPayload): DiscussionReactionPayload[] {
  return statement.reactions ?? [];
}

function normalized(value: string): string | null {
  const text = value.trim().replace(/\s+/g, " ");
  return text.length === 0 ? null : text;
}

function proposalSource(
  value: DesignDiscussionPayload,
  round: DiscussionRoundPayload,
  proposal: DiscussionProposalPayload,
): InsightSource {
  return {
    kind: "TWIN_DISCUSSION",
    id: `discussion:${value.id}:${round.ordinal}:${proposal.code}`,
    twinId: null,
    text: named(proposal.text),
  };
}

function isKnownError(code: string): code is KnownError {
  return code in designDiscussionCopy.en.errors;
}

async function reload(): Promise<void> {
  try {
    await store.loadDiscussions(props.projectId, authorize, api.value);
  } catch {
    return;
  }
}

async function recover(): Promise<void> {
  const code = store.discussionError ?? "DESIGN_DISCUSSION_FAILED";
  if (isGenerationInterrupted(code)) {
    failure.value = null;
    return;
  }
  failure.value = code;
  if (RELOAD_CODES.has(code)) {
    await reload();
  }
}

async function start(): Promise<void> {
  if (store.isBusy || discussionJob.value !== null) return;
  failure.value = null;
  dismissDiscussionJob();
  try {
    await store.startDiscussion(
      props.projectId,
      {
        design_version_id: props.designVersionId,
        design_content_hash: props.designContentHash,
        locale: props.locale === "it" ? "it-IT" : "en-US",
        owner_note: normalized(startNote.value),
      },
      authorize,
      api.value,
    );
    startNote.value = "";
  } catch {
    await recover();
  }
}

async function nextRound(): Promise<void> {
  const value = discussion.value;
  if (value === null || store.isBusy || !canContinue.value || discussionJob.value !== null) return;
  failure.value = null;
  dismissDiscussionJob();
  try {
    await store.nextDiscussionRound(
      props.projectId,
      value.id,
      { expected_round_count: value.rounds.length, owner_note: normalized(roundNote.value) },
      authorize,
      api.value,
    );
    roundNote.value = "";
  } catch {
    await recover();
  }
}

async function decide(action: DiscussionDecisionAction): Promise<void> {
  const value = discussion.value;
  if (value === null || store.isBusy || value.status !== "OPEN" || discussionJob.value !== null) {
    return;
  }
  failure.value = null;
  try {
    await store.decideDiscussion(props.projectId, value.id, action, authorize, api.value);
  } catch {
    await recover();
  }
}

async function load(): Promise<void> {
  failure.value = null;
  try {
    await store.loadDiscussions(props.projectId, authorize, api.value);
  } catch {
    failure.value = store.discussionError ?? "DESIGN_DISCUSSION_FAILED";
  }
}

onMounted(load);
watch(() => props.projectId, load);
watch(
  () => [discussion.value?.status, running.value || discussionJob.value !== null] as const,
  ([status, busy]) => {
    if (status === "OPEN" || busy) {
      expanded.value = true;
    }
  },
  { immediate: true },
);
</script>

<template>
  <section
    class="grid gap-4 rounded-tile border border-night-line bg-night-raised p-5 text-on-night sm:p-6"
    :aria-labelledby="titleId"
    data-testid="design-discussion-panel"
  >
    <header class="flex flex-wrap items-center gap-x-4 gap-y-3">
      <div class="grid min-w-[min(100%,16rem)] flex-1 gap-1">
        <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
          {{ copy.eyebrow }}
        </p>
        <h3 :id="titleId" class="m-0 text-lg font-semibold">
          {{ copy.title }}
        </h3>
      </div>
      <UiButton
        variant="outline"
        :aria-expanded="expanded ? 'true' : 'false'"
        :aria-controls="bodyId"
        data-testid="discussion-toggle"
        @click="expanded = !expanded"
      >
        {{ expanded ? copy.hide : copy.show }}
      </UiButton>
    </header>

    <div v-show="expanded" :id="bodyId" class="grid gap-4" data-testid="discussion-body">
      <p class="m-0 max-w-3xl text-[15px] leading-normal text-on-night-2">{{ copy.intro }}</p>

      <GenerationJobNotice
        v-if="discussionJob !== null || discussionJobFailure !== null"
        :job="discussionJob"
        :failure="discussionJobFailure"
        :locale="locale"
        @dismiss="dismissDiscussionJob"
      />
      <p v-else-if="running" class="m-0 text-sm text-on-night-2" aria-live="polite">
        {{ copy.running }}
      </p>

      <p
        v-if="failure !== null && failureIsNotice"
        class="m-0 rounded-field border border-night-line bg-on-night/3 px-4 py-3 text-sm text-on-night-2"
        role="status"
        data-testid="discussion-notice"
      >
        {{ failureMessage }}
      </p>
      <div
        v-else-if="failure !== null"
        class="grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
        role="alert"
        data-testid="discussion-error"
      >
        <p class="m-0 font-semibold">{{ failureMessage }}</p>
        <details class="text-xs">
          <summary class="inline-flex min-h-11 cursor-pointer items-center">
            {{ copy.details }}
          </summary>
          <code class="break-all">{{ failure }}</code>
        </details>
      </div>

      <template v-if="discussion !== null">
        <p
          class="m-0 text-sm font-semibold text-petrol-on-night-2"
          :data-status="discussion.status"
          data-testid="discussion-status"
        >
          <template v-if="discussion.status === 'OPEN'">
            {{ copy.open }} ·
            {{ fill(copy.roundOf, { n: discussion.rounds.length, max: discussion.max_rounds }) }}
          </template>
          <template v-else-if="discussion.status === 'APPROVED'">
            {{
              fill(copy.approved, {
                date: formatDateTime(discussion.decided_at ?? discussion.created_at, locale),
              })
            }}
          </template>
          <template v-else>
            {{
              fill(copy.closed, {
                date: formatDateTime(discussion.decided_at ?? discussion.created_at, locale),
              })
            }}
          </template>
        </p>
        <p
          v-if="isOpen && outdated"
          class="m-0 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm text-warn-on-night"
          data-testid="discussion-outdated"
        >
          {{ fill(copy.outdated, { n: discussion.design_version_number }) }}
        </p>

        <details
          v-for="round in rounds"
          :key="round.ordinal"
          class="rounded-field border border-night-line px-4 pb-1"
          :open="isOpen && round.ordinal === lastOrdinal"
          data-testid="discussion-round"
        >
          <summary class="flex min-h-11 cursor-pointer items-center gap-1.5 font-semibold">
            {{ fill(copy.round, { n: round.ordinal }) }}
            <span class="font-normal text-on-night-3">
              · {{ fill(copy.statements, { n: round.statements.length }) }}
            </span>
          </summary>
          <div class="mt-1 grid gap-4 pb-4">
            <p
              v-if="round.owner_note"
              class="m-0 text-sm text-on-night-2"
              data-testid="discussion-owner-note"
            >
              <strong class="text-on-night">{{ copy.yourNote }}:</strong> {{ round.owner_note }}
            </p>
            <ul class="m-0 grid list-none gap-3 p-0">
              <li
                v-for="statement in round.statements"
                :key="`${round.ordinal}:${statement.twin_id}`"
                class="grid gap-2 rounded-field border border-night-line bg-on-night/3 p-4"
                data-testid="discussion-statement"
              >
                <div class="flex flex-wrap items-center gap-2 text-xs">
                  <strong class="text-sm text-on-night">{{ statement.twin_name }}</strong>
                  <span
                    class="inline-flex min-h-6 items-center rounded-pill border px-2.5 font-semibold"
                    :class="stanceClass(statement.stance)"
                    :data-stance="statement.stance"
                    data-testid="discussion-stance"
                  >
                    {{ copy.stance[statement.stance] }}
                  </span>
                  <span
                    v-if="reactionsOf(statement).length === 0 && statement.replies_to.length > 0"
                    class="text-on-night-3"
                    data-testid="discussion-replies-to"
                  >
                    {{ fill(copy.repliesTo, { names: listOf(statement.replies_to) }) }}
                  </span>
                  <span class="text-on-night-3">
                    {{ fill(copy.confidence, { value: confidence(statement.confidence, locale) }) }}
                  </span>
                </div>
                <div
                  v-if="statement.answer_to_owner"
                  class="grid gap-1 border-l-2 border-petrol-on-night/60 pl-3 text-sm"
                  data-testid="discussion-answer-to-owner"
                >
                  <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.answerToOwner }}</p>
                  <p class="m-0 leading-normal whitespace-pre-line text-on-night">
                    {{ named(statement.answer_to_owner) }}
                  </p>
                </div>
                <p
                  class="m-0 text-[15px] leading-normal whitespace-pre-line text-on-night"
                  data-testid="discussion-statement-text"
                >
                  {{ named(statement.statement) }}
                </p>
                <div
                  v-if="reactionsOf(statement).length > 0"
                  class="grid gap-1 text-sm"
                  data-testid="discussion-reactions"
                >
                  <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.reactions }}</p>
                  <ul class="m-0 grid list-none gap-1 p-0">
                    <li
                      v-for="(reaction, index) in reactionsOf(statement)"
                      :key="`${reaction.twin_id}:${index}`"
                      class="flex flex-wrap items-baseline gap-2"
                      :data-verdict="reaction.verdict"
                      data-testid="discussion-reaction"
                    >
                      <strong class="text-on-night">{{ twinName(reaction.twin_id) }}</strong>
                      <span
                        class="inline-flex min-h-6 items-center rounded-pill border px-2.5 text-xs font-semibold"
                        :class="verdictClass(reaction.verdict)"
                        data-testid="discussion-verdict"
                      >
                        {{ copy.verdict[reaction.verdict] }}
                      </span>
                      <span class="text-on-night-2">{{ named(reaction.reason) }}</span>
                    </li>
                  </ul>
                </div>
                <div
                  v-if="statement.proposals.length > 0"
                  class="grid gap-1 text-sm text-on-night-2"
                >
                  <p class="m-0 font-semibold text-on-night">{{ copy.proposes }}</p>
                  <ul class="m-0 list-disc pl-5">
                    <li v-for="proposal in statement.proposals" :key="proposal">
                      {{ named(proposal) }}
                    </li>
                  </ul>
                </div>
              </li>
            </ul>

            <section
              class="grid gap-3 rounded-field border border-petrol-on-night/35 bg-petrol-on-night/8 p-4"
              data-testid="discussion-synthesis"
            >
              <h4 class="m-0 text-sm font-semibold text-petrol-on-night-2">{{ copy.synthesis }}</h4>
              <div class="grid gap-1 text-sm text-on-night">
                <h5 class="m-0 font-semibold">{{ copy.agreements }}</h5>
                <ul v-if="round.synthesis.agreements.length > 0" class="m-0 list-disc pl-5">
                  <li v-for="agreement in round.synthesis.agreements" :key="agreement">
                    {{ named(agreement) }}
                  </li>
                </ul>
                <p v-else class="m-0 text-on-night-3">{{ copy.nothing }}</p>
              </div>
              <div class="grid gap-1 text-sm text-on-night">
                <h5 class="m-0 font-semibold">{{ copy.conflicts }}</h5>
                <ul
                  v-if="round.synthesis.conflicts.length > 0"
                  class="m-0 grid list-none gap-2 p-0"
                >
                  <li
                    v-for="conflict in round.synthesis.conflicts"
                    :key="conflict.topic"
                    class="grid gap-1"
                    data-testid="discussion-conflict"
                  >
                    <p class="m-0 font-semibold">{{ named(conflict.topic) }}</p>
                    <ul class="m-0 list-disc pl-5 text-on-night-2">
                      <li
                        v-for="position in conflict.positions"
                        :key="`${conflict.topic}:${position.twin_id}`"
                      >
                        <strong class="text-on-night">{{ twinName(position.twin_id) }}:</strong>
                        {{ named(position.position) }}
                      </li>
                    </ul>
                  </li>
                </ul>
                <p v-else class="m-0 text-on-night-3">{{ copy.nothing }}</p>
              </div>
              <div class="grid gap-2 text-sm text-on-night">
                <h5 class="m-0 font-semibold">{{ copy.proposals }}</h5>
                <ul
                  v-if="round.synthesis.proposals.length > 0"
                  class="m-0 grid list-none gap-3 p-0"
                >
                  <li
                    v-for="proposal in round.synthesis.proposals"
                    :key="proposal.code"
                    class="grid gap-1 rounded-field border border-night-line bg-night-raised p-3"
                    :data-target="proposal.target"
                    data-testid="discussion-proposal"
                  >
                    <p class="m-0 font-semibold">{{ named(proposal.text) }}</p>
                    <p v-if="proposal.supported_by.length > 0" class="m-0 text-xs text-on-night-3">
                      {{ fill(copy.supportedBy, { names: listOf(proposal.supported_by) }) }}
                    </p>
                    <p class="m-0 text-xs text-on-night-2" data-testid="discussion-proposal-target">
                      {{ copy.suggestedTarget[proposal.target] }}
                    </p>
                    <InsightApplyMenu
                      :project-id="projectId"
                      :source="proposalSource(discussion, round, proposal)"
                      :locale="locale"
                      :authorize="authorize"
                      :api="api"
                      @applied="emit('applied', $event)"
                    />
                  </li>
                </ul>
                <p v-else class="m-0 text-on-night-3">{{ copy.nothing }}</p>
              </div>
              <div v-if="round.synthesis.questions_for_owner.length > 0" class="grid gap-1 text-sm">
                <h5 class="m-0 font-semibold text-on-night">{{ copy.questions }}</h5>
                <ul class="m-0 list-disc pl-5 text-on-night-2">
                  <li v-for="question in round.synthesis.questions_for_owner" :key="question">
                    {{ named(question) }}
                  </li>
                </ul>
              </div>
            </section>

            <details class="text-xs text-on-night-3">
              <summary class="inline-flex min-h-11 cursor-pointer items-center font-mono">
                {{ copy.technical }}
              </summary>
              <ul class="m-0 grid list-none gap-1 p-0 font-mono break-all">
                <li>{{ round.content_hash }}</li>
                <li>{{ round.synthesis.model_generation_id }}</li>
                <li
                  v-for="statement in round.statements"
                  :key="`${round.ordinal}:${statement.twin_id}:technical`"
                  data-testid="discussion-technical-statement"
                >
                  {{ statement.twin_name }} · {{ statement.model_generation_id }}
                  <template v-if="statement.grounded_on.length > 0">
                    · {{ fill(copy.groundedOn, { fields: groundingOf(statement.grounded_on) }) }}
                  </template>
                </li>
              </ul>
            </details>
          </div>
        </details>

        <section v-if="isOpen" class="grid gap-3" data-testid="discussion-actions">
          <label
            v-if="canContinue"
            class="grid gap-1.5 text-sm font-medium text-on-night-2"
            :for="roundNoteId"
          >
            {{ copy.roundNote }}
            <textarea
              :id="roundNoteId"
              v-model="roundNote"
              rows="2"
              :maxlength="NOTE_LIMIT"
              :disabled="store.isBusy"
              class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] font-normal text-on-night"
              data-testid="discussion-round-note"
            ></textarea>
          </label>
          <p v-if="roundsFull" class="m-0 text-sm text-on-night-2" data-testid="discussion-full">
            {{ copy.full }}
          </p>
          <div class="flex flex-wrap items-center gap-3">
            <UiButton
              variant="pill"
              :disabled="store.isBusy || discussionJob !== null"
              data-testid="discussion-approve"
              @click="decide('APPROVE')"
            >
              {{ copy.approve }}
            </UiButton>
            <UiButton
              v-if="canContinue"
              variant="outline"
              :disabled="store.isBusy || discussionJob !== null"
              data-testid="discussion-next-round"
              @click="nextRound"
            >
              {{ copy.nextRound }}
            </UiButton>
            <UiButton
              variant="quiet"
              :disabled="store.isBusy || discussionJob !== null"
              data-testid="discussion-close"
              @click="decide('CLOSE')"
            >
              {{ copy.close }}
            </UiButton>
          </div>
        </section>
      </template>

      <section v-if="!isOpen" class="grid gap-3" data-testid="discussion-start">
        <label class="grid gap-1.5 text-sm font-medium text-on-night-2" :for="startNoteId">
          {{ copy.startNote }}
          <textarea
            :id="startNoteId"
            v-model="startNote"
            rows="2"
            :maxlength="NOTE_LIMIT"
            :disabled="store.isBusy"
            class="min-h-11 rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] font-normal text-on-night"
            data-testid="discussion-start-note"
          ></textarea>
        </label>
        <UiButton
          variant="outline"
          class="justify-self-start"
          :disabled="store.isBusy || discussionJob !== null"
          data-testid="discussion-start-button"
          @click="start"
        >
          {{ discussion === null ? copy.start : copy.restart }}
        </UiButton>
      </section>
    </div>
  </section>
</template>
