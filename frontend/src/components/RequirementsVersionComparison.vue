<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import { useSurface } from "./UiSurface.vue";
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
    artifact: "Item",
    kind: "Kind",
    status: "Change",
    empty: "At least two versions are required for comparison.",
    added: "Added",
    removed: "Removed",
    changed: "Changed",
    unchanged: "Unchanged",
    kinds: {
      NEED: "Need",
      JOURNEY: "Journey",
      REQUIREMENT: "Requirement",
      USER_STORY: "User story",
      ACCEPTANCE_CRITERION: "Acceptance criterion",
      SCENARIO: "Usage scenario",
      RISK: "Risk",
      DEFINITION_OF_DONE: "Definition of done",
    },
  },
  it: {
    title: "Confronto versioni",
    base: "Versione base",
    target: "Versione di destinazione",
    artifact: "Elemento",
    kind: "Tipo",
    status: "Modifica",
    empty: "Per il confronto sono necessarie almeno due versioni.",
    added: "Aggiunto",
    removed: "Rimosso",
    changed: "Modificato",
    unchanged: "Invariato",
    kinds: {
      NEED: "Bisogno",
      JOURNEY: "Journey",
      REQUIREMENT: "Requisito",
      USER_STORY: "Storia dell'utente",
      ACCEPTANCE_CRITERION: "Criterio di accettazione",
      SCENARIO: "Scenario d'uso",
      RISK: "Rischio",
      DEFINITION_OF_DONE: "Quando il lavoro è finito",
    },
  },
} as const;

const palettes = {
  light: {
    title: "text-ink",
    muted: "text-ink-3",
    field: "border-field bg-surface text-ink",
    line: "border-line",
    cell: "text-ink-2",
    code: "text-ink",
    changed: "text-action",
  },
  night: {
    title: "text-on-night",
    muted: "text-on-night-3",
    field: "border-night-line-strong bg-night-panel text-on-night [color-scheme:dark]",
    line: "border-night-line",
    cell: "text-on-night-2",
    code: "text-on-night",
    changed: "text-petrol-on-night-2",
  },
};

const titleId = `requirements-version-comparison-${useId()}`;
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
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
    ...(specification.journeys ?? []).map((value) => ({
      kind: "JOURNEY" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
    ...(specification.needs ?? []).map((value) => ({
      kind: "NEED" as const,
      id: value.id,
      code: value.code,
      snapshot: value,
    })),
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
  <section class="grid gap-3">
    <h2 :id="titleId" :class="['m-0 text-sm font-semibold', palette.title]">
      {{ copy.title }}
    </h2>

    <p v-if="orderedVersions.length < 2" :class="['m-0 text-[13px]', palette.muted]">
      {{ copy.empty }}
    </p>

    <template v-else>
      <div class="grid gap-3 sm:grid-cols-2">
        <label :class="['grid gap-1 text-[13px] font-medium', palette.muted]">
          {{ copy.base }}
          <select
            v-model="baseVersionNumber"
            :class="['min-h-11 rounded-field border px-3 text-sm', palette.field]"
          >
            <option
              v-for="version in orderedVersions"
              :key="`base:${version.id}`"
              :value="version.version_number"
            >
              {{ version.version_number }}
            </option>
          </select>
        </label>
        <label :class="['grid gap-1 text-[13px] font-medium', palette.muted]">
          {{ copy.target }}
          <select
            v-model="targetVersionNumber"
            :class="['min-h-11 rounded-field border px-3 text-sm', palette.field]"
          >
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

      <div class="overflow-x-auto" role="region" tabindex="0" :aria-labelledby="titleId">
        <table
          class="w-full border-collapse text-left text-[13px]"
          data-testid="version-comparison"
        >
          <thead>
            <tr :class="['border-b', palette.line, palette.muted]">
              <th scope="col" class="px-2 py-2 font-medium">{{ copy.artifact }}</th>
              <th scope="col" class="px-2 py-2 font-medium">{{ copy.kind }}</th>
              <th scope="col" class="px-2 py-2 font-medium">{{ copy.status }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in rows"
              :key="`${row.kind}:${row.code}`"
              :class="['border-b', palette.line]"
            >
              <td :class="['px-2 py-2 font-mono text-xs', palette.code]">{{ row.code }}</td>
              <td :class="['px-2 py-2', palette.cell]">{{ copy.kinds[row.kind] }}</td>
              <td
                :class="[
                  'px-2 py-2 font-semibold',
                  row.status === 'UNCHANGED' ? palette.cell : palette.changed,
                ]"
              >
                {{ statusLabel(row.status) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>
