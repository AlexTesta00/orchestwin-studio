<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import { twinChatApi, type TwinChatApi } from "@/api/twinChat";
import UiButton from "@/components/UiButton.vue";
import InsightApplyMenu from "@/components/InsightApplyMenu.vue";
import UiClaimLabel from "@/components/UiClaimLabel.vue";
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

const question = ref("");
const questionMissing = ref(false);
const loaded = ref(false);

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

function confidenceText(insight: TwinInsightPayload): string {
  return new Intl.NumberFormat(locale.value, { style: "percent", maximumFractionDigits: 0 }).format(
    insight.confidence,
  );
}

function groundingText(insight: TwinInsightPayload): string {
  return insight.grounded_on.map((key) => key.replace(/^user_twin\./u, "")).join(", ");
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
    await store.ask(props.projectId, twinId.value, text, authorize, props.api);
    question.value = "";
  } catch {
    return;
  }
}

onMounted(load);
</script>

<template>
  <section class="grid gap-5" data-testid="twin-chat">
    <div class="rounded-card border border-hypothesis-line bg-hypothesis-bg p-4">
      <div class="flex flex-wrap items-center gap-2">
        <UiClaimLabel kind="hypothesis" />
        <span class="text-xs font-semibold text-ink-3">
          {{ t("twinChat.version", { n: twin.version_number }) }}
        </span>
      </div>
      <p class="m-0 mt-2 text-sm leading-6 text-ink-2">{{ t("twinChat.notice") }}</p>
    </div>

    <p
      v-if="staleVersion"
      class="m-0 rounded-panel border border-line bg-surface-3 px-4 py-3 text-sm text-ink-2"
      data-testid="twin-chat-stale"
    >
      {{ t("twinChat.stale", { n: conversation?.twin_version_number ?? 0 }) }}
    </p>

    <ol v-if="turns.length > 0" class="m-0 grid list-none gap-4 p-0" data-testid="twin-chat-turns">
      <li
        v-for="turn in turns"
        :key="turn.id"
        class="grid gap-3 rounded-card border border-line bg-surface p-4"
        data-testid="twin-chat-turn"
      >
        <p class="m-0 text-sm leading-6 text-ink-2">
          <span class="font-semibold text-ink">{{ t("twinChat.you") }}</span>
          {{ turn.question }}
        </p>
        <div class="grid gap-2 rounded-panel bg-surface-2 p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-sm font-semibold text-ink">{{ twin.profile.name }}</span>
            <UiClaimLabel kind="hypothesis" />
          </div>
          <p class="m-0 text-[15px] leading-relaxed whitespace-pre-line text-ink">
            {{ turn.reply }}
          </p>
        </div>
        <div v-if="turn.insights.length > 0" class="grid gap-2">
          <h3 class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("twinChat.insights") }}
          </h3>
          <ul class="m-0 grid list-none gap-2 p-0">
            <li
              v-for="(insight, index) in turn.insights"
              :key="`${turn.id}:${index}`"
              class="grid gap-1 rounded-panel border border-line-soft px-3 py-2 text-sm"
              data-testid="twin-chat-insight"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span
                  class="inline-flex items-center rounded-pill border border-line bg-surface-3 px-2 py-0.5 text-xs font-semibold text-ink-2"
                >
                  {{ t(`twinChat.kinds.${insight.kind}`) }}
                </span>
                <span class="font-mono text-xs text-ink-3">
                  {{ t("twinChat.confidence", { value: confidenceText(insight) }) }}
                </span>
              </div>
              <p class="m-0 leading-6 text-ink">{{ insight.text }}</p>
              <p v-if="insight.grounded_on.length > 0" class="m-0 font-mono text-xs text-ink-3">
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
    <p v-else-if="loaded" class="m-0 text-sm text-ink-3" data-testid="twin-chat-empty">
      {{ t("twinChat.empty", { name: twin.profile.name }) }}
    </p>

    <p v-if="busy" class="m-0 text-sm text-ink-3" aria-live="polite" data-testid="twin-chat-busy">
      {{ t("twinChat.thinking", { name: twin.profile.name }) }}
    </p>
    <p
      v-if="store.error"
      role="alert"
      class="m-0 rounded-panel border border-fail-line bg-fail-bg px-4 py-3 text-sm font-semibold text-fail-dark"
    >
      {{ store.error }}
    </p>

    <form class="grid gap-3" @submit.prevent="ask">
      <label class="grid gap-2 text-sm font-semibold text-ink-2" for="twin-chat-question">
        {{ t("twinChat.questionLabel", { name: twin.profile.name }) }}
        <textarea
          id="twin-chat-question"
          v-model="question"
          rows="3"
          :disabled="busy"
          class="rounded-control border border-field bg-surface px-3 py-2 text-sm font-normal text-ink focus-visible:outline-none"
          data-testid="twin-chat-question"
        ></textarea>
      </label>
      <p v-if="questionMissing" role="alert" class="m-0 text-sm font-semibold text-fail-dark">
        {{ t("twinChat.questionMissing") }}
      </p>
      <div class="flex">
        <UiButton type="submit" :disabled="busy" data-testid="twin-chat-ask">
          {{ t("twinChat.ask") }}
        </UiButton>
      </div>
    </form>
  </section>
</template>
