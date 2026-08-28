<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { executionApi, type ExecutionApi } from "@/api/execution";
import { webExecutionApi, type WebExecutionApi } from "@/api/webExecution";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedWebExecutionRequest, useWebExecutionStore } from "@/stores/webExecution";
import type { ExecutionProfilePayload } from "@/types/execution";
import type {
  WebExecutionTarget,
  WebSourceFilePayload,
  WebSourceRevisionPayload,
} from "@/types/webExecution";

type Locale = "en" | "it";
type FileChangeKind = "ADDED" | "REMOVED" | "CHANGED";

interface FileChangeView {
  path: string;
  kind: FileChangeKind;
  previousDigest: string | null;
  currentDigest: string | null;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedWebExecutionRequest;
    webApi?: WebExecutionApi;
    profileApi?: ExecutionApi;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useWebExecutionStore();
const profiles = ref<ExecutionProfilePayload[]>([]);
const localError = ref<string | null>(null);
const comparisonBaseId = ref<string | null>(null);
const comparisonTargetId = ref<string | null>(null);

const messages = {
  en: {
    eyebrow: "Web implementation · immutable source",
    title: "Web profiles and source revisions",
    intro:
      "Review the declared execution scope, language configuration, immutable lineage, file digests, and provenance before execution.",
    capabilityNotice:
      "Level D applies only to the exact validated profile version, runner image, fixture scope, and recorded evidence. Unvalidated configurations remain Level C.",
    refresh: "Refresh Web source state",
    profiles: "Web execution profiles",
    noProfiles: "No Web execution profile is registered.",
    capability: "Capability",
    targets: "Targets",
    evidence: "Validation evidence",
    noEvidence: "No Level D evidence is recorded.",
    ownerApproval: "Owner approval required",
    revisions: "Source revision history",
    noRevisions: "No Web source revision exists.",
    version: "Version",
    target: "Target",
    languages: "Languages",
    layout: "Layout",
    origin: "Origin",
    created: "Created",
    contentHash: "Revision hash",
    treeHash: "Source-tree hash",
    scopeHash: "Validation-scope hash",
    files: "Files",
    noFiles: "No file metadata is available.",
    path: "Path",
    bytes: "Bytes",
    mediaType: "Media type",
    digest: "SHA-256",
    provenance: "Provenance",
    noProvenance: "No provenance reference is available.",
    compare: "Compare immutable revisions",
    previous: "Previous revision",
    current: "Current revision",
    noComparison: "Select two different revisions to inspect a deterministic file diff.",
    noChanges: "The selected revisions contain the same path and content digests.",
    added: "Added",
    removed: "Removed",
    changed: "Changed",
    loading: "Loading Web source state…",
    loadError: "Web source state could not be loaded.",
    none: "None",
    yes: "Yes",
    no: "No",
  },
  it: {
    eyebrow: "Implementazione Web · sorgente immutabile",
    title: "Profili Web e revisioni del sorgente",
    intro:
      "Revisiona ambito di esecuzione dichiarato, configurazione dei linguaggi, lineage immutabile, digest dei file e provenienza prima dell'esecuzione.",
    capabilityNotice:
      "Il Level D vale solo per versione esatta del profilo, immagine runner, ambito dei fixture ed evidenze registrate. Le configurazioni non validate restano Level C.",
    refresh: "Aggiorna stato del sorgente Web",
    profiles: "Profili di esecuzione Web",
    noProfiles: "Nessun profilo di esecuzione Web è registrato.",
    capability: "Capacità",
    targets: "Target",
    evidence: "Evidenze di validazione",
    noEvidence: "Non è registrata alcuna evidenza Level D.",
    ownerApproval: "Approvazione del proprietario richiesta",
    revisions: "Cronologia revisioni del sorgente",
    noRevisions: "Non esiste alcuna revisione del sorgente Web.",
    version: "Versione",
    target: "Target",
    languages: "Linguaggi",
    layout: "Layout",
    origin: "Origine",
    created: "Creata",
    contentHash: "Hash revisione",
    treeHash: "Hash albero sorgente",
    scopeHash: "Hash ambito di validazione",
    files: "File",
    noFiles: "Non sono disponibili metadati dei file.",
    path: "Percorso",
    bytes: "Byte",
    mediaType: "Media type",
    digest: "SHA-256",
    provenance: "Provenienza",
    noProvenance: "Non è disponibile alcun riferimento di provenienza.",
    compare: "Confronta revisioni immutabili",
    previous: "Revisione precedente",
    current: "Revisione corrente",
    noComparison: "Seleziona due revisioni diverse per ispezionare un diff deterministico.",
    noChanges: "Le revisioni selezionate hanno gli stessi percorsi e digest dei contenuti.",
    added: "Aggiunto",
    removed: "Rimosso",
    changed: "Modificato",
    loading: "Caricamento stato del sorgente Web…",
    loadError: "Non è stato possibile caricare lo stato del sorgente Web.",
    none: "Nessuno",
    yes: "Sì",
    no: "No",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const webApi = computed(() => props.webApi ?? webExecutionApi);
const profileApi = computed(() => props.profileApi ?? executionApi);
const webProfiles = computed(() =>
  profiles.value.filter((profile) =>
    profile.supported_targets.some((target) => isWebTarget(target)),
  ),
);
const selectedRevision = computed(() =>
  store.sourceRevisions.find((revision) => revision.id === comparisonTargetId.value),
);
const selectedBaseRevision = computed(() =>
  store.sourceRevisions.find((revision) => revision.id === comparisonBaseId.value),
);
const fileChanges = computed(() =>
  compareFiles(selectedBaseRevision.value?.files ?? [], selectedRevision.value?.files ?? []),
);

function isWebTarget(value: string): value is WebExecutionTarget {
  return ["WEB_STATIC", "WEB_VUE", "WEB_NODE_EXPRESS", "WEB_PHP", "WEB_VUE_NODE"].includes(value);
}

function authorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }
  return auth.withAccessToken(apiClient, operation);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(props.locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function languageLabel(revision: WebSourceRevisionPayload): string {
  const configuration = revision.target_selection.language_configuration;
  return [configuration.frontend, configuration.backend].filter(Boolean).join(" + ");
}

function compareFiles(
  previous: WebSourceFilePayload[],
  current: WebSourceFilePayload[],
): FileChangeView[] {
  const previousByPath = new Map(previous.map((file) => [file.normalized_path, file]));
  const currentByPath = new Map(current.map((file) => [file.normalized_path, file]));
  const paths = [...new Set([...previousByPath.keys(), ...currentByPath.keys()])].sort();
  return paths.flatMap((path): FileChangeView[] => {
    const before = previousByPath.get(path);
    const after = currentByPath.get(path);
    if (before === undefined && after !== undefined) {
      return [{ path, kind: "ADDED", previousDigest: null, currentDigest: after.sha256_digest }];
    }
    if (before !== undefined && after === undefined) {
      return [{ path, kind: "REMOVED", previousDigest: before.sha256_digest, currentDigest: null }];
    }
    if (
      before !== undefined &&
      after !== undefined &&
      before.sha256_digest !== after.sha256_digest
    ) {
      return [
        {
          path,
          kind: "CHANGED",
          previousDigest: before.sha256_digest,
          currentDigest: after.sha256_digest,
        },
      ];
    }
    return [];
  });
}

function changeLabel(kind: FileChangeKind): string {
  return {
    ADDED: copy.value.added,
    REMOVED: copy.value.removed,
    CHANGED: copy.value.changed,
  }[kind];
}

async function load(): Promise<void> {
  localError.value = null;
  try {
    const loadedProfiles = await authorized((token) => profileApi.value.profiles(token));
    await store.loadProject(props.projectId, authorized, webApi.value);
    profiles.value = loadedProfiles;
    const revisions = store.sourceRevisions;
    comparisonBaseId.value = revisions.at(-2)?.id ?? revisions[0]?.id ?? null;
    comparisonTargetId.value = revisions.at(-1)?.id ?? null;
  } catch (error: unknown) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  }
}

watch(
  () => props.projectId,
  async () => {
    if (props.autoLoad) {
      await load();
    }
  },
);

onMounted(async () => {
  if (props.autoLoad) {
    await load();
  }
});
</script>

<template>
  <section class="grid gap-6" aria-labelledby="web-source-review-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-sky-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="web-source-review-title" class="m-0 text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">
        {{ copy.intro }}
      </p>
      <p class="m-0 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
        {{ copy.capabilityNotice }}
      </p>
      <button
        type="button"
        class="w-fit rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-700"
        :disabled="store.isBusy"
        @click="load"
      >
        {{ copy.refresh }}
      </button>
    </header>

    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ copy.loading }}
    </p>
    <p
      v-if="localError !== null || store.errorCode !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.errorCode ?? copy.loadError }}
    </p>

    <section class="grid gap-4" aria-labelledby="web-profile-list-title">
      <h3 id="web-profile-list-title" class="m-0 text-xl font-black text-slate-950">
        {{ copy.profiles }}
      </h3>
      <ul v-if="webProfiles.length > 0" class="grid gap-3 lg:grid-cols-2">
        <li
          v-for="profile in webProfiles"
          :key="`${profile.profile_id}:${profile.version}`"
          class="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <p class="m-0 font-black text-slate-950">{{ profile.name }}</p>
          <p class="m-0 text-sm text-slate-700">
            {{ copy.capability }}: <strong>{{ profile.capability_status }}</strong>
          </p>
          <p class="m-0 text-sm text-slate-700">
            {{ copy.targets }}: {{ profile.supported_targets.join(", ") }}
          </p>
          <p class="m-0 text-sm text-slate-700">
            {{ copy.ownerApproval }}:
            {{ profile.requires_owner_approval ? copy.yes : copy.no }}
          </p>
          <div>
            <p class="m-0 text-sm font-bold text-slate-900">{{ copy.evidence }}</p>
            <ul v-if="profile.validation_evidence_refs.length > 0" class="mt-1 grid gap-1 pl-5">
              <li v-for="reference in profile.validation_evidence_refs" :key="reference">
                <code class="text-xs break-all">{{ reference }}</code>
              </li>
            </ul>
            <p v-else class="m-0 text-sm text-slate-600">{{ copy.noEvidence }}</p>
          </div>
        </li>
      </ul>
      <p v-else class="m-0 text-slate-600">{{ copy.noProfiles }}</p>
    </section>

    <section class="grid gap-4" aria-labelledby="web-revision-list-title">
      <h3 id="web-revision-list-title" class="m-0 text-xl font-black text-slate-950">
        {{ copy.revisions }}
      </h3>
      <ol v-if="store.sourceRevisions.length > 0" class="grid gap-4">
        <li
          v-for="revision in store.sourceRevisions"
          :key="revision.id"
          class="grid gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <dl class="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <dt class="font-bold">{{ copy.version }}</dt>
              <dd class="m-0">{{ revision.version_number }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.target }}</dt>
              <dd class="m-0">{{ revision.target_selection.target }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.languages }}</dt>
              <dd class="m-0">{{ languageLabel(revision) || copy.none }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.layout }}</dt>
              <dd class="m-0">{{ revision.target_selection.layout }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.origin }}</dt>
              <dd class="m-0">{{ revision.origin }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.created }}</dt>
              <dd class="m-0">{{ formatDate(revision.created_at) }}</dd>
            </div>
          </dl>
          <dl class="grid gap-2 text-xs">
            <div>
              <dt class="font-bold">{{ copy.contentHash }}</dt>
              <dd class="m-0 break-all">
                <code>{{ revision.content_hash }}</code>
              </dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.treeHash }}</dt>
              <dd class="m-0 break-all">
                <code>{{ revision.source_tree_hash }}</code>
              </dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.scopeHash }}</dt>
              <dd class="m-0 break-all">
                <code>{{ revision.validation_scope_hash }}</code>
              </dd>
            </div>
          </dl>

          <div class="overflow-x-auto">
            <table
              v-if="revision.files.length > 0"
              class="w-full border-collapse text-left text-sm"
            >
              <caption class="pb-2 text-left font-black text-slate-950">
                {{
                  copy.files
                }}
              </caption>
              <thead>
                <tr>
                  <th class="border-b p-2">{{ copy.path }}</th>
                  <th class="border-b p-2">{{ copy.bytes }}</th>
                  <th class="border-b p-2">{{ copy.mediaType }}</th>
                  <th class="border-b p-2">{{ copy.digest }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in revision.files" :key="file.normalized_path">
                  <th scope="row" class="border-b p-2 font-semibold">{{ file.normalized_path }}</th>
                  <td class="border-b p-2">{{ file.size_bytes }}</td>
                  <td class="border-b p-2">{{ file.media_type }}</td>
                  <td class="border-b p-2">
                    <code class="text-xs break-all">{{ file.sha256_digest }}</code>
                  </td>
                </tr>
              </tbody>
            </table>
            <p v-else class="m-0 text-slate-600">{{ copy.noFiles }}</p>
          </div>

          <div>
            <p class="m-0 font-black text-slate-950">{{ copy.provenance }}</p>
            <ul
              v-if="revision.provenance_references.length > 0"
              class="mt-2 grid gap-2 pl-5 text-sm"
            >
              <li
                v-for="reference in revision.provenance_references"
                :key="`${reference.kind}:${reference.reference_id}:${reference.version_number}`"
              >
                {{ reference.kind }} · {{ reference.reference_id }} · v{{
                  reference.version_number
                }}
                ·
                <code class="text-xs break-all">{{ reference.content_hash }}</code>
              </li>
            </ul>
            <p v-else class="m-0 text-slate-600">{{ copy.noProvenance }}</p>
          </div>
        </li>
      </ol>
      <p v-else class="m-0 text-slate-600">{{ copy.noRevisions }}</p>
    </section>

    <section class="grid gap-4" aria-labelledby="web-revision-comparison-title">
      <h3 id="web-revision-comparison-title" class="m-0 text-xl font-black text-slate-950">
        {{ copy.compare }}
      </h3>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="grid gap-1 font-bold text-slate-900">
          {{ copy.previous }}
          <select
            v-model="comparisonBaseId"
            class="rounded-lg border border-slate-300 bg-white p-2"
          >
            <option :value="null">{{ copy.none }}</option>
            <option
              v-for="revision in store.sourceRevisions"
              :key="`base:${revision.id}`"
              :value="revision.id"
            >
              v{{ revision.version_number }} · {{ revision.content_hash.slice(0, 12) }}
            </option>
          </select>
        </label>
        <label class="grid gap-1 font-bold text-slate-900">
          {{ copy.current }}
          <select
            v-model="comparisonTargetId"
            class="rounded-lg border border-slate-300 bg-white p-2"
          >
            <option :value="null">{{ copy.none }}</option>
            <option
              v-for="revision in store.sourceRevisions"
              :key="`target:${revision.id}`"
              :value="revision.id"
            >
              v{{ revision.version_number }} · {{ revision.content_hash.slice(0, 12) }}
            </option>
          </select>
        </label>
      </div>
      <p
        v-if="
          selectedBaseRevision === undefined ||
          selectedRevision === undefined ||
          selectedBaseRevision.id === selectedRevision.id
        "
        class="m-0 text-slate-600"
      >
        {{ copy.noComparison }}
      </p>
      <p v-else-if="fileChanges.length === 0" class="m-0 text-slate-600">{{ copy.noChanges }}</p>
      <ul v-else class="grid gap-2">
        <li
          v-for="change in fileChanges"
          :key="change.path"
          class="rounded-lg border border-slate-200 bg-white p-3"
        >
          <p class="m-0 font-bold text-slate-950">
            {{ changeLabel(change.kind) }} · {{ change.path }}
          </p>
          <code class="mt-1 block text-xs break-all"
            >{{ change.previousDigest ?? copy.none }} →
            {{ change.currentDigest ?? copy.none }}</code
          >
        </li>
      </ul>
    </section>
  </section>
</template>
