<script setup lang="ts">
import { computed } from "vue";

import type {
  WorkflowCheckpointPayload,
  WorkflowEventPayload,
  WorkflowLifecycleAction,
  WorkflowRunPayload,
} from "@/types/workflowRuns";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    run: WorkflowRunPayload;
    checkpoints?: WorkflowCheckpointPayload[];
    events?: WorkflowEventPayload[];
    locale?: Locale;
    busy?: boolean;
  }>(),
  {
    checkpoints: () => [],
    events: () => [],
    locale: "en",
    busy: false,
  },
);

const emit = defineEmits<{
  lifecycle: [action: WorkflowLifecycleAction];
  replay: [];
}>();

const messages = {
  en: {
    eyebrow: "Governed workflow",
    title: "Run timeline and controls",
    stage: "Current stage",
    status: "Run status",
    stateVersion: "State version",
    checkpointSequence: "Checkpoint sequence",
    checkpoints: "Durable checkpoints",
    noCheckpoints: "No durable checkpoint has been recorded yet.",
    events: "Ordered workflow events",
    noEvents: "No workflow event has been replayed yet.",
    controls: "Owner controls",
    pause: "Pause run",
    resume: "Resume run",
    cancel: "Cancel run",
    replay: "Replay newer events",
    eventSequence: "Sequence {sequence}",
    checkpointSequenceLabel: "Checkpoint {sequence}",
    methodological:
      "These controls govern orchestration state. Owner approval remains distinct from empirical target-user validation.",
  },
  it: {
    eyebrow: "Workflow governato",
    title: "Timeline e controlli della run",
    stage: "Fase corrente",
    status: "Stato della run",
    stateVersion: "Versione dello stato",
    checkpointSequence: "Sequenza checkpoint",
    checkpoints: "Checkpoint persistenti",
    noCheckpoints: "Non è ancora stato registrato alcun checkpoint persistente.",
    events: "Eventi ordinati del workflow",
    noEvents: "Non è ancora stato riprodotto alcun evento del workflow.",
    controls: "Controlli del proprietario",
    pause: "Metti in pausa",
    resume: "Riprendi run",
    cancel: "Annulla run",
    replay: "Riproduci nuovi eventi",
    eventSequence: "Sequenza {sequence}",
    checkpointSequenceLabel: "Checkpoint {sequence}",
    methodological:
      "Questi controlli governano lo stato dell'orchestrazione. L'approvazione del proprietario resta distinta dalla validazione empirica con utenti target.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const orderedCheckpoints = computed(() =>
  [...props.checkpoints].sort((left, right) => left.sequence_number - right.sequence_number),
);
const orderedEvents = computed(() =>
  [...props.events].sort((left, right) => left.sequence_number - right.sequence_number),
);
const canPause = computed(
  () => props.run.status === "RUNNING" || props.run.status === "WAITING_FOR_HUMAN",
);
const canResume = computed(
  () => props.run.status === "PAUSED" || props.run.status === "PAUSED_NEEDS_HUMAN",
);
const canCancel = computed(() => !["FAILED", "CANCELLED", "APPROVED"].includes(props.run.status));

function formatTimestamp(value: string): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(props.locale, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(timestamp);
}

function lifecycle(action: WorkflowLifecycleAction): void {
  emit("lifecycle", action);
}
</script>

<template>
  <section class="grid gap-6" aria-labelledby="workflow-run-timeline-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-hypothesis uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="workflow-run-timeline-title" class="m-0 text-2xl font-semibold text-ink">
        {{ copy.title }}
      </h2>
      <p
        class="m-0 rounded-panel border border-hypothesis-line bg-hypothesis-bg p-4 text-sm text-hypothesis-text"
      >
        {{ copy.methodological }}
      </p>
    </header>

    <dl
      class="grid gap-3 rounded-card border border-line bg-white p-5 sm:grid-cols-2 lg:grid-cols-4"
    >
      <div>
        <dt class="font-bold text-ink-2">{{ copy.stage }}</dt>
        <dd class="m-0" data-testid="workflow-stage">{{ run.current_stage }}</dd>
      </div>
      <div>
        <dt class="font-bold text-ink-2">{{ copy.status }}</dt>
        <dd class="m-0" aria-live="polite" data-testid="workflow-status">{{ run.status }}</dd>
      </div>
      <div>
        <dt class="font-bold text-ink-2">{{ copy.stateVersion }}</dt>
        <dd class="m-0">{{ run.state_version }}</dd>
      </div>
      <div>
        <dt class="font-bold text-ink-2">{{ copy.checkpointSequence }}</dt>
        <dd class="m-0">{{ run.checkpoint_sequence }}</dd>
      </div>
    </dl>

    <section class="grid gap-3" aria-labelledby="workflow-owner-controls-title">
      <h3 id="workflow-owner-controls-title" class="m-0 text-xl font-semibold">
        {{ copy.controls }}
      </h3>
      <div class="flex flex-wrap gap-3">
        <button
          type="button"
          class="rounded-control border border-field bg-white px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canPause"
          @click="lifecycle('pause')"
        >
          {{ copy.pause }}
        </button>
        <button
          type="button"
          class="rounded-control border border-field bg-white px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canResume"
          @click="lifecycle('resume')"
        >
          {{ copy.resume }}
        </button>
        <button
          type="button"
          class="rounded-control border border-fail-line bg-fail-bg px-4 py-2 font-bold text-fail-dark disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy || !canCancel"
          @click="lifecycle('cancel')"
        >
          {{ copy.cancel }}
        </button>
        <button
          type="button"
          class="rounded-control border border-hypothesis-line bg-hypothesis-bg px-4 py-2 font-bold text-hypothesis-text disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="busy"
          @click="emit('replay')"
        >
          {{ copy.replay }}
        </button>
      </div>
    </section>

    <section class="grid gap-3" aria-labelledby="workflow-checkpoint-list-title">
      <h3 id="workflow-checkpoint-list-title" class="m-0 text-xl font-semibold">
        {{ copy.checkpoints }}
      </h3>
      <p v-if="orderedCheckpoints.length === 0">{{ copy.noCheckpoints }}</p>
      <ol v-else class="m-0 grid list-decimal gap-3 pl-6">
        <li
          v-for="checkpoint in orderedCheckpoints"
          :key="checkpoint.id"
          class="rounded-panel border border-line bg-white p-4"
        >
          <strong>
            {{
              copy.checkpointSequenceLabel.replace("{sequence}", String(checkpoint.sequence_number))
            }}
          </strong>
          <span class="block text-sm text-ink-2">
            {{ formatTimestamp(checkpoint.created_at) }} · state {{ checkpoint.state_version }}
          </span>
        </li>
      </ol>
    </section>

    <section class="grid gap-3" aria-labelledby="workflow-event-list-title">
      <h3 id="workflow-event-list-title" class="m-0 text-xl font-semibold">
        {{ copy.events }}
      </h3>
      <p v-if="orderedEvents.length === 0" aria-live="polite">{{ copy.noEvents }}</p>
      <ol v-else class="m-0 grid list-decimal gap-3 pl-6" aria-live="polite">
        <li
          v-for="event in orderedEvents"
          :key="event.id"
          class="rounded-panel border border-line bg-white p-4"
          :data-event-sequence="event.sequence_number"
        >
          <strong>{{ event.event_type }}</strong>
          <span class="block text-sm text-ink-2">
            {{ copy.eventSequence.replace("{sequence}", String(event.sequence_number)) }} ·
            {{ formatTimestamp(event.occurred_at) }}
          </span>
        </li>
      </ol>
    </section>
  </section>
</template>
