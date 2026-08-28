<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { jvmExecutionApi, type JvmExecutionApi } from "@/api/jvmExecution";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedJvmExecutionRequest, useJvmExecutionStore } from "@/stores/jvmExecution";
import type { JvmSourceFilePayload } from "@/types/jvmExecution";

type Locale = "en" | "it";
type ChangeKind = "ADDED" | "REMOVED" | "CHANGED";

interface FileChangeView {
  path: string;
  kind: ChangeKind;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedJvmExecutionRequest;
    api?: JvmExecutionApi;
  }>(),
  { locale: "en", autoLoad: true },
);

const auth = useAuthStore();
const store = useJvmExecutionStore();
const localError = ref<string | null>(null);
const baseRevisionId = ref<string | null>(null);
const targetRevisionId = ref<string | null>(null);

const messages = {
  en: {
    eyebrow: "JVM implementation · immutable source",
    title: "JVM profiles and source revisions",
    intro:
      "Review Java, Kotlin, and Scala scope, exact toolchains, immutable lineage, file digests, and provenance before execution.",
    honesty:
      "A profile remains Level C until complete validation evidence is bound to the exact profile, runner, toolchain, and fixture scope.",
    refresh: "Refresh JVM source state",
    profiles: "JVM execution profiles",
    noProfiles: "No JVM profile is registered.",
    capability: "Capability",
    language: "Language",
    buildSystem: "Build system",
    jdk: "JDK",
    evidence: "Validation evidence",
    noEvidence: "No Level D evidence is recorded.",
    revisions: "Source revision history",
    noRevisions: "No JVM source revision exists.",
    version: "Version",
    target: "Target",
    origin: "Origin",
    treeHash: "Source-tree hash",
    contentHash: "Revision hash",
    scopeHash: "Validation-scope hash",
    files: "Files",
    path: "Path",
    bytes: "Bytes",
    mediaType: "Media type",
    provenance: "Provenance",
    noProvenance: "No provenance reference is available.",
    compare: "Compare immutable revisions",
    base: "Base revision",
    current: "Current revision",
    noComparison: "Select two different revisions to inspect a deterministic file diff.",
    noChanges: "The selected revisions contain the same file digests.",
    added: "Added",
    removed: "Removed",
    changed: "Changed",
    loading: "Loading JVM source state…",
    loadError: "JVM source state could not be loaded.",
  },
  it: {
    eyebrow: "Implementazione JVM · sorgente immutabile",
    title: "Profili JVM e revisioni del sorgente",
    intro:
      "Revisiona ambito Java, Kotlin e Scala, toolchain esatte, lineage immutabile, digest dei file e provenienza prima dell'esecuzione.",
    honesty:
      "Un profilo resta Level C finché le evidenze complete non sono legate a profilo, runner, toolchain e ambito dei fixture esatti.",
    refresh: "Aggiorna stato del sorgente JVM",
    profiles: "Profili di esecuzione JVM",
    noProfiles: "Nessun profilo JVM è registrato.",
    capability: "Capacità",
    language: "Linguaggio",
    buildSystem: "Build system",
    jdk: "JDK",
    evidence: "Evidenze di validazione",
    noEvidence: "Non è registrata alcuna evidenza Level D.",
    revisions: "Cronologia revisioni del sorgente",
    noRevisions: "Non esiste alcuna revisione del sorgente JVM.",
    version: "Versione",
    target: "Target",
    origin: "Origine",
    treeHash: "Hash albero sorgente",
    contentHash: "Hash revisione",
    scopeHash: "Hash ambito di validazione",
    files: "File",
    path: "Percorso",
    bytes: "Byte",
    mediaType: "Media type",
    provenance: "Provenienza",
    noProvenance: "Non è disponibile alcun riferimento di provenienza.",
    compare: "Confronta revisioni immutabili",
    base: "Revisione base",
    current: "Revisione corrente",
    noComparison: "Seleziona due revisioni diverse per ispezionare un diff deterministico.",
    noChanges: "Le revisioni selezionate contengono gli stessi digest dei file.",
    added: "Aggiunto",
    removed: "Rimosso",
    changed: "Modificato",
    loading: "Caricamento stato del sorgente JVM…",
    loadError: "Non è stato possibile caricare lo stato del sorgente JVM.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const selectedBase = computed(() =>
  store.sourceRevisions.find((revision) => revision.id === baseRevisionId.value),
);
const selectedTarget = computed(() =>
  store.sourceRevisions.find((revision) => revision.id === targetRevisionId.value),
);
const fileChanges = computed(() =>
  compareFiles(selectedBase.value?.files ?? [], selectedTarget.value?.files ?? []),
);

function authorized<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize?.(operation) ?? auth.withAccessToken(apiClient, operation);
}

function compareFiles(
  previous: JvmSourceFilePayload[],
  current: JvmSourceFilePayload[],
): FileChangeView[] {
  const before = new Map(previous.map((file) => [file.normalized_path, file.sha256_digest]));
  const after = new Map(current.map((file) => [file.normalized_path, file.sha256_digest]));
  return [...new Set([...before.keys(), ...after.keys()])]
    .sort()
    .flatMap<FileChangeView>((path) => {
      if (!before.has(path)) return [{ path, kind: "ADDED" as const }];
      if (!after.has(path)) return [{ path, kind: "REMOVED" as const }];
      return before.get(path) === after.get(path) ? [] : [{ path, kind: "CHANGED" as const }];
    });
}

function changeLabel(kind: ChangeKind): string {
  return { ADDED: copy.value.added, REMOVED: copy.value.removed, CHANGED: copy.value.changed }[
    kind
  ];
}

async function load(): Promise<void> {
  localError.value = null;
  try {
    await store.loadProject(props.projectId, authorized, props.api ?? jvmExecutionApi);
    baseRevisionId.value = store.sourceRevisions.at(-2)?.id ?? store.sourceRevisions[0]?.id ?? null;
    targetRevisionId.value = store.sourceRevisions.at(-1)?.id ?? null;
  } catch (error: unknown) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  }
}

watch(
  () => props.projectId,
  async () => {
    if (props.autoLoad) await load();
  },
);
onMounted(async () => {
  if (props.autoLoad) await load();
});
</script>

<template>
  <section class="grid gap-6" aria-labelledby="jvm-source-review-title">
    <header class="grid gap-2">
      <p class="m-0 text-sm font-bold tracking-wide text-violet-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 id="jvm-source-review-title" class="m-0 text-2xl font-black text-slate-950">
        {{ copy.title }}
      </h2>
      <p class="m-0 max-w-4xl text-slate-700">{{ copy.intro }}</p>
      <p class="m-0 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
        {{ copy.honesty }}
      </p>
      <button
        type="button"
        class="w-fit rounded-lg border border-slate-300 bg-white px-4 py-2 font-bold"
        :disabled="store.isBusy"
        @click="load"
      >
        {{ copy.refresh }}
      </button>
    </header>

    <p v-if="store.isBusy" aria-live="polite">{{ copy.loading }}</p>
    <p
      v-if="localError !== null || store.errorCode !== null"
      class="rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.errorCode ?? copy.loadError }}
    </p>

    <section class="grid gap-3" aria-labelledby="jvm-profile-list-title">
      <h3 id="jvm-profile-list-title" class="text-xl font-black">{{ copy.profiles }}</h3>
      <ul v-if="store.profiles.length > 0" class="grid gap-3 lg:grid-cols-3">
        <li
          v-for="profile in store.profiles"
          :key="`${profile.profile_id}:${profile.profile_version}`"
          class="grid gap-2 rounded-xl border border-slate-200 p-4"
        >
          <strong>{{ profile.profile_id }} · {{ profile.profile_version }}</strong>
          <span>{{ copy.capability }}: {{ profile.capability_status }}</span>
          <span
            >{{ copy.language }}: {{ profile.language ?? profile.target }}
            {{ profile.language_version ?? "" }}</span
          >
          <span>{{ copy.buildSystem }}: {{ profile.build_system ?? "—" }}</span>
          <span>{{ copy.jdk }}: {{ profile.jdk_major ?? "—" }}</span>
          <div>
            <strong>{{ copy.evidence }}</strong>
            <ul v-if="(profile.validation_evidence_refs?.length ?? 0) > 0" class="pl-5">
              <li v-for="reference in profile.validation_evidence_refs" :key="reference">
                <code class="text-xs break-all">{{ reference }}</code>
              </li>
            </ul>
            <p v-else class="m-0 text-sm text-slate-600">{{ copy.noEvidence }}</p>
          </div>
        </li>
      </ul>
      <p v-else>{{ copy.noProfiles }}</p>
    </section>

    <section class="grid gap-3" aria-labelledby="jvm-revision-list-title">
      <h3 id="jvm-revision-list-title" class="text-xl font-black">{{ copy.revisions }}</h3>
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
              <dt class="font-bold">{{ copy.language }}</dt>
              <dd class="m-0">{{ revision.target_selection.language }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.buildSystem }}</dt>
              <dd class="m-0">{{ revision.target_selection.build_system }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.jdk }}</dt>
              <dd class="m-0">{{ revision.target_selection.jdk_major }}</dd>
            </div>
            <div>
              <dt class="font-bold">{{ copy.origin }}</dt>
              <dd class="m-0">{{ revision.origin }}</dd>
            </div>
          </dl>
          <p class="m-0 text-xs break-all">
            {{ copy.contentHash }}: <code>{{ revision.content_hash }}</code>
          </p>
          <p class="m-0 text-xs break-all">
            {{ copy.treeHash }}: <code>{{ revision.source_tree_hash }}</code>
          </p>
          <p class="m-0 text-xs break-all">
            {{ copy.scopeHash }}: <code>{{ revision.validation_scope_hash ?? "—" }}</code>
          </p>
          <div>
            <h4 class="font-black">{{ copy.files }}</h4>
            <table class="w-full text-left text-sm">
              <thead>
                <tr>
                  <th>{{ copy.path }}</th>
                  <th>{{ copy.bytes }}</th>
                  <th>{{ copy.mediaType }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in revision.files" :key="file.normalized_path">
                  <td>
                    <code>{{ file.normalized_path }}</code>
                  </td>
                  <td>{{ file.size_bytes }}</td>
                  <td>{{ file.media_type }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <h4 class="font-black">{{ copy.provenance }}</h4>
            <ul v-if="revision.provenance_references.length > 0" class="pl-5">
              <li
                v-for="item in revision.provenance_references"
                :key="`${item.kind}:${item.reference_id}:${item.version_number}`"
              >
                {{ item.kind }} · <code>{{ item.reference_id }}</code>
              </li>
            </ul>
            <p v-else>{{ copy.noProvenance }}</p>
          </div>
        </li>
      </ol>
      <p v-else>{{ copy.noRevisions }}</p>
    </section>

    <section class="grid gap-3" aria-labelledby="jvm-revision-compare-title">
      <h3 id="jvm-revision-compare-title" class="text-xl font-black">{{ copy.compare }}</h3>
      <div class="grid gap-3 sm:grid-cols-2">
        <label
          >{{ copy.base
          }}<select v-model="baseRevisionId" class="block w-full">
            <option
              v-for="revision in store.sourceRevisions"
              :key="revision.id"
              :value="revision.id"
            >
              {{ copy.version }} {{ revision.version_number }}
            </option>
          </select></label
        >
        <label
          >{{ copy.current
          }}<select v-model="targetRevisionId" class="block w-full">
            <option
              v-for="revision in store.sourceRevisions"
              :key="revision.id"
              :value="revision.id"
            >
              {{ copy.version }} {{ revision.version_number }}
            </option>
          </select></label
        >
      </div>
      <p
        v-if="
          baseRevisionId === targetRevisionId ||
          baseRevisionId === null ||
          targetRevisionId === null
        "
      >
        {{ copy.noComparison }}
      </p>
      <p v-else-if="fileChanges.length === 0">{{ copy.noChanges }}</p>
      <ul v-else class="grid gap-2">
        <li
          v-for="change in fileChanges"
          :key="`${change.kind}:${change.path}`"
          class="rounded-lg border border-slate-200 p-3"
        >
          <strong>{{ changeLabel(change.kind) }}</strong> · <code>{{ change.path }}</code>
        </li>
      </ul>
    </section>
  </section>
</template>
