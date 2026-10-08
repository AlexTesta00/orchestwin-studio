<script setup lang="ts">
import { computed, nextTick, ref, shallowRef, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { activityApi, type ActivityApi } from "../api/activity";
import type { AuthorizedRequest } from "../stores/activityJournal";
import { SECTIONS, type ProjectActivity, type ProjectActivitySection } from "../types/activity";

const SECTION_COLUMNS = [
  "first_event_at",
  "first_approved_at",
  "elapsed_seconds",
  "owner_actions",
  "succeeded",
  "failed",
  "wait_seconds",
] as const;
const SESSION_COLUMNS = [
  "dwell_seconds",
  "details_opened",
  "why_opened",
  "mockups_opened",
] as const;

type ColumnKey = (typeof SECTION_COLUMNS)[number] | (typeof SESSION_COLUMNS)[number];

type Reading =
  | { kind: "moment"; value: string | null }
  | { kind: "duration"; value: number | null }
  | { kind: "count"; value: number };

interface Shown {
  text: string | null;
  datetime: string | null;
}

interface Fact extends Shown {
  key: string;
  label: string;
}

const MOMENTS: ReadonlySet<ColumnKey> = new Set(["first_event_at", "first_approved_at"]);
const CLOCK: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
};
const READINGS: Readonly<Record<ColumnKey, (item: ProjectActivitySection) => Reading>> = {
  first_event_at: (item) => ({ kind: "moment", value: item.first_event_at }),
  first_approved_at: (item) => ({ kind: "moment", value: item.first_approved_at }),
  elapsed_seconds: (item) => ({ kind: "duration", value: item.elapsed_seconds }),
  owner_actions: (item) => ({ kind: "count", value: item.owner_actions }),
  succeeded: (item) => ({ kind: "count", value: item.generations.succeeded }),
  failed: (item) => ({ kind: "count", value: item.generations.failed }),
  wait_seconds: (item) => ({
    kind: "duration",
    value: item.generations.count === 0 ? null : item.generations.wait_seconds,
  }),
  dwell_seconds: (item) => ({ kind: "duration", value: item.journal.dwell_seconds }),
  details_opened: (item) => ({ kind: "count", value: item.journal.details_opened }),
  why_opened: (item) => ({ kind: "count", value: item.journal.why_opened }),
  mockups_opened: (item) => ({ kind: "count", value: item.journal.mockups_opened }),
};

const props = withDefaults(
  defineProps<{
    projectId: string;
    authorize: AuthorizedRequest;
    locale?: "it" | "en";
    api?: ActivityApi;
  }>(),
  { locale: "en", api: () => activityApi },
);

const messages = {
  it: {
    title: "Tempi e passi del progetto",
    loading: "Carico…",
    failed: "Non è stato possibile leggere i tempi e i passi del progetto.",
    retry: "Riprova",
    refresh: "Aggiorna",
    missing: "non ancora",
    caption: "Tempi e passi per sezione",
    section: "Sezione",
    sections: {
      BRIEF: "Brief",
      TEAM: "Prospettive",
      USER_TWINS: "User Twin",
      REQUIREMENTS: "Definizione",
      DESIGN: "Design e valutazione",
      PACKAGE: "Dossier",
    },
    columns: {
      first_event_at: "Primo evento",
      first_approved_at: "Prima approvazione",
      elapsed_seconds: "Tempo fino all'approvazione",
      owner_actions: "Gesti",
      succeeded: "Generazioni riuscite",
      failed: "Generazioni fallite",
      wait_seconds: "Attesa delle generazioni",
      dwell_seconds: "Permanenza",
      details_opened: "Dettagli aperti",
      why_opened: "Perché? aperti",
      mockups_opened: "Mockup aperti",
    },
    totals: "Totali",
    totalLabels: {
      events: "Eventi",
      owner_actions: "Gesti",
      generations: "Generazioni",
      wait: "Attesa delle generazioni",
    },
    sessions: "Sessioni di prova",
    noSessions: "Nessuna sessione di prova.",
    sessionLabels: {
      started: "Inizio",
      ended: "Fine",
      running: "in corso",
      events: "Eventi",
      discarded: "Intervalli scartati",
    },
    limitsTitle: "Limiti della misura",
    limits: {
      ACTOR_DERIVED_FROM_RECORD_KIND:
        "Chi ha fatto ogni passo si ricava dal tipo di registrazione.",
      CLIENT_CLOCK_NOT_VERIFIED:
        "Gli orari mandati dal browser e da ut vengono dall'orologio del computer, che lo Studio non verifica.",
      ELAPSED_INCLUDES_IDLE_TIME: "I tempi comprendono le pause.",
      FAILED_EVALUATION_RUNS_NOT_RECORDED:
        "Le valutazioni dei twin non riuscite non si registrano.",
      GENERATION_JOBS_NOT_PERSISTED:
        "Le generazioni ancora in corso non si salvano: se lo Studio si ferma, possono mancare.",
      PRE_MODEL_REFUSALS_NOT_RECORDED:
        "Le richieste rifiutate prima di arrivare al modello non si registrano.",
      VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS:
        "Sezioni, dettagli, Perché? e mockup aperti si contano solo durante una sessione di prova.",
    },
  },
  en: {
    title: "Times and steps of the project",
    loading: "Loading…",
    failed: "The times and steps of the project could not be read.",
    retry: "Try again",
    refresh: "Refresh",
    missing: "not yet",
    caption: "Times and steps by section",
    section: "Section",
    sections: {
      BRIEF: "Brief",
      TEAM: "Perspectives",
      USER_TWINS: "User Twin",
      REQUIREMENTS: "Definition",
      DESIGN: "Design & Evaluation",
      PACKAGE: "Dossier",
    },
    columns: {
      first_event_at: "First event",
      first_approved_at: "First approval",
      elapsed_seconds: "Time to approval",
      owner_actions: "Actions",
      succeeded: "Successful generations",
      failed: "Failed generations",
      wait_seconds: "Wait for generations",
      dwell_seconds: "Time spent",
      details_opened: "Details opened",
      why_opened: "Why? opened",
      mockups_opened: "Mockups opened",
    },
    totals: "Totals",
    totalLabels: {
      events: "Events",
      owner_actions: "Actions",
      generations: "Generations",
      wait: "Wait for generations",
    },
    sessions: "Study sessions",
    noSessions: "No study session.",
    sessionLabels: {
      started: "Start",
      ended: "End",
      running: "in progress",
      events: "Events",
      discarded: "Discarded intervals",
    },
    limitsTitle: "Limits of the measure",
    limits: {
      ACTOR_DERIVED_FROM_RECORD_KIND: "Who took each step is inferred from the kind of record.",
      CLIENT_CLOCK_NOT_VERIFIED:
        "The times sent by the browser and by ut come from the computer's clock, which the Studio does not check.",
      ELAPSED_INCLUDES_IDLE_TIME: "The times include breaks.",
      FAILED_EVALUATION_RUNS_NOT_RECORDED: "Twin evaluations that failed are not recorded.",
      GENERATION_JOBS_NOT_PERSISTED:
        "Generations still running are not saved: if the Studio stops, they may be missing.",
      PRE_MODEL_REFUSALS_NOT_RECORDED:
        "Requests refused before they reach the model are not recorded.",
      VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS:
        "Sections, details, Why? and mockups opened are counted only during a study session.",
    },
  },
} as const;

const copy = computed(() => messages[props.locale]);
const language = computed(() => (props.locale === "it" ? "it-IT" : "en-GB"));
const clock = computed(() => new Intl.DateTimeFormat(language.value, CLOCK));
const numbers = computed(() => new Intl.NumberFormat(language.value));
const panel = ref<HTMLDetailsElement | null>(null);
const action = ref<InstanceType<typeof UiButton> | null>(null);
const activity = shallowRef<ProjectActivity | null>(null);
const loading = ref(false);
const failed = ref(false);
const captionId = `activity-timeline-${useId()}`;
const actionKind = computed(() => (activity.value === null ? "retry" : "refresh"));
let requested = false;
let epoch = 0;

function moment(value: string): string {
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? value : clock.value.format(instant);
}

function amount(value: number): string {
  return numbers.value.format(value);
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function duration(seconds: number): string {
  const total = Math.max(Math.trunc(seconds), 0);
  if (total < 60) return `${total} s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes} min ${pad(total % 60)} s`;
  return `${Math.floor(minutes / 60)} h ${pad(minutes % 60)} min`;
}

function shown(reading: Reading): Shown {
  switch (reading.kind) {
    case "moment":
      return reading.value === null
        ? { text: null, datetime: null }
        : { text: moment(reading.value), datetime: reading.value };
    case "duration":
      return { text: reading.value === null ? null : duration(reading.value), datetime: null };
    case "count":
      return { text: amount(reading.value), datetime: null };
  }
}

function fact(key: string, label: string, reading: Reading): Fact {
  return { key, label, ...shown(reading) };
}

const sessions = computed(() => {
  const labels = copy.value.sessionLabels;
  return (activity.value?.sessions ?? []).map((session) => ({
    code: session.code,
    facts: [
      fact("started", labels.started, { kind: "moment", value: session.started_at }),
      session.ended_at === null
        ? { key: "ended", label: labels.ended, text: labels.running, datetime: null }
        : fact("ended", labels.ended, { kind: "moment", value: session.ended_at }),
      fact("events", labels.events, { kind: "count", value: session.events }),
      fact("discarded", labels.discarded, { kind: "count", value: session.discarded_intervals }),
    ],
  }));
});

const columns = computed<readonly ColumnKey[]>(() =>
  sessions.value.length > 0 ? [...SECTION_COLUMNS, ...SESSION_COLUMNS] : SECTION_COLUMNS,
);

const headings = computed(() =>
  columns.value.map((key) => ({
    key,
    label: copy.value.columns[key],
    numeric: !MOMENTS.has(key),
  })),
);

const rows = computed(() => {
  const found = activity.value?.sections ?? [];
  const ordered = [...found].sort((a, b) => SECTIONS.indexOf(a.key) - SECTIONS.indexOf(b.key));
  return ordered.map((item) => ({
    key: item.key,
    cells: columns.value.map((key) => ({
      key,
      numeric: !MOMENTS.has(key),
      ...shown(READINGS[key](item)),
    })),
  }));
});

const totals = computed(() => {
  const summary = activity.value?.totals;
  if (summary === undefined) return [];
  const labels = copy.value.totalLabels;
  const wait = summary.generations === 0 ? null : summary.generation_wait_seconds;
  return [
    fact("events", labels.events, { kind: "count", value: summary.events }),
    fact("owner_actions", labels.owner_actions, { kind: "count", value: summary.owner_actions }),
    fact("generations", labels.generations, { kind: "count", value: summary.generations }),
    fact("wait", labels.wait, { kind: "duration", value: wait }),
  ];
});

const limits = computed(() => {
  const known = new Map<string, string>(Object.entries(copy.value.limits));
  return [...new Set(activity.value?.limits ?? [])].map((code) => ({
    code,
    text: known.get(code) ?? null,
  }));
});

async function load(): Promise<void> {
  const project = props.projectId;
  const current = ++epoch;
  loading.value = true;
  try {
    const result = await props.authorize((token) => props.api.current(project, token));
    if (current !== epoch) return;
    activity.value = result;
    failed.value = false;
  } catch {
    if (current === epoch) failed.value = true;
  } finally {
    if (current === epoch) loading.value = false;
  }
}

function toggled(): void {
  if (panel.value?.open !== true || requested) return;
  requested = true;
  void load();
}

function actionElement(): HTMLElement | null {
  const element: unknown = action.value?.$el;
  return element instanceof HTMLElement ? element : null;
}

async function reread(): Promise<void> {
  if (loading.value) return;
  const button = actionElement();
  const focused = button !== null && document.activeElement === button;
  await load();
  if (!focused) return;
  await nextTick();
  if (document.activeElement === null || document.activeElement === document.body) {
    actionElement()?.focus();
  }
}

watch(
  () => props.projectId,
  () => {
    epoch += 1;
    activity.value = null;
    failed.value = false;
    loading.value = false;
    requested = false;
    toggled();
  },
);
</script>

<template>
  <details
    ref="panel"
    class="mt-4 min-w-0 rounded-field border border-night-line text-sm text-on-night-2"
    data-testid="activity-timeline"
    @toggle="toggled"
  >
    <summary class="min-h-11 cursor-pointer px-4 py-3 font-semibold text-on-night">
      {{ copy.title }}
    </summary>
    <div
      class="grid min-w-0 gap-5 border-t border-night-line p-4"
      :aria-busy="loading ? 'true' : undefined"
    >
      <p
        v-if="failed && !loading"
        role="alert"
        class="m-0 max-w-[68ch] leading-normal text-fail-on-night"
        data-testid="activity-timeline-error"
      >
        {{ copy.failed }}
      </p>
      <div class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
        <UiButton
          v-if="activity !== null || failed"
          ref="action"
          variant="outline"
          :disabled="loading"
          :data-testid="`activity-timeline-${actionKind}`"
          @click="reread"
        >
          {{ copy[actionKind] }}
        </UiButton>
        <p
          role="status"
          :class="loading ? 'm-0 leading-normal' : 'sr-only'"
          data-testid="activity-timeline-status"
        >
          {{ loading ? copy.loading : "" }}
        </p>
      </div>
      <template v-if="activity !== null">
        <div
          v-if="rows.length > 0"
          class="min-w-0 overflow-x-auto rounded-field border border-night-line"
          role="region"
          tabindex="0"
          :aria-labelledby="captionId"
          data-testid="activity-timeline-sections"
        >
          <table class="w-full border-collapse text-left text-[13px]">
            <caption :id="captionId" class="sr-only">
              {{
                copy.caption
              }}
            </caption>
            <thead class="border-b border-night-line bg-on-night/3">
              <tr>
                <th scope="col" class="py-3 pr-3 pl-4 align-bottom font-semibold text-on-night-2">
                  {{ copy.section }}
                </th>
                <th
                  v-for="heading in headings"
                  :key="heading.key"
                  scope="col"
                  :class="[
                    'px-3 py-3 align-bottom font-semibold text-on-night-2 last:pr-4',
                    heading.numeric ? 'text-right' : '',
                  ]"
                  :data-column="heading.key"
                >
                  {{ heading.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in rows"
                :key="row.key"
                class="border-t border-on-night/8 align-top first:border-t-0"
                :data-section="row.key"
                data-testid="activity-timeline-section"
              >
                <th scope="row" class="py-3 pr-3 pl-4 font-medium whitespace-nowrap text-on-night">
                  {{ copy.sections[row.key] }}
                </th>
                <td
                  v-for="cell in row.cells"
                  :key="cell.key"
                  :class="[
                    'px-3 py-3 whitespace-nowrap text-on-night last:pr-4',
                    cell.numeric ? 'text-right tabular-nums' : '',
                  ]"
                  :data-column="cell.key"
                >
                  <span v-if="cell.text === null" role="img" :aria-label="copy.missing">–</span>
                  <time v-else-if="cell.datetime" :datetime="cell.datetime">{{ cell.text }}</time>
                  <template v-else>{{ cell.text }}</template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid min-w-0 gap-2">
          <h3 class="m-0 text-sm font-semibold text-on-night">{{ copy.totals }}</h3>
          <dl
            class="m-0 flex min-w-0 flex-wrap gap-x-6 gap-y-2"
            data-testid="activity-timeline-totals"
          >
            <div
              v-for="total in totals"
              :key="total.key"
              class="flex min-w-0 items-baseline gap-1.5"
              :data-total="total.key"
            >
              <dt class="text-on-night-3">{{ total.label }}</dt>
              <dd class="m-0 font-semibold text-on-night tabular-nums">
                <span v-if="total.text === null" role="img" :aria-label="copy.missing">–</span>
                <template v-else>{{ total.text }}</template>
              </dd>
            </div>
          </dl>
        </div>
        <div class="grid min-w-0 gap-2">
          <h3 class="m-0 text-sm font-semibold text-on-night">{{ copy.sessions }}</h3>
          <p
            v-if="sessions.length === 0"
            class="m-0 leading-normal"
            data-testid="activity-timeline-no-sessions"
          >
            {{ copy.noSessions }}
          </p>
          <ul v-else class="m-0 grid list-none gap-2 p-0" data-testid="activity-timeline-sessions">
            <li
              v-for="session in sessions"
              :key="session.code"
              class="grid min-w-0 gap-1.5 rounded-field border border-night-line px-3 py-2.5"
              :data-session-code="session.code"
              data-testid="activity-timeline-session"
            >
              <p class="m-0 font-mono text-xs font-semibold wrap-anywhere text-on-night">
                {{ session.code }}
              </p>
              <dl class="m-0 flex min-w-0 flex-wrap gap-x-5 gap-y-1">
                <div
                  v-for="entry in session.facts"
                  :key="entry.key"
                  class="flex min-w-0 items-baseline gap-1.5"
                  :data-fact="entry.key"
                >
                  <dt class="text-on-night-3">{{ entry.label }}</dt>
                  <dd class="m-0 text-on-night">
                    <time v-if="entry.datetime" :datetime="entry.datetime">{{ entry.text }}</time>
                    <template v-else>{{ entry.text }}</template>
                  </dd>
                </div>
              </dl>
            </li>
          </ul>
        </div>
        <div v-if="limits.length > 0" class="grid min-w-0 gap-2">
          <h3 class="m-0 text-sm font-semibold text-on-night">{{ copy.limitsTitle }}</h3>
          <ul
            class="m-0 grid list-disc gap-1 pl-5 leading-normal"
            data-testid="activity-timeline-limits"
          >
            <li v-for="limit in limits" :key="limit.code" :data-limit="limit.code">
              <template v-if="limit.text !== null">{{ limit.text }}</template>
              <code v-else class="font-mono text-xs break-all">{{ limit.code }}</code>
            </li>
          </ul>
        </div>
      </template>
    </div>
  </details>
</template>
