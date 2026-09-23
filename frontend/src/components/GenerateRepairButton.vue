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
import UiButton from "./UiButton.vue";

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
    label?: string;
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
  <div class="mt-3 grid gap-2" :aria-busy="pending">
    <div>
      <UiButton :disabled="pending || disabled || complete" @click="generate">
        {{ pending ? copy.busy : (label ?? copy.action) }}
      </UiButton>
    </div>
    <p v-if="complete" class="m-0 text-[15px] font-semibold text-ok-dark" role="status">
      {{ copy.complete }}
    </p>
    <p v-if="error" class="m-0 text-[15px] font-semibold text-fail-dark" role="alert">
      {{ copy.error }}
    </p>
  </div>
</template>
