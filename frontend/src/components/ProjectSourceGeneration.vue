<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/api/client";
import { ApiRequestError } from "@/api/requestError";
import { generationProgress, modelFeedback } from "./modelFeedback";
import TwinIdentity from "./TwinIdentity.vue";
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
        title: "Crea la tua applicazione",
        settings: "Opzioni per lo sviluppo",
        selection: "Formato scelto",
        previewHint: "La versione web semplice si può provare direttamente qui.",
        otherHint: "Questo formato richiede strumenti di sviluppo esterni per essere provato.",
        target: "Tecnologia",
        frontend: "Linguaggio frontend",
        backend: "Linguaggio backend",
        intro:
          "Gli assistenti realizzano una prima versione seguendo le scelte che hai approvato. La versione web semplice si potrà aprire e provare nel passaggio successivo.",
        waiting: "Approva la soluzione nel passaggio precedente per continuare.",
        exists:
          "La tua applicazione è già disponibile. Apri il passaggio Risultato per consultarla.",
        unavailable: "Il profilo selezionato non è disponibile.",
        loadingProfiles: "Caricamento dei profili disponibili…",
        generate: "Crea applicazione",
        busy: generationProgress("it"),
        created: "Revisione generata",
        failed:
          "Generazione non completata. Controlla lo stato del modello e aggiorna le revisioni prima di riprovare.",
        refreshFailed:
          "I sorgenti sono stati salvati, ma non è stato possibile aggiornare la revisione. Ricarica la pagina per visualizzarli.",
        levelC:
          "Potrai provare un’anteprima. La verifica completa dell’applicazione non è ancora disponibile per questo formato.",
      }
    : {
        title: "Create your application",
        settings: "Development options",
        selection: "Selected format",
        previewHint: "The simple web version can be tried right here.",
        otherHint: "This format needs external development tools to be tried.",
        target: "Technology",
        frontend: "Frontend language",
        backend: "Backend language",
        intro:
          "The assistants build a first version from your approved choices. You can open and try the simple web version in the next step.",
        waiting: "Approve the solution in the previous step to continue.",
        exists: "Your application is already available. Open the Result step to view it.",
        unavailable: "The selected profile is unavailable.",
        loadingProfiles: "Loading available profiles…",
        generate: "Create application",
        busy: generationProgress("en"),
        created: "Generated revision",
        failed:
          "Generation did not complete. Check the model and refresh source revisions before retrying.",
        refreshFailed:
          "Sources were saved, but source review could not refresh. Reload the page to view them.",
        levelC:
          "You can try a preview. Full application verification is not yet available for this format.",
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
    <TwinIdentity
      :role="platform === 'web' ? 'FRONTEND_ENGINEER' : 'BACKEND_ENGINEER'"
      :locale="locale"
      compact
    />
    <h2 id="source-generation-title" class="text-xl font-bold">{{ copy.title }}</h2>
    <p class="text-sm leading-6 text-slate-600">{{ copy.intro }}</p>
    <p v-if="!approved" role="status">{{ copy.waiting }}</p>
    <form class="space-y-3" @submit.prevent="generate">
      <div class="rounded-xl bg-indigo-50 p-4 text-sm text-indigo-950">
        <p class="font-semibold">
          {{ copy.selection }}:
          {{
            target === "WEB_STATIC"
              ? locale === "it"
                ? "Web semplice"
                : "Simple web"
              : targets.find((option) => option.value === target)?.label
          }}
        </p>
        <p class="mt-1 text-indigo-800">
          {{ target === "WEB_STATIC" ? copy.previewHint : copy.otherHint }}
        </p>
      </div>
      <details class="rounded-xl border border-slate-200 p-3 text-sm">
        <summary class="cursor-pointer font-semibold text-slate-600">{{ copy.settings }}</summary>
        <div class="mt-3 space-y-3">
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
        </div>
      </details>
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
