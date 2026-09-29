<script setup lang="ts">
import { computed, ref, useId, watch } from "vue";

import UiButton from "./UiButton.vue";
import { useSurface } from "./UiSurface.vue";

import { apiClient } from "@/api/client";
import {
  RequirementsAlignmentApiError,
  requirementsAlignmentApi,
  type RequirementsAlignmentApi,
} from "@/api/requirementsAlignment";
import { useAuthStore } from "@/stores/auth";
import type { AuthorizedRequest } from "@/stores/requirements";
import type {
  RequirementsAlignmentPayload,
  RequirementsRealignmentPayload,
} from "@/types/requirementsAlignment";

type Locale = "en" | "it";
type Mode = "hidden" | "ready" | "twins" | "revision" | "blocked" | "done";

const props = withDefaults(
  defineProps<{
    projectId: string;
    locale?: Locale;
    refreshKey?: string | number | null;
    authorize?: AuthorizedRequest | undefined;
    api?: RequirementsAlignmentApi | undefined;
  }>(),
  {
    locale: "en",
    refreshKey: null,
    authorize: undefined,
    api: undefined,
  },
);

const emit = defineEmits<{ realigned: [payload: RequirementsRealignmentPayload] }>();

const messages = {
  en: {
    title: "The twins have changed",
    doneTitle: "The requirements follow the current twins",
    ready:
      "These requirements were written for the previous twins. Update them so that they follow the current twins: their content stays the same, and then you approve them again.",
    update: "Update the requirements",
    running: "Updating the requirements…",
    done: "Version {version} of the requirements is ready with the same content. Approve it again below.",
    twins:
      "Approve the twins in the User Twin step first; then come back here to update the requirements.",
    revision:
      "A proposed change to these requirements is waiting for your decision. Apply it or discard it below; then update the requirements.",
    blocked: "These requirements cannot be updated automatically.",
    reasons: {
      REQUIREMENTS_CONTEXT_CHANGED:
        "The brief or the team changed as well, so these requirements cannot be updated automatically.",
      TWIN_NO_LONGER_AVAILABLE:
        "These requirements mention a twin that is no longer part of the project, so they cannot be updated automatically.",
    },
    failed: "The requirements could not be updated. Try again.",
    errors: {
      REQUIREMENTS_NOT_FOUND: "The requirements were not found. Reload the page and try again.",
      USER_TWINS_REQUIRED: "Approve the twins in the User Twin step first, then try again.",
      USER_TWINS_APPROVAL_REQUIRED:
        "Approve the twins in the User Twin step first, then try again.",
      REQUIREMENTS_ALREADY_ALIGNED:
        "The requirements already follow the current twins: there is nothing to update.",
      REQUIREMENTS_REVISION_PENDING:
        "A proposed change to these requirements is waiting for your decision. Apply it or discard it below, then try again.",
      PERSISTENCE_REJECTED:
        "The update could not be saved because the requirements changed in the meantime. Reload the page and try again.",
    },
    details: "Details",
  },
  it: {
    title: "I twin sono cambiati",
    doneTitle: "I requisiti seguono i twin attuali",
    ready:
      "Questi requisiti sono stati scritti per i twin precedenti. Aggiornali perché seguano i twin attuali: il contenuto resta lo stesso, poi li approvi di nuovo.",
    update: "Aggiorna i requisiti",
    running: "Aggiorno i requisiti…",
    done: "La versione {version} dei requisiti è pronta con lo stesso contenuto. Approvala di nuovo qui sotto.",
    twins: "Approva prima i twin nel passo User Twin, poi torna qui per aggiornare i requisiti.",
    revision:
      "Una modifica proposta a questi requisiti aspetta la tua decisione. Applicala o scartala qui sotto, poi aggiorna i requisiti.",
    blocked: "Questi requisiti non si possono aggiornare automaticamente.",
    reasons: {
      REQUIREMENTS_CONTEXT_CHANGED:
        "Sono cambiati anche il brief o la squadra, quindi questi requisiti non si possono aggiornare automaticamente.",
      TWIN_NO_LONGER_AVAILABLE:
        "Questi requisiti citano un twin che non fa più parte del progetto, quindi non si possono aggiornare automaticamente.",
    },
    failed: "Non è stato possibile aggiornare i requisiti. Riprova.",
    errors: {
      REQUIREMENTS_NOT_FOUND: "Non ho trovato i requisiti. Ricarica la pagina e riprova.",
      USER_TWINS_REQUIRED: "Approva prima i twin nel passo User Twin, poi riprova.",
      USER_TWINS_APPROVAL_REQUIRED: "Approva prima i twin nel passo User Twin, poi riprova.",
      REQUIREMENTS_ALREADY_ALIGNED:
        "I requisiti seguono già i twin attuali: non c'è niente da aggiornare.",
      REQUIREMENTS_REVISION_PENDING:
        "Una modifica proposta a questi requisiti aspetta la tua decisione. Applicala o scartala qui sotto, poi riprova.",
      PERSISTENCE_REJECTED:
        "Non è stato possibile salvare l'aggiornamento perché nel frattempo i requisiti sono cambiati. Ricarica la pagina e riprova.",
    },
    details: "Dettagli",
  },
} as const;

const HIDDEN_ISSUES = new Set(["REQUIREMENTS_NOT_FOUND", "REQUIREMENTS_ALREADY_ALIGNED"]);
const TWIN_ISSUES = new Set(["USER_TWINS_REQUIRED", "USER_TWINS_APPROVAL_REQUIRED"]);

const palettes = {
  light: {
    box: "border-action-soft-line bg-action-soft",
    title: "text-ink",
    text: "text-ink-2",
    done: "text-ok-dark",
    muted: "text-ink-3",
    failure: "border-fail-line bg-fail-bg text-fail-dark",
  },
  night: {
    box: "border-petrol-on-night/40 bg-petrol-on-night/8",
    title: "text-on-night",
    text: "text-on-night-2",
    done: "text-petrol-on-night-2",
    muted: "text-on-night-3",
    failure: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
  },
};

const auth = useAuthStore();
const surface = useSurface(() => undefined);
const palette = computed(() => palettes[surface.value]);
const titleId = `requirements-alignment-${useId()}`;
const copy = computed(() => messages[props.locale]);
const api = computed(() => props.api ?? requirementsAlignmentApi);
const alignment = ref<RequirementsAlignmentPayload | null>(null);
const realigned = ref<RequirementsRealignmentPayload | null>(null);
const running = ref(false);
const failure = ref<{ code: string | null } | null>(null);
let sequence = 0;

const mode = computed<Mode>(() => {
  if (realigned.value !== null) return "done";
  const current = alignment.value;
  if (current === null || current.aligned) return "hidden";
  const issue = current.issue;
  if (issue === null) return "ready";
  if (HIDDEN_ISSUES.has(issue)) return "hidden";
  if (TWIN_ISSUES.has(issue)) return "twins";
  return issue === "REQUIREMENTS_REVISION_PENDING" ? "revision" : "blocked";
});

const explanation = computed(() => {
  switch (mode.value) {
    case "ready":
      return copy.value.ready;
    case "twins":
      return copy.value.twins;
    case "revision":
      return copy.value.revision;
    default:
      return lookup(copy.value.reasons, alignment.value?.issue ?? null) ?? copy.value.blocked;
  }
});

const failureText = computed(() => {
  const code = failure.value?.code ?? null;
  return lookup(copy.value.errors, code) ?? lookup(copy.value.reasons, code) ?? copy.value.failed;
});

function lookup(table: Record<string, string>, code: string | null): string | null {
  return code !== null && Object.hasOwn(table, code) ? (table[code] ?? null) : null;
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function authorizedRequest<T>(operation: (accessToken: string) => Promise<T>): Promise<T> {
  return props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);
}

function apply(result: RequirementsAlignmentPayload): void {
  const done = realigned.value;
  if (
    done !== null &&
    (!result.aligned || result.requirements_version_number !== done.version_number)
  ) {
    realigned.value = null;
  }
  alignment.value = result;
}

async function load(): Promise<void> {
  const current = ++sequence;
  const projectId = props.projectId;
  if (projectId.trim().length === 0) {
    alignment.value = null;
    return;
  }
  try {
    const result = await authorizedRequest((token) => api.value.status(projectId, token));
    if (current === sequence) apply(result);
  } catch {
    if (current === sequence) alignment.value = null;
  }
}

async function realign(): Promise<void> {
  if (running.value || mode.value !== "ready") return;
  running.value = true;
  failure.value = null;
  const projectId = props.projectId;
  try {
    const result = await authorizedRequest((token) => api.value.realign(projectId, token));
    if (projectId !== props.projectId) return;
    sequence++;
    realigned.value = result;
    emit("realigned", result);
  } catch (error) {
    if (projectId === props.projectId) {
      failure.value = { code: error instanceof RequirementsAlignmentApiError ? error.code : null };
    }
  } finally {
    running.value = false;
  }
}

watch(
  () => [props.projectId, props.refreshKey] as const,
  ([projectId], previous) => {
    if (previous === undefined || previous[0] !== projectId) {
      alignment.value = null;
      realigned.value = null;
    }
    failure.value = null;
    void load();
  },
  { immediate: true },
);
</script>

<template>
  <section
    v-if="mode !== 'hidden'"
    :class="['grid gap-3 rounded-panel border px-5 py-4', palette.box]"
    :aria-labelledby="titleId"
    data-testid="requirements-twin-alignment"
  >
    <h2 :id="titleId" :class="['m-0 text-[15px] font-semibold', palette.title]">
      {{ mode === "done" ? copy.doneTitle : copy.title }}
    </h2>
    <p
      v-if="mode === 'done'"
      :class="['m-0 max-w-3xl text-sm leading-normal font-semibold', palette.done]"
      role="status"
      data-testid="requirements-twin-alignment-done"
    >
      <span aria-hidden="true">✓</span>
      {{ fill(copy.done, { version: realigned?.version_number ?? "" }) }}
    </p>
    <template v-else>
      <p
        :class="['m-0 max-w-3xl text-sm leading-normal', palette.text]"
        data-testid="requirements-twin-alignment-text"
      >
        {{ explanation }}
      </p>
      <details v-if="mode === 'blocked'" :class="['text-xs', palette.muted]">
        <summary class="min-h-11 cursor-pointer py-3">{{ copy.details }}</summary>
        <code class="font-mono break-all">{{ alignment?.issue }}</code>
      </details>
      <UiButton
        v-if="mode === 'ready'"
        variant="outline"
        class="justify-self-start"
        :disabled="running"
        data-testid="requirements-twin-alignment-update"
        @click="realign"
      >
        {{ copy.update }}
      </UiButton>
      <p
        v-if="running"
        :class="['m-0 text-sm', palette.text]"
        role="status"
        data-testid="requirements-twin-alignment-running"
      >
        {{ copy.running }}
      </p>
    </template>
    <div
      v-if="failure"
      :class="['grid gap-1 rounded-field border px-4 py-3 text-sm', palette.failure]"
      role="alert"
      data-testid="requirements-twin-alignment-error"
    >
      <p class="m-0 font-semibold">{{ failureText }}</p>
      <details v-if="failure.code" class="text-xs">
        <summary class="min-h-11 cursor-pointer py-3">{{ copy.details }}</summary>
        <code class="font-mono break-all">{{ failure.code }}</code>
      </details>
    </div>
  </section>
</template>
