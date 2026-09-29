<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { apiClient } from "@/api/client";
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

const props = withDefaults(
  defineProps<{
    projectId: string;
    designRequirementsVersionId?: string | null;
    refreshKey?: number;
    busy?: boolean;
    locale?: Locale;
    authorize?: AuthorizedRequest | undefined;
    api?: Pick<RequirementsApi, "readiness" | "submitGate" | "decideGate"> | undefined;
  }>(),
  {
    designRequirementsVersionId: null,
    refreshKey: 0,
    busy: false,
    locale: "en",
    authorize: undefined,
    api: undefined,
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
    step: "Step {n}",
    stepOne: "Approve the requirements again",
    stepOneDone: "Requirements approved",
    stepOneHint: "Want to check the change first? Open the Requirements step.",
    approving: "Approving the requirements…",
    stepTwo: "Regenerate the design alternatives",
    stepTwoLocked: "Available after step 1.",
    briefTitle: "The brief has a new version",
    brief:
      "You added an idea to the brief (version {version}). Open the Brief step and approve the new version, then update and approve the requirements. Then come back here and regenerate the design alternatives.",
    manual:
      "The requirements need your review in the Requirements step before they can be approved.",
    failed:
      "The requirements could not be approved. Try again, or approve them in the Requirements step.",
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
    step: "Passo {n}",
    stepOne: "Riapprova i requisiti",
    stepOneDone: "Requisiti approvati",
    stepOneHint: "Vuoi prima controllare la modifica? Apri il passo Requisiti.",
    approving: "Approvo i requisiti…",
    stepTwo: "Rigenera le alternative di design",
    stepTwoLocked: "Disponibile dopo il passo 1.",
    briefTitle: "Il brief ha una nuova versione",
    brief:
      "Hai aggiunto uno spunto al brief (versione {version}). Apri il passo Brief e approva la nuova versione, poi aggiorna e approva i requisiti. Infine torna qui e rigenera le alternative di design.",
    manual: "I requisiti vanno controllati nel passo Requisiti prima di poterli approvare.",
    failed:
      "Non è stato possibile approvare i requisiti. Riprova, oppure approvali nel passo Requisiti.",
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
const readiness = ref<RequirementsReadinessPayload | null>(null);
const reapproved = ref(false);
const approving = ref(false);
const failure = ref<{ code: string; manual: boolean } | null>(null);
let sequence = 0;

const authorize: AuthorizedRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

const lastApplication = computed(() =>
  loopStore.projectId === props.projectId ? loopStore.lastApplication : null,
);
const needsApproval = computed(() => readiness.value?.status === "REQUIREMENTS_APPROVAL_REQUIRED");
const designOutdated = computed(() => {
  const version = readiness.value?.version ?? null;
  return (
    readiness.value?.status === "READY_FOR_DESIGN_EXPLORATION" &&
    version !== null &&
    props.designRequirementsVersionId !== null &&
    version.id !== props.designRequirementsVersionId
  );
});
const mode = computed<"brief" | "steps" | "idle">(() => {
  if (lastApplication.value?.target === "BRIEF") return "brief";
  if (needsApproval.value || designOutdated.value || reapproved.value) return "steps";
  return "idle";
});
const stepOneDone = computed(() => !needsApproval.value);
const title = computed(() =>
  needsApproval.value ? copy.value.changedTitle : copy.value.outdatedTitle,
);
const explanation = computed(() => {
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

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
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

async function load(): Promise<void> {
  const current = ++sequence;
  const projectId = props.projectId;
  try {
    const result = await authorize((token) => api.value.readiness(projectId, token));
    if (current === sequence) readiness.value = result;
  } catch {
    if (current === sequence) readiness.value = null;
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
    sequence++;
    readiness.value = result;
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

watch(() => [props.projectId, props.refreshKey] as const, refresh, { immediate: true });
</script>

<template>
  <div class="grid gap-3">
    <section
      v-if="mode === 'steps'"
      class="grid gap-3 rounded-tile border border-petrol-on-night/35 bg-petrol-on-night/8 p-5 text-on-night"
      :aria-labelledby="titleId"
      data-testid="design-next-step"
    >
      <p class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase">
        {{ copy.eyebrow }}
      </p>
      <h4 :id="titleId" class="m-0 text-[17px] font-semibold">{{ title }}</h4>
      <p class="m-0 max-w-3xl text-[15px] leading-normal text-on-night-2">{{ explanation }}</p>
      <ol class="m-0 grid list-none gap-3 p-0 md:grid-cols-2">
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
    <slot v-if="mode !== 'steps'" />
  </div>
</template>
