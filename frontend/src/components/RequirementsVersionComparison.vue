<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type {
  RequirementsArtifactKind,
  RequirementsSpecificationVersionPayload,
} from "../types/requirements";

type Locale = "en" | "it";
type ComparisonStatus = "ADDED" | "REMOVED" | "CHANGED" | "UNCHANGED";

interface ComparableArtifact {
  kind: RequirementsArtifactKind;
  id: string;
  code: string;
  snapshot: unknown;
}

interface ComparisonRow {
  kind: RequirementsArtifactKind;
  code: string;
  status: ComparisonStatus;
}

const props = withDefaults(
  defineProps<{
    versions: RequirementsSpecificationVersionPayload[];
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    title: "Version comparison",
    base: "Base version",
    target: "Target version",
    artifact: "Artifact",
    kind: "Kind",
    status: "Change",
    empty: "At least two versions are required for comparison.",
    added: "Added",
    removed: "Removed",
    changed: "Changed",
    unchanged: "Unchanged",
  },
  it: {
    title: "Confronto versioni",
    base: "Versione base",
    target: "Versione di destinazione",
    artifact: "Artefatto",
    kind: "Tipo",
    status: "Modifica",
    empty: "Per il confronto sono necessarie almeno due versioni.",
    added: "Aggiunto",
    removed: "Rimosso",
    changed: "Modificato",
    unchanged: "Invariato",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const baseVersionNumber = ref<number | null>(null);
const targetVersionNumber = ref<number | null>(null);

const orderedVersions = computed(() =>
  [...props.versions].sort((left, right) => left.version_number - right.version_number),
);

watch(
  orderedVersions,
  (versions) => {
    const target = versions.at(-1);
    const base = versions.at(-2);
    baseVersionNumber.value = base?.version_number ?? target?.version_number ?? null;
    targetVersionNumber.value = target?.version_number ?? null;
  },
  {
    immediate: true,
  },
);

const baseVersion = computed(() =>
  orderedVersions.value.find((version) => version.version_number === baseVersionNumber.value),
);
const targetVersion = computed(() =>
  orderedVersions.value.find((version) => version.version_number === targetVersionNumber.value),
);
const rows = computed<ComparisonRow[]>(() => {
  if (baseVersion.value === undefined || targetVersion.value === undefined) {
    return [];
  }

  const before = new Map(
    artifacts(baseVersion.value).map((artifact) => [`${artifact.kind}:${artifact.id}`, artifact]),
  );
  const after = new Map(
    artifacts(targetVersion.value).map((artifact) => [`${artifact.kind}:${artifact.id}`, artifact]),
  );
  const keys = [...new Set([...before.keys(), ...after.keys()])].sort();

  return keys.map((key) => {
    const previous = before.get(key);
    const current = after.get(key);

    if (previous === undefined && current !== undefined) {
      return {
        kind: current.kind,
        code: current.code,
        status: "ADDED",
      };
    }

    if (previous !== undefined && current === undefined) {
      return {
        kind: previous.kind,
        code: previous.code,
        status: "REMOVED",
      };
    }

    if (previous === undefined || current === undefined) {
      throw new Error("Requirements comparison row has no artifact");
    }

    return {
      kind: current.kind,
      code: current.code,
      status:
        JSON.stringify(previous.snapshot) === JSON.stringify(current.snapshot)
          ? "UNCHANGED"
          : "CHANGED",
    };
  });
});

function artifacts(version: RequirementsSpecificationVersionPayload): ComparableArtifact[] {
  const specification = version.specification;

  return [
    ...specification.requirements.map((value) => ({
      kind: "REQUIREMENT" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...specification.user_stories.map((value) => ({
      kind: "USER_STORY" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...specification.acceptance_criteria.map((value) => ({
      kind: "ACCEPTANCE_CRITERION" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...specification.scenarios.map((value) => ({
      kind: "SCENARIO" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...specification.risks.map((value) => ({
      kind: "RISK" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...specification.definition_of_done.map((value) => ({
      kind: "DEFINITION_OF_DONE" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
  ];
}

function statusLabel(status: ComparisonStatus): string {
  switch (status) {
    case "ADDED":
      return copy.value.added;
    case "REMOVED":
      return copy.value.removed;
    case "CHANGED":
      return copy.value.changed;
    case "UNCHANGED":
      return copy.value.unchanged;
  }
}
</script>

<template>
  <section
    class="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    aria-labelledby="requirements-version-comparison-title"
  >
    <h3 id="requirements-version-comparison-title" class="text-xl font-black text-slate-950">
      {{ copy.title }}
    </h3>

    <p v-if="orderedVersions.length < 2" class="m-0 text-sm text-slate-600">
      {{ copy.empty }}
    </p>

    <template v-else>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="grid gap-1 text-sm font-bold text-slate-700">
          {{ copy.base }}
          <select v-model="baseVersionNumber" class="rounded-lg border px-3 py-2">
            <option
              v-for="version in orderedVersions"
              :key="`base:${version.id}`"
              :value="version.version_number"
            >
              {{ version.version_number }}
            </option>
          </select>
        </label>
        <label class="grid gap-1 text-sm font-bold text-slate-700">
          {{ copy.target }}
          <select v-model="targetVersionNumber" class="rounded-lg border px-3 py-2">
            <option
              v-for="version in orderedVersions"
              :key="`target:${version.id}`"
              :value="version.version_number"
            >
              {{ version.version_number }}
            </option>
          </select>
        </label>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full border-collapse text-left text-sm" data-testid="version-comparison">
          <thead>
            <tr class="border-b text-xs tracking-wide text-slate-500 uppercase">
              <th class="px-2 py-2">{{ copy.artifact }}</th>
              <th class="px-2 py-2">{{ copy.kind }}</th>
              <th class="px-2 py-2">{{ copy.status }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="`${row.kind}:${row.code}`" class="border-b">
              <td class="px-2 py-2 font-black text-slate-900">{{ row.code }}</td>
              <td class="px-2 py-2 text-slate-600">{{ row.kind }}</td>
              <td class="px-2 py-2 font-bold">{{ statusLabel(row.status) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
