<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from "vue";

import { useSurface } from "./UiSurface.vue";
import {
  DIAGRAM_BACKGROUND,
  mermaidRenderer,
  type DiagramLink,
  type DiagramRenderer,
} from "./mermaidRenderer";

type Locale = "en" | "it";
type Status = "loading" | "ready" | "failed";
type ViewMode = "fit" | "actual" | "custom";

interface Press {
  id: number;
  x: number;
  y: number;
  originX: number;
  originY: number;
  moved: boolean;
}

const READABLE_SHRINK = 1.5;
const FIT_MARGIN = 0.9;
const MAX_FIT_ZOOM = 1.5;
const MIN_ZOOM = 0.2;
const MAX_ZOOM = 4;
const ZOOM_STEP = 1.2;
const PAN_STEP = 48;
const PAN_STEP_LARGE = 160;
const DRAG_THRESHOLD = 4;
const EDGE_PADDING = 24;
const VISIBLE_MARGIN = 64;
const FALLBACK_HEIGHT = 540;
const WHEEL_SENSITIVITY = 0.002;
const LINE_HEIGHT = 16;
const CODE_PATTERN = /([A-Z]{2,5}-\d{3,})/;
const NODE_SELECTOR = "[data-diagram-node]";

const props = withDefaults(
  defineProps<{
    source: string;
    title: string;
    description: string;
    fileName: string;
    locale?: Locale;
    renderer?: DiagramRenderer | undefined;
    saveFile?: ((blob: Blob, fileName: string) => void) | undefined;
    links?: readonly DiagramLink[] | undefined;
  }>(),
  { locale: "en", renderer: undefined, saveFile: undefined, links: () => [] },
);

const emit = defineEmits<{ "select-node": [code: string] }>();

const messages = {
  en: {
    loading: "Drawing the diagram…",
    failed: "The diagram could not be drawn. Its source is shown below.",
    controls: "Zoom of the diagram",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    fit: "Fit",
    actual: "Actual size",
    hint: "Drag or use the arrow keys to move around; to zoom use the buttons, the + and − keys or Ctrl with the wheel.",
    hintLinks:
      "Drag or use the arrow keys to move around; to zoom use the buttons, the + and − keys or Ctrl with the wheel. Select an item with a code to read it in the text.",
    source: "Mermaid source",
    downloadSource: "Download the source",
    downloadImage: "Download the image",
  },
  it: {
    loading: "Disegno il diagramma…",
    failed: "Non è stato possibile disegnare il diagramma. Sotto trovi il sorgente.",
    controls: "Zoom del diagramma",
    zoomIn: "Ingrandisci",
    zoomOut: "Riduci",
    fit: "Adatta",
    actual: "Dimensione reale",
    hint: "Trascina o usa le frecce per spostarti; per lo zoom usa i pulsanti, i tasti + e − oppure Ctrl con la rotella.",
    hintLinks:
      "Trascina o usa le frecce per spostarti; per lo zoom usa i pulsanti, i tasti + e − oppure Ctrl con la rotella. Tocca un elemento con un codice per leggerlo nel testo.",
    source: "Sorgente Mermaid",
    downloadSource: "Scarica il sorgente",
    downloadImage: "Scarica l'immagine",
  },
} as const;

const palettes = {
  light: {
    frame: "border-line bg-surface",
    line: "border-line",
    text: "text-ink",
    muted: "text-ink-3",
    control: "border-line-strong text-ink hover:bg-surface-3",
    link: "text-ink-3 hover:text-ink",
    code: "text-ink-2",
    error: "text-fail-dark",
  },
  night: {
    frame: "border-night-line bg-on-night/3",
    line: "border-night-line",
    text: "text-on-night",
    muted: "text-on-night-3",
    control: "border-on-night/22 text-on-night hover:bg-night-hover",
    link: "text-on-night-3 hover:text-on-night",
    code: "text-on-night-2",
    error: "text-fail-on-night",
  },
};

const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
const copy = computed(() => messages[props.locale]);
const renderer = computed(() => props.renderer ?? mermaidRenderer);
const identifier = `diagram-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
const descriptionId = `${identifier}-description`;
const hintId = `${identifier}-hint`;
const viewport = ref<HTMLElement | null>(null);
const canvas = ref<HTMLElement | null>(null);
const status = ref<Status>("loading");
const image = ref("");
const mode = ref<ViewMode>("fit");
const dragging = ref(false);
const linkedCount = ref(0);
const view = reactive({ zoom: 1, x: 0, y: 0 });
const natural = reactive({ width: 0, height: 0 });
let sequence = 0;
let active = true;
let press: Press | null = null;
let swallowClick = false;
let awaitingSize = false;
let resizeObserver: ResizeObserver | null = null;

const percent = computed(() => Math.round(view.zoom * 100));
const transform = computed(() => `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`);
const controlClass = computed(() => [
  "inline-flex min-h-11 min-w-11 items-center justify-center rounded-[10px] border text-sm font-semibold transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-40",
  palette.value.control,
]);
const linkClass = computed(() => [
  "min-h-11 font-mono text-xs underline underline-offset-4 transition-colors duration-150",
  palette.value.link,
]);

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

function printable(svg: string): string {
  const opening = /^<svg\b[^>]*>/.exec(svg);

  if (opening === null) {
    return svg;
  }

  const tag = opening[0];
  const background = `background-color: ${DIAGRAM_BACKGROUND};`;
  const styled = /\sstyle="[^"]*"/.test(tag)
    ? tag.replace(/\sstyle="([^"]*)"/, (_match, value: string) => {
        const declarations = value.trim().replace(/;$/, "");
        return ` style="${declarations.length > 0 ? `${declarations}; ` : ""}${background}"`;
      })
    : tag.replace(/^<svg\b/, `<svg style="${background}"`);

  return `${styled}${svg.slice(tag.length)}`;
}

function downloadSource(): void {
  save(new Blob([props.source], { type: "text/plain;charset=utf-8" }), `${baseName()}.mmd`);
}

function downloadImage(): void {
  save(
    new Blob([printable(image.value)], { type: "image/svg+xml;charset=utf-8" }),
    `${baseName()}.svg`,
  );
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

function naturalSize(svg: string): { width: number; height: number } | null {
  const match = /viewBox="[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)"/.exec(svg);
  const width = match === null ? Number.NaN : Number(match[1]);
  const height = match === null ? Number.NaN : Number(match[2]);
  return Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0
    ? { width, height }
    : null;
}

function viewportBox(): { width: number; height: number } {
  const element = viewport.value;

  if (element === null) {
    return { width: 0, height: 0 };
  }

  return {
    width:
      element.clientWidth > 0 ? element.clientWidth : (element.parentElement?.clientWidth ?? 0),
    height: element.clientHeight > 0 ? element.clientHeight : FALLBACK_HEIGHT,
  };
}

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function bounded(value: number, size: number, available: number): number {
  if (size <= 0 || available <= 0) {
    return value;
  }

  const margin = Math.min(VISIBLE_MARGIN, size, available);
  return Math.min(available - margin, Math.max(margin - size, value));
}

function place(zoom: number, x: number, y: number, next: ViewMode): void {
  const box = viewportBox();
  view.zoom = zoom;
  view.x = next === "custom" ? bounded(x, natural.width * zoom, box.width) : x;
  view.y = next === "custom" ? bounded(y, natural.height * zoom, box.height) : y;
  mode.value = next;
}

function fit(): void {
  const box = viewportBox();

  if (natural.width <= 0 || natural.height <= 0 || box.width <= 0) {
    place(1, 0, 0, "fit");
    return;
  }

  const zoom = clampZoom(
    Math.min(box.width / natural.width, box.height / natural.height, MAX_FIT_ZOOM) * FIT_MARGIN,
  );
  place(
    zoom,
    (box.width - natural.width * zoom) / 2,
    (box.height - natural.height * zoom) / 2,
    "fit",
  );
}

function actualSize(): void {
  const box = viewportBox();
  const x = natural.width <= box.width ? (box.width - natural.width) / 2 : EDGE_PADDING;
  const y = natural.height <= box.height ? (box.height - natural.height) / 2 : EDGE_PADDING;
  place(1, x, y, "actual");
}

function initialView(): void {
  const box = viewportBox();
  awaitingSize = box.width <= 0;

  if (natural.width <= 0 || box.width <= 0 || natural.width <= box.width * READABLE_SHRINK) {
    fit();
  } else {
    actualSize();
  }
}

function toggleSize(): void {
  if (mode.value === "fit") {
    actualSize();
  } else {
    fit();
  }
}

function zoomBy(factor: number, origin?: { x: number; y: number }): void {
  const box = viewportBox();
  const centerX = origin?.x ?? box.width / 2;
  const centerY = origin?.y ?? box.height / 2;
  const zoom = clampZoom(view.zoom * factor);
  const ratio = zoom / view.zoom;
  place(zoom, centerX - (centerX - view.x) * ratio, centerY - (centerY - view.y) * ratio, "custom");
}

function panBy(dx: number, dy: number): void {
  place(view.zoom, view.x + dx, view.y + dy, "custom");
}

function nodeOf(target: EventTarget | null): Element | null {
  return target instanceof Element ? target.closest(NODE_SELECTOR) : null;
}

function activate(node: Element): void {
  const code = node.getAttribute("data-diagram-node");

  if (code !== null) {
    emit("select-node", code);
  }
}

function decorate(element: HTMLElement): void {
  const labels = new Map(props.links.map((link) => [link.code, link.label]));
  let count = 0;

  for (const node of element.querySelectorAll("g.node")) {
    const code = CODE_PATTERN.exec(node.textContent ?? "")?.[1];
    const label = code === undefined ? undefined : labels.get(code);

    if (code === undefined || label === undefined) {
      for (const name of ["data-diagram-node", "tabindex", "role", "aria-label"]) {
        node.removeAttribute(name);
      }
      continue;
    }

    node.setAttribute("data-diagram-node", code);
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", label);
    count += 1;
  }

  linkedCount.value = count;
}

function prepare(element: HTMLElement, svg: string): void {
  const size = naturalSize(svg);
  const drawing = element.querySelector("svg");
  natural.width = size?.width ?? 0;
  natural.height = size?.height ?? 0;

  if (drawing !== null && size !== null) {
    drawing.setAttribute("width", String(size.width));
    drawing.setAttribute("height", String(size.height));
  }

  decorate(element);
}

function onKeydown(event: KeyboardEvent): void {
  if (status.value !== "ready") {
    return;
  }

  const node = nodeOf(event.target);

  if (node !== null && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    activate(node);
    return;
  }

  const step = event.shiftKey ? PAN_STEP_LARGE : PAN_STEP;
  const moves: Record<string, readonly [number, number]> = {
    ArrowLeft: [step, 0],
    ArrowRight: [-step, 0],
    ArrowUp: [0, step],
    ArrowDown: [0, -step],
  };
  const move = moves[event.key];

  if (move !== undefined) {
    event.preventDefault();
    panBy(move[0], move[1]);
  } else if (event.key === "+" || event.key === "=") {
    event.preventDefault();
    zoomBy(ZOOM_STEP);
  } else if (event.key === "-" || event.key === "_") {
    event.preventDefault();
    zoomBy(1 / ZOOM_STEP);
  } else if (event.key === "0") {
    event.preventDefault();
    fit();
  }
}

function onWheel(event: WheelEvent): void {
  const element = viewport.value;

  if (!(event.ctrlKey || event.metaKey) || status.value !== "ready" || element === null) {
    return;
  }

  event.preventDefault();
  const delta = event.deltaMode === 1 ? event.deltaY * LINE_HEIGHT : event.deltaY;
  const factor = Math.min(1.25, Math.max(0.8, Math.exp(-delta * WHEEL_SENSITIVITY)));
  const area = element.getBoundingClientRect();
  zoomBy(factor, { x: event.clientX - area.left, y: event.clientY - area.top });
}

function onPointerDown(event: PointerEvent): void {
  swallowClick = false;

  if (status.value !== "ready" || (event.pointerType === "mouse" && event.button !== 0)) {
    return;
  }

  press = {
    id: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    originX: view.x,
    originY: view.y,
    moved: false,
  };
}

function onPointerMove(event: PointerEvent): void {
  const current = press;

  if (current === null || current.id !== event.pointerId) {
    return;
  }

  const dx = event.clientX - current.x;
  const dy = event.clientY - current.y;

  if (!current.moved) {
    if (Math.hypot(dx, dy) < DRAG_THRESHOLD) {
      return;
    }

    current.moved = true;
    dragging.value = true;
    viewport.value?.setPointerCapture?.(event.pointerId);
  }

  place(view.zoom, current.originX + dx, current.originY + dy, "custom");
}

function onPointerEnd(event: PointerEvent): void {
  const current = press;

  if (current === null || current.id !== event.pointerId) {
    return;
  }

  swallowClick = current.moved;
  press = null;
  dragging.value = false;

  if (viewport.value?.hasPointerCapture?.(event.pointerId) === true) {
    viewport.value.releasePointerCapture(event.pointerId);
  }
}

function onClick(event: MouseEvent): void {
  if (swallowClick) {
    swallowClick = false;
    return;
  }

  const node = nodeOf(event.target);

  if (node !== null) {
    activate(node);
  }
}

function onFocusIn(event: FocusEvent): void {
  const node = nodeOf(event.target);
  const element = viewport.value;

  if (node === null || element === null) {
    return;
  }

  const area = element.getBoundingClientRect();
  const box = node.getBoundingClientRect();

  if (area.width <= 0 || area.height <= 0) {
    return;
  }

  const dx =
    box.left < area.left + EDGE_PADDING
      ? area.left + EDGE_PADDING - box.left
      : box.right > area.right - EDGE_PADDING
        ? area.right - EDGE_PADDING - box.right
        : 0;
  const dy =
    box.top < area.top + EDGE_PADDING
      ? area.top + EDGE_PADDING - box.top
      : box.bottom > area.bottom - EDGE_PADDING
        ? area.bottom - EDGE_PADDING - box.bottom
        : 0;

  if (dx !== 0 || dy !== 0) {
    panBy(dx, dy);
  }
}

watch(
  [image, canvas],
  ([svg, element], [previous]) => {
    if (element === null) {
      return;
    }

    element.innerHTML = svg;

    if (svg === "") {
      linkedCount.value = 0;
      return;
    }

    prepare(element, svg);

    if (svg !== previous) {
      initialView();
    }
  },
  { flush: "post" },
);

watch(
  () => props.links,
  () => {
    if (canvas.value !== null && image.value !== "") {
      decorate(canvas.value);
    }
  },
);

watch(() => [props.source, renderer.value], draw, { immediate: true });

onMounted(() => {
  if (typeof ResizeObserver === "undefined" || viewport.value === null) {
    return;
  }

  resizeObserver = new ResizeObserver(() => {
    if (status.value !== "ready") {
      return;
    }

    if (awaitingSize) {
      initialView();
    } else if (mode.value === "fit") {
      fit();
    }
  });
  resizeObserver.observe(viewport.value);
});

onBeforeUnmount(() => {
  active = false;
  resizeObserver?.disconnect();
});
</script>

<template>
  <figure
    :class="['m-0 overflow-hidden rounded-tile border', palette.frame]"
    data-testid="mermaid-diagram"
    :data-status="status"
    :aria-describedby="descriptionId"
  >
    <figcaption class="sr-only">{{ title }}</figcaption>

    <div :class="['flex flex-wrap items-center gap-2 border-b px-3.5 py-3', palette.line]">
      <div class="min-w-0 flex-[1_1_auto]">
        <slot name="choice">
          <p :class="['px-1 text-sm font-semibold', palette.text]" aria-hidden="true">
            {{ title }}
          </p>
        </slot>
      </div>
      <div
        v-if="status === 'ready'"
        class="ml-auto flex items-center gap-1.5"
        role="group"
        :aria-label="copy.controls"
      >
        <button
          type="button"
          :class="controlClass"
          :aria-label="copy.zoomOut"
          :disabled="view.zoom <= MIN_ZOOM"
          data-testid="diagram-zoom-out"
          @click="zoomBy(1 / ZOOM_STEP)"
        >
          <span aria-hidden="true">−</span>
        </button>
        <span
          :class="['min-w-12 text-center font-mono text-xs tabular-nums', palette.muted]"
          aria-live="polite"
          data-testid="diagram-zoom-level"
        >
          {{ percent }}%
        </span>
        <button
          type="button"
          :class="controlClass"
          :aria-label="copy.zoomIn"
          :disabled="view.zoom >= MAX_ZOOM"
          data-testid="diagram-zoom-in"
          @click="zoomBy(ZOOM_STEP)"
        >
          <span aria-hidden="true">+</span>
        </button>
        <button
          type="button"
          :class="[controlClass, 'px-3.5']"
          data-testid="diagram-size"
          @click="toggleSize"
        >
          {{ mode === "fit" ? copy.actual : copy.fit }}
        </button>
      </div>
    </div>

    <div class="relative">
      <p
        v-if="status === 'loading'"
        class="m-0 flex h-[420px] items-center justify-center bg-night-deep px-6 text-sm text-on-night-3 sm:h-[540px]"
        role="status"
      >
        {{ copy.loading }}
      </p>
      <p
        v-if="status === 'failed'"
        :class="['m-0 px-5 py-4 text-sm font-semibold', palette.error]"
        role="alert"
        data-testid="diagram-error"
      >
        {{ copy.failed }}
      </p>
      <div
        v-show="status === 'ready'"
        ref="viewport"
        class="relative h-[420px] touch-none overflow-clip bg-night-deep bg-[radial-gradient(rgb(243_244_244/0.09)_1px,transparent_1px)] bg-size-[22px_22px] select-none focus-visible:-outline-offset-4 sm:h-[540px] [&_[data-diagram-node]]:cursor-pointer [&_[data-diagram-node]:focus-visible]:outline-offset-4 [&_[data-diagram-node]:hover_:is(rect,ellipse,polygon,circle,path)]:stroke-on-night!"
        :class="dragging ? 'cursor-grabbing' : 'cursor-grab'"
        :role="linkedCount > 0 ? 'group' : 'img'"
        :aria-label="`${title}. ${description}`"
        :aria-describedby="status === 'ready' ? hintId : undefined"
        tabindex="0"
        data-testid="diagram-canvas"
        :data-mode="mode"
        :data-links="linkedCount"
        @keydown="onKeydown"
        @wheel="onWheel"
        @pointerdown="onPointerDown"
        @pointermove="onPointerMove"
        @pointerup="onPointerEnd"
        @pointercancel="onPointerEnd"
        @click="onClick"
        @focusin="onFocusIn"
      >
        <div ref="canvas" class="absolute top-0 left-0 origin-top-left" :style="{ transform }" />
      </div>
    </div>

    <div
      :class="[
        'flex flex-wrap items-start gap-x-6 gap-y-2 border-t px-[18px] py-3.5',
        palette.line,
      ]"
    >
      <div :class="['min-w-0 flex-[1_1_320px] text-[13px] leading-normal', palette.muted]">
        <p :id="descriptionId" class="m-0" data-testid="diagram-description">{{ description }}</p>
        <p v-if="status === 'ready'" :id="hintId" class="m-0 mt-1">
          {{ linkedCount > 0 ? copy.hintLinks : copy.hint }}
        </p>
      </div>
      <div v-if="status === 'ready'" class="flex flex-wrap gap-x-5">
        <button
          type="button"
          :class="linkClass"
          data-testid="diagram-download-image"
          @click="downloadImage"
        >
          {{ copy.downloadImage }}
        </button>
        <button
          type="button"
          :class="linkClass"
          data-testid="diagram-download-source"
          @click="downloadSource"
        >
          {{ copy.downloadSource }}
        </button>
      </div>
    </div>

    <details :class="['border-t', palette.line]" :open="status === 'failed'">
      <summary
        :class="[
          'flex min-h-11 cursor-pointer items-center px-[18px] font-mono text-xs underline underline-offset-4',
          palette.link,
        ]"
      >
        {{ copy.source }}
      </summary>
      <pre
        :class="[
          'm-0 max-h-[260px] overflow-auto border-t px-[18px] py-4 font-mono text-xs leading-[1.6]',
          palette.line,
          palette.code,
        ]"
        data-testid="diagram-source"
        >{{ source }}</pre>
    </details>
  </figure>
</template>
