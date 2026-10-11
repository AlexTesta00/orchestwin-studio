<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, reactive, ref, useId, watch } from "vue";

import { designCritiqueCopy } from "./designCritiqueCopy";
import { modelFeedback } from "./modelFeedback";
import { withScreenNames, type ScreenName } from "./screenNames";
import { fill, formatDate } from "./textFormat";
import UiClaimFrame from "./UiClaimFrame.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import type { DesignCritiqueApi } from "../api/designCritique";
import {
  critiqueFileProblem,
  useDesignCritiqueStore,
  type AuthorizedCritiqueRequest,
} from "../stores/designCritique";
import { generationFailureMessage } from "../stores/designMockupMessages";
import type {
  DesignCritiqueFindingPayload,
  DesignCritiqueRunPayload,
  DesignCritiqueShotPayload,
  DesignCritiqueSourcePayload,
  DesignCritiqueVerdict,
} from "../types/designCritique";
import type { SyntheticFindingSeverity } from "../types/designLoop";

type Locale = "en" | "it";

interface VerdictRow {
  twinId: string;
  name: string;
  verdict: DesignCritiqueVerdict;
}

interface ScreenView {
  key: string;
  label: string;
  shot: DesignCritiqueShotPayload;
  rows: VerdictRow[];
}

interface FindingView {
  key: string;
  severity: SyntheticFindingSeverity;
  summary: string;
  action: string;
  place: string | null;
}

interface TwinView {
  id: string;
  name: string;
  summary: string;
  findings: FindingView[];
  gaps: string[];
}

interface RunView {
  run: DesignCritiqueRunPayload;
  latest: boolean;
  title: string;
  meta: string;
  screens: ScreenView[];
  twins: TwinView[];
  cost: string;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale: Locale;
    authorize: AuthorizedCritiqueRequest;
    twinsReady?: boolean;
    redrawReady?: boolean;
    redrawBusy?: boolean;
    api?: DesignCritiqueApi | undefined;
  }>(),
  {
    twinsReady: true,
    redrawReady: false,
    redrawBusy: false,
    api: undefined,
  },
);

const emit = defineEmits<{
  redraw: [sourceId: string, title: string];
  critiqued: [run: DesignCritiqueRunPayload];
}>();

const VERDICTS: readonly DesignCritiqueVerdict[] = ["WORKS", "SLOWS", "BLOCKS"];

const SEVERITY_RANK: Record<SyntheticFindingSeverity, number> = {
  observation: 0,
  minor: 1,
  moderate: 2,
  major: 3,
  critical: 4,
};

const VERDICT_STYLES: Record<DesignCritiqueVerdict, string> = {
  WORKS: "bg-petrol-on-night/12 text-petrol-on-night-2",
  SLOWS: "bg-warn-on-night/12 text-warn-on-night",
  BLOCKS: "bg-fail-on-night/12 text-fail-on-night",
};

const SEVERITY_STYLES: Record<SyntheticFindingSeverity, string> = {
  critical: "bg-fail-on-night/12 text-fail-on-night",
  major: "bg-warn-on-night/12 text-warn-on-night",
  moderate: "bg-on-night/8 text-on-night-2",
  minor: "bg-on-night/8 text-on-night-2",
  observation: "bg-on-night/8 text-on-night-2",
};

const BADGE = "inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold";

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const store = useDesignCritiqueStore();

const copy = computed(() => designCritiqueCopy[props.locale]);
const tag = computed(() => (props.locale === "it" ? "it-IT" : "en-US"));

const fileId = useId();
const limitId = useId();
const fileErrorId = useId();
const titleId = useId();
const titleHintId = useId();
const askTimeId = useId();
const twinsMissingId = useId();
const resultId = useId();
const redrawTextId = useId();
const redrawTimeId = useId();
const redrawNoteId = useId();

const root = ref<HTMLDetailsElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const resultHeading = ref<HTMLElement | null>(null);
const opened = ref(false);
const file = ref<File | null>(null);
const fileProblem = ref<string | null>(null);
const title = ref("");
const receivedSeconds = ref<number | null>(null);
const shownId = ref<string | null>(null);
const shotUrls = reactive<Record<string, string>>({});
const shotsMissing = reactive<Record<string, boolean>>({});
const shotsLoading = new Set<string>();
let requested = false;
let alive = true;

const runs = computed(() => (store.projectId === props.projectId ? store.runs : []));
const shown = computed(
  () => runs.value.find((run) => run.id === shownId.value) ?? runs.value[0] ?? null,
);
const older = computed(() => runs.value.slice(1));
const busy = computed(() => store.pending.upload || store.pending.critique);

const canAsk = computed(
  () => file.value !== null && fileProblem.value === null && props.twinsReady && !busy.value,
);
const canRedraw = computed(() => props.redrawReady && !props.redrawBusy);

const fileDescribedBy = computed(() =>
  fileProblem.value === null ? limitId : `${limitId} ${fileErrorId}`,
);
const askDescribedBy = computed(() =>
  [
    askTimeId,
    props.twinsReady ? null : twinsMissingId,
    fileProblem.value === null ? null : fileErrorId,
  ]
    .filter((id): id is string => id !== null)
    .join(" "),
);
const redrawNote = computed(() => {
  if (!props.redrawReady) {
    return { text: copy.value.redrawMissing, testid: "design-critique-redraw-missing" };
  }
  return props.redrawBusy
    ? { text: copy.value.redrawBusy, testid: "design-critique-redraw-busy" }
    : null;
});
const redrawDescribedBy = computed(() =>
  [redrawTextId, redrawTimeId, redrawNote.value === null ? null : redrawNoteId]
    .filter((id): id is string => id !== null)
    .join(" "),
);

const statusText = computed(() => {
  if (store.pending.upload) {
    return copy.value.uploading;
  }
  if (store.pending.critique) {
    return copy.value.critiquing;
  }
  if (store.pending.load) {
    return copy.value.loading;
  }
  const seconds = receivedSeconds.value;
  return seconds === null ? "" : fill(copy.value.received, { seconds: count(seconds) });
});

const errorText = computed(() => {
  const failure = store.projectId === props.projectId ? store.error : null;
  return failure === null ? null : failureText(failure.code);
});

const view = computed<RunView | null>(() => {
  const run = shown.value;
  return run === null ? null : runView(run, run.id === runs.value[0]?.id);
});

function count(value: number): string {
  return new Intl.NumberFormat(tag.value).format(value);
}

function money(microusd: number): string {
  return new Intl.NumberFormat(tag.value, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(microusd / 1_000_000);
}

function failureText(code: string): string {
  const known: Readonly<Record<string, string>> = copy.value.errors;
  return (
    known[code] ?? modelFeedback(code, props.locale) ?? generationFailureMessage(code, props.locale)
  );
}

function secondsOf(run: DesignCritiqueRunPayload): number {
  const measured = Number.isFinite(run.duration_seconds)
    ? run.duration_seconds
    : (Date.parse(run.completed_at) - Date.parse(run.started_at)) / 1000;
  return Number.isFinite(measured) ? Math.max(0, Math.round(measured)) : 0;
}

function costText(run: DesignCritiqueRunPayload): string {
  const seconds = count(secondsOf(run));
  return run.cost_microusd > 0
    ? fill(copy.value.costPaid, { seconds, cost: money(run.cost_microusd) })
    : fill(copy.value.costSubscription, { seconds });
}

function screenLabel(
  source: DesignCritiqueSourcePayload,
  shot: DesignCritiqueShotPayload,
  index: number,
): string {
  if (source.kind === "IMAGE" && source.shots.length === 1) {
    return copy.value.supplied;
  }
  return shot.viewport_width === null
    ? fill(copy.value.screen, { n: index + 1 })
    : fill(copy.value.screenWidth, { n: index + 1, width: shot.viewport_width });
}

function shotKey(sourceId: string, code: string): string {
  return `${sourceId}|${code}`;
}

function derivedVerdict(findings: readonly DesignCritiqueFindingPayload[]): DesignCritiqueVerdict {
  const worst = Math.max(-1, ...findings.map((finding) => SEVERITY_RANK[finding.severity] ?? 0));
  return worst >= SEVERITY_RANK.major ? "BLOCKS" : worst >= SEVERITY_RANK.minor ? "SLOWS" : "WORKS";
}

function verdictOf(
  run: DesignCritiqueRunPayload,
  twinId: string,
  code: string,
): DesignCritiqueVerdict {
  const given = run.verdicts.find(
    (item) => item.twin_id === twinId && item.anchor_key === code,
  )?.verdict;
  if (given !== undefined && VERDICTS.includes(given)) {
    return given;
  }
  const findings = run.responses.find((response) => response.twin_id === twinId)?.findings ?? [];
  return derivedVerdict(findings.filter((finding) => finding.anchor_key === code));
}

function runView(run: DesignCritiqueRunPayload, latest: boolean): RunView {
  const source = run.source;
  const labels = source.shots.map((shot, index) => screenLabel(source, shot, index));
  const names: ScreenName[] = source.shots.map((shot, index) => ({
    code: shot.code,
    title: labels[index] ?? shot.code,
  }));
  const named = (text: string) => withScreenNames(text, { screens: names, locale: props.locale });
  const places = new Map(names.map((item) => [item.code, item.title]));
  const twins = run.twins.map((twin) => ({
    id: twin.twin_id,
    name: twin.name.trim() || copy.value.someone,
  }));
  const meta = [copy.value.kinds[source.kind], source.url, formatDate(run.completed_at, tag.value)]
    .filter((part): part is string => typeof part === "string" && part.length > 0)
    .join(" · ");
  return {
    run,
    latest,
    title: source.title,
    meta,
    screens: source.shots.map((shot, index) => ({
      key: shotKey(source.id, shot.code),
      label: labels[index] ?? shot.code,
      shot,
      rows: twins.map((twin) => ({
        twinId: twin.id,
        name: twin.name,
        verdict: verdictOf(run, twin.id, shot.code),
      })),
    })),
    twins: twins.map((twin) => {
      const response = run.responses.find((item) => item.twin_id === twin.id) ?? null;
      return {
        id: twin.id,
        name: twin.name,
        summary: named(response?.summary ?? ""),
        findings: (response?.findings ?? []).map((finding) => ({
          key: `${twin.id}:${finding.finding_id}`,
          severity: finding.severity,
          summary: named(finding.summary),
          action: named(finding.recommended_action),
          place: source.shots.length > 1 ? (places.get(finding.anchor_key) ?? null) : null,
        })),
        gaps: (response?.evidence_gaps ?? [])
          .map((gap) => named(gap.trim()))
          .filter((gap) => gap.length > 0),
      };
    }),
    cost: costText(run),
  };
}

function buttonClasses(enabled: boolean): string[] {
  return [
    "inline-flex min-h-11 items-center justify-center rounded-pill px-5 py-2.5 text-sm font-semibold transition-colors duration-150",
    enabled
      ? "bg-on-night text-ink hover:bg-petrol-on-night-2"
      : "cursor-not-allowed bg-night-hover text-on-night-3",
  ];
}

async function loadRuns(): Promise<void> {
  requested = true;
  try {
    await store.load(props.projectId, props.authorize, props.api);
  } catch {
    requested = false;
  }
}

function onToggle(): void {
  opened.value = root.value?.open === true;
  if (opened.value && !requested) {
    void loadRuns();
  }
}

function onFile(event: Event): void {
  const chosen = (event.target as HTMLInputElement).files?.[0] ?? null;
  file.value = chosen;
  fileProblem.value = chosen === null ? null : critiqueFileProblem(chosen);
  receivedSeconds.value = null;
}

function clearForm(): void {
  file.value = null;
  fileProblem.value = null;
  title.value = "";
  if (fileInput.value !== null) {
    fileInput.value.value = "";
  }
}

async function focusResult(): Promise<void> {
  await nextTick();
  resultHeading.value?.focus();
}

async function ask(): Promise<void> {
  const chosen = file.value;
  if (!canAsk.value || chosen === null) {
    return;
  }
  receivedSeconds.value = null;
  let run: DesignCritiqueRunPayload;
  try {
    run = await store.critiqueImage(
      props.projectId,
      chosen,
      title.value,
      tag.value,
      props.authorize,
      props.api,
    );
  } catch {
    return;
  }
  if (!alive) {
    return;
  }
  receivedSeconds.value = secondsOf(run);
  shownId.value = null;
  clearForm();
  emit("critiqued", run);
  await focusResult();
}

async function show(id: string | null): Promise<void> {
  shownId.value = id;
  await focusResult();
}

function redraw(run: DesignCritiqueRunPayload): void {
  if (canRedraw.value) {
    emit("redraw", run.source.id, run.source.title);
  }
}

async function loadShot(sourceId: string, code: string): Promise<void> {
  const key = shotKey(sourceId, code);
  if (key in shotUrls || shotsMissing[key] === true || shotsLoading.has(key)) {
    return;
  }
  const project = props.projectId;
  shotsLoading.add(key);
  try {
    const url = await store.shotUrl(project, sourceId, code, props.authorize, props.api);
    if (alive && project === props.projectId) {
      shotUrls[key] = url;
    }
  } catch {
    if (alive && project === props.projectId) {
      shotsMissing[key] = true;
    }
  } finally {
    shotsLoading.delete(key);
  }
}

function forgetShots(): void {
  for (const key of Object.keys(shotUrls)) {
    delete shotUrls[key];
  }
  for (const key of Object.keys(shotsMissing)) {
    delete shotsMissing[key];
  }
  shotsLoading.clear();
}

watch(
  () => [opened.value, shown.value] as const,
  ([open, run]) => {
    if (!open || run === null) {
      return;
    }
    for (const shot of run.source.shots) {
      void loadShot(run.source.id, shot.code);
    }
  },
);

watch(
  () => props.projectId,
  () => {
    requested = false;
    shownId.value = null;
    receivedSeconds.value = null;
    clearForm();
    forgetShots();
    store.reset();
    if (opened.value) {
      void loadRuns();
    }
  },
);

onBeforeUnmount(() => {
  alive = false;
  forgetShots();
  store.revokeShotUrls();
});
</script>

<template>
  <details
    ref="root"
    class="group/critique rounded-tile border border-night-line bg-night-raised text-on-night"
    data-surface="night"
    data-testid="design-critique"
    @toggle="onToggle"
  >
    <summary
      class="flex min-h-12 cursor-pointer list-none items-center gap-3 px-5 py-3 [&::-webkit-details-marker]:hidden"
      data-testid="design-critique-summary"
    >
      <span
        class="inline-block text-xs text-on-night-3 group-open/critique:rotate-90"
        aria-hidden="true"
        >▸</span
      >
      <span class="text-[15px] font-semibold">{{ copy.title }}</span>
    </summary>
    <div class="grid gap-5 border-t border-night-line px-5 py-4">
      <p class="m-0 max-w-2xl text-sm leading-normal text-on-night-2">{{ copy.intro }}</p>

      <div class="grid gap-4">
        <div class="grid gap-1.5">
          <label :for="fileId" class="text-sm font-semibold">{{ copy.file }}</label>
          <input
            :id="fileId"
            ref="fileInput"
            type="file"
            accept="image/png,image/jpeg"
            :aria-describedby="fileDescribedBy"
            :aria-invalid="fileProblem === null ? undefined : 'true'"
            :disabled="busy"
            class="min-h-11 w-full max-w-md min-w-0 text-sm text-on-night-2 file:mr-3 file:min-h-11 file:rounded-pill file:border file:border-night-line-strong file:bg-night-raised file:px-4 file:py-2 file:text-sm file:font-semibold file:text-on-night"
            data-testid="design-critique-file"
            @change="onFile"
          />
          <p :id="limitId" class="m-0 text-xs text-on-night-3" data-testid="design-critique-limit">
            {{ copy.limit }}
          </p>
          <p
            v-if="fileProblem !== null"
            :id="fileErrorId"
            class="m-0 text-sm leading-normal text-fail-on-night"
            role="alert"
            data-testid="design-critique-file-error"
          >
            {{ failureText(fileProblem) }}
          </p>
        </div>

        <div class="grid gap-1.5">
          <label :for="titleId" class="text-sm font-semibold">{{ copy.titleLabel }}</label>
          <input
            :id="titleId"
            v-model="title"
            type="text"
            maxlength="200"
            :aria-describedby="titleHintId"
            :disabled="busy"
            class="min-h-11 w-full max-w-md rounded-field border border-night-line-strong bg-night-panel px-3 py-2.5 text-[15px] text-on-night"
            data-testid="design-critique-title"
          />
          <p :id="titleHintId" class="m-0 text-xs text-on-night-3">{{ copy.titleHint }}</p>
        </div>

        <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <button
            type="button"
            :class="buttonClasses(canAsk)"
            :aria-disabled="canAsk ? undefined : 'true'"
            :aria-describedby="askDescribedBy"
            data-testid="design-critique-ask"
            @click="ask"
          >
            {{ copy.ask }}
          </button>
          <p
            :id="askTimeId"
            class="m-0 text-[13px] text-on-night-3"
            data-testid="design-critique-ask-time"
          >
            {{ copy.askTime }}
          </p>
        </div>
        <p
          v-if="!twinsReady"
          :id="twinsMissingId"
          class="m-0 text-sm leading-normal text-warn-on-night"
          data-testid="design-critique-twins-missing"
        >
          {{ copy.twinsMissing }}
        </p>
      </div>

      <p
        :class="[
          'm-0 text-sm leading-normal text-on-night-2',
          busy || statusText.length > 0 ? 'flex items-center gap-3' : 'sr-only',
        ]"
        role="status"
        aria-live="polite"
        data-testid="design-critique-status"
      >
        <span
          v-if="busy"
          class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
          aria-hidden="true"
        />
        <span v-if="statusText.length > 0">{{ statusText }}</span>
      </p>
      <p
        v-if="errorText !== null"
        class="m-0 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm leading-normal text-fail-on-night"
        role="alert"
        data-testid="design-critique-error"
      >
        {{ errorText }}
      </p>

      <article
        v-if="view !== null"
        class="grid gap-5 rounded-field border border-night-line-strong p-4"
        :aria-labelledby="resultId"
        data-testid="design-critique-run"
      >
        <header class="grid gap-1">
          <h3
            :id="resultId"
            ref="resultHeading"
            tabindex="-1"
            class="m-0 text-base font-semibold break-words"
          >
            {{ view.title }}
          </h3>
          <p class="m-0 text-[13px] break-words text-on-night-3" data-testid="design-critique-meta">
            {{ view.meta }}
          </p>
          <button
            v-if="!view.latest"
            type="button"
            class="inline-flex min-h-11 items-center self-start text-left text-[13px] font-medium text-petrol-on-night-2 underline underline-offset-4 transition-colors duration-150 hover:text-on-night"
            data-testid="design-critique-latest"
            @click="show(null)"
          >
            {{ copy.latest }}
          </button>
        </header>
        <p class="m-0 text-xs leading-normal text-violet-on-night-2">{{ copy.note }}</p>

        <ul class="m-0 grid list-none gap-5 p-0">
          <li
            v-for="screen in view.screens"
            :key="screen.key"
            class="grid gap-2.5"
            data-testid="design-critique-screen"
          >
            <h4 class="m-0 text-sm font-semibold" data-testid="design-critique-screen-label">
              {{ screen.label }}
            </h4>
            <img
              v-if="shotUrls[screen.key] !== undefined"
              :src="shotUrls[screen.key]"
              :alt="fill(copy.shotAlt, { title: view.title, screen: screen.label })"
              :width="screen.shot.width"
              :height="screen.shot.height"
              decoding="async"
              class="h-auto max-h-96 w-auto max-w-full justify-self-start rounded-field border border-night-line object-contain"
              data-testid="design-critique-shot"
            />
            <p
              v-else-if="shotsMissing[screen.key] === true"
              class="m-0 text-[13px] text-on-night-3"
              data-testid="design-critique-shot-missing"
            >
              {{ copy.shotMissing }}
            </p>
            <ul
              class="m-0 grid list-none gap-1.5 p-0"
              :aria-label="fill(copy.verdictsOn, { screen: screen.label })"
            >
              <li
                v-for="row in screen.rows"
                :key="row.twinId"
                class="flex flex-wrap items-center gap-2 text-sm"
              >
                <span class="font-semibold" data-testid="design-critique-verdict-twin">{{
                  row.name
                }}</span>
                <span class="sr-only">: </span>
                <span
                  :class="[BADGE, VERDICT_STYLES[row.verdict]]"
                  :data-verdict="row.verdict"
                  data-testid="design-critique-verdict"
                >
                  {{ copy.verdicts[row.verdict] }}
                </span>
              </li>
            </ul>
          </li>
        </ul>

        <ul class="m-0 grid list-none gap-3 p-0">
          <li v-for="twin in view.twins" :key="twin.id" data-testid="design-critique-twin">
            <UiClaimFrame status="hypothesis" radius="tile" :padded="false" class="grid gap-3 p-4">
              <h4 class="m-0 text-[15px] font-semibold" data-testid="design-critique-twin-name">
                {{ twin.name }}
              </h4>
              <p
                v-if="twin.summary.length > 0"
                class="m-0 text-sm leading-normal text-on-night"
                data-testid="design-critique-twin-summary"
              >
                {{ twin.summary }}
              </p>
              <p v-if="twin.findings.length === 0" class="m-0 text-sm text-on-night-3">
                {{ copy.noFindings }}
              </p>
              <ul v-else class="m-0 grid list-none gap-3 p-0">
                <li
                  v-for="finding in twin.findings"
                  :key="finding.key"
                  class="grid gap-1"
                  :data-severity="finding.severity"
                  data-testid="design-critique-finding"
                >
                  <div class="flex flex-wrap items-center gap-2">
                    <span
                      :class="[BADGE, SEVERITY_STYLES[finding.severity]]"
                      data-testid="design-critique-severity"
                    >
                      {{ copy.severity[finding.severity] }}
                    </span>
                    <span
                      v-if="finding.place !== null"
                      class="text-xs text-on-night-3"
                      data-testid="design-critique-place"
                    >
                      {{ finding.place }}
                    </span>
                  </div>
                  <p
                    class="m-0 text-sm leading-normal font-semibold"
                    data-testid="design-critique-finding-summary"
                  >
                    {{ finding.summary }}
                  </p>
                  <p
                    class="m-0 text-sm leading-normal text-on-night-2"
                    data-testid="design-critique-action"
                  >
                    <strong class="font-semibold text-on-night">{{ copy.todo }}:</strong>
                    {{ finding.action }}
                  </p>
                </li>
              </ul>
              <div
                v-if="twin.gaps.length > 0"
                class="grid gap-1"
                data-testid="design-critique-gaps"
              >
                <p class="m-0 text-xs font-semibold text-on-night-3">{{ copy.gaps }}</p>
                <ul class="m-0 grid list-disc gap-0.5 pl-5 text-xs leading-normal text-on-night-3">
                  <li v-for="gap in twin.gaps" :key="gap">{{ gap }}</li>
                </ul>
              </div>
            </UiClaimFrame>
          </li>
        </ul>

        <p class="m-0 text-[13px] text-on-night-3" data-testid="design-critique-cost">
          {{ view.cost }}
        </p>

        <div class="grid gap-2 border-t border-night-line pt-4">
          <p :id="redrawTextId" class="m-0 text-sm leading-normal text-on-night-2">
            {{ copy.redrawText }}
          </p>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <button
              type="button"
              :class="buttonClasses(canRedraw)"
              :aria-disabled="canRedraw ? undefined : 'true'"
              :aria-describedby="redrawDescribedBy"
              data-testid="design-critique-redraw"
              @click="redraw(view.run)"
            >
              {{ copy.redraw }}
            </button>
            <p
              :id="redrawTimeId"
              class="m-0 text-[13px] text-on-night-3"
              data-testid="design-critique-redraw-time"
            >
              {{ copy.redrawTime }}
            </p>
          </div>
          <p
            v-if="redrawNote !== null"
            :id="redrawNoteId"
            class="m-0 text-[13px] leading-normal text-warn-on-night"
            :data-testid="redrawNote.testid"
          >
            {{ redrawNote.text }}
          </p>
        </div>
      </article>

      <details
        v-if="older.length > 0"
        class="group/history rounded-field border border-night-line"
        data-testid="design-critique-history"
      >
        <summary
          class="flex min-h-11 cursor-pointer list-none items-center gap-3 px-4 py-2 [&::-webkit-details-marker]:hidden"
          data-testid="design-critique-history-summary"
        >
          <span
            class="inline-block text-xs text-on-night-3 group-open/history:rotate-90"
            aria-hidden="true"
            >▸</span
          >
          <span class="text-sm font-semibold">{{ fill(copy.history, { n: older.length }) }}</span>
        </summary>
        <ul class="m-0 grid list-none gap-1 border-t border-night-line p-2">
          <li v-for="run in older" :key="run.id">
            <button
              type="button"
              :class="[
                'flex min-h-11 w-full items-center rounded-control px-3 py-2 text-left text-sm transition-colors duration-150',
                run.id === shown?.id
                  ? 'bg-on-night text-ink'
                  : 'text-on-night hover:bg-night-hover',
              ]"
              :aria-current="run.id === shown?.id ? 'true' : undefined"
              data-testid="design-critique-history-item"
              @click="show(run.id)"
            >
              <span class="min-w-0 break-words">
                {{ run.source.title }} · {{ formatDate(run.completed_at, tag) }}
              </span>
            </button>
          </li>
        </ul>
      </details>
    </div>
  </details>
</template>
