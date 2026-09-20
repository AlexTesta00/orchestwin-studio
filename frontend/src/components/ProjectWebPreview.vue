<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient, ApiError, resolveApiBaseUrl } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useWebExecutionStore } from "@/stores/webExecution";
import { buildWebPreview, type PreviewContent } from "./webPreview";
import WebSourceEditor from "./WebSourceEditor.vue";
import type { WebSourceRevisionPayload } from "@/types/webExecution";

const props = withDefaults(defineProps<{ projectId: string; locale?: "it" | "en" }>(), {
  locale: "en",
});
const auth = useAuthStore();
const web = useWebExecutionStore();
const document = ref<string | null>(null);
const busy = ref(false);
const error = ref(false);
const editing = ref<PreviewContent | null>(null);
const viewport = ref<"desktop" | "mobile">("desktop");
let epoch = 0;
const revision = computed(() =>
  web.activeProjectId === props.projectId ? web.currentSourceRevision : null,
);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "La tua applicazione",
        open: "Apri anteprima",
        close: "Chiudi anteprima",
        download: "Scarica il progetto",
        tools: "Codice e dettagli della versione",
        technicalInfo:
          "L’anteprima esegue HTML, CSS e JavaScript in un riquadro isolato. Non equivale alla validazione Level D o ai test del progetto.",
        edit: "Modifica sorgenti",
        desktop: "Computer",
        mobile: "Telefono",
        revised: "Versione rivista con assistenza · prima proposta AI conservata",
        empty: "Crea prima l’applicazione nel passaggio precedente.",
        info: "Esplora l’anteprima con mouse e tastiera. È una versione da provare, non ancora una pubblicazione verificata.",
        failed: "Impossibile aprire il risultato. Riprova oppure scarica il progetto.",
        unsupported:
          "Questo formato non si può aprire qui. Scarica il progetto e usa gli strumenti di sviluppo per avviarlo.",
      }
    : {
        title: "Your application",
        open: "Open preview",
        close: "Close preview",
        download: "Download project",
        tools: "Code and version details",
        technicalInfo:
          "The preview runs HTML, CSS and JavaScript in an isolated frame. It does not establish Level D validation or project test results.",
        edit: "Edit sources",
        desktop: "Desktop",
        mobile: "Mobile",
        revised: "Assisted revision · original model output preserved in history",
        empty: "Create the application in the previous step first.",
        info: "Explore the preview with your mouse and keyboard. This is a version to try, not yet a verified release.",
        failed: "Could not open the result. Try again or download the project.",
        unsupported:
          "This format cannot be opened here. Download the project and use development tools to run it.",
      },
);
async function request(action: "content" | "download" | "edit") {
  const source = revision.value;
  if (!source || busy.value) return;
  const projectId = props.projectId;
  const currentEpoch = epoch;
  busy.value = true;
  error.value = false;
  try {
    const response = await auth.withAccessToken(apiClient, async (token) => {
      const result = await fetch(
        `${resolveApiBaseUrl()}/projects/${encodeURIComponent(projectId)}/web-source-revisions/${encodeURIComponent(source.id)}/${action === "edit" ? "content" : action}`,
        {
          credentials: "include",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      if (!result.ok) throw new ApiError(result.status, "WEB_SOURCE_CONTENT_UNAVAILABLE");
      return result;
    });
    if (action !== "download") {
      const content = (await response.json()) as PreviewContent;
      if (content.revision_id !== source.id || content.content_hash !== source.content_hash)
        throw new Error("REVISION_CHANGED");
      if (epoch !== currentEpoch) return;
      if (action === "edit") {
        // Fail before mounting the text editor when a source tree contains binary assets.
        for (const file of content.files)
          new TextDecoder("utf-8", { fatal: true }).decode(
            Uint8Array.from(atob(file.base64), (c) => c.charCodeAt(0)),
          );
        editing.value = content;
      } else document.value = buildWebPreview(content);
    } else {
      const blob = await response.blob();
      if (epoch !== currentEpoch) return;
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `web-source-${source.id}.zip`;
      window.document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
  } catch {
    if (epoch === currentEpoch) error.value = true;
  } finally {
    if (epoch === currentEpoch) busy.value = false;
  }
}
function saved(source: WebSourceRevisionPayload) {
  if (source.project_id !== props.projectId || web.activeProjectId !== props.projectId) return;
  web.sourceRevisions = [
    ...web.sourceRevisions.filter((item) => item.id !== source.id),
    source,
  ].sort((a, b) => a.version_number - b.version_number);
  editing.value = null;
}
watch(
  () => [props.projectId, revision.value?.id],
  () => {
    epoch++;
    document.value = null;
    error.value = false;
    busy.value = false;
    editing.value = null;
  },
);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <section
    class="space-y-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"
    :aria-busy="busy"
  >
    <h2 class="text-lg font-bold">{{ copy.title }}</h2>
    <p class="text-sm text-slate-500">{{ copy.info }}</p>
    <p v-if="revision?.origin === 'OWNER_EDIT'" class="text-xs text-slate-600">
      {{ copy.revised }}
    </p>
    <p v-if="!revision">{{ copy.empty }}</p>
    <template v-else>
      <div class="flex flex-wrap gap-3">
        <button
          v-if="revision.target_selection.target === 'WEB_STATIC' && !document"
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
    <details v-if="revision" class="rounded-xl border border-slate-200 px-3 py-2 text-sm">
      <summary class="cursor-pointer font-semibold text-slate-500">{{ copy.tools }}</summary>
      <p class="my-3 text-slate-500">{{ copy.technicalInfo }}</p>
      <button
        v-if="revision.target_selection.target === 'WEB_STATIC'"
        class="rounded-xl border px-4 py-2"
        :disabled="busy || !!editing"
        @click="request('edit')"
      >
        {{ copy.edit }}
      </button>
    </details>
    <WebSourceEditor
      v-if="editing"
      :key="editing.revision_id"
      :project-id="projectId"
      :content="editing"
      :locale="locale"
      @saved="saved"
      @cancel="editing = null"
    />
    <div v-if="document" class="flex gap-2">
      <button
        v-for="size in ['desktop', 'mobile'] as const"
        :key="size"
        :aria-pressed="viewport === size"
        class="rounded-lg border px-3 py-1 text-xs"
        :class="viewport === size ? 'bg-slate-100 font-bold' : ''"
        @click="viewport = size"
      >
        {{ copy[size] }}
      </button>
    </div>
    <!-- Native validation and submit events require allow-forms; the injected
         form-action 'none' CSP still prevents every form navigation. -->
    <iframe
      v-if="document"
      :title="copy.title"
      :srcdoc="document"
      sandbox="allow-scripts allow-forms"
      referrerpolicy="no-referrer"
      class="mx-auto block h-[600px] w-full rounded-xl border bg-white"
      :class="viewport === 'mobile' ? 'max-w-[375px]' : ''"
    ></iframe>
  </section>
</template>
