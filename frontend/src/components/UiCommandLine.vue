<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import UiButton from "./UiButton.vue";
import { useSurface } from "./UiSurface.vue";

type CopyState = "idle" | "copied" | "failed";

const COPIED_MILLISECONDS = 2000;

const props = withDefaults(
  defineProps<{
    command: string;
    copyLabel: string;
    copiedLabel: string;
    failedLabel: string;
    copyText?: ((text: string) => Promise<void>) | undefined;
  }>(),
  { copyText: undefined },
);

const context = useSurface(() => undefined);
const state = ref<CopyState>("idle");
let attempt = 0;
let timer: ReturnType<typeof setTimeout> | null = null;

const palettes = {
  light: "bg-surface-3 text-ink",
  night: "bg-on-night/8 text-on-night",
};

const palette = computed(() => palettes[context.value]);
const label = computed(() => {
  const labels = { idle: props.copyLabel, copied: props.copiedLabel, failed: props.failedLabel };
  return labels[state.value];
});
const announcement = computed(() => (state.value === "idle" ? "" : label.value));

function writeToClipboard(text: string): Promise<void> {
  return navigator.clipboard.writeText(text);
}

function reset(): void {
  attempt += 1;
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  state.value = "idle";
}

async function written(text: string): Promise<boolean> {
  try {
    await (props.copyText ?? writeToClipboard)(text);
    return true;
  } catch {
    return false;
  }
}

async function copy(): Promise<void> {
  reset();
  const current = attempt;
  const copied = await written(props.command);
  if (current !== attempt) {
    return;
  }
  if (!copied) {
    state.value = "failed";
    return;
  }
  state.value = "copied";
  timer = setTimeout(reset, COPIED_MILLISECONDS);
}

watch(() => props.command, reset);

onBeforeUnmount(reset);
</script>

<template>
  <div class="flex items-start gap-2" data-testid="command-line" :data-surface-context="context">
    <code
      :class="[
        'min-w-0 flex-1 rounded-[4px] px-2.5 py-3 font-mono text-[13px] leading-5 wrap-anywhere whitespace-pre-wrap',
        palette,
      ]"
      data-testid="command-text"
      >{{ command }}</code
    >
    <UiButton
      variant="outline"
      class="shrink-0"
      :aria-label="`${copyLabel}: ${command}`"
      data-testid="command-copy"
      @click="copy"
    >
      {{ label }}
    </UiButton>
    <span class="sr-only" role="status" aria-live="polite" data-testid="command-status">{{
      announcement
    }}</span>
  </div>
</template>
