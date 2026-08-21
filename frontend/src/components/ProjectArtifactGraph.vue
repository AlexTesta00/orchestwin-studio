<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { apiClient } from "@/api/client";
import { artifactGraphApi, type ArtifactGraphApi } from "../api/artifacts";
import { type AuthorizedRequest, useArtifactGraphStore } from "../stores/artifacts";
import { useAuthStore } from "../stores/auth";
import type {
  ArtifactGraphNodePayload,
  ArtifactGraphReferencePayload,
  ArtifactGraphStage,
  VersionedArtifactReferencePayload,
} from "../types/artifacts";

type Locale = "en" | "it";
type StageFilter = "ALL" | ArtifactGraphStage;

export type ArtifactGraphExportSaver = (blob: Blob, filename: string) => void;

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    autoLoad?: boolean;
    authorize?: AuthorizedRequest;
    api?: ArtifactGraphApi;
    saveExport?: ArtifactGraphExportSaver;
  }>(),
  {
    locale: "en",
    autoLoad: true,
  },
);

const auth = useAuthStore();
const store = useArtifactGraphStore();
const localError = ref<string | null>(null);
const stageFilter = ref<StageFilter>("ALL");

const stages: ArtifactGraphStage[] = [
  "CONTEXT",
  "REQUIREMENTS",
  "DESIGN",
  "ARCHITECTURE",
  "TESTING",
];

const messages = {
  en: {
    eyebrow: "Artifact and provenance management",
    title: "Cross-stage artifact graph",
    intro:
      "Inspect exact governed stage roots and trace relationships from user context and requirements through design, architecture, and planned tests.",
    methodology:
      "The graph derives relationships from immutable artifacts. It preserves synthetic critique origin and traceability, but a graph link is not empirical evidence or proof that a requirement has passed execution.",
    loading: "Loading the current artifact graph…",
    loadError: "The artifact graph could not be loaded.",
    unavailable: "The graph becomes available after a Requirements Specification exists.",
    refresh: "Refresh graph",
    export: "Export JSON graph",
    nodes: "Nodes",
    links: "Relationships",
    hash: "Graph content hash",
    exactRoots: "Exact governed stage roots",
    stagesLabel: "Artifact graph stages",
    requirements: "Requirements",
    design: "Design",
    architecture: "Architecture",
    notAvailable: "Not available",
    filter: "Relationship stage filter",
    allStages: "All stages",
    context: "Context",
    requirementsStage: "Requirements",
    designStage: "Design",
    architectureStage: "Architecture",
    testing: "Testing",
    nodeKind: "Artifact kind",
    version: "Exact version",
    outgoing: "Outgoing",
    incoming: "Incoming",
    relationships: "Accessible relationship table",
    relationship: "Relationship",
    source: "Source",
    target: "Target",
    noRelationships: "No relationships match the selected stage.",
    downloadError: "The graph export could not be downloaded.",
  },
  it: {
    eyebrow: "Gestione artefatti e provenienza",
    title: "Grafo degli artefatti tra le fasi",
    intro:
      "Ispeziona le radici esatte delle fasi governate e le relazioni di tracciabilità dal contesto utente e dai requisiti fino a design, architettura e test pianificati.",
    methodology:
      "Il grafo deriva le relazioni dagli artefatti immutabili. Mantiene origine e tracciabilità delle critiche sintetiche, ma un collegamento non è evidenza empirica né prova che un requisito abbia superato l'esecuzione.",
    loading: "Caricamento del grafo corrente degli artefatti…",
    loadError: "Non è stato possibile caricare il grafo degli artefatti.",
    unavailable:
      "Il grafo diventa disponibile dopo la creazione di una Requirements Specification.",
    refresh: "Aggiorna grafo",
    export: "Esporta grafo JSON",
    nodes: "Nodi",
    links: "Relazioni",
    hash: "Hash del contenuto del grafo",
    exactRoots: "Radici esatte delle fasi governate",
    stagesLabel: "Fasi del grafo degli artefatti",
    requirements: "Requisiti",
    design: "Design",
    architecture: "Architettura",
    notAvailable: "Non disponibile",
    filter: "Filtro della fase per le relazioni",
    allStages: "Tutte le fasi",
    context: "Contesto",
    requirementsStage: "Requisiti",
    designStage: "Design",
    architectureStage: "Architettura",
    testing: "Testing",
    nodeKind: "Tipo di artefatto",
    version: "Versione esatta",
    outgoing: "In uscita",
    incoming: "In ingresso",
    relationships: "Tabella accessibile delle relazioni",
    relationship: "Relazione",
    source: "Sorgente",
    target: "Destinazione",
    noRelationships: "Nessuna relazione corrisponde alla fase selezionata.",
    downloadError: "Non è stato possibile scaricare l'esportazione del grafo.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? artifactGraphApi);
const graph = computed(() => store.graph);
const nodeLookup = computed(() => {
  const values = new Map<string, ArtifactGraphNodePayload>();

  for (const node of graph.value?.nodes ?? []) {
    values.set(referenceKey(node.reference), node);
  }

  return values;
});
const nodesByStage = computed(
  () =>
    Object.fromEntries(
      stages.map((stage) => [
        stage,
        (graph.value?.nodes ?? []).filter((node) => node.stage === stage),
      ]),
    ) as Record<ArtifactGraphStage, ArtifactGraphNodePayload[]>,
);
const visibleLinks = computed(() => {
  const links = graph.value?.links ?? [];

  if (stageFilter.value === "ALL") {
    return links;
  }

  return links.filter((link) => {
    const source = nodeLookup.value.get(referenceKey(link.source));
    const target = nodeLookup.value.get(referenceKey(link.target));

    return source?.stage === stageFilter.value || target?.stage === stageFilter.value;
  });
});

function referenceKey(reference: ArtifactGraphReferencePayload): string {
  return [
    reference.kind,
    reference.artifact_id,
    reference.version_number ?? "",
    reference.content_hash ?? "",
  ].join(":");
}

function stageLabel(stage: ArtifactGraphStage): string {
  const labels: Record<ArtifactGraphStage, string> = {
    CONTEXT: copy.value.context,
    REQUIREMENTS: copy.value.requirementsStage,
    DESIGN: copy.value.designStage,
    ARCHITECTURE: copy.value.architectureStage,
    TESTING: copy.value.testing,
  };

  return labels[stage];
}

function nodeLabel(reference: ArtifactGraphReferencePayload): string {
  const node = nodeLookup.value.get(referenceKey(reference));

  return node === undefined
    ? `${reference.kind} · ${reference.artifact_id}`
    : `${node.display_code} · ${node.title}`;
}

function exactReferenceLabel(reference: VersionedArtifactReferencePayload | null): string {
  if (reference === null) {
    return copy.value.notAvailable;
  }

  return `${reference.artifact_id} · v${reference.version_number} · ${reference.content_hash}`;
}

function outgoingCount(reference: ArtifactGraphReferencePayload): number {
  return (
    graph.value?.links.filter((link) => referenceKey(link.source) === referenceKey(reference))
      .length ?? 0
  );
}

function incomingCount(reference: ArtifactGraphReferencePayload): number {
  return (
    graph.value?.links.filter((link) => referenceKey(link.target) === referenceKey(reference))
      .length ?? 0
  );
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  if (props.authorize !== undefined) {
    return props.authorize(operation);
  }

  return auth.withAccessToken(apiClient, operation);
}

async function load(): Promise<void> {
  if (props.projectId.trim().length === 0) {
    return;
  }

  localError.value = null;

  try {
    await store.load(props.projectId, authorizedRequest, api.value);
  } catch (error) {
    localError.value = error instanceof Error ? error.message : copy.value.loadError;
  }
}

function saveBlob(blob: Blob, filename: string): void {
  if (props.saveExport !== undefined) {
    props.saveExport(blob, filename);
    return;
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function exportGraph(): Promise<void> {
  localError.value = null;

  try {
    const blob = await store.exportGraph(props.projectId, authorizedRequest, api.value);
    saveBlob(blob, `orchestwin-${props.projectId}-artifact-graph.json`);
  } catch (error) {
    localError.value = error instanceof Error ? error.message : copy.value.downloadError;
  }
}

watch(
  () => props.projectId,
  async () => {
    stageFilter.value = "ALL";

    if (props.autoLoad) {
      await load();
    }
  },
  { immediate: true },
);
</script>

<template>
  <section
    class="grid gap-6 rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7"
    data-testid="project-artifact-graph"
  >
    <header class="grid gap-2">
      <p class="m-0 text-xs font-black tracking-widest text-cyan-700 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h2 class="text-2xl font-black text-slate-950">{{ copy.title }}</h2>
      <p class="m-0 max-w-4xl text-slate-600">{{ copy.intro }}</p>
    </header>

    <p class="m-0 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-950">
      {{ copy.methodology }}
    </p>

    <p v-if="store.isBusy" class="m-0 text-slate-700" aria-live="polite">
      {{ copy.loading }}
    </p>

    <p
      v-if="localError !== null || store.error !== null"
      class="m-0 rounded-xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800"
      role="alert"
    >
      {{ localError ?? store.error?.message ?? copy.loadError }}
    </p>

    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        class="rounded-xl border border-slate-300 bg-white px-4 py-2 font-black text-slate-800 hover:bg-slate-100"
        :disabled="store.isBusy"
        @click="load"
      >
        {{ copy.refresh }}
      </button>
      <button
        type="button"
        class="rounded-xl bg-cyan-700 px-4 py-2 font-black text-white hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="graph === null || store.isBusy"
        @click="exportGraph"
      >
        {{ copy.export }}
      </button>
    </div>

    <p v-if="graph === null" class="m-0 text-slate-600">{{ copy.unavailable }}</p>

    <template v-else>
      <div class="grid gap-4 sm:grid-cols-3">
        <div class="rounded-2xl border border-cyan-200 bg-cyan-50 p-4">
          <p class="m-0 text-sm font-bold text-cyan-800">{{ copy.nodes }}</p>
          <p class="mt-1 text-3xl font-black text-cyan-950">{{ store.nodeCount }}</p>
        </div>
        <div class="rounded-2xl border border-violet-200 bg-violet-50 p-4">
          <p class="m-0 text-sm font-bold text-violet-800">{{ copy.links }}</p>
          <p class="mt-1 text-3xl font-black text-violet-950">{{ store.linkCount }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <p class="m-0 text-sm font-bold text-slate-700">{{ copy.hash }}</p>
          <code class="mt-2 block text-xs break-all text-slate-600">
            {{ graph.content_hash }}
          </code>
        </div>
      </div>

      <section class="grid gap-3 rounded-2xl border border-slate-200 p-5">
        <h3 class="text-xl font-black text-slate-950">{{ copy.exactRoots }}</h3>
        <dl class="grid gap-3 text-sm">
          <div>
            <dt class="font-black text-slate-900">{{ copy.requirements }}</dt>
            <dd class="m-0 break-all text-slate-600">
              {{ exactReferenceLabel(graph.requirements_reference) }}
            </dd>
          </div>
          <div>
            <dt class="font-black text-slate-900">{{ copy.design }}</dt>
            <dd class="m-0 break-all text-slate-600">
              {{ exactReferenceLabel(graph.design_reference) }}
            </dd>
          </div>
          <div>
            <dt class="font-black text-slate-900">{{ copy.architecture }}</dt>
            <dd class="m-0 break-all text-slate-600">
              {{ exactReferenceLabel(graph.architecture_reference) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="grid gap-5" :aria-label="copy.stagesLabel">
        <article
          v-for="stage in stages"
          :key="stage"
          class="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-5"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h3 class="text-xl font-black text-slate-950">{{ stageLabel(stage) }}</h3>
            <span class="rounded-full bg-slate-900 px-3 py-1 text-xs font-black text-white">
              {{ graph.stage_counts[stage] }}
            </span>
          </div>
          <ul class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            <li
              v-for="node in nodesByStage[stage]"
              :key="referenceKey(node.reference)"
              class="grid gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <p class="m-0 text-xs font-black tracking-wide text-slate-500 uppercase">
                {{ node.display_code }}
              </p>
              <h4 class="font-black text-slate-950">{{ node.title }}</h4>
              <dl class="grid gap-1 text-xs text-slate-600">
                <div>
                  <dt class="inline font-bold">{{ copy.nodeKind }}:</dt>
                  <dd class="m-0 inline">{{ node.reference.kind }}</dd>
                </div>
                <div v-if="node.reference.version_number !== null">
                  <dt class="inline font-bold">{{ copy.version }}:</dt>
                  <dd class="m-0 inline">{{ node.reference.version_number }}</dd>
                </div>
                <div>
                  <dt class="inline font-bold">{{ copy.outgoing }}:</dt>
                  <dd class="m-0 inline">{{ outgoingCount(node.reference) }}</dd>
                </div>
                <div>
                  <dt class="inline font-bold">{{ copy.incoming }}:</dt>
                  <dd class="m-0 inline">{{ incomingCount(node.reference) }}</dd>
                </div>
              </dl>
            </li>
          </ul>
        </article>
      </section>

      <section class="grid gap-4" aria-labelledby="artifact-relationships-title">
        <div class="flex flex-wrap items-end justify-between gap-4">
          <h3 id="artifact-relationships-title" class="text-xl font-black text-slate-950">
            {{ copy.relationships }}
          </h3>
          <label class="grid gap-2 text-sm font-bold text-slate-900">
            {{ copy.filter }}
            <select
              v-model="stageFilter"
              class="rounded-xl border border-slate-300 bg-white px-3 py-2 font-normal"
            >
              <option value="ALL">{{ copy.allStages }}</option>
              <option v-for="stage in stages" :key="stage" :value="stage">
                {{ stageLabel(stage) }}
              </option>
            </select>
          </label>
        </div>

        <div
          v-if="visibleLinks.length > 0"
          class="overflow-x-auto rounded-2xl border border-slate-200"
        >
          <table class="w-full min-w-4xl border-collapse text-left text-sm">
            <thead class="bg-slate-100 text-slate-900">
              <tr>
                <th class="px-4 py-3" scope="col">{{ copy.relationship }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.source }}</th>
                <th class="px-4 py-3" scope="col">{{ copy.target }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="link in visibleLinks"
                :key="`${link.kind}:${referenceKey(link.source)}:${referenceKey(link.target)}`"
                class="border-t border-slate-200"
              >
                <th class="px-4 py-3 font-black text-slate-900" scope="row">
                  {{ link.kind }}
                </th>
                <td class="px-4 py-3 text-slate-700">{{ nodeLabel(link.source) }}</td>
                <td class="px-4 py-3 text-slate-700">{{ nodeLabel(link.target) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="m-0 text-slate-600">{{ copy.noRelationships }}</p>
      </section>
    </template>
  </section>
</template>
