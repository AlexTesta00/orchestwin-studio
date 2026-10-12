<script lang="ts">
export {
  generationFailureText,
  generationReasonText,
  generationRetryable,
} from "./iterationMessages";
export type { IterationItem, IterationJob } from "./iterationTypes";
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import type { MockupDocument } from "./GeneratedMockupDialog.vue";
import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import UiClaimFrame from "./UiClaimFrame.vue";
import UiStateBlock from "./UiStateBlock.vue";
import UiStatusChip from "./UiStatusChip.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { designIterationCopy } from "./designIterationCopy";
import {
  correctionLines,
  generationFailureText,
  generationReasonText,
  generationRetryable,
  uncorrectedWarnings,
  type GenerationLocale,
} from "./iterationMessages";
import type { IterationItem, IterationJob, IterationReason, IterationSide } from "./iterationTypes";
import {
  withScreenNames,
  type ScreenName,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";
import { fill, formatDateTime, moveTabFocus } from "./textFormat";

type Phase = "idle" | "drawing" | "ready" | "rejected" | "failed" | "error";

const QUOTE_CLASS = "border-l-2 border-on-night/40 pl-3 leading-normal whitespace-pre-line";

const props = withDefaults(
  defineProps<{
    job?: IterationJob | null | undefined;
    request?: string | null | undefined;
    items?: readonly IterationItem[] | undefined;
    before?: MockupDocument | null | undefined;
    after?: MockupDocument | null | undefined;
    assertions?: readonly string[] | undefined;
    error?: string | null | undefined;
    busy?: boolean | undefined;
    screens?: readonly ScreenName[] | undefined;
    workflows?: readonly WorkflowName[] | undefined;
    locale?: GenerationLocale | undefined;
  }>(),
  {
    job: null,
    request: null,
    items: () => [],
    before: null,
    after: null,
    assertions: () => [],
    error: null,
    busy: false,
    screens: () => [],
    workflows: () => [],
    locale: undefined,
  },
);

const emit = defineEmits<{
  apply: [generationId: string];
  discard: [generationId: string];
  "remove-assertion": [assertion: string];
  open: [side: IterationSide, screen: string];
  retry: [request: string];
  screen: [code: string];
}>();

const CHIPS = {
  PROPOSED: "pending",
  APPLIED: "approved",
  REJECTED: "rejected",
  FAILED: "failed",
} as const;

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { locale: appLocale } = useI18n({ useScope: "global" });

const lang = computed<GenerationLocale>(
  () => props.locale ?? (appLocale.value === "it" ? "it" : "en"),
);
const copy = computed(() => designIterationCopy[lang.value]);

const titleId = useId();
const historyId = useId();
const rulesId = useId();
const regionId = useId();
const tabPrefix = useId();

const now = ref(Date.now());
const historyOpen = ref(false);
const requested = ref<string | null>(null);
const focusIndex = ref(0);
const narrow = ref(false);
const tablist = ref<HTMLElement | null>(null);

let clock: ReturnType<typeof setInterval> | null = null;
let media: MediaQueryList | null = null;

const phase = computed<Phase>(() => {
  if (props.error !== null) {
    return "error";
  }
  const job = props.job;
  if (job === null) {
    return "idle";
  }
  if (job.status === "RUNNING") {
    return "drawing";
  }
  if (job.status === "SUCCEEDED") {
    return job.result === null ? "failed" : "ready";
  }
  return job.status === "REJECTED" ? "rejected" : "failed";
});

const visible = computed(
  () => phase.value !== "idle" || props.assertions.length > 0 || props.items.length > 0,
);

const requestText = computed(() => props.request?.trim() ?? "");

const elapsed = computed(() => {
  const started = props.job === null ? Number.NaN : Date.parse(props.job.started_at);
  if (Number.isNaN(started)) {
    return "";
  }
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  const time = minutes > 0 ? `${minutes} min ${seconds % 60} s` : `${seconds} s`;
  return fill(copy.value.elapsed, { time });
});

const stageText = computed(() => {
  const stage = props.job?.stage ?? null;
  return stage === null ? copy.value.stages.none : copy.value.stages[stage];
});

const result = computed(() => (phase.value === "ready" ? (props.job?.result ?? null) : null));

const naming = computed<ScreenNaming>(() => ({
  screens: [...props.screens, ...(props.after?.screens ?? []), ...(props.before?.screens ?? [])],
  workflows: props.workflows,
  locale: lang.value,
}));

const changes = computed(() =>
  (result.value?.changes ?? []).map((change) => withScreenNames(change, naming.value)),
);

const screens = computed(() => props.after?.screens ?? props.before?.screens ?? []);

const selectedScreen = computed(
  () =>
    requested.value ??
    props.after?.entry_screen ??
    props.before?.entry_screen ??
    screens.value[0]?.code ??
    null,
);

const selectedIndex = computed(() =>
  screens.value.findIndex((screen) => screen.code === selectedScreen.value),
);

const sides = computed(() =>
  (["before", "after"] as const).map((side) => {
    const document = side === "before" ? props.before : props.after;
    const version = side === "before" ? copy.value.current : copy.value.proposed;
    const screen = document?.screens.find((item) => item.code === document.entry_screen);
    return {
      side,
      document,
      version,
      note: side === "before" ? copy.value.currentNote : copy.value.proposedNote,
      status: side === "before" ? ("confirmed" as const) : ("hypothesis" as const),
      title: fill(copy.value.frame, { version, screen: screen?.title ?? document?.title ?? "" }),
      key: document === null ? side : `${side}|${document.content_hash}|${document.entry_screen}`,
    };
  }),
);

const resultCorrections = computed(() => result.value?.corrections ?? []);

const corrections = computed(() => correctionLines(resultCorrections.value, lang.value));

const warnings = computed(() =>
  reasonLines(uncorrectedWarnings(result.value?.warnings ?? [], resultCorrections.value)),
);

const failureText = computed(() => {
  if (phase.value === "error") {
    return generationFailureText(props.error, lang.value);
  }
  return generationFailureText(props.job?.failure?.code, lang.value);
});

const failureReasons = computed(() =>
  phase.value === "rejected" || phase.value === "failed"
    ? reasonLines(props.job?.failure?.reasons ?? [])
    : [],
);

const failureTitle = computed(() => {
  if (phase.value === "error") {
    return copy.value.errorTitle;
  }
  return phase.value === "rejected" ? copy.value.rejectedTitle : copy.value.failedTitle;
});

const canRetry = computed(() => {
  if (requestText.value.length === 0 || props.busy) {
    return false;
  }
  if (phase.value === "error") {
    return generationRetryable(props.error);
  }
  return generationRetryable(props.job?.failure?.code);
});

const history = computed(() =>
  props.items.map((item) => ({
    item,
    date: formatDate(item.requested_at),
    chip: CHIPS[item.status],
    label: copy.value.statuses[item.status],
    notes: [
      {
        key: "changes",
        title: copy.value.historyChanges,
        lines: item.changes.map((change) => withScreenNames(change, naming.value)),
      },
      {
        key: "corrections",
        title: copy.value.historyCorrections,
        lines: correctionLines(item.corrections ?? [], lang.value),
      },
      { key: "rules", title: copy.value.historyRules, lines: item.assertions },
    ].filter((note) => note.lines.length > 0),
  })),
);

function formatDate(value: string): string {
  return Number.isNaN(new Date(value).getTime()) ? "" : formatDateTime(value, lang.value);
}

function screenTitle(code: string | null | undefined): string | null {
  if (!code) {
    return null;
  }
  const known = [...(props.after?.screens ?? []), ...(props.before?.screens ?? [])];
  return known.find((screen) => screen.code === code)?.title ?? null;
}

function reasonLines(reasons: readonly IterationReason[]): string[] {
  const lines: string[] = [];
  for (const reason of reasons) {
    const text = generationReasonText(reason.code, lang.value);
    const title = screenTitle(reason.screen_code);
    const line = title === null ? text : fill(copy.value.onScreen, { title, text });
    if (!lines.includes(line)) {
      lines.push(line);
    }
  }
  return lines;
}

function tabId(index: number): string {
  return `${tabPrefix}-${index}`;
}

function chooseScreen(code: string): void {
  if (code === selectedScreen.value) {
    return;
  }
  requested.value = code;
  emit("screen", code);
}

function moveFocus(event: KeyboardEvent): void {
  moveTabFocus(event, focusIndex, screens.value.length, tablist.value);
}

function openLarge(side: IterationSide): void {
  const document = side === "before" ? props.before : props.after;
  if (document !== null) {
    emit("open", side, document.entry_screen);
  }
}

function apply(): void {
  const id = result.value?.generation_id;
  if (id !== undefined && !props.busy) {
    emit("apply", id);
  }
}

function discard(): void {
  const id = result.value?.generation_id;
  if (id !== undefined && !props.busy) {
    emit("discard", id);
  }
}

function retry(): void {
  if (canRetry.value) {
    emit("retry", requestText.value);
  }
}

function tick(): void {
  now.value = Date.now();
}

function updateNarrow(): void {
  narrow.value = media?.matches ?? false;
}

watch(
  phase,
  (current) => {
    if (current === "drawing" && clock === null) {
      tick();
      clock = setInterval(tick, 1000);
    }
    if (current !== "drawing" && clock !== null) {
      clearInterval(clock);
      clock = null;
    }
  },
  { immediate: true },
);

watch(
  () => [props.after?.entry_screen, props.before?.entry_screen],
  () => {
    requested.value = null;
  },
);

watch(
  selectedIndex,
  (index) => {
    focusIndex.value = Math.max(0, index);
  },
  { immediate: true },
);

onMounted(() => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return;
  }
  media = window.matchMedia("(max-width: 767px)");
  updateNarrow();
  media.addEventListener?.("change", updateNarrow);
});

onBeforeUnmount(() => {
  if (clock !== null) {
    clearInterval(clock);
    clock = null;
  }
  media?.removeEventListener?.("change", updateNarrow);
  media = null;
});
</script>

<template>
  <section
    v-if="visible"
    class="grid gap-4 text-on-night"
    data-surface="night"
    :aria-labelledby="titleId"
    :data-phase="phase"
    data-testid="design-iteration-panel"
  >
    <h2 :id="titleId" class="text-xl font-semibold">{{ copy.title }}</h2>

    <template v-if="phase === 'drawing'">
      <UiAgentMessage :role-label="copy.designer" avatar="/team/ux.webp">
        {{ copy.drawingMessage }}
      </UiAgentMessage>
      <div
        class="grid gap-3 rounded-tile border border-night-line bg-night-raised p-5"
        aria-busy="true"
        data-testid="design-iteration-drawing"
      >
        <div v-if="requestText" class="grid gap-1">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.request }}
          </p>
          <blockquote :class="[QUOTE_CLASS, 'text-[15px]']" data-testid="design-iteration-request">
            {{ requestText }}
          </blockquote>
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-on-night-2">
          <span
            class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
            aria-hidden="true"
          />
          <span role="status" data-testid="design-iteration-stage">{{ stageText }}</span>
          <span class="text-on-night-3" data-testid="design-iteration-elapsed">{{ elapsed }}</span>
        </div>
        <p class="text-sm leading-normal text-on-night-3" data-testid="design-iteration-duration">
          {{ copy.duration }}
        </p>
      </div>
    </template>

    <template v-else-if="phase === 'ready' && result !== null">
      <UiAgentMessage :role-label="copy.designer" avatar="/team/ux.webp">
        {{ copy.readyMessage }}
      </UiAgentMessage>
      <div
        class="grid gap-5 rounded-tile border border-night-line bg-night-raised p-4 sm:p-6"
        data-testid="design-iteration-ready"
      >
        <div v-if="requestText" class="grid gap-1">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.request }}
          </p>
          <blockquote :class="[QUOTE_CLASS, 'text-[15px]']" data-testid="design-iteration-request">
            {{ requestText }}
          </blockquote>
        </div>
        <div class="grid gap-2">
          <h3 class="text-base font-semibold">{{ copy.changes }}</h3>
          <ul
            v-if="changes.length > 0"
            class="grid list-disc gap-1.5 pl-5 text-[15px] leading-normal text-on-night-2 marker:text-petrol-on-night"
            data-testid="design-iteration-changes"
          >
            <li v-for="change in changes" :key="change">{{ change }}</li>
          </ul>
          <p v-else class="text-sm text-on-night-3">{{ copy.noChanges }}</p>
        </div>
        <div class="grid gap-3">
          <div
            v-if="screens.length > 1"
            ref="tablist"
            role="tablist"
            :aria-label="copy.screens"
            class="-mx-1.5 flex min-w-0 gap-1 overflow-x-auto p-1.5"
            data-testid="design-iteration-screens"
            @keydown="moveFocus"
          >
            <button
              v-for="(screen, index) in screens"
              :id="tabId(index)"
              :key="screen.code"
              type="button"
              role="tab"
              :aria-selected="screen.code === selectedScreen ? 'true' : 'false'"
              :aria-controls="regionId"
              :tabindex="index === focusIndex ? 0 : -1"
              :class="[
                'inline-flex min-h-11 shrink-0 items-center rounded-pill px-3.5 text-[13px] font-medium whitespace-nowrap transition-colors duration-150',
                screen.code === selectedScreen
                  ? 'bg-on-night text-ink'
                  : 'text-on-night hover:bg-night-hover',
              ]"
              :data-screen="screen.code"
              data-testid="design-iteration-screen"
              @click="chooseScreen(screen.code)"
            >
              {{ screen.title }}
            </button>
          </div>
          <p
            v-if="requested !== null"
            class="inline-flex items-center gap-2 text-sm text-on-night-2"
            role="status"
            data-testid="design-iteration-opening"
          >
            <span
              class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
              aria-hidden="true"
            />
            {{ copy.opening }}
          </p>
          <div
            :id="regionId"
            :role="screens.length > 1 ? 'tabpanel' : undefined"
            :aria-labelledby="
              screens.length > 1 && selectedIndex >= 0 ? tabId(selectedIndex) : undefined
            "
            :aria-busy="requested !== null ? 'true' : undefined"
            class="grid gap-4 md:grid-cols-2"
          >
            <UiClaimFrame
              v-for="item in sides"
              :key="item.side"
              as="section"
              :status="item.status"
              radius="tile"
              :padded="false"
              class="grid content-start gap-3 overflow-hidden p-3"
              :data-side="item.side"
              data-testid="design-iteration-side"
            >
              <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 px-1">
                <h3 class="text-[15px] font-semibold">{{ item.version }}</h3>
                <span
                  :class="[
                    'text-xs',
                    item.status === 'confirmed'
                      ? 'text-petrol-on-night-2'
                      : 'text-violet-on-night-2',
                  ]"
                >
                  {{ item.note }}
                </span>
              </div>
              <div
                :class="[
                  'overflow-hidden rounded-field bg-night-deep',
                  narrow ? 'h-[520px]' : 'h-[420px]',
                ]"
              >
                <GeneratedMockupFrame
                  v-if="item.document"
                  :key="item.key"
                  :html="item.document.html"
                  :title="item.title"
                  :width="narrow ? 'phone' : 'desktop'"
                />
                <div v-else class="grid h-full place-items-center p-4">
                  <UiStateBlock kind="loading" :title="copy.preparing" />
                </div>
              </div>
              <UiButton
                variant="outline"
                class="justify-self-start"
                :disabled="!item.document"
                :data-side="item.side"
                data-testid="design-iteration-open"
                :aria-label="fill(copy.openLabel, { version: item.version })"
                @click="openLarge(item.side)"
              >
                {{ copy.open }}
              </UiButton>
            </UiClaimFrame>
          </div>
        </div>
        <div
          v-if="corrections.length > 0"
          class="grid gap-2"
          data-testid="design-iteration-corrections"
        >
          <h3 class="text-base font-semibold">{{ copy.corrections }}</h3>
          <p class="text-sm text-on-night-3">{{ copy.correctionsNote }}</p>
          <ul
            class="grid list-disc gap-1.5 pl-5 text-sm leading-normal text-on-night-2 marker:text-petrol-on-night"
          >
            <li
              v-for="(line, index) in corrections"
              :key="index"
              data-testid="design-iteration-correction"
            >
              {{ line }}
            </li>
          </ul>
        </div>
        <div v-if="warnings.length > 0" class="grid gap-2" data-testid="design-iteration-warnings">
          <h3 class="text-base font-semibold text-warn-on-night">{{ copy.warnings }}</h3>
          <p class="text-sm text-on-night-3">{{ copy.warningsNote }}</p>
          <ul
            class="grid list-disc gap-1.5 pl-5 text-sm leading-normal text-on-night-2 marker:text-warn-on-night"
          >
            <li v-for="line in warnings" :key="line">{{ line }}</li>
          </ul>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <UiButton
            variant="outline"
            :disabled="busy"
            data-testid="design-iteration-discard"
            @click="discard"
          >
            {{ copy.discard }}
          </UiButton>
          <UiButton
            variant="pill"
            :disabled="busy"
            data-testid="design-iteration-apply"
            @click="apply"
          >
            {{ copy.apply }}
          </UiButton>
        </div>
      </div>
    </template>

    <UiStateBlock
      v-else-if="phase === 'rejected' || phase === 'failed' || phase === 'error'"
      kind="error"
      :title="failureTitle"
      :text="failureText"
      data-testid="design-iteration-failure"
    >
      <div class="grid gap-3">
        <div v-if="failureReasons.length > 0" class="grid gap-1">
          <p class="text-sm font-semibold">{{ copy.why }}</p>
          <ul class="grid list-disc gap-1 pl-5 text-sm leading-normal">
            <li v-for="line in failureReasons" :key="line">{{ line }}</li>
          </ul>
        </div>
        <div v-if="requestText" class="grid gap-1" data-testid="design-iteration-failure-request">
          <p class="text-sm font-semibold">{{ copy.request }}</p>
          <blockquote :class="[QUOTE_CLASS, 'text-sm text-on-night-2']">
            {{ requestText }}
          </blockquote>
        </div>
        <UiButton
          v-if="canRetry"
          variant="outline"
          class="justify-self-start"
          data-testid="design-iteration-retry"
          @click="retry"
        >
          {{ copy.retry }}
        </UiButton>
      </div>
    </UiStateBlock>

    <section
      v-if="assertions.length > 0"
      class="grid gap-2"
      :aria-labelledby="rulesId"
      data-testid="design-iteration-rules"
    >
      <h3 :id="rulesId" class="text-base font-semibold">{{ copy.rules }}</h3>
      <p class="text-sm text-on-night-3">{{ copy.rulesNote }}</p>
      <ul class="grid list-none gap-2">
        <li v-for="rule in assertions" :key="rule">
          <UiClaimFrame
            status="confirmed"
            :padded="false"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 pr-1.5 pl-3.5"
            data-testid="design-iteration-rule"
          >
            <span class="min-w-0 flex-1 text-sm leading-normal">{{ rule }}</span>
            <button
              type="button"
              class="inline-flex min-h-11 items-center rounded-pill px-3.5 text-[13px] font-medium text-on-night-2 transition-colors duration-150 hover:bg-night-hover hover:text-on-night disabled:cursor-not-allowed disabled:opacity-60"
              :aria-label="fill(copy.removeLabel, { rule })"
              :disabled="busy"
              data-testid="design-iteration-remove-rule"
              @click="emit('remove-assertion', rule)"
            >
              {{ copy.remove }}
            </button>
          </UiClaimFrame>
        </li>
      </ul>
    </section>

    <section v-if="items.length > 0" class="grid gap-2" data-testid="design-iteration-history">
      <button
        type="button"
        class="inline-flex min-h-11 items-center gap-2 justify-self-start text-left text-sm font-semibold text-on-night-2 transition-colors duration-150 hover:text-on-night"
        :aria-expanded="historyOpen ? 'true' : 'false'"
        :aria-controls="historyOpen ? historyId : undefined"
        data-testid="design-iteration-history-toggle"
        @click="historyOpen = !historyOpen"
      >
        <span
          aria-hidden="true"
          :class="[
            'inline-block transition-transform duration-150',
            historyOpen ? 'rotate-90' : '',
          ]"
          >›</span
        >
        {{ fill(copy.history, { n: items.length }) }}
      </button>
      <ol v-if="historyOpen" :id="historyId" class="grid list-none gap-2.5">
        <li
          v-for="entry in history"
          :key="entry.item.generation_id"
          class="grid gap-2 rounded-tile border border-night-line bg-night-raised p-4"
          :data-status="entry.item.status"
          data-testid="design-iteration-history-item"
        >
          <div class="flex flex-wrap items-center gap-2">
            <UiStatusChip :status="entry.chip" :label="entry.label" />
            <span v-if="entry.date" class="text-xs text-on-night-3">{{ entry.date }}</span>
          </div>
          <blockquote
            :class="[QUOTE_CLASS, 'text-[15px]']"
            data-testid="design-iteration-history-request"
          >
            {{ entry.item.request }}
          </blockquote>
          <div
            v-for="note in entry.notes"
            :key="note.key"
            class="grid gap-1"
            :data-testid="`design-iteration-history-${note.key}`"
          >
            <p class="text-xs font-semibold text-on-night-3">{{ note.title }}</p>
            <ul class="grid list-disc gap-1 pl-5 text-sm text-on-night-2">
              <li v-for="(line, index) in note.lines" :key="index">{{ line }}</li>
            </ul>
          </div>
        </li>
      </ol>
    </section>
  </section>
</template>
