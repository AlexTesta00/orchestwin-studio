<script lang="ts">
export type TwinMatrixSeverity = "critical" | "major" | "moderate" | "minor" | "observation";

export interface TwinMatrixAlternative {
  id: string;
  code: string;
  title: string;
}

export interface TwinMatrixTwin {
  id: string;
  name: string;
  avatar?: string | null | undefined;
}

export interface TwinMatrixCell {
  twin: string;
  alternative: string;
  verdict?: string | null | undefined;
  quote?: string | null | undefined;
  count: number;
  strengths?: readonly string[] | undefined;
  concerns?: readonly string[] | undefined;
  severity?: TwinMatrixSeverity | null | undefined;
}

export interface TwinMatrixSelection {
  twin: string;
  alternative: string;
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, provide, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    alternatives: readonly TwinMatrixAlternative[];
    twins: readonly TwinMatrixTwin[];
    cells: readonly TwinMatrixCell[];
    selected?: TwinMatrixSelection | null | undefined;
    locale?: Locale | undefined;
  }>(),
  { selected: null, locale: undefined },
);

const emit = defineEmits<{ select: [selection: TwinMatrixSelection] }>();

const messages = {
  it: {
    title: "Il parere dei twin",
    simulated: "Feedback simulato, non prove",
    caption: "Il parere di ogni twin su ogni alternativa di design",
    twin: "Twin",
    none: "Nessuna osservazione",
    one: "1 osservazione",
    many: "{n} osservazioni",
    worst: "la più grave è {severity}",
    severity: { critical: "critica", major: "importante" },
    empty: "Nessun parere su questa alternativa",
  },
  en: {
    title: "What the twins think",
    simulated: "Simulated feedback, not evidence",
    caption: "What each twin thinks of each design alternative",
    twin: "Twin",
    none: "No observations",
    one: "1 observation",
    many: "{n} observations",
    worst: "the most serious is {severity}",
    severity: { critical: "critical", major: "major" },
    empty: "No opinion on this alternative",
  },
} as const;

const TWIN_COLUMN = 170;
const CELL_MINIMUM = 170;
const SPACING = 8;
const ROW_GRID =
  "grid grid-cols-[170px_repeat(var(--twin-matrix-alternatives),minmax(0,1fr))] gap-2";

const TONES = {
  critical: "bg-fail-on-night/12 text-fail-on-night",
  major: "bg-warn-on-night/12 text-warn-on-night",
  neutral: "bg-on-night/8 text-on-night-2",
};

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const { locale: appLocale } = useI18n({ useScope: "global" });

const lang = computed<Locale>(() => props.locale ?? (appLocale.value === "it" ? "it" : "en"));
const copy = computed(() => messages[lang.value]);

const titleId = useId();
const area = ref<HTMLElement | null>(null);
const available = ref(0);
let observer: ResizeObserver | null = null;

const wide = computed(
  () =>
    available.value > 0 &&
    available.value >= TWIN_COLUMN + props.alternatives.length * (CELL_MINIMUM + SPACING),
);

const cellIndex = computed(() => {
  const index = new Map<string, TwinMatrixCell>();
  for (const cell of props.cells) {
    index.set(`${cell.twin}\u0000${cell.alternative}`, cell);
  }
  return index;
});

const rows = computed(() =>
  props.twins.map((twin) => ({
    twin,
    initials: initialsOf(twin.name),
    cells: props.alternatives.map((alternative) => {
      const cell = cellIndex.value.get(`${twin.id}\u0000${alternative.id}`) ?? null;
      return {
        alternative,
        cell,
        selected:
          props.selected !== null &&
          props.selected.twin === twin.id &&
          props.selected.alternative === alternative.id,
        verdict: cell?.verdict?.trim() || null,
        quote: cell?.quote?.trim() || null,
        text: fallbackText(cell),
        count: countLabel(cell),
        tone: toneOf(cell),
      };
    }),
  })),
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/u).filter(Boolean);
  const first = words[0];
  if (first === undefined) {
    return "UT";
  }
  const last = words.length > 1 ? words.at(-1) : undefined;
  return [first, last]
    .filter((word): word is string => word !== undefined)
    .map((word) => [...word][0] ?? "")
    .join("")
    .toLocaleUpperCase();
}

function fallbackText(cell: TwinMatrixCell | null): string | null {
  if (cell === null || cell.verdict?.trim() || cell.quote?.trim()) {
    return null;
  }
  const first =
    cell.strengths?.find((item) => item.trim()) ?? cell.concerns?.find((item) => item.trim());
  return first?.trim() ?? null;
}

function countLabel(cell: TwinMatrixCell | null): string {
  const count = cell?.count ?? 0;
  const base =
    count <= 0
      ? copy.value.none
      : count === 1
        ? copy.value.one
        : fill(copy.value.many, { n: count });
  const severity = cell?.severity;
  if (count > 0 && (severity === "critical" || severity === "major")) {
    return `${base} · ${fill(copy.value.worst, { severity: copy.value.severity[severity] })}`;
  }
  return base;
}

function toneOf(cell: TwinMatrixCell | null): string {
  if (cell?.severity === "critical") {
    return TONES.critical;
  }
  if (cell?.severity === "major") {
    return TONES.major;
  }
  return TONES.neutral;
}

function choose(twin: string, alternative: string): void {
  emit("select", { twin, alternative });
}

function measure(): void {
  available.value = area.value?.clientWidth ?? 0;
}

onMounted(() => {
  measure();
  if (typeof ResizeObserver === "undefined" || area.value === null) {
    return;
  }
  observer = new ResizeObserver(measure);
  observer.observe(area.value);
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});
</script>

<template>
  <section
    class="rounded-tile border border-night-line bg-night-raised p-4 text-on-night sm:p-6"
    data-surface="night"
    :aria-labelledby="titleId"
    data-testid="design-twin-matrix"
  >
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <h2 :id="titleId" class="min-w-0 flex-[1_1_14rem] text-xl font-semibold">{{ copy.title }}</h2>
      <span
        class="inline-flex min-h-7 items-center gap-1.5 rounded-pill border border-dashed border-violet-on-night px-3 text-xs font-medium whitespace-nowrap text-violet-on-night-2"
        data-testid="design-twin-matrix-simulated"
      >
        <span
          class="inline-block h-2 w-2 shrink-0 rounded-full border-[1.5px] border-violet-on-night"
          aria-hidden="true"
        />
        {{ copy.simulated }}
      </span>
    </div>
    <div ref="area" :data-layout="wide ? 'table' : 'stack'" data-testid="design-twin-matrix-area">
      <table
        role="table"
        :class="wide ? 'grid w-full gap-2' : 'block w-full'"
        :style="wide ? { '--twin-matrix-alternatives': alternatives.length } : undefined"
      >
        <caption class="sr-only">
          {{
            copy.caption
          }}
        </caption>
        <thead role="rowgroup" :class="wide ? 'block' : 'sr-only'">
          <tr role="row" :class="wide ? ROW_GRID : undefined">
            <th role="columnheader" scope="col" class="p-0">
              <span class="sr-only">{{ copy.twin }}</span>
            </th>
            <th
              v-for="alternative in alternatives"
              :key="alternative.id"
              role="columnheader"
              scope="col"
              class="self-end px-1 pb-0.5 text-left font-mono text-[11px] font-normal tracking-label break-words text-on-night-3 uppercase"
              :data-alternative="alternative.id"
            >
              {{ alternative.code }} · {{ alternative.title }}
            </th>
          </tr>
        </thead>
        <tbody role="rowgroup" :class="wide ? 'grid gap-2' : 'grid gap-3'">
          <tr
            v-for="row in rows"
            :key="row.twin.id"
            role="row"
            :class="
              wide ? ROW_GRID : 'grid gap-2 rounded-tile border border-night-line bg-on-night/3 p-3'
            "
            :data-twin="row.twin.id"
            data-testid="design-twin-matrix-row"
          >
            <th
              role="rowheader"
              scope="row"
              :class="['p-0 text-left font-semibold', wide ? 'flex items-center pr-2' : 'pb-1']"
            >
              <span class="flex items-center gap-2.5 text-sm leading-[1.3]">
                <span
                  class="inline-flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 border-dashed border-violet-on-night text-[13px] font-semibold text-violet-on-night-2"
                  aria-hidden="true"
                  data-testid="design-twin-matrix-avatar"
                >
                  <img
                    v-if="row.twin.avatar"
                    :src="row.twin.avatar"
                    alt=""
                    width="40"
                    height="40"
                    decoding="async"
                    class="h-full w-full object-cover"
                  />
                  <template v-else>{{ row.initials }}</template>
                </span>
                <span class="min-w-0 break-words">{{ row.twin.name }}</span>
              </span>
            </th>
            <td
              v-for="entry in row.cells"
              :key="entry.alternative.id"
              role="cell"
              :class="['p-0', wide ? 'flex' : 'align-top']"
            >
              <button
                type="button"
                :aria-pressed="entry.selected ? 'true' : 'false'"
                :class="[
                  'flex min-h-24 w-full flex-col items-start gap-1.5 rounded-field text-left text-on-night transition-colors duration-150 hover:bg-night-hover',
                  entry.selected
                    ? 'border-2 border-petrol-on-night bg-on-night/6 px-[13px] py-[11px]'
                    : 'border border-night-line bg-on-night/3 px-3.5 py-3',
                ]"
                :data-twin="row.twin.id"
                :data-alternative="entry.alternative.id"
                data-testid="design-twin-matrix-cell"
                @click="choose(row.twin.id, entry.alternative.id)"
              >
                <span class="sr-only">{{ row.twin.name }}, </span>
                <span
                  :class="[
                    'font-mono text-[11px] tracking-label text-on-night-3 uppercase',
                    wide ? 'sr-only' : '',
                  ]"
                  data-testid="design-twin-matrix-cell-alternative"
                >
                  {{ entry.alternative.code }} · {{ entry.alternative.title
                  }}<span class="sr-only">, </span>
                </span>
                <span
                  v-if="entry.verdict"
                  :class="[
                    'inline-flex min-h-6 items-center self-start rounded-pill px-[9px] text-xs font-semibold',
                    entry.tone,
                  ]"
                  data-testid="design-twin-matrix-verdict"
                >
                  {{ entry.verdict }}
                </span>
                <span
                  v-if="entry.quote"
                  class="text-sm leading-[1.45] text-on-night-2"
                  data-testid="design-twin-matrix-quote"
                >
                  «{{ entry.quote }}»
                </span>
                <span
                  v-else-if="entry.text"
                  class="text-sm leading-[1.45] text-on-night-2"
                  data-testid="design-twin-matrix-text"
                >
                  {{ entry.text }}
                </span>
                <span v-else-if="!entry.verdict" class="text-sm leading-[1.45] text-on-night-3">
                  {{ copy.empty }}
                </span>
                <span
                  class="mt-auto pt-0.5 text-xs text-on-night-3"
                  data-testid="design-twin-matrix-count"
                >
                  {{ entry.count }}
                </span>
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="$slots.default" class="mt-7">
      <slot />
    </div>
  </section>
</template>
