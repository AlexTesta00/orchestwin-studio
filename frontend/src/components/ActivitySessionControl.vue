<script setup lang="ts">
import { computed, nextTick, ref, useId } from "vue";

import UiButton from "./UiButton.vue";
import { useActivityJournalStore, type ActivityStartOutcome } from "../stores/activityJournal";

type Refusal = Exclude<ActivityStartOutcome, "STARTED">;

const props = withDefaults(
  defineProps<{
    locale?: "it" | "en";
    rowTarget?: HTMLElement | null;
  }>(),
  { locale: "en", rowTarget: null },
);

const messages = {
  it: {
    title: "Sessione di prova",
    intro:
      "Registra quali sezioni e dettagli apri e quando. Non registra ciò che scrivi né i contenuti del progetto.",
    label: "Codice della sessione",
    hint: "Usa un codice come SES-P01, senza nomi.",
    start: "Avvia la registrazione",
    active: "Registrazione di tempi e passi attiva · {code}",
    stop: "Ferma",
    refusals: {
      ACTIVITY_INPUT_INVALID: "Il codice non è valido.",
      ACTIVITY_SESSION_ACTIVE: "Una sessione di prova è già attiva.",
      ACTIVITY_SESSION_CODE_USED: "Questo codice è già stato usato in questo progetto.",
      FAILED: "La registrazione non è partita. Riprova.",
    },
  },
  en: {
    title: "Study session",
    intro:
      "Records which sections and details you open and when. It does not record what you type or the project's content.",
    label: "Session code",
    hint: "Use a code such as SES-P01, without names.",
    start: "Start recording",
    active: "Recording of times and steps is on · {code}",
    stop: "Stop",
    refusals: {
      ACTIVITY_INPUT_INVALID: "The code is not valid.",
      ACTIVITY_SESSION_ACTIVE: "A study session is already active.",
      ACTIVITY_SESSION_CODE_USED: "This code was already used in this project.",
      FAILED: "Recording did not start. Try again.",
    },
  },
} as const;

const journal = useActivityJournalStore();
const copy = computed(() => messages[props.locale]);
const draft = ref("");
const refusal = ref<Refusal | null>(null);
const summary = ref<HTMLElement | null>(null);
const stopButton = ref<InstanceType<typeof UiButton> | null>(null);
const fieldId = useId();
const hintId = useId();
const errorId = useId();
const statusId = useId();
const describedBy = computed(() => (refusal.value === null ? hintId : `${hintId} ${errorId}`));
const statusText = computed(() => copy.value.active.replace("{code}", journal.code ?? ""));

async function start(): Promise<void> {
  if (journal.starting) return;
  refusal.value = null;
  const outcome = await journal.start(draft.value);
  if (outcome !== "STARTED") {
    refusal.value = outcome;
    return;
  }
  draft.value = "";
  await nextTick();
  const element: unknown = stopButton.value?.$el;
  if (element instanceof HTMLElement) element.focus();
}

async function stop(): Promise<void> {
  if (!(await journal.stop())) return;
  await nextTick();
  summary.value?.focus();
}
</script>

<template>
  <Teleport :to="rowTarget" :disabled="rowTarget === null">
    <div
      v-if="journal.recording"
      role="status"
      class="mb-6 flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 rounded-panel border border-petrol-on-night/35 bg-petrol-on-night/8 py-2 pr-2 pl-4"
      data-testid="activity-session-active"
    >
      <span aria-hidden="true" class="h-2 w-2 shrink-0 rounded-full bg-fail-on-night" />
      <p
        :id="statusId"
        class="m-0 min-w-0 flex-1 text-sm leading-normal wrap-anywhere text-on-night"
        data-testid="activity-session-status"
      >
        {{ statusText }}
      </p>
      <UiButton
        ref="stopButton"
        variant="outline"
        :disabled="journal.stopping"
        :aria-describedby="statusId"
        data-testid="activity-session-stop"
        @click="stop"
      >
        {{ copy.stop }}
      </UiButton>
    </div>
  </Teleport>
  <details
    v-if="!journal.recording"
    class="mt-6 rounded-field border border-night-line text-sm text-on-night-2"
    data-testid="activity-session"
  >
    <summary ref="summary" class="min-h-11 cursor-pointer px-4 py-3 font-semibold text-on-night">
      {{ copy.title }}
    </summary>
    <form class="grid gap-4 border-t border-night-line p-4" novalidate @submit.prevent="start">
      <p class="m-0 max-w-[68ch] leading-normal">{{ copy.intro }}</p>
      <div class="grid max-w-sm min-w-0 gap-1.5">
        <label :for="fieldId" class="font-semibold text-on-night">{{ copy.label }}</label>
        <input
          :id="fieldId"
          v-model="draft"
          type="text"
          maxlength="24"
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          :aria-invalid="refusal === 'ACTIVITY_INPUT_INVALID' ? 'true' : undefined"
          :aria-describedby="describedBy"
          class="min-h-11 w-full min-w-0 rounded-field border border-night-line-strong bg-night-panel px-3 font-mono text-on-night"
          data-testid="activity-session-code"
          @input="refusal = null"
        />
        <p :id="hintId" class="m-0 text-xs leading-normal text-on-night-3">{{ copy.hint }}</p>
      </div>
      <p
        v-if="refusal !== null"
        :id="errorId"
        role="alert"
        class="m-0 text-fail-on-night"
        data-testid="activity-session-error"
      >
        {{ copy.refusals[refusal] }}
      </p>
      <div>
        <UiButton
          type="submit"
          variant="outline"
          :disabled="journal.starting"
          data-testid="activity-session-start"
        >
          {{ copy.start }}
        </UiButton>
      </div>
    </form>
  </details>
</template>
