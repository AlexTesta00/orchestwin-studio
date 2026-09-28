<script setup lang="ts">
import { computed, ref, useId } from "vue";

import { apiClient } from "@/api/client";
import { designLoopApi, type DesignLoopApi } from "@/api/designLoop";
import { useAuthStore } from "@/stores/auth";
import { type AuthorizedDesignLoopRequest, useDesignLoopStore } from "@/stores/designLoop";
import { MAX_TRAY_ITEMS, useInsightTrayStore } from "@/stores/insightTray";
import type {
  InsightApplicationPayload,
  InsightBriefField,
  InsightSource,
} from "@/types/designLoop";

type Locale = "en" | "it";
type ProjectTarget = "REQUIREMENTS" | "DESIGN";

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
    requirements: "Into the requirements",
    design: "Into the design",
    brief: "Set aside for the brief",
    briefSetAside: "Set aside for the brief",
    briefNote:
      "In the brief it changes the starting point: brief, team, twins, requirements and design will need approval again.",
    briefFull: "You have already set aside {max} insights, the most for one brief version.",
    field: "Brief field",
    busy: "Applying…",
    applied: {
      REQUIREMENTS: "Added to the requirements as {code} (version {version}).",
      DESIGN: "Recorded in the design as concern {code} (version {version}).",
    },
    error: "The insight could not be applied.",
    duplicate: "This insight is already in the project.",
    dismissed: "You marked this finding as not relevant, so it is not brought into the project.",
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
    requirements: "Nei requisiti",
    design: "Nel design",
    brief: "Metti da parte per il brief",
    briefSetAside: "Messo da parte per il brief",
    briefNote:
      "Nel brief cambia il punto di partenza: brief, squadra, twin, requisiti e design andranno approvati di nuovo.",
    briefFull: "Hai già messo da parte {max} spunti, il massimo per una versione del brief.",
    field: "Campo del brief",
    busy: "Applico…",
    applied: {
      REQUIREMENTS: "Aggiunto ai requisiti come {code} (versione {version}).",
      DESIGN: "Registrato nel design come criticità {code} (versione {version}).",
    },
    error: "Non è stato possibile applicare lo spunto.",
    duplicate: "Questo spunto è già nel progetto.",
    dismissed:
      "Hai segnato questa osservazione come non pertinente, quindi non viene portata nel progetto.",
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
const tray = useInsightTrayStore();
const noteId = `insight-brief-note-${useId()}`;
const copy = computed(() => messages[props.locale]);
const briefField = ref<InsightBriefField>("functional_requirements");
const busy = ref(false);
const outcome = ref<string | null>(null);
const failure = ref<string | null>(null);
const fieldOptions = computed(
  () => Object.entries(copy.value.fields) as [InsightBriefField, string][],
);
const setAside = computed(() => tray.itemOf(props.projectId, props.source.kind, props.source.id));
const trayFull = computed(() => setAside.value === null && tray.isFull(props.projectId));
const chosenField = computed<InsightBriefField>({
  get: () => setAside.value?.briefField ?? briefField.value,
  set: (value) => {
    briefField.value = value;
  },
});

const authorize: AuthorizedDesignLoopRequest = (operation) =>
  props.authorize ? props.authorize(operation) : auth.withAccessToken(apiClient, operation);

function fill(template: string, values: Record<string, string | number | null>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

async function apply(target: ProjectTarget): Promise<void> {
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
        brief_field: null,
        mitigation: props.source.mitigation ?? null,
      },
      authorize,
      props.api ?? designLoopApi,
    );
    outcome.value = fill(copy.value.applied[target], {
      code: application.target_code,
      version: application.target_version_number,
    });
    emit("applied", application);
  } catch (error) {
    const code = error instanceof Error ? error.message : "";
    if (store.error === "INSIGHT_ALREADY_APPLIED" || code === "INSIGHT_ALREADY_APPLIED") {
      failure.value = copy.value.duplicate;
    } else if (store.error === "INSIGHT_SOURCE_DISMISSED" || code === "INSIGHT_SOURCE_DISMISSED") {
      failure.value = copy.value.dismissed;
    } else {
      failure.value = copy.value.error;
    }
  } finally {
    busy.value = false;
  }
}

function setAsideForBrief(): void {
  if (busy.value || setAside.value !== null) return;
  failure.value = null;
  outcome.value = null;
  tray.add(props.projectId, {
    sourceKind: props.source.kind,
    sourceId: props.source.id,
    sourceTwinId: props.source.twinId ?? null,
    text: props.source.text,
    briefField: briefField.value,
  });
}
</script>

<template>
  <details class="text-xs" data-testid="insight-apply-menu">
    <summary class="cursor-pointer font-semibold text-action">{{ copy.summary }}</summary>
    <div class="mt-2 grid gap-3">
      <div class="flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="inline-flex min-h-11 items-center rounded-control bg-action px-3 font-semibold text-white transition-colors hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
          :disabled="busy"
          data-testid="insight-apply-design"
          @click="apply('DESIGN')"
        >
          {{ copy.design }}
        </button>
        <button
          type="button"
          class="inline-flex min-h-11 items-center rounded-control border border-button-line bg-surface px-3 font-semibold text-ink transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
          :disabled="busy"
          data-testid="insight-apply-requirements"
          @click="apply('REQUIREMENTS')"
        >
          {{ copy.requirements }}
        </button>
        <span v-if="busy" class="text-ink-3" aria-live="polite">{{ copy.busy }}</span>
      </div>
      <div class="grid gap-1.5 border-t border-line-soft pt-2" data-testid="insight-brief-option">
        <div class="flex flex-wrap items-center gap-2">
          <label class="flex items-center text-ink-2">
            <span class="sr-only">{{ copy.field }}</span>
            <select
              v-model="chosenField"
              class="min-h-11 rounded-control border border-field bg-white px-2 text-xs disabled:opacity-60"
              :disabled="setAside !== null"
              data-testid="insight-brief-field"
            >
              <option v-for="[value, label] in fieldOptions" :key="value" :value="value">
                {{ label }}
              </option>
            </select>
          </label>
          <button
            type="button"
            class="inline-flex min-h-11 items-center rounded-control border border-line px-3 font-semibold text-ink-2 transition-colors hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
            :disabled="busy || setAside !== null || trayFull"
            :aria-describedby="noteId"
            data-testid="insight-apply-brief"
            @click="setAsideForBrief"
          >
            {{ setAside === null ? copy.brief : copy.briefSetAside }}
          </button>
        </div>
        <p :id="noteId" class="m-0 leading-5 text-ink-3" data-testid="insight-brief-note">
          {{ copy.briefNote }}
        </p>
        <p v-if="trayFull" class="m-0 leading-5 text-ink-2" data-testid="insight-brief-full">
          {{ fill(copy.briefFull, { max: MAX_TRAY_ITEMS }) }}
        </p>
        <span class="sr-only" aria-live="polite">
          {{ setAside === null ? "" : copy.briefSetAside }}
        </span>
      </div>
    </div>
    <p v-if="outcome" class="m-0 mt-2 font-semibold text-ok-dark" data-testid="insight-applied">
      {{ outcome }}
    </p>
    <p v-if="failure" class="m-0 mt-2 font-semibold text-fail-dark" role="alert">
      {{ failure }}
    </p>
  </details>
</template>
