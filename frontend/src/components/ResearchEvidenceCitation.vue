<script setup lang="ts">
import type { EvidenceCitationPayload } from "../types/researchEvidence";
import { researchEvidenceCopy } from "./researchEvidenceCopy";

withDefaults(defineProps<{ citation: EvidenceCitationPayload; locale?: "it" | "en" }>(), {
  locale: "en",
});
</script>

<template>
  <figure
    class="m-0 grid gap-2 rounded-field border border-night-line bg-night-panel p-3"
    data-testid="evidence-citation"
  >
    <figcaption class="text-xs font-semibold text-on-night-3">
      {{ researchEvidenceCopy[locale].quote }} · {{ researchEvidenceCopy[locale].lines }}
      {{ citation.start_line }}–{{ citation.end_line }}
    </figcaption>
    <blockquote
      class="m-0 text-sm leading-normal wrap-anywhere whitespace-pre-wrap text-on-night"
      data-testid="evidence-quote"
    >
      {{ citation.quote }}
    </blockquote>
    <details class="text-xs text-on-night-3">
      <summary class="min-h-11 cursor-pointer py-3">
        {{ researchEvidenceCopy[locale].details }}
      </summary>
      <dl class="m-0 grid gap-2">
        <div>
          <dt>{{ researchEvidenceCopy[locale].version }}</dt>
          <dd class="m-0">{{ citation.source_version }}</dd>
        </div>
        <div>
          <dt>{{ researchEvidenceCopy[locale].hash }}</dt>
          <dd class="m-0 font-mono break-all">{{ citation.content_hash }}</dd>
        </div>
        <div>
          <dt>{{ researchEvidenceCopy[locale].sourceRef }}</dt>
          <dd class="m-0 font-mono break-all">
            {{ citation.source_id }} · [{{ citation.start }}, {{ citation.end }})
          </dd>
        </div>
      </dl>
    </details>
  </figure>
</template>
