<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { BriefField, ProjectBriefInput, ProjectBriefResponse } from "@/api/contracts";
import UiButton from "./UiButton.vue";

const props = defineProps<{
  initial: ProjectBriefResponse | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  submit: [brief: ProjectBriefInput];
}>();

const { t, locale } = useI18n({
  useScope: "global",
});

const textFields = [
  "name",
  "description",
  "problem",
  "domain",
  "temporal_constraints",
  "budget",
] as const satisfies readonly BriefField[];

const listFields = [
  "goals",
  "target_users",
  "technical_constraints",
  "functional_requirements",
  "non_functional_requirements",
  "risks",
  "stakeholders",
  "available_artifacts",
  "definition_of_done",
] as const satisfies readonly BriefField[];

type TextField = (typeof textFields)[number];
type ListField = (typeof listFields)[number];

const fieldGroups = computed(() => [
  {
    title: locale.value === "it" ? "La tua idea" : "Your idea",
    essential: true,
    fields: [
      "name",
      "description",
      "problem",
      "goals",
      "target_users",
      "functional_requirements",
    ] as BriefField[],
  },
  {
    title: locale.value === "it" ? "Altri dettagli del progetto" : "More project details",
    essential: false,
    fields: [
      "domain",
      "temporal_constraints",
      "budget",
      "technical_constraints",
      "non_functional_requirements",
      "risks",
      "stakeholders",
      "available_artifacts",
      "definition_of_done",
    ] as BriefField[],
  },
]);

function isListField(field: BriefField): field is ListField {
  return listFields.includes(field as ListField);
}

function fieldValue(field: BriefField): string {
  return isListField(field) ? listValues[field] : textValues[field as TextField];
}

function updateField(field: BriefField, event: Event): void {
  const value = (event.target as HTMLTextAreaElement).value;
  if (isListField(field)) listValues[field] = value;
  else textValues[field as TextField] = value;
}

const textValues = reactive<Record<TextField, string>>({
  name: "",
  description: "",
  problem: "",
  domain: "",
  temporal_constraints: "",
  budget: "",
});

const listValues = reactive<Record<ListField, string>>({
  goals: "",
  target_users: "",
  technical_constraints: "",
  functional_requirements: "",
  non_functional_requirements: "",
  risks: "",
  stakeholders: "",
  available_artifacts: "",
  definition_of_done: "",
});

const unknownFields = ref<BriefField[]>([]);

const missingCount = computed(() => {
  const missingText = textFields.filter(
    (field) => textValues[field].trim() === "" && !isUnknown(field),
  );
  const missingLists = listFields.filter(
    (field) => listValues[field].trim() === "" && !isUnknown(field),
  );

  return missingText.length + missingLists.length;
});

watch(
  () => props.initial,
  (initial) => {
    for (const field of textFields) {
      textValues[field] = initial?.[field] ?? "";
    }

    for (const field of listFields) {
      listValues[field] = initial?.[field]?.join("\n") ?? "";
    }

    unknownFields.value = [...(initial?.unknown_fields ?? [])];
  },
  {
    immediate: true,
  },
);

function isUnknown(field: BriefField): boolean {
  return unknownFields.value.includes(field);
}

function onUnknownChange(field: BriefField, event: Event): void {
  const target = event.target;

  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  if (target.checked) {
    unknownFields.value = [...new Set([...unknownFields.value, field])];

    if (textFields.includes(field as TextField)) {
      textValues[field as TextField] = "";
    } else {
      listValues[field as ListField] = "";
    }

    return;
  }

  unknownFields.value = unknownFields.value.filter((candidate) => candidate !== field);
}

function optionalText(value: string): string | null {
  const normalized = value.trim();

  return normalized || null;
}

function optionalList(value: string): readonly string[] | null {
  const items = value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  return items.length > 0 ? items : null;
}

function submit(): void {
  emit("submit", {
    name: optionalText(textValues.name),
    description: optionalText(textValues.description),
    problem: optionalText(textValues.problem),
    goals: optionalList(listValues.goals),
    target_users: optionalList(listValues.target_users),
    domain: optionalText(textValues.domain),
    technical_constraints: optionalList(listValues.technical_constraints),
    temporal_constraints: optionalText(textValues.temporal_constraints),
    budget: optionalText(textValues.budget),
    functional_requirements: optionalList(listValues.functional_requirements),
    non_functional_requirements: optionalList(listValues.non_functional_requirements),
    risks: optionalList(listValues.risks),
    stakeholders: optionalList(listValues.stakeholders),
    available_artifacts: optionalList(listValues.available_artifacts),
    definition_of_done: optionalList(listValues.definition_of_done),
    unknown_fields: [...unknownFields.value].sort(),
  });
}
</script>

<template>
  <form class="grid gap-5" @submit.prevent="submit">
    <p
      class="rounded-field border border-night-line bg-night-raised px-4 py-3 text-sm leading-normal text-on-night-2"
      role="status"
    >
      {{
        t("brief.missingSummary", {
          count: missingCount,
        })
      }}
    </p>

    <component
      :is="group.essential ? 'fieldset' : 'details'"
      v-for="group in fieldGroups"
      :key="group.title"
      :class="[
        'rounded-tile border border-night-line',
        group.essential ? 'px-5 pt-2 pb-5' : 'group px-5 py-1',
      ]"
      :data-testid="group.essential ? 'brief-essentials' : 'brief-additional-details'"
    >
      <component
        :is="group.essential ? 'legend' : 'summary'"
        :class="[
          'px-1 text-base font-semibold tracking-block text-on-night',
          group.essential
            ? ''
            : 'flex min-h-11 cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden',
        ]"
      >
        <span
          v-if="!group.essential"
          aria-hidden="true"
          class="inline-block h-1.5 w-1.5 shrink-0 -rotate-45 border-r-[1.5px] border-b-[1.5px] border-on-night-3 transition-transform duration-150 group-open:rotate-45"
        />
        {{ group.title }}
      </component>
      <div :class="['grid gap-5 sm:grid-cols-2', group.essential ? 'mt-3' : 'mt-3 mb-4']">
        <div v-for="field in group.fields" :key="field" class="grid content-start gap-2">
          <label class="text-sm font-semibold text-on-night" :for="`brief-${field}`">
            {{ t(`brief.fields.${field}`) }}
          </label>
          <textarea
            :id="`brief-${field}`"
            :value="fieldValue(field)"
            :rows="field === 'name' ? 1 : 3"
            class="resize-y rounded-control border border-night-line-strong bg-night-raised px-3 py-2.5 text-[15px] leading-normal text-on-night disabled:cursor-not-allowed disabled:border-night-line disabled:text-on-night-3"
            :disabled="isUnknown(field)"
            :aria-describedby="isListField(field) ? `brief-${field}-hint` : undefined"
            @input="updateField(field, $event)"
          ></textarea>
          <p v-if="isListField(field)" :id="`brief-${field}-hint`" class="text-xs text-on-night-3">
            {{ t("brief.oneItemPerLine") }}
          </p>
          <label class="flex min-h-11 items-center gap-2.5 text-sm text-on-night-2">
            <input
              type="checkbox"
              class="h-4 w-4 accent-petrol-on-night"
              :checked="isUnknown(field)"
              :data-testid="`brief-${field}-unknown`"
              @change="onUnknownChange(field, $event)"
            />
            {{ t("brief.markUnknown") }}
          </label>
        </div>
      </div>
    </component>

    <div>
      <UiButton type="submit" variant="pill" :disabled="busy">
        {{ busy ? t("brief.saving") : t("brief.saveVersion") }}
      </UiButton>
    </div>
  </form>
</template>
