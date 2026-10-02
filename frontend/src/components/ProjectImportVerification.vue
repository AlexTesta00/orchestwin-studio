<script setup lang="ts">
import { computed } from "vue";
import type { ProjectImportPayload } from "../types/projectImports";

const props = defineProps<{ result: ProjectImportPayload; locale: "en" | "it" }>();
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
        unknown: "Some historical links are unavailable.",
        details: "Limit details",
      },
);

function limitText(code: string): string {
  return code === "LEARNED_PROJECTION_NOT_RESTORED" || code === "LEGACY_FEEDBACK_CONTEXT_MISSING"
    ? copy.value[code]
    : copy.value.unknown;
}
</script>

<template>
  <section
    class="mt-3 grid max-w-[720px] min-w-0 gap-2 rounded-field border border-current/20 p-3 text-sm [overflow-wrap:anywhere]"
    data-testid="project-import-verification"
  >
    <p class="m-0" data-testid="project-import-why-verified">
      {{ result.why_verified === true ? copy.verified : copy.unavailable }}
    </p>
    <ul
      v-if="result.import_limits?.length"
      class="m-0 grid list-disc gap-1 pl-5"
      data-testid="project-import-limits"
    >
      <li v-for="limit in result.import_limits" :key="limit">{{ limitText(limit) }}</li>
    </ul>
    <p v-if="result.approval_required.length > 0" class="m-0">{{ copy.approvals }}</p>
    <details v-if="result.import_limits?.length" class="text-xs">
      <summary class="flex min-h-11 cursor-pointer items-center">{{ copy.details }}</summary>
      <p class="m-0 font-mono break-all">{{ result.import_limits.join(" · ") }}</p>
    </details>
  </section>
</template>
