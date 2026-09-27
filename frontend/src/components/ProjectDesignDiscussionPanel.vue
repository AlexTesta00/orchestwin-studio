<script setup lang="ts">
import { computed, onMounted, ref, useId, watch } from "vue";

import InsightApplyMenu from "./InsightApplyMenu.vue";
import { apiClient } from "@/api/client";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedDesignLoopRequest, useDesignLoopStore } from "@/stores/designLoop";
import type {
  DesignDiscussionPayload,
  DiscussionDecisionAction,
  DiscussionProposalPayload,
  DiscussionRoundPayload,
  DiscussionStance,
  InsightApplicationPayload,
  InsightSource,
} from "@/types/designLoop";

type Locale = "en" | "it";

const NOTE_LIMIT = 500;
const RELOAD_CODES = new Set([
  "DESIGN_DISCUSSION_OPEN",
  "DESIGN_DISCUSSION_CHANGED",
  "DESIGN_DISCUSSION_FULL",
  "DESIGN_DISCUSSION_CLOSED",
]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    designVersionId: string;
    designContentHash: string;
    twinNames?: Record<string, string>;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: DesignLoopApi | undefined;
  }>(),
  { twinNames: () => ({}), locale: "en", authorize: undefined, api: undefined },
);

const emit = defineEmits<{ applied: [application: InsightApplicationPayload] }>();

const messages = {
  en: {
    eyebrow: "Twin discussion",
    title: "Let the twins discuss the chosen design",
    intro:
      "The user twins talk to each other about the design, answer each other and propose changes. A moderator sums up where they agree, where they disagree and what they suggest. It is a simulation by the language model: treat it as design hypotheses, not as the voice of real users.",
    startNote: "What should the twins focus on? (optional)",
    start: "Start the discussion",
    restart: "Start a new discussion",
    running: "The twins are discussing the design. It can take a few minutes: keep this page open.",
    round: "Round {n}",
    roundOf: "Round {n} of {max}",
    statements: "{n} contributions",
    yourNote: "Your note",
    repliesTo: "answers {names}",
    proposes: "Proposes",
    confidence: "confidence {value}",
    stance: {
      SUPPORT: "Supports",
      CONCERN: "Has doubts",
      OBJECTION: "Objects",
    },
    synthesis: "Moderator's summary",
    agreements: "Where they agree",
    conflicts: "Where they disagree",
    proposals: "What they propose",
    supportedBy: "Supported by {names}",
    suggestedTarget: {
      BRIEF: "The moderator suggests bringing it into the brief.",
      REQUIREMENTS: "The moderator suggests bringing it into the requirements.",
      DESIGN: "The moderator suggests bringing it into the design.",
    },
    questions: "Questions for you",
    nothing: "Nothing to report.",
    technical: "Technical details",
    groundedOn: "grounded on {fields}",
    roundNote: "A note for the twins before the next round (optional)",
    nextRound: "Ask for another round",
    approve: "Approve the summary",
    close: "Close the discussion",
    full: "The twins have used all the rounds: approve the summary or close the discussion.",
    outdated:
      "The design has changed since this discussion started (version {n}). You can still approve the summary or close the discussion; to discuss the current design, start a new discussion afterwards.",
    open: "Discussion open",
    approved: "You approved the moderator's summary on {date}.",
    closed: "You closed the discussion on {date}.",
    details: "Details",
    errors: {
      DESIGN_DISCUSSION_NOT_CONFIGURED:
        "The language model that plays the twins is not connected, so the discussion cannot run.",
      DESIGN_DISCUSSION_OPEN:
        "A discussion is already open: continue it or close it before starting a new one.",
      DESIGN_CONTEXT_CHANGED:
        "The design has changed in the meantime. Reload the page and discuss the current design.",
      DESIGN_PROTOTYPE_REQUIRED:
        "The twins need the visual preview of the chosen design: create it before starting the discussion.",
      DESIGN_DISCUSSION_CHANGED:
        "The discussion was updated in the meantime and has been reloaded. Read the latest round and try again.",
      DESIGN_DISCUSSION_FULL:
        "The discussion has reached the maximum number of rounds: approve the summary or close it.",
      DESIGN_DISCUSSION_CLOSED: "The discussion is already closed. You can start a new one.",
    },
    error: "The discussion could not continue. Try again.",
  },
  it: {
    eyebrow: "Discussione tra i twin",
    title: "Fai discutere i twin sul design scelto",
    intro:
      "Gli user twin discutono tra loro del design, si rispondono e propongono modifiche. Un moderatore riassume dove sono d'accordo, dove no e cosa suggeriscono. È una simulazione del modello linguistico: trattala come ipotesi di design, non come la voce di utenti reali.",
    startNote: "Su cosa vuoi che si concentrino i twin? (facoltativo)",
    start: "Avvia la discussione",
    restart: "Avvia una nuova discussione",
    running:
      "I twin stanno discutendo il design. Può richiedere qualche minuto: lascia aperta questa pagina.",
    round: "Giro {n}",
    roundOf: "Giro {n} di {max}",
    statements: "{n} interventi",
    yourNote: "La tua nota",
    repliesTo: "risponde a {names}",
    proposes: "Propone",
    confidence: "confidenza {value}",
    stance: {
      SUPPORT: "Favorevole",
      CONCERN: "Ha dei dubbi",
      OBJECTION: "Contrario",
    },
    synthesis: "Sintesi del moderatore",
    agreements: "Dove sono d'accordo",
    conflicts: "Dove non sono d'accordo",
    proposals: "Cosa propongono",
    supportedBy: "Sostenuta da {names}",
    suggestedTarget: {
      BRIEF: "Il moderatore suggerisce di portarla nel brief.",
      REQUIREMENTS: "Il moderatore suggerisce di portarla nei requisiti.",
      DESIGN: "Il moderatore suggerisce di portarla nel design.",
    },
    questions: "Domande per te",
    nothing: "Niente da segnalare.",
    technical: "Dettagli tecnici",
    groundedOn: "basato su {fields}",
    roundNote: "Una nota per i twin prima del prossimo giro (facoltativa)",
    nextRound: "Chiedi un altro giro",
    approve: "Approva la sintesi",
    close: "Chiudi la discussione",
    full: "I twin hanno usato tutti i giri: approva la sintesi o chiudi la discussione.",
    outdated:
      "Il design è cambiato da quando è iniziata questa discussione (versione {n}). Puoi ancora approvare la sintesi o chiudere la discussione; per discutere il design attuale, avvia poi una nuova discussione.",
    open: "Discussione aperta",
    approved: "Hai approvato la sintesi del moderatore il {date}.",
    closed: "Hai chiuso la discussione il {date}.",
    details: "Dettagli",
    errors: {
      DESIGN_DISCUSSION_NOT_CONFIGURED:
        "Il modello linguistico che interpreta i twin non è collegato, quindi la discussione non può partire.",
      DESIGN_DISCUSSION_OPEN:
        "C'è già una discussione aperta: continuala o chiudila prima di avviarne una nuova.",
      DESIGN_CONTEXT_CHANGED:
        "Il design è cambiato nel frattempo. Ricarica la pagina e discuti il design attuale.",
      DESIGN_PROTOTYPE_REQUIRED:
        "I twin hanno bisogno dell'anteprima visiva del design scelto: creala prima di avviare la discussione.",
      DESIGN_DISCUSSION_CHANGED:
        "La discussione è stata aggiornata nel frattempo ed è stata ricaricata. Leggi l'ultimo giro e riprova.",
      DESIGN_DISCUSSION_FULL:
        "La discussione ha raggiunto il numero massimo di giri: approva la sintesi o chiudila.",
      DESIGN_DISCUSSION_CLOSED: "La discussione è già chiusa. Puoi avviarne una nuova.",
    },
    error: "La discussione non è potuta proseguire. Riprova.",
  },
} as const;

type KnownError = keyof (typeof messages)["en"]["errors"];

const auth = useAuthStore();
const store = useDesignLoopStore();
const uid = useId();
const titleId = `discussion-title-${uid}`;
const startNoteId = `discussion-start-note-${uid}`;
const roundNoteId = `discussion-round-note-${uid}`;
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? designLoopApi);
const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
const startNote = ref("");
const roundNote = ref("");
const failure = ref<string | null>(null);

const discussion = computed<DesignDiscussionPayload | null>(() =>
  store.projectId === props.projectId ? (store.discussions[0] ?? null) : null,
);
const rounds = computed<DiscussionRoundPayload[]>(() =>
  [...(discussion.value?.rounds ?? [])].sort((left, right) => left.ordinal - right.ordinal),
);
const lastOrdinal = computed(() => rounds.value.at(-1)?.ordinal ?? 0);
const isOpen = computed(() => discussion.value?.status === "OPEN");
const outdated = computed(
  () =>
    discussion.value !== null &&
    (discussion.value.design_version_id !== props.designVersionId ||
      discussion.value.design_content_hash !== props.designContentHash),
);
const roundsFull = computed(
  () => discussion.value !== null && discussion.value.rounds.length >= discussion.value.max_rounds,
);
const canContinue = computed(() => isOpen.value && !outdated.value && !roundsFull.value);
const running = computed(
  () => store.discussionBusy === "start" || store.discussionBusy === "round",
);
const names = computed(() => {
  const byId: Record<string, string> = { ...props.twinNames };
  for (const round of rounds.value) {
    for (const statement of round.statements) {
      byId[statement.twin_id] = statement.twin_name;
    }
  }
  return byId;
});
const failureIsNotice = computed(() => failure.value !== null && isKnownError(failure.value));
const failureMessage = computed(() =>
  failure.value !== null && isKnownError(failure.value)
    ? copy.value.errors[failure.value]
    : copy.value.error,
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function twinName(id: string): string {
  return names.value[id] ?? id.slice(0, 8);
}

function listOf(ids: readonly string[]): string {
  return new Intl.ListFormat(props.locale, { style: "long", type: "conjunction" }).format(
    ids.map(twinName),
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(props.locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(value),
  );
}

function confidence(value: number): string {
  return new Intl.NumberFormat(props.locale, { style: "percent", maximumFractionDigits: 0 }).format(
    value,
  );
}

function stanceClass(stance: DiscussionStance): string {
  if (stance === "SUPPORT") return "border-ok-line bg-ok-bg text-ok-dark";
  if (stance === "CONCERN") return "border-hypothesis-line bg-hypothesis-bg text-hypothesis-text";
  return "border-fail-line bg-fail-bg text-fail-dark";
}

function normalized(value: string): string | null {
  const text = value.trim().replace(/\s+/g, " ");
  return text.length === 0 ? null : text;
}

function proposalSource(
  value: DesignDiscussionPayload,
  round: DiscussionRoundPayload,
  proposal: DiscussionProposalPayload,
): InsightSource {
  return {
    kind: "TWIN_DISCUSSION",
    id: `discussion:${value.id}:${round.ordinal}:${proposal.code}`,
    twinId: null,
    text: proposal.text,
  };
}

function isKnownError(code: string): code is KnownError {
  return code in messages.en.errors;
}

async function reload(): Promise<void> {
  try {
    await store.loadDiscussions(props.projectId, authorize, api.value);
  } catch {
    return;
  }
}

async function recover(): Promise<void> {
  const code = store.discussionError ?? "DESIGN_DISCUSSION_FAILED";
  failure.value = code;
  if (RELOAD_CODES.has(code)) {
    await reload();
  }
}

async function start(): Promise<void> {
  if (store.isBusy) return;
  failure.value = null;
  try {
    await store.startDiscussion(
      props.projectId,
      {
        design_version_id: props.designVersionId,
        design_content_hash: props.designContentHash,
        locale: props.locale === "it" ? "it-IT" : "en-US",
        owner_note: normalized(startNote.value),
      },
      authorize,
      api.value,
    );
    startNote.value = "";
  } catch {
    await recover();
  }
}

async function nextRound(): Promise<void> {
  const value = discussion.value;
  if (value === null || store.isBusy || !canContinue.value) return;
  failure.value = null;
  try {
    await store.nextDiscussionRound(
      props.projectId,
      value.id,
      { expected_round_count: value.rounds.length, owner_note: normalized(roundNote.value) },
      authorize,
      api.value,
    );
    roundNote.value = "";
  } catch {
    await recover();
  }
}

async function decide(action: DiscussionDecisionAction): Promise<void> {
  const value = discussion.value;
  if (value === null || store.isBusy || value.status !== "OPEN") return;
  failure.value = null;
  try {
    await store.decideDiscussion(props.projectId, value.id, action, authorize, api.value);
  } catch {
    await recover();
  }
}

async function load(): Promise<void> {
  failure.value = null;
  try {
    await store.loadDiscussions(props.projectId, authorize, api.value);
  } catch {
    failure.value = store.discussionError ?? "DESIGN_DISCUSSION_FAILED";
  }
}

onMounted(load);
watch(() => props.projectId, load);
</script>

<template>
  <section
    class="grid gap-4 rounded-card border border-line bg-white p-4 shadow-sm sm:p-5"
    :aria-labelledby="titleId"
    data-testid="design-discussion-panel"
  >
    <header class="grid gap-2">
      <p class="m-0 text-xs font-semibold tracking-widest text-action uppercase">
        {{ copy.eyebrow }}
      </p>
      <h3 :id="titleId" class="m-0 text-lg font-bold text-ink">
        {{ copy.title }}
      </h3>
      <p class="m-0 max-w-3xl text-sm leading-6 text-ink-2">{{ copy.intro }}</p>
    </header>

    <p v-if="running" class="m-0 text-sm text-ink-2" aria-live="polite">{{ copy.running }}</p>

    <p
      v-if="failure !== null && failureIsNotice"
      class="m-0 rounded-panel border border-line bg-surface-3 p-3 text-sm text-ink-2"
      role="status"
      data-testid="discussion-notice"
    >
      {{ failureMessage }}
    </p>
    <div
      v-else-if="failure !== null"
      class="grid gap-1 rounded-panel border border-fail-line bg-fail-bg p-3 text-sm text-fail-dark"
      role="alert"
      data-testid="discussion-error"
    >
      <p class="m-0 font-semibold">{{ failureMessage }}</p>
      <details class="text-xs">
        <summary class="cursor-pointer">{{ copy.details }}</summary>
        <code class="break-all">{{ failure }}</code>
      </details>
    </div>

    <template v-if="discussion !== null">
      <p
        class="m-0 text-sm font-semibold"
        :class="discussion.status === 'OPEN' ? 'text-action' : 'text-ok-dark'"
        :data-status="discussion.status"
        data-testid="discussion-status"
      >
        <template v-if="discussion.status === 'OPEN'">
          {{ copy.open }} ·
          {{ fill(copy.roundOf, { n: discussion.rounds.length, max: discussion.max_rounds }) }}
        </template>
        <template v-else-if="discussion.status === 'APPROVED'">
          {{
            fill(copy.approved, {
              date: formatDate(discussion.decided_at ?? discussion.created_at),
            })
          }}
        </template>
        <template v-else>
          {{
            fill(copy.closed, { date: formatDate(discussion.decided_at ?? discussion.created_at) })
          }}
        </template>
      </p>
      <p
        v-if="isOpen && outdated"
        class="m-0 rounded-panel border border-line bg-surface-3 p-3 text-sm text-ink-2"
        data-testid="discussion-outdated"
      >
        {{ fill(copy.outdated, { n: discussion.design_version_number }) }}
      </p>

      <details
        v-for="round in rounds"
        :key="round.ordinal"
        class="rounded-panel border border-line p-4"
        :open="isOpen && round.ordinal === lastOrdinal"
        data-testid="discussion-round"
      >
        <summary class="cursor-pointer font-semibold text-ink">
          {{ fill(copy.round, { n: round.ordinal }) }}
          <span class="font-normal text-ink-3">
            · {{ fill(copy.statements, { n: round.statements.length }) }}
          </span>
        </summary>
        <div class="mt-3 grid gap-4">
          <p v-if="round.owner_note" class="m-0 text-sm text-ink-2">
            <strong>{{ copy.yourNote }}:</strong> {{ round.owner_note }}
          </p>
          <ul class="m-0 grid list-none gap-3 p-0">
            <li
              v-for="statement in round.statements"
              :key="`${round.ordinal}:${statement.twin_id}`"
              class="grid gap-2 rounded-panel border border-line-soft bg-surface-2 p-3"
              data-testid="discussion-statement"
            >
              <div class="flex flex-wrap items-center gap-2 text-xs">
                <strong class="text-sm text-ink">{{ statement.twin_name }}</strong>
                <span
                  class="rounded-pill border px-2 py-0.5 font-semibold"
                  :class="stanceClass(statement.stance)"
                  :data-stance="statement.stance"
                  data-testid="discussion-stance"
                >
                  {{ copy.stance[statement.stance] }}
                </span>
                <span v-if="statement.replies_to.length > 0" class="text-ink-3">
                  {{ fill(copy.repliesTo, { names: listOf(statement.replies_to) }) }}
                </span>
                <span class="text-ink-3">
                  {{ fill(copy.confidence, { value: confidence(statement.confidence) }) }}
                </span>
              </div>
              <p class="m-0 text-sm leading-6 whitespace-pre-line text-ink">
                {{ statement.statement }}
              </p>
              <div v-if="statement.proposals.length > 0" class="grid gap-1 text-sm text-ink-2">
                <p class="m-0 font-semibold">{{ copy.proposes }}</p>
                <ul class="m-0 list-disc pl-5">
                  <li v-for="proposal in statement.proposals" :key="proposal">{{ proposal }}</li>
                </ul>
              </div>
            </li>
          </ul>

          <section
            class="grid gap-3 rounded-panel border border-action-soft-line bg-action-soft p-4"
            data-testid="discussion-synthesis"
          >
            <h4 class="m-0 text-sm font-semibold text-action">{{ copy.synthesis }}</h4>
            <div class="grid gap-1 text-sm text-ink">
              <h5 class="m-0 font-semibold">{{ copy.agreements }}</h5>
              <ul v-if="round.synthesis.agreements.length > 0" class="m-0 list-disc pl-5">
                <li v-for="agreement in round.synthesis.agreements" :key="agreement">
                  {{ agreement }}
                </li>
              </ul>
              <p v-else class="m-0 text-ink-3">{{ copy.nothing }}</p>
            </div>
            <div class="grid gap-1 text-sm text-ink">
              <h5 class="m-0 font-semibold">{{ copy.conflicts }}</h5>
              <ul v-if="round.synthesis.conflicts.length > 0" class="m-0 grid list-none gap-2 p-0">
                <li
                  v-for="conflict in round.synthesis.conflicts"
                  :key="conflict.topic"
                  class="grid gap-1"
                  data-testid="discussion-conflict"
                >
                  <p class="m-0 font-semibold">{{ conflict.topic }}</p>
                  <ul class="m-0 list-disc pl-5 text-ink-2">
                    <li
                      v-for="position in conflict.positions"
                      :key="`${conflict.topic}:${position.twin_id}`"
                    >
                      <strong>{{ twinName(position.twin_id) }}:</strong> {{ position.position }}
                    </li>
                  </ul>
                </li>
              </ul>
              <p v-else class="m-0 text-ink-3">{{ copy.nothing }}</p>
            </div>
            <div class="grid gap-2 text-sm text-ink">
              <h5 class="m-0 font-semibold">{{ copy.proposals }}</h5>
              <ul v-if="round.synthesis.proposals.length > 0" class="m-0 grid list-none gap-3 p-0">
                <li
                  v-for="proposal in round.synthesis.proposals"
                  :key="proposal.code"
                  class="grid gap-1 rounded-panel border border-line bg-white p-3"
                  :data-target="proposal.target"
                  data-testid="discussion-proposal"
                >
                  <p class="m-0 font-semibold">{{ proposal.text }}</p>
                  <p v-if="proposal.supported_by.length > 0" class="m-0 text-xs text-ink-3">
                    {{ fill(copy.supportedBy, { names: listOf(proposal.supported_by) }) }}
                  </p>
                  <p class="m-0 text-xs text-ink-2" data-testid="discussion-proposal-target">
                    {{ copy.suggestedTarget[proposal.target] }}
                  </p>
                  <InsightApplyMenu
                    :project-id="projectId"
                    :source="proposalSource(discussion, round, proposal)"
                    :locale="locale"
                    :authorize="authorize"
                    :api="api"
                    @applied="emit('applied', $event)"
                  />
                </li>
              </ul>
              <p v-else class="m-0 text-ink-3">{{ copy.nothing }}</p>
            </div>
            <div v-if="round.synthesis.questions_for_owner.length > 0" class="grid gap-1 text-sm">
              <h5 class="m-0 font-semibold text-ink">{{ copy.questions }}</h5>
              <ul class="m-0 list-disc pl-5 text-ink-2">
                <li v-for="question in round.synthesis.questions_for_owner" :key="question">
                  {{ question }}
                </li>
              </ul>
            </div>
          </section>

          <details class="text-xs text-ink-3">
            <summary class="cursor-pointer">{{ copy.technical }}</summary>
            <ul class="m-0 mt-2 grid list-none gap-1 p-0 break-all">
              <li>{{ round.content_hash }}</li>
              <li>{{ round.synthesis.model_generation_id }}</li>
              <li
                v-for="statement in round.statements"
                :key="`${round.ordinal}:${statement.twin_id}:technical`"
              >
                {{ statement.twin_name }} · {{ statement.model_generation_id }}
                <template v-if="statement.grounded_on.length > 0">
                  · {{ fill(copy.groundedOn, { fields: statement.grounded_on.join(", ") }) }}
                </template>
              </li>
            </ul>
          </details>
        </div>
      </details>

      <section v-if="isOpen" class="grid gap-3" data-testid="discussion-actions">
        <label
          v-if="canContinue"
          class="grid gap-1 text-sm font-semibold text-ink-2"
          :for="roundNoteId"
        >
          {{ copy.roundNote }}
          <textarea
            :id="roundNoteId"
            v-model="roundNote"
            rows="2"
            :maxlength="NOTE_LIMIT"
            :disabled="store.isBusy"
            class="rounded-control border border-field bg-white px-3 py-2 text-sm font-normal text-ink"
            data-testid="discussion-round-note"
          ></textarea>
        </label>
        <p v-if="roundsFull" class="m-0 text-sm text-ink-2" data-testid="discussion-full">
          {{ copy.full }}
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="rounded-panel bg-action px-5 py-3 font-semibold text-white hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3"
            :disabled="store.isBusy"
            data-testid="discussion-approve"
            @click="decide('APPROVE')"
          >
            {{ copy.approve }}
          </button>
          <button
            v-if="canContinue"
            type="button"
            class="rounded-panel border border-line bg-white px-4 py-3 text-sm font-semibold text-ink-2 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="store.isBusy"
            data-testid="discussion-next-round"
            @click="nextRound"
          >
            {{ copy.nextRound }}
          </button>
          <button
            type="button"
            class="rounded-panel px-4 py-3 text-sm font-semibold text-ink-2 underline hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="store.isBusy"
            data-testid="discussion-close"
            @click="decide('CLOSE')"
          >
            {{ copy.close }}
          </button>
        </div>
      </section>
    </template>

    <section v-if="!isOpen" class="grid gap-3" data-testid="discussion-start">
      <label class="grid gap-1 text-sm font-semibold text-ink-2" :for="startNoteId">
        {{ copy.startNote }}
        <textarea
          :id="startNoteId"
          v-model="startNote"
          rows="2"
          :maxlength="NOTE_LIMIT"
          :disabled="store.isBusy"
          class="rounded-control border border-field bg-white px-3 py-2 text-sm font-normal text-ink"
          data-testid="discussion-start-note"
        ></textarea>
      </label>
      <button
        type="button"
        class="justify-self-start rounded-panel bg-action px-5 py-3 font-semibold text-white hover:bg-action-hover disabled:cursor-not-allowed disabled:bg-surface-3"
        :disabled="store.isBusy"
        data-testid="discussion-start-button"
        @click="start"
      >
        {{ discussion === null ? copy.start : copy.restart }}
      </button>
    </section>
  </section>
</template>
