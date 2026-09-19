<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/api/client";
import { ApiRequestError } from "@/api/requestError";
import { generationProgress, modelFeedback } from "./modelFeedback";
import { executionApi, type ExecutionApi } from "@/api/execution";
import {
  sourceGenerationApi,
  type SourceGenerationApi,
  type SourceGenerationInput,
} from "@/api/sourceGeneration";
import { useAuthStore } from "@/stores/auth";
import { useArchitectureStore, type AuthorizedRequest } from "@/stores/architecture";
import { useJvmExecutionStore } from "@/stores/jvmExecution";
import { useWebExecutionStore } from "@/stores/webExecution";
import type { ExecutionProfilePayload, ExecutionTarget } from "@/types/execution";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: "it" | "en";
    authorize?: AuthorizedRequest;
    api?: SourceGenerationApi;
    catalogApi?: Pick<ExecutionApi, "profiles">;
  }>(),
  { locale: "en" },
);
const auth = useAuthStore();
const architecture = useArchitectureStore();
const web = useWebExecutionStore();
const jvm = useJvmExecutionStore();
const profiles = ref<ExecutionProfilePayload[]>([]);
const profilesLoading = ref(true);
const target = ref<ExecutionTarget>("WEB_STATIC");
const frontendLanguage = ref<"JAVASCRIPT" | "TYPESCRIPT">("TYPESCRIPT");
const backendLanguage = ref<"JAVASCRIPT" | "TYPESCRIPT">("TYPESCRIPT");
const pending = ref(false);
const error = ref<string | null>(null);
const generatedVersions = ref<Partial<Record<"web" | "jvm", number>>>({});
let epoch = 0;
const platform = computed(() => (target.value.startsWith("JVM_") ? "jvm" : "web"));
const generatedVersion = computed(() => generatedVersions.value[platform.value] ?? null);
const selectedStore = computed(() => (platform.value === "web" ? web : jvm));
const targets: { value: ExecutionTarget; label: string }[] = [
  { value: "WEB_STATIC", label: "HTML / CSS / JavaScript" },
  { value: "WEB_VUE", label: "Vue" },
  { value: "WEB_NODE_EXPRESS", label: "Node / Express" },
  { value: "WEB_VUE_NODE", label: "Vue + Node / Express" },
  { value: "JVM_JAVA", label: "Java" },
  { value: "JVM_KOTLIN", label: "Kotlin" },
  { value: "JVM_SCALA", label: "Scala" },
];
const approved = computed(
  () =>
    architecture.projectId === props.projectId &&
    architecture.isReadyForImplementation &&
    architecture.current !== null,
);
const hasSource = computed(
  () =>
    generatedVersion.value !== null ||
    (selectedStore.value.activeProjectId === props.projectId &&
      selectedStore.value.sourceRevisions.length > 0),
);
const profile = computed(() =>
  profiles.value.find((item) => item.supported_targets.includes(target.value)),
);
const canGenerate = computed(
  () => approved.value && profile.value !== undefined && !hasSource.value && !pending.value,
);
const usesFrontend = computed(() => ["WEB_VUE", "WEB_VUE_NODE"].includes(target.value));
const usesBackend = computed(() => ["WEB_NODE_EXPRESS", "WEB_VUE_NODE"].includes(target.value));
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Genera l’implementazione",
        target: "Tecnologia",
        frontend: "Linguaggio frontend",
        backend: "Linguaggio backend",
        intro:
          "Il modello genera sorgenti e test dall’architettura approvata. Potrai revisionarli prima di autorizzarne l’esecuzione.",
        waiting: "Approva l’architettura per generare il sorgente.",
        exists:
          "Esiste già una revisione: usa le evidenze di esecuzione per proporre una riparazione.",
        unavailable: "Il profilo selezionato non è disponibile.",
        loadingProfiles: "Caricamento dei profili disponibili…",
        generate: "Genera sorgenti e test",
        busy: generationProgress("it"),
        created: "Revisione generata",
        failed:
          "Generazione non completata. Controlla lo stato del modello e aggiorna le revisioni prima di riprovare.",
        refreshFailed:
          "I sorgenti sono stati salvati, ma non è stato possibile aggiornare la revisione. Ricarica la pagina per visualizzarli.",
        levelC:
          "Questo profilo permette la progettazione; non è qualificato per l’esecuzione Level D.",
      }
    : {
        title: "Generate the implementation",
        target: "Technology",
        frontend: "Frontend language",
        backend: "Backend language",
        intro:
          "The model generates sources and tests from the approved architecture. Review them before authorizing execution.",
        waiting: "Approve the architecture to generate sources.",
        exists: "A source revision already exists. Use execution evidence to propose a repair.",
        unavailable: "The selected profile is unavailable.",
        loadingProfiles: "Loading available profiles…",
        generate: "Generate sources and tests",
        busy: generationProgress("en"),
        created: "Generated revision",
        failed:
          "Generation did not complete. Check the model and refresh source revisions before retrying.",
        refreshFailed:
          "Sources were saved, but source review could not refresh. Reload the page to view them.",
        levelC: "This profile supports design; it is not qualified for Level D execution.",
      },
);
function authorized<T>(operation: (token: string) => Promise<T>): Promise<T> {
  return props.authorize?.(operation) ?? auth.withAccessToken(apiClient, operation);
}
async function loadProfiles() {
  const currentEpoch = epoch;
  profilesLoading.value = true;
  try {
    const values = await authorized((token) => (props.catalogApi ?? executionApi).profiles(token));
    if (currentEpoch === epoch) profiles.value = values;
  } catch {
    if (currentEpoch === epoch) error.value = copy.value.unavailable;
  } finally {
    if (currentEpoch === epoch) profilesLoading.value = false;
  }
}
async function generate() {
  if (!canGenerate.value || !architecture.current) return;
  const project = props.projectId;
  const currentEpoch = epoch;
  const selectedPlatform = platform.value;
  const input: SourceGenerationInput = {
    target: target.value,
    architecture_version_id: architecture.current.id,
    architecture_content_hash: architecture.current.content_hash,
  };
  if (selectedPlatform === "web") {
    input.frontend_language =
      target.value === "WEB_STATIC"
        ? "STATIC_ASSETS"
        : usesFrontend.value
          ? frontendLanguage.value
          : null;
    input.backend_language = usesBackend.value ? backendLanguage.value : null;
    input.layout = target.value === "WEB_VUE_NODE" ? "FRONTEND_BACKEND" : "SINGLE_ROOT";
  }
  pending.value = true;
  error.value = null;
  try {
    const revision = await authorized((token) =>
      (props.api ?? sourceGenerationApi).source(project, selectedPlatform, input, token),
    );
    if (currentEpoch !== epoch) return;
    generatedVersions.value[selectedPlatform] = revision.version_number;
    const store = selectedPlatform === "web" ? web : jvm;
    await store.loadProject(project, authorized);
  } catch (failure) {
    if (currentEpoch === epoch)
      error.value =
        generatedVersions.value[selectedPlatform] !== undefined
          ? copy.value.refreshFailed
          : (modelFeedback(
              failure instanceof ApiRequestError ? failure.code : null,
              props.locale,
            ) ?? copy.value.failed);
  } finally {
    if (currentEpoch === epoch) pending.value = false;
  }
}
watch(
  () => props.projectId,
  () => {
    epoch++;
    pending.value = false;
    error.value = null;
    generatedVersions.value = {};
    profiles.value = [];
    void loadProfiles();
  },
);
onMounted(loadProfiles);
onUnmounted(() => {
  epoch++;
});
</script>

<template>
  <section
    class="space-y-4 rounded-2xl border border-slate-200 bg-white p-6"
    aria-labelledby="source-generation-title"
    :aria-busy="pending"
  >
    <h2 id="source-generation-title" class="text-2xl font-black">{{ copy.title }}</h2>
    <p>{{ copy.intro }}</p>
    <p v-if="!approved" role="status">{{ copy.waiting }}</p>
    <form class="space-y-3" @submit.prevent="generate">
      <label class="block"
        >{{ copy.target }}
        <select v-model="target" class="ml-3 rounded border p-2" :disabled="pending">
          <option v-for="option in targets" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>
      <label v-if="usesFrontend" class="block"
        >{{ copy.frontend }}
        <select v-model="frontendLanguage" class="ml-3 rounded border p-2" :disabled="pending">
          <option>JAVASCRIPT</option>
          <option>TYPESCRIPT</option>
        </select>
      </label>
      <label v-if="usesBackend" class="block"
        >{{ copy.backend }}
        <select v-model="backendLanguage" class="ml-3 rounded border p-2" :disabled="pending">
          <option>JAVASCRIPT</option>
          <option>TYPESCRIPT</option>
        </select>
      </label>
      <p v-if="hasSource" role="status">{{ copy.exists }}</p>
      <p v-else-if="profilesLoading" role="status">{{ copy.loadingProfiles }}</p>
      <p v-else-if="!profile" role="status">{{ copy.unavailable }}</p>
      <p v-else-if="profile.capability_status === 'DESIGN_ONLY_LEVEL_C'">{{ copy.levelC }}</p>
      <button
        type="submit"
        class="rounded-xl bg-slate-900 px-4 py-2 font-bold text-white disabled:opacity-50"
        :disabled="!canGenerate"
      >
        {{ pending ? copy.busy : copy.generate }}
      </button>
    </form>
    <p v-if="generatedVersion !== null" role="status">{{ copy.created }} {{ generatedVersion }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
