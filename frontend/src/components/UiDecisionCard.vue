<script setup lang="ts">
import { computed, ref, useId } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import UiStatusChip from "./UiStatusChip.vue";

export interface DecisionRecord {
  n: number;
  ok: boolean;
  note?: string;
}

const props = withDefaults(
  defineProps<{
    decision: number;
    max: number;
    enabled?: boolean | undefined;
    busy?: boolean | undefined;
    hint?: string | undefined;
    history?: DecisionRecord[] | undefined;
  }>(),
  { enabled: true, busy: false, hint: "", history: () => [] },
);

const emit = defineEmits<{ approve: []; reject: [note: string] }>();

const { t } = useI18n({ useScope: "global" });

const rejecting = ref(false);
const note = ref("");
const noteMissing = ref(false);
const noteId = useId();
const errorId = useId();

const blocked = computed(() => !props.enabled || props.busy);

const explanation = computed(() => {
  if (props.busy) {
    return t("ui.decision.busy");
  }
  if (!props.enabled) {
    return t("ui.decision.locked");
  }
  return props.hint;
});

const orderedHistory = computed(() => [...props.history].sort((left, right) => right.n - left.n));

function startRejection(): void {
  rejecting.value = true;
  noteMissing.value = false;
}

function cancelRejection(): void {
  rejecting.value = false;
  note.value = "";
  noteMissing.value = false;
}

function confirmRejection(): void {
  const trimmed = note.value.trim();
  if (!trimmed) {
    noteMissing.value = true;
    return;
  }
  emit("reject", trimmed);
  cancelRejection();
}
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="decision-card">
    <UiCard tone="elevated">
      <div class="flex flex-wrap items-baseline justify-between gap-3">
        <h2 class="text-2xl font-semibold tracking-card">{{ t("ui.decision.title") }}</h2>
        <span class="font-mono text-xs text-ink-3" data-testid="decision-counter">
          {{ t("ui.decision.counter", { n: decision, max }) }}
        </span>
      </div>
      <p v-if="explanation" class="mt-2 text-[15px] text-ink-2">{{ explanation }}</p>
      <div v-if="!rejecting" class="mt-6 flex flex-wrap gap-3">
        <UiButton :disabled="blocked" data-testid="approve" @click="emit('approve')">
          {{ t("ui.decision.approve") }}
        </UiButton>
        <UiButton
          variant="secondary"
          :disabled="blocked"
          data-testid="reject"
          @click="startRejection"
        >
          {{ t("ui.decision.reject") }}
        </UiButton>
      </div>
      <div v-else class="mt-6 flex flex-col gap-3">
        <label class="text-sm font-semibold" :for="noteId">{{ t("ui.decision.noteLabel") }}</label>
        <textarea
          :id="noteId"
          v-model="note"
          class="min-h-28 rounded-control border border-field bg-surface px-3 py-2 text-[15px]"
          required
          :aria-invalid="noteMissing ? 'true' : undefined"
          :aria-describedby="noteMissing ? errorId : undefined"
          data-testid="rejection-note"
        />
        <p
          v-if="noteMissing"
          :id="errorId"
          class="text-sm font-semibold text-fail-dark"
          role="alert"
          data-testid="note-error"
        >
          {{ t("ui.decision.noteError") }}
        </p>
        <div class="flex flex-wrap gap-3">
          <UiButton variant="danger" data-testid="confirm-rejection" @click="confirmRejection">
            {{ t("ui.decision.confirm") }}
          </UiButton>
          <UiButton variant="secondary" data-testid="cancel-rejection" @click="cancelRejection">
            {{ t("ui.decision.cancel") }}
          </UiButton>
        </div>
      </div>
    </UiCard>
    <section v-if="orderedHistory.length" aria-labelledby="decision-history-title">
      <h3 id="decision-history-title" class="font-mono text-xs tracking-wide text-ink-3 uppercase">
        {{ t("ui.decision.history") }}
      </h3>
      <ol class="mt-2 flex flex-col gap-2" data-testid="decision-history">
        <li
          v-for="entry in orderedHistory"
          :key="entry.n"
          class="flex flex-wrap items-center gap-3 rounded-panel border border-line bg-surface px-4 py-3"
        >
          <UiStatusChip :status="entry.ok ? 'approved' : 'rejected'" />
          <span v-if="entry.note" class="min-w-0 flex-1 text-sm text-ink-2">{{ entry.note }}</span>
          <span class="font-mono text-xs text-ink-3">
            {{ t("ui.decision.counter", { n: entry.n, max }) }}
          </span>
        </li>
      </ol>
    </section>
  </div>
</template>
