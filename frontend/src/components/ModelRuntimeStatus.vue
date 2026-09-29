<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { apiClient } from "@/api/client";
import { modelRuntimeReadiness, type ModelRuntimeReadiness } from "@/api/modelRuntime";
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
        title: "Assistenti AI",
        ready: "Gli assistenti AI sono collegati e pronti a ricevere richieste.",
        development:
          "Questo ambiente usa simulazioni di sviluppo. Gli assistenti AI reali non sono collegati.",
        unavailable: "Gli assistenti AI non sono al momento raggiungibili. Riprova tra poco.",
        unknown: "Non è stato possibile verificare la disponibilità degli assistenti.",
        refresh: "Verifica disponibilità",
        checking: "Verifica in corso…",
      }
    : {
        title: "AI assistants",
        ready: "The AI assistants are connected and ready for requests.",
        development:
          "This environment uses development simulations. Real AI assistants are not connected.",
        unavailable: "The AI assistants cannot be reached right now. Try again shortly.",
        unknown: "Could not check assistant availability.",
        refresh: "Check availability",
        checking: "Checking…",
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
