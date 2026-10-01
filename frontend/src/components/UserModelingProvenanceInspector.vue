<script setup lang="ts">
import { computed } from "vue";

import { useSurface, type SurfaceContext } from "./UiSurface.vue";
import UserModelingEpistemicBadge from "./UserModelingEpistemicBadge.vue";
import { claimText, readableClaim } from "./twinRepresentation";
import type { ProfileObservationPayload, ReadableClaim } from "../types/userModeling";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    observation: ProfileObservationPayload | ReadableClaim;
    summaryLabel?: string | undefined;
    testId?: string;
    locale?: Locale;
    surface?: SurfaceContext | undefined;
  }>(),
  {
    locale: "en",
    surface: undefined,
    summaryLabel: undefined,
    testId: "provenance-inspector",
  },
);

const context = useSurface(() => props.surface);

const palettes = {
  light: {
    box: "border-line bg-surface-2",
    summary: "text-ink-2 hover:text-ink",
    divider: "border-line",
    card: "border-line bg-white",
    strong: "text-ink-2",
    text: "text-ink-2",
    muted: "text-ink-3",
  },
  night: {
    box: "border-night-line bg-night-raised",
    summary: "text-on-night-2 hover:text-on-night",
    divider: "border-night-line",
    card: "border-night-line bg-night-panel",
    strong: "text-on-night",
    text: "text-on-night-2",
    muted: "text-on-night-3",
  },
};

const palette = computed(() => palettes[context.value]);
const claim = computed(() =>
  "display_status" in props.observation
    ? props.observation
    : readableClaim(props.observation, props.observation.observation_key),
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
    class="rounded-field border"
    :class="palette.box"
    :data-surface-context="context"
    :data-testid="testId"
  >
    <summary
      class="flex min-h-11 cursor-pointer items-center px-3 text-sm font-semibold transition-colors duration-150"
      :class="palette.summary"
    >
      {{ summaryLabel ?? copy.provenance }}
      ({{ observation.provenance.length }})
    </summary>

    <div class="grid gap-3 border-t px-3 py-3" :class="palette.divider">
      <p class="m-0 text-sm" :class="palette.text">{{ claimText(claim, locale) }}</p>
      <UserModelingEpistemicBadge
        :status="claim.display_status"
        :show-details="false"
        :locale="locale"
      />
      <p v-if="observation.provenance.length === 0" class="m-0 text-sm" :class="palette.text">
        {{ copy.noEvidence }}
      </p>

      <article
        v-for="(reference, index) in observation.provenance"
        :key="`${reference.source_kind}-${reference.source_id}-${index}`"
        class="grid gap-2 rounded-field border p-3"
        :class="palette.card"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong class="text-xs font-semibold tracking-wide uppercase" :class="palette.strong">
            {{ reference.source_kind }}
          </strong>

          <code class="font-mono text-xs break-all" :class="palette.muted">
            {{ reference.source_id }}
          </code>
        </div>

        <p v-if="reference.summary" class="m-0 text-sm" :class="palette.text">
          {{ reference.summary }}
        </p>

        <dl class="m-0 grid gap-1 text-xs" :class="palette.muted">
          <div v-if="reference.source_version !== null" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.version }}
            </dt>

            <dd class="m-0">
              {{ reference.source_version }}
            </dd>
          </div>

          <div v-if="reference.locator" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.locator }}
            </dt>

            <dd class="m-0 break-all">
              {{ reference.locator }}
            </dd>
          </div>

          <div v-if="reference.content_hash" class="flex gap-2">
            <dt class="font-medium">
              {{ copy.hash }}
            </dt>

            <dd class="m-0 font-mono break-all">
              {{ reference.content_hash }}
            </dd>
          </div>
        </dl>
      </article>

      <div
        v-if="observation.rationale"
        class="grid gap-1 rounded-field border p-3"
        :class="palette.card"
      >
        <strong class="text-xs font-semibold tracking-wide uppercase" :class="palette.strong">
          {{ copy.rationale }}
        </strong>

        <p class="m-0 text-sm" :class="palette.text">
          {{ observation.rationale }}
        </p>
      </div>
    </div>
  </details>
</template>
