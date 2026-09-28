<script setup lang="ts">
import { computed, useId } from "vue";

export type ArtifactView = "text" | "table" | "diagram";
type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    modelValue: ArtifactView;
    locale?: Locale;
    label?: string | undefined;
    panelId?: string | undefined;
  }>(),
  { locale: "en", label: undefined, panelId: undefined },
);

const emit = defineEmits<{ "update:modelValue": [value: ArtifactView] }>();

const messages = {
  en: {
    label: "How to look at this content",
    text: ["Text", "Read it as a document"],
    table: ["Table", "Compare the items in rows and columns"],
    diagram: ["Diagram", "See how the parts are connected"],
  },
  it: {
    label: "Come guardare questo contenuto",
    text: ["Testo", "Leggilo come un documento"],
    table: ["Tabella", "Confronta le voci in righe e colonne"],
    diagram: ["Diagramma", "Guarda come sono collegate le parti"],
  },
} as const;

const views: readonly ArtifactView[] = ["text", "table", "diagram"];
const group = `artifact-view-${useId()}`;
const copy = computed(() => messages[props.locale]);

function tabId(view: ArtifactView): string {
  return `${group}-${view}`;
}

function select(view: ArtifactView): void {
  if (view !== props.modelValue) {
    emit("update:modelValue", view);
  }
}

function move(event: KeyboardEvent, view: ArtifactView): void {
  const index = views.indexOf(view);
  const steps: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    Home: 0,
    End: views.length - 1,
  };
  const target = steps[event.key];

  if (target === undefined) {
    return;
  }

  event.preventDefault();
  const next = views[(target + views.length) % views.length];

  if (next === undefined) {
    return;
  }

  select(next);
  const holder =
    event.currentTarget instanceof HTMLElement ? event.currentTarget.parentElement : null;
  holder?.querySelector<HTMLElement>(`[data-view="${next}"]`)?.focus();
}

defineExpose({ tabId });
</script>

<template>
  <div
    class="inline-flex flex-wrap gap-1 rounded-panel border border-line bg-surface-2 p-1"
    role="tablist"
    :aria-label="label ?? copy.label"
    data-testid="artifact-view-switch"
  >
    <button
      v-for="view in views"
      :id="tabId(view)"
      :key="view"
      type="button"
      role="tab"
      class="min-h-11 rounded-control px-4 py-2 text-sm font-semibold transition-colors duration-150"
      :class="
        view === modelValue
          ? 'bg-surface text-ink shadow-card'
          : 'text-ink-2 hover:bg-surface-3 hover:text-ink'
      "
      :aria-selected="view === modelValue"
      :aria-controls="panelId"
      :tabindex="view === modelValue ? 0 : -1"
      :title="copy[view][1]"
      :data-view="view"
      :data-testid="`artifact-view-${view}`"
      @click="select(view)"
      @keydown="move($event, view)"
    >
      {{ copy[view][0] }}
    </button>
  </div>
</template>
