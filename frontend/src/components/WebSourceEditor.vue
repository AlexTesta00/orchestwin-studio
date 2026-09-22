<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient, ApiError, resolveApiBaseUrl } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import type { WebSourceRevisionPayload } from "@/types/webExecution";
import type { PreviewContent } from "./webPreview";
import { modelFeedback } from "./modelFeedback";

const props = defineProps<{ projectId: string; content: PreviewContent; locale: "it" | "en" }>();
const emit = defineEmits<{ saved: [revision: WebSourceRevisionPayload]; cancel: [] }>();
const auth = useAuthStore();
const files = ref(
  props.content.files.map((file) => ({
    normalized_path: file.path,
    media_type: file.media_type,
    content: new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0)),
    ),
  })),
);
const original = JSON.stringify(files.value);
const selected = ref(0);
const rationale = ref("");
const busy = ref(false);
const failed = ref(false);
const conflict = ref(false);
const rejectionCode = ref<string | null>(null);
let epoch = 0;
watch(
  () => [props.projectId, props.content.revision_id, props.content.content_hash],
  () => {
    epoch++;
  },
);
onUnmounted(() => {
  epoch++;
});
const changed = computed(() => JSON.stringify(files.value) !== original);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Revisiona i sorgenti",
        why: "Motivo della modifica",
        save: "Salva nuova revisione",
        cancel: "Annulla",
        info: "Le modifiche vengono registrate come revisione del proprietario. La versione del modello resta nella cronologia; i test e la validazione vanno eseguiti di nuovo.",
        failed: "Revisione non salvata. Verifica i file e l’approvazione dell’architettura.",
        conflict:
          "La versione di partenza o l’architettura è cambiata. Annulla e riapri i sorgenti aggiornati.",
      }
    : {
        title: "Review source files",
        why: "Reason for this change",
        save: "Save new revision",
        cancel: "Cancel",
        info: "Changes are recorded as an owner revision. The model version remains in history; tests and validation must run again.",
        failed: "Revision was not saved. Check the files and architecture approval.",
        conflict:
          "The base revision or architecture has changed. Cancel and reopen the current sources.",
      },
);
async function save() {
  if (busy.value || !changed.value || !rationale.value.trim()) return;
  busy.value = true;
  failed.value = false;
  conflict.value = false;
  rejectionCode.value = null;
  const currentEpoch = epoch;
  const projectId = props.projectId;
  const revisionId = props.content.revision_id;
  const body = JSON.stringify({
    base_revision_content_hash: props.content.content_hash,
    rationale: rationale.value.trim(),
    files: files.value,
  });
  try {
    const source = await auth.withAccessToken(apiClient, async (token) => {
      const response = await fetch(
        `${resolveApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/web-source-revisions/${encodeURIComponent(revisionId)}/edits`,
        {
          method: "POST",
          credentials: "include",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body,
        },
      );
      if (!response.ok) {
        const payload: unknown = await response.json().catch(() => null);
        const detail =
          payload && typeof payload === "object" && "detail" in payload ? payload.detail : null;
        const code =
          detail &&
          typeof detail === "object" &&
          "code" in detail &&
          typeof detail.code === "string"
            ? detail.code
            : "WEB_SOURCE_EDIT_REJECTED";
        throw new ApiError(response.status, code);
      }
      const result = (await response.json()) as { snapshot: WebSourceRevisionPayload };
      return result.snapshot;
    });
    if (epoch === currentEpoch) emit("saved", source);
  } catch (error) {
    if (epoch !== currentEpoch) return;
    conflict.value = error instanceof ApiError && error.status === 409;
    rejectionCode.value = error instanceof ApiError ? error.detail : null;
    failed.value = !conflict.value;
  } finally {
    if (epoch === currentEpoch) busy.value = false;
  }
}
</script>

<template>
  <form
    class="space-y-3 rounded-panel border border-line bg-surface-2 p-4"
    :aria-busy="busy"
    @submit.prevent="save"
  >
    <h3 class="font-bold">{{ copy.title }}</h3>
    <p class="text-sm text-ink-2">{{ copy.info }}</p>
    <div class="flex flex-wrap gap-2" :aria-label="copy.title">
      <button
        v-for="(file, index) in files"
        :key="file.normalized_path"
        type="button"
        :aria-pressed="selected === index"
        class="rounded-control border px-3 py-1.5 text-sm"
        :class="selected === index ? 'bg-action text-white' : 'bg-white'"
        @click="selected = index"
      >
        {{ file.normalized_path }}
      </button>
    </div>
    <label
      v-for="(file, index) in files"
      v-show="selected === index"
      :key="file.normalized_path"
      class="block text-sm"
    >
      <span class="sr-only">{{ file.normalized_path }}</span>
      <textarea
        v-model="file.content"
        :disabled="busy"
        spellcheck="false"
        rows="16"
        class="w-full rounded-control border bg-white p-3 font-mono text-xs leading-5"
      />
    </label>
    <label class="block text-sm font-medium"
      >{{ copy.why
      }}<input
        v-model="rationale"
        :disabled="busy"
        required
        maxlength="1000"
        class="mt-1 w-full rounded-control border bg-white px-3 py-2"
    /></label>
    <p v-if="failed || conflict" role="alert" class="text-sm text-fail-dark">
      {{ modelFeedback(rejectionCode, locale) ?? (conflict ? copy.conflict : copy.failed) }}
    </p>
    <div class="flex gap-2">
      <button
        type="submit"
        :disabled="busy || !changed || !rationale.trim()"
        class="rounded-control bg-action px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
      >
        {{ copy.save }}
      </button>
      <button
        type="button"
        :disabled="busy"
        class="rounded-control border px-4 py-2 text-sm"
        @click="emit('cancel')"
      >
        {{ copy.cancel }}
      </button>
    </div>
  </form>
</template>
