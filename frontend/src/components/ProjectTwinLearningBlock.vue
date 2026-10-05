<script setup lang="ts">
import { computed, provide, watch } from "vue";

import UiClaimFrame from "./UiClaimFrame.vue";
import { surfaceKey, type SurfaceContext } from "./UiSurface.vue";

import type { TwinLearningApi } from "../api/twinLearning";
import { useTwinLearningStore, type AuthorizedRequest } from "../stores/twinLearning";
import type {
  LearnedObservationPayload,
  LearningTwinPayload,
  TwinUpdateMaterialPayload,
} from "../types/twinLearning";

type Locale = "en" | "it";

interface Subject {
  key: string;
  code: string;
  title: string | null;
}

const props = withDefaults(
  defineProps<{
    projectId: string;
    authorize: AuthorizedRequest;
    locale?: Locale;
    api?: TwinLearningApi | undefined;
    requirementTitles?: Readonly<Record<string, string>>;
    screenTitles?: Readonly<Record<string, string>>;
  }>(),
  {
    locale: "en",
    api: undefined,
    requirementTitles: () => ({}),
    screenTitles: () => ({}),
  },
);

provide(
  surfaceKey,
  computed<SurfaceContext>(() => "night"),
);

const messages = {
  en: {
    title: "What the twins learned",
    intro:
      "During the development each twin learns from its own critiques and from you. An observation becomes part of the twin only when you approve it, and each change raises the number after the dot in its version: 1.2 is profile version 1 with two changes.",
    loadFailed: "What the twins learned could not be loaded.",
    loadFailedCode: "What the twins learned could not be loaded ({code}).",
    noModel:
      "On this Studio the twins cannot propose what they learned: connect a model. You can still write an observation yourself with `ut twins learn`.",
    version: "version {label}",
    nothing: "Nothing learned yet.",
    source: {
      TWIN_CRITIQUE: "From its critiques, approved on {date}",
      OWNER: "Written by you on {date}",
    },
    basis: "Based on",
    about: "About",
    contradicts: "It contradicts the profile",
    retired: ["1 observation was retired.", "{count} observations were retired."],
    pending: "A proposal waits for your decision: `ut twins update`.",
    pendingEvidence:
      "An evidence proposal waits for your decision in the User Twin step. Review its exact quotes and refused changes there.",
    newMaterial: "It has new critiques to learn from, on {material}: `ut twins update`.",
    changes: ["1 commit", "{count} commits"],
    tests: ["1 test run", "{count} test runs"],
    terminal:
      "Everything happens in the terminal: `ut twins update` has the twins propose what they learned, `ut twins learn` writes an observation of your own, `ut twins forget` retires one.",
  },
  it: {
    title: "Che cosa hanno imparato i twin",
    intro:
      "Durante lo sviluppo ogni twin impara dalle proprie critiche e da te. Un'osservazione entra nel twin solo quando la approvi, e ogni cambiamento aumenta il numero dopo il punto nella sua versione: 1.2 è il profilo versione 1 con due cambiamenti.",
    loadFailed: "Non è stato possibile caricare ciò che hanno imparato i twin.",
    loadFailedCode: "Non è stato possibile caricare ciò che hanno imparato i twin ({code}).",
    noModel:
      "In questo Studio i twin non possono proporre ciò che hanno imparato: collega un modello. Puoi comunque scrivere tu un'osservazione con `ut twins learn`.",
    version: "versione {label}",
    nothing: "Non ha ancora imparato nulla.",
    source: {
      TWIN_CRITIQUE: "Dalle sue critiche, approvata il {date}",
      OWNER: "Scritta da te il {date}",
    },
    basis: "Si basa su",
    about: "Riguarda",
    contradicts: "Contraddice il profilo",
    retired: ["1 osservazione è stata ritirata.", "{count} osservazioni sono state ritirate."],
    pending: "Una proposta attende la tua decisione: `ut twins update`.",
    pendingEvidence:
      "Una proposta da evidenza attende la tua decisione nel passo User Twin. Lì trovi le citazioni esatte e i cambiamenti rifiutati.",
    newMaterial: "Ha nuove critiche da cui imparare, su {material}: `ut twins update`.",
    changes: ["1 commit", "{count} commit"],
    tests: ["1 verifica", "{count} verifiche"],
    terminal:
      "Tutto avviene nel terminale: `ut twins update` fa proporre ai twin ciò che hanno imparato, `ut twins learn` scrive una tua osservazione, `ut twins forget` ne ritira una.",
  },
} as const;

const store = useTwinLearningStore();

const copy = computed(() => messages[props.locale]);
const intlLocale = computed(() => (props.locale === "it" ? "it-IT" : "en-GB"));

const current = computed(() => store.projectId === props.projectId);
const twins = computed<LearningTwinPayload[]>(() => (current.value ? store.twins : []));
const updateAvailable = computed(() => current.value && store.updateAvailable);
const failure = computed(() => (current.value ? store.failure : null));

const dateFormat = computed(
  () =>
    new Intl.DateTimeFormat(intlLocale.value, {
      dateStyle: "medium",
      timeStyle: "short",
    }),
);

const listFormat = computed(
  () => new Intl.ListFormat(intlLocale.value, { style: "long", type: "conjunction" }),
);

const failureText = computed(() => {
  const value = failure.value;
  if (value === null) {
    return null;
  }
  return value.code === null
    ? copy.value.loadFailed
    : fill(copy.value.loadFailedCode, { code: value.code });
});

const twinViews = computed(() =>
  twins.value.map((twin) => ({
    key: twin.twin_id,
    name: twin.twin_name,
    label: fill(copy.value.version, { label: twin.label }),
    observations: twin.observations.map(observationView),
    retired: twin.retired.length === 0 ? null : plural(twin.retired.length, copy.value.retired),
    pending: twin.pending_update !== null,
    pendingEvidence: twin.pending_update?.evidence !== undefined,
    material:
      twin.pending_update === null && updateAvailable.value
        ? materialText(twin.new_material)
        : null,
  })),
);

const visible = computed(() => twinViews.value.length > 0 || failureText.value !== null);

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => String(values[key] ?? ""));
}

function plural(count: number, forms: readonly [string, string]): string {
  return fill(count === 1 ? forms[0] : forms[1], { count });
}

function commandParts(text: string): { key: number; text: string; command: boolean }[] {
  return text
    .split("`")
    .map((part, index) => ({ key: index, text: part, command: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

function formatDate(value: string): string {
  const time = Date.parse(value);
  return Number.isNaN(time) ? value : dateFormat.value.format(time);
}

function materialText(material: TwinUpdateMaterialPayload): string | null {
  const parts: string[] = [];
  if (material.changes > 0) {
    parts.push(plural(material.changes, copy.value.changes));
  }
  if (material.tests > 0) {
    parts.push(plural(material.tests, copy.value.tests));
  }
  return parts.length === 0
    ? null
    : fill(copy.value.newMaterial, { material: listFormat.value.format(parts) });
}

function observationSubjects(observation: LearnedObservationPayload): Subject[] {
  const subjects: Subject[] = [];
  const { requirement, screen } = observation.about;
  if (requirement !== null) {
    subjects.push({
      key: `requirement:${requirement}`,
      code: requirement,
      title: props.requirementTitles[requirement] ?? null,
    });
  }
  if (screen !== null) {
    subjects.push({
      key: `screen:${screen}`,
      code: screen,
      title: props.screenTitles[screen] ?? null,
    });
  }
  return subjects;
}

function observationView(observation: LearnedObservationPayload) {
  const source: Readonly<Record<string, string>> = copy.value.source;
  const template = source[observation.source];
  return {
    code: observation.code,
    statement: observation.statement,
    source:
      template === undefined ? null : fill(template, { date: formatDate(observation.approved_at) }),
    basis: observation.basis,
    subjects: observationSubjects(observation),
    contradiction: observation.contradicts_profile,
  };
}

async function load(): Promise<void> {
  try {
    await store.load(props.projectId, props.authorize, props.api);
  } catch {
    return;
  }
}

watch(() => props.projectId, load, { immediate: true });
</script>

<template>
  <div v-if="visible" class="border-t border-on-night/10 pt-4" data-testid="learning-block">
    <h3 class="m-0 text-base leading-tight font-semibold">{{ copy.title }}</h3>
    <p class="m-0 mt-1 text-sm leading-normal text-on-night-3">{{ copy.intro }}</p>
    <p
      v-if="failureText !== null"
      class="m-0 mt-3 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm font-semibold wrap-anywhere text-fail-on-night"
      role="alert"
      data-testid="learning-error"
    >
      {{ failureText }}
    </p>
    <template v-if="twinViews.length > 0">
      <p
        v-if="!updateAvailable"
        class="m-0 mt-3 rounded-field border border-warn-on-night/40 bg-warn-on-night/8 px-4 py-3 text-sm leading-normal text-warn-on-night"
        data-testid="learning-no-model"
      >
        <template v-for="part in commandParts(copy.noModel)" :key="part.key">
          <code
            v-if="part.command"
            class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
            >{{ part.text }}</code
          >
          <template v-else>{{ part.text }}</template>
        </template>
      </p>
      <ul class="m-0 mt-2 list-none p-0">
        <li
          v-for="twin in twinViews"
          :key="twin.key"
          class="grid gap-2 border-t border-on-night/10 py-3"
          data-testid="learning-twin"
        >
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h4 class="m-0 text-[15px] leading-snug font-semibold wrap-anywhere">
              {{ twin.name }}
            </h4>
            <span class="text-xs text-on-night-3" data-testid="learning-twin-label">
              {{ twin.label }}
            </span>
          </div>
          <UiClaimFrame
            v-if="twin.observations.length > 0"
            status="confirmed"
            data-testid="learning-observations"
          >
            <ul class="m-0 grid list-none gap-3 p-0">
              <li
                v-for="observation in twin.observations"
                :key="observation.code"
                class="grid gap-1"
                data-testid="learning-observation"
              >
                <p class="m-0 text-[15px] leading-snug wrap-anywhere">
                  <span
                    class="font-mono text-xs text-on-night-2"
                    data-testid="learning-observation-code"
                    >{{ observation.code }}</span
                  >
                  · {{ observation.statement }}
                </p>
                <p
                  v-if="observation.source !== null"
                  class="m-0 text-[13px] text-on-night-3"
                  data-testid="learning-observation-source"
                >
                  {{ observation.source }}
                </p>
                <p
                  v-if="observation.basis"
                  class="m-0 text-[13px] leading-normal wrap-anywhere text-on-night-2"
                  data-testid="learning-observation-basis"
                >
                  <strong class="font-semibold text-on-night">{{ copy.basis }}:</strong>
                  {{ observation.basis }}
                </p>
                <div
                  v-if="observation.subjects.length > 0"
                  class="flex flex-wrap items-baseline gap-x-2 text-[13px] text-on-night-3"
                >
                  <span>{{ copy.about }}:</span>
                  <ul class="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0">
                    <li
                      v-for="subject in observation.subjects"
                      :key="subject.key"
                      data-testid="learning-subject"
                    >
                      <span class="font-mono text-xs text-on-night-2">{{ subject.code }}</span>
                      <template v-if="subject.title"> · {{ subject.title }}</template>
                    </li>
                  </ul>
                </div>
                <p
                  v-if="observation.contradiction"
                  class="m-0 text-[13px] leading-normal wrap-anywhere text-warn-on-night"
                  data-testid="learning-contradiction"
                >
                  <strong class="font-semibold">{{ copy.contradicts }}:</strong>
                  {{ observation.contradiction }}
                </p>
              </li>
            </ul>
          </UiClaimFrame>
          <p v-else class="m-0 text-sm text-on-night-3" data-testid="learning-nothing">
            {{ copy.nothing }}
          </p>
          <p
            v-if="twin.retired !== null"
            class="m-0 text-[13px] text-on-night-3"
            data-testid="learning-retired"
          >
            {{ twin.retired }}
          </p>
          <p
            v-if="twin.pending"
            class="m-0 text-sm leading-normal text-on-night-2"
            data-testid="learning-pending"
          >
            <template
              v-for="part in commandParts(
                twin.pendingEvidence ? copy.pendingEvidence : copy.pending,
              )"
              :key="part.key"
            >
              <code
                v-if="part.command"
                class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                >{{ part.text }}</code
              >
              <template v-else>{{ part.text }}</template>
            </template>
          </p>
          <p
            v-else-if="twin.material !== null"
            class="m-0 text-sm leading-normal text-on-night-2"
            data-testid="learning-new-material"
          >
            <template v-for="part in commandParts(twin.material)" :key="part.key">
              <code
                v-if="part.command"
                class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
                >{{ part.text }}</code
              >
              <template v-else>{{ part.text }}</template>
            </template>
          </p>
        </li>
      </ul>
      <p
        class="m-0 border-t border-on-night/10 pt-3 text-sm leading-normal text-on-night-2"
        data-testid="learning-terminal"
      >
        <template v-for="part in commandParts(copy.terminal)" :key="part.key">
          <code
            v-if="part.command"
            class="rounded-[4px] bg-on-night/8 px-1 font-mono text-[13px] text-on-night"
            >{{ part.text }}</code
          >
          <template v-else>{{ part.text }}</template>
        </template>
      </p>
    </template>
  </div>
</template>
