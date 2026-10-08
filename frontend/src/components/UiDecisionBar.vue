<script setup lang="ts">
import { computed, nextTick, provide, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "./UiButton.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

const props = withDefaults(
  defineProps<{
    title?: string | undefined;
    description?: string | undefined;
    primaryLabel: string;
    secondaryLabel?: string | null | undefined;
    requestPlaceholder?: string | undefined;
    busy?: boolean | undefined;
    disabled?: boolean | undefined;
  }>(),
  {
    title: undefined,
    description: "",
    secondaryLabel: undefined,
    requestPlaceholder: undefined,
    busy: false,
    disabled: false,
  },
);

const emit = defineEmits<{ primary: []; secondary: []; request: [text: string] }>();

const { t } = useI18n({ useScope: "global" });

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const root = ref<HTMLElement | null>(null);
const field = ref<HTMLTextAreaElement | null>(null);
const requesting = ref(false);
const note = ref("");
const titleId = useId();
const noteId = useId();
let focusSecondaryWhenIdle = false;

const requestable = computed(() => props.secondaryLabel !== null);
const noteOpen = computed(() => requesting.value && requestable.value);
const canSend = computed(() => note.value.trim().length > 0 && !props.busy);

async function focusSecondary(): Promise<void> {
  await nextTick();
  const target =
    root.value?.querySelector<HTMLElement>("[data-decision-secondary]") ??
    root.value?.querySelector<HTMLElement>("[data-decision-primary]");
  target?.focus();
}

async function openRequest(): Promise<void> {
  requesting.value = true;
  emit("secondary");
  await nextTick();
  field.value?.focus();
}

async function cancel(): Promise<void> {
  requesting.value = false;
  note.value = "";
  await focusSecondary();
}

function send(): void {
  if (!canSend.value) {
    return;
  }
  emit("request", note.value.trim());
}

async function completeRequest(): Promise<void> {
  if (!requesting.value) {
    return;
  }
  requesting.value = false;
  note.value = "";
  if (props.busy) {
    focusSecondaryWhenIdle = true;
    return;
  }
  await focusSecondary();
}

watch(
  () => props.busy,
  async (busy, wasBusy) => {
    if (busy || !wasBusy) {
      return;
    }
    if (focusSecondaryWhenIdle) {
      focusSecondaryWhenIdle = false;
      await focusSecondary();
      return;
    }
    if (noteOpen.value) {
      await nextTick();
      field.value?.focus();
    }
  },
);

watch(requestable, async (available) => {
  if (available || !requesting.value) {
    return;
  }
  requesting.value = false;
  note.value = "";
  if (props.busy) {
    focusSecondaryWhenIdle = true;
    return;
  }
  await focusSecondary();
});

defineExpose({ completeRequest });
</script>

<template>
  <section
    ref="root"
    class="sticky bottom-4 z-10 mt-10 rounded-tile border border-night-line-strong bg-night-panel/94 py-3.5 pr-3.5 pl-5 text-on-night shadow-bar backdrop-blur-[14px] sm:pl-[22px]"
    data-surface="night"
    data-ui-decision-bar
    :aria-labelledby="titleId"
    :aria-busy="busy ? 'true' : undefined"
    data-testid="decision-bar"
  >
    <div v-if="noteOpen" class="flex flex-col gap-2 pt-1.5 pb-3.5">
      <label :for="noteId" class="text-sm font-semibold">{{ t("ui.decision.requestLabel") }}</label>
      <textarea
        :id="noteId"
        ref="field"
        v-model="note"
        rows="3"
        :placeholder="requestPlaceholder ?? t('ui.decision.requestPlaceholder')"
        :disabled="busy"
        class="min-h-24 resize-y rounded-control border border-night-line-strong bg-night-raised p-3 text-[15px] text-on-night placeholder:text-on-night-3"
        data-testid="decision-note"
        @keydown.esc.prevent="cancel"
      />
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <div class="min-w-0 flex-[1_1_260px]">
        <p :id="titleId" class="text-[15px] font-semibold">{{ title ?? t("ui.decision.title") }}</p>
        <p v-if="description" class="mt-0.5 text-sm leading-[1.45] text-on-night-3">
          {{ description }}
        </p>
        <slot />
      </div>
      <div class="flex w-full flex-wrap items-center gap-3 sm:w-auto">
        <template v-if="!noteOpen">
          <UiButton
            v-if="requestable"
            variant="outline"
            class="grow sm:grow-0"
            :disabled="busy"
            data-decision-secondary
            data-testid="decision-secondary"
            @click="openRequest"
          >
            {{ secondaryLabel ?? t("ui.decision.secondary") }}
          </UiButton>
          <UiButton
            variant="pill"
            size="lg"
            class="grow sm:grow-0"
            :disabled="busy || disabled"
            data-decision-primary
            data-testid="decision-primary"
            @click="emit('primary')"
          >
            {{ primaryLabel }}
          </UiButton>
        </template>
        <template v-else>
          <UiButton
            variant="quiet"
            class="grow sm:grow-0"
            :disabled="busy"
            data-testid="decision-cancel"
            @click="cancel"
          >
            {{ t("ui.decision.cancel") }}
          </UiButton>
          <UiButton
            variant="pill"
            size="lg"
            class="grow sm:grow-0"
            :disabled="!canSend"
            data-testid="decision-send"
            @click="send"
          >
            {{ t("ui.decision.send") }}
          </UiButton>
        </template>
      </div>
    </div>
    <p class="sr-only" role="status">{{ busy ? t("ui.decision.busy") : "" }}</p>
  </section>
</template>
