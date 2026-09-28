<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useId, watch } from "vue";

import { apiClient } from "@/api/client";
import { designLoopApi, type InsightBatchApi } from "@/api/designLoop";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedDesignLoopRequest } from "@/stores/designLoop";
import { type InsightTrayItem, useInsightTrayStore } from "@/stores/insightTray";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: InsightBatchApi | undefined;
  }>(),
  { locale: "en", authorize: undefined, api: undefined },
);

const messages = {
  en: {
    region: "Insights for the brief",
    one: "1 insight set aside for the brief",
    many: "{count} insights set aside for the brief",
    apply: "Add to the brief as one version",
    applying: "Adding the insights to the brief…",
    clear: "Clear",
    remove: "Remove",
    close: "Close",
    doneOne:
      "1 insight added to the brief, version {version}. Brief, team, twins, requirements and design need approval again.",
    doneMany:
      "{count} insights added to the brief, version {version}. Brief, team, twins, requirements and design need approval again.",
    alreadyApplied: "One insight had already been applied: remove it and try again.",
    dismissed: "One insight comes from a dismissed observation: remove it and try again.",
    failed: "The operation failed: {code}",
    conflicts: {
      INSIGHT_ALREADY_APPLIED: "Already applied",
      INSIGHT_SOURCE_DISMISSED: "Dismissed observation",
    },
  },
  it: {
    region: "Spunti per il brief",
    one: "1 spunto messo da parte per il brief",
    many: "{count} spunti messi da parte per il brief",
    apply: "Porta nel brief in una sola versione",
    applying: "Porto gli spunti nel brief…",
    clear: "Svuota",
    remove: "Togli",
    close: "Chiudi",
    doneOne:
      "Aggiunto al brief 1 spunto, versione {version}. Brief, squadra, twin, requisiti e design vanno approvati di nuovo.",
    doneMany:
      "Aggiunti al brief {count} spunti, versione {version}. Brief, squadra, twin, requisiti e design vanno approvati di nuovo.",
    alreadyApplied: "Uno spunto era già stato applicato: toglilo e riprova.",
    dismissed: "Uno spunto viene da un'osservazione messa da parte: toglilo e riprova.",
    failed: "Operazione non riuscita: {code}",
    conflicts: {
      INSIGHT_ALREADY_APPLIED: "Già applicato",
      INSIGHT_SOURCE_DISMISSED: "Osservazione messa da parte",
    },
  },
} as const;

type ConflictCode = keyof (typeof messages)["en"]["conflicts"];

const auth = useAuthStore();
const tray = useInsightTrayStore();
const uid = useId();
const copy = computed(() => messages[props.locale]);
const items = computed(() => tray.itemsOf(props.projectId));
const result = computed(() => tray.resultOf(props.projectId));
const failure = computed(() => tray.failureOf(props.projectId));
const applying = computed(() => tray.isApplying(props.projectId));
const visible = computed(() => tray.isVisible(props.projectId));
const listOpen = ref(false);
const summary = ref<HTMLElement | null>(null);
const closeButton = ref<HTMLButtonElement | null>(null);

const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

const countText = computed(() =>
  items.value.length === 1 ? copy.value.one : fill(copy.value.many, { count: items.value.length }),
);
const done = computed(() => result.value !== null && items.value.length === 0);
const status = computed(() => {
  if (applying.value) return copy.value.applying;
  const value = result.value;
  if (value === null) return "";
  return fill(value.count === 1 ? copy.value.doneOne : copy.value.doneMany, {
    count: value.count,
    version: value.briefVersionNumber,
  });
});
const failureText = computed(() => {
  const value = failure.value;
  if (value === null) return null;
  if (value.code === "INSIGHT_ALREADY_APPLIED") return copy.value.alreadyApplied;
  if (value.code === "INSIGHT_SOURCE_DISMISSED") return copy.value.dismissed;
  return fill(copy.value.failed, { code: value.code });
});

function isConflictCode(code: string): code is ConflictCode {
  return code in messages.en.conflicts;
}

function conflictLabel(item: InsightTrayItem): string | null {
  const value = failure.value;
  if (value === null || !isConflictCode(value.code) || !value.sources.includes(item.sourceId)) {
    return null;
  }
  return copy.value.conflicts[value.code];
}

function itemKey(item: InsightTrayItem): string {
  return `${item.sourceKind}:${item.sourceId}`;
}

function textId(index: number): string {
  return `insight-brief-tray-${uid}-${index}`;
}

function onToggle(event: Event): void {
  listOpen.value = (event.target as HTMLDetailsElement).open;
}

async function remove(item: InsightTrayItem): Promise<void> {
  tray.remove(props.projectId, item.sourceKind, item.sourceId);
  await nextTick();
  summary.value?.focus();
}

async function applyAll(): Promise<void> {
  const projectId = props.projectId;
  try {
    const outcome = await tray.applyAll(projectId, props.api ?? designLoopApi, authorize);
    if (outcome === null) return;
    listOpen.value = false;
    await nextTick();
    closeButton.value?.focus();
  } catch {
    if ((tray.failureOf(projectId)?.sources.length ?? 0) > 0) listOpen.value = true;
  }
}

watch(
  () => props.projectId,
  (_next, previous) => {
    listOpen.value = false;
    tray.dismissResult(previous);
  },
);
onBeforeUnmount(() => tray.dismissResult(props.projectId));
</script>

<template>
  <section
    v-if="visible"
    role="region"
    :aria-label="copy.region"
    class="fixed inset-x-0 bottom-0 z-30 border-t border-line-strong bg-surface shadow-decision motion-safe:animate-reveal"
    data-testid="insight-brief-tray"
  >
    <div class="mx-auto grid w-full max-w-[1180px] gap-2 px-4 py-3 sm:px-6">
      <div v-if="items.length > 0" class="flex flex-wrap items-start gap-2">
        <details
          class="min-w-0 flex-[1_1_16rem]"
          :open="listOpen"
          data-testid="insight-brief-tray-details"
          @toggle="onToggle"
        >
          <summary
            ref="summary"
            class="min-h-11 cursor-pointer rounded-control py-2.5 text-sm leading-6 font-semibold text-ink"
            data-testid="insight-brief-tray-count"
          >
            {{ countText }}
          </summary>
          <ul class="m-0 mt-2 grid max-h-[40vh] list-none gap-2 overflow-y-auto p-0">
            <li
              v-for="(item, index) in items"
              :key="itemKey(item)"
              class="flex items-start justify-between gap-2 rounded-panel border border-line bg-surface-2 py-1 pr-1 pl-3 text-sm"
              :data-conflict="conflictLabel(item) !== null"
              data-testid="insight-brief-tray-item"
            >
              <span class="grid min-w-0 gap-1 py-2">
                <span :id="textId(index)" class="leading-6 break-words text-ink">
                  {{ item.text }}
                </span>
                <span
                  v-if="conflictLabel(item) !== null"
                  class="justify-self-start rounded-pill border border-fail-line bg-fail-bg px-2 py-0.5 text-xs font-semibold text-fail-dark"
                  data-testid="insight-brief-tray-conflict"
                >
                  {{ conflictLabel(item) }}
                </span>
              </span>
              <button
                type="button"
                class="inline-flex min-h-11 shrink-0 items-center rounded-control px-3 font-semibold text-action transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
                :aria-label="copy.remove"
                :aria-describedby="textId(index)"
                :disabled="applying"
                data-testid="insight-brief-tray-remove"
                @click="remove(item)"
              >
                {{ copy.remove }}
              </button>
            </li>
          </ul>
        </details>
        <div class="flex gap-2 max-sm:w-full sm:ml-auto">
          <button
            type="button"
            class="inline-flex min-h-11 min-w-0 flex-1 items-center justify-center rounded-control bg-action px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-ink-3 motion-reduce:transition-none sm:flex-none"
            :disabled="applying"
            data-testid="insight-brief-tray-apply"
            @click="applyAll"
          >
            {{ copy.apply }}
          </button>
          <button
            type="button"
            class="inline-flex min-h-11 flex-none items-center justify-center rounded-control border border-button-line bg-surface px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:text-ink-3 motion-reduce:transition-none"
            :disabled="applying"
            data-testid="insight-brief-tray-clear"
            @click="tray.clear(projectId)"
          >
            {{ copy.clear }}
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p
          role="status"
          class="m-0 min-w-0 text-sm leading-6"
          :class="done ? 'font-semibold text-ok-dark' : 'text-ink-2'"
          data-testid="insight-brief-tray-status"
        >
          {{ status }}
        </p>
        <button
          v-if="done"
          ref="closeButton"
          type="button"
          class="inline-flex min-h-11 items-center justify-center rounded-control border border-button-line bg-surface px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-3 motion-reduce:transition-none"
          data-testid="insight-brief-tray-close"
          @click="tray.dismissResult(projectId)"
        >
          {{ copy.close }}
        </button>
      </div>
      <p
        v-if="failureText !== null"
        role="alert"
        class="m-0 rounded-panel border border-fail-line bg-fail-bg px-3 py-2 text-sm font-semibold text-fail-dark"
        data-testid="insight-brief-tray-error"
      >
        {{ failureText }}
      </p>
    </div>
  </section>
</template>
