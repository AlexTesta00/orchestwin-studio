<script lang="ts">
import type { GenerationJobStage, MockupIssuePayload } from "../types/designMockups";

export const MOCKUP_READ_FAILURE = "MOCKUP_STATUS_UNAVAILABLE";

export type AlternativePreview =
  | { kind: "document"; html: string }
  | { kind: "loading" }
  | { kind: "drawing"; startedAt: string; stage: GenerationJobStage | null }
  | {
      kind: "rejected" | "failed";
      code: string;
      reasons: readonly MockupIssuePayload[];
      retryable: boolean;
    }
  | { kind: "missing" }
  | { kind: "declarative" };
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";

import { generationFailureText, generationReasonText } from "./DesignIterationPanel.vue";
import DesignStyleTile from "./DesignStyleTile.vue";
import GeneratedMockupFrame from "./GeneratedMockupFrame.vue";
import UiButton from "./UiButton.vue";
import { archetypeLabel } from "./visualLanguage";
import type { DesignAlternativePayload, UserTwinVersionReferencePayload } from "../types/design";

type Locale = "en" | "it";

const REASON_LIMIT = 3;

const props = withDefaults(
  defineProps<{
    alternatives: readonly DesignAlternativePayload[];
    twins?: readonly UserTwinVersionReferencePayload[];
    recommendedAlternativeId?: string | null;
    selectedAlternativeId?: string | null;
    previews?: Readonly<Record<string, AlternativePreview>>;
    choosable?: Readonly<Record<string, boolean>>;
    hints?: Readonly<Record<string, string>>;
    notes?: Readonly<Record<string, string>>;
    choosing?: string | null;
    disabled?: boolean;
    locale?: Locale;
  }>(),
  {
    twins: () => [],
    recommendedAlternativeId: null,
    selectedAlternativeId: null,
    previews: () => ({}),
    choosable: () => ({}),
    hints: () => ({}),
    notes: () => ({}),
    choosing: null,
    disabled: false,
    locale: "en",
  },
);

const emit = defineEmits<{
  select: [alternativeId: string];
  open: [alternativeId: string];
  retry: [alternativeId: string];
}>();

const messages = {
  en: {
    title: "The design alternatives",
    recommended: "recommended by the designer",
    pros: "In favour",
    cons: "Against",
    open: "Try the mockup",
    openLabel: "Try the mockup of {code} · {title}",
    choose: "Choose this one",
    chooseLabel: "Choose {code} · {title}",
    choosing: "Applying your choice…",
    chosen: "Your choice",
    drawing: "The designer is drawing the mockup",
    stages: {
      GENERATING: "Drawing the screens.",
      VALIDATING: "The Studio is checking the mockup.",
      RETRYING: "The first attempt was not good enough: it is being redone.",
      none: "Working on the mockup.",
    },
    elapsed: "Running for {time}",
    duration:
      "It usually takes 5 to 10 minutes. You can keep working: the drawing goes on even if you close the page.",
    rejectedTitle: "The mockup needs another try",
    failedTitle: "The mockup was not drawn",
    unreadTitle: "The mockup did not load",
    why: "Why",
    more: ["and 1 more point", "and {n} more points"],
    retry: "Try again",
    retryLabel: "Try again to draw the mockup of {code}",
    missing: "The mockup of this alternative has not been drawn yet.",
    draw: "Draw the mockup",
    drawLabel: "Draw the mockup of {code}",
    drawCost: "Drawing uses the hosted model and has a cost.",
    loading: "Preparing the preview…",
    thumbnail: "Preview of {code} · {title}",
    details: "Details of the alternative",
    layout: "Layout",
    approach: "Approach",
    rationale: "Why this alternative",
    advantages: "Advantages",
    tradeOffs: "Trade-offs",
    informationArchitecture: "Information architecture",
    accessibility: "Accessibility",
    security: "Security",
    workflows: "Workflows",
    twinFit: "How it serves the twins",
  },
  it: {
    title: "Le alternative di design",
    recommended: "consigliata dal designer",
    pros: "A favore",
    cons: "Contro",
    open: "Prova il mockup",
    openLabel: "Prova il mockup di {code} · {title}",
    choose: "Scegli questa",
    chooseLabel: "Scegli {code} · {title}",
    choosing: "Applico la tua scelta…",
    chosen: "La tua scelta",
    drawing: "Il designer sta disegnando il mockup",
    stages: {
      GENERATING: "Disegna le schermate.",
      VALIDATING: "Lo Studio controlla il mockup.",
      RETRYING: "Il primo tentativo non andava bene: lo sta rifacendo.",
      none: "Sta lavorando al mockup.",
    },
    elapsed: "In corso da {time}",
    duration:
      "Di solito servono da 5 a 10 minuti. Puoi continuare a lavorare: il disegno prosegue anche se chiudi la pagina.",
    rejectedTitle: "Il mockup va rifatto",
    failedTitle: "Il mockup non è stato disegnato",
    unreadTitle: "Il mockup non si è caricato",
    why: "Perché",
    more: ["e un altro punto", "e altri {n} punti"],
    retry: "Riprova",
    retryLabel: "Riprova a disegnare il mockup di {code}",
    missing: "Il mockup di questa alternativa non è ancora stato disegnato.",
    draw: "Disegna il mockup",
    drawLabel: "Disegna il mockup di {code}",
    drawCost: "Il disegno usa il modello ospitato e ha un costo.",
    loading: "Preparo l'anteprima…",
    thumbnail: "Anteprima di {code} · {title}",
    details: "Dettagli dell'alternativa",
    layout: "Impostazione",
    approach: "Approccio",
    rationale: "Perché questa alternativa",
    advantages: "Vantaggi",
    tradeOffs: "Compromessi",
    informationArchitecture: "Architettura dell'informazione",
    accessibility: "Accessibilità",
    security: "Sicurezza",
    workflows: "Flussi",
    twinFit: "Come serve i twin",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const titleId = `design-alternatives-${useId()}`;
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval> | null = null;

const drawing = computed(() =>
  Object.values(props.previews).some((preview) => preview.kind === "drawing"),
);

const cards = computed(() =>
  props.alternatives.map((alternative) => {
    const preview: AlternativePreview = props.previews[alternative.id] ?? { kind: "declarative" };
    const chosen = alternative.id === props.selectedAlternativeId;
    return {
      alternative,
      preview,
      chosen,
      recommended: alternative.id === props.recommendedAlternativeId,
      canChoose: !props.disabled && props.choosable[alternative.id] !== false,
      busy: props.choosing === alternative.id,
      hint: props.hints[alternative.id] ?? null,
      note: props.notes[alternative.id] ?? null,
      layout: layoutRow(alternative),
      fits: fitsOf(alternative),
      pro: alternative.advantages[0] ?? null,
      con: alternative.trade_offs[0] ?? null,
      reasons: preview.kind === "rejected" || preview.kind === "failed" ? reasonLines(preview) : [],
      canOpen: openable(preview),
    };
  }),
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function failureTitle(kind: "rejected" | "failed", code: string): string {
  if (kind === "rejected") {
    return copy.value.rejectedTitle;
  }
  return code === MOCKUP_READ_FAILURE ? copy.value.unreadTitle : copy.value.failedTitle;
}

function openable(preview: AlternativePreview): boolean {
  if (preview.kind === "failed") {
    return preview.code === MOCKUP_READ_FAILURE;
  }
  return preview.kind !== "drawing" && preview.kind !== "rejected" && preview.kind !== "missing";
}

function layoutRow(alternative: DesignAlternativePayload): { label: string; value: string } | null {
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

function fitsOf(
  alternative: DesignAlternativePayload,
): { id: string; name: string; text: string }[] {
  const names = new Map(props.twins.map((twin) => [twin.twin_id, twin.name]));
  return (alternative.visual_language?.twin_fit ?? []).map((fit) => ({
    id: fit.twin_id,
    name: names.get(fit.twin_id) ?? fit.name,
    text: fit.statement,
  }));
}

function reasonLines(preview: { reasons: readonly MockupIssuePayload[] }): string[] {
  const lines: string[] = [];
  for (const reason of preview.reasons) {
    const line = generationReasonText(reason.code, props.locale);
    if (!lines.includes(line)) {
      lines.push(line);
    }
  }
  if (lines.length <= REASON_LIMIT) {
    return lines;
  }
  const rest = lines.length - REASON_LIMIT;
  const [one, many] = copy.value.more;
  return [...lines.slice(0, REASON_LIMIT), rest === 1 ? one : fill(many, { n: rest })];
}

function elapsed(startedAt: string): string {
  const started = Date.parse(startedAt);
  if (Number.isNaN(started)) {
    return "";
  }
  const seconds = Math.max(0, Math.floor((now.value - started) / 1000));
  const minutes = Math.floor(seconds / 60);
  const time = minutes > 0 ? `${minutes} min ${seconds % 60} s` : `${seconds} s`;
  return fill(copy.value.elapsed, { time });
}

function stageText(stage: GenerationJobStage | null): string {
  return stage === null ? copy.value.stages.none : copy.value.stages[stage];
}

function choose(alternativeId: string, allowed: boolean): void {
  if (allowed && props.choosing === null) {
    emit("select", alternativeId);
  }
}

watch(
  drawing,
  (active) => {
    if (active && clock === null) {
      now.value = Date.now();
      clock = setInterval(() => {
        now.value = Date.now();
      }, 1000);
    }
    if (!active && clock !== null) {
      clearInterval(clock);
      clock = null;
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  if (clock !== null) {
    clearInterval(clock);
    clock = null;
  }
});
</script>

<template>
  <section class="text-on-night" :aria-labelledby="titleId" data-testid="design-alternatives">
    <h2 :id="titleId" class="sr-only">{{ copy.title }}</h2>
    <div class="grid grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))] gap-4">
      <article
        v-for="card in cards"
        :key="card.alternative.id"
        :data-test="`alternative-${card.alternative.code}`"
        :data-alternative="card.alternative.id"
        :data-chosen="card.chosen ? 'true' : 'false'"
        :data-preview="card.preview.kind"
        :class="[
          'flex min-w-0 flex-col gap-3 rounded-tile bg-on-night/4 p-4',
          card.chosen ? 'border-2 border-petrol-on-night' : 'border border-night-line',
        ]"
        data-testid="design-alternative"
      >
        <div
          v-if="card.preview.kind === 'document'"
          class="overflow-hidden rounded-[10px] bg-night-deep"
          data-testid="alternative-thumbnail"
        >
          <GeneratedMockupFrame
            :html="card.preview.html"
            :title="
              fill(copy.thumbnail, { code: card.alternative.code, title: card.alternative.title })
            "
            :interactive="false"
          />
        </div>
        <div
          v-else-if="card.preview.kind === 'drawing'"
          class="grid min-h-[180px] content-center justify-items-start gap-2 rounded-[10px] border border-night-line bg-night-deep p-5 sm:aspect-[16/10]"
          aria-busy="true"
          data-testid="alternative-drawing"
        >
          <span
            class="inline-block h-5 w-5 shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
            aria-hidden="true"
          />
          <p class="text-[15px] font-semibold">{{ copy.drawing }}</p>
          <p class="text-sm text-on-night-2" role="status">
            {{ stageText(card.preview.stage) }}
          </p>
          <p class="text-[13px] text-on-night-3" data-testid="alternative-elapsed">
            {{ elapsed(card.preview.startedAt) }}
          </p>
          <p class="text-[13px] leading-normal text-on-night-3" data-testid="alternative-duration">
            {{ copy.duration }}
          </p>
        </div>
        <div
          v-else-if="card.preview.kind === 'rejected' || card.preview.kind === 'failed'"
          class="grid min-h-[180px] content-start gap-2 rounded-[10px] border border-fail-on-night/40 bg-fail-on-night/8 p-4"
          role="alert"
          data-testid="alternative-failure"
        >
          <p class="text-[15px] font-semibold text-fail-on-night">
            {{ failureTitle(card.preview.kind, card.preview.code) }}
          </p>
          <p class="text-sm leading-normal text-on-night-2">
            {{ generationFailureText(card.preview.code, locale) }}
          </p>
          <div v-if="card.reasons.length > 0" class="grid gap-1">
            <p class="text-[13px] font-semibold text-on-night">{{ copy.why }}</p>
            <ul class="grid list-disc gap-1 pl-5 text-[13px] leading-normal text-on-night-2">
              <li v-for="line in card.reasons" :key="line">{{ line }}</li>
            </ul>
          </div>
          <UiButton
            v-if="card.preview.retryable"
            variant="outline"
            class="mt-1 justify-self-start"
            :disabled="disabled"
            :aria-label="fill(copy.retryLabel, { code: card.alternative.code })"
            data-testid="alternative-retry"
            @click="emit('retry', card.alternative.id)"
          >
            {{ copy.retry }}
          </UiButton>
        </div>
        <div
          v-else-if="card.preview.kind === 'missing'"
          class="grid aspect-[16/10] content-center justify-items-start gap-2 rounded-[10px] border border-dashed border-night-line-strong bg-night-deep p-5"
          data-testid="alternative-missing"
        >
          <p class="text-[15px] leading-normal text-on-night-2">{{ copy.missing }}</p>
          <UiButton
            variant="outline"
            :disabled="disabled"
            :aria-label="fill(copy.drawLabel, { code: card.alternative.code })"
            data-testid="alternative-draw"
            @click="emit('retry', card.alternative.id)"
          >
            {{ copy.draw }}
          </UiButton>
          <p class="text-xs text-on-night-3">{{ copy.drawCost }}</p>
        </div>
        <div
          v-else-if="card.preview.kind === 'loading'"
          class="grid aspect-[16/10] place-items-center rounded-[10px] border border-night-line bg-night-deep p-5"
          role="status"
          data-testid="alternative-loading"
        >
          <span class="inline-flex items-center gap-2.5 text-sm text-on-night-2">
            <span
              class="inline-block h-[15px] w-[15px] shrink-0 animate-spin-arc rounded-full border-2 border-night-line-strong border-t-petrol-on-night"
              aria-hidden="true"
            />
            {{ copy.loading }}
          </span>
        </div>
        <DesignStyleTile
          v-else-if="card.alternative.visual_language"
          :visual="card.alternative.visual_language"
          :locale="locale"
          compact
        />

        <div class="flex flex-wrap items-center gap-2">
          <span class="font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ card.alternative.code }}
          </span>
          <span
            v-if="card.recommended"
            class="text-xs text-on-night-3"
            data-testid="alternative-recommended"
          >
            · {{ copy.recommended }}
          </span>
        </div>
        <h3 class="-mt-1 text-[22px] leading-tight font-semibold tracking-[-0.015em] break-words">
          {{ card.alternative.title }}
        </h3>
        <p class="text-[15px] leading-normal text-on-night-2">{{ card.alternative.summary }}</p>
        <div
          v-if="card.pro !== null || card.con !== null"
          class="grid grid-cols-1 gap-3 text-sm leading-[1.45] text-on-night-2 min-[420px]:grid-cols-2"
        >
          <div v-if="card.pro !== null" data-testid="alternative-pro">
            <p class="mb-1 font-mono text-[10px] tracking-label text-petrol-on-night-2 uppercase">
              {{ copy.pros }}
            </p>
            {{ card.pro }}
          </div>
          <div v-if="card.con !== null" data-testid="alternative-con">
            <p class="mb-1 font-mono text-[10px] tracking-label text-warn-on-night uppercase">
              {{ copy.cons }}
            </p>
            {{ card.con }}
          </div>
        </div>
        <p
          v-if="card.note !== null"
          class="rounded-field border border-warn-on-night/30 bg-warn-on-night/6 px-3 py-2 text-[13px] leading-normal text-warn-on-night"
          data-testid="alternative-note"
        >
          {{ card.note }}
        </p>

        <div class="mt-auto flex flex-wrap items-center gap-2 pt-1">
          <UiButton
            v-if="card.canOpen"
            variant="outline"
            :aria-label="
              fill(copy.openLabel, { code: card.alternative.code, title: card.alternative.title })
            "
            data-testid="alternative-open"
            @click="emit('open', card.alternative.id)"
          >
            {{ copy.open }}
          </UiButton>
          <UiButton
            v-if="!card.chosen"
            variant="pill"
            :disabled="!card.canChoose || choosing !== null"
            :aria-label="
              fill(copy.chooseLabel, { code: card.alternative.code, title: card.alternative.title })
            "
            :data-alternative-id="card.alternative.id"
            data-testid="alternative-choose"
            @click="choose(card.alternative.id, card.canChoose)"
          >
            {{ card.busy ? copy.choosing : copy.choose }}
          </UiButton>
          <span
            v-else
            class="inline-flex min-h-7 items-center gap-1.5 rounded-pill border border-petrol-on-night bg-petrol-on-night/16 px-3 text-xs font-semibold whitespace-nowrap text-petrol-on-night-2"
            data-testid="alternative-chosen"
          >
            <span class="inline-block h-2 w-2 rounded-full bg-petrol-on-night" aria-hidden="true" />
            {{ copy.chosen }}
          </span>
        </div>
        <p
          v-if="card.hint !== null"
          class="text-[13px] leading-normal text-on-night-3"
          data-testid="alternative-hint"
        >
          {{ card.hint }}
        </p>

        <details class="group text-sm" data-testid="alternative-details">
          <summary
            class="flex min-h-11 cursor-pointer list-none items-center gap-2.5 font-semibold text-petrol-on-night-2 [&::-webkit-details-marker]:hidden"
          >
            <span
              aria-hidden="true"
              class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-petrol-on-night-2 transition-transform duration-150 group-open:rotate-45"
            />
            {{ copy.details }}<span class="sr-only">: {{ card.alternative.title }}</span>
          </summary>
          <div class="grid gap-4 pt-2 pb-1 text-on-night-2">
            <dl class="grid gap-3">
              <div v-if="card.layout" data-testid="alternative-layout">
                <dt class="font-semibold text-on-night">{{ card.layout.label }}</dt>
                <dd class="mt-1">{{ card.layout.value }}</dd>
              </div>
              <div>
                <dt class="font-semibold text-on-night">{{ copy.rationale }}</dt>
                <dd class="mt-1 leading-normal">{{ card.alternative.rationale }}</dd>
              </div>
            </dl>
            <section v-if="card.alternative.advantages.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.advantages }}</h4>
              <ul class="mt-1 list-disc space-y-1 pl-5">
                <li v-for="item in card.alternative.advantages" :key="item">{{ item }}</li>
              </ul>
            </section>
            <section v-if="card.alternative.trade_offs.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.tradeOffs }}</h4>
              <ul class="mt-1 list-disc space-y-1 pl-5">
                <li v-for="item in card.alternative.trade_offs" :key="item">{{ item }}</li>
              </ul>
            </section>
            <section v-if="card.alternative.information_architecture.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.informationArchitecture }}</h4>
              <ol class="mt-1 flex list-none flex-wrap gap-1.5 p-0">
                <li
                  v-for="(item, index) in card.alternative.information_architecture"
                  :key="item"
                  class="rounded-pill border border-night-line px-2.5 py-1 text-[13px]"
                >
                  {{ index + 1 }}. {{ item }}
                </li>
              </ol>
            </section>
            <section v-if="card.alternative.accessibility_considerations.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.accessibility }}</h4>
              <ul class="mt-1 list-disc space-y-1 pl-5">
                <li v-for="item in card.alternative.accessibility_considerations" :key="item">
                  {{ item }}
                </li>
              </ul>
            </section>
            <section v-if="card.alternative.security_considerations.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.security }}</h4>
              <ul class="mt-1 list-disc space-y-1 pl-5">
                <li v-for="item in card.alternative.security_considerations" :key="item">
                  {{ item }}
                </li>
              </ul>
            </section>
            <section v-if="card.alternative.workflows.length > 0">
              <h4 class="font-semibold text-on-night">{{ copy.workflows }}</h4>
              <ol class="mt-1 grid list-none gap-2 p-0">
                <li
                  v-for="workflow in card.alternative.workflows"
                  :key="workflow.id"
                  class="rounded-field border border-night-line p-3"
                >
                  <p class="font-semibold text-on-night">
                    {{ workflow.code }} · {{ workflow.title }}
                  </p>
                  <ol class="mt-1 list-decimal space-y-1 pl-5">
                    <li v-for="step in workflow.steps" :key="step">{{ step }}</li>
                  </ol>
                </li>
              </ol>
            </section>
            <section v-if="card.fits.length > 0" data-testid="alternative-twin-fit">
              <h4 class="font-semibold text-on-night">{{ copy.twinFit }}</h4>
              <ul class="mt-1 grid list-none gap-1.5 p-0">
                <li v-for="fit in card.fits" :key="fit.id" class="leading-normal">
                  <strong class="font-semibold text-on-night">{{ fit.name }}</strong>
                  · {{ fit.text }}
                </li>
              </ul>
            </section>
          </div>
        </details>
      </article>
    </div>
  </section>
</template>
