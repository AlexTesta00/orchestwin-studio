<script setup lang="ts">
import { computed, nextTick, onMounted, provide, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{ open: boolean; title: string; surface?: SurfaceContext | undefined }>(),
  { surface: "light" },
);

const emit = defineEmits<{ close: [] }>();

const { t } = useI18n({ useScope: "global" });

const host = ref<HTMLElement | null>(null);
const panel = ref<HTMLElement | null>(null);
const atBody = ref(false);
const titleId = useId();
const context = computed<SurfaceContext>(() => props.surface);

provide(surfaceKey, context);

const styles = {
  light: {
    veil: "bg-ink/40",
    panel: "border-l border-line bg-surface text-ink",
    header: "border-line bg-surface",
    close: "text-ink-2 hover:bg-surface-3 hover:text-ink",
  },
  night: {
    veil: "bg-night/60",
    panel: "border-l border-night-line-strong bg-night-panel text-on-night",
    header: "border-night-line bg-night-panel",
    close: "text-on-night-2 hover:bg-night-hover hover:text-on-night",
  },
};

const style = computed(() => styles[context.value]);

const focusableSelector = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "summary",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

let opener: HTMLElement | null = null;

function focusables(): HTMLElement[] {
  const element = panel.value;
  if (element === null) {
    return [];
  }
  return Array.from(element.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (candidate) =>
      candidate.closest("[hidden], [inert]") === null &&
      (typeof candidate.checkVisibility !== "function" || candidate.checkVisibility()),
  );
}

function trapFocus(event: KeyboardEvent): void {
  const element = panel.value;
  if (element === null) {
    return;
  }
  const items = focusables();
  const first = items[0];
  const last = items[items.length - 1];
  if (first === undefined || last === undefined) {
    event.preventDefault();
    element.focus();
    return;
  }
  const active = document.activeElement;
  if (event.shiftKey && (active === first || active === element)) {
    event.preventDefault();
    last.focus();
    return;
  }
  if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      await nextTick();
      panel.value?.focus();
      return;
    }
    opener?.focus();
    opener = null;
  },
);

onMounted(() => {
  atBody.value = host.value?.parentElement === document.body;
});
</script>

<template>
  <div ref="host" class="contents" data-testid="side-panel-host">
    <Teleport to="body" :disabled="atBody">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex justify-end"
        :data-surface="surface"
        data-testid="side-panel"
      >
        <button
          type="button"
          :class="['absolute inset-0', style.veil]"
          :aria-label="t('ui.panel.close')"
          data-testid="side-panel-veil"
          @click="emit('close')"
        />
        <div
          ref="panel"
          :class="[
            'relative flex h-full w-full max-w-[560px] flex-col overflow-y-auto shadow-drawer outline-none',
            style.panel,
          ]"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :data-surface="surface"
          tabindex="-1"
          @keydown.esc="emit('close')"
          @keydown.tab="trapFocus"
        >
          <div
            :class="[
              'sticky top-0 z-10 flex items-center justify-between gap-4 border-b py-3 pr-3 pl-6',
              style.header,
            ]"
          >
            <h2 :id="titleId" class="text-xl font-semibold tracking-block">{{ title }}</h2>
            <button
              type="button"
              :class="[
                'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-lg transition-colors duration-150',
                style.close,
              ]"
              :aria-label="t('ui.panel.close')"
              data-testid="side-panel-close"
              @click="emit('close')"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          <div class="grid gap-5 px-6 py-5">
            <slot />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
