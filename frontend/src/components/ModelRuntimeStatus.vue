<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { apiClient } from "@/api/client";
import { modelRuntimeReadiness, type ModelRuntimeReadiness } from "@/api/modelRuntime";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedRequest } from "@/stores/architecture";

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
        title: "Disponibilità degli assistenti",
        ready: "Gli assistenti AI sono collegati e pronti a ricevere richieste.",
        development:
          "Questo ambiente usa simulazioni di sviluppo. Gli assistenti AI reali non sono collegati.",
        unavailable: "Gli assistenti AI non sono al momento raggiungibili. Riprova tra poco.",
        unknown: "Non è stato possibile verificare la disponibilità degli assistenti.",
        refresh: "Verifica disponibilità",
        checking: "Verifica in corso…",
      }
    : {
        title: "Assistant availability",
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
    class="rounded-panel border border-field bg-white p-4"
    aria-labelledby="model-runtime-status-title"
    :aria-busy="pending"
  >
    <h2 id="model-runtime-status-title" class="font-bold">{{ copy.title }}</h2>
    <p role="status">{{ pending ? copy.checking : description }}</p>
    <button
      class="rounded border border-line-strong px-3 py-2 font-semibold"
      type="button"
      :disabled="pending"
      @click="refresh"
    >
      {{ copy.refresh }}
    </button>
  </section>
</template>
