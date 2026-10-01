<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { apiClient } from "@/api/client";
import {
  designAlignmentApi,
  type DesignAlignmentApi,
  type DesignAlignmentPayload,
} from "@/api/designAlignment";
import { RequirementsApiError, requirementsApi, type RequirementsApi } from "@/api/requirements";
import { useAuthStore } from "@/stores/auth";
import { useDesignLoopStore } from "@/stores/designLoop";
import type { AuthorizedRequest } from "@/stores/requirements";
import type {
  HumanGatePayload,
  RequirementsReadinessPayload,
  RequirementsSpecificationVersionPayload,
} from "@/types/requirements";

type Locale = "en" | "it";
type Mode = "brief" | "steps" | "approve" | "reanchor" | "blocked" | "uncovered" | "idle";

const APPROVAL_REQUIRED = "REQUIREMENTS_APPROVAL_REQUIRED";
const BLOCKING_ISSUES = new Set(["REQUIREMENT_NO_LONGER_AVAILABLE", "TWIN_SET_CHANGED"]);
const PANEL_MODES = new Set<Mode>(["steps", "approve", "blocked"]);
const SLOT_MODES = new Set<Mode>(["brief", "uncovered", "idle"]);

const props = withDefaults(
  defineProps<{
    projectId: string;
    designRequirementsVersionId?: string | null;
    designVersionId?: string | null;
    designApproved?: boolean;
    refreshKey?: number;
    busy?: boolean;
    locale?: Locale;
    authorize?: AuthorizedRequest | undefined;
    api?: Pick<RequirementsApi, "readiness" | "submitGate" | "decideGate"> | undefined;
    alignmentApi?: Pick<DesignAlignmentApi, "status"> | undefined;
  }>(),
  {
    designRequirementsVersionId: null,
    designVersionId: null,
    designApproved: false,
    refreshKey: 0,
    busy: false,
    locale: "en",
    authorize: undefined,
    api: undefined,
    alignmentApi: undefined,
  },
);

const emit = defineEmits<{ regenerate: []; reapproved: [] }>();

const messages = {
  en: {
    eyebrow: "Next step",
    changedTitle: "The requirements have changed",
    changedFromInsight:
      "You brought an idea into the requirements as {code} (version {version}). The design can use it only after you approve the updated requirements.",
    changed:
      "The requirements have a new version that you have not approved yet. The design can use it only after you approve it.",
    outdatedTitle: "Now update the design",
    outdated:
      "The requirements are approved. Regenerate the design alternatives so that they follow the new version.",
    reanchor:
      "The design is anchored to Definition v{old}; now there is v{new}. The alternatives stay: use «Update and confirm» above to re-anchor it.",
    reanchorApprove:
      "The design is anchored to Definition v{old}; now there is v{new}. The alternatives stay: approve the design in the bar at the bottom, then use «Update and confirm» above to re-anchor it.",
    blocked: "{section} cannot be updated by itself: {reason}.",
    section: "Design & Evaluation",
    reasons: {
      REQUIREMENT_NO_LONGER_AVAILABLE:
        "the design cites {codes}, which the Definition no longer contains: regenerate the alternatives in the Design & Evaluation step",
      TWIN_SET_CHANGED: "the twins are no longer the same",
    },
    uncovered:
      "New requirements that the design does not cover yet: {codes}. Ask for a change to the design to cover them.",
    step: "Step {n}",
    stepOne: "Approve the requirements again",
    stepOneDone: "Requirements approved",
    stepOneHint: "Want to check the change first? Open the Definition.",
    approving: "Approving the requirements…",
    stepTwo: "Regenerate the design alternatives",
    stepTwoLocked: "Available after step 1.",
    briefTitle: "The brief has a new version",
    brief:
      "You added an idea to the brief (version {version}). Open the Brief and approve the new version, then update and approve the requirements in the Definition. Then come back here to update the design.",
    manual: "The requirements need your review in the Definition before they can be approved.",
    failed: "The requirements could not be approved. Try again, or approve them in the Definition.",
    details: "Details",
  },
  it: {
    eyebrow: "Prossimo passo",
    changedTitle: "I requisiti sono cambiati",
    changedFromInsight:
      "Hai portato uno spunto nei requisiti come {code} (versione {version}). Il design potrà usarlo solo dopo che avrai approvato i requisiti aggiornati.",
    changed:
      "I requisiti hanno una nuova versione che non hai ancora approvato. Il design potrà usarla solo dopo la tua approvazione.",
    outdatedTitle: "Ora aggiorna il design",
    outdated:
      "I requisiti sono approvati. Rigenera le alternative di design perché seguano la nuova versione.",
    reanchor:
      "Il design è agganciato alla Definizione v{old}; ora c'è la v{new}. Le alternative restano: usa «Aggiorna e conferma» qui sopra per riagganciarlo.",
    reanchorApprove:
      "Il design è agganciato alla Definizione v{old}; ora c'è la v{new}. Le alternative restano: approva il design dalla barra in fondo, poi usa «Aggiorna e conferma» qui sopra per riagganciarlo.",
    blocked: "{section} non si aggiorna da sola: {reason}.",
    section: "Design e valutazione",
    reasons: {
      REQUIREMENT_NO_LONGER_AVAILABLE:
        "il design cita {codes}, che la Definizione non contiene più: rigenera le alternative nel passo Design e valutazione",
      TWIN_SET_CHANGED: "i twin non sono più gli stessi",
    },
    uncovered:
      "Requisiti nuovi che il design non copre ancora: {codes}. Chiedi una modifica al design per coprirli.",
    step: "Passo {n}",
    stepOne: "Riapprova i requisiti",
    stepOneDone: "Requisiti approvati",
    stepOneHint: "Vuoi prima controllare la modifica? Apri la Definizione.",
    approving: "Approvo i requisiti…",
    stepTwo: "Rigenera le alternative di design",
    stepTwoLocked: "Disponibile dopo il passo 1.",
    briefTitle: "Il brief ha una nuova versione",
    brief:
      "Hai aggiunto uno spunto al brief (versione {version}). Apri il Brief e approva la nuova versione, poi aggiorna e approva i requisiti nella Definizione. Infine torna qui per aggiornare il design.",
    manual: "I requisiti vanno controllati nella Definizione prima di poterli approvare.",
    failed:
      "Non è stato possibile approvare i requisiti. Riprova, oppure approvali nella Definizione.",
    details: "Dettagli",
  },
} as const;

class StepFailure extends Error {
  readonly code: string;
  readonly manual: boolean;

  constructor(code: string, manual: boolean) {
    super(code);
    this.code = code;
    this.manual = manual;
  }
}

const auth = useAuthStore();
const loopStore = useDesignLoopStore();
const titleId = `design-next-step-${useId()}`;
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? requirementsApi);
const alignmentApi = computed(() => props.alignmentApi ?? designAlignmentApi);
const readiness = ref<RequirementsReadinessPayload | null>(null);
const alignment = ref<DesignAlignmentPayload | null>(null);
const reapproved = ref(false);
const approving = ref(false);
const failure = ref<{ code: string; manual: boolean } | null>(null);
let sequence = 0;

const authorize: AuthorizedRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const lastApplication = computed(() =>
  loopStore.projectId === props.projectId ? loopStore.lastApplication : null,
);
const needsApproval = computed(
  () =>
    readiness.value?.status === APPROVAL_REQUIRED || alignment.value?.issue === APPROVAL_REQUIRED,
);
const designOutdated = computed(() => {
  const version = readiness.value?.version ?? null;
  return (
    readiness.value?.status === "READY_FOR_DESIGN_EXPLORATION" &&
    version !== null &&
    props.designRequirementsVersionId !== null &&
    version.id !== props.designRequirementsVersionId
  );
});
const mode = computed<Mode>(() => {
  if (lastApplication.value?.target === "BRIEF") return "brief";
  const value = alignment.value;
  if (value === null) {
    return needsApproval.value || designOutdated.value || reapproved.value ? "steps" : "idle";
  }
  if (needsApproval.value) return "approve";
  if (value.issue === null && !value.aligned) return "reanchor";
  if (value.issue !== null && BLOCKING_ISSUES.has(value.issue)) return "blocked";
  if (value.aligned && value.uncovered_codes.length > 0) return "uncovered";
  return "idle";
});
const stepOneDone = computed(() => !needsApproval.value);
const title = computed(() =>
  needsApproval.value ? copy.value.changedTitle : copy.value.outdatedTitle,
);
const blockedSentence = computed(() => {
  const value = alignment.value;
  const reasons: Readonly<Record<string, string>> = copy.value.reasons;
  const reason = reasons[value?.issue ?? ""];
  if (value === null || reason === undefined) return "";
  return fill(copy.value.blocked, {
    section: copy.value.section,
    reason: fill(reason, { codes: listOf(value.missing_codes) }),
  });
});
const explanation = computed(() => {
  if (mode.value === "blocked") return blockedSentence.value;
  if (!needsApproval.value) return copy.value.outdated;
  const application = lastApplication.value;
  if (application?.target === "REQUIREMENTS" && application.target_code !== null) {
    return fill(copy.value.changedFromInsight, {
      code: application.target_code,
      version: application.target_version_number,
    });
  }
  return copy.value.changed;
});
const reanchorSentence = computed(() =>
  fill(props.designApproved ? copy.value.reanchor : copy.value.reanchorApprove, {
    old: alignment.value?.grounded_requirements_version_number ?? "",
    new: alignment.value?.requirements_version_number ?? "",
  }),
);
const uncoveredSentence = computed(() =>
  fill(copy.value.uncovered, { codes: listOf(alignment.value?.uncovered_codes ?? []) }),
);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function listOf(codes: readonly string[]): string {
  return new Intl.ListFormat(props.locale, { type: "conjunction" }).format(codes);
}

function targetsVersion(
  gate: HumanGatePayload,
  version: RequirementsSpecificationVersionPayload,
): boolean {
  return (
    gate.artifact.artifact_id === version.id &&
    gate.artifact.version === version.version_number &&
    gate.artifact.content_hash === version.content_hash
  );
}

async function readReadiness(projectId: string): Promise<RequirementsReadinessPayload | null> {
  try {
    return await authorize((token) => api.value.readiness(projectId, token));
  } catch {
    return null;
  }
}

async function readAlignment(projectId: string): Promise<DesignAlignmentPayload | null> {
  try {
    return await authorize((token) => alignmentApi.value.status(projectId, token));
  } catch {
    return null;
  }
}

async function load(): Promise<void> {
  const current = ++sequence;
  const projectId = props.projectId;
  const [nextReadiness, nextAlignment] = await Promise.all([
    readReadiness(projectId),
    readAlignment(projectId),
  ]);
  if (current === sequence) {
    readiness.value = nextReadiness;
    alignment.value = nextAlignment;
  }
}

function refresh(): void {
  reapproved.value = false;
  failure.value = null;
  void load();
}

async function approveRequirements(projectId: string): Promise<void> {
  const current = await authorize((token) => api.value.readiness(projectId, token));
  if (current.status === "READY_FOR_DESIGN_EXPLORATION") return;
  const version = current.version;
  if (version === null) throw new StepFailure(current.status, true);
  const gate = current.gate;
  const status = gate !== null && targetsVersion(gate, version) ? gate.status : null;
  if (status === "APPROVED") return;
  if (status === null || status === "DRAFT" || status === "STALE") {
    const submission = await authorize((token) => api.value.submitGate(projectId, token));
    if (submission.status === "ALREADY_APPROVED") return;
    if (submission.status !== "SUBMITTED" && submission.status !== "ALREADY_PENDING") {
      throw new StepFailure(submission.issue ?? submission.status, true);
    }
  } else if (status !== "PENDING_APPROVAL") {
    throw new StepFailure(status, true);
  }
  const decision = await authorize((token) =>
    api.value.decideGate(projectId, { action: "APPROVE", reason: null }, token),
  );
  if (decision.status !== "APPLIED") {
    throw new StepFailure(decision.issue ?? decision.status, false);
  }
}

function failureOf(error: unknown): { code: string; manual: boolean } {
  if (error instanceof StepFailure) return { code: error.code, manual: error.manual };
  if (error instanceof RequirementsApiError) {
    return { code: error.code ?? error.message, manual: false };
  }
  return {
    code: error instanceof Error ? error.message : "REQUIREMENTS_APPROVAL_FAILED",
    manual: false,
  };
}

async function reapprove(): Promise<void> {
  if (approving.value || props.busy) return;
  approving.value = true;
  failure.value = null;
  const projectId = props.projectId;
  try {
    await approveRequirements(projectId);
    const result = await authorize((token) => api.value.readiness(projectId, token));
    const nextAlignment = await readAlignment(projectId);
    sequence++;
    readiness.value = result;
    alignment.value = nextAlignment;
    if (result.status !== "READY_FOR_DESIGN_EXPLORATION") {
      throw new StepFailure(result.status, true);
    }
    reapproved.value = true;
    emit("reapproved");
  } catch (error) {
    failure.value = failureOf(error);
  } finally {
    approving.value = false;
  }
}

function regenerate(): void {
  if (!stepOneDone.value || approving.value || props.busy) return;
  emit("regenerate");
}

watch(() => [props.projectId, props.refreshKey, props.designVersionId] as const, refresh, {
  immediate: true,
});
</script>

<template>
  <div class="grid gap-3">
    <section
      v-if="PANEL_MODES.has(mode)"
      class="grid gap-3 rounded-tile border border-petrol-on-night/35 bg-petrol-on-night/8 p-5 text-on-night"
      :aria-labelledby="titleId"
      :data-mode="mode"
      data-testid="design-next-step"
    >
      <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h4 :id="titleId" class="m-0 text-[17px] font-semibold">{{ title }}</h4>
      <p class="m-0 max-w-3xl text-[15px] leading-normal text-on-night-2">{{ explanation }}</p>
      <ol :class="['m-0 grid list-none gap-3 p-0', mode === 'approve' ? '' : 'md:grid-cols-2']">
        <li
          class="grid content-start gap-2 rounded-field border border-night-line bg-night-raised p-4"
          :data-done="stepOneDone"
          data-testid="design-next-step-1"
        >
          <p class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ fill(copy.step, { n: 1 }) }}
          </p>
          <p
            v-if="stepOneDone"
            class="m-0 text-sm font-semibold text-petrol-on-night-2"
            data-testid="design-next-step-1-done"
          >
            <span aria-hidden="true">✓</span> {{ copy.stepOneDone }}
          </p>
          <template v-else>
            <UiButton
              variant="pill"
              class="justify-self-start"
              :disabled="approving || busy"
              data-testid="design-reapprove-requirements"
              @click="reapprove"
            >
              {{ copy.stepOne }}
            </UiButton>
            <p class="m-0 text-[13px] text-on-night-3">{{ copy.stepOneHint }}</p>
          </template>
          <p v-if="approving" class="m-0 text-sm text-on-night-2" aria-live="polite">
            {{ copy.approving }}
          </p>
        </li>
        <li
          v-if="mode !== 'approve'"
          class="grid content-start gap-2 rounded-field border border-night-line bg-night-raised p-4"
          data-testid="design-next-step-2"
        >
          <p class="m-0 font-mono text-[11px] tracking-label text-on-night-3 uppercase">
            {{ fill(copy.step, { n: 2 }) }}
          </p>
          <UiButton
            :variant="stepOneDone ? 'pill' : 'outline'"
            class="justify-self-start"
            :disabled="!stepOneDone || approving || busy"
            data-testid="design-next-regenerate"
            @click="regenerate"
          >
            {{ copy.stepTwo }}
          </UiButton>
          <p v-if="!stepOneDone" class="m-0 text-[13px] text-on-night-3">
            {{ copy.stepTwoLocked }}
          </p>
        </li>
      </ol>
      <div
        v-if="failure"
        class="grid gap-1 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm text-fail-on-night"
        role="alert"
        data-testid="design-next-step-error"
      >
        <p class="m-0 font-semibold">{{ failure.manual ? copy.manual : copy.failed }}</p>
        <details class="text-xs">
          <summary class="inline-flex min-h-11 cursor-pointer items-center">
            {{ copy.details }}
          </summary>
          <code class="break-all">{{ failure.code }}</code>
        </details>
      </div>
    </section>
    <section
      v-else-if="mode === 'reanchor'"
      class="grid gap-2 rounded-tile border border-petrol-on-night/35 bg-petrol-on-night/8 p-5 text-on-night"
      :aria-labelledby="titleId"
      data-testid="design-next-step-reanchor"
    >
      <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h4 :id="titleId" class="m-0 text-[17px] font-semibold">{{ copy.outdatedTitle }}</h4>
      <p class="m-0 max-w-3xl text-[15px] leading-normal text-on-night-2">
        {{ reanchorSentence }}
      </p>
    </section>
    <section
      v-else-if="mode === 'brief'"
      class="grid gap-2 rounded-tile border border-petrol-on-night/35 bg-petrol-on-night/8 p-5 text-on-night"
      :aria-labelledby="titleId"
      data-testid="design-next-step-brief"
    >
      <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h4 :id="titleId" class="m-0 text-[17px] font-semibold">{{ copy.briefTitle }}</h4>
      <p class="m-0 max-w-3xl text-[15px] leading-normal text-on-night-2">
        {{ fill(copy.brief, { version: lastApplication?.target_version_number ?? "" }) }}
      </p>
    </section>
    <p
      v-else-if="mode === 'uncovered'"
      class="m-0 max-w-3xl rounded-field border border-petrol-on-night/35 bg-petrol-on-night/8 px-4 py-3 text-[15px] leading-normal text-on-night-2"
      data-testid="design-next-step-uncovered"
    >
      {{ uncoveredSentence }}
    </p>
    <slot v-if="SLOT_MODES.has(mode)" />
  </div>
</template>
