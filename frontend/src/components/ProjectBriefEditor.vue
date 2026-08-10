<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { BriefField, ProjectBriefInput, ProjectBriefResponse } from "@/api/contracts";

const props = defineProps<{
  initial: ProjectBriefResponse | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  submit: [brief: ProjectBriefInput];
}>();

const { t } = useI18n({
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
  <form class="grid gap-8" @submit.prevent="submit">
    <div
      class="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700"
      role="status"
    >
      {{
        t("brief.missingSummary", {
          count: missingCount,
        })
      }}
    </div>

    <fieldset class="grid gap-5">
      <legend class="text-xl font-black text-slate-950">
        {{ t("brief.textFields") }}
      </legend>

      <div
        v-for="field in textFields"
        :key="field"
        class="grid gap-2 rounded-xl border border-slate-200 p-4"
      >
        <label class="font-bold text-slate-800" :for="`brief-${field}`">
          {{ t(`brief.fields.${field}`) }}
        </label>

        <textarea
          :id="`brief-${field}`"
          v-model="textValues[field]"
          class="min-h-24 rounded-lg border border-slate-300 bg-white px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:outline-none"
          :disabled="isUnknown(field)"
        ></textarea>

        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            :checked="isUnknown(field)"
            :data-testid="`brief-${field}-unknown`"
            @change="onUnknownChange(field, $event)"
          />

          {{ t("brief.markUnknown") }}
        </label>
      </div>
    </fieldset>

    <fieldset class="grid gap-5">
      <legend class="text-xl font-black text-slate-950">
        {{ t("brief.listFields") }}
      </legend>

      <div
        v-for="field in listFields"
        :key="field"
        class="grid gap-2 rounded-xl border border-slate-200 p-4"
      >
        <label class="font-bold text-slate-800" :for="`brief-${field}`">
          {{ t(`brief.fields.${field}`) }}
        </label>

        <textarea
          :id="`brief-${field}`"
          v-model="listValues[field]"
          class="min-h-32 rounded-lg border border-slate-300 bg-white px-3 py-2 focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:outline-none"
          :disabled="isUnknown(field)"
          :aria-describedby="`brief-${field}-hint`"
        ></textarea>

        <p :id="`brief-${field}-hint`" class="m-0 text-sm text-slate-600">
          {{ t("brief.oneItemPerLine") }}
        </p>

        <label class="flex items-center gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            :checked="isUnknown(field)"
            :data-testid="`brief-${field}-unknown`"
            @change="onUnknownChange(field, $event)"
          />

          {{ t("brief.markUnknown") }}
        </label>
      </div>
    </fieldset>

    <button
      class="min-h-12 rounded-xl bg-slate-950 px-5 py-3 font-bold text-white shadow-sm hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:opacity-60"
      type="submit"
      :disabled="busy"
    >
      {{ busy ? t("brief.saving") : t("brief.saveVersion") }}
    </button>
  </form>
</template>
