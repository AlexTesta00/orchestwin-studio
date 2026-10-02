<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { apiClient } from "@/api/client";
import {
  modelRuntimeReadiness,
  type ModelRuntimeComponent,
  type ModelRuntimeReadiness,
} from "@/api/modelRuntime";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedRequest } from "@/stores/design";

const props = withDefaults(
  defineProps<{
    locale?: "it" | "en";
    authorize?: AuthorizedRequest;
    query?: (token: string) => Promise<ModelRuntimeReadiness>;
  }>(),
  { locale: "en" },
);
const auth = useAuthStore();
const status = ref<ModelRuntimeReadiness | null>(null);
const pending = ref(false);
let mounted = true;
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Modello AI",
        ready: "Il modello AI è collegato e pronto a ricevere richieste.",
        development:
          "Questo ambiente usa simulazioni di sviluppo. Il modello AI reale non è collegato.",
        unavailable: "Il modello AI non è al momento raggiungibile. Riprova tra poco.",
        unknown: "Non è stato possibile verificare la disponibilità del modello.",
        refresh: "Verifica disponibilità",
        checking: "Verifica in corso…",
        claudeReady: "Claude Code {version}, abbonamento {subscription}",
        claudeReadyWithoutPlan: "Claude Code {version}, con l'abbonamento di Claude",
        claudeReadyWithoutVersion: "Claude Code, abbonamento {subscription}",
        claudeReadyWithoutEither: "Claude Code, con l'abbonamento di Claude",
        claudeNotFound:
          "Lo Studio non trova Claude Code: installalo sul computer dove gira lo Studio, poi verifica di nuovo.",
        claudeNotLoggedIn:
          "Claude Code non è collegato a un account: esegui `claude` una volta in un terminale e accedi con il tuo account Claude.",
        claudeNotOnSubscription:
          "Claude Code è collegato a un account senza abbonamento di Claude: accedi con l'account del tuo abbonamento.",
      }
    : {
        title: "AI model",
        ready: "The AI model is connected and ready for requests.",
        development:
          "This environment uses development simulations. The real AI model is not connected.",
        unavailable: "The AI model cannot be reached right now. Try again shortly.",
        unknown: "Could not check model availability.",
        refresh: "Check availability",
        checking: "Checking…",
        claudeReady: "Claude Code {version}, {subscription} subscription",
        claudeReadyWithoutPlan: "Claude Code {version}, on the Claude subscription",
        claudeReadyWithoutVersion: "Claude Code, {subscription} subscription",
        claudeReadyWithoutEither: "Claude Code, on the Claude subscription",
        claudeNotFound:
          "The Studio cannot find Claude Code: install it on the computer where the Studio runs, then check again.",
        claudeNotLoggedIn:
          "Claude Code is not logged in: run `claude` once in a terminal and log in with your Claude account.",
        claudeNotOnSubscription:
          "Claude Code is logged in to an account without a Claude subscription: log in with the account of your subscription.",
      },
);
const description = computed(() =>
  !status.value
    ? copy.value.unknown
    : status.value.mode === "DEVELOPMENT_FIXTURES"
      ? copy.value.development
      : status.value.ready
        ? copy.value.ready
        : copy.value.unavailable,
);
const claudeCode = computed(() =>
  pending.value || !status.value
    ? []
    : Object.entries(status.value.components ?? {}).flatMap(([name, component]) => {
        const text = claudeCodeText(component);
        return text === null ? [] : [{ name, parts: commandParts(text) }];
      }),
);

function claudeCodeText(component: ModelRuntimeComponent): string | null {
  const failure = claudeCodeFailure(component.code);
  if (component.kind !== "CLAUDE_CODE_CLI" && failure === null) return null;
  return component.ready ? claudeCodeReady(component) : failure;
}

function claudeCodeReady({ version, subscription }: ModelRuntimeComponent): string {
  const text = copy.value;
  if (version && subscription) return fill(text.claudeReady, { version, subscription });
  if (version) return fill(text.claudeReadyWithoutPlan, { version });
  if (subscription) return fill(text.claudeReadyWithoutVersion, { subscription });
  return text.claudeReadyWithoutEither;
}

function claudeCodeFailure(code: string | undefined): string | null {
  switch (code) {
    case "CLAUDE_CODE_NOT_FOUND":
      return copy.value.claudeNotFound;
    case "CLAUDE_CODE_NOT_LOGGED_IN":
      return copy.value.claudeNotLoggedIn;
    case "CLAUDE_CODE_NOT_ON_SUBSCRIPTION":
      return copy.value.claudeNotOnSubscription;
    default:
      return null;
  }
}

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => values[key] ?? "");
}

function commandParts(text: string): { key: number; text: string; command: boolean }[] {
  return text
    .split("`")
    .map((part, index) => ({ key: index, text: part, command: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

async function refresh() {
  if (pending.value) return;
  pending.value = true;
  try {
    const operation = props.query ?? modelRuntimeReadiness;
    const report = await (props.authorize?.(operation) ??
      auth.withAccessToken(apiClient, operation));
    if (mounted) status.value = report;
  } catch {
    if (mounted) status.value = null;
  } finally {
    if (mounted) pending.value = false;
  }
}
onMounted(refresh);
onUnmounted(() => {
  mounted = false;
});
</script>

<template>
  <section
    class="grid grid-cols-1 gap-x-5 gap-y-1 text-[13px] sm:grid-cols-[180px_minmax(0,1fr)]"
    aria-labelledby="model-runtime-status-title"
    :aria-busy="pending"
    data-testid="model-runtime-status"
  >
    <h2 id="model-runtime-status-title" class="text-[13px] font-normal text-on-night-3">
      {{ copy.title }}
    </h2>
    <div class="grid justify-items-start">
      <p role="status" class="font-mono text-xs leading-[1.6] text-on-night">
        {{ pending ? copy.checking : description }}
        <span
          v-for="line in claudeCode"
          :key="line.name"
          class="block"
          data-testid="model-runtime-claude-code"
        >
          <template v-for="part in line.parts" :key="part.key">
            <code v-if="part.command" class="rounded-[4px] bg-on-night/8 px-1">{{
              part.text
            }}</code>
            <template v-else>{{ part.text }}</template>
          </template>
        </span>
      </p>
      <button
        class="inline-flex min-h-11 items-center text-[13px] font-semibold text-petrol-on-night-2 underline underline-offset-[3px] hover:text-on-night disabled:cursor-not-allowed disabled:text-on-night-3 disabled:no-underline"
        type="button"
        :disabled="pending"
        @click="refresh"
      >
        {{ copy.refresh }}
      </button>
    </div>
  </section>
</template>
