<script setup lang="ts">
import { computed, ref, useId } from "vue";

import { useSurface } from "./UiSurface.vue";
import ArtifactWhy from "./ArtifactWhy.vue";

export interface ArtifactTableColumn {
  key: string;
  label: string;
  numeric?: boolean | undefined;
  sortable?: boolean | undefined;
  sortKey?: string | undefined;
  strong?: boolean | undefined;
  missing?: string | undefined;
  nowrap?: boolean | undefined;
}

type Locale = "en" | "it";
type SortDirection = "ascending" | "descending";

interface ActiveSort {
  key: string;
  direction: SortDirection;
}

const props = withDefaults(
  defineProps<{
    caption: string;
    columns: readonly ArtifactTableColumn[];
    rows: readonly Record<string, string>[];
    rowKey: string;
    locale?: Locale;
    emptyText?: string | undefined;
    why?: boolean;
    versionNumber?: number | undefined;
    contentHash?: string | undefined;
  }>(),
  { locale: "en", emptyText: undefined },
);

const messages = {
  en: {
    empty: "Nothing to show yet.",
    emptyCell: "empty",
    oneRow: "1 row",
    manyRows: "{count} rows",
  },
  it: {
    empty: "Ancora nulla da mostrare.",
    emptyCell: "vuoto",
    oneRow: "1 riga",
    manyRows: "{count} righe",
  },
} as const;

const palettes = {
  light: {
    empty: "rounded-panel border-line-soft bg-surface-2 text-ink-2",
    region: "rounded-panel border-line bg-surface",
    head: "border-line bg-surface-3",
    heading: "text-ink",
    sort: "text-ink hover:text-action",
    symbol: "text-ink-3",
    row: "border-line-soft even:bg-row-alt",
    key: "text-ink",
    cell: "text-ink-2",
    missing: "font-medium text-warn",
    count: "text-ink-3",
  },
  night: {
    empty: "rounded-tile border-night-line bg-night-raised text-on-night-2",
    region: "rounded-tile border-night-line bg-night-raised",
    head: "border-night-line bg-on-night/3",
    heading: "text-on-night-2",
    sort: "text-on-night-2 hover:text-on-night",
    symbol: "text-on-night-3",
    row: "border-on-night/8",
    key: "text-on-night",
    cell: "text-on-night",
    missing: "font-medium text-warn-on-night",
    count: "text-on-night-3",
  },
};

const captionId = `artifact-table-${useId()}`;
const copy = computed(() => messages[props.locale]);
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
const activeSort = ref<ActiveSort | null>(null);

const headerKey = computed(
  () => props.columns.find((column) => column.key === props.rowKey)?.key ?? props.columns[0]?.key,
);

const sortedRows = computed<readonly Record<string, string>[]>(() => {
  const active = activeSort.value;

  if (active === null) {
    return props.rows;
  }

  const valueKey = props.columns.find((column) => column.key === active.key)?.sortKey ?? active.key;
  const factor = active.direction === "ascending" ? 1 : -1;

  return [...props.rows].sort(
    (left, right) =>
      factor *
      (left[valueKey] ?? "").localeCompare(right[valueKey] ?? "", props.locale, {
        numeric: true,
        sensitivity: "base",
      }),
  );
});

const widthClasses = computed<Record<string, string>>(() =>
  Object.fromEntries(props.columns.map((column) => [column.key, widthClass(column)])),
);

const countLabel = computed(() =>
  props.rows.length === 1
    ? copy.value.oneRow
    : copy.value.manyRows.replace("{count}", String(props.rows.length)),
);

function longestLine(text: string): number {
  return Math.max(...text.split("\n").map((line) => line.length));
}

function widthClass(column: ArtifactTableColumn): string {
  if (column.key === headerKey.value || column.numeric === true) {
    return "whitespace-nowrap";
  }

  if (column.nowrap === true) {
    return "whitespace-pre";
  }

  const longest = Math.max(0, ...props.rows.map((row) => longestLine(row[column.key] ?? "")));

  if (longest > 80) {
    return "min-w-60 whitespace-pre-line";
  }

  if (longest > 40) {
    return "min-w-44 whitespace-pre-line";
  }

  if (longest > 24) {
    return "min-w-36 whitespace-pre-line";
  }

  return "whitespace-pre";
}

function ariaSort(column: ArtifactTableColumn): SortDirection | "none" | undefined {
  if (column.sortable !== true) {
    return undefined;
  }

  const active = activeSort.value;

  return active !== null && active.key === column.key ? active.direction : "none";
}

function sortSymbol(column: ArtifactTableColumn): string {
  const state = ariaSort(column);

  if (state === "ascending") {
    return "↑";
  }

  return state === "descending" ? "↓" : "↕";
}

function toggleSort(key: string): void {
  const active = activeSort.value;

  if (active === null || active.key !== key) {
    activeSort.value = { key, direction: "ascending" };
  } else if (active.direction === "ascending") {
    activeSort.value = { key, direction: "descending" };
  } else {
    activeSort.value = null;
  }
}

function isEmpty(value: string | undefined): boolean {
  return value === undefined || value.trim().length === 0;
}
</script>

<template>
  <div class="grid gap-2" data-testid="artifact-table" :data-surface-context="surface">
    <p
      v-if="rows.length === 0"
      :class="['m-0 border p-4 text-sm', palette.empty]"
      data-testid="artifact-table-empty"
    >
      {{ emptyText ?? copy.empty }}
    </p>

    <template v-else>
      <div
        :class="['overflow-x-auto border', palette.region]"
        role="region"
        tabindex="0"
        :aria-labelledby="captionId"
        data-testid="artifact-table-region"
      >
        <table class="w-full border-collapse text-left text-sm">
          <caption :id="captionId" class="sr-only">
            {{
              caption
            }}
          </caption>
          <thead :class="['border-b', palette.head]">
            <tr>
              <th
                v-for="column in columns"
                :key="column.key"
                scope="col"
                :class="[
                  'px-3 py-3 align-bottom text-[13px] font-semibold whitespace-nowrap first:pl-5 last:pr-5',
                  palette.heading,
                  column.numeric ? 'text-right' : '',
                ]"
                :aria-sort="ariaSort(column)"
                :data-column="column.key"
              >
                <button
                  v-if="column.sortable"
                  type="button"
                  :class="[
                    '-mx-1 -my-2 inline-flex min-h-11 items-center gap-1.5 rounded-control px-1 font-semibold transition-colors duration-150',
                    palette.sort,
                  ]"
                  :data-testid="`sort-${column.key}`"
                  @click="toggleSort(column.key)"
                >
                  {{ column.label }}
                  <span :class="palette.symbol" aria-hidden="true">{{ sortSymbol(column) }}</span>
                </button>
                <template v-else>{{ column.label }}</template>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in sortedRows"
              :key="row[rowKey] ?? index"
              :class="['border-t align-top first:border-t-0', palette.row]"
              :data-row-key="row[rowKey]"
            >
              <template v-for="column in columns" :key="column.key">
                <th
                  v-if="column.key === headerKey"
                  scope="row"
                  :class="[
                    'px-3 py-3.5 font-mono text-xs leading-6 font-medium first:pl-5 last:pr-5',
                    palette.key,
                    widthClasses[column.key],
                  ]"
                  :data-column="column.key"
                >
                  <span v-if="isEmpty(row[column.key])" role="img" :aria-label="copy.emptyCell"
                    >—</span
                  >
                  <template v-else>{{ row[column.key] }}</template>
                  <ArtifactWhy
                    v-if="why"
                    :code="row[rowKey] ?? ''"
                    :title="row.title ?? row.goal ?? row.statement"
                    :version-number="versionNumber"
                    :content-hash="contentHash"
                    :locale="locale"
                    test-id="table-why"
                    class="mt-2 font-sans"
                  />
                </th>
                <td
                  v-else
                  :class="[
                    'px-3 py-3.5 leading-normal first:pl-5 last:pr-5',
                    palette.cell,
                    widthClasses[column.key],
                    column.numeric ? 'text-right tabular-nums' : '',
                    column.strong ? 'font-semibold' : '',
                  ]"
                  :data-column="column.key"
                >
                  <template v-if="isEmpty(row[column.key])">
                    <span v-if="column.missing" :class="palette.missing" data-missing>{{
                      column.missing
                    }}</span>
                    <span v-else role="img" :aria-label="copy.emptyCell">—</span>
                  </template>
                  <template v-else>{{ row[column.key] }}</template>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <p :class="['m-0 text-xs', palette.count]" data-testid="artifact-table-count">
        {{ countLabel }}
      </p>
    </template>
  </div>
</template>
