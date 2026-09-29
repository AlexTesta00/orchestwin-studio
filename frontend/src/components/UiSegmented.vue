<script setup lang="ts" generic="T extends string">
import { computed, ref, useId } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    modelValue: T;
    options: readonly { value: T; label: string; testId?: string }[];
    label: string;
    kind?: "tabs" | "radio" | undefined;
    panelId?: string | undefined;
    surface?: SurfaceContext | undefined;
  }>(),
  { kind: "tabs", panelId: undefined, surface: undefined },
);

const emit = defineEmits<{ "update:modelValue": [value: T] }>();

const context = useSurface(() => props.surface);
const root = ref<HTMLElement | null>(null);
const base = useId();

const palettes = {
  light: {
    track: "bg-surface-3",
    selected: "bg-ink text-white shadow-segment",
    idle: "text-ink-2 hover:bg-surface hover:text-ink",
  },
  night: {
    track: "bg-on-night/6",
    selected: "bg-on-night text-ink shadow-segment",
    idle: "text-on-night hover:bg-night-hover",
  },
};

const palette = computed(() => palettes[context.value]);
const selectedIndex = computed(() =>
  props.options.findIndex((option) => option.value === props.modelValue),
);
const tabs = computed(() => props.kind === "tabs");

function optionId(index: number): string {
  return `${base}-${index}`;
}

function tabId(value: T): string | undefined {
  const index = props.options.findIndex((option) => option.value === value);
  return index < 0 ? undefined : optionId(index);
}

function isFocusable(index: number): boolean {
  return selectedIndex.value < 0 ? index === 0 : index === selectedIndex.value;
}

function select(value: T): void {
  if (value !== props.modelValue) {
    emit("update:modelValue", value);
  }
}

function move(event: KeyboardEvent, index: number): void {
  const count = props.options.length;
  const vertical = tabs.value ? {} : { ArrowDown: index + 1, ArrowUp: index - 1 };
  const targets: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    Home: 0,
    End: count - 1,
    ...vertical,
  };
  const target = targets[event.key];
  if (target === undefined || count === 0) {
    return;
  }
  event.preventDefault();
  const position = (target + count) % count;
  const next = props.options[position];
  if (next === undefined) {
    return;
  }
  select(next.value);
  root.value?.querySelectorAll<HTMLElement>("[data-segment]")[position]?.focus();
}

defineExpose({ tabId });
</script>

<template>
  <div
    ref="root"
    :class="['inline-flex max-w-full flex-wrap gap-1 rounded-[26px] p-1', palette.track]"
    :role="tabs ? 'tablist' : 'radiogroup'"
    :aria-label="label"
    data-testid="segmented"
    :data-surface-context="context"
  >
    <button
      v-for="(option, index) in options"
      :id="optionId(index)"
      :key="option.value"
      type="button"
      :role="tabs ? 'tab' : 'radio'"
      :class="[
        'inline-flex min-h-11 items-center justify-center rounded-pill px-[18px] text-[15px] font-medium transition-colors duration-150',
        option.value === modelValue ? palette.selected : palette.idle,
      ]"
      :aria-selected="tabs ? (option.value === modelValue ? 'true' : 'false') : undefined"
      :aria-checked="tabs ? undefined : option.value === modelValue ? 'true' : 'false'"
      :aria-controls="tabs ? panelId : undefined"
      :tabindex="isFocusable(index) ? 0 : -1"
      :data-value="option.value"
      :data-testid="option.testId"
      data-segment
      @click="select(option.value)"
      @keydown="move($event, index)"
    >
      {{ option.label }}
    </button>
  </div>
</template>
