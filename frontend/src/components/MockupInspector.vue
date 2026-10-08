<script lang="ts">
import type { DesignChangeTarget } from "../api/designIterations";
import { TARGET_HTML_LIMIT, TARGET_LABEL_LIMIT } from "../stores/designIterations";

export interface InspectorBox {
  code: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface InspectorHighlight {
  hover: InspectorBox | null;
  selected: InspectorBox | null;
}

export interface InspectedElement {
  code: string;
  tag: string;
  text: string;
  screen: string | null;
  requirements: string[];
}

export interface ScreenElements {
  screen: string | null;
  elements: Element[];
}

export const NO_HIGHLIGHT: InspectorHighlight = { hover: null, selected: null };

const SCREEN = "section[id^='SCR-']";
const MARKED = "[data-elm]";
const PIN = "ot-pin";
const SRCDOC_LINK = /(\shref=")about:srcdoc#(SCR-[0-9]{3}")/g;
const NAME_ATTRIBUTES = ["value", "placeholder", "title", "alt"] as const;
const SILENT = new Set(["script", "style", "template", "noscript", "select", "textarea", "svg"]);
const BLOCKS = new Set([
  "article",
  "aside",
  "blockquote",
  "br",
  "caption",
  "dd",
  "details",
  "div",
  "dl",
  "dt",
  "fieldset",
  "figcaption",
  "figure",
  "footer",
  "form",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "legend",
  "li",
  "main",
  "nav",
  "ol",
  "p",
  "section",
  "summary",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "ul",
]);

function normalize(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function clip(value: string, limit: number): string {
  const characters = [...value];
  return characters.length <= limit ? value : characters.slice(0, limit).join("").trimEnd();
}

function isElement(node: Node): node is Element {
  return node.nodeType === 1;
}

function silent(element: Element): boolean {
  return (
    SILENT.has(element.localName) ||
    element.hasAttribute("hidden") ||
    element.classList.contains(PIN)
  );
}

function collect(node: Node, parts: string[]): void {
  for (const child of node.childNodes) {
    if (child.nodeType === 3) {
      parts.push(child.textContent ?? "");
      continue;
    }
    if (!isElement(child) || silent(child)) {
      continue;
    }
    const block = BLOCKS.has(child.localName);
    if (block) {
      parts.push(" ");
    }
    collect(child, parts);
    if (block) {
      parts.push(" ");
    }
  }
}

function ownText(element: Element): string {
  if (element.localName === "select") {
    const option = element.querySelector("option[selected]") ?? element.querySelector("option");
    return normalize(option?.textContent ?? "");
  }
  if (element.localName === "textarea") {
    return normalize(element.textContent ?? "");
  }
  const parts: string[] = [];
  collect(element, parts);
  return normalize(parts.join(""));
}

function referencedText(element: Element): string {
  const page = element.ownerDocument;
  const names = (element.getAttribute("aria-labelledby") ?? "").split(/\s+/).filter(Boolean);
  return normalize(names.map((name) => page.getElementById(name)?.textContent ?? "").join(" "));
}

function labelText(element: Element): string {
  const id = element.getAttribute("id");
  const labels = [...element.ownerDocument.querySelectorAll("label[for]")].filter(
    (label) => id !== null && label.getAttribute("for") === id,
  );
  const owner = element.closest("label");
  return normalize(
    [...labels, ...(owner === null ? [] : [owner])].map((label) => ownText(label)).join(" "),
  );
}

export function elementText(element: Element): string {
  const candidates = [
    () => ownText(element),
    () => referencedText(element),
    () => normalize(element.getAttribute("aria-label") ?? ""),
    () => labelText(element),
    ...NAME_ATTRIBUTES.map((name) => () => normalize(element.getAttribute(name) ?? "")),
  ];
  for (const candidate of candidates) {
    const text = candidate();
    if (text.length > 0) {
      return clip(text, TARGET_LABEL_LIMIT);
    }
  }
  return "";
}

export function requirementsOf(element: Element): string[] {
  const value = element.closest("[data-req]")?.getAttribute("data-req") ?? "";
  return [...new Set(value.split(/[\s,]+/).filter((code) => code.length > 0))];
}

export function describeElement(element: Element): InspectedElement {
  return {
    code: element.getAttribute("data-elm") ?? "",
    tag: element.localName,
    text: elementText(element),
    screen: element.closest(SCREEN)?.id ?? null,
    requirements: requirementsOf(element),
  };
}

function rendered(element: Element): boolean {
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

export function visibleScreen(page: Document): Element | null {
  const screens = [...page.querySelectorAll(SCREEN)];
  return (
    screens.find(rendered) ??
    screens.find((screen) => screen.hasAttribute("data-entry")) ??
    screens[0] ??
    null
  );
}

export function screenElements(page: Document): ScreenElements {
  const screen = visibleScreen(page);
  const scope = screen ?? page.body ?? page.documentElement;
  const seen = new Set<string>();
  const elements = [...scope.querySelectorAll(MARKED)].filter((element) => {
    const code = element.getAttribute("data-elm") ?? "";
    if (code.length === 0 || seen.has(code)) {
      return false;
    }
    seen.add(code);
    return true;
  });
  return { screen: screen?.id ?? null, elements };
}

export function markedElements(html: string): boolean {
  return new DOMParser().parseFromString(html, "text/html").querySelector(MARKED) !== null;
}

export function changeTarget(element: Element, screen: string | null): DesignChangeTarget | null {
  const code = element.getAttribute("data-elm");
  const screenCode = element.closest(SCREEN)?.id ?? screen;
  if (code === null || code.length === 0 || screenCode === null || screenCode.length === 0) {
    return null;
  }
  const copy = element.cloneNode(true) as Element;
  for (const pin of [...copy.querySelectorAll(`.${PIN}`)]) {
    pin.remove();
  }
  return {
    screen_code: screenCode,
    element_code: code,
    label: elementText(element) || code,
    html: clip(copy.outerHTML.replace(SRCDOC_LINK, "$1#$2"), TARGET_HTML_LIMIT),
  };
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";

import { generationFailureText } from "./DesignIterationPanel.vue";
import { modelFeedback } from "./modelFeedback";
import { elementNames, withScreenNames } from "./screenNames";
import UiStateBlock from "./UiStateBlock.vue";
import { designApi as defaultDesignApi, type DesignApi } from "../api/design";
import { designIterationsApi, type DesignIterationsApi } from "../api/designIterations";
import { designLoopApi, type DesignEvaluationScope, type DesignLoopApi } from "../api/designLoop";
import { designMockupsApi, type DesignMockupsApi } from "../api/designMockups";
import { useDesignStore } from "../stores/design";
import {
  DESIGN_CONTEXT_CHANGED,
  ITERATION_REQUEST_LIMIT,
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
import type { DesignPackagePayload } from "../types/design";
import type {
  DesignEvaluationRunPayload,
  SyntheticFindingPayload,
  SyntheticFindingSeverity,
} from "../types/designLoop";

type Locale = "en" | "it";
type FailureTitle = "rejected" | "failed" | "start";
type Verdict = "helps" | "slows" | "blocks";
type Unapplied = "stale" | "pending" | "unchanged" | "recorded" | "failed" | "context";

type Outcome =
  | { kind: "ready" }
  | { kind: "applied" }
  | { kind: "unapplied"; reason: Unapplied }
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

interface AppliedVersion {
  id: string;
  hash: string;
}

interface TwinNote {
  key: string;
  twin: string;
  verdict: Verdict;
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
    signal?: AbortSignal | undefined;
  }>(),
  {
    screens: () => [],
    authorize: undefined,
    api: undefined,
    mockupsApi: undefined,
    designApi: undefined,
    loopApi: undefined,
    signal: undefined,
  },
);

const emit = defineEmits<{
  highlight: [value: InspectorHighlight];
  version: [screen: string];
  applied: [versionId: string];
}>();

const messages = {
  it: {
    title: "Elementi indicabili",
    reading: "Leggo gli elementi della schermata…",
    none: "In questa schermata non ci sono elementi indicabili.",
    hint: "Passa sul mockup e fai clic su un elemento, oppure sceglilo dall'elenco con le frecce e Invio.",
    noText: "Senza testo",
    selection: "Elemento scelto",
    code: "Codice",
    screen: "Schermata",
    text: "Testo",
    requirements: "Requisiti",
    noRequirements: "Nessun requisito collegato",
    ask: "Che cosa cambio?",
    count: "{n} di {max} caratteri",
    review: "Chiedi subito il parere dei twin",
    apply: "Applica la modifica",
    estimate: "Di solito servono da 5 a 10 minuti.",
    estimateReview: "Di solito servono da 5 a 10 minuti, più il parere dei twin.",
    pending:
      "Una nuova versione aspetta già la tua decisione: applicala o scartala prima di chiedere altre modifiche.",
    chosen: "Hai scelto {code}: {text}",
    cleared: "Nessun elemento scelto.",
    drawing:
      "Sto disegnando la nuova versione con le tue indicazioni. Può richiedere qualche minuto: intanto puoi continuare a guardare il design.",
    ready: "Ecco la nuova versione. Confrontala con quella attuale e decidi se applicarla.",
    applyVersion: "Applica la nuova versione",
    versionReview: "Dopo l'applicazione i twin guardano {code}: di solito serve un paio di minuti.",
    versionAlone:
      "Applicarla non avvia nessuna generazione: la versione proposta diventa quella attuale.",
    applied: "Hai applicato la nuova versione: ora è quella attuale.",
    unapplied: {
      stale: "Il design è cambiato nel frattempo: questa versione non si può più applicare.",
      pending:
        "Un'altra modifica aspetta la tua decisione nella pagina del passo Design: applicala o scartala prima.",
      unchanged: "Questa versione è già quella attuale.",
      recorded:
        "La nuova versione è registrata ma non è ancora stata applicata. Premi di nuovo «Applica la nuova versione».",
      failed: "Il design è rimasto com'era. Riprova tra poco.",
    },
    reviewing: "I twin stanno guardando l'elemento…",
    reviewingScreen: "I twin stanno guardando la schermata…",
    reviewTime: "Di solito serve un paio di minuti: intanto puoi continuare a guardare il mockup.",
    reviewed: "I twin hanno detto la loro su {code}: le loro note sono accanto all'elemento.",
    reviewedNone:
      "I twin non hanno lasciato note su {code}: il loro giudizio è nelle revisioni del passo Design.",
    reviewedScreen:
      "I twin hanno detto la loro su {code}: scegli un elemento per leggere le loro note.",
    reviewFailed: "Il parere dei twin non è arrivato",
    reviewerMissing:
      "Il modello che interpreta i twin non è collegato, quindi i twin non possono dare il loro parere.",
    reviewBusy:
      "I twin stanno già facendo un'altra revisione: chiedi il loro parere quando hanno finito.",
    askTwins: "Chiedi il parere dei twin su questo elemento",
    askTwinsTime: "Di solito serve un paio di minuti.",
    notes: "Che cosa ne dicono i twin",
    notesNote: "Sono ipotesi dei twin da pesare, non prove.",
    verdicts: { helps: "Aiuta", slows: "Rallenta", blocks: "Blocca" },
    todo: "Cosa fare",
    tryThis: "Prova questo",
    tried:
      "Ho scritto il suggerimento in «Che cosa cambio?»: controllalo e premi «Applica la modifica».",
    failures: {
      rejected: "La nuova versione va rifatta",
      failed: "La nuova versione non è stata disegnata",
      start: "La richiesta non è partita",
      apply: "La nuova versione non è stata applicata",
    },
    stages: {
      GENERATING: "Il designer sta disegnando le schermate.",
      VALIDATING: "Lo Studio controlla la nuova versione.",
      RETRYING: "Il primo tentativo non andava bene: il designer lo sta rifacendo.",
      none: "Il designer sta lavorando alla nuova versione.",
    },
  },
  en: {
    title: "Elements you can point at",
    reading: "Reading the elements of the screen…",
    none: "This screen has no elements to point at.",
    hint: "Move over the mockup and click an element, or choose it from the list with the arrow keys and Enter.",
    noText: "No text",
    selection: "Chosen element",
    code: "Code",
    screen: "Screen",
    text: "Text",
    requirements: "Requirements",
    noRequirements: "No linked requirement",
    ask: "What should I change?",
    count: "{n} of {max} characters",
    review: "Ask the twins for their opinion right away",
    apply: "Apply the change",
    estimate: "It usually takes 5 to 10 minutes.",
    estimateReview: "It usually takes 5 to 10 minutes, plus the opinion of the twins.",
    pending:
      "A new version is already waiting for your decision: apply it or discard it before asking for other changes.",
    chosen: "You chose {code}: {text}",
    cleared: "No element chosen.",
    drawing:
      "I am drawing the new version from your instructions. It can take a few minutes: meanwhile you can keep looking at the design.",
    ready:
      "Here is the new version. Compare it with the current one and decide whether to apply it.",
    applyVersion: "Apply the new version",
    versionReview:
      "Once it is applied the twins look at {code}: it usually takes a couple of minutes.",
    versionAlone: "Applying it starts no generation: the proposed version becomes the current one.",
    applied: "You applied the new version: it is now the current one.",
    unapplied: {
      stale: "The design changed in the meantime: this version can no longer be applied.",
      pending:
        "Another change is waiting for your decision on the page of the Design step: apply it or discard it first.",
      unchanged: "This version is already the current one.",
      recorded:
        "The new version is recorded but it was not applied yet. Press “Apply the new version” again.",
      failed: "The design stayed as it was. Try again in a moment.",
    },
    reviewing: "The twins are looking at the element…",
    reviewingScreen: "The twins are looking at the screen…",
    reviewTime:
      "It usually takes a couple of minutes: meanwhile you can keep looking at the mockup.",
    reviewed: "The twins gave their opinion on {code}: their notes are next to the element.",
    reviewedNone:
      "The twins left no note on {code}: their judgement is in the reviews of the Design step.",
    reviewedScreen:
      "The twins gave their opinion on {code}: choose an element to read their notes.",
    reviewFailed: "The opinion of the twins did not arrive",
    reviewerMissing:
      "The model that plays the twins is not connected, so the twins cannot give their opinion.",
    reviewBusy:
      "The twins are already doing another review: ask for their opinion once they have finished.",
    askTwins: "Ask the twins for their opinion on this element",
    askTwinsTime: "It usually takes a couple of minutes.",
    notes: "What the twins say about it",
    notesNote: "They are hypotheses of the twins to weigh, not evidence.",
    verdicts: { helps: "Helps", slows: "Slows down", blocks: "Blocks" },
    todo: "What to do",
    tryThis: "Try this",
    tried:
      "I wrote the suggestion in “What should I change?”: check it and press “Apply the change”.",
    failures: {
      rejected: "The new version needs another try",
      failed: "The new version was not drawn",
      start: "The request did not start",
      apply: "The new version was not applied",
    },
    stages: {
      GENERATING: "The designer is drawing the screens.",
      VALIDATING: "The Studio is checking the new version.",
      RETRYING: "The first attempt was not good enough: the designer is redoing it.",
      none: "The designer is working on the new version.",
    },
  },
} as const;

const REVEAL_MARGIN = 16;
const REVIEW_BUSY = "DESIGN_REVIEW_BUSY";
const REVIEW_FAILED = "DESIGN_LOOP_REQUEST_FAILED";

const VERDICTS: Record<SyntheticFindingSeverity, Verdict> = {
  observation: "helps",
  minor: "slows",
  moderate: "slows",
  major: "blocks",
  critical: "blocks",
};

const VERDICT_STYLES: Record<Verdict, string> = {
  helps: "bg-petrol-on-night/12 text-petrol-on-night-2",
  slows: "bg-warn-on-night/12 text-warn-on-night",
  blocks: "bg-fail-on-night/12 text-fail-on-night",
};

const iterations = useDesignIterationsStore();
const design = useDesignStore();
const loop = useDesignLoopStore();

const copy = computed(() => messages[props.locale]);

const titleId = useId();
const selectionId = useId();
const fieldId = useId();
const countId = useId();
const estimateId = useId();
const pendingId = useId();
const optionPrefix = useId();
const notesId = useId();
const versionNoteId = useId();
const askTimeId = useId();

const list = ref<HTMLElement | null>(null);
const field = ref<HTMLTextAreaElement | null>(null);
const items = ref<InspectedElement[]>([]);
const screenCode = ref<string | null>(null);
const ready = ref(false);
const hovered = ref<string | null>(null);
const selected = ref<string | null>(null);
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
let live = new Map<string, Element>();
let detach: (() => void) | null = null;

const chosen = computed(() => items.value.find((item) => item.code === selected.value) ?? null);

const length = computed(() => [...request.value].length);

const drawing = computed(() => iterations.state === "drawing" || iterations.starting);

const waiting = computed(() => iterations.state === "ready");

const pending = computed(() => waiting.value && outcome.value?.kind !== "ready");

const canApply = computed(
  () =>
    chosen.value !== null &&
    request.value.trim().length > 0 &&
    length.value <= ITERATION_REQUEST_LIMIT &&
    props.authorize !== undefined &&
    !sending.value &&
    !drawing.value &&
    !waiting.value &&
    !applying.value,
);

const estimate = computed(() => (review.value ? copy.value.estimateReview : copy.value.estimate));

const describedBy = computed(() => (pending.value ? `${estimateId} ${pendingId}` : estimateId));

const applyClasses = computed(() => buttonClasses(canApply.value));

const proposal = computed(() => (waiting.value ? iterations.result : null));

const reviewing = computed(() => reviewState.value?.kind === "running");

const project = computed(() => iterations.projectId ?? design.projectId);

const currentVersion = computed<AppliedVersion | null>(() => {
  const current = design.current;
  if (current !== null && current.project_id === project.value) {
    return { id: current.id, hash: current.content_hash };
  }
  const context = iterations.design;
  return context === null
    ? appliedVersion.value
    : { id: context.versionId, hash: context.contentHash };
});

const selectedScope = computed<DesignEvaluationScope | null>(() => {
  const item = chosen.value;
  const screen = item?.screen ?? screenCode.value;
  return item === null || screen === null ? null : { screen_code: screen, element_code: item.code };
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
  () => chosen.value !== null && (!review.value || reviewState.value?.kind === "failed"),
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

const askClasses = computed(() => [
  "inline-flex min-h-11 items-center justify-center rounded-pill border px-4 py-2 text-sm font-semibold transition-colors duration-150",
  canAsk.value
    ? "border-night-line-strong text-on-night hover:bg-night-hover"
    : "cursor-not-allowed border-night-line text-on-night-3",
]);

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
    items.value.filter((item) => item.text.length > 0).map((item) => [item.code, item.text]),
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
      run.design_content_hash === version.hash,
  );
});

const notes = computed<TwinNote[]>(() => {
  const code = chosen.value?.code ?? null;
  if (code === null) {
    return [];
  }
  for (const run of reviewRuns.value) {
    const found = run.responses.flatMap((response) =>
      response.findings.filter((finding) => findingElement(finding) === code),
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
    const title =
      state.scope.element_code === undefined ? copy.value.reviewingScreen : copy.value.reviewing;
    return { kind: "loading", title, text: copy.value.reviewTime };
  }
  if (state.kind === "failed") {
    return { kind: "error", title: copy.value.reviewFailed, text: reviewFailure(state.code) };
  }
  return { kind: "success", title: reviewedText(state.scope, state.run), text: "" };
});

const screenLabel = computed(() => {
  const code = chosen.value?.screen ?? screenCode.value;
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
  const reason = generationFailureText(value.code, props.locale);
  return value.title === null
    ? { kind: "error", title: reason, text: "" }
    : { kind: "error", title: copy.value.failures[value.title], text: reason };
});

function optionLabel(item: InspectedElement): string {
  return [item.code, item.tag, item.text || copy.value.noText].join(", ");
}

function buttonClasses(enabled: boolean): string[] {
  return [
    "inline-flex min-h-11 items-center justify-center rounded-pill px-5 py-2.5 text-sm font-semibold transition-colors duration-150",
    enabled
      ? "bg-on-night text-ink hover:bg-petrol-on-night-2"
      : "cursor-not-allowed bg-night-hover text-on-night-3",
  ];
}

function scopeOf(target: DesignChangeTarget | undefined): DesignEvaluationScope | null {
  if (target === undefined) {
    return null;
  }
  return {
    screen_code: target.screen_code,
    ...(target.element_code === undefined ? {} : { element_code: target.element_code }),
  };
}

function scopeCode(scope: DesignEvaluationScope): string {
  return scope.element_code ?? scope.screen_code;
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
  const code = scope.element_code;
  if (code === undefined) {
    return fill(copy.value.reviewedScreen, { code: scope.screen_code });
  }
  const noted = run.responses.some((response) =>
    response.findings.some((finding) => findingElement(finding) === code),
  );
  return fill(noted ? copy.value.reviewed : copy.value.reviewedNone, { code });
}

function named(text: string, location: string): string {
  return withScreenNames(text, {
    screens: props.screens,
    elements: { ...elementNames([location]), ...elementLabels.value },
    locale: props.locale,
  });
}

function twinNote(finding: SyntheticFindingPayload): TwinNote {
  return {
    key: `${finding.twin_id}:${finding.finding_id}`,
    twin: twinNames.value[finding.twin_id] ?? finding.twin_id.slice(0, 8),
    verdict: VERDICTS[finding.severity],
    summary: named(finding.summary, finding.location),
    action: named(finding.recommended_action, finding.location),
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
  const code = elementOf(target)?.closest(MARKED)?.getAttribute("data-elm") ?? null;
  return code !== null && live.has(code) ? code : null;
}

function boxOf(code: string | null): InspectorBox | null {
  const element = code === null ? undefined : live.get(code);
  if (code === null || element === undefined) {
    return null;
  }
  const rect = element.getBoundingClientRect();
  return { code, left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function publish(): void {
  emit("highlight", {
    hover: hovered.value === selected.value ? null : boxOf(hovered.value),
    selected: boxOf(selected.value),
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
  const element = live.get(code);
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

function choose(code: string): void {
  const index = items.value.findIndex((item) => item.code === code);
  const item = items.value[index];
  if (item === undefined) {
    return;
  }
  selected.value = code;
  active.value = index;
  announcement.value = fill(copy.value.chosen, { code, text: item.text || copy.value.noText });
  showOption(index);
}

function clear(): void {
  selected.value = null;
  announcement.value = copy.value.cleared;
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
    choose(code);
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && selected.value !== null) {
    event.preventDefault();
    clear();
  }
}

function read(current: Document): void {
  const found = screenElements(current);
  live = new Map(
    found.elements.map((element) => [element.getAttribute("data-elm") ?? "", element]),
  );
  items.value = found.elements.map((element) => describeElement(element));
  screenCode.value = found.screen ?? props.screen;
  ready.value = true;
  hovered.value = null;
  if (selected.value !== null && live.size > 0 && !live.has(selected.value)) {
    selected.value = null;
  }
  active.value = Math.max(
    0,
    items.value.findIndex((item) => item.code === selected.value),
  );
  publish();
}

function attach(): void {
  detach?.();
  detach = null;
  page = props.frame?.contentDocument ?? null;
  const current = page;
  if (current === null) {
    live = new Map();
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
  const item = items.value[active.value];
  if ((event.key === "Enter" || event.key === " ") && item !== undefined) {
    event.preventDefault();
    choose(item.code);
    return;
  }
  if (event.key === "Escape" && selected.value !== null) {
    event.preventDefault();
    clear();
  }
}

function onPanelKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.isComposing || selected.value === null) {
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
  const code = selected.value;
  const element = code === null ? undefined : live.get(code);
  const authorize = props.authorize;
  if (!canApply.value || element === undefined || authorize === undefined) {
    return;
  }
  const target = changeTarget(element, screenCode.value ?? props.screen);
  if (target === null) {
    return;
  }
  sending.value = true;
  outcome.value = null;
  if (!reviewing.value) {
    reviewState.value = null;
  }
  try {
    const result = await iterations.start(
      { request: request.value, target },
      authorize,
      startOptions(),
    );
    settle(result, target.screen_code);
  } finally {
    sending.value = false;
  }
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
    return { id: version.id, hash: version.content_hash };
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
      version.hash,
      authorize,
      props.loopApi ?? designLoopApi,
      "TWIN_REVIEW",
      props.locale === "it" ? "it-IT" : "en-US",
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
  live = new Map();
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
    <ul
      v-else
      ref="list"
      role="listbox"
      :aria-labelledby="titleId"
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
        :aria-selected="item.code === selected ? 'true' : 'false'"
        :tabindex="index === active ? 0 : -1"
        :aria-label="optionLabel(item)"
        :class="[
          'grid cursor-pointer gap-0.5 rounded-control px-3 py-2 text-sm transition-colors duration-150',
          item.code === selected ? 'bg-on-night text-ink' : 'text-on-night hover:bg-night-hover',
        ]"
        :data-code="item.code"
        data-testid="mockup-element"
        @click="choose(item.code)"
        @focus="onOptionFocus(index)"
        @mouseenter="hovered = item.code"
      >
        <span class="flex flex-wrap items-baseline gap-x-2 font-mono text-xs">
          <span class="font-semibold">{{ item.code }}</span>
          <span :class="item.code === selected ? 'text-ink-2' : 'text-on-night-3'">
            {{ item.tag }}
          </span>
        </span>
        <span class="min-w-0 break-words">{{ item.text || copy.noText }}</span>
      </li>
    </ul>
    <p
      v-if="ready && items.length > 0 && chosen === null"
      class="text-sm leading-normal text-on-night-3"
      data-testid="mockup-inspect-hint"
    >
      {{ copy.hint }}
    </p>
    <section
      v-if="chosen !== null"
      class="grid gap-3"
      :aria-labelledby="selectionId"
      data-testid="mockup-selection"
      @keydown="onPanelKeydown"
    >
      <h4 :id="selectionId" class="text-[15px] font-semibold">{{ copy.selection }}</h4>
      <dl class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
        <dt class="text-on-night-3">{{ copy.code }}</dt>
        <dd class="font-mono" data-testid="mockup-selection-code">{{ chosen.code }}</dd>
        <dt class="text-on-night-3">{{ copy.screen }}</dt>
        <dd class="break-words" data-testid="mockup-selection-screen">{{ screenLabel }}</dd>
        <dt class="text-on-night-3">{{ copy.text }}</dt>
        <dd class="break-words" data-testid="mockup-selection-text">
          {{ chosen.text || copy.noText }}
        </dd>
        <dt class="text-on-night-3">{{ copy.requirements }}</dt>
        <dd data-testid="mockup-selection-requirements">
          <ul v-if="chosen.requirements.length > 0" class="grid list-none gap-0.5 font-mono">
            <li v-for="code in chosen.requirements" :key="code" data-testid="mockup-requirement">
              {{ code }}
            </li>
          </ul>
          <span v-else>{{ copy.noRequirements }}</span>
        </dd>
      </dl>
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
          {{ copy.askTwins }}
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
          :aria-describedby="describedBy"
          data-testid="mockup-apply"
          @click="apply"
        >
          {{ copy.apply }}
        </button>
        <p :id="estimateId" class="text-[13px] text-on-night-3" data-testid="mockup-estimate">
          {{ estimate }}
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
