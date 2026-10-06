<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import UiAgentMessage from "./UiAgentMessage.vue";
import UiButton from "./UiButton.vue";
import { useSurface, type SurfaceContext } from "./UiSurface.vue";
import { modelFeedback } from "./modelFeedback";
import { GENERATION_POLL_TIMEOUT, type GenerationRequestJob } from "../api/generationJobs";
import { generationFailureMessage } from "../stores/designMockups";
import type { GenerationResumeFailure } from "../stores/generationJobs";
import type { GenerationOperation } from "../types/designMockups";

type Locale = "en" | "it";

interface Subject {
  what: string;
  of: string;
}

export interface GenerationAgentVoice {
  role: string;
  avatar: string;
  message: string;
}

const props = withDefaults(
  defineProps<{
    job: GenerationRequestJob | null;
    failure?: GenerationResumeFailure | null;
    locale?: Locale;
    surface?: SurfaceContext | undefined;
    agent?: GenerationAgentVoice | null;
  }>(),
  { failure: null, locale: "en", surface: undefined, agent: null },
);

const emit = defineEmits<{ dismiss: [] }>();

const messages = {
  en: {
    running: "The Studio is generating {what}.",
    since: "Started at {time}, {elapsed} ago.",
    justNow: "Started at {time}, a few seconds ago.",
    second: "1 second",
    seconds: "{n} seconds",
    minute: "1 minute",
    minutes: "{n} minutes",
    leave:
      "You can leave this page and come back later: the generation keeps going and the result will appear here.",
    failed: "The generation {of} did not succeed.",
    lost: "The generation {of} stopped, perhaps because the Studio was restarted.",
    lostHint: "It does not start again on its own: you can start it again whenever you want.",
    late: "The generation {of} has been running for more than twenty minutes.",
    lateHint: "Come back later or reload the page to see whether it is ready.",
    dismiss: "Close",
    subjects: {
      MOCKUP: { what: "the mockup", of: "of the mockup" },
      ITERATION: { what: "the change to the design", of: "of the change to the design" },
      PERSONA_PROPOSAL: { what: "the user profiles", of: "of the user profiles" },
      USER_TWIN_GENERATION: { what: "the user twins", of: "of the user twins" },
      REQUIREMENTS_PROPOSAL: { what: "the requirements", of: "of the requirements" },
      REQUIREMENTS_CHANGE: { what: "the requirements", of: "of the requirements" },
      DESIGN_PROPOSAL: { what: "the design alternatives", of: "of the design alternatives" },
      DESIGN_REGENERATION: {
        what: "the new design alternatives",
        of: "of the new design alternatives",
      },
      DESIGN_EVALUATION: {
        what: "the twins' review of the design",
        of: "of the twins' review of the design",
      },
      DISCUSSION_START: { what: "the twins' discussion", of: "of the twins' discussion" },
      DISCUSSION_ROUND: {
        what: "a new round of the discussion",
        of: "of the new round of the discussion",
      },
      CODE_CHANGE_REVIEW: {
        what: "the twins' review of a commit",
        of: "of the twins' review of a commit",
      },
      TEST_PLAN: {
        what: "the paths that verify the acceptance criteria",
        of: "of the paths that verify the acceptance criteria",
      },
      TEST_REVIEW: {
        what: "the twins' review of the test results",
        of: "of the twins' review of the test results",
      },
      TWIN_UPDATE: {
        what: "the proposal of what a twin learned",
        of: "of the proposal of what a twin learned",
      },
      KNOWLEDGE_ALIGNMENT: {
        what: "the alignment of the knowledge to the code",
        of: "of the alignment of the knowledge to the code",
      },
      DESIGN_CHANGE: {
        what: "the change to the design from the words",
        of: "of the change to the design from the words",
      },
    } satisfies Record<GenerationOperation, Subject>,
  },
  it: {
    running: "Lo Studio sta generando {what}.",
    since: "Iniziata alle {time}, {elapsed} fa.",
    justNow: "Iniziata alle {time}, pochi secondi fa.",
    second: "1 secondo",
    seconds: "{n} secondi",
    minute: "1 minuto",
    minutes: "{n} minuti",
    leave:
      "Puoi lasciare questa pagina e tornare più tardi: la generazione continua e il risultato comparirà qui.",
    failed: "La generazione {of} non è riuscita.",
    lost: "La generazione {of} si è interrotta, forse perché lo Studio è stato riavviato.",
    lostHint: "Non riparte da sola: puoi avviarla di nuovo quando vuoi.",
    late: "La generazione {of} dura da più di venti minuti.",
    lateHint: "Torna più tardi o ricarica la pagina per vedere se è pronta.",
    dismiss: "Chiudi",
    subjects: {
      MOCKUP: { what: "il mockup", of: "del mockup" },
      ITERATION: { what: "la modifica del design", of: "della modifica del design" },
      PERSONA_PROPOSAL: { what: "i profili degli utenti", of: "dei profili degli utenti" },
      USER_TWIN_GENERATION: { what: "i twin degli utenti", of: "dei twin degli utenti" },
      REQUIREMENTS_PROPOSAL: { what: "i requisiti", of: "dei requisiti" },
      REQUIREMENTS_CHANGE: { what: "i requisiti", of: "dei requisiti" },
      DESIGN_PROPOSAL: { what: "le alternative di design", of: "delle alternative di design" },
      DESIGN_REGENERATION: {
        what: "le nuove alternative di design",
        of: "delle nuove alternative di design",
      },
      DESIGN_EVALUATION: {
        what: "la revisione dei twin sul design",
        of: "della revisione dei twin sul design",
      },
      DISCUSSION_START: { what: "la discussione dei twin", of: "della discussione dei twin" },
      DISCUSSION_ROUND: {
        what: "un nuovo giro della discussione",
        of: "del nuovo giro della discussione",
      },
      CODE_CHANGE_REVIEW: {
        what: "la revisione dei twin su un commit",
        of: "della revisione dei twin su un commit",
      },
      TEST_PLAN: {
        what: "i percorsi di verifica dei criteri",
        of: "dei percorsi di verifica dei criteri",
      },
      TEST_REVIEW: {
        what: "la revisione dei twin sui risultati dei test",
        of: "della revisione dei twin sui risultati dei test",
      },
      TWIN_UPDATE: {
        what: "la proposta di ciò che un twin ha imparato",
        of: "della proposta di ciò che un twin ha imparato",
      },
      KNOWLEDGE_ALIGNMENT: {
        what: "l'allineamento della conoscenza al codice",
        of: "dell'allineamento della conoscenza al codice",
      },
      DESIGN_CHANGE: {
        what: "la modifica del design dalle parole",
        of: "della modifica del design dalle parole",
      },
    } satisfies Record<GenerationOperation, Subject>,
  },
} as const;

const JUST_NOW_SECONDS = 10;

const context = useSurface(() => props.surface);
const copy = computed(() => messages[props.locale]);
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;

const palettes = {
  light: {
    running: "border-line bg-surface-2 text-ink-2",
    title: "text-ink",
    spinner: "border-line-strong border-t-action",
    failure: "border-fail-line bg-fail-bg text-fail-dark",
  },
  night: {
    running: "border-night-line bg-night-raised text-on-night-2",
    title: "text-on-night",
    spinner: "border-night-line-strong border-t-petrol-on-night",
    failure: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
  },
};

const palette = computed(() => palettes[context.value]);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function subject(operation: GenerationOperation): Subject {
  return copy.value.subjects[operation];
}

function elapsedText(seconds: number): string {
  if (seconds < 60) {
    return seconds === 1 ? copy.value.second : fill(copy.value.seconds, { n: seconds });
  }

  const minutes = Math.floor(seconds / 60);

  return minutes === 1 ? copy.value.minute : fill(copy.value.minutes, { n: minutes });
}

const runningTitle = computed(() =>
  props.job === null ? "" : fill(copy.value.running, { what: subject(props.job.operation).what }),
);

const sinceText = computed(() => {
  if (props.job === null) {
    return "";
  }

  const started = Date.parse(props.job.started_at);

  if (Number.isNaN(started)) {
    return "";
  }

  const time = new Intl.DateTimeFormat(props.locale, { timeStyle: "short" }).format(started);
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));

  return seconds < JUST_NOW_SECONDS
    ? fill(copy.value.justNow, { time })
    : fill(copy.value.since, { time, elapsed: elapsedText(seconds) });
});

const failureTitle = computed(() => {
  const failure = props.failure;

  if (failure === null) {
    return "";
  }

  const of = subject(failure.operation).of;

  if (failure.lost) {
    return fill(copy.value.lost, { of });
  }

  return fill(failure.code === GENERATION_POLL_TIMEOUT ? copy.value.late : copy.value.failed, {
    of,
  });
});

const failureText = computed(() => {
  const failure = props.failure;

  if (failure === null) {
    return "";
  }

  if (failure.lost) {
    return copy.value.lostHint;
  }

  if (failure.code === GENERATION_POLL_TIMEOUT) {
    return copy.value.lateHint;
  }

  return (
    modelFeedback(failure.code, props.locale) ??
    generationFailureMessage(failure.code, props.locale)
  );
});

function stopClock(): void {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

watch(
  () => props.job?.job_id ?? null,
  (jobId) => {
    stopClock();
    now.value = Date.now();

    if (jobId !== null) {
      timer = setInterval(() => {
        now.value = Date.now();
      }, 1000);
    }
  },
  { immediate: true },
);

onBeforeUnmount(stopClock);
</script>

<template>
  <div
    v-if="job !== null && agent !== null"
    data-testid="generation-job-notice"
    :data-operation="job.operation"
    :data-job-id="job.job_id"
  >
    <UiAgentMessage :role-label="agent.role" :avatar="agent.avatar" :surface="surface">
      <div class="flex items-center gap-2.5">
        <span
          :class="[
            'inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2',
            palette.spinner,
          ]"
          aria-hidden="true"
        />
        <p role="status" :class="['m-0 font-semibold', palette.title]">{{ agent.message }}</p>
      </div>
      <p v-if="sinceText" class="m-0 mt-1" data-testid="generation-job-since">
        {{ sinceText }}
      </p>
      <p class="m-0 mt-1">{{ copy.leave }}</p>
      <div v-if="$slots.default" class="mt-3">
        <slot />
      </div>
    </UiAgentMessage>
  </div>
  <div
    v-else-if="job !== null"
    :class="['rounded-panel border px-5 py-4', palette.running]"
    data-testid="generation-job-notice"
    :data-operation="job.operation"
    :data-job-id="job.job_id"
  >
    <div class="flex items-center gap-3">
      <span
        :class="[
          'inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2',
          palette.spinner,
        ]"
        aria-hidden="true"
      />
      <p role="status" :class="['m-0 text-[15px] font-semibold', palette.title]">
        {{ runningTitle }}
      </p>
    </div>
    <p
      v-if="sinceText"
      class="m-0 mt-1 text-[15px] leading-normal"
      data-testid="generation-job-since"
    >
      {{ sinceText }}
    </p>
    <p class="m-0 mt-1 text-[15px] leading-normal">{{ copy.leave }}</p>
  </div>
  <div
    v-else-if="failure !== null"
    :class="['grid gap-2 rounded-panel border px-5 py-4', palette.failure]"
    role="alert"
    data-testid="generation-job-failure"
    :data-code="failure.code"
    :data-lost="failure.lost ? 'true' : 'false'"
  >
    <p class="m-0 text-[15px] font-semibold">{{ failureTitle }}</p>
    <p class="m-0 text-[15px] leading-normal">{{ failureText }}</p>
    <div>
      <UiButton variant="quiet" data-testid="generation-job-dismiss" @click="emit('dismiss')">
        {{ copy.dismiss }}
      </UiButton>
    </div>
  </div>
</template>
