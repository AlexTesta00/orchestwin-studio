<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import MermaidDiagram from "./MermaidDiagram.vue";
import UiButton from "./UiButton.vue";
import type { DiagramRenderer } from "./mermaidRenderer";

import { apiClient } from "../api/client";
import type { DiagramsApi } from "../api/diagrams";
import { useAuthStore } from "../stores/auth";
import { useDiagramsStore, type AuthorizedRequest } from "../stores/diagrams";
import type { DiagramPayload, DiagramStage } from "../types/diagrams";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    stage: DiagramStage;
    locale?: Locale;
    refreshKey?: string | number | null;
    authorize?: AuthorizedRequest | undefined;
    api?: DiagramsApi | undefined;
    renderer?: DiagramRenderer | undefined;
    saveFile?: ((blob: Blob, fileName: string) => void) | undefined;
  }>(),
  {
    locale: "en",
    refreshKey: null,
    authorize: undefined,
    api: undefined,
    renderer: undefined,
    saveFile: undefined,
  },
);

const messages = {
  en: {
    choose: "Choose a diagram",
    loading: "Preparing the diagrams…",
    failed: "The diagrams could not be loaded.",
    retry: "Try again",
    empty: {
      requirements: "The diagrams appear here as soon as the requirements exist.",
      design: "The diagrams appear here as soon as the design alternatives exist.",
    },
    generated:
      "Drawn from the current version without a model: the same content always gives the same diagram.",
  },
  it: {
    choose: "Scegli un diagramma",
    loading: "Preparo i diagrammi…",
    failed: "Non è stato possibile caricare i diagrammi.",
    retry: "Riprova",
    empty: {
      requirements: "I diagrammi compaiono qui appena esistono i requisiti.",
      design: "I diagrammi compaiono qui appena esistono le alternative di design.",
    },
    generated:
      "Disegnati dalla versione corrente senza usare un modello: lo stesso contenuto dà sempre lo stesso diagramma.",
  },
} as const;

const auth = useAuthStore();
const store = useDiagramsStore();
const group = `diagrams-${useId()}`;
const copy = computed(() => messages[props.locale]);
const selectedKey = ref<string | null>(null);
const failed = ref(false);
let sequence = 0;

const authorize: AuthorizedRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const current = computed(
  () => store.projectId === props.projectId && store.locale === props.locale,
);
const diagrams = computed<DiagramPayload[]>(() =>
  current.value ? store.byStage(props.stage) : [],
);
const selected = computed<DiagramPayload | null>(
  () =>
    diagrams.value.find((diagram) => diagram.key === selectedKey.value) ??
    diagrams.value[0] ??
    null,
);
const loading = computed(() => store.pending.load && diagrams.value.length === 0);

async function load(): Promise<void> {
  const request = ++sequence;
  failed.value = false;

  try {
    await store.load(props.projectId, props.locale, authorize, props.api);
  } catch {
    if (request === sequence) {
      failed.value = true;
    }
  }
}

watch(() => [props.projectId, props.locale, props.refreshKey], load, { immediate: true });

watch(diagrams, (items) => {
  if (!items.some((diagram) => diagram.key === selectedKey.value)) {
    selectedKey.value = items[0]?.key ?? null;
  }
});
</script>

<template>
  <section class="grid gap-5" data-testid="project-diagrams" :data-stage="stage">
    <p v-if="loading" class="m-0 text-sm font-semibold text-ink-2" role="status">
      {{ copy.loading }}
    </p>

    <div
      v-else-if="failed"
      class="rounded-panel border border-fail-line bg-fail-bg p-4 text-fail-dark"
      role="alert"
      data-testid="diagrams-error"
    >
      <p class="m-0 font-semibold">{{ copy.failed }}</p>
      <UiButton class="mt-3" variant="secondary" data-testid="diagrams-retry" @click="load">
        {{ copy.retry }}
      </UiButton>
    </div>

    <p
      v-else-if="selected === null"
      class="m-0 rounded-panel border border-line-soft bg-surface-2 p-5 text-sm text-ink-2"
      data-testid="diagrams-empty"
    >
      {{ copy.empty[stage] }}
    </p>

    <template v-else>
      <div
        v-if="diagrams.length > 1"
        class="flex flex-wrap gap-2"
        role="tablist"
        :aria-label="copy.choose"
        data-testid="diagram-choice"
      >
        <button
          v-for="diagram in diagrams"
          :id="`${group}-${diagram.key}`"
          :key="diagram.key"
          type="button"
          role="tab"
          class="min-h-11 rounded-pill border px-4 py-2 text-sm font-semibold transition-colors duration-150"
          :class="
            diagram.key === selected.key
              ? 'border-action bg-action-soft text-action'
              : 'border-line bg-surface text-ink-2 hover:bg-surface-3'
          "
          :aria-selected="diagram.key === selected.key"
          :aria-controls="`${group}-panel`"
          :data-testid="`diagram-option-${diagram.key}`"
          @click="selectedKey = diagram.key"
        >
          {{ diagram.title }}
        </button>
      </div>

      <div
        :id="`${group}-panel`"
        role="tabpanel"
        :aria-labelledby="diagrams.length > 1 ? `${group}-${selected.key}` : undefined"
      >
        <MermaidDiagram
          :key="`${selected.key}-${locale}`"
          :source="selected.source"
          :title="selected.title"
          :description="selected.description"
          :file-name="selected.path"
          :locale="locale"
          :renderer="renderer"
          :save-file="saveFile"
        />
      </div>

      <p class="m-0 text-xs leading-5 text-ink-3" data-testid="diagrams-note">
        {{ copy.generated }}
      </p>
    </template>
  </section>
</template>
