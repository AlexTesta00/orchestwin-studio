<script setup lang="ts">
import { computed, nextTick, provide, ref, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";
import { modelFeedback } from "./modelFeedback";

import { apiClient } from "../api/client";
import type { KnowledgeAlignmentApi } from "../api/knowledgeAlignment";
import { useAuthStore } from "../stores/auth";
import { errorCodeOf, generationFailureMessage } from "../stores/designMockups";
import {
  useKnowledgeAlignmentStore,
  type AuthorizedRequest,
  type ProposalDecision,
} from "../stores/knowledgeAlignment";
import type { AlignmentProposalPayload, ProposalSection } from "../types/knowledgeAlignment";

type Locale = "en" | "it";
type CardState = "waiting" | "applying" | "skipping" | "applied" | "skipped" | "failed";
type ReasonKey =
  "decided" | "missing" | "revisionPending" | "unchanged" | "alternative" | "approval";

export interface AppliedProposal {
  code: string;
  section: ProposalSection;
  diffId: string | null;
}

export interface SkippedProposal {
  code: string;
  section: ProposalSection;
}

interface CardFailure {
  decision: ProposalDecision;
  code: string | null;
}

const REQUEST_LIMITS: Record<ProposalSection, number> = {
  REQUIREMENTS: 2000,
  DESIGN: 1000,
  TESTS: 600,
};

const SHORT_COMMIT = 7;

const REASONS: ReadonlyMap<string, ReasonKey> = new Map<string, ReasonKey>([
  ["ALIGNMENT_PROPOSAL_DECIDED", "decided"],
  ["ALIGNMENT_PROPOSAL_NOT_FOUND", "missing"],
  ["REVISION_PENDING", "revisionPending"],
  ["REQUIREMENTS_REVISION_PENDING", "revisionPending"],
  ["DESIGN_REVISION_PENDING", "revisionPending"],
  ["UNCHANGED", "unchanged"],
  ["REQUIREMENTS_UNCHANGED", "unchanged"],
  ["DESIGN_UNCHANGED", "unchanged"],
  ["NO_CHANGE", "unchanged"],
  ["ALTERNATIVE_NOT_CHOSEN", "alternative"],
  ["DESIGN_ALTERNATIVE_NOT_CHOSEN", "alternative"],
  ["DESIGN_NOT_FOUND", "approval"],
  ["REQUIREMENTS_APPROVAL_REQUIRED", "approval"],
  ["DESIGN_APPROVAL_REQUIRED", "approval"],
]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    section: ProposalSection;
    locale?: Locale;
    authorize?: AuthorizedRequest;
    api?: KnowledgeAlignmentApi | undefined;
  }>(),
  { locale: "en", api: undefined },
);

const emit = defineEmits<{
  applied: [proposal: AppliedProposal];
  skipped: [proposal: SkippedProposal];
}>();

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const messages = {
  en: {
    title: "Proposals from the code",
    hypothesis: "A hypothesis of the model drawn from the code diff: no person has verified it.",
    text: "Request to apply",
    rationale: "Reason",
    about: "About: {items}",
    why: "Why?",
    commits: "Commits",
    files: "Files",
    excerpt: "Diff excerpt",
    apply: "Update and confirm",
    skip: "Skip",
    applying: "The Studio is applying the proposal…",
    applyingModel: "The model is preparing the differences: it can take a few minutes.",
    skipping: "The Studio is skipping the proposal…",
    applied: "Applied: the differences to approve are in this section.",
    appliedTests: "Applied.",
    skipped: "Skipped.",
    applyFailed: "The proposal could not be applied.",
    skipFailed: "The proposal could not be skipped.",
    reasons: {
      decided: "This proposal was already decided, perhaps from the terminal.",
      missing: "This proposal is no longer there.",
      revisionPending:
        "A new version is already waiting for your decision: apply it or discard it before you apply a proposal.",
      unchanged:
        "The model found nothing to change with this request. Edit the text and try again.",
      alternative: "Choose a design alternative first.",
      approval: "This section has to be approved first.",
    },
    model: "The model is not connected: check the model status in Project details.",
  },
  it: {
    title: "Proposte dal codice",
    hypothesis:
      "Ipotesi del modello ricavata dal diff del codice: nessuna persona l'ha verificata.",
    text: "Richiesta da applicare",
    rationale: "Motivazione",
    about: "Riguarda: {items}",
    why: "Perché?",
    commits: "Commit",
    files: "File",
    excerpt: "Estratto del diff",
    apply: "Aggiorna e conferma",
    skip: "Scarta",
    applying: "Lo Studio sta applicando la proposta…",
    applyingModel: "Il modello prepara le differenze: può richiedere qualche minuto.",
    skipping: "Lo Studio sta scartando la proposta…",
    applied: "Applicata: le differenze da approvare sono in questa sezione.",
    appliedTests: "Applicata.",
    skipped: "Scartata.",
    applyFailed: "Non è stato possibile applicare la proposta.",
    skipFailed: "Non è stato possibile scartare la proposta.",
    reasons: {
      decided: "Questa proposta è già stata decisa, forse dal terminale.",
      missing: "Questa proposta non c'è più.",
      revisionPending:
        "C'è già una nuova versione da decidere: applicala o scartala prima di applicare una proposta.",
      unchanged:
        "Il modello non ha trovato nulla da cambiare con questa richiesta. Modifica il testo e riprova.",
      alternative: "Prima scegli un'alternativa di design.",
      approval: "Prima va approvata questa sezione.",
    },
    model: "Il modello non è collegato: controlla lo stato dei modelli in Dettagli del progetto.",
  },
} as const;

const store = useKnowledgeAlignmentStore();
const auth = useAuthStore();
const root = ref<HTMLElement | null>(null);
const titleId = useId();
const copy = computed(() => messages[props.locale]);
const projectId = computed(() => props.projectId.trim());
const texts = ref<Record<string, string>>({});
const kept = ref<Record<string, AlignmentProposalPayload>>({});
const failures = ref<Record<string, CardFailure>>({});

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

function fill(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => values[key] ?? match);
}

function listOf(items: readonly string[]): string {
  return new Intl.ListFormat(props.locale === "it" ? "it-IT" : "en-GB", {
    style: "long",
    type: "conjunction",
  }).format(items);
}

const cards = computed<AlignmentProposalPayload[]>(() => {
  const own = kept.value;
  const shown = store
    .bySection(props.section)
    .filter((proposal) => proposal.status === "PROPOSED" || proposal.code in own);

  for (const proposal of Object.values(own)) {
    if (!shown.some((known) => known.code === proposal.code)) {
      shown.push(proposal);
    }
  }

  return shown;
});

function keep(proposal: AlignmentProposalPayload): void {
  kept.value = { ...kept.value, [proposal.code]: proposal };
}

const busy = computed(() => store.pending.apply || store.pending.skip);

function textOf(proposal: AlignmentProposalPayload): string {
  return texts.value[proposal.code] ?? proposal.request;
}

function editedText(proposal: AlignmentProposalPayload): string | null {
  const text = textOf(proposal).trim();

  return text === proposal.request.trim() ? null : text;
}

function stateOf(proposal: AlignmentProposalPayload): CardState {
  const deciding = store.decisionOf(proposal.code);

  if (deciding === "apply") return "applying";
  if (deciding === "skip") return "skipping";
  if (proposal.status === "APPLIED") return "applied";
  if (proposal.status === "SKIPPED") return "skipped";
  if (proposal.code in failures.value) return "failed";

  return "waiting";
}

function isSettled(proposal: AlignmentProposalPayload): boolean {
  const state = stateOf(proposal);

  return state === "applied" || state === "skipped";
}

function failureText(failure: CardFailure): string {
  const lead = failure.decision === "apply" ? copy.value.applyFailed : copy.value.skipFailed;
  const reason = failure.code === null ? undefined : REASONS.get(failure.code);

  if (reason !== undefined) {
    return `${lead} ${copy.value.reasons[reason]}`;
  }

  if (failure.code !== null && failure.code.endsWith("_MODEL_NOT_CONFIGURED")) {
    return `${lead} ${copy.value.model}`;
  }

  return `${lead} ${
    modelFeedback(failure.code, props.locale) ??
    generationFailureMessage(failure.code, props.locale)
  }`;
}

function stateText(proposal: AlignmentProposalPayload): string {
  const state = stateOf(proposal);

  if (state === "applying") {
    return proposal.section === "TESTS"
      ? copy.value.applying
      : `${copy.value.applying} ${copy.value.applyingModel}`;
  }
  if (state === "skipping") return copy.value.skipping;
  if (state === "applied") {
    return proposal.section === "TESTS" ? copy.value.appliedTests : copy.value.applied;
  }
  if (state === "skipped") return copy.value.skipped;

  const failure = failures.value[proposal.code];

  return failure === undefined ? "" : failureText(failure);
}

function subjectsOf(proposal: AlignmentProposalPayload): string {
  const codes = [
    ...proposal.subjects.requirements,
    ...proposal.subjects.screens,
    ...proposal.subjects.criteria,
  ];

  return codes.length === 0 ? "" : fill(copy.value.about, { items: listOf(codes) });
}

function shortCommits(proposal: AlignmentProposalPayload): string {
  return proposal.origin.commits.map((commit) => commit.slice(0, SHORT_COMMIT)).join(", ");
}

function textIdOf(code: string): string {
  return `${titleId}-text-${code}`;
}

function cardTitleIdOf(code: string): string {
  return `${titleId}-title-${code}`;
}

async function announce(code: string): Promise<void> {
  await nextTick();
  const active = document.activeElement;

  if (active !== null && active !== document.body && active.isConnected) return;

  root.value
    ?.querySelector<HTMLElement>(`[data-code="${code}"] [data-testid="alignment-proposal-state"]`)
    ?.focus();
}

function forgetFailure(code: string): void {
  const remaining = { ...failures.value };
  delete remaining[code];
  failures.value = remaining;
}

async function apply(proposal: AlignmentProposalPayload): Promise<void> {
  if (busy.value || textOf(proposal).trim().length === 0) return;
  const { code, section } = proposal;
  forgetFailure(code);
  keep(proposal);

  try {
    const diffId = await store.apply(
      projectId.value,
      code,
      editedText(proposal),
      authorizedRequest,
      props.api,
    );
    keep(
      store.proposals.find((known) => known.code === code) ?? {
        ...proposal,
        status: "APPLIED",
        applied_diff_id: diffId,
      },
    );
    emit("applied", { code, section, diffId });
  } catch (error) {
    failures.value = { ...failures.value, [code]: { decision: "apply", code: errorCodeOf(error) } };
  }

  await announce(code);
}

async function skip(proposal: AlignmentProposalPayload): Promise<void> {
  if (busy.value) return;
  const { code, section } = proposal;
  forgetFailure(code);
  keep(proposal);

  try {
    const skipped = await store.skip(projectId.value, code, null, authorizedRequest, props.api);
    keep(skipped);
    emit("skipped", { code, section });
  } catch (error) {
    failures.value = { ...failures.value, [code]: { decision: "skip", code: errorCodeOf(error) } };
  }

  await announce(code);
}

async function load(): Promise<void> {
  if (projectId.value.length === 0) return;

  try {
    await store.load(projectId.value, authorizedRequest, props.api);
  } catch {
    return;
  }
}

watch(
  projectId,
  () => {
    texts.value = {};
    kept.value = {};
    failures.value = {};
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section
    v-if="cards.length > 0"
    ref="root"
    :aria-labelledby="titleId"
    class="mt-7 grid gap-4 rounded-panel border border-night-line bg-night-raised px-5 py-4 text-on-night"
    data-surface="night"
    data-testid="alignment-proposals"
    :data-section="section"
  >
    <p :id="titleId" class="m-0 text-[15px] font-semibold text-on-night">{{ copy.title }}</p>
    <article
      v-for="card in cards"
      :key="card.code"
      class="grid gap-3 rounded-field border border-night-line bg-night-panel px-4 py-4"
      :aria-labelledby="cardTitleIdOf(card.code)"
      :aria-busy="stateOf(card) === 'applying' || stateOf(card) === 'skipping' ? 'true' : undefined"
      data-testid="alignment-proposal"
      :data-code="card.code"
      :data-state="stateOf(card)"
    >
      <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p :id="cardTitleIdOf(card.code)" class="m-0 text-[15px] font-semibold text-on-night">
          {{ card.title }}
        </p>
        <span class="font-mono text-xs text-on-night-3">{{ card.code }}</span>
      </div>
      <p class="m-0 text-sm text-on-night-3 italic">{{ copy.hypothesis }}</p>
      <label class="grid gap-1.5 text-sm font-medium text-on-night-2" :for="textIdOf(card.code)">
        {{ copy.text }}
      </label>
      <textarea
        :id="textIdOf(card.code)"
        :value="textOf(card)"
        rows="5"
        :maxlength="REQUEST_LIMITS[card.section]"
        :disabled="busy || isSettled(card)"
        class="min-h-11 rounded-field border border-night-line-strong bg-night px-3 py-2.5 text-[15px] leading-normal font-normal text-on-night [color-scheme:dark] disabled:text-on-night-2"
        data-testid="alignment-proposal-text"
        @input="texts[card.code] = ($event.target as HTMLTextAreaElement).value"
      />
      <p class="m-0 text-sm leading-normal text-on-night-2">
        <span class="font-medium">{{ copy.rationale }}:</span> {{ card.rationale }}
      </p>
      <p v-if="subjectsOf(card)" class="m-0 text-sm text-on-night-3">{{ subjectsOf(card) }}</p>
      <details class="text-sm" data-testid="alignment-proposal-why">
        <summary class="min-h-11 cursor-pointer py-3 font-semibold text-on-night-2">
          {{ copy.why }}
        </summary>
        <div class="grid gap-2 pb-3 text-on-night-2">
          <p class="m-0 flex flex-wrap items-baseline gap-x-1">
            <span class="text-on-night-3">{{ copy.commits }}:</span>
            <code class="font-mono text-[13px] text-on-night">{{ shortCommits(card) }}</code>
          </p>
          <p class="m-0 text-on-night-3">{{ copy.files }}:</p>
          <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
            <li v-for="file in card.origin.files" :key="file">
              <code class="font-mono text-[13px] wrap-anywhere text-on-night">{{ file }}</code>
            </li>
          </ul>
          <p class="m-0 text-on-night-3">{{ copy.excerpt }}:</p>
          <pre
            class="m-0 max-h-72 overflow-auto rounded-field border border-night-line bg-night p-3 font-mono text-xs leading-[1.6] wrap-anywhere whitespace-pre-wrap text-on-night-2"
            >{{ card.origin.excerpt }}</pre>
        </div>
      </details>
      <p
        v-if="stateText(card)"
        :role="stateOf(card) === 'failed' ? 'alert' : 'status'"
        tabindex="-1"
        :class="[
          'm-0 text-sm leading-normal outline-none',
          stateOf(card) === 'failed'
            ? 'text-fail-on-night'
            : stateOf(card) === 'applied'
              ? 'font-semibold text-petrol-on-night-2'
              : 'text-on-night-2',
        ]"
        data-testid="alignment-proposal-state"
        :data-state="stateOf(card)"
      >
        {{ stateText(card) }}
      </p>
      <div v-if="!isSettled(card)" class="flex flex-wrap gap-3">
        <UiButton
          variant="outline"
          :disabled="busy || textOf(card).trim().length === 0"
          data-testid="alignment-proposal-apply"
          @click="apply(card)"
        >
          {{ copy.apply }}
        </UiButton>
        <UiButton
          variant="quiet"
          :disabled="busy"
          data-testid="alignment-proposal-skip"
          @click="skip(card)"
        >
          {{ copy.skip }}
        </UiButton>
      </div>
    </article>
  </section>
</template>
