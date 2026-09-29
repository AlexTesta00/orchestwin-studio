<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { briefDialogueApi, type BriefDialogueApi } from "@/api/briefDialogue";
import { apiClient } from "@/api/client";
import type { BriefField, ProjectBriefVersionResponse } from "@/api/contracts";
import UiBrandMark from "@/components/UiBrandMark.vue";
import UiButton from "@/components/UiButton.vue";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedBriefDialogueRequest, useBriefDialogueStore } from "@/stores/briefDialogue";
import type { BriefDialogueTurnPayload } from "@/types/briefDialogue";

const props = withDefaults(
  defineProps<{
    projectId: string;
    currentBrief: ProjectBriefVersionResponse | null;
    api?: BriefDialogueApi | undefined;
    authorize?: AuthorizedBriefDialogueRequest | undefined;
  }>(),
  { api: () => briefDialogueApi, authorize: undefined },
);

const emit = defineEmits<{
  active: [active: boolean];
  synthesized: [version: ProjectBriefVersionResponse];
  "open-form": [];
  unavailable: [];
}>();

const { t } = useI18n({ useScope: "global" });
const { t: tl } = useI18n({
  useScope: "local",
  messages: {
    en: {
      chat: {
        analyst: "Requirements analyst",
        analystSays: "The analyst:",
        youSay: "You:",
        greeting:
          "Hi! I am the requirements analyst. Tell me your idea in two lines: what do you want to build?",
        typing: "The analyst is writing",
        shapeTitle: "The brief takes shape",
        shapeIntro: "Each answer fills a point. What is missing, I will propose at the end.",
        waiting: "Waiting for your answer",
        asking: "I am asking you now",
        openPoint: "You do not know yet: it stays an open point",
        startHint: "Then I will ask one question at a time and compose the brief.",
        answerHint: "Answer in your own words. Press Enter to send.",
        listHint: "One item per line. Press Send when you are done.",
        unknownHint: "Not sure yet?",
        seeBrief: "See the brief and the proposals",
        fields: {
          name: "Name",
          description: "The idea",
          problem: "The problem",
          goals: "Goals",
          target_users: "For whom",
          domain: "Context",
          technical_constraints: "Technical constraints",
          temporal_constraints: "Timing",
          budget: "Budget",
          functional_requirements: "What it must do",
          non_functional_requirements: "Expected qualities",
          risks: "Risks",
          stakeholders: "People involved",
          available_artifacts: "Available materials",
          definition_of_done: "When it is done",
        },
      },
    },
    it: {
      chat: {
        analyst: "Analista delle esigenze",
        analystSays: "L'analista:",
        youSay: "Tu:",
        greeting:
          "Ciao! Sono l'analista delle esigenze. Raccontami l'idea in due righe: che cosa vuoi realizzare?",
        typing: "L'analista sta scrivendo",
        shapeTitle: "Il brief prende forma",
        shapeIntro: "Ogni risposta riempie un punto. Quello che manca te lo proporrò alla fine.",
        waiting: "In attesa della tua risposta",
        asking: "Te lo sto chiedendo ora",
        openPoint: "Non lo sai ancora: resta un punto aperto",
        startHint: "Poi ti farò una domanda alla volta e comporrò il brief.",
        answerHint: "Rispondi con parole tue. Premi Invio per mandarla.",
        listHint: "Un elemento per riga. Premi Invia quando hai finito.",
        unknownHint: "Non lo sai ancora?",
        seeBrief: "Vedi il brief e le proposte",
        fields: {
          name: "Nome",
          description: "L'idea",
          problem: "Il problema",
          goals: "Obiettivi",
          target_users: "Per chi",
          domain: "Contesto",
          technical_constraints: "Vincoli tecnici",
          temporal_constraints: "Tempi",
          budget: "Budget",
          functional_requirements: "Cosa deve fare",
          non_functional_requirements: "Qualità attese",
          risks: "Rischi",
          stakeholders: "Persone coinvolte",
          available_artifacts: "Materiali disponibili",
          definition_of_done: "Quando sarà finito",
        },
      },
    },
  },
});
const auth = useAuthStore();
const store = useBriefDialogueStore();

const statement = ref("");
const statementMissing = ref(false);
const answerText = ref("");
const answerMissing = ref(false);
const synthesizing = ref(false);
const synthesizedVersion = ref<number | null>(null);
const log = ref<HTMLElement | null>(null);

const displayOrder: readonly BriefField[] = [
  "name",
  "description",
  "problem",
  "target_users",
  "goals",
  "functional_requirements",
  "domain",
  "temporal_constraints",
  "technical_constraints",
  "budget",
  "non_functional_requirements",
  "risks",
  "stakeholders",
  "available_artifacts",
  "definition_of_done",
];
const defaultEssentials: readonly BriefField[] = [
  "description",
  "problem",
  "goals",
  "target_users",
  "functional_requirements",
];

const authorize: AuthorizedBriefDialogueRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const dialogue = computed(() => store.dialogue);
const active = computed(() => store.isActive);
const pending = computed(() => store.pendingTurn);
const answered = computed(() => store.answeredTurns);
const busy = computed(() => store.busy);
const composing = computed(
  () => pending.value === null && (dialogue.value?.status === "READY" || synthesizing.value),
);
const typing = computed(() => busy.value && !composing.value);
const progressText = computed(() => {
  const progress = store.progress;
  if (progress === null) return "";
  const left = progress.open_essential_fields.length;
  const essentials =
    left > 0
      ? t("briefDialogue.essentialsLeft", { count: left }, left)
      : t("briefDialogue.essentialsDone");
  return `${t("briefDialogue.progress", {
    asked: progress.questions_asked,
    limit: progress.question_limit,
  })} · ${essentials}`;
});
const errorText = computed(() => {
  const code = store.error;
  if (code === null || store.modelUnavailable) return null;
  const key = `briefDialogue.errors.${code}`;
  const translated = t(key);
  return translated === key ? t("briefDialogue.errors.default", { code }) : translated;
});

type ShapeState = "answered" | "open" | "asking" | "waiting";

const shapeCards = computed(() => {
  const current = active.value ? dialogue.value : null;
  const turns = current?.turns ?? [];
  const essentials = current?.essential_fields ?? defaultEssentials;
  const asked = turns
    .map((turn) => turn.field)
    .filter((field): field is BriefField => field !== null);
  const fields = new Set<BriefField>([...essentials, ...asked]);
  return displayOrder
    .filter((field) => fields.has(field))
    .map((field) => {
      const turn = [...turns]
        .reverse()
        .find((candidate) => candidate.field === field && candidate.answer !== null);
      let state: ShapeState = "waiting";
      let value = tl("chat.waiting");
      if (turn !== undefined) {
        state = turn.answer?.kind === "UNKNOWN" ? "open" : "answered";
        value = state === "open" ? tl("chat.openPoint") : answerLabel(turn);
      } else if (field === "description" && current !== null && current.statement.trim() !== "") {
        state = "answered";
        value = current.statement;
      }
      if (pending.value?.field === field) {
        state = "asking";
        value = tl("chat.asking");
      }
      return { field, state, value };
    });
});

function shapeLabel(field: BriefField): string {
  return tl(`chat.fields.${field}`);
}

function fieldLabel(turn: BriefDialogueTurnPayload): string {
  return turn.field === null ? t("briefDialogue.followUp") : shapeLabel(turn.field);
}

function answerLabel(turn: BriefDialogueTurnPayload): string {
  const answer = turn.answer;
  if (answer === null || answer.kind === "UNKNOWN") return t("briefDialogue.unknownAnswer");
  if (answer.kind === "ITEM_LIST") return (answer.items ?? []).join(" · ");
  return answer.text ?? "";
}

function itemsOf(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

async function scrollToLatest(): Promise<void> {
  await nextTick();
  const element = log.value;
  if (element !== null) element.scrollTop = element.scrollHeight;
}

async function load(): Promise<void> {
  try {
    await store.load(props.projectId, authorize, props.api);
  } catch {
    if (store.modelUnavailable) emit("unavailable");
    return;
  }
  statement.value = props.currentBrief?.brief.description ?? "";
  emit("active", store.isActive);
}

async function start(): Promise<void> {
  const text = statement.value.trim();
  if (text.length === 0) {
    statementMissing.value = true;
    return;
  }
  statementMissing.value = false;
  synthesizedVersion.value = null;
  try {
    await store.start(props.projectId, text, authorize, props.api);
  } catch {
    if (store.modelUnavailable) emit("unavailable");
    return;
  }
  emit("active", true);
}

async function reloadAfterConflict(): Promise<void> {
  if (store.error === "BRIEF_DIALOGUE_CHANGED") {
    try {
      await store.load(props.projectId, authorize, props.api);
    } catch {
      return;
    }
  }
}

async function send(): Promise<void> {
  const turn = pending.value;
  if (turn === null) return;
  const listAnswer = turn.answer_type === "ITEM_LIST";
  const items = itemsOf(answerText.value);
  const text = answerText.value.trim();
  if ((listAnswer && items.length === 0) || (!listAnswer && text.length === 0)) {
    answerMissing.value = true;
    return;
  }
  answerMissing.value = false;
  try {
    await store.answer(
      props.projectId,
      listAnswer ? { kind: "ITEM_LIST", items } : { kind: "TEXT", text },
      authorize,
      props.api,
    );
  } catch {
    await reloadAfterConflict();
    return;
  }
  answerText.value = "";
}

function sendOnEnter(event: KeyboardEvent): void {
  if (event.isComposing || pending.value?.answer_type !== "TEXT" || busy.value) return;
  event.preventDefault();
  void send();
}

async function sayUnknown(): Promise<void> {
  answerMissing.value = false;
  try {
    await store.answer(props.projectId, { kind: "UNKNOWN" }, authorize, props.api);
  } catch {
    await reloadAfterConflict();
    return;
  }
  answerText.value = "";
}

async function continueQuestion(): Promise<void> {
  try {
    await store.nextQuestion(props.projectId, authorize, props.api);
  } catch {
    await reloadAfterConflict();
  }
}

async function synthesize(): Promise<void> {
  if (synthesizing.value) return;
  synthesizing.value = true;
  try {
    const response = await store.synthesize(props.projectId, authorize, props.api);
    if (response?.brief_version) {
      synthesizedVersion.value = response.brief_version.version_number;
      emit("synthesized", response.brief_version);
      emit("active", false);
    }
  } catch {
    await reloadAfterConflict();
  } finally {
    synthesizing.value = false;
  }
}

async function closeDialogue(): Promise<void> {
  try {
    await store.close(props.projectId, authorize, props.api);
  } catch {
    await reloadAfterConflict();
    return;
  }
  emit("active", false);
}

watch(
  () => store.lastOutcome,
  (outcome) => {
    if (outcome === "BRIEF_DIALOGUE_READY") void synthesize();
  },
);

watch(
  () => [answered.value.length, pending.value?.id, typing.value, composing.value],
  () => {
    void scrollToLatest();
  },
);

let logObserver: ResizeObserver | null = null;

onMounted(() => {
  if (typeof ResizeObserver !== "undefined" && log.value !== null) {
    logObserver = new ResizeObserver(() => {
      void scrollToLatest();
    });
    logObserver.observe(log.value);
  }
  void load();
});

onBeforeUnmount(() => {
  logObserver?.disconnect();
  logObserver = null;
});
</script>

<template>
  <section
    class="flex min-w-0 flex-col gap-4"
    data-testid="brief-dialogue"
    aria-labelledby="brief-dialogue-title"
  >
    <p
      v-if="errorText !== null"
      class="rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm font-semibold text-fail-on-night"
      role="alert"
      data-testid="brief-dialogue-error"
    >
      {{ errorText }}
    </p>

    <div class="flex flex-wrap items-start gap-5">
      <section
        class="flex h-[min(640px,calc(100vh-220px))] min-h-[480px] min-w-0 flex-[1.6_1_460px] flex-col overflow-hidden rounded-sheet bg-night"
        :aria-busy="busy ? 'true' : undefined"
        :data-testid="
          !active
            ? 'brief-dialogue-entry'
            : pending !== null
              ? 'brief-dialogue-question'
              : undefined
        "
      >
        <header class="flex items-center gap-3 border-b border-night-line px-5 py-3.5">
          <span aria-hidden="true" class="inline-flex shrink-0">
            <UiBrandMark :size="36" surface="night" />
          </span>
          <div class="min-w-0 flex-1">
            <h2 id="brief-dialogue-title" class="text-[15px] font-semibold text-on-night">
              {{ tl("chat.analyst") }}
            </h2>
            <p
              v-if="active && dialogue !== null"
              class="mt-0.5 font-mono text-[11px] leading-snug tracking-[0.04em] text-on-night-3"
              data-testid="brief-dialogue-progress"
            >
              {{ progressText }}
            </p>
          </div>
        </header>

        <div
          ref="log"
          role="log"
          aria-live="polite"
          class="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-6 sm:px-5"
        >
          <p
            class="max-w-[82%] self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3 text-[15px] leading-[1.55] text-on-night"
          >
            <span class="sr-only">{{ tl("chat.analystSays") }} </span>{{ tl("chat.greeting") }}
          </p>

          <template v-if="!active">
            <template v-if="store.modelUnavailable">
              <div
                class="grid max-w-[82%] gap-3 self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3"
              >
                <p
                  class="text-[15px] leading-[1.55] text-on-night"
                  data-testid="brief-dialogue-unavailable"
                >
                  <span class="sr-only">{{ tl("chat.analystSays") }} </span
                  >{{ t("briefDialogue.modelUnavailable") }}
                </p>
                <div>
                  <UiButton
                    variant="outline"
                    data-testid="brief-dialogue-open-form"
                    @click="emit('open-form')"
                  >
                    {{ t("briefDialogue.openForm") }}
                  </UiButton>
                </div>
              </div>
            </template>
            <template v-else-if="synthesizedVersion !== null">
              <p
                class="max-w-[82%] self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3 text-[15px] leading-[1.55] text-on-night"
                data-testid="brief-dialogue-synthesized"
              >
                <span class="sr-only">{{ tl("chat.analystSays") }} </span
                >{{ t("briefDialogue.synthesized") }}
              </p>
              <div class="self-start">
                <UiButton
                  variant="pill"
                  data-testid="brief-dialogue-open-form"
                  @click="emit('open-form')"
                >
                  {{ tl("chat.seeBrief") }}
                </UiButton>
              </div>
            </template>
          </template>

          <template v-else-if="dialogue !== null">
            <p
              class="max-w-[82%] self-end rounded-[18px_18px_6px_18px] bg-on-night px-4 py-3 text-[15px] leading-[1.55] break-words whitespace-pre-line text-ink"
            >
              <span class="sr-only">{{ tl("chat.youSay") }} </span>{{ dialogue.statement }}
            </p>
            <ol
              v-if="answered.length > 0"
              class="m-0 flex list-none flex-col gap-3 p-0"
              data-testid="brief-dialogue-turns"
            >
              <li
                v-for="turn in answered"
                :key="turn.id"
                class="flex flex-col gap-3"
                data-testid="brief-dialogue-turn"
              >
                <p
                  class="max-w-[82%] self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3 text-[15px] leading-[1.55] text-on-night"
                >
                  <span class="sr-only">{{ tl("chat.analystSays") }} </span>{{ turn.question }}
                </p>
                <p
                  class="max-w-[82%] self-end rounded-[18px_18px_6px_18px] bg-on-night px-4 py-3 text-[15px] leading-[1.55] break-words whitespace-pre-line text-ink"
                >
                  <span class="sr-only">{{ tl("chat.youSay") }} </span>{{ answerLabel(turn) }}
                </p>
              </li>
            </ol>

            <p
              v-if="pending !== null"
              class="max-w-[82%] self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3 text-[15px] leading-[1.55] text-on-night"
              data-testid="brief-dialogue-pending"
            >
              <span
                class="mb-1 block font-mono text-[11px] tracking-label text-violet-on-night-2 uppercase"
              >
                {{ fieldLabel(pending) }}
              </span>
              <span class="sr-only">{{ tl("chat.analystSays") }} </span>{{ pending.question }}
            </p>

            <div
              v-else-if="composing"
              class="grid max-w-[82%] gap-3 self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3"
              data-testid="brief-dialogue-composing"
            >
              <p class="text-[15px] leading-[1.55] text-on-night" aria-live="polite">
                <span class="sr-only">{{ tl("chat.analystSays") }} </span
                >{{
                  synthesizing || busy
                    ? t("briefDialogue.composing")
                    : t("briefDialogue.readyToCompose")
                }}
              </p>
              <div v-if="!synthesizing && !busy">
                <UiButton
                  variant="pill"
                  data-testid="brief-dialogue-retry-compose"
                  @click="synthesize"
                >
                  {{ t("briefDialogue.retryCompose") }}
                </UiButton>
              </div>
            </div>

            <div
              v-else-if="!busy"
              class="grid max-w-[82%] gap-3 self-start rounded-[18px_18px_18px_6px] border border-on-night/10 bg-on-night/7 px-4 py-3"
              data-testid="brief-dialogue-resume"
            >
              <p class="text-[15px] leading-[1.55] text-on-night">
                <span class="sr-only">{{ tl("chat.analystSays") }} </span
                >{{ t("briefDialogue.interrupted") }}
              </p>
              <div>
                <UiButton
                  variant="pill"
                  :disabled="busy"
                  data-testid="brief-dialogue-continue"
                  @click="continueQuestion"
                >
                  {{ t("briefDialogue.continueQuestion") }}
                </UiButton>
              </div>
            </div>
          </template>

          <div
            v-if="typing"
            class="flex gap-[5px] self-start rounded-[18px] bg-on-night/7 px-4 py-3.5"
            role="img"
            :aria-label="tl('chat.typing')"
            data-testid="brief-dialogue-typing"
          >
            <span class="h-[7px] w-[7px] rounded-full bg-petrol-on-night-2 opacity-90" />
            <span class="h-[7px] w-[7px] rounded-full bg-petrol-on-night-2 opacity-60" />
            <span class="h-[7px] w-[7px] rounded-full bg-petrol-on-night-2 opacity-30" />
          </div>
        </div>

        <form
          v-if="!active && !store.modelUnavailable && synthesizedVersion === null"
          class="grid gap-2.5 border-t border-night-line px-4 pt-3 pb-4"
          novalidate
          @submit.prevent="start"
        >
          <label class="sr-only" for="brief-dialogue-statement">
            {{ t("briefDialogue.statementLabel") }}
          </label>
          <div class="flex items-end gap-2">
            <textarea
              id="brief-dialogue-statement"
              v-model="statement"
              data-testid="brief-dialogue-statement"
              rows="3"
              class="min-w-0 flex-1 resize-none rounded-[14px] border border-on-night/18 bg-night-raised px-3.5 py-3 text-[15px] leading-[1.45] text-on-night placeholder:text-on-night-3"
              :placeholder="t('briefDialogue.statementPlaceholder')"
              :disabled="busy"
            ></textarea>
            <UiButton
              type="submit"
              variant="pill"
              class="shrink-0"
              :disabled="busy"
              data-testid="brief-dialogue-start"
            >
              {{
                busy
                  ? t("briefDialogue.waiting")
                  : currentBrief
                    ? t("briefDialogue.restart")
                    : t("briefDialogue.start")
              }}
            </UiButton>
          </div>
          <p v-if="statementMissing" class="text-sm font-semibold text-fail-on-night" role="alert">
            {{ t("briefDialogue.statementRequired") }}
          </p>
          <p class="flex flex-wrap items-center gap-x-2 text-xs text-on-night-3">
            <span>{{ tl("chat.startHint") }}</span>
            <button
              type="button"
              class="inline-flex min-h-11 items-center font-semibold text-petrol-on-night-2 underline-offset-4 hover:underline"
              data-testid="brief-dialogue-open-form"
              @click="emit('open-form')"
            >
              {{ t("briefDialogue.preferForm") }}
            </button>
          </p>
        </form>

        <form
          v-else-if="active && pending !== null"
          class="grid gap-2 border-t border-night-line px-4 pt-3 pb-4"
          novalidate
          data-testid="brief-dialogue-composer"
          @submit.prevent="send"
        >
          <label class="sr-only" for="brief-dialogue-answer">
            {{ t("briefDialogue.answerLabel") }}
          </label>
          <div class="flex items-end gap-2">
            <textarea
              id="brief-dialogue-answer"
              v-model="answerText"
              data-testid="brief-dialogue-answer"
              :rows="pending.answer_type === 'ITEM_LIST' ? 3 : 2"
              class="min-w-0 flex-1 resize-none rounded-[14px] border border-on-night/18 bg-night-raised px-3.5 py-3 text-[15px] leading-[1.45] text-on-night placeholder:text-on-night-3"
              :placeholder="
                pending.answer_type === 'ITEM_LIST'
                  ? t('briefDialogue.answerPlaceholderList')
                  : t('briefDialogue.answerPlaceholderText')
              "
              aria-describedby="brief-dialogue-answer-hint"
              :disabled="busy"
              @keydown.enter.exact="sendOnEnter"
            ></textarea>
            <UiButton
              type="submit"
              variant="pill"
              class="shrink-0"
              :disabled="busy"
              data-testid="brief-dialogue-send"
            >
              {{ t("briefDialogue.send") }}
            </UiButton>
          </div>
          <p v-if="answerMissing" class="text-sm font-semibold text-fail-on-night" role="alert">
            {{ t("briefDialogue.answerRequired") }}
          </p>
          <p
            id="brief-dialogue-answer-hint"
            class="flex flex-wrap items-center gap-x-2 text-xs text-on-night-3"
          >
            <span>
              {{
                pending.answer_type === "ITEM_LIST" ? tl("chat.listHint") : tl("chat.answerHint")
              }}
            </span>
            <span>{{ tl("chat.unknownHint") }}</span>
            <button
              type="button"
              class="inline-flex min-h-11 items-center font-semibold text-violet-on-night-2 underline-offset-4 hover:underline disabled:text-on-night-3 disabled:no-underline"
              :disabled="busy"
              data-testid="brief-dialogue-unknown"
              @click="sayUnknown"
            >
              {{ t("briefDialogue.unknown") }}
            </button>
          </p>
        </form>
      </section>

      <aside
        class="min-w-0 flex-[1_1_280px] rounded-sheet border border-night-line bg-night-raised p-5 sm:p-[22px] lg:sticky lg:top-24"
        aria-labelledby="brief-shape-title"
        data-testid="brief-dialogue-shape"
      >
        <h3
          id="brief-shape-title"
          class="mb-1 font-mono text-[11px] tracking-label text-on-night-3 uppercase"
        >
          {{ tl("chat.shapeTitle") }}
        </h3>
        <p class="mb-4 text-sm leading-normal text-on-night-3">{{ tl("chat.shapeIntro") }}</p>
        <ul class="m-0 flex list-none flex-col gap-2 p-0">
          <li
            v-for="card in shapeCards"
            :key="card.field"
            :class="[
              'rounded-field px-3 py-2.5',
              card.state === 'answered'
                ? 'border border-night-line-strong bg-night-raised'
                : card.state === 'asking'
                  ? 'border-[1.5px] border-dashed border-violet-on-night bg-violet-on-night/12'
                  : 'border-[1.5px] border-dashed border-violet-on-night/70 bg-violet-on-night/6',
            ]"
            :data-shape-field="card.field"
            :data-shape-state="card.state"
          >
            <p
              :class="[
                'text-xs font-semibold',
                card.state === 'answered' ? 'text-petrol-on-night-2' : 'text-violet-on-night-2',
              ]"
            >
              {{ shapeLabel(card.field) }}
            </p>
            <p
              :class="[
                'mt-0.5 line-clamp-4 text-sm leading-[1.45] break-words',
                card.state === 'answered' ? 'text-on-night' : 'text-violet-on-night-2',
              ]"
            >
              {{ card.value }}
            </p>
          </li>
        </ul>
      </aside>
    </div>

    <div
      v-if="active && dialogue !== null"
      class="flex flex-wrap items-center gap-x-5 text-sm font-semibold"
    >
      <button
        v-if="pending !== null"
        type="button"
        class="inline-flex min-h-11 items-center text-petrol-on-night-2 underline-offset-4 hover:underline disabled:text-on-night-3 disabled:no-underline"
        data-testid="brief-dialogue-compose"
        :disabled="busy"
        @click="synthesize"
      >
        {{ t("briefDialogue.composeNow") }}
      </button>
      <button
        type="button"
        class="inline-flex min-h-11 items-center text-petrol-on-night-2 underline-offset-4 hover:underline disabled:text-on-night-3 disabled:no-underline"
        data-testid="brief-dialogue-open-form"
        :disabled="busy"
        @click="emit('open-form')"
      >
        {{ t("briefDialogue.openForm") }}
      </button>
      <button
        type="button"
        class="inline-flex min-h-11 items-center text-on-night-3 underline-offset-4 hover:underline disabled:no-underline"
        data-testid="brief-dialogue-close"
        :disabled="busy"
        @click="closeDialogue"
      >
        {{ t("briefDialogue.close") }}
      </button>
    </div>
  </section>
</template>
