<script setup lang="ts">
import { computed, ref, watch } from "vue";

import MermaidDiagram from "./MermaidDiagram.vue";
import UiButton from "./UiButton.vue";
import { useSurface } from "./UiSurface.vue";
import type { DiagramLink, DiagramRenderer } from "./mermaidRenderer";

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
    links?: readonly DiagramLink[] | undefined;
  }>(),
  {
    locale: "en",
    refreshKey: null,
    authorize: undefined,
    api: undefined,
    renderer: undefined,
    saveFile: undefined,
    links: () => [],
  },
);

const emit = defineEmits<{ "select-node": [code: string] }>();

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

const palettes = {
  light: {
    state: "border-line bg-surface-2 text-ink-2",
    failure: "border-fail-line bg-fail-bg text-fail-dark",
    note: "text-ink-3",
    chosen: "border-ink bg-ink text-white",
    idle: "border-line-strong text-ink-2 hover:bg-surface-3 hover:text-ink",
  },
  night: {
    state: "border-night-line bg-night-raised text-on-night-2",
    failure: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
    note: "text-on-night-3",
    chosen: "border-on-night bg-on-night text-ink",
    idle: "border-on-night/22 text-on-night hover:bg-night-hover",
  },
};

const auth = useAuthStore();
const store = useDiagramsStore();
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
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
  <section class="grid gap-3" data-testid="project-diagrams" :data-stage="stage">
    <p
      v-if="loading"
      :class="['m-0 rounded-tile border px-5 py-4 text-sm font-semibold', palette.state]"
      role="status"
    >
      {{ copy.loading }}
    </p>

    <div
      v-else-if="failed"
      :class="['rounded-tile border px-5 py-4', palette.failure]"
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
      :class="['m-0 rounded-tile border px-5 py-4 text-sm', palette.state]"
      data-testid="diagrams-empty"
    >
      {{ copy.empty[stage] }}
    </p>

    <template v-else>
      <MermaidDiagram
        :source="selected.source"
        :title="selected.title"
        :description="selected.description"
        :file-name="selected.path"
        :locale="locale"
        :renderer="renderer"
        :save-file="saveFile"
        :links="links"
        @select-node="emit('select-node', $event)"
      >
        <template v-if="diagrams.length > 1" #choice>
          <div
            class="flex flex-wrap gap-2"
            role="group"
            :aria-label="copy.choose"
            data-testid="diagram-choice"
          >
            <button
              v-for="diagram in diagrams"
              :key="diagram.key"
              type="button"
              :class="[
                'min-h-11 rounded-pill border px-3.5 text-[13px] font-semibold transition-colors duration-150',
                diagram.key === selected.key ? palette.chosen : palette.idle,
              ]"
              :aria-pressed="diagram.key === selected.key ? 'true' : 'false'"
              :data-testid="`diagram-option-${diagram.key}`"
              @click="selectedKey = diagram.key"
            >
              {{ diagram.title }}
            </button>
          </div>
        </template>
      </MermaidDiagram>

      <p :class="['m-0 text-xs leading-5', palette.note]" data-testid="diagrams-note">
        {{ copy.generated }}
      </p>
    </template>
  </section>
</template>
