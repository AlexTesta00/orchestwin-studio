<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

type MockupWidth = "desktop" | "tablet" | "phone" | number;
type WidthPreset = "desktop" | "tablet" | "phone";

const props = withDefaults(
  defineProps<{
    html: string;
    title: string;
    width?: MockupWidth | undefined;
    interactive?: boolean | undefined;
    scale?: number | undefined;
  }>(),
  { width: "desktop", interactive: true, scale: undefined },
);

const PRESET_WIDTHS: Record<WidthPreset, number> = { desktop: 1280, tablet: 768, phone: 390 };
const PRESET_HEIGHTS: Record<WidthPreset, number> = { desktop: 800, tablet: 1024, phone: 844 };
const DESKTOP_MINIMUM = 1024;
const DEVICE_MARGIN = 16;

const RATIOS: Record<WidthPreset, string> = {
  desktop: "aspect-[16/10]",
  tablet: "aspect-[3/4]",
  phone: "aspect-[390/844]",
};

const SCREEN_LINK = /(<a\b[^<>]*?\shref=")#(SCR-[0-9]{3}")/g;

const box = ref<HTMLElement | null>(null);
const size = ref({ width: 0, height: 0 });
let observer: ResizeObserver | null = null;

const documentHtml = computed(() => props.html.replace(SCREEN_LINK, "$1about:srcdoc#$2"));

const preset = computed<WidthPreset>(() =>
  typeof props.width === "number" ? "desktop" : props.width,
);

const widthName = computed(() =>
  typeof props.width === "number" ? String(Math.round(props.width)) : props.width,
);

const layoutWidth = computed(() => {
  if (typeof props.width === "number") {
    return Math.max(1, Math.round(props.width));
  }
  if (props.width === "desktop" && props.interactive) {
    return Math.max(DESKTOP_MINIMUM, size.value.width);
  }
  return PRESET_WIDTHS[props.width];
});

const factor = computed(() => {
  const available = size.value.width;
  if (!props.interactive && props.scale !== undefined && props.scale > 0) {
    return props.scale;
  }
  if (available <= 0) {
    return 1;
  }
  const fit = available / layoutWidth.value;
  return props.interactive ? Math.min(1, fit) : fit;
});

const device = computed(() => props.interactive && props.width !== "desktop");

const inset = computed(() =>
  device.value && size.value.height > DEVICE_MARGIN * 8 ? DEVICE_MARGIN : 0,
);

const layoutHeight = computed(() => {
  if (size.value.height > 0) {
    return Math.ceil((size.value.height - inset.value * 2) / factor.value);
  }
  return typeof props.width === "number"
    ? Math.round((layoutWidth.value * 10) / 16)
    : PRESET_HEIGHTS[preset.value];
});

const offset = computed(() =>
  Math.max(0, Math.floor((size.value.width - layoutWidth.value * factor.value) / 2)),
);

const boxClasses = computed(() =>
  props.interactive
    ? ["relative h-full w-full overflow-hidden"]
    : [
        "pointer-events-none relative w-full overflow-hidden rounded-[10px] bg-night-deep select-none",
        RATIOS[preset.value],
      ],
);

const frameClasses = computed(() => [
  "absolute block origin-top-left border-0 bg-transparent",
  device.value ? "rounded-[18px] shadow-dialog ring-1 ring-night-line-strong" : "",
]);

const frameStyle = computed(() => ({
  width: `${layoutWidth.value}px`,
  height: `${layoutHeight.value}px`,
  top: `${inset.value}px`,
  left: `${offset.value}px`,
  transform: factor.value === 1 ? undefined : `scale(${factor.value})`,
}));

function measure(): void {
  const element = box.value;
  if (element !== null) {
    size.value = { width: element.clientWidth, height: element.clientHeight };
  }
}

onMounted(() => {
  measure();
  if (typeof ResizeObserver === "undefined" || box.value === null) {
    return;
  }
  observer = new ResizeObserver(measure);
  observer.observe(box.value);
});

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
});
</script>

<template>
  <div
    ref="box"
    :class="boxClasses"
    :inert="interactive ? undefined : true"
    :aria-hidden="interactive ? undefined : 'true'"
    data-testid="generated-mockup-frame"
    :data-width="widthName"
    :data-interactive="interactive ? 'true' : 'false'"
  >
    <iframe
      :class="frameClasses"
      :style="frameStyle"
      :srcdoc="documentHtml"
      sandbox=""
      referrerpolicy="no-referrer"
      loading="lazy"
      :title="title"
      :tabindex="interactive ? undefined : -1"
      data-testid="generated-mockup-iframe"
    />
  </div>
</template>
