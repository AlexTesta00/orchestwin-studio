<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { apiClient, ApiError, resolveApiBaseUrl } from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useWebExecutionStore } from "@/stores/webExecution";
import { buildWebPreview, type PreviewContent } from "./webPreview";
import WebSourceEditor from "./WebSourceEditor.vue";
import type { WebSourceRevisionPayload } from "@/types/webExecution";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";

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
  <UiCard :aria-busy="busy">
    <div class="grid gap-4">
      <div class="grid gap-1">
        <h2 class="m-0 text-2xl font-semibold tracking-card">{{ copy.title }}</h2>
        <p class="m-0 text-[15px] text-ink-2">{{ copy.info }}</p>
        <p v-if="revision?.origin === 'OWNER_EDIT'" class="m-0 font-mono text-xs text-ink-3">
          {{ copy.revised }}
        </p>
      </div>
      <p v-if="!revision" class="m-0 text-[15px] text-ink-2">{{ copy.empty }}</p>
      <template v-else>
        <div class="flex flex-wrap gap-3">
          <UiButton
            v-if="revision.target_selection.target === 'WEB_STATIC' && !document"
            :disabled="busy"
            @click="request('content')"
          >
            {{ copy.open }}
          </UiButton>
          <UiButton variant="secondary" :disabled="busy" @click="request('download')">
            {{ copy.download }}
          </UiButton>
          <UiButton v-if="document" variant="secondary" @click="document = null">
            {{ copy.close }}
          </UiButton>
        </div>
        <p v-if="revision.target_selection.target !== 'WEB_STATIC'" class="m-0 text-[15px]">
          {{ copy.unsupported }}
        </p>
      </template>
      <p v-if="error" class="m-0 text-[15px] font-semibold text-fail-dark" role="alert">
        {{ copy.failed }}
      </p>
      <details v-if="revision" class="rounded-panel border border-line px-4 py-3 text-sm">
        <summary class="cursor-pointer font-semibold text-ink-2">{{ copy.tools }}</summary>
        <p class="my-3 text-ink-3">{{ copy.technicalInfo }}</p>
        <UiButton
          v-if="revision.target_selection.target === 'WEB_STATIC'"
          variant="secondary"
          :disabled="busy || !!editing"
          @click="request('edit')"
        >
          {{ copy.edit }}
        </UiButton>
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
      <div
        v-if="document"
        class="inline-flex rounded-pill border border-line-strong bg-surface p-0.5"
      >
        <button
          v-for="size in ['desktop', 'mobile'] as const"
          :key="size"
          type="button"
          :aria-pressed="viewport === size"
          :class="[
            'rounded-pill px-3 py-1.5 font-mono text-xs font-medium transition-colors',
            viewport === size ? 'bg-ink text-white' : 'text-ink-2 hover:bg-surface-3',
          ]"
          @click="viewport = size"
        >
          {{ copy[size] }}
        </button>
      </div>
      <div
        v-if="document"
        class="overflow-hidden rounded-panel border border-line-strong bg-surface-3"
      >
        <div
          class="flex items-center gap-1.5 border-b border-line-strong px-3 py-2"
          aria-hidden="true"
        >
          <span class="h-2.5 w-2.5 rounded-full bg-button-line" />
          <span class="h-2.5 w-2.5 rounded-full bg-button-line" />
          <span class="h-2.5 w-2.5 rounded-full bg-button-line" />
        </div>
        <iframe
          :title="copy.title"
          :srcdoc="document"
          sandbox="allow-scripts allow-forms"
          referrerpolicy="no-referrer"
          class="mx-auto block h-[600px] w-full bg-white"
          :class="viewport === 'mobile' ? 'max-w-[375px]' : ''"
        ></iframe>
      </div>
    </div>
  </UiCard>
</template>
