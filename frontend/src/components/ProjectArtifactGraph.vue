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

const stages: ArtifactGraphStage[] = ["CONTEXT", "REQUIREMENTS", "DESIGN"];

const messages = {
  en: {
    eyebrow: "Artifact and provenance management",
    title: "Cross-stage artifact graph",
    intro:
      "Inspect exact governed stage roots and trace relationships from user context and requirements through the chosen design.",
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
    notAvailable: "Not available",
    filter: "Relationship stage filter",
    allStages: "All stages",
    context: "Brief, Perspectives and User Twin",
    requirementsStage: "Definition",
    designStage: "Design & Evaluation",
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
      "Ispeziona le radici esatte delle fasi governate e le relazioni di tracciabilità dal contesto utente e dai requisiti fino al design scelto.",
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
    notAvailable: "Non disponibile",
    filter: "Filtro della fase per le relazioni",
    allStages: "Tutte le fasi",
    context: "Brief, Prospettive e User Twin",
    requirementsStage: "Definizione",
    designStage: "Design e valutazione",
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
  <section class="grid gap-6 text-on-night" data-testid="project-artifact-graph">
    <header class="grid gap-2">
      <p class="font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h3 class="text-xl leading-tight font-semibold tracking-block">{{ copy.title }}</h3>
      <p class="text-[15px] leading-normal text-on-night-2">{{ copy.intro }}</p>
    </header>

    <p
      class="rounded-field border border-night-line bg-night-raised px-4 py-3 text-sm leading-normal text-on-night-2"
    >
      {{ copy.methodology }}
    </p>

    <p v-if="store.isBusy" class="text-sm text-on-night-2" aria-live="polite">
      {{ copy.loading }}
    </p>

    <p
      v-if="localError !== null || store.error !== null"
      class="rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm font-semibold text-fail-on-night"
      role="alert"
    >
      {{ localError ?? store.error?.message ?? copy.loadError }}
    </p>

    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        class="inline-flex min-h-11 items-center justify-center rounded-pill border border-on-night/32 bg-on-night/5 px-5 text-sm font-semibold text-on-night transition-colors duration-150 hover:bg-on-night hover:text-ink disabled:cursor-not-allowed disabled:border-night-line disabled:bg-transparent disabled:text-on-night-3"
        :disabled="store.isBusy"
        @click="load"
      >
        {{ copy.refresh }}
      </button>
      <button
        type="button"
        class="inline-flex min-h-11 items-center justify-center rounded-pill bg-on-night px-5 text-sm font-semibold text-ink transition-colors duration-150 hover:bg-petrol-on-night-2 disabled:cursor-not-allowed disabled:bg-night-hover disabled:text-on-night-3"
        :disabled="graph === null || store.isBusy"
        @click="exportGraph"
      >
        {{ copy.export }}
      </button>
    </div>

    <p v-if="graph === null" class="text-[15px] text-on-night-2">{{ copy.unavailable }}</p>

    <template v-else>
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="rounded-tile border border-night-line bg-night-raised p-4">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.nodes }}
          </p>
          <p
            class="mt-2 font-display text-4xl leading-none font-extralight tracking-numeral text-on-night"
          >
            {{ store.nodeCount }}
          </p>
        </div>
        <div class="rounded-tile border border-night-line bg-night-raised p-4">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.links }}
          </p>
          <p
            class="mt-2 font-display text-4xl leading-none font-extralight tracking-numeral text-on-night"
          >
            {{ store.linkCount }}
          </p>
        </div>
        <div class="rounded-tile border border-night-line bg-night-raised p-4 sm:col-span-2">
          <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ copy.hash }}
          </p>
          <code class="mt-2 block font-mono text-xs leading-[1.6] break-all text-on-night-2">
            {{ graph.content_hash }}
          </code>
        </div>
      </div>

      <section class="grid gap-3 rounded-tile border border-night-line p-5">
        <h4 class="text-base font-semibold">{{ copy.exactRoots }}</h4>
        <dl class="grid gap-3 text-sm">
          <div>
            <dt class="font-semibold text-on-night">{{ copy.requirements }}</dt>
            <dd class="mt-1 font-mono text-xs leading-[1.6] break-all text-on-night-2">
              {{ exactReferenceLabel(graph.requirements_reference) }}
            </dd>
          </div>
          <div>
            <dt class="font-semibold text-on-night">{{ copy.design }}</dt>
            <dd class="mt-1 font-mono text-xs leading-[1.6] break-all text-on-night-2">
              {{ exactReferenceLabel(graph.design_reference) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="grid gap-4" :aria-label="copy.stagesLabel">
        <article
          v-for="stage in stages"
          :key="stage"
          class="grid gap-4 rounded-tile border border-night-line p-5"
        >
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h4 class="text-base font-semibold">{{ stageLabel(stage) }}</h4>
            <span
              class="inline-flex min-h-[26px] items-center rounded-pill border border-petrol-on-night bg-petrol-on-night/16 px-2.5 text-xs font-medium text-petrol-on-night-2"
            >
              {{ graph.stage_counts[stage] }}
            </span>
          </div>
          <ul class="grid gap-3 sm:grid-cols-2">
            <li
              v-for="node in nodesByStage[stage]"
              :key="referenceKey(node.reference)"
              class="grid content-start gap-2 rounded-field border border-night-line bg-night-raised p-4"
            >
              <p class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
                {{ node.display_code }}
              </p>
              <h5 class="text-sm font-semibold break-words">{{ node.title }}</h5>
              <dl class="grid gap-1 text-xs text-on-night-2">
                <div>
                  <dt class="inline font-semibold text-on-night">{{ copy.nodeKind }}:</dt>
                  <dd class="inline break-all">{{ node.reference.kind }}</dd>
                </div>
                <div v-if="node.reference.version_number !== null">
                  <dt class="inline font-semibold text-on-night">{{ copy.version }}:</dt>
                  <dd class="inline">{{ node.reference.version_number }}</dd>
                </div>
                <div>
                  <dt class="inline font-semibold text-on-night">{{ copy.outgoing }}:</dt>
                  <dd class="inline">{{ outgoingCount(node.reference) }}</dd>
                </div>
                <div>
                  <dt class="inline font-semibold text-on-night">{{ copy.incoming }}:</dt>
                  <dd class="inline">{{ incomingCount(node.reference) }}</dd>
                </div>
              </dl>
            </li>
          </ul>
        </article>
      </section>

      <section class="grid gap-4" aria-labelledby="artifact-relationships-title">
        <div class="flex flex-wrap items-end justify-between gap-4">
          <h4 id="artifact-relationships-title" class="text-base font-semibold">
            {{ copy.relationships }}
          </h4>
          <label class="grid gap-2 text-sm font-semibold">
            {{ copy.filter }}
            <select
              v-model="stageFilter"
              class="min-h-11 rounded-control border border-night-line-strong bg-night-panel px-3 py-2 font-normal text-on-night"
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
          class="overflow-x-auto rounded-tile border border-night-line"
        >
          <table class="w-full min-w-[36rem] border-collapse text-left text-sm">
            <thead class="bg-night-raised text-on-night">
              <tr>
                <th class="px-4 py-3 font-semibold" scope="col">{{ copy.relationship }}</th>
                <th class="px-4 py-3 font-semibold" scope="col">{{ copy.source }}</th>
                <th class="px-4 py-3 font-semibold" scope="col">{{ copy.target }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="link in visibleLinks"
                :key="`${link.kind}:${referenceKey(link.source)}:${referenceKey(link.target)}`"
                class="border-t border-night-line"
              >
                <th class="px-4 py-3 font-mono text-xs font-medium text-on-night" scope="row">
                  {{ link.kind }}
                </th>
                <td class="px-4 py-3 text-on-night-2">{{ nodeLabel(link.source) }}</td>
                <td class="px-4 py-3 text-on-night-2">{{ nodeLabel(link.target) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-[15px] text-on-night-2">{{ copy.noRelationships }}</p>
      </section>
    </template>
  </section>
</template>
