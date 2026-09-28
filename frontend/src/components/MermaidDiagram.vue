<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { mermaidRenderer, type DiagramRenderer } from "./mermaidRenderer";

type Locale = "en" | "it";
type Status = "loading" | "ready" | "failed";

const READABLE_SHRINK = 1.5;

const props = withDefaults(
  defineProps<{
    source: string;
    title: string;
    description: string;
    fileName: string;
    locale?: Locale;
    renderer?: DiagramRenderer | undefined;
    saveFile?: ((blob: Blob, fileName: string) => void) | undefined;
  }>(),
  { locale: "en", renderer: undefined, saveFile: undefined },
);

const messages = {
  en: {
    loading: "Drawing the diagram…",
    failed: "The diagram could not be drawn. Its source is shown below.",
    fit: "Fit to width",
    actual: "Actual size",
    source: "Diagram source (Mermaid)",
    downloadSource: "Download the source",
    downloadImage: "Download the image",
  },
  it: {
    loading: "Disegno il diagramma…",
    failed: "Non è stato possibile disegnare il diagramma. Sotto trovi il sorgente.",
    fit: "Adatta alla larghezza",
    actual: "Dimensione reale",
    source: "Sorgente del diagramma (Mermaid)",
    downloadSource: "Scarica il sorgente",
    downloadImage: "Scarica l'immagine",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const renderer = computed(() => props.renderer ?? mermaidRenderer);
const identifier = `diagram-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
const canvas = ref<HTMLElement | null>(null);
const status = ref<Status>("loading");
const fitted = ref(true);
const image = ref("");
let sequence = 0;
let active = true;

function baseName(): string {
  const name = props.fileName.split("/").pop() ?? "diagram.mmd";
  return name.replace(/\.mmd$/, "");
}

function save(blob: Blob, fileName: string): void {
  if (props.saveFile !== undefined) {
    props.saveFile(blob, fileName);
    return;
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadSource(): void {
  save(new Blob([props.source], { type: "text/plain;charset=utf-8" }), `${baseName()}.mmd`);
}

function downloadImage(): void {
  save(new Blob([image.value], { type: "image/svg+xml;charset=utf-8" }), `${baseName()}.svg`);
}

async function draw(): Promise<void> {
  const current = ++sequence;
  status.value = "loading";
  image.value = "";

  try {
    const svg = await renderer.value.render(`${identifier}-${current}`, props.source);

    if (!active || current !== sequence) {
      return;
    }

    image.value = svg;
    status.value = "ready";
  } catch {
    if (active && current === sequence) {
      status.value = "failed";
    }
  }
}

function naturalWidth(svg: string): number | null {
  const match = /viewBox="[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+[\d.]+"/.exec(svg);
  const width = match === null ? Number.NaN : Number(match[1]);
  return Number.isFinite(width) && width > 0 ? width : null;
}

function availableWidth(element: HTMLElement): number {
  return element.clientWidth > 0 ? element.clientWidth : (element.parentElement?.clientWidth ?? 0);
}

function readableWhenFitted(svg: string, element: HTMLElement): boolean {
  const width = naturalWidth(svg);
  const available = availableWidth(element);
  return width === null || available <= 0 || width <= available * READABLE_SHRINK;
}

watch(
  [image, canvas],
  ([svg, element], [previous]) => {
    if (element === null) {
      return;
    }

    element.innerHTML = svg;

    if (svg !== "" && svg !== previous) {
      fitted.value = readableWhenFitted(svg, element);
    }
  },
  { flush: "post" },
);

watch(() => [props.source, renderer.value], draw, { immediate: true });

onBeforeUnmount(() => {
  active = false;
});
</script>

<template>
  <figure class="m-0 grid gap-3" data-testid="mermaid-diagram" :data-status="status">
    <figcaption class="grid gap-1">
      <span class="text-base font-semibold text-ink">{{ title }}</span>
      <span class="text-sm leading-6 text-ink-2" data-testid="diagram-description">
        {{ description }}
      </span>
    </figcaption>

    <p v-if="status === 'loading'" class="m-0 text-sm text-ink-3" role="status">
      {{ copy.loading }}
    </p>
    <p
      v-if="status === 'failed'"
      class="m-0 rounded-panel border border-fail-line bg-fail-bg p-4 text-sm font-semibold text-fail-dark"
      role="alert"
      data-testid="diagram-error"
    >
      {{ copy.failed }}
    </p>

    <div
      v-show="status === 'ready'"
      ref="canvas"
      class="overflow-auto rounded-panel border border-line bg-surface p-4"
      :class="fitted ? '[&>svg]:h-auto [&>svg]:max-w-full' : '[&>svg]:h-auto [&>svg]:max-w-none'"
      role="img"
      :aria-label="`${title}. ${description}`"
      tabindex="0"
      data-testid="diagram-canvas"
    ></div>

    <div v-if="status === 'ready'" class="flex flex-wrap gap-2">
      <UiButton variant="secondary" data-testid="diagram-size" @click="fitted = !fitted">
        {{ fitted ? copy.actual : copy.fit }}
      </UiButton>
      <UiButton variant="secondary" data-testid="diagram-download-image" @click="downloadImage">
        {{ copy.downloadImage }}
      </UiButton>
      <UiButton variant="secondary" data-testid="diagram-download-source" @click="downloadSource">
        {{ copy.downloadSource }}
      </UiButton>
    </div>

    <details class="text-sm" :open="status === 'failed'">
      <summary class="cursor-pointer font-semibold text-ink-2">{{ copy.source }}</summary>
      <pre
        class="mt-2 max-h-80 overflow-auto rounded-panel border border-line bg-surface-2 p-4 font-mono text-xs leading-5 text-ink"
        data-testid="diagram-source"
        >{{ source }}</pre>
    </details>
  </figure>
</template>
