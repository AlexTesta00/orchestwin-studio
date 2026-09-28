<script setup lang="ts">
import { computed, useId } from "vue";

import DesignStyleTile from "./DesignStyleTile.vue";
import InsightApplyMenu from "./InsightApplyMenu.vue";
import TwinIdentity from "./TwinIdentity.vue";
import { archetypeLabel } from "./visualLanguage";
import type { AuthorizedDesignLoopRequest } from "../stores/designLoop";
import type {
  DesignAlternativePayload,
  SyntheticDesignCritiquePayload,
  UserTwinVersionReferencePayload,
} from "../types/design";

type Locale = "en" | "it";

type CritiqueList =
  | "strengths"
  | "concerns"
  | "unmet_needs"
  | "accessibility_observations"
  | "trust_concerns"
  | "questions"
  | "suggested_changes";

interface LayoutRow {
  label: string;
  value: string;
}

interface OpinionList {
  key: CritiqueList;
  items: readonly string[];
}

interface TwinOpinion {
  twinId: string;
  name: string;
  fit: string | null;
  critique: SyntheticDesignCritiquePayload | null;
  lists: OpinionList[];
}

const CRITIQUE_LISTS: readonly CritiqueList[] = [
  "strengths",
  "concerns",
  "unmet_needs",
  "accessibility_observations",
  "trust_concerns",
  "questions",
  "suggested_changes",
];

const props = withDefaults(
  defineProps<{
    alternatives: readonly DesignAlternativePayload[];
    critiques: readonly SyntheticDesignCritiquePayload[];
    twins?: readonly UserTwinVersionReferencePayload[];
    recommendedAlternativeId?: string | null;
    selectedAlternativeId?: string | null;
    disabled?: boolean;
    locale?: Locale;
    projectId?: string | null;
    authorize?: AuthorizedDesignLoopRequest | undefined;
  }>(),
  {
    twins: () => [],
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
    layout: "Layout",
    approach: "Approach",
    rationale: "Rationale",
    advantages: "Advantages",
    tradeOffs: "Trade-offs",
    informationArchitecture: "Information architecture",
    accessibility: "Accessibility considerations",
    security: "Security considerations",
    workflows: "Workflows",
    twinsTitle: "What the twins think",
    twinFit: "How this design serves them",
    lists: {
      strengths: "Strengths",
      concerns: "Concerns",
      unmet_needs: "Unmet needs",
      accessibility_observations: "Accessibility",
      trust_concerns: "Trust",
      questions: "Open questions",
      suggested_changes: "Suggested changes",
    },
    details: "Alternative details",
    confidence: "Self-assessed confidence",
    provenance: "Provenance of the critiques",
    select: "Select {title}",
    methodology:
      "User Twin critiques are simulated feedback and design hypotheses. They are not empirical evidence of real-user behavior.",
  },
  it: {
    title: "Alternative di design",
    recommended: "Raccomandazione del provider",
    selected: "Selezione del proprietario",
    layout: "Impostazione",
    approach: "Approccio",
    rationale: "Motivazione",
    advantages: "Vantaggi",
    tradeOffs: "Compromessi",
    informationArchitecture: "Architettura dell'informazione",
    accessibility: "Considerazioni di accessibilità",
    security: "Considerazioni di sicurezza",
    workflows: "Flussi",
    twinsTitle: "Cosa ne pensano i twin",
    twinFit: "Come gli serve questo design",
    lists: {
      strengths: "Punti di forza",
      concerns: "Criticità",
      unmet_needs: "Bisogni non coperti",
      accessibility_observations: "Accessibilità",
      trust_concerns: "Fiducia",
      questions: "Domande aperte",
      suggested_changes: "Modifiche suggerite",
    },
    details: "Dettagli dell'alternativa",
    confidence: "Confidenza auto-valutata",
    provenance: "Provenienza delle critiche",
    select: "Seleziona {title}",
    methodology:
      "Le critiche dei User Twin sono feedback simulato e ipotesi progettuali. Non sono evidenza empirica del comportamento di utenti reali.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const groupName = `design-alternative-${useId()}`;

function layoutRow(alternative: DesignAlternativePayload): LayoutRow | null {
  if (alternative.visual_language) {
    return {
      label: copy.value.layout,
      value: archetypeLabel(props.locale, alternative.visual_language.choices.archetype),
    };
  }
  if (alternative.approach) {
    return { label: copy.value.approach, value: alternative.approach };
  }
  return null;
}

const layoutRows = computed<Record<string, LayoutRow | null>>(() =>
  Object.fromEntries(
    props.alternatives.map((alternative) => [alternative.id, layoutRow(alternative)]),
  ),
);

function critiquesFor(alternativeId: string): SyntheticDesignCritiquePayload[] {
  return props.critiques.filter((critique) => critique.design_alternative_id === alternativeId);
}

function listsOf(critique: SyntheticDesignCritiquePayload): OpinionList[] {
  return CRITIQUE_LISTS.map((key) => ({ key, items: critique[key] })).filter(
    (list) => list.items.length > 0,
  );
}

function opinionsOf(alternative: DesignAlternativePayload): TwinOpinion[] {
  const critiques = critiquesFor(alternative.id);
  const fits = alternative.visual_language?.twin_fit ?? [];
  const names = new Map<string, string>();
  for (const twin of [
    ...props.twins,
    ...critiques.map((critique) => critique.user_twin_reference),
    ...fits,
  ]) {
    if (!names.has(twin.twin_id)) {
      names.set(twin.twin_id, twin.name);
    }
  }
  return [...names].flatMap(([twinId, name]) => {
    const critique = critiques.find((item) => item.user_twin_reference.twin_id === twinId) ?? null;
    const fit = fits.find((item) => item.twin_id === twinId)?.statement ?? null;
    if (critique === null && fit === null) {
      return [];
    }
    return [{ twinId, name, fit, critique, lists: critique === null ? [] : listsOf(critique) }];
  });
}

const opinions = computed<Record<string, TwinOpinion[]>>(() =>
  Object.fromEntries(
    props.alternatives.map((alternative) => [alternative.id, opinionsOf(alternative)]),
  ),
);

function opinionsFor(alternativeId: string): TwinOpinion[] {
  return opinions.value[alternativeId] ?? [];
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

        <section
          v-if="opinionsFor(alternative.id).length > 0"
          class="grid gap-3 border-t border-line pt-4"
          data-testid="twin-opinions"
        >
          <h4 class="m-0 text-base font-semibold tracking-block text-ink">
            {{ copy.twinsTitle }}<span class="sr-only">: {{ alternative.title }}</span>
          </h4>
          <ul class="m-0 grid list-none gap-3 p-0">
            <li
              v-for="opinion in opinionsFor(alternative.id)"
              :key="opinion.twinId"
              class="@container grid gap-3 rounded-panel border border-hypothesis-line bg-hypothesis-bg p-3 break-words text-hypothesis-text sm:p-4"
              :data-twin-id="opinion.twinId"
              data-testid="twin-opinion"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h5 class="m-0 min-w-0">
                  <TwinIdentity
                    :identity-key="opinion.twinId"
                    :name="opinion.name"
                    :locale="locale"
                    compact
                  />
                </h5>
                <p
                  v-if="opinion.critique"
                  class="m-0 text-xs font-semibold"
                  data-testid="twin-opinion-confidence"
                >
                  {{ copy.confidence }}: {{ confidenceLabel(opinion.critique.confidence) }}
                </p>
              </div>
              <div
                v-if="opinion.fit !== null"
                class="grid gap-1 rounded-control border border-hypothesis-line bg-surface p-3"
                data-testid="twin-opinion-fit"
              >
                <h6 class="m-0 text-sm font-semibold">{{ copy.twinFit }}</h6>
                <p class="m-0 text-sm leading-6">{{ opinion.fit }}</p>
              </div>
              <template v-if="opinion.critique">
                <p class="m-0 text-[15px] leading-6" data-testid="twin-opinion-rationale">
                  {{ opinion.critique.rationale }}
                </p>
                <div v-if="opinion.lists.length > 0" class="grid gap-3 @lg:grid-cols-2">
                  <section
                    v-for="list in opinion.lists"
                    :key="list.key"
                    :data-testid="`twin-opinion-${list.key}`"
                  >
                    <h6 class="m-0 text-sm font-semibold">{{ copy.lists[list.key] }}</h6>
                    <ul class="mt-1 list-disc space-y-1 pl-5 text-sm">
                      <li v-for="(item, index) in list.items" :key="item">
                        {{ item }}
                        <InsightApplyMenu
                          v-if="projectId && list.key === 'concerns'"
                          :project-id="projectId"
                          :source="{
                            kind: 'DESIGN_CRITIQUE',
                            id: opinion.critique.code + ':' + index,
                            twinId: opinion.critique.user_twin_reference.twin_id,
                            text: item,
                            mitigation: opinion.critique.suggested_changes[0] ?? null,
                          }"
                          :locale="locale"
                          :authorize="authorize"
                        />
                      </li>
                    </ul>
                  </section>
                </div>
              </template>
            </li>
          </ul>
        </section>

        <details class="text-sm" data-testid="alternative-details">
          <summary class="cursor-pointer font-semibold text-ink-2">{{ copy.details }}</summary>
          <div class="mt-4 grid gap-5">
            <dl class="m-0 grid gap-3 text-sm">
              <div v-if="layoutRows[alternative.id]" data-testid="alternative-layout">
                <dt class="font-semibold text-ink">{{ layoutRows[alternative.id]?.label }}</dt>
                <dd class="m-0 mt-1 text-ink-2">{{ layoutRows[alternative.id]?.value }}</dd>
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

            <section
              v-if="critiquesFor(alternative.id).length > 0"
              data-testid="critique-provenance"
            >
              <h4 class="m-0 font-semibold text-ink">{{ copy.provenance }}</h4>
              <ul class="mt-2 grid list-none gap-3 p-0">
                <li
                  v-for="critique in critiquesFor(alternative.id)"
                  :key="critique.id"
                  class="grid gap-2"
                >
                  <p class="m-0 flex flex-wrap items-center gap-2">
                    <span class="font-semibold text-ink">
                      {{ critique.code }} · {{ critique.user_twin_reference.name }}
                    </span>
                    <span
                      class="rounded-pill border border-hypothesis-line bg-hypothesis-bg px-2.5 py-1 font-mono text-[11px] text-hypothesis-text"
                    >
                      {{ critique.epistemic_status }} · {{ critique.human_validation }}
                    </span>
                  </p>
                  <ul class="m-0 grid list-none gap-2 p-0 text-xs text-ink-2">
                    <li
                      v-for="reference in critique.provenance"
                      :key="`${reference.source_kind}:${reference.source_id}:${reference.locator}`"
                      class="rounded-control bg-surface-2 p-2 break-all"
                    >
                      {{ reference.source_kind }} · {{ reference.source_id }}
                      <span v-if="reference.locator !== null"> · {{ reference.locator }}</span>
                    </li>
                  </ul>
                </li>
              </ul>
            </section>
          </div>
        </details>
      </article>
    </div>
  </section>
</template>
