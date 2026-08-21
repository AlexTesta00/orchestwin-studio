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
    <h3 id="design-alternatives-title" class="text-xl font-black text-slate-950">
      {{ copy.title }}
    </h3>

    <p class="m-0 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
      {{ copy.methodology }}
    </p>

    <div class="grid gap-5 xl:grid-cols-2">
      <article
        v-for="alternative in alternatives"
        :key="alternative.id"
        :data-test="`alternative-${alternative.code}`"
        class="grid content-start gap-5 rounded-2xl border bg-white p-5 shadow-sm"
        :class="
          alternative.id === selectedAlternativeId
            ? 'border-indigo-500 ring-2 ring-indigo-100'
            : 'border-slate-200'
        "
      >
        <header class="grid gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-700">
              {{ alternative.code }}
            </span>
            <span
              v-if="alternative.id === recommendedAlternativeId"
              class="rounded-full bg-sky-100 px-3 py-1 text-xs font-black text-sky-800"
            >
              {{ copy.recommended }}
            </span>
            <span
              v-if="alternative.id === selectedAlternativeId"
              class="rounded-full bg-indigo-100 px-3 py-1 text-xs font-black text-indigo-800"
            >
              {{ copy.selected }}
            </span>
          </div>

          <label class="flex cursor-pointer items-start gap-3">
            <input
              :name="groupName"
              type="radio"
              class="mt-1 size-4 accent-indigo-600"
              :value="alternative.id"
              :checked="alternative.id === selectedAlternativeId"
              :disabled="disabled"
              :aria-label="copy.select.replace('{title}', alternative.title)"
              :data-alternative-id="alternative.id"
              @change="choose(alternative.id)"
            />
            <span>
              <span class="block text-lg font-black text-slate-950">
                {{ alternative.title }}
              </span>
              <span class="mt-1 block text-sm text-slate-600">
                {{ alternative.summary }}
              </span>
            </span>
          </label>
        </header>

        <dl class="grid gap-3 text-sm">
          <div>
            <dt class="font-black text-slate-900">{{ copy.approach }}</dt>
            <dd class="m-0 mt-1 text-slate-700">{{ alternative.approach }}</dd>
          </div>
          <div>
            <dt class="font-black text-slate-900">{{ copy.rationale }}</dt>
            <dd class="m-0 mt-1 text-slate-700">{{ alternative.rationale }}</dd>
          </div>
        </dl>

        <div class="grid gap-4 md:grid-cols-2">
          <section>
            <h4 class="font-black text-slate-900">{{ copy.advantages }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              <li v-for="item in alternative.advantages" :key="item">{{ item }}</li>
            </ul>
          </section>
          <section>
            <h4 class="font-black text-slate-900">{{ copy.tradeOffs }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              <li v-for="item in alternative.trade_offs" :key="item">{{ item }}</li>
            </ul>
          </section>
        </div>

        <section>
          <h4 class="font-black text-slate-900">{{ copy.informationArchitecture }}</h4>
          <ol class="mt-2 flex flex-wrap gap-2 text-sm text-slate-700">
            <li
              v-for="(item, index) in alternative.information_architecture"
              :key="item"
              class="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
            >
              {{ index + 1 }}. {{ item }}
            </li>
          </ol>
        </section>

        <div class="grid gap-4 md:grid-cols-2">
          <section>
            <h4 class="font-black text-slate-900">{{ copy.accessibility }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              <li v-for="item in alternative.accessibility_considerations" :key="item">
                {{ item }}
              </li>
            </ul>
          </section>
          <section>
            <h4 class="font-black text-slate-900">{{ copy.security }}</h4>
            <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
              <li v-for="item in alternative.security_considerations" :key="item">
                {{ item }}
              </li>
            </ul>
          </section>
        </div>

        <section v-if="alternative.workflows.length > 0">
          <h4 class="font-black text-slate-900">{{ copy.workflows }}</h4>
          <ol class="mt-2 grid gap-3">
            <li
              v-for="workflow in alternative.workflows"
              :key="workflow.id"
              class="rounded-xl border border-slate-200 p-3"
            >
              <p class="m-0 font-bold text-slate-900">{{ workflow.code }} · {{ workflow.title }}</p>
              <ol class="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">
                <li v-for="step in workflow.steps" :key="step">{{ step }}</li>
              </ol>
            </li>
          </ol>
        </section>

        <section v-if="critiquesFor(alternative.id).length > 0" class="grid gap-3">
          <h4 class="font-black text-slate-900">{{ copy.critiques }}</h4>
          <article
            v-for="critique in critiquesFor(alternative.id)"
            :key="critique.id"
            class="grid gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4"
          >
            <header class="flex flex-wrap items-center justify-between gap-2">
              <p class="m-0 font-black text-amber-950">
                {{ critique.code }} · {{ critique.user_twin_reference.name }}
              </p>
              <span class="rounded-full bg-amber-100 px-3 py-1 text-xs font-black text-amber-900">
                {{ critique.epistemic_status }} · {{ critique.human_validation }}
              </span>
            </header>

            <p class="m-0 text-sm text-amber-950">{{ critique.rationale }}</p>
            <p class="m-0 text-xs font-bold text-amber-900">
              {{ copy.confidence }}: {{ confidenceLabel(critique.confidence) }}
            </p>

            <section v-if="critique.concerns.length > 0">
              <h5 class="text-sm font-black text-amber-950">{{ copy.concerns }}</h5>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-amber-950">
                <li v-for="item in critique.concerns" :key="item">{{ item }}</li>
              </ul>
            </section>

            <section v-if="critique.questions.length > 0">
              <h5 class="text-sm font-black text-amber-950">{{ copy.questions }}</h5>
              <ul class="mt-1 list-disc space-y-1 pl-5 text-sm text-amber-950">
                <li v-for="item in critique.questions" :key="item">{{ item }}</li>
              </ul>
            </section>

            <details>
              <summary class="cursor-pointer text-sm font-black text-amber-950">
                {{ copy.provenance }}
              </summary>
              <ul class="mt-2 grid gap-2 text-xs text-amber-950">
                <li
                  v-for="reference in critique.provenance"
                  :key="`${reference.source_kind}:${reference.source_id}:${reference.locator}`"
                  class="rounded-lg bg-white/70 p-2 break-all"
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
