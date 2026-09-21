<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/api/client";
import {
  sourceGenerationApi,
  type SourceGenerationApi,
  type SourcePlatform,
} from "@/api/sourceGeneration";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedRequest } from "@/stores/architecture";

const props = withDefaults(
  defineProps<{
    projectId: string;
    platform: SourcePlatform;
    executionId: string;
    baseRevisionHash: string;
    failureSignature: string;
    locale?: "en" | "it";
    disabled?: boolean;
    authorize?: AuthorizedRequest;
    api?: SourceGenerationApi;
  }>(),
  { locale: "en", disabled: false },
);
const emit = defineEmits<{ generated: [] }>();
const auth = useAuthStore();
const pending = ref(false);
const error = ref(false);
const complete = ref(false);
let epoch = 0;
const copy = computed(() =>
  props.locale === "it"
    ? {
        action: "Proponi una riparazione con il modello",
        busy: "Generazione della proposta…",
        complete: "Proposta generata: revisiona le modifiche prima di applicarle.",
        error:
          "Proposta non completata. Aggiorna le evidenze e controlla lo stato del modello prima di riprovare.",
      }
    : {
        action: "Propose a repair with the model",
        busy: "Generating a proposal…",
        complete: "Proposal generated. Review the changes before applying them.",
        error:
          "The proposal did not complete. Refresh evidence and check the model before retrying.",
      },
);
async function generate() {
  if (pending.value || props.disabled) return;
  const currentEpoch = epoch;
  pending.value = true;
  error.value = false;
  complete.value = false;
  const { projectId, platform, executionId, baseRevisionHash, failureSignature } = props;
  const operation = (token: string) =>
    (props.api ?? sourceGenerationApi).repair(
      projectId,
      platform,
      executionId,
      {
        base_revision_content_hash: baseRevisionHash,
        failure_signature_digest: failureSignature,
      },
      token,
    );
  try {
    await (props.authorize?.(operation) ?? auth.withAccessToken(apiClient, operation));
    if (currentEpoch !== epoch) return;
    complete.value = true;
    emit("generated");
  } catch {
    if (currentEpoch === epoch) error.value = true;
  } finally {
    if (currentEpoch === epoch) pending.value = false;
  }
}
watch(
  () => [props.projectId, props.executionId, props.baseRevisionHash, props.failureSignature],
  () => {
    epoch++;
    pending.value = false;
    error.value = false;
    complete.value = false;
  },
);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <div class="mt-3 space-y-2" :aria-busy="pending">
    <button
      type="button"
      class="rounded-lg bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50"
      :disabled="pending || disabled || complete"
      @click="generate"
    >
      {{ pending ? copy.busy : copy.action }}
    </button>
    <p v-if="complete" role="status">{{ copy.complete }}</p>
    <p v-if="error" role="alert">{{ copy.error }}</p>
  </div>
</template>
