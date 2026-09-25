<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { briefDialogueApi, type BriefDialogueApi } from "@/api/briefDialogue";
import { apiClient } from "@/api/client";
import type { ProjectBriefVersionResponse } from "@/api/contracts";
import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
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
const auth = useAuthStore();
const store = useBriefDialogueStore();

const statement = ref("");
const statementMissing = ref(false);
const answerText = ref("");
const answerMissing = ref(false);
const synthesizing = ref(false);
const synthesizedVersion = ref<number | null>(null);

const authorize: AuthorizedBriefDialogueRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const dialogue = computed(() => store.dialogue);
const active = computed(() => store.isActive);
const pending = computed(() => store.pendingTurn);
const answered = computed(() => store.answeredTurns);
const busy = computed(() => store.busy);
const progressText = computed(() => {
  const progress = store.progress;
  if (progress === null) return "";
  const left = progress.open_essential_fields.length;
  const essentials =
    left > 0
      ? t("briefDialogue.essentialsLeft", { count: left })
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

function fieldLabel(turn: BriefDialogueTurnPayload): string {
  return turn.field === null ? t("briefDialogue.followUp") : t(`brief.fields.${turn.field}`);
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

onMounted(load);
</script>

<template>
  <section class="grid gap-5" data-testid="brief-dialogue" aria-labelledby="brief-dialogue-title">
    <header class="grid gap-2">
      <h2 id="brief-dialogue-title" class="m-0 text-2xl font-semibold tracking-card">
        {{ t("briefDialogue.title") }}
      </h2>
      <p class="m-0 max-w-3xl text-[15px] leading-6 text-ink-2">{{ t("briefDialogue.intro") }}</p>
    </header>

    <p
      v-if="errorText !== null"
      class="m-0 rounded-panel border border-fail-line bg-fail-bg p-4 text-sm font-semibold text-fail-dark"
      role="alert"
      data-testid="brief-dialogue-error"
    >
      {{ errorText }}
    </p>

    <UiCard v-if="!active" data-testid="brief-dialogue-entry">
      <template v-if="store.modelUnavailable">
        <p class="m-0 text-[15px] leading-6 text-ink-2" data-testid="brief-dialogue-unavailable">
          {{ t("briefDialogue.modelUnavailable") }}
        </p>
        <div class="mt-4">
          <UiButton
            variant="secondary"
            data-testid="brief-dialogue-open-form"
            @click="emit('open-form')"
          >
            {{ t("briefDialogue.openForm") }}
          </UiButton>
        </div>
      </template>
      <template v-else-if="synthesizedVersion !== null">
        <p class="m-0 text-[15px] leading-6 text-ink-2" data-testid="brief-dialogue-synthesized">
          {{ t("briefDialogue.synthesized") }}
        </p>
        <div class="mt-4">
          <UiButton data-testid="brief-dialogue-open-form" @click="emit('open-form')">
            {{ t("briefDialogue.goToForm") }}
          </UiButton>
        </div>
      </template>
      <form v-else class="grid gap-4" @submit.prevent="start">
        <label class="grid gap-2 text-sm font-semibold" for="brief-dialogue-statement">
          {{ t("briefDialogue.statementLabel") }}
          <textarea
            id="brief-dialogue-statement"
            v-model="statement"
            data-testid="brief-dialogue-statement"
            rows="4"
            class="rounded-control border border-field bg-surface px-3 py-2 text-[15px] font-normal"
            :placeholder="t('briefDialogue.statementPlaceholder')"
            :disabled="busy"
          ></textarea>
        </label>
        <p v-if="statementMissing" class="m-0 text-sm font-semibold text-fail-dark" role="alert">
          {{ t("briefDialogue.statementRequired") }}
        </p>
        <div class="flex flex-wrap items-center gap-4">
          <UiButton type="submit" :disabled="busy" data-testid="brief-dialogue-start">
            {{
              busy
                ? t("briefDialogue.waiting")
                : currentBrief
                  ? t("briefDialogue.restart")
                  : t("briefDialogue.start")
            }}
          </UiButton>
          <button
            type="button"
            class="text-sm font-semibold text-action underline-offset-4 hover:underline"
            data-testid="brief-dialogue-open-form"
            @click="emit('open-form')"
          >
            {{ t("briefDialogue.preferForm") }}
          </button>
        </div>
      </form>
    </UiCard>

    <template v-else-if="dialogue !== null">
      <p
        class="m-0 font-mono text-xs text-ink-3"
        data-testid="brief-dialogue-progress"
        aria-live="polite"
      >
        {{ progressText }}
      </p>

      <ol
        v-if="answered.length > 0"
        class="m-0 grid list-none gap-3 p-0"
        data-testid="brief-dialogue-turns"
      >
        <li
          v-for="turn in answered"
          :key="turn.id"
          class="grid gap-1 rounded-panel border border-line bg-surface-2 px-4 py-3"
          data-testid="brief-dialogue-turn"
        >
          <span class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">{{
            fieldLabel(turn)
          }}</span>
          <p class="m-0 text-sm text-ink-2">{{ turn.question }}</p>
          <p class="m-0 text-[15px] leading-6 whitespace-pre-line text-ink">
            {{ answerLabel(turn) }}
          </p>
        </li>
      </ol>

      <UiCard v-if="pending !== null" tone="elevated" data-testid="brief-dialogue-question">
        <span class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">{{
          fieldLabel(pending)
        }}</span>
        <h3 class="m-0 mt-2 text-xl font-semibold text-ink">{{ pending.question }}</h3>
        <form class="mt-4 grid gap-3" @submit.prevent="send">
          <label class="sr-only" for="brief-dialogue-answer">{{
            t("briefDialogue.answerLabel")
          }}</label>
          <textarea
            id="brief-dialogue-answer"
            v-model="answerText"
            data-testid="brief-dialogue-answer"
            rows="3"
            class="rounded-control border border-field bg-surface px-3 py-2 text-[15px]"
            :placeholder="
              pending.answer_type === 'ITEM_LIST'
                ? t('briefDialogue.answerPlaceholderList')
                : t('briefDialogue.answerPlaceholderText')
            "
            :disabled="busy"
          ></textarea>
          <p v-if="pending.answer_type === 'ITEM_LIST'" class="m-0 text-xs text-ink-3">
            {{ t("brief.oneItemPerLine") }}
          </p>
          <p v-if="answerMissing" class="m-0 text-sm font-semibold text-fail-dark" role="alert">
            {{ t("briefDialogue.answerRequired") }}
          </p>
          <div class="flex flex-wrap gap-3">
            <UiButton type="submit" :disabled="busy" data-testid="brief-dialogue-send">
              {{ busy ? t("briefDialogue.waiting") : t("briefDialogue.send") }}
            </UiButton>
            <UiButton
              variant="secondary"
              :disabled="busy"
              data-testid="brief-dialogue-unknown"
              @click="sayUnknown"
            >
              {{ t("briefDialogue.unknown") }}
            </UiButton>
          </div>
        </form>
      </UiCard>

      <UiCard
        v-else-if="dialogue.status === 'READY' || synthesizing"
        tone="soft"
        data-testid="brief-dialogue-composing"
      >
        <p class="m-0 text-[15px] leading-6 text-ink-2" aria-live="polite">
          {{
            synthesizing || busy ? t("briefDialogue.composing") : t("briefDialogue.readyToCompose")
          }}
        </p>
        <div v-if="!synthesizing && !busy" class="mt-4">
          <UiButton data-testid="brief-dialogue-retry-compose" @click="synthesize">
            {{ t("briefDialogue.retryCompose") }}
          </UiButton>
        </div>
      </UiCard>

      <UiCard v-else tone="soft" data-testid="brief-dialogue-resume">
        <p class="m-0 text-[15px] leading-6 text-ink-2">{{ t("briefDialogue.interrupted") }}</p>
        <div class="mt-4">
          <UiButton
            :disabled="busy"
            data-testid="brief-dialogue-continue"
            @click="continueQuestion"
          >
            {{ busy ? t("briefDialogue.waiting") : t("briefDialogue.continueQuestion") }}
          </UiButton>
        </div>
      </UiCard>

      <div class="flex flex-wrap items-center gap-4 text-sm font-semibold">
        <button
          v-if="pending !== null"
          type="button"
          class="text-action underline-offset-4 hover:underline disabled:text-ink-3"
          data-testid="brief-dialogue-compose"
          :disabled="busy"
          @click="synthesize"
        >
          {{ t("briefDialogue.composeNow") }}
        </button>
        <button
          type="button"
          class="text-action underline-offset-4 hover:underline disabled:text-ink-3"
          data-testid="brief-dialogue-open-form"
          :disabled="busy"
          @click="emit('open-form')"
        >
          {{ t("briefDialogue.openForm") }}
        </button>
        <button
          type="button"
          class="text-ink-3 underline-offset-4 hover:underline disabled:text-ink-3"
          data-testid="brief-dialogue-close"
          :disabled="busy"
          @click="closeDialogue"
        >
          {{ t("briefDialogue.close") }}
        </button>
      </div>
    </template>
  </section>
</template>
