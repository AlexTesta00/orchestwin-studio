<script setup lang="ts">
import { computed } from "vue";
import type { ProjectImportOriginPayload, ProjectImportPayload } from "../types/projectImports";

const props = defineProps<{
  result?: ProjectImportPayload | undefined;
  origin?: ProjectImportOriginPayload | undefined;
  locale: "en" | "it";
}>();
const limits = computed(() => [
  ...new Set([...(props.result?.import_limits ?? []), ...(props.origin?.import_limits ?? [])]),
]);
const omissions = computed(() => [
  ...new Map(
    [...(props.result?.omitted_sections ?? []), ...(props.origin?.omitted_sections ?? [])].map(
      (item) => [JSON.stringify(item), item],
    ),
  ).values(),
]);
const copy = computed(() =>
  props.locale === "it"
    ? {
        verified:
          "La catena è stata ricalcolata dai dati importati e verificata con quella esportata.",
        unavailable: "La verifica della catena ricalcolata non è disponibile per questa cartella.",
        approvals: "L'import non approva le sezioni.",
        LEARNED_PROJECTION_NOT_RESTORED:
          "La proiezione dei twin appresa dal feedback non è stata ripristinata.",
        LEGACY_FEEDBACK_CONTEXT_MISSING:
          "Questa cartella precedente non conserva il contesto completo dei feedback storici.",
        FEEDBACK_CONTEXT_NOT_RESTORED:
          "Il contesto completo delle valutazioni storiche non è stato ripristinato.",
        HYPOTHESIS_HISTORY_PARTIAL:
          "Lo storico delle ipotesi è parziale. Le versioni mancanti non sono state sostituite con quelle correnti.",
        omitted: "Dati omessi",
        unknown: "Alcuni collegamenti storici non sono disponibili.",
        details: "Dettagli dei limiti",
      }
    : {
        verified:
          "The chain was recalculated from the imported data and verified against the exported chain.",
        unavailable: "Verification of the recalculated chain is unavailable for this folder.",
        approvals: "The import does not approve the sections.",
        LEARNED_PROJECTION_NOT_RESTORED:
          "The twin projection learned from feedback was not restored.",
        LEGACY_FEEDBACK_CONTEXT_MISSING:
          "This older folder does not preserve the full context of historical feedback.",
        FEEDBACK_CONTEXT_NOT_RESTORED:
          "The full context of historical evaluations was not restored.",
        HYPOTHESIS_HISTORY_PARTIAL:
          "Hypothesis history is partial. Missing versions were not replaced with current ones.",
        omitted: "Omitted data",
        unknown: "Some historical links are unavailable.",
        details: "Limit details",
      },
);

function limitText(code: string): string {
  return code === "LEARNED_PROJECTION_NOT_RESTORED" ||
    code === "LEGACY_FEEDBACK_CONTEXT_MISSING" ||
    code === "FEEDBACK_CONTEXT_NOT_RESTORED" ||
    code === "HYPOTHESIS_HISTORY_PARTIAL"
    ? copy.value[code]
    : copy.value.unknown;
}
</script>

<template>
  <section
    class="mt-3 grid max-w-[720px] min-w-0 gap-2 rounded-field border border-current/20 p-3 text-sm [overflow-wrap:anywhere]"
    data-testid="project-import-verification"
  >
    <p v-if="result" class="m-0" data-testid="project-import-why-verified">
      {{ result.why_verified === true ? copy.verified : copy.unavailable }}
    </p>
    <ul
      v-if="limits.length"
      class="m-0 grid list-disc gap-1 pl-5"
      data-testid="project-import-limits"
    >
      <li v-for="limit in limits" :key="limit">{{ limitText(limit) }}</li>
    </ul>
    <div v-if="omissions.length" class="grid gap-2" data-testid="project-import-omissions">
      <strong>{{ copy.omitted }} · {{ omissions.length }}</strong>
      <ul class="m-0 grid list-disc gap-1 pl-5">
        <li v-for="(item, index) in omissions" :key="index">{{ limitText(item.reason) }}</li>
      </ul>
    </div>
    <p v-if="result && result.approval_required.length > 0" class="m-0">{{ copy.approvals }}</p>
    <details v-if="limits.length || omissions.length" class="text-xs">
      <summary class="flex min-h-11 cursor-pointer items-center">{{ copy.details }}</summary>
      <p v-if="limits.length" class="m-0 font-mono break-all">{{ limits.join(" · ") }}</p>
      <pre
        v-if="omissions.length"
        class="m-0 mt-2 font-mono [overflow-wrap:anywhere] whitespace-pre-wrap"
        >{{ JSON.stringify(omissions, null, 2) }}</pre>
    </details>
  </section>
</template>
