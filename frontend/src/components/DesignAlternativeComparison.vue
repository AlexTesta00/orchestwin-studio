<script setup lang="ts">
import { computed, useId } from "vue";

import type { DesignAlternativePayload, SyntheticDesignCritiquePayload } from "../types/design";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    alternatives: readonly DesignAlternativePayload[];
    critiques: readonly SyntheticDesignCritiquePayload[];
    recommendedAlternativeId?: string | null;
    selectedAlternativeId?: string | null;
    disabled?: boolean;
    locale?: Locale;
  }>(),
  {
    recommendedAlternativeId: null,
    selectedAlternativeId: null,
    disabled: false,
    locale: "en",
  },
);

const emit = defineEmits<{
  select: [alternativeId: string];
}>();

const messages = {
  en: {
    title: "Design alternatives",
    recommended: "Provider recommendation",
    selected: "Owner selection",
    approach: "Approach",
    rationale: "Rationale",
    advantages: "Advantages",
    tradeOffs: "Trade-offs",
    informationArchitecture: "Information architecture",
    accessibility: "Accessibility considerations",
    security: "Security considerations",
    workflows: "Workflows",
    critiques: "Synthetic User Twin critiques",
    confidence: "Self-assessed confidence",
    provenance: "Provenance",
    concerns: "Concerns",
    questions: "Questions for human validation",
    select: "Select {title}",
    methodology:
      "User Twin critiques are simulated feedback and design hypotheses. They are not empirical evidence of real-user behavior.",
  },
  it: {
    title: "Alternative di design",
    recommended: "Raccomandazione del provider",
    selected: "Selezione del proprietario",
    approach: "Approccio",
    rationale: "Motivazione",
    advantages: "Vantaggi",
    tradeOffs: "Compromessi",
    informationArchitecture: "Architettura dell'informazione",
    accessibility: "Considerazioni di accessibilità",
    security: "Considerazioni di sicurezza",
    workflows: "Flussi",
    critiques: "Critiche sintetiche dei User Twin",
    confidence: "Confidenza auto-valutata",
    provenance: "Provenienza",
    concerns: "Criticità",
    questions: "Domande per la validazione umana",
    select: "Seleziona {title}",
    methodology:
      "Le critiche dei User Twin sono feedback simulato e ipotesi progettuali. Non sono evidenza empirica del comportamento di utenti reali.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const groupName = `design-alternative-${useId()}`;

function critiquesFor(alternativeId: string): SyntheticDesignCritiquePayload[] {
  return props.critiques.filter((critique) => critique.design_alternative_id === alternativeId);
}

function confidenceLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function choose(alternativeId: string): void {
  if (!props.disabled) {
    emit("select", alternativeId);
  }
}
</script>

<template>
  <section class="grid gap-5" aria-labelledby="design-alternatives-title">
    <h3 id="design-alternatives-title" class="text-xl font-semibold text-ink">
      {{ copy.title }}
    </h3>

    <p class="m-0 rounded-panel border border-line-strong bg-surface-2 p-4 text-sm text-warn">
      {{ copy.methodology }}
    </p>

    <div class="grid gap-5 xl:grid-cols-2">
      <article
        v-for="alternative in alternatives"
        :key="alternative.id"
        :data-test="`alternative-${alternative.code}`"
        class="grid content-start gap-5 rounded-card border bg-white p-5 shadow-sm"
        :class="
          alternative.id === selectedAlternativeId
            ? 'border-action ring-2 ring-action-soft-line'
            : 'border-line'
        "
      >
        <header class="grid gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-full bg-surface-3 px-3 py-1 text-xs font-semibold text-ink-2">
              {{ alternative.code }}
            </span>
            <span
              v-if="alternative.id === recommendedAlternativeId"
              class="rounded-full bg-action-soft px-3 py-1 text-xs font-semibold text-ink-2"
            >
              {{ copy.recommended }}
            </span>
            <span
              v-if="alternative.id === selectedAlternativeId"
              class="rounded-full bg-action-soft px-3 py-1 text-xs font-semibold text-action"
            >
              {{ copy.selected }}
            </span>
          </div>

          <label class="flex cursor-pointer items-start gap-3">
            <input
              :name="groupName"
              type="radio"
              class="mt-1 size-4 accent-action"
              :value="alternative.id"
              :checked="alternative.id === selectedAlternativeId"
              :disabled="disabled"
              :aria-label="copy.select.replace('{title}', alternative.title)"
              :data-alternative-id="alternative.id"
              @change="choose(alternative.id)"
            />
            <span>
              <span class="block text-lg font-semibold text-ink">
                {{ alternative.title }}
              </span>
              <span class="mt-1 block text-sm text-ink-2">
                {{ alternative.summary }}
              </span>
            </span>
          </label>
        </header>

        <dl class="grid gap-3 text-sm">
          <div>
            <dt class="font-semibold text-ink">{{ copy.approach }}</dt>
            <dd class="m-0 mt-1 text-ink-2">{{ alternative.approach }}</dd>
          </div>
          <div>
            <dt class="font-semibold text-ink">{{ copy.rationale }}</dt>
            <dd class="m-0 mt-1 text-ink-2">{{ alternative.rationale }}</dd>
          </div>
        </dl>

        <div class="grid gap-4 md:grid-cols-2">
          <section>
            <h4 class="font-semibold text-ink">{{ copy.advantages }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
              <li v-for="item in alternative.advantages" :key="item">{{ item }}</li>
            </ul>
          </section>
          <section>
            <h4 class="font-semibold text-ink">{{ copy.tradeOffs }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
              <li v-for="item in alternative.trade_offs" :key="item">{{ item }}</li>
            </ul>
          </section>
        </div>

        <section>
          <h4 class="font-semibold text-ink">{{ copy.informationArchitecture }}</h4>
          <ol class="mt-2 flex flex-wrap gap-2 text-sm text-ink-2">
            <li
              v-for="(item, index) in alternative.information_architecture"
              :key="item"
              class="rounded-control border border-line bg-surface-2 px-3 py-2"
            >
              {{ index + 1 }}. {{ item }}
            </li>
          </ol>
        </section>

        <div class="grid gap-4 md:grid-cols-2">
          <section>
            <h4 class="font-semibold text-ink">{{ copy.accessibility }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
              <li v-for="item in alternative.accessibility_considerations" :key="item">
                {{ item }}
              </li>
            </ul>
          </section>
          <section>
            <h4 class="font-semibold text-ink">{{ copy.security }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
              <li v-for="item in alternative.security_considerations" :key="item">
                {{ item }}
              </li>
            </ul>
          </section>
        </div>

        <section v-if="alternative.workflows.length > 0">
          <h4 class="font-semibold text-ink">{{ copy.workflows }}</h4>
          <ol class="mt-2 grid gap-3">
            <li
              v-for="workflow in alternative.workflows"
              :key="workflow.id"
              class="rounded-panel border border-line p-3"
            >
              <p class="m-0 font-bold text-ink">{{ workflow.code }} · {{ workflow.title }}</p>
              <ol class="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
                <li v-for="step in workflow.steps" :key="step">{{ step }}</li>
              </ol>
            </li>
          </ol>
        </section>

        <section v-if="critiquesFor(alternative.id).length > 0" class="grid gap-3">
          <h4 class="font-semibold text-ink">{{ copy.critiques }}</h4>
          <article
            v-for="critique in critiquesFor(alternative.id)"
            :key="critique.id"
            class="grid gap-3 rounded-panel border border-line-strong bg-surface-2 p-4"
          >
            <header class="flex flex-wrap items-center justify-between gap-2">
              <p class="m-0 font-semibold text-warn">
                {{ critique.code }} · {{ critique.user_twin_reference.name }}
              </p>
              <span class="rounded-full bg-surface-2 px-3 py-1 text-xs font-semibold text-warn">
                {{ critique.epistemic_status }} · {{ critique.human_validation }}
              </span>
            </header>

            <p class="m-0 text-sm text-warn">{{ critique.rationale }}</p>
            <p class="m-0 text-xs font-bold text-warn">
              {{ copy.confidence }}: {{ confidenceLabel(critique.confidence) }}
            </p>

            <section v-if="critique.concerns.length > 0">
              <h5 class="text-sm font-semibold text-warn">{{ copy.concerns }}</h5>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-warn">
                <li v-for="item in critique.concerns" :key="item">{{ item }}</li>
              </ul>
            </section>

            <section v-if="critique.questions.length > 0">
              <h5 class="text-sm font-semibold text-warn">{{ copy.questions }}</h5>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-warn">
                <li v-for="item in critique.questions" :key="item">{{ item }}</li>
              </ul>
            </section>

            <details>
              <summary class="cursor-pointer text-sm font-semibold text-warn">
                {{ copy.provenance }}
              </summary>
              <ul class="mt-2 grid gap-2 text-xs text-warn">
                <li
                  v-for="reference in critique.provenance"
                  :key="`${reference.source_kind}:${reference.source_id}:${reference.locator}`"
                  class="rounded-control bg-white/70 p-2 break-all"
                >
                  {{ reference.source_kind }} · {{ reference.source_id }}
                  <span v-if="reference.locator !== null"> · {{ reference.locator }}</span>
                </li>
              </ul>
            </details>
          </article>
        </section>
      </article>
    </div>
  </section>
</template>
