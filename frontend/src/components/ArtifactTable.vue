<script setup lang="ts">
import { computed, ref, useId } from "vue";

export interface ArtifactTableColumn {
  key: string;
  label: string;
  numeric?: boolean | undefined;
  sortable?: boolean | undefined;
  sortKey?: string | undefined;
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

const captionId = `artifact-table-${useId()}`;
const copy = computed(() => messages[props.locale]);
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

  const longest = Math.max(0, ...props.rows.map((row) => longestLine(row[column.key] ?? "")));

  if (longest > 80) {
    return "min-w-72 whitespace-pre-line";
  }

  if (longest > 40) {
    return "min-w-56 whitespace-pre-line";
  }

  if (longest > 24) {
    return "min-w-40 whitespace-pre-line";
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
  <div class="grid gap-2" data-testid="artifact-table">
    <p
      v-if="rows.length === 0"
      class="m-0 rounded-panel border border-line-soft bg-surface-2 p-4 text-sm text-ink-2"
      data-testid="artifact-table-empty"
    >
      {{ emptyText ?? copy.empty }}
    </p>

    <template v-else>
      <div
        class="overflow-x-auto rounded-panel border border-line bg-surface"
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
          <thead class="bg-surface-3">
            <tr>
              <th
                v-for="column in columns"
                :key="column.key"
                scope="col"
                class="px-3 py-2.5 align-bottom text-[13px] font-semibold whitespace-nowrap text-ink"
                :class="column.numeric ? 'text-right' : ''"
                :aria-sort="ariaSort(column)"
                :data-column="column.key"
              >
                <button
                  v-if="column.sortable"
                  type="button"
                  class="-mx-1 inline-flex items-center gap-1.5 rounded-control px-1 py-0.5 font-semibold text-ink hover:text-action"
                  :data-testid="`sort-${column.key}`"
                  @click="toggleSort(column.key)"
                >
                  {{ column.label }}
                  <span class="text-ink-3" aria-hidden="true">{{ sortSymbol(column) }}</span>
                </button>
                <template v-else>{{ column.label }}</template>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, index) in sortedRows"
              :key="row[rowKey] ?? index"
              class="border-t border-line-soft align-top even:bg-row-alt"
              :data-row-key="row[rowKey]"
            >
              <template v-for="column in columns" :key="column.key">
                <th
                  v-if="column.key === headerKey"
                  scope="row"
                  class="px-3 py-2.5 font-mono text-xs leading-6 font-semibold text-ink"
                  :class="widthClasses[column.key]"
                  :data-column="column.key"
                >
                  <span v-if="isEmpty(row[column.key])" role="img" :aria-label="copy.emptyCell"
                    >—</span
                  >
                  <template v-else>{{ row[column.key] }}</template>
                </th>
                <td
                  v-else
                  class="px-3 py-2.5 leading-6 text-ink-2"
                  :class="[
                    widthClasses[column.key],
                    column.numeric ? 'text-right tabular-nums' : '',
                  ]"
                  :data-column="column.key"
                >
                  <span v-if="isEmpty(row[column.key])" role="img" :aria-label="copy.emptyCell"
                    >—</span
                  >
                  <template v-else>{{ row[column.key] }}</template>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="m-0 text-xs text-ink-3" data-testid="artifact-table-count">{{ countLabel }}</p>
    </template>
  </div>
</template>
