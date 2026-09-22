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
    <div
      class="rounded-panel border border-line bg-surface-2 px-4 py-3 text-sm text-ink-2"
      role="status"
    >
      {{
        t("brief.missingSummary", {
          count: missingCount,
        })
      }}
    </div>

    <component
      :is="group.essential ? 'fieldset' : 'details'"
      v-for="group in fieldGroups"
      :key="group.title"
      class="rounded-card border border-line bg-surface p-5 shadow-card"
      :data-testid="group.essential ? 'brief-essentials' : 'brief-additional-details'"
    >
      <component
        :is="group.essential ? 'legend' : 'summary'"
        class="px-1 text-lg font-semibold tracking-block"
        :class="{ 'cursor-pointer': !group.essential }"
      >
        {{ group.title }}
      </component>
      <div class="mt-4 grid gap-5 sm:grid-cols-2">
        <div v-for="field in group.fields" :key="field" class="grid gap-2">
          <label class="text-sm font-semibold" :for="`brief-${field}`">
            {{ t(`brief.fields.${field}`) }}
          </label>
          <textarea
            :id="`brief-${field}`"
            :value="fieldValue(field)"
            :rows="field === 'name' ? 1 : 3"
            class="rounded-control border border-field bg-surface px-3 py-2 text-[15px] disabled:bg-surface-3 disabled:text-ink-3"
            :disabled="isUnknown(field)"
            :aria-describedby="isListField(field) ? `brief-${field}-hint` : undefined"
            @input="updateField(field, $event)"
          ></textarea>
          <p v-if="isListField(field)" :id="`brief-${field}-hint`" class="m-0 text-xs text-ink-3">
            {{ t("brief.oneItemPerLine") }}
          </p>
          <label class="flex items-center gap-2 text-sm text-ink-2">
            <input
              type="checkbox"
              class="h-4 w-4 accent-action"
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
      <UiButton type="submit" :disabled="busy">
        {{ busy ? t("brief.saving") : t("brief.saveVersion") }}
      </UiButton>
    </div>
  </form>
</template>
