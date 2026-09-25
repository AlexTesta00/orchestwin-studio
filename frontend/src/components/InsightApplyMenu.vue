<script setup lang="ts">
import { computed, ref } from "vue";

import { apiClient } from "@/api/client";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedDesignLoopRequest, useDesignLoopStore } from "@/stores/designLoop";
import type {
  InsightApplicationPayload,
  InsightBriefField,
  InsightSource,
  InsightTarget,
} from "@/types/designLoop";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    projectId: string;
    source: InsightSource;
    locale?: Locale;
    authorize?: AuthorizedDesignLoopRequest | undefined;
    api?: DesignLoopApi | undefined;
  }>(),
  { locale: "en", authorize: undefined, api: undefined },
);

const emit = defineEmits<{ applied: [application: InsightApplicationPayload] }>();

const messages = {
  en: {
    summary: "Bring into the project",
    brief: "Into the brief",
    requirements: "Into the requirements",
    design: "Into the design",
    field: "Brief field",
    busy: "Applying…",
    applied: {
      BRIEF: "Added to the brief ({field}, version {version}).",
      REQUIREMENTS: "Added to the requirements as {code} (version {version}).",
      DESIGN: "Recorded in the design as concern {code} (version {version}).",
    },
    error: "The insight could not be applied.",
    duplicate: "This insight is already in the project.",
    fields: {
      goals: "Goals",
      target_users: "Target users",
      technical_constraints: "Technical constraints",
      functional_requirements: "Functional requirements",
      non_functional_requirements: "Non-functional requirements",
      risks: "Risks",
      stakeholders: "Stakeholders",
      definition_of_done: "Definition of done",
    },
  },
  it: {
    summary: "Porta nel progetto",
    brief: "Nel brief",
    requirements: "Nei requisiti",
    design: "Nel design",
    field: "Campo del brief",
    busy: "Applico…",
    applied: {
      BRIEF: "Aggiunto al brief ({field}, versione {version}).",
      REQUIREMENTS: "Aggiunto ai requisiti come {code} (versione {version}).",
      DESIGN: "Registrato nel design come criticità {code} (versione {version}).",
    },
    error: "Non è stato possibile applicare lo spunto.",
    duplicate: "Questo spunto è già nel progetto.",
    fields: {
      goals: "Obiettivi",
      target_users: "Utenti destinatari",
      technical_constraints: "Vincoli tecnici",
      functional_requirements: "Requisiti funzionali",
      non_functional_requirements: "Requisiti non funzionali",
      risks: "Rischi",
      stakeholders: "Stakeholder",
      definition_of_done: "Definizione di fatto",
    },
  },
} as const;

const auth = useAuthStore();
const store = useDesignLoopStore();
const copy = computed(() => messages[props.locale]);
const briefField = ref<InsightBriefField>("functional_requirements");
const busy = ref(false);
const outcome = ref<string | null>(null);
const failure = ref<string | null>(null);
const fieldOptions = computed(
  () => Object.entries(copy.value.fields) as [InsightBriefField, string][],
);

const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

function fill(template: string, values: Record<string, string | number | null>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

async function apply(target: InsightTarget): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  failure.value = null;
  outcome.value = null;
  try {
    const application = await store.apply(
      props.projectId,
      {
        source_kind: props.source.kind,
        source_id: props.source.id,
        source_twin_id: props.source.twinId ?? null,
        text: props.source.text,
        target,
        brief_field: target === "BRIEF" ? briefField.value : null,
        mitigation: props.source.mitigation ?? null,
      },
      authorize,
      props.api ?? designLoopApi,
    );
    outcome.value = fill(copy.value.applied[target], {
      field: copy.value.fields[briefField.value],
      code: application.target_code,
      version: application.target_version_number,
    });
    emit("applied", application);
  } catch (error) {
    const code = error instanceof Error ? error.message : "";
    failure.value =
      store.error === "INSIGHT_ALREADY_APPLIED" || code === "INSIGHT_ALREADY_APPLIED"
        ? copy.value.duplicate
        : copy.value.error;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <details class="text-xs" data-testid="insight-apply-menu">
    <summary class="cursor-pointer font-semibold text-action">{{ copy.summary }}</summary>
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <label class="flex items-center gap-1 text-ink-2">
        <span class="sr-only">{{ copy.field }}</span>
        <select
          v-model="briefField"
          class="rounded-control border border-field bg-white px-2 py-1 text-xs"
          data-testid="insight-brief-field"
        >
          <option v-for="[value, label] in fieldOptions" :key="value" :value="value">
            {{ label }}
          </option>
        </select>
      </label>
      <button
        type="button"
        class="rounded-control border border-line px-2 py-1 font-semibold text-ink-2 hover:bg-surface-3 disabled:opacity-60"
        :disabled="busy"
        data-testid="insight-apply-brief"
        @click="apply('BRIEF')"
      >
        {{ copy.brief }}
      </button>
      <button
        type="button"
        class="rounded-control border border-line px-2 py-1 font-semibold text-ink-2 hover:bg-surface-3 disabled:opacity-60"
        :disabled="busy"
        data-testid="insight-apply-requirements"
        @click="apply('REQUIREMENTS')"
      >
        {{ copy.requirements }}
      </button>
      <button
        type="button"
        class="rounded-control border border-line px-2 py-1 font-semibold text-ink-2 hover:bg-surface-3 disabled:opacity-60"
        :disabled="busy"
        data-testid="insight-apply-design"
        @click="apply('DESIGN')"
      >
        {{ copy.design }}
      </button>
      <span v-if="busy" class="text-ink-3" aria-live="polite">{{ copy.busy }}</span>
    </div>
    <p v-if="outcome" class="m-0 mt-2 font-semibold text-ok-dark" data-testid="insight-applied">
      {{ outcome }}
    </p>
    <p v-if="failure" class="m-0 mt-2 font-semibold text-fail-dark" role="alert">
      {{ failure }}
    </p>
  </details>
</template>
