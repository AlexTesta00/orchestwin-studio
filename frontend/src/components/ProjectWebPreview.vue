<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient, ApiError, resolveApiBaseUrl } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useWebExecutionStore } from "@/stores/webExecution";
import { buildWebPreview, type PreviewContent } from "./webPreview";

const props = withDefaults(defineProps<{ projectId: string; locale?: "it" | "en" }>(), {
  locale: "en",
});
const auth = useAuthStore();
const web = useWebExecutionStore();
const document = ref<string | null>(null);
const busy = ref(false);
const error = ref(false);
let epoch = 0;
const revision = computed(() =>
  web.activeProjectId === props.projectId ? web.currentSourceRevision : null,
);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Prova l’applicazione generata",
        open: "Apri anteprima",
        close: "Chiudi anteprima",
        download: "Scarica sorgenti ZIP",
        empty: "Genera prima una revisione del sorgente.",
        info: "L’anteprima esegue HTML, CSS e JavaScript in un riquadro isolato. Non equivale alla validazione Level D o ai test del progetto.",
        failed:
          "Impossibile aprire il risultato. Controlla le risorse locali richieste; puoi scaricare i sorgenti.",
        unsupported:
          "Per questo stack scarica i sorgenti e consulta le evidenze di esecuzione. L’anteprima integrata supporta Web statico.",
      }
    : {
        title: "Try the generated application",
        open: "Open preview",
        close: "Close preview",
        download: "Download source ZIP",
        empty: "Generate a source revision first.",
        info: "The preview runs HTML, CSS and JavaScript in an isolated frame. It does not establish Level D validation or project test results.",
        failed:
          "Could not open the result. Check the required local resources; you can download the sources.",
        unsupported:
          "Download the sources and consult execution evidence for this stack. The integrated preview supports static Web.",
      },
);
async function request(action: "content" | "download") {
  const source = revision.value;
  if (!source || busy.value) return;
  const currentEpoch = epoch;
  busy.value = true;
  error.value = false;
  try {
    const response = await auth.withAccessToken(apiClient, async (token) => {
      const result = await fetch(
        `${resolveApiBaseUrl()}/projects/${encodeURIComponent(props.projectId)}/web-source-revisions/${encodeURIComponent(source.id)}/${action}`,
        {
          credentials: "include",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      if (!result.ok) throw new ApiError(result.status, "WEB_SOURCE_CONTENT_UNAVAILABLE");
      return result;
    });
    if (action === "content") {
      const content = (await response.json()) as PreviewContent;
      if (content.revision_id !== source.id || content.content_hash !== source.content_hash)
        throw new Error("REVISION_CHANGED");
      const html = buildWebPreview(content);
      if (epoch === currentEpoch) document.value = html;
    } else {
      const blob = await response.blob();
      if (epoch !== currentEpoch) return;
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `web-source-${source.id}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch {
    if (epoch === currentEpoch) error.value = true;
  } finally {
    if (epoch === currentEpoch) busy.value = false;
  }
}
watch(
  () => [props.projectId, revision.value?.id],
  () => {
    epoch++;
    document.value = null;
    error.value = false;
    busy.value = false;
  },
);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <section class="space-y-4 rounded-2xl border border-slate-200 bg-white p-6" :aria-busy="busy">
    <h2 class="text-2xl font-black">{{ copy.title }}</h2>
    <p>{{ copy.info }}</p>
    <p v-if="!revision">{{ copy.empty }}</p>
    <template v-else>
      <div class="flex flex-wrap gap-3">
        <button
          v-if="revision.target_selection.target === 'WEB_STATIC'"
          class="rounded-xl bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50"
          :disabled="busy"
          @click="request('content')"
        >
          {{ copy.open }}
        </button>
        <button
          class="rounded-xl border px-4 py-2 font-bold"
          :disabled="busy"
          @click="request('download')"
        >
          {{ copy.download }}
        </button>
        <button v-if="document" class="rounded-xl border px-4 py-2" @click="document = null">
          {{ copy.close }}
        </button>
      </div>
      <p v-if="revision.target_selection.target !== 'WEB_STATIC'">{{ copy.unsupported }}</p>
    </template>
    <p v-if="error" role="alert">{{ copy.failed }}</p>
    <iframe
      v-if="document"
      :title="copy.title"
      :srcdoc="document"
      sandbox="allow-scripts"
      referrerpolicy="no-referrer"
      class="h-[650px] w-full rounded-xl border bg-white"
    ></iframe>
  </section>
</template>
