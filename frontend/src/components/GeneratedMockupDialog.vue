<script lang="ts">
export type MockupSeverity = "critical" | "major" | "moderate" | "minor" | "observation";

export interface MockupScreen {
  code: string;
  title: string;
  state: string;
}

export interface MockupDocument {
  html: string;
  content_hash: string;
  source: string;
  alternative_id: string;
  title: string;
  entry_screen: string;
  screens: readonly MockupScreen[];
}

export interface MockupPin {
  number: number;
  element_code: string;
  screen_code: string;
  twin_id: string;
  finding_id: string;
  severity: MockupSeverity;
  label: string;
}

export interface MockupUnanchoredPin {
  number: number;
  screen_code: string;
  twin_id: string;
  finding_id: string;
}

export interface MockupObservation {
  number: number;
  twin_name: string;
  severity: MockupSeverity;
  text: string;
  place: string;
}
</script>

<script setup lang="ts">
import {
  computed,
  inject,
  nextTick,
  onMounted,
  onUnmounted,
  provide,
  ref,
  useId,
  watch,
} from "vue";
import { useI18n } from "vue-i18n";

import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import MockupWhyElements from "./MockupWhyElements.vue";
import MockupScenarioWalkthrough from "./MockupScenarioWalkthrough.vue";
import { whyContextKey } from "./whyContext";
import UiSegmented from "./UiSegmented.vue";
import UiStateBlock from "./UiStateBlock.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import {
  elementNames,
  placeLabel,
  placeScreens,
  withScreenNames,
  type ScreenNaming,
  type WorkflowName,
} from "./screenNames";

type Locale = "en" | "it";
type FrameWidth = "desktop" | "tablet" | "phone";

const props = withDefaults(
  defineProps<{
    title: string;
    document: MockupDocument | null;
    pins?: readonly MockupPin[] | undefined;
    unanchored?: readonly MockupUnanchoredPin[] | undefined;
    observations?: readonly MockupObservation[] | undefined;
    elements?: Readonly<Record<string, string>> | undefined;
    workflows?: readonly WorkflowName[] | undefined;
    busy?: boolean | undefined;
    locale?: Locale | undefined;
  }>(),
  {
    pins: () => [],
    unanchored: () => [],
    observations: () => [],
    elements: () => ({}),
    workflows: () => [],
    busy: false,
    locale: undefined,
  },
);

const emit = defineEmits<{ close: []; screen: [code: string] }>();

const messages = {
  it: {
    close: "Chiudi il mockup",
    screens: "Schermate del mockup",
    width: "Larghezza del mockup",
    widths: { desktop: "Desktop", tablet: "Tablet", phone: "Telefono" },
    frame: "Mockup navigabile: {title}",
    hint: "Il mockup è navigabile: i suoi collegamenti portano alle altre schermate.",
    opening: "Apro la schermata…",
    empty: "Il mockup non è ancora disponibile.",
    observations: "Osservazioni dei twin",
    one: "1 osservazione",
    many: "{n} osservazioni",
    note: "I numeri viola sul mockup sono le osservazioni dei twin: ipotesi da pesare, non prove.",
    where: "Dove",
    screen: "Schermata «{title}»",
    unanchored: "Riguarda tutta la schermata: sul mockup non ha un punto preciso.",
    show: "Mostra la schermata «{title}»",
    severity: {
      critical: "Critica",
      major: "Importante",
      moderate: "Moderata",
      minor: "Minore",
      observation: "Nota",
    },
  },
  en: {
    close: "Close the mockup",
    screens: "Mockup screens",
    width: "Mockup width",
    widths: { desktop: "Desktop", tablet: "Tablet", phone: "Phone" },
    frame: "Navigable mockup: {title}",
    hint: "The mockup can be navigated: its links lead to the other screens.",
    opening: "Opening the screen…",
    empty: "The mockup is not available yet.",
    observations: "What the twins noticed",
    one: "1 observation",
    many: "{n} observations",
    note: "The purple numbers on the mockup are the observations of the twins: hypotheses to weigh, not evidence.",
    where: "Where",
    screen: "Screen “{title}”",
    unanchored: "It concerns the whole screen: it has no precise point on the mockup.",
    show: "Show the screen “{title}”",
    severity: {
      critical: "Critical",
      major: "Major",
      moderate: "Moderate",
      minor: "Minor",
      observation: "Note",
    },
  },
} as const;

const SEVERITY_STYLES: Record<MockupSeverity, string> = {
  critical: "bg-fail-on-night/12 text-fail-on-night",
  major: "bg-warn-on-night/12 text-warn-on-night",
  moderate: "bg-on-night/8 text-on-night-2",
  minor: "bg-on-night/8 text-on-night-2",
  observation: "bg-on-night/8 text-on-night-2",
};

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, summary, [tabindex]";

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { locale: appLocale } = useI18n({ useScope: "global" });

const lang = computed<Locale>(() => props.locale ?? (appLocale.value === "it" ? "it" : "en"));
const copy = computed(() => messages[lang.value]);
const whyContext = inject(whyContextKey, null);
const hasSidecar = computed(
  () => items.value.length > 0 || (whyContext !== null && props.document !== null),
);

const overlay = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const tablist = ref<HTMLElement | null>(null);
const titleId = useId();
const listTitleId = useId();
const noteId = useId();
const regionId = useId();
const tabPrefix = useId();

const requested = ref<string | null>(null);
const reloads = ref(0);
const focusIndex = ref(0);
const width = ref<FrameWidth>(initialWidth());
const knownScreens = ref<readonly MockupScreen[]>([]);

let opener: HTMLElement | null = null;
let focusScreen: string | null = null;
let showing = true;

const screens = computed<readonly MockupScreen[]>(
  () => props.document?.screens ?? knownScreens.value,
);

const selectedScreen = computed(
  () => requested.value ?? props.document?.entry_screen ?? screens.value[0]?.code ?? null,
);

const selectedIndex = computed(() =>
  screens.value.findIndex((screen) => screen.code === selectedScreen.value),
);

const widthOptions = computed(() =>
  (["desktop", "tablet", "phone"] as const).map((value) => ({
    value,
    label: copy.value.widths[value],
    testId: `mockup-dialog-width-${value}`,
  })),
);

const frameKey = computed(() =>
  props.document === null
    ? "empty"
    : `${props.document.content_hash}|${props.document.entry_screen}|${reloads.value}`,
);

const frameTitle = computed(() => {
  const screen = screens.value.find((item) => item.code === props.document?.entry_screen);
  const label = screen === undefined ? props.title : `${props.title} · ${screen.title}`;
  return fill(copy.value.frame, { title: label });
});

const naming = computed<ScreenNaming>(() => {
  const places = props.observations.map((observation) => observation.place);
  return {
    screens: [...screens.value, ...placeScreens(places)],
    elements: { ...props.elements, ...elementNames(places) },
    workflows: props.workflows,
    locale: lang.value,
  };
});

const items = computed(() =>
  [...props.observations]
    .sort((first, second) => first.number - second.number)
    .map((observation) => {
      const pin = props.pins.find((item) => item.number === observation.number);
      const loose = props.unanchored.find((item) => item.number === observation.number);
      const screen = pin?.screen_code ?? loose?.screen_code ?? null;
      return {
        observation,
        text: withScreenNames(observation.text, naming.value),
        place: observation.place
          ? withScreenNames(placeLabel(observation.place), naming.value)
          : "",
        anchored: pin !== undefined,
        screen,
        screenTitle: screen === null ? null : titleOf(screen),
      };
    }),
);

const countLabel = computed(() =>
  items.value.length === 1 ? copy.value.one : fill(copy.value.many, { n: items.value.length }),
);

function initialWidth(): FrameWidth {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "desktop";
  }
  return window.matchMedia("(max-width: 639px)").matches ? "phone" : "desktop";
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function titleOf(code: string): string | null {
  return screens.value.find((screen) => screen.code === code)?.title ?? null;
}

function tabId(index: number): string {
  return `${tabPrefix}-${index}`;
}

function tabOf(code: string): HTMLElement | null {
  const tabs = tablist.value?.querySelectorAll<HTMLElement>("[role='tab']") ?? [];
  return [...tabs].find((tab) => tab.dataset.screen === code) ?? null;
}

function focusLost(): boolean {
  const active = document.activeElement;
  const root = overlay.value;
  return active === null || active === document.body || root === null || !root.contains(active);
}

function keepFocus(): void {
  const code = focusScreen;
  if (!showing || code === null) {
    return;
  }
  if (focusLost()) {
    (tabOf(code) ?? panel.value)?.focus();
  }
  if (props.document?.entry_screen === code && !props.busy) {
    focusScreen = null;
  }
}

async function requestScreen(code: string): Promise<void> {
  focusScreen = code;
  if (code === selectedScreen.value) {
    reloads.value += 1;
  } else {
    requested.value = code;
    emit("screen", code);
  }
  await nextTick();
  keepFocus();
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key !== "Escape" || event.defaultPrevented) {
    return;
  }
  event.preventDefault();
  emit("close");
}

function onDocumentFocus(event: FocusEvent): void {
  const root = overlay.value;
  if (!showing || root === null || !(event.target instanceof Node) || root.contains(event.target)) {
    return;
  }
  panel.value?.focus();
}

function onFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget;
  if (next instanceof Node && overlay.value?.contains(next)) {
    return;
  }
  void nextTick().then(() => {
    if (showing && focusLost()) {
      ((focusScreen === null ? null : tabOf(focusScreen)) ?? panel.value)?.focus();
    }
  });
}

function moveFocus(event: KeyboardEvent): void {
  const count = screens.value.length;
  const targets: Record<string, number> = {
    ArrowRight: focusIndex.value + 1,
    ArrowLeft: focusIndex.value - 1,
    Home: 0,
    End: count - 1,
  };
  const target = targets[event.key];
  if (target === undefined || count === 0) {
    return;
  }
  event.preventDefault();
  focusIndex.value = (target + count) % count;
  tablist.value?.querySelectorAll<HTMLElement>("[role='tab']")[focusIndex.value]?.focus();
}

function focusables(): HTMLElement[] {
  const root = panel.value;
  if (root === null) {
    return [];
  }
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) =>
      element.tabIndex >= 0 &&
      element.closest("[inert], [hidden]") === null &&
      visibleInDetails(element),
  );
}

function visibleInDetails(element: HTMLElement): boolean {
  let details = element.parentElement?.closest("details:not([open])") ?? null;
  while (details !== null) {
    if (!details.querySelector(":scope > summary")?.contains(element)) return false;
    details = details.parentElement?.closest("details:not([open])") ?? null;
  }
  return true;
}

function focusFirst(): void {
  (focusables()[0] ?? panel.value)?.focus();
}

function focusLast(): void {
  (focusables().at(-1) ?? panel.value)?.focus();
}

watch(
  () => props.document?.screens,
  (value) => {
    if (value !== undefined && value.length > 0) {
      knownScreens.value = value;
    }
  },
  { immediate: true },
);

watch(
  () => props.document?.entry_screen,
  () => {
    requested.value = null;
  },
);

watch(frameKey, async () => {
  await nextTick();
  keepFocus();
});

watch(
  () => props.busy,
  (busy) => {
    if (!busy && requested.value !== null && requested.value !== props.document?.entry_screen) {
      requested.value = null;
    }
  },
);

watch(
  selectedIndex,
  (index) => {
    focusIndex.value = Math.max(0, index);
  },
  { immediate: true },
);

onMounted(async () => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  document.addEventListener("keydown", onDocumentKeydown);
  document.addEventListener("focusin", onDocumentFocus);
  await nextTick();
  panel.value?.focus();
});

onUnmounted(() => {
  showing = false;
  document.removeEventListener("keydown", onDocumentKeydown);
  document.removeEventListener("focusin", onDocumentFocus);
  if (opener?.isConnected) {
    opener.focus();
  }
  opener = null;
});
</script>

<template>
  <Teleport to="body">
    <div
      ref="overlay"
      class="fixed inset-0 z-50 flex items-stretch justify-center sm:items-center sm:p-6 lg:p-8"
      data-surface="night"
      data-testid="mockup-dialog"
      @focusout="onFocusOut"
    >
      <div
        class="absolute inset-0 bg-night-deep/75"
        aria-hidden="true"
        data-testid="mockup-dialog-veil"
        @click="emit('close')"
      />
      <span
        tabindex="0"
        class="pointer-events-none fixed top-0 left-0 h-px w-px opacity-0"
        data-focus-guard="start"
        @focus="focusLast"
      />
      <section
        ref="panel"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        class="relative flex h-full w-full max-w-[1360px] flex-col overflow-hidden bg-night-panel text-on-night shadow-dialog outline-none sm:rounded-[20px] sm:border sm:border-night-line-strong"
        data-testid="mockup-dialog-panel"
      >
        <header
          class="flex flex-col gap-2.5 border-b border-night-line bg-night-panel py-3 pr-3 pl-4 sm:pl-5"
        >
          <div class="flex items-center gap-3">
            <h2 :id="titleId" class="min-w-0 flex-1 text-base font-semibold break-words">
              {{ title }}
            </h2>
            <p class="hidden text-[13px] text-on-night-3 lg:block">{{ copy.hint }}</p>
            <button
              type="button"
              class="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-pill bg-on-night/8 text-lg text-on-night transition-colors duration-150 hover:bg-on-night/16"
              :aria-label="copy.close"
              data-testid="mockup-dialog-close"
              @click="emit('close')"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
            <div
              ref="tablist"
              role="tablist"
              :aria-label="copy.screens"
              class="-mx-1.5 flex min-w-0 flex-[1_1_320px] flex-wrap gap-1 p-1.5"
              data-testid="mockup-dialog-screens"
              @keydown="moveFocus"
            >
              <button
                v-for="(screen, index) in screens"
                :id="tabId(index)"
                :key="screen.code"
                type="button"
                role="tab"
                :title="screen.title"
                :aria-selected="screen.code === selectedScreen ? 'true' : 'false'"
                :aria-controls="regionId"
                :tabindex="index === focusIndex ? 0 : -1"
                :class="[
                  'inline-flex min-h-11 max-w-[calc(28ch+1.75rem)] min-w-0 items-center rounded-pill px-3.5 text-[13px] font-medium transition-colors duration-150',
                  screen.code === selectedScreen
                    ? 'bg-on-night text-ink'
                    : 'text-on-night hover:bg-night-hover',
                ]"
                :data-screen="screen.code"
                data-testid="mockup-dialog-screen"
                @click="requestScreen(screen.code)"
              >
                <span class="truncate" data-testid="mockup-dialog-screen-title">{{
                  screen.title
                }}</span>
              </button>
            </div>
            <UiSegmented
              v-model="width"
              :options="widthOptions"
              :label="copy.width"
              kind="radio"
              class="shrink-0"
            />
          </div>
        </header>
        <div
          :class="[
            'min-h-0 flex-1 overflow-y-auto overscroll-contain',
            hasSidecar
              ? 'xl:grid xl:grid-cols-[minmax(0,1fr)_360px] xl:overflow-hidden'
              : 'flex flex-col',
          ]"
        >
          <div
            :id="regionId"
            role="tabpanel"
            :aria-labelledby="selectedIndex >= 0 ? tabId(selectedIndex) : titleId"
            :aria-busy="busy ? 'true' : undefined"
            :class="[
              'relative bg-night-deep',
              hasSidecar ? 'h-[70dvh] min-h-[360px] xl:h-full xl:min-h-0' : 'min-h-[360px] flex-1',
            ]"
            data-testid="mockup-dialog-stage"
          >
            <GeneratedMockupFrame
              v-if="document !== null"
              :key="frameKey"
              :html="document.html"
              :title="frameTitle"
              :width="width"
            />
            <div v-else class="grid h-full place-items-center p-6">
              <UiStateBlock
                :kind="busy ? 'loading' : 'empty'"
                :title="busy ? copy.opening : copy.empty"
              />
            </div>
            <p
              v-if="busy && document !== null"
              role="status"
              class="pointer-events-none absolute top-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-2 rounded-pill border border-night-line-strong bg-night-panel/94 px-4 py-2 text-sm whitespace-nowrap text-on-night-2 shadow-bar"
              data-testid="mockup-dialog-busy"
            >
              <span
                class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
                aria-hidden="true"
              />
              {{ copy.opening }}
            </p>
          </div>
          <div
            v-if="hasSidecar"
            class="min-h-0 min-w-0 xl:overflow-y-auto"
            data-testid="mockup-dialog-sidecar"
          >
            <MockupWhyElements
              v-if="document !== null"
              :alternative-id="document.alternative_id"
              :document-hash="document.content_hash"
              :screen-code="selectedScreen ?? ''"
              :locale="lang"
            />
            <MockupScenarioWalkthrough
              v-if="document !== null"
              :alternative-id="document.alternative_id"
              :document-hash="document.content_hash"
              :screen-codes="screens.map((screen) => screen.code)"
              :locale="lang"
              @screen="requestScreen"
            />
            <aside
              v-if="items.length > 0"
              class="flex min-h-0 flex-col border-t border-night-line xl:border-t-0 xl:border-l"
              :aria-labelledby="listTitleId"
              data-testid="mockup-dialog-observations"
            >
              <div class="grid gap-2 border-b border-night-line px-4 pt-4 pb-3">
                <div class="flex items-baseline gap-2">
                  <h3 :id="listTitleId" class="flex-1 text-[17px] font-semibold">
                    {{ copy.observations }}
                  </h3>
                  <span class="text-[13px] text-on-night-3">{{ countLabel }}</span>
                </div>
                <p :id="noteId" class="text-xs leading-normal text-violet-on-night-2">
                  {{ copy.note }}
                </p>
              </div>
              <ol
                class="grid list-none content-start gap-2.5 p-3 md:grid-cols-2 xl:min-h-0 xl:flex-1 xl:grid-cols-1 xl:overflow-y-auto"
                :aria-describedby="noteId"
              >
                <li
                  v-for="item in items"
                  :key="item.observation.number"
                  class="grid gap-[7px] rounded-[14px] border-[1.5px] border-dashed border-violet-on-night/70 bg-on-night/3 p-3.5"
                  :data-number="item.observation.number"
                  :data-anchored="item.anchored ? 'true' : 'false'"
                  data-testid="mockup-dialog-observation"
                >
                  <div class="flex flex-wrap items-center gap-2">
                    <span
                      :class="[
                        'inline-flex h-6 min-w-6 items-center justify-center rounded-xl px-1.5 text-xs font-bold',
                        item.anchored
                          ? 'bg-violet-on-night text-night'
                          : 'border border-violet-on-night text-violet-on-night-2',
                      ]"
                      data-testid="mockup-dialog-number"
                    >
                      {{ item.observation.number }}
                    </span>
                    <span
                      :class="[
                        'inline-flex min-h-6 items-center rounded-pill px-[9px] text-xs font-semibold',
                        SEVERITY_STYLES[item.observation.severity],
                      ]"
                    >
                      {{ copy.severity[item.observation.severity] }}
                    </span>
                    <span class="ml-auto text-xs text-on-night-3">
                      {{ item.observation.twin_name }}
                    </span>
                  </div>
                  <p class="text-[15px] leading-[1.4] font-semibold text-on-night">
                    {{ item.text }}
                  </p>
                  <p v-if="item.place" class="text-[13px] text-on-night-3">
                    {{ copy.where }}: {{ item.place }}
                  </p>
                  <p v-if="item.screenTitle !== null" class="text-[13px] text-on-night-3">
                    {{ fill(copy.screen, { title: item.screenTitle }) }}
                  </p>
                  <p v-if="!item.anchored" class="text-xs leading-normal text-violet-on-night-2">
                    {{ copy.unanchored }}
                  </p>
                  <button
                    v-if="
                      item.screen !== null &&
                      item.screenTitle !== null &&
                      item.screen !== selectedScreen
                    "
                    type="button"
                    class="inline-flex min-h-11 items-center self-start text-left text-[13px] font-medium text-petrol-on-night-2 underline underline-offset-4 transition-colors duration-150 hover:text-on-night"
                    data-testid="mockup-dialog-show-screen"
                    @click="requestScreen(item.screen)"
                  >
                    {{ fill(copy.show, { title: item.screenTitle }) }}
                  </button>
                </li>
              </ol>
            </aside>
          </div>
        </div>
      </section>
      <span
        tabindex="0"
        class="pointer-events-none fixed top-0 left-0 h-px w-px opacity-0"
        data-focus-guard="end"
        @focus="focusFirst"
      />
    </div>
  </Teleport>
</template>
