<script setup lang="ts">
import { computed, useId } from "vue";

import { useSurface } from "./UiSurface.vue";

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

const palettes = {
  light: {
    track: "bg-surface-3",
    selected: "bg-ink text-white shadow-segment",
    idle: "text-ink-2 hover:bg-surface hover:text-ink",
  },
  night: {
    track: "bg-on-night/8",
    selected: "bg-on-night text-ink shadow-segment",
    idle: "text-on-night hover:bg-night-hover",
  },
};

const views: readonly ArtifactView[] = ["text", "table", "diagram"];
const group = `artifact-view-${useId()}`;
const copy = computed(() => messages[props.locale]);
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);

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
    :class="['inline-flex max-w-full flex-wrap gap-1 rounded-[26px] p-1', palette.track]"
    role="tablist"
    :aria-label="label ?? copy.label"
    data-testid="artifact-view-switch"
    :data-surface-context="surface"
  >
    <button
      v-for="view in views"
      :id="tabId(view)"
      :key="view"
      type="button"
      role="tab"
      :class="[
        'inline-flex min-h-11 items-center justify-center rounded-pill px-[18px] text-[15px] font-medium transition-colors duration-150',
        view === modelValue ? palette.selected : palette.idle,
      ]"
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
