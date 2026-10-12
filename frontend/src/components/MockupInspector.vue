<script lang="ts">
export {
  changeTarget,
  describeElement,
  elementText,
  markedElements,
  requirementsOf,
  screenElements,
  visibleScreen,
} from "./mockupElements";
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";

import { correctionLines, generationFailureText } from "./iterationMessages";
import MockupChangeOpinions from "./MockupChangeOpinions.vue";
import {
  changeTarget,
  clip,
  codeOf,
  describeElement,
  isElement,
  MARKED,
  screenElements,
  type InspectorBox,
  type InspectorElement,
  type InspectorHighlight,
} from "./mockupElements";
import { mockupInspectorCopy } from "./mockupInspectorCopy";
import { modelFeedback } from "./modelFeedback";
import { elementNames, withScreenNames } from "./screenNames";
import { fill, plural } from "./textFormat";
import UiStateBlock from "./UiStateBlock.vue";
import { VERDICT_STYLES } from "./verdictStyles";
import { designApi as defaultDesignApi, type DesignApi } from "../api/design";
import {
  designIterationsApi,
  type DesignChangeTarget,
  type DesignIterationsApi,
} from "../api/designIterations";
import { designLoopApi, type DesignEvaluationScope, type DesignLoopApi } from "../api/designLoop";
import { designMockupsApi, type DesignMockupsApi } from "../api/designMockups";
import { designOpinionsApi, type DesignOpinionsApi } from "../api/designOpinions";
import { useIntlFormats } from "../composables/useIntlFormats";
import { useDesignStore } from "../stores/design";
import {
  DESIGN_CONTEXT_CHANGED,
  ITERATION_REQUEST_LIMIT,
  TARGET_PARTS_LIMIT,
  targetCodes,
  useDesignIterationsStore,
  type IterationOutcome,
  type IterationStartOptions,
} from "../stores/designIterations";
import {
  findingElement,
  REVIEWER_NOT_CONFIGURED,
  runMode,
  useDesignLoopStore,
} from "../stores/designLoop";
import { generationFailureMessage, type AuthorizedMockupRequest } from "../stores/designMockups";
import { CHANGE_OPINION_FAILED, useDesignOpinionsStore } from "../stores/designOpinions";
import type { DesignPackagePayload, DesignPackageVersionPayload } from "../types/design";
import type {
  DesignEvaluationRunPayload,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "../types/designLoop";
import type {
  ChangeOpinion,
  ChangeOpinionRun,
  ChangeOpinionVerdict,
} from "../types/designOpinions";

type Locale = "en" | "it";
type FailureTitle = "rejected" | "failed" | "start";
type Unapplied = "stale" | "pending" | "unchanged" | "recorded" | "failed" | "context";
type PartSubject = "element" | "zone" | "parts";
type Subject = "screen" | PartSubject;
type AppliedVersion = Pick<DesignPackageVersionPayload, "id" | "content_hash">;

type Outcome =
  | { kind: "ready" }
  | { kind: "applied" }
  | { kind: "unapplied"; reason: Unapplied }
  | { kind: "opinion"; code: string }
  | { kind: "error"; title: FailureTitle | null; code: string };

type Review =
  | { kind: "running"; scope: DesignEvaluationScope }
  | { kind: "done"; scope: DesignEvaluationScope; run: DesignEvaluationRunPayload }
  | { kind: "failed"; code: string };

interface Notice {
  kind: "loading" | "error" | "success";
  title: string;
  text: string;
}

interface TwinNote {
  key: string;
  twin: string;
  verdict: ChangeOpinionVerdict;
  summary: string;
  action: string;
}

const props = withDefaults(
  defineProps<{
    frame: HTMLIFrameElement | null;
    loads: number;
    screen: string | null;
    locale: Locale;
    screens?: readonly { code: string; title: string }[] | undefined;
    authorize?: AuthorizedMockupRequest | undefined;
    api?: DesignIterationsApi | undefined;
    mockupsApi?: DesignMockupsApi | undefined;
    designApi?: DesignApi | undefined;
    loopApi?: DesignLoopApi | undefined;
    opinionsApi?: DesignOpinionsApi | undefined;
    signal?: AbortSignal | undefined;
  }>(),
  {
    screens: () => [],
    authorize: undefined,
    api: undefined,
    mockupsApi: undefined,
    designApi: undefined,
    loopApi: undefined,
    opinionsApi: undefined,
    signal: undefined,
  },
);

const emit = defineEmits<{
  highlight: [value: InspectorHighlight];
  version: [screen: string];
  applied: [versionId: string];
}>();

const REVEAL_MARGIN = 16;
const HELD_PREVIEW = 3;
const ZONE_PREFIX = "ZON-";
const REVIEW_BUSY = "DESIGN_REVIEW_BUSY";
const REVIEW_FAILED = "DESIGN_LOOP_REQUEST_FAILED";
const SECONDARY_BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-pill border px-4 py-2 text-sm font-semibold transition-colors duration-150";

const VERDICTS: Record<SyntheticFindingSeverity, ChangeOpinionVerdict> = {
  observation: "HELPS",
  minor: "SLOWS",
  moderate: "SLOWS",
  major: "BLOCKS",
  critical: "BLOCKS",
};

const iterations = useDesignIterationsStore();
const design = useDesignStore();
const loop = useDesignLoopStore();
const opinions = useDesignOpinionsStore();

const copy = computed(() => mockupInspectorCopy[props.locale]);
const modelLocale = computed(() => (props.locale === "it" ? "it-IT" : "en-US"));
const { listFormat } = useIntlFormats(() => (props.locale === "it" ? "it-IT" : "en-GB"));

const titleId = useId();
const multiHintId = useId();
const selectionId = useId();
const parentId = useId();
const fieldId = useId();
const countId = useId();
const estimateId = useId();
const pendingId = useId();
const optionPrefix = useId();
const notesId = useId();
const versionNoteId = useId();
const correctionsId = useId();
const askTimeId = useId();
const askFirstTimeId = useId();

const list = ref<HTMLElement | null>(null);
const partList = ref<HTMLElement | null>(null);
const parentButton = ref<HTMLElement | null>(null);
const field = ref<HTMLTextAreaElement | null>(null);
const items = ref<InspectorElement[]>([]);
const ready = ref(false);
const hovered = ref<string | null>(null);
const picked = ref<InspectorElement[]>([]);
const latest = ref<string | null>(null);
const multi = ref(false);
const active = ref(0);
const request = ref("");
const review = ref(true);
const sending = ref(false);
const asked = ref<string | null>(null);
const outcome = ref<Outcome | null>(null);
const announcement = ref("");
const applying = ref(false);
const reviewState = ref<Review | null>(null);
const appliedVersion = ref<AppliedVersion | null>(null);

let page: Document | null = null;
let detach: (() => void) | null = null;

const byCode = computed(() => new Map(items.value.map((item) => [item.code, item])));

const parts = computed(() => (items.value.length > 0 ? picked.value : []));

const selected = computed(() => parts.value.map((part) => part.code));

const chosen = computed(() => (parts.value.length === 1 ? (parts.value[0] ?? null) : null));

const subject = computed(() => partSubject(selected.value));

const target = computed(() => changeTarget(parts.value));

const multiselectable = computed(() => multi.value || selected.value.length > 1);

const anchor = computed(
  () => parts.value.find((part) => part.code === latest.value) ?? parts.value.at(-1) ?? null,
);

const container = computed(() => {
  const code = anchor.value?.parent ?? null;
  return code === null ? null : (byCode.value.get(code) ?? null);
});

const held = computed(() =>
  (chosen.value?.holds ?? [])
    .slice(0, HELD_PREVIEW)
    .flatMap((code) => byCode.value.get(code) ?? []),
);

const requirements = computed(() => [...new Set(parts.value.flatMap((part) => part.requirements))]);

const length = computed(() => [...request.value].length);

const drawing = computed(() => iterations.state === "drawing" || iterations.starting);

const waiting = computed(() => iterations.state === "ready");

const pending = computed(() => waiting.value && outcome.value?.kind !== "ready");

const requestReady = computed(
  () =>
    parts.value.length > 0 &&
    request.value.trim().length > 0 &&
    length.value <= ITERATION_REQUEST_LIMIT &&
    props.authorize !== undefined,
);

const idle = computed(() => !sending.value && !drawing.value && !waiting.value && !applying.value);

const canApply = computed(() => requestReady.value && idle.value);

const estimate = computed(() => (review.value ? copy.value.estimateReview : copy.value.estimate));

const applyClasses = computed(() => buttonClasses(canApply.value));

const proposal = computed(() => (waiting.value ? iterations.result : null));

const corrections = computed(() =>
  correctionLines(proposal.value?.corrections ?? [], props.locale),
);

const reviewing = computed(() => reviewState.value?.kind === "running");

const project = computed(() => iterations.projectId ?? design.projectId);

const currentVersion = computed<AppliedVersion | null>(() => {
  const current = design.current;
  if (current !== null && current.project_id === project.value) {
    return { id: current.id, content_hash: current.content_hash };
  }
  const context = iterations.design;
  return context === null
    ? appliedVersion.value
    : { id: context.versionId, content_hash: context.contentHash };
});

const canAskFirst = computed(
  () =>
    requestReady.value &&
    idle.value &&
    !reviewing.value &&
    !opinions.busy &&
    currentVersion.value !== null &&
    project.value !== null,
);

const opinionStale = computed(() => {
  const version = currentVersion.value;
  const value = target.value;
  return version === null || value === null || opinions.isStale(version, value, request.value);
});

const freshOpinion = computed(() => (opinionStale.value ? null : opinions.current));

const opinionRun = computed<ChangeOpinionRun | null>(() => {
  const run = opinions.current;
  return run === null ? null : { ...run, opinions: run.opinions.map(namedOpinion) };
});

const selectedScope = computed<DesignEvaluationScope | null>(() => {
  const screen = parts.value[0]?.screen ?? null;
  return screen === null ? null : scopeFor(screen, selected.value);
});

const plannedScope = computed(() => scopeOf(iterations.request?.target) ?? selectedScope.value);

const canApplyVersion = computed(
  () =>
    proposal.value !== null &&
    props.authorize !== undefined &&
    !applying.value &&
    !reviewing.value &&
    !design.isBusy,
);

const versionClasses = computed(() => buttonClasses(canApplyVersion.value));

const versionNote = computed(() => {
  const scope = plannedScope.value;
  return review.value && scope !== null
    ? fill(copy.value.versionReview, { code: scopeCode(scope) })
    : copy.value.versionAlone;
});

const showAsk = computed(
  () => parts.value.length > 0 && (!review.value || reviewState.value?.kind === "failed"),
);

const canAsk = computed(
  () =>
    showAsk.value &&
    selectedScope.value !== null &&
    currentVersion.value !== null &&
    project.value !== null &&
    props.authorize !== undefined &&
    !applying.value &&
    !reviewing.value &&
    !drawing.value &&
    !waiting.value &&
    !loop.isBusy,
);

const askClasses = computed(() => secondaryClasses(canAsk.value));

const twinNames = computed<Record<string, string>>(() =>
  Object.fromEntries(
    (design.current?.package.grounding.user_twin_references ?? []).map((item) => [
      item.twin_id,
      item.name,
    ]),
  ),
);

const elementLabels = computed<Record<string, string>>(() =>
  Object.fromEntries(
    items.value.filter((item) => item.label.length > 0).map((item) => [item.code, item.label]),
  ),
);

const reviewRuns = computed<DesignEvaluationRunPayload[]>(() => {
  const version = currentVersion.value;
  if (version === null) {
    return [];
  }
  const own = reviewState.value?.kind === "done" ? [reviewState.value.run] : [];
  const known = loop.projectId === project.value ? loop.runs : [];
  return [...own, ...known.filter((run) => !own.some((item) => item.id === run.id))].filter(
    (run) =>
      runMode(run) === "TWIN_REVIEW" &&
      run.design_version_id === version.id &&
      run.design_content_hash === version.content_hash,
  );
});

const notes = computed<TwinNote[]>(() => {
  for (const run of reviewRuns.value) {
    const found = run.responses.flatMap((response) =>
      response.findings.filter((finding) => aboutAny(finding, selected.value)),
    );
    if (found.length > 0) {
      return found.map((finding) => twinNote(finding));
    }
  }
  return [];
});

const reviewNotice = computed<Notice | null>(() => {
  const state = reviewState.value;
  if (state === null) {
    return null;
  }
  if (state.kind === "running") {
    return {
      kind: "loading",
      title: copy.value.reviewing[subjectOf(state.scope)],
      text: copy.value.reviewTime,
    };
  }
  if (state.kind === "failed") {
    return { kind: "error", title: copy.value.reviewFailed, text: reviewFailure(state.code) };
  }
  return { kind: "success", title: reviewedText(state.scope, state.run), text: "" };
});

const screenLabel = computed(() => {
  const code = parts.value[0]?.screen ?? null;
  if (code === null) {
    return "";
  }
  const title = props.screens.find((screen) => screen.code === code)?.title;
  return title === undefined ? code : `${code} · ${title}`;
});

const stage = computed(() => {
  const value = iterations.job?.stage ?? null;
  return value === null ? copy.value.stages.none : copy.value.stages[value];
});

const notice = computed<Notice | null>(() => {
  if (drawing.value) {
    return { kind: "loading", title: stage.value, text: copy.value.drawing };
  }
  const value = outcome.value;
  if (value === null) {
    return null;
  }
  if (value.kind === "ready") {
    return { kind: "success", title: copy.value.ready, text: "" };
  }
  if (value.kind === "applied") {
    return { kind: "success", title: copy.value.applied, text: "" };
  }
  if (value.kind === "unapplied") {
    return { kind: "error", title: copy.value.failures.apply, text: unappliedText(value.reason) };
  }
  if (value.kind === "opinion") {
    return { kind: "error", title: copy.value.reviewFailed, text: reviewFailure(value.code) };
  }
  const reason = generationFailureText(value.code, props.locale);
  return value.title === null
    ? { kind: "error", title: reason, text: "" }
    : { kind: "error", title: copy.value.failures[value.title], text: reason };
});

function shown(item: InspectorElement): string {
  return item.label || copy.value.noText;
}

function partKind(item: InspectorElement): string {
  return item.zoneKind === undefined
    ? item.tag
    : `${copy.value.zoneKinds[item.zoneKind]}, ${plural(item.holds.length, copy.value.elements)}`;
}

function optionLabel(item: InspectorElement): string {
  return [item.code, partKind(item), shown(item)].join(", ");
}

function isPicked(item: InspectorElement): boolean {
  return selected.value.includes(item.code);
}

function withPending(id: string): string {
  return pending.value ? `${id} ${pendingId}` : id;
}

function buttonClasses(enabled: boolean): string[] {
  return [
    "inline-flex min-h-11 items-center justify-center rounded-pill px-5 py-2.5 text-sm font-semibold transition-colors duration-150",
    enabled
      ? "bg-on-night text-ink hover:bg-petrol-on-night-2"
      : "cursor-not-allowed bg-night-hover text-on-night-3",
  ];
}

function secondaryClasses(enabled: boolean): string[] {
  return [
    SECONDARY_BUTTON,
    enabled
      ? "border-night-line-strong text-on-night hover:bg-night-hover"
      : "cursor-not-allowed border-night-line text-on-night-3",
  ];
}

function partSubject(codes: readonly string[]): PartSubject {
  if (codes.length > 1) {
    return "parts";
  }
  return codes[0]?.startsWith(ZONE_PREFIX) === true ? "zone" : "element";
}

function scopeFor(screen: string, codes: readonly string[]): DesignEvaluationScope {
  const [code, ...others] = codes;
  if (code === undefined) {
    return { screen_code: screen };
  }
  return others.length === 0
    ? { screen_code: screen, element_code: code }
    : { screen_code: screen, element_codes: [...codes] };
}

function scopeOf(target: DesignChangeTarget | undefined): DesignEvaluationScope | null {
  return target === undefined ? null : scopeFor(target.screen_code, targetCodes(target));
}

function scopeCodes(scope: DesignEvaluationScope): string[] {
  return scope.element_codes ?? (scope.element_code === undefined ? [] : [scope.element_code]);
}

function scopeCode(scope: DesignEvaluationScope): string {
  const codes = scopeCodes(scope);
  return codes.length === 0 ? scope.screen_code : listFormat.value.format(codes);
}

function subjectOf(scope: DesignEvaluationScope): Subject {
  const codes = scopeCodes(scope);
  return codes.length === 0 ? "screen" : partSubject(codes);
}

function aboutAny(finding: SyntheticFindingPayload, codes: readonly string[]): boolean {
  const code = findingElement(finding);
  return code !== null && codes.includes(code);
}

function unappliedText(reason: Unapplied): string {
  return reason === "context"
    ? generationFailureText(DESIGN_CONTEXT_CHANGED, props.locale)
    : copy.value.unapplied[reason];
}

function reviewFailure(code: string): string {
  if (code === REVIEW_BUSY) {
    return copy.value.reviewBusy;
  }
  if (code === REVIEWER_NOT_CONFIGURED) {
    return copy.value.reviewerMissing;
  }
  return modelFeedback(code, props.locale) ?? generationFailureMessage(code, props.locale);
}

function reviewedText(scope: DesignEvaluationScope, run: DesignEvaluationRunPayload): string {
  const codes = scopeCodes(scope);
  const about = subjectOf(scope);
  const noted = run.responses.some((response) =>
    response.findings.some((finding) => aboutAny(finding, codes)),
  );
  const template =
    about === "screen" || noted ? copy.value.reviewed[about] : copy.value.reviewedNone;
  return fill(template, { code: scopeCode(scope) });
}

function named(text: string, places: readonly string[] = []): string {
  return withScreenNames(text, {
    screens: props.screens,
    elements: { ...elementNames(places), ...elementLabels.value },
    locale: props.locale,
  });
}

function twinNote(finding: SyntheticFindingPayload): TwinNote {
  return {
    key: `${finding.twin_id}:${finding.finding_id}`,
    twin: twinNames.value[finding.twin_id] ?? finding.twin_id.slice(0, 8),
    verdict: VERDICTS[finding.severity],
    summary: named(finding.summary, [finding.location]),
    action: named(finding.recommended_action, [finding.location]),
  };
}

function namedOpinion(opinion: ChangeOpinion): ChangeOpinion {
  return {
    ...opinion,
    why: named(opinion.why),
    what_to_do: named(opinion.what_to_do),
    try_this: opinion.try_this === null ? null : named(opinion.try_this),
  };
}

function samePackage(left: DesignPackagePayload, right: DesignPackagePayload): boolean {
  return (
    left.owner_selected_alternative_id === right.owner_selected_alternative_id &&
    JSON.stringify(left.generated_mockup ?? null) ===
      JSON.stringify(right.generated_mockup ?? null) &&
    JSON.stringify(left.prototype) === JSON.stringify(right.prototype) &&
    JSON.stringify(left.owner_assertions ?? []) === JSON.stringify(right.owner_assertions ?? [])
  );
}

function elementOf(target: EventTarget | null): Element | null {
  const node = target as Node | null;
  if (node === null || typeof node.nodeType !== "number") {
    return null;
  }
  return isElement(node) ? node : node.parentElement;
}

function codeAt(target: EventTarget | null): string | null {
  const marked = elementOf(target)?.closest(MARKED) ?? null;
  const code = marked === null ? null : codeOf(marked);
  return code !== null && byCode.value.has(code) ? code : null;
}

function boxOf(code: string): InspectorBox | null {
  const element = byCode.value.get(code)?.node;
  if (element === undefined) {
    return null;
  }
  const rect = element.getBoundingClientRect();
  return { code, left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function publish(): void {
  const hover = hovered.value;
  emit("highlight", {
    hover: hover === null || selected.value.includes(hover) ? null : boxOf(hover),
    selected: selected.value.flatMap((code) => boxOf(code) ?? []),
  });
}

function options(): HTMLElement[] {
  return [...(list.value?.querySelectorAll<HTMLElement>("[role='option']") ?? [])];
}

function showOption(index: number): void {
  const container = list.value;
  const option = options()[index];
  if (container === null || option === undefined) {
    return;
  }
  if (option.offsetTop < container.scrollTop) {
    container.scrollTop = option.offsetTop;
  } else if (
    option.offsetTop + option.offsetHeight >
    container.scrollTop + container.clientHeight
  ) {
    container.scrollTop = option.offsetTop + option.offsetHeight - container.clientHeight;
  }
}

function reveal(code: string): void {
  const element = byCode.value.get(code)?.node;
  const view = page?.defaultView ?? null;
  if (element === undefined || view === null) {
    return;
  }
  const box = element.getBoundingClientRect();
  if (box.top >= 0 && box.bottom <= view.innerHeight) {
    return;
  }
  view.scrollTo({ top: view.scrollY + box.top - REVEAL_MARGIN });
}

function pickCodes(codes: readonly string[], code: string): void {
  picked.value = items.value.filter((item) => codes.includes(item.code));
  latest.value = code;
  active.value = Math.max(
    0,
    items.value.findIndex((item) => item.code === code),
  );
  showOption(active.value);
}

function chosenText(item: InspectorElement): string {
  return fill(copy.value.chosen, { code: item.code, text: shown(item) });
}

function countedText(item: InspectorElement, template: string): string {
  const count = selected.value.length;
  return count === 0
    ? copy.value.cleared
    : fill(template, {
        code: item.code,
        text: shown(item),
        count: plural(count, copy.value.partsCount),
      });
}

function choose(code: string): void {
  const item = byCode.value.get(code);
  if (item === undefined) {
    return;
  }
  pickCodes([code], code);
  announcement.value = chosenText(item);
}

function toggle(code: string): void {
  const item = byCode.value.get(code);
  if (item === undefined) {
    return;
  }
  const removing = selected.value.includes(code);
  if (!removing && selected.value.length >= TARGET_PARTS_LIMIT) {
    announcement.value = fill(copy.value.tooMany, { max: TARGET_PARTS_LIMIT });
    return;
  }
  const codes = removing
    ? selected.value.filter((value) => value !== code)
    : [...selected.value, code];
  pickCodes(codes, code);
  announcement.value = countedText(item, removing ? copy.value.removed : copy.value.added);
}

function pick(code: string, event: MouseEvent): void {
  if (multi.value || event.ctrlKey || event.metaKey) {
    toggle(code);
  } else {
    choose(code);
  }
}

function clear(message: string = copy.value.cleared): void {
  picked.value = [];
  latest.value = null;
  announcement.value = message;
}

async function focusInPanel(target: () => HTMLElement | null | undefined): Promise<void> {
  await nextTick();
  (target() ?? field.value)?.focus();
}

function removePart(code: string, index: number): void {
  toggle(code);
  void focusInPanel(() => {
    const buttons = [...(partList.value?.querySelectorAll<HTMLElement>("button") ?? [])];
    return buttons[Math.min(index, buttons.length - 1)];
  });
}

function chooseContainer(): void {
  const part = anchor.value;
  const zone = container.value;
  if (part === null || zone === null) {
    return;
  }
  pickCodes([...selected.value.filter((code) => code !== part.code), zone.code], zone.code);
  announcement.value =
    selected.value.length === 1 ? chosenText(zone) : countedText(zone, copy.value.added);
  void focusInPanel(() => parentButton.value);
}

function onPointer(event: Event): void {
  hovered.value = codeAt(event.target);
}

function onLeave(): void {
  hovered.value = null;
}

function onClick(event: MouseEvent): void {
  if (elementOf(event.target)?.closest("a[href]")) {
    event.preventDefault();
  }
  const code = codeAt(event.target);
  if (code !== null) {
    pick(code, event);
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && selected.value.length > 0) {
    event.preventDefault();
    clear();
  }
}

function sameLook(left: InspectorElement, right: InspectorElement): boolean {
  return left.tag === right.tag && left.label === right.label;
}

function keepParts(fresh: readonly InspectorElement[], screen: string | null): void {
  const previous = picked.value;
  if (previous.length === 0 || fresh.length === 0) {
    return;
  }
  if (previous[0]?.screen !== screen) {
    clear(copy.value.reset);
    return;
  }
  const found = new Map(fresh.map((item) => [item.code, item]));
  const strict = previous.length > 1;
  const kept = previous.flatMap((part) => {
    const next = found.get(part.code);
    return next !== undefined && (!strict || sameLook(next, part)) ? [next] : [];
  });
  const dropped = previous.filter((part) => !kept.some((item) => item.code === part.code));
  picked.value = kept;
  if (dropped.length > 0) {
    announcement.value = fill(copy.value.dropped, {
      codes: listFormat.value.format(dropped.map((part) => part.code)),
    });
  }
}

function read(current: Document): void {
  const found = screenElements(current);
  const screen = found.screen ?? props.screen;
  const fresh = found.elements.map((element) => describeElement(element, screen));
  keepParts(fresh, screen);
  items.value = fresh;
  ready.value = true;
  hovered.value = null;
  active.value = Math.max(
    0,
    fresh.findIndex((item) => selected.value.includes(item.code)),
  );
  publish();
}

function attach(): void {
  detach?.();
  detach = null;
  page = props.frame?.contentDocument ?? null;
  const current = page;
  if (current === null) {
    items.value = [];
    ready.value = false;
    hovered.value = null;
    publish();
    return;
  }
  const root = current.documentElement;
  const view = current.defaultView;
  current.addEventListener("mousemove", onPointer);
  current.addEventListener("focusin", onPointer);
  current.addEventListener("click", onClick, true);
  current.addEventListener("keydown", onKeydown);
  current.addEventListener("scroll", publish, true);
  root.addEventListener("mouseleave", onLeave);
  view?.addEventListener("resize", publish);
  detach = () => {
    current.removeEventListener("mousemove", onPointer);
    current.removeEventListener("focusin", onPointer);
    current.removeEventListener("click", onClick, true);
    current.removeEventListener("keydown", onKeydown);
    current.removeEventListener("scroll", publish, true);
    root.removeEventListener("mouseleave", onLeave);
    view?.removeEventListener("resize", publish);
  };
  read(current);
}

function focusOption(index: number): void {
  active.value = index;
  options()[index]?.focus();
}

function onOptionFocus(index: number): void {
  active.value = index;
  const code = items.value[index]?.code ?? null;
  hovered.value = code;
  if (code !== null) {
    reveal(code);
  }
}

function onListKeydown(event: KeyboardEvent): void {
  const count = items.value.length;
  const moves: Record<string, number> = {
    ArrowDown: active.value + 1,
    ArrowUp: active.value - 1,
    Home: 0,
    End: count - 1,
  };
  const next = moves[event.key];
  if (next !== undefined && count > 0) {
    event.preventDefault();
    focusOption(Math.min(count - 1, Math.max(0, next)));
    return;
  }
  const actions: Record<string, (code: string) => void> = { Enter: choose, " ": toggle };
  const action = actions[event.key];
  const item = items.value[active.value];
  if (action !== undefined && item !== undefined) {
    event.preventDefault();
    action(item.code);
    return;
  }
  if (event.key === "Escape" && selected.value.length > 0) {
    event.preventDefault();
    clear();
  }
}

function onPanelKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.isComposing || selected.value.length === 0) {
    return;
  }
  event.preventDefault();
  focusOption(active.value);
  clear();
}

function onListFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget;
  if (!(next instanceof Node) || list.value?.contains(next) !== true) {
    hovered.value = null;
  }
}

function startOptions(): IterationStartOptions {
  return {
    api: props.api ?? designIterationsApi,
    mockupsApi: props.mockupsApi ?? designMockupsApi,
    ...(props.signal === undefined ? {} : { signal: props.signal }),
  };
}

function track(): void {
  const screen = asked.value;
  const state = iterations.state;
  if (screen === null || state === "drawing" || iterations.starting) {
    return;
  }
  asked.value = null;
  if (state === "ready" && iterations.result !== null) {
    outcome.value = { kind: "ready" };
    emit("version", screen);
  } else if (state === "rejected" || state === "failed") {
    outcome.value = {
      kind: "error",
      title: state,
      code: iterations.failure?.code ?? "GENERATION_FAILED",
    };
  }
}

function settle(result: IterationOutcome, screen: string): void {
  if (result === "started") {
    request.value = "";
    asked.value = screen;
    track();
  } else if (result === "invalid") {
    outcome.value = { kind: "error", title: null, code: "ITERATION_REQUEST_INVALID" };
  } else if (result === "unavailable") {
    outcome.value = { kind: "error", title: null, code: "GENERATED_MOCKUP_REQUIRED" };
  } else if (result === "refused") {
    outcome.value = {
      kind: "error",
      title: "start",
      code: iterations.failure?.code ?? "GENERATION_START_FAILED",
    };
  }
}

async function apply(): Promise<void> {
  const value = target.value;
  const opinion = freshOpinion.value;
  const authorize = props.authorize;
  if (!canApply.value || value === null || authorize === undefined) {
    return;
  }
  sending.value = true;
  outcome.value = null;
  if (!reviewing.value) {
    reviewState.value = null;
  }
  try {
    const result = await iterations.start(
      {
        request: request.value,
        target: value,
        ...(opinion === null ? {} : { opinionId: opinion.run_id }),
      },
      authorize,
      startOptions(),
    );
    settle(result, value.screen_code);
  } finally {
    sending.value = false;
  }
}

async function askFirst(): Promise<void> {
  const value = target.value;
  const version = currentVersion.value;
  const projectId = project.value;
  const authorize = props.authorize;
  if (
    !canAskFirst.value ||
    value === null ||
    version === null ||
    projectId === null ||
    authorize === undefined
  ) {
    return;
  }
  outcome.value = null;
  try {
    await opinions.ask(
      projectId,
      version,
      request.value,
      value,
      modelLocale.value,
      authorize,
      props.opinionsApi ?? designOpinionsApi,
    );
  } catch {
    outcome.value = { kind: "opinion", code: opinions.error ?? CHANGE_OPINION_FAILED };
  }
}

function cancelRequest(): void {
  request.value = "";
  opinions.clear();
  announcement.value = copy.value.cancelled;
  void nextTick(() => field.value?.focus());
}

async function applyProposal(
  projectId: string,
  proposed: DesignPackagePayload,
  authorize: AuthorizedMockupRequest,
): Promise<AppliedVersion | null> {
  const api = props.designApi ?? defaultDesignApi;
  const previous = design.current?.id ?? null;
  let diff = design.pendingDiffs[0] ?? null;
  if (diff !== null && !samePackage(diff.proposed_package, proposed)) {
    outcome.value = { kind: "unapplied", reason: "pending" };
    return null;
  }
  try {
    if (diff === null) {
      const created = await design.proposeRevision(projectId, proposed, authorize, api);
      if (created.diff === null || created.diff.status !== "PROPOSED") {
        const reason = created.domain_issue === "NO_CHANGES" ? "unchanged" : "failed";
        outcome.value = { kind: "unapplied", reason };
        return null;
      }
      diff = created.diff;
    }
    const decided = await design.decideRevision(
      projectId,
      diff.id,
      "APPROVE",
      authorize,
      null,
      api,
    );
    const version = decided.version ?? design.current;
    if (version === null || version.id === previous) {
      outcome.value = { kind: "unapplied", reason: "recorded" };
      return null;
    }
    return { id: version.id, content_hash: version.content_hash };
  } catch {
    const changed = design.error?.code === DESIGN_CONTEXT_CHANGED;
    outcome.value = {
      kind: "unapplied",
      reason: changed ? "context" : diff === null ? "failed" : "recorded",
    };
    return null;
  }
}

async function askTwins(
  projectId: string,
  version: AppliedVersion,
  scope: DesignEvaluationScope,
  authorize: AuthorizedMockupRequest,
): Promise<void> {
  if (loop.isBusy) {
    reviewState.value = { kind: "failed", code: REVIEW_BUSY };
    return;
  }
  reviewState.value = { kind: "running", scope };
  try {
    const run = await loop.evaluate(
      projectId,
      version.id,
      version.content_hash,
      authorize,
      props.loopApi ?? designLoopApi,
      "TWIN_REVIEW",
      modelLocale.value,
      scope,
    );
    reviewState.value = { kind: "done", scope, run };
    announcement.value = reviewedText(scope, run);
  } catch {
    reviewState.value = { kind: "failed", code: loop.error ?? REVIEW_FAILED };
  }
}

async function applyVersion(): Promise<void> {
  const result = proposal.value;
  const projectId = iterations.projectId;
  const authorize = props.authorize;
  if (!canApplyVersion.value || result === null || projectId === null || authorize === undefined) {
    return;
  }
  if (!iterations.isApplicable) {
    outcome.value = { kind: "unapplied", reason: "stale" };
    return;
  }
  const scope = review.value ? plannedScope.value : null;
  applying.value = true;
  try {
    const version = await applyProposal(projectId, result.package, authorize);
    if (version === null) {
      return;
    }
    iterations.settleApplied();
    appliedVersion.value = version;
    outcome.value = { kind: "applied" };
    announcement.value = copy.value.applied;
    emit("applied", version.id);
    if (scope !== null) {
      await askTwins(projectId, version, scope, authorize);
    }
  } finally {
    applying.value = false;
  }
}

async function askAbout(): Promise<void> {
  const scope = selectedScope.value;
  const version = currentVersion.value;
  const projectId = project.value;
  const authorize = props.authorize;
  if (
    !canAsk.value ||
    scope === null ||
    version === null ||
    projectId === null ||
    authorize === undefined
  ) {
    return;
  }
  await askTwins(projectId, version, scope, authorize);
}

function trySuggestion(action: string): void {
  request.value = clip(action, ITERATION_REQUEST_LIMIT);
  announcement.value = copy.value.tried;
  void nextTick(() => field.value?.focus());
}

watch(() => [props.frame, props.loads] as const, attach, { immediate: true });

watch([hovered, selected], publish);

watch(() => [iterations.state, iterations.result?.generation_id ?? null] as const, track);

onBeforeUnmount(() => {
  detach?.();
  detach = null;
  page = null;
  opinions.clear();
});
</script>

<template>
  <section
    class="grid min-w-0 gap-4 border-b border-night-line p-4"
    :aria-labelledby="titleId"
    data-testid="mockup-inspector"
  >
    <h3 :id="titleId" class="text-[17px] font-semibold">{{ copy.title }}</h3>
    <p
      v-if="!ready"
      class="text-sm text-on-night-3"
      role="status"
      data-testid="mockup-elements-reading"
    >
      {{ copy.reading }}
    </p>
    <p
      v-else-if="items.length === 0"
      class="text-sm text-on-night-2"
      data-testid="mockup-elements-empty"
    >
      {{ copy.none }}
    </p>
    <template v-else>
      <div class="grid gap-1">
        <label class="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm text-on-night-2">
          <input
            v-model="multi"
            type="checkbox"
            class="h-5 w-5 shrink-0 accent-petrol-on-night"
            :aria-describedby="multiHintId"
            data-testid="mockup-multi"
          />
          <span>{{ copy.multi }}</span>
        </label>
        <p
          :id="multiHintId"
          class="text-xs leading-normal text-on-night-3"
          data-testid="mockup-multi-hint"
        >
          {{ fill(copy.multiHint, { max: TARGET_PARTS_LIMIT }) }}
        </p>
      </div>
      <ul
        ref="list"
        role="listbox"
        :aria-labelledby="titleId"
        :aria-multiselectable="multiselectable ? 'true' : undefined"
        class="relative grid max-h-64 list-none gap-1 overflow-y-auto rounded-field border border-night-line p-1"
        data-testid="mockup-elements"
        @keydown="onListKeydown"
        @focusout="onListFocusOut"
        @mouseleave="hovered = null"
      >
        <li
          v-for="(item, index) in items"
          :id="`${optionPrefix}-${index}`"
          :key="item.code"
          role="option"
          :aria-selected="isPicked(item) ? 'true' : 'false'"
          :tabindex="index === active ? 0 : -1"
          :aria-label="optionLabel(item)"
          :class="[
            'grid cursor-pointer gap-0.5 rounded-control px-3 py-2 text-sm transition-colors duration-150',
            isPicked(item) ? 'bg-on-night text-ink' : 'text-on-night hover:bg-night-hover',
          ]"
          :data-code="item.code"
          :data-kind="item.kind"
          data-testid="mockup-element"
          @click="pick(item.code, $event)"
          @focus="onOptionFocus(index)"
          @mouseenter="hovered = item.code"
        >
          <span class="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span class="font-mono font-semibold">{{ item.code }}</span>
            <span
              :class="[
                item.zoneKind === undefined ? 'font-mono' : '',
                isPicked(item) ? 'text-ink-2' : 'text-on-night-3',
              ]"
            >
              {{ partKind(item) }}
            </span>
          </span>
          <span class="min-w-0 break-words">{{ shown(item) }}</span>
        </li>
      </ul>
    </template>
    <p
      v-if="ready && items.length > 0 && parts.length === 0"
      class="text-sm leading-normal text-on-night-3"
      data-testid="mockup-inspect-hint"
    >
      {{ copy.hint }}
    </p>
    <section
      v-if="parts.length > 0"
      class="grid gap-3"
      :aria-labelledby="selectionId"
      data-testid="mockup-selection"
      @keydown="onPanelKeydown"
    >
      <h4 :id="selectionId" class="text-[15px] font-semibold">{{ copy.selection[subject] }}</h4>
      <ul
        v-if="chosen === null"
        ref="partList"
        class="grid list-none gap-1.5"
        :aria-labelledby="selectionId"
        data-testid="mockup-parts"
      >
        <li
          v-for="(part, index) in parts"
          :key="part.code"
          class="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-control border border-night-line px-3 py-2"
          :data-code="part.code"
          :data-kind="part.kind"
          data-testid="mockup-part"
        >
          <span class="grid min-w-0 flex-1 gap-0.5 text-sm">
            <span class="flex flex-wrap items-baseline gap-x-2 text-xs">
              <span class="font-mono font-semibold">{{ part.code }}</span>
              <span :class="[part.zoneKind === undefined ? 'font-mono' : '', 'text-on-night-3']">
                {{ partKind(part) }}
              </span>
            </span>
            <span class="break-words">{{ shown(part) }}</span>
          </span>
          <button
            type="button"
            :class="secondaryClasses(true)"
            :aria-label="fill(copy.removeLabel, { part: optionLabel(part) })"
            data-testid="mockup-part-remove"
            @click="removePart(part.code, index)"
          >
            {{ copy.remove }}
          </button>
        </li>
      </ul>
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        <template v-if="chosen !== null">
          <dt class="text-on-night-3">{{ copy.code }}</dt>
          <dd class="font-mono" data-testid="mockup-selection-code">{{ chosen.code }}</dd>
        </template>
        <dt class="text-on-night-3">{{ copy.screen }}</dt>
        <dd class="break-words" data-testid="mockup-selection-screen">{{ screenLabel }}</dd>
        <template v-if="chosen !== null">
          <dt class="text-on-night-3">{{ copy.text }}</dt>
          <dd class="break-words" data-testid="mockup-selection-text">{{ shown(chosen) }}</dd>
        </template>
        <dt class="text-on-night-3">{{ copy.requirements }}</dt>
        <dd data-testid="mockup-selection-requirements">
          <ul v-if="requirements.length > 0" class="grid list-none gap-0.5 font-mono">
            <li v-for="code in requirements" :key="code" data-testid="mockup-requirement">
              {{ code }}
            </li>
          </ul>
          <span v-else>{{ copy.noRequirements }}</span>
        </dd>
      </dl>
      <div
        v-if="chosen?.zoneKind !== undefined"
        class="grid gap-1 text-sm"
        data-testid="mockup-selection-holds"
      >
        <p class="text-on-night-2">{{ plural(chosen.holds.length, copy.holds) }}</p>
        <ul class="grid list-none gap-0.5">
          <li
            v-for="part in held"
            :key="part.code"
            class="break-words"
            data-testid="mockup-selection-held"
          >
            <span class="font-mono font-semibold">{{ part.code }}</span>
            {{ shown(part) }}
          </li>
        </ul>
      </div>
      <div v-if="container !== null" class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          ref="parentButton"
          type="button"
          :class="secondaryClasses(true)"
          :aria-describedby="parentId"
          data-testid="mockup-select-parent"
          @click="chooseContainer"
        >
          {{ copy.selectParent }}
        </button>
        <p
          :id="parentId"
          class="min-w-0 text-[13px] break-words text-on-night-3"
          data-testid="mockup-parent"
        >
          {{ optionLabel(container) }}
        </p>
      </div>
      <section
        v-if="notes.length > 0"
        class="grid gap-2"
        :aria-labelledby="notesId"
        data-testid="mockup-twin-notes"
      >
        <h5 :id="notesId" class="text-sm font-semibold">{{ copy.notes }}</h5>
        <p class="text-xs leading-normal text-violet-on-night-2">{{ copy.notesNote }}</p>
        <ul class="grid list-none gap-2">
          <li
            v-for="(note, index) in notes"
            :key="note.key"
            class="grid gap-1.5 rounded-[14px] border-[1.5px] border-dashed border-violet-on-night/70 bg-on-night/3 p-3"
            :data-verdict="note.verdict"
            data-testid="mockup-twin-note"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-semibold text-on-night" data-testid="mockup-twin-note-twin">
                {{ note.twin }}
              </span>
              <span
                :class="[
                  'inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                  VERDICT_STYLES[note.verdict],
                ]"
                data-testid="mockup-twin-note-verdict"
              >
                {{ copy.verdicts[note.verdict] }}
              </span>
            </div>
            <p class="text-sm leading-normal text-on-night" data-testid="mockup-twin-note-summary">
              {{ note.summary }}
            </p>
            <p
              :id="`${notesId}-${index}`"
              class="text-sm leading-normal text-on-night-2"
              data-testid="mockup-twin-note-action"
            >
              <strong class="font-semibold text-on-night">{{ copy.todo }}:</strong>
              {{ note.action }}
            </p>
            <button
              type="button"
              class="inline-flex min-h-11 items-center self-start text-left text-[13px] font-medium text-petrol-on-night-2 underline underline-offset-4 transition-colors duration-150 hover:text-on-night"
              :aria-describedby="`${notesId}-${index}`"
              data-testid="mockup-try-suggestion"
              @click="trySuggestion(note.action)"
            >
              {{ copy.tryThis }}
            </button>
          </li>
        </ul>
      </section>
      <div class="grid gap-1.5">
        <label :for="fieldId" class="text-sm font-semibold">{{ copy.ask }}</label>
        <textarea
          :id="fieldId"
          ref="field"
          v-model="request"
          rows="3"
          :maxlength="ITERATION_REQUEST_LIMIT"
          :aria-describedby="countId"
          class="min-h-24 resize-y rounded-control border border-night-line-strong bg-night-raised p-3 text-[15px] text-on-night"
          data-testid="mockup-request"
        />
        <p :id="countId" class="text-xs text-on-night-3" data-testid="mockup-request-count">
          {{ fill(copy.count, { n: length, max: ITERATION_REQUEST_LIMIT }) }}
        </p>
      </div>
      <MockupChangeOpinions
        :run="opinionRun"
        :busy="opinions.busy"
        :stale="opinionStale"
        :can-apply="canApply"
        :locale="locale"
        @apply="apply"
        @change="field?.focus()"
        @cancel="cancelRequest"
        @try="trySuggestion"
      />
      <label class="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm text-on-night-2">
        <input
          v-model="review"
          type="checkbox"
          class="h-5 w-5 shrink-0 accent-petrol-on-night"
          data-testid="mockup-review"
        />
        <span>{{ copy.review }}</span>
      </label>
      <div v-if="showAsk" class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          :class="askClasses"
          :aria-disabled="canAsk ? undefined : 'true'"
          :aria-describedby="askTimeId"
          data-testid="mockup-ask-twins"
          @click="askAbout"
        >
          {{ copy.askTwins[subject] }}
        </button>
        <p :id="askTimeId" class="text-[13px] text-on-night-3" data-testid="mockup-ask-time">
          {{ copy.askTwinsTime }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          :class="applyClasses"
          :aria-disabled="canApply ? undefined : 'true'"
          :aria-describedby="withPending(estimateId)"
          data-testid="mockup-apply"
          @click="apply"
        >
          {{ copy.apply }}
        </button>
        <p :id="estimateId" class="text-[13px] text-on-night-3" data-testid="mockup-estimate">
          {{ estimate }}
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          :class="secondaryClasses(canAskFirst)"
          :aria-disabled="canAskFirst ? undefined : 'true'"
          :aria-describedby="withPending(askFirstTimeId)"
          data-testid="mockup-ask-first"
          @click="askFirst"
        >
          {{ copy.askFirst }}
        </button>
        <p
          :id="askFirstTimeId"
          class="text-[13px] text-on-night-3"
          data-testid="mockup-ask-first-time"
        >
          {{ copy.askFirstTime }}
        </p>
      </div>
      <p
        v-if="pending"
        :id="pendingId"
        class="text-[13px] leading-normal text-warn-on-night"
        data-testid="mockup-change-pending"
      >
        {{ copy.pending }}
      </p>
    </section>
    <UiStateBlock
      v-if="notice !== null"
      :kind="notice.kind"
      :title="notice.title"
      :text="notice.text"
      data-testid="mockup-change-status"
    />
    <div v-if="proposal !== null" class="grid gap-1.5" data-testid="mockup-version">
      <button
        type="button"
        :class="[versionClasses, 'justify-self-start']"
        :aria-disabled="canApplyVersion ? undefined : 'true'"
        :aria-describedby="versionNoteId"
        data-testid="mockup-apply-version"
        @click="applyVersion"
      >
        {{ copy.applyVersion }}
      </button>
      <p
        :id="versionNoteId"
        class="text-[13px] leading-normal text-on-night-3"
        data-testid="mockup-version-note"
      >
        {{ versionNote }}
      </p>
      <section
        v-if="corrections.length > 0"
        class="mt-1.5 grid gap-1.5"
        :aria-labelledby="correctionsId"
        data-testid="mockup-version-corrections"
      >
        <h4 :id="correctionsId" class="text-sm font-semibold">{{ copy.corrections }}</h4>
        <ul
          class="grid list-disc gap-1 pl-5 text-[13px] leading-normal text-on-night-2 marker:text-petrol-on-night"
        >
          <li
            v-for="(line, index) in corrections"
            :key="index"
            data-testid="mockup-version-correction"
          >
            {{ line }}
          </li>
        </ul>
      </section>
    </div>
    <UiStateBlock
      v-if="reviewNotice !== null"
      :kind="reviewNotice.kind"
      :title="reviewNotice.title"
      :text="reviewNotice.text"
      data-testid="mockup-review-status"
    />
    <p class="sr-only" role="status" data-testid="mockup-inspect-announcement">
      {{ announcement }}
    </p>
  </section>
</template>
