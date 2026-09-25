<script setup lang="ts">
import { computed, useId } from "vue";

import DesignStyleTile from "./DesignStyleTile.vue";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import type { AuthorizedDesignLoopRequest } from "../stores/designLoop";
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
    projectId?: string | null;
    authorize?: AuthorizedDesignLoopRequest | undefined;
  }>(),
  {
    recommendedAlternativeId: null,
    selectedAlternativeId: null,
    disabled: false,
    locale: "en",
    projectId: null,
    authorize: undefined,
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
    details: "Alternative details",
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
    details: "Dettagli dell'alternativa",
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
    <div class="grid gap-1">
      <h3 id="design-alternatives-title" class="m-0 text-xl font-semibold tracking-block text-ink">
        {{ copy.title }}
      </h3>
      <p class="m-0 text-sm leading-6 text-ink-3">{{ copy.methodology }}</p>
    </div>

    <div class="grid gap-5 md:grid-cols-2">
      <article
        v-for="alternative in alternatives"
        :key="alternative.id"
        :data-test="`alternative-${alternative.code}`"
        class="grid content-start gap-4 rounded-card border bg-surface p-5 shadow-card"
        :class="alternative.id === selectedAlternativeId ? 'border-2 border-ok' : 'border-line'"
      >
        <header class="grid gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-mono text-[11px] tracking-wide text-ink-3 uppercase">
              {{ alternative.code }}
            </span>
            <span
              v-if="alternative.id === recommendedAlternativeId"
              class="inline-flex items-center rounded-pill border border-line bg-surface-3 px-2.5 py-1 text-xs font-semibold text-ink-2"
            >
              {{ copy.recommended }}
            </span>
            <span
              v-if="alternative.id === selectedAlternativeId"
              class="inline-flex items-center rounded-pill border border-ok-line bg-ok-bg px-2.5 py-1 text-xs font-semibold text-ok-dark"
            >
              {{ copy.selected }}
            </span>
          </div>

          <label class="flex cursor-pointer items-start gap-3">
            <input
              :name="groupName"
              type="radio"
              class="mt-1.5 size-4 accent-action"
              :value="alternative.id"
              :checked="alternative.id === selectedAlternativeId"
              :disabled="disabled"
              :aria-label="copy.select.replace('{title}', alternative.title)"
              :data-alternative-id="alternative.id"
              @change="choose(alternative.id)"
            />
            <span class="min-w-0">
              <span class="block text-[17px] font-semibold tracking-block text-ink">
                {{ alternative.title }}
              </span>
              <span class="mt-1 block text-[14.5px] leading-6 text-ink-2">
                {{ alternative.summary }}
              </span>
            </span>
          </label>
          <DesignStyleTile
            v-if="alternative.visual_language"
            :visual="alternative.visual_language"
            :locale="locale"
            compact
          />
        </header>

        <section v-if="critiquesFor(alternative.id).length > 0" class="grid gap-2">
          <h4 class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ copy.critiques }}
          </h4>
          <ul class="m-0 grid list-none gap-2 p-0">
            <li
              v-for="critique in critiquesFor(alternative.id)"
              :key="critique.id"
              class="text-sm leading-6 text-ink-2"
            >
              <strong class="font-semibold text-ink">{{
                critique.user_twin_reference.name
              }}</strong>
              {{ critique.rationale }}
            </li>
          </ul>
        </section>

        <details class="text-sm">
          <summary class="cursor-pointer font-semibold text-ink-2">{{ copy.details }}</summary>
          <div class="mt-4 grid gap-5">
            <dl class="m-0 grid gap-3 text-sm">
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
                <h4 class="m-0 font-semibold text-ink">{{ copy.advantages }}</h4>
                <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                  <li v-for="item in alternative.advantages" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <h4 class="m-0 font-semibold text-ink">{{ copy.tradeOffs }}</h4>
                <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                  <li v-for="item in alternative.trade_offs" :key="item">{{ item }}</li>
                </ul>
              </section>
            </div>

            <section>
              <h4 class="m-0 font-semibold text-ink">{{ copy.informationArchitecture }}</h4>
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
                <h4 class="m-0 font-semibold text-ink">{{ copy.accessibility }}</h4>
                <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                  <li v-for="item in alternative.accessibility_considerations" :key="item">
                    {{ item }}
                  </li>
                </ul>
              </section>
              <section>
                <h4 class="m-0 font-semibold text-ink">{{ copy.security }}</h4>
                <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
                  <li v-for="item in alternative.security_considerations" :key="item">
                    {{ item }}
                  </li>
                </ul>
              </section>
            </div>

            <section v-if="alternative.workflows.length > 0">
              <h4 class="m-0 font-semibold text-ink">{{ copy.workflows }}</h4>
              <ol class="mt-2 grid gap-3">
                <li
                  v-for="workflow in alternative.workflows"
                  :key="workflow.id"
                  class="rounded-panel border border-line p-3"
                >
                  <p class="m-0 font-semibold text-ink">
                    {{ workflow.code }} · {{ workflow.title }}
                  </p>
                  <ol class="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
                    <li v-for="step in workflow.steps" :key="step">{{ step }}</li>
                  </ol>
                </li>
              </ol>
            </section>

            <section v-if="critiquesFor(alternative.id).length > 0" class="grid gap-3">
              <h4 class="m-0 font-semibold text-ink">{{ copy.critiques }}</h4>
              <article
                v-for="critique in critiquesFor(alternative.id)"
                :key="critique.id"
                class="grid gap-3 rounded-panel border border-hypothesis-line bg-hypothesis-bg p-4 text-hypothesis-text"
              >
                <header class="flex flex-wrap items-center justify-between gap-2">
                  <p class="m-0 font-semibold">
                    {{ critique.code }} · {{ critique.user_twin_reference.name }}
                  </p>
                  <span
                    class="rounded-pill border border-hypothesis-line bg-surface px-2.5 py-1 font-mono text-[11px]"
                  >
                    {{ critique.epistemic_status }} · {{ critique.human_validation }}
                  </span>
                </header>

                <p class="m-0 text-sm">{{ critique.rationale }}</p>
                <p class="m-0 font-mono text-[11px] tracking-wide uppercase">
                  {{ copy.confidence }}: {{ confidenceLabel(critique.confidence) }}
                </p>

                <section v-if="critique.concerns.length > 0">
                  <h5 class="m-0 text-sm font-semibold">{{ copy.concerns }}</h5>
                  <ul class="mt-1 list-disc space-y-1 pl-5 text-sm">
                    <li v-for="(item, index) in critique.concerns" :key="item">
                      {{ item }}
                      <InsightApplyMenu
                        v-if="projectId"
                        :project-id="projectId"
                        :source="{
                          kind: 'DESIGN_CRITIQUE',
                          id: critique.code + ':' + index,
                          twinId: critique.user_twin_reference.twin_id,
                          text: item,
                          mitigation: critique.suggested_changes[0] ?? null,
                        }"
                        :locale="locale"
                        :authorize="authorize"
                      />
                    </li>
                  </ul>
                </section>

                <section v-if="critique.questions.length > 0">
                  <h5 class="m-0 text-sm font-semibold">{{ copy.questions }}</h5>
                  <ul class="mt-1 list-disc space-y-1 pl-5 text-sm">
                    <li v-for="item in critique.questions" :key="item">{{ item }}</li>
                  </ul>
                </section>

                <details>
                  <summary class="cursor-pointer text-sm font-semibold">
                    {{ copy.provenance }}
                  </summary>
                  <ul class="mt-2 grid gap-2 text-xs">
                    <li
                      v-for="reference in critique.provenance"
                      :key="`${reference.source_kind}:${reference.source_id}:${reference.locator}`"
                      class="rounded-control bg-surface p-2 break-all"
                    >
                      {{ reference.source_kind }} · {{ reference.source_id }}
                      <span v-if="reference.locator !== null"> · {{ reference.locator }}</span>
                    </li>
                  </ul>
                </details>
              </article>
            </section>
          </div>
        </details>
      </article>
    </div>
  </section>
</template>
