<script setup lang="ts">
import { computed, nextTick, onMounted, ref, useId, watch } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import { twinChatApi, type TwinChatApi } from "@/api/twinChat";
import UiButton from "@/components/UiButton.vue";
import InsightApplyMenu from "@/components/InsightApplyMenu.vue";
import TwinIdentity from "@/components/TwinIdentity.vue";
import UiClaimFrame from "@/components/UiClaimFrame.vue";
import UiClaimLabel from "@/components/UiClaimLabel.vue";
import { useSurface } from "@/components/UiSurface.vue";
import { observationLabel } from "@/components/observationLabels";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedTwinChatRequest, useTwinChatStore } from "@/stores/twinChat";
import type { TwinInsightPayload } from "@/types/twinChat";
import type { UserTwinVersionPayload } from "@/types/userModeling";

const props = withDefaults(
  defineProps<{
    projectId: string;
    twin: UserTwinVersionPayload;
    api?: TwinChatApi | undefined;
    authorize?: AuthorizedTwinChatRequest | undefined;
  }>(),
  { api: () => twinChatApi, authorize: undefined },
);

const { t, locale } = useI18n({ useScope: "global" });
const auth = useAuthStore();
const store = useTwinChatStore();
const context = useSurface(() => undefined);

const messages = {
  en: {
    simulated: "Simulated answers · hypotheses",
    placeholder: "Write a question",
    send: "Send",
    suggestions: "Questions to start with",
    suggested: [
      "How do you usually work?",
      "What wastes your time today?",
      "What do you expect from this application?",
    ],
    you: "You",
    errorTitle: "The twin could not answer.",
    details: "Details",
    errors: {
      TWIN_CHAT_MODEL_NOT_CONFIGURED:
        "The model that plays the twins is not connected. Ask whoever runs the Studio to connect it.",
      TWIN_CONVERSATION_CHANGED:
        "The conversation changed in the meantime. Close the panel and open it again.",
      TWIN_CONVERSATION_FULL: "This conversation is full. The twin cannot take more questions.",
      TWIN_QUESTION_INVALID: "The question cannot be sent: write it again with plain words.",
      USER_TWIN_NOT_FOUND: "This twin is no longer among the twins of the project.",
      DATABASE_UNAVAILABLE: "The Studio cannot save the conversation now. Try again in a moment.",
    },
    fallback: "The twin could not answer. Try again in a moment.",
  },
  it: {
    simulated: "Risposte simulate · ipotesi",
    placeholder: "Scrivi una domanda",
    send: "Invia",
    suggestions: "Domande per iniziare",
    suggested: [
      "Come lavori di solito?",
      "Che cosa ti fa perdere tempo oggi?",
      "Che cosa ti aspetti da questa applicazione?",
    ],
    you: "Tu",
    errorTitle: "Il twin non ha potuto rispondere.",
    details: "Dettagli",
    errors: {
      TWIN_CHAT_MODEL_NOT_CONFIGURED:
        "Il modello che dà voce ai twin non è collegato. Chiedi a chi gestisce lo Studio di collegarlo.",
      TWIN_CONVERSATION_CHANGED:
        "Nel frattempo la conversazione è cambiata. Chiudi il pannello e riaprilo.",
      TWIN_CONVERSATION_FULL: "Questa conversazione è piena: il twin non accetta altre domande.",
      TWIN_QUESTION_INVALID: "La domanda non si può inviare: riscrivila con parole semplici.",
      USER_TWIN_NOT_FOUND: "Questo twin non è più tra i twin del progetto.",
      DATABASE_UNAVAILABLE:
        "Lo Studio non riesce a salvare la conversazione ora. Riprova tra poco.",
    },
    fallback: "Il twin non ha potuto rispondere. Riprova tra poco.",
  },
} as const;

const lang = computed(() => (locale.value.startsWith("it") ? "it" : "en"));
const copy = computed(() => messages[lang.value]);

const question = ref("");
const questionMissing = ref(false);
const loaded = ref(false);
const log = ref<HTMLElement | null>(null);
const questionId = useId();

const authorize: AuthorizedTwinChatRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const twinId = computed(() => props.twin.twin_id);
const conversation = computed(() => store.conversationOf(twinId.value));
const turns = computed(() => conversation.value?.turns ?? []);
const busy = computed(() => store.isBusy(twinId.value));
const staleVersion = computed(
  () =>
    conversation.value !== null &&
    conversation.value.twin_version_number !== props.twin.version_number,
);

const suggestions = computed(() => {
  const asked = new Set(turns.value.map((turn) => turn.question.trim().toLocaleLowerCase()));
  return copy.value.suggested.filter((item) => !asked.has(item.toLocaleLowerCase()));
});

const failure = computed(() => {
  const code = store.error;
  if (code === null) return null;
  const known: Readonly<Record<string, string>> = copy.value.errors;
  const text = known[code];
  return text === undefined ? { text: copy.value.fallback, code } : { text, code: null };
});

const palettes = {
  light: {
    muted: "text-ink-3",
    text: "text-ink-2",
    mine: "bg-ink text-white",
    insight: "border-line bg-surface-2",
    kind: "border-line bg-surface-3 text-ink-2",
    chip: "border-button-line bg-surface text-ink hover:bg-surface-3",
    composer: "border-line bg-surface",
    field: "border-field bg-surface text-ink placeholder:text-ink-3",
    error: "border-fail-line bg-fail-bg text-fail-dark",
    alert: "text-fail-dark",
    stale: "border-line bg-surface-3 text-ink-2",
  },
  night: {
    muted: "text-on-night-3",
    text: "text-on-night-2",
    mine: "bg-on-night text-ink",
    insight: "border-night-line bg-night-raised",
    kind: "border-night-line-strong bg-night-raised text-on-night-2",
    chip: "border-night-line-strong bg-night-raised text-on-night hover:bg-night-hover",
    composer: "border-night-line bg-night-panel",
    field: "border-night-line-strong bg-night-raised text-on-night placeholder:text-on-night-3",
    error: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
    alert: "text-fail-on-night",
    stale: "border-night-line bg-night-raised text-on-night-2",
  },
};

const palette = computed(() => palettes[context.value]);

function confidenceText(insight: TwinInsightPayload): string {
  return new Intl.NumberFormat(locale.value, { style: "percent", maximumFractionDigits: 0 }).format(
    insight.confidence,
  );
}

function groundingText(insight: TwinInsightPayload): string {
  const labels = insight.grounded_on.map((key) =>
    observationLabel(key, lang.value).toLocaleLowerCase(lang.value),
  );
  return new Intl.ListFormat(lang.value, { style: "long", type: "conjunction" }).format([
    ...new Set(labels),
  ]);
}

async function scrollToLatest(): Promise<void> {
  await nextTick();
  const element = log.value;
  if (element !== null && typeof element.scrollIntoView === "function") {
    element.lastElementChild?.scrollIntoView({ block: "nearest" });
  }
}

async function load(): Promise<void> {
  try {
    await store.load(props.projectId, twinId.value, authorize, props.api);
  } catch {
    return;
  } finally {
    loaded.value = true;
  }
}

async function ask(): Promise<void> {
  const text = question.value.trim();
  if (text.length === 0) {
    questionMissing.value = true;
    return;
  }
  questionMissing.value = false;
  try {
    await store.ask(
      props.projectId,
      twinId.value,
      props.twin.version_number,
      text,
      authorize,
      props.api,
    );
    question.value = "";
  } catch {
    return;
  }
}

async function askSuggestion(text: string): Promise<void> {
  if (busy.value) return;
  question.value = text;
  await ask();
}

watch(() => turns.value.length, scrollToLatest);

onMounted(load);
</script>

<template>
  <section
    class="flex min-h-[calc(100dvh-109px)] flex-col gap-4"
    data-testid="twin-chat"
    :data-surface-context="context"
  >
    <div class="grid gap-3">
      <TwinIdentity
        :identity-key="twin.twin_id"
        :name="twin.profile.name"
        :description="copy.simulated"
        :locale="locale.startsWith('it') ? 'it' : 'en'"
      />
      <div class="flex flex-wrap items-center gap-2">
        <UiClaimLabel kind="hypothesis" />
        <span :class="['text-xs font-semibold', palette.muted]">
          {{ t("twinChat.version", { n: twin.version_number }) }}
        </span>
      </div>
      <p :class="['m-0 text-[13px] leading-5', palette.muted]">{{ t("twinChat.notice") }}</p>
    </div>

    <p
      v-if="staleVersion"
      :class="['m-0 rounded-field border px-4 py-3 text-sm', palette.stale]"
      data-testid="twin-chat-stale"
    >
      {{ t("twinChat.stale", { n: conversation?.twin_version_number ?? 0 }) }}
    </p>

    <ol
      v-if="turns.length > 0"
      ref="log"
      class="m-0 flex list-none flex-col gap-4 p-0"
      data-testid="twin-chat-turns"
      aria-live="polite"
    >
      <li
        v-for="turn in turns"
        :key="turn.id"
        class="flex flex-col gap-2.5"
        data-testid="twin-chat-turn"
      >
        <p
          :class="[
            'm-0 max-w-[85%] self-end rounded-[14px] rounded-br-[4px] px-3.5 py-2.5 text-[15px] leading-normal',
            palette.mine,
          ]"
        >
          <span class="sr-only">{{ copy.you }}: </span>{{ turn.question }}
        </p>
        <UiClaimFrame
          status="hypothesis"
          radius="field"
          :padded="false"
          class="max-w-[85%] self-start rounded-[14px] rounded-bl-[4px] px-3.5 py-2.5"
        >
          <span class="sr-only">{{ twin.profile.name }}: </span>
          <span class="block text-[15px] leading-normal whitespace-pre-line">{{ turn.reply }}</span>
        </UiClaimFrame>
        <div v-if="turn.insights.length > 0" class="grid max-w-[92%] gap-2 self-start">
          <h3 :class="['m-0 font-mono text-[11px] tracking-label uppercase', palette.muted]">
            {{ t("twinChat.insights") }}
          </h3>
          <ul class="m-0 grid list-none gap-2 p-0">
            <li
              v-for="(insight, index) in turn.insights"
              :key="`${turn.id}:${index}`"
              :class="['grid gap-1.5 rounded-field border px-3.5 py-3 text-sm', palette.insight]"
              data-testid="twin-chat-insight"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span
                  :class="[
                    'inline-flex min-h-6 items-center rounded-pill border px-2 text-xs font-semibold',
                    palette.kind,
                  ]"
                >
                  {{ t(`twinChat.kinds.${insight.kind}`) }}
                </span>
                <span :class="['font-mono text-xs', palette.muted]">
                  {{ t("twinChat.confidence", { value: confidenceText(insight) }) }}
                </span>
              </div>
              <p class="m-0 leading-6">{{ insight.text }}</p>
              <p
                v-if="insight.grounded_on.length > 0"
                :class="['m-0 font-mono text-xs', palette.muted]"
              >
                {{ t("twinChat.groundedOn", { fields: groundingText(insight) }) }}
              </p>
              <InsightApplyMenu
                :project-id="projectId"
                :source="{
                  kind: 'TWIN_CHAT_INSIGHT',
                  id: turn.id + ':' + index,
                  twinId: twin.twin_id,
                  text: insight.text,
                }"
                :locale="locale === 'it' ? 'it' : 'en'"
                :authorize="authorize"
              />
            </li>
          </ul>
        </div>
      </li>
    </ol>
    <p
      v-else-if="loaded"
      :class="['m-0 text-sm leading-6', palette.muted]"
      data-testid="twin-chat-empty"
    >
      {{ t("twinChat.empty", { name: twin.profile.name }) }}
    </p>

    <p
      v-if="busy"
      :class="['m-0 inline-flex items-center gap-2 self-start text-sm', palette.muted]"
      aria-live="polite"
      data-testid="twin-chat-busy"
    >
      <span class="inline-flex gap-1" aria-hidden="true">
        <span class="size-1.5 animate-pulse rounded-full bg-violet-on-night" />
        <span
          class="size-1.5 animate-pulse rounded-full bg-violet-on-night [animation-delay:150ms]"
        />
        <span
          class="size-1.5 animate-pulse rounded-full bg-violet-on-night [animation-delay:300ms]"
        />
      </span>
      {{ t("twinChat.thinking", { name: twin.profile.name }) }}
    </p>
    <div
      v-if="failure !== null"
      role="alert"
      :class="['grid gap-1 rounded-field border px-4 py-3 text-sm', palette.error]"
      data-testid="twin-chat-error"
    >
      <p class="m-0 font-semibold">{{ failure.text }}</p>
      <details v-if="failure.code !== null" class="text-xs">
        <summary class="flex min-h-11 cursor-pointer items-center">{{ copy.details }}</summary>
        <code class="break-all">{{ failure.code }}</code>
      </details>
    </div>

    <form
      :class="[
        'sticky bottom-0 -mx-6 mt-auto grid gap-2.5 border-t px-6 pt-3 pb-4',
        palette.composer,
      ]"
      @submit.prevent="ask"
    >
      <div v-if="suggestions.length > 0" class="flex flex-wrap gap-1.5">
        <p class="sr-only">{{ copy.suggestions }}</p>
        <button
          v-for="suggestion in suggestions"
          :key="suggestion"
          type="button"
          :class="[
            'inline-flex min-h-11 items-center rounded-pill border px-3 text-[13px] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60',
            palette.chip,
          ]"
          :disabled="busy"
          data-testid="twin-chat-suggestion"
          @click="askSuggestion(suggestion)"
        >
          {{ suggestion }}
        </button>
      </div>
      <label :for="questionId" class="sr-only">
        {{ t("twinChat.questionLabel", { name: twin.profile.name }) }}
      </label>
      <div class="flex items-end gap-2">
        <textarea
          :id="questionId"
          v-model="question"
          rows="1"
          :disabled="busy"
          :placeholder="copy.placeholder"
          :class="[
            'field-sizing-content max-h-40 min-h-11 flex-1 resize-none rounded-control border px-3 py-2.5 text-[15px] leading-normal',
            palette.field,
          ]"
          data-testid="twin-chat-question"
          @keydown.enter.exact.prevent="ask"
        ></textarea>
        <UiButton type="submit" :disabled="busy" data-testid="twin-chat-ask">
          {{ copy.send }}
        </UiButton>
      </div>
      <p v-if="questionMissing" role="alert" :class="['m-0 text-sm font-semibold', palette.alert]">
        {{ t("twinChat.questionMissing") }}
      </p>
    </form>
  </section>
</template>
