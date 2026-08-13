<script setup lang="ts">
import { computed } from "vue";

import type { ProfileObservationPayload } from "../types/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    observation: ProfileObservationPayload;
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

const copy = computed(() => {
  if (props.locale === "it") {
    return {
      provenance: "Provenienza",
      noEvidence: "Nessun riferimento di evidenza.",
      version: "Versione",
      locator: "Posizione",
      hash: "Hash",
      rationale: "Motivazione",
    };
  }

  return {
    provenance: "Provenance",
    noEvidence: "No evidence references.",
    version: "Version",
    locator: "Locator",
    hash: "Hash",
    rationale: "Rationale",
  };
});
</script>

<template>
  <details
    class="rounded-lg border border-slate-200 bg-slate-50"
    data-testid="provenance-inspector"
  >
    <summary class="cursor-pointer px-3 py-2 text-sm font-semibold text-slate-700">
      {{ copy.provenance }}
      ({{ observation.provenance.length }})
    </summary>

    <div class="space-y-3 border-t border-slate-200 px-3 py-3">
      <p v-if="observation.provenance.length === 0" class="text-sm text-slate-600">
        {{ copy.noEvidence }}
      </p>

      <article
        v-for="(reference, index) in observation.provenance"
        :key="`${reference.source_kind}-${reference.source_id}-${index}`"
        class="rounded-md border border-slate-200 bg-white p-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-xs font-semibold tracking-wide text-slate-700 uppercase">
            {{ reference.source_kind }}
          </strong>

          <code class="text-xs break-all text-slate-500">
            {{ reference.source_id }}
          </code>
        </div>

        <p v-if="reference.summary" class="mt-2 text-sm text-slate-700">
          {{ reference.summary }}
        </p>

        <dl class="mt-2 grid gap-1 text-xs text-slate-500">
          <div v-if="reference.source_version !== null" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.version }}
            </dt>

            <dd>
              {{ reference.source_version }}
            </dd>
          </div>

          <div v-if="reference.locator" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.locator }}
            </dt>

            <dd class="break-all">
              {{ reference.locator }}
            </dd>
          </div>

          <div v-if="reference.content_hash" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.hash }}
            </dt>

            <dd class="font-mono break-all">
              {{ reference.content_hash }}
            </dd>
          </div>
        </dl>
      </article>

      <div v-if="observation.rationale" class="rounded-md border border-slate-200 bg-white p-3">
        <strong class="text-xs font-semibold tracking-wide text-slate-600 uppercase">
          {{ copy.rationale }}
        </strong>

        <p class="mt-1 text-sm text-slate-700">
          {{ observation.rationale }}
        </p>
      </div>
    </div>
  </details>
</template>
