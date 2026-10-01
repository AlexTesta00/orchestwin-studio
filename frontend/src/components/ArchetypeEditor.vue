<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import UiButton from "./UiButton.vue";
import type { ArchetypeInput, ArchetypePayload } from "../types/userModeling";

const props = withDefaults(
  defineProps<{ archetype?: ArchetypePayload | null; busy?: boolean; locale?: "en" | "it" }>(),
  { archetype: null, busy: false, locale: "en" },
);
const emit = defineEmits<{ save: [data: ArchetypeInput]; cancel: [] }>();
const draft = reactive({ name: "", description: "", role: "", goals: "", context: "" });
watch(
  () => props.archetype,
  (value) =>
    Object.assign(draft, {
      name: value?.name ?? "",
      description: value?.description ?? "",
      role: value?.role ?? "",
      goals: value?.goals.join("\n") ?? "",
      context: value?.context ?? "",
    }),
  { immediate: true },
);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Archetipo",
        name: "Nome",
        description: "Breve descrizione",
        role: "Ruolo",
        goals: "Obiettivi, uno per riga",
        context: "Contesto",
        save: "Salva archetipo",
        cancel: "Annulla",
        note: "Il brief e le scelte del proprietario non sono evidenze su utenti reali.",
      }
    : {
        title: "Archetype",
        name: "Name",
        description: "Short description",
        role: "Role",
        goals: "Goals, one per line",
        context: "Context",
        save: "Save archetype",
        cancel: "Cancel",
        note: "The brief and the owner's choices are not evidence about real users.",
      },
);
const valid = computed(() =>
  [draft.name, draft.description, draft.role].every((value) => value.trim().length > 0),
);
const fields = ["name", "description", "role", "goals", "context"] as const;
function save(): void {
  if (!valid.value || props.busy) return;
  emit("save", {
    name: draft.name.trim(),
    description: draft.description.trim(),
    role: draft.role.trim(),
    goals: draft.goals
      .split("\n")
      .map((goal) => goal.trim())
      .filter(Boolean),
    context: draft.context.trim() || null,
  });
}
</script>

<template>
  <form
    class="grid gap-4 rounded-panel border border-night-line bg-night-raised p-5 text-on-night"
    :aria-label="copy.title"
    @submit.prevent="save"
  >
    <h3 class="m-0 text-base font-semibold">{{ copy.title }}</h3>
    <label v-for="field in fields" :key="field" class="grid gap-1.5 text-sm font-medium">
      {{ copy[field] }}
      <input
        v-if="field === 'name' || field === 'role'"
        v-model="draft[field]"
        :data-testid="`archetype-${field}`"
        :required="true"
        :maxlength="field === 'name' ? 200 : 4000"
        :disabled="busy"
        class="min-h-11 rounded-field border border-night-line bg-night-panel px-3 text-on-night"
      />
      <textarea
        v-else
        v-model="draft[field]"
        :data-testid="`archetype-${field}`"
        :required="field === 'description'"
        :maxlength="field === 'goals' ? undefined : 4000"
        :disabled="busy"
        rows="3"
        class="rounded-field border border-night-line bg-night-panel px-3 py-2 text-on-night"
      />
    </label>
    <p class="m-0 text-xs leading-5 text-on-night-3">{{ copy.note }}</p>
    <div class="flex flex-wrap gap-2">
      <UiButton type="submit" :disabled="busy || !valid" data-testid="archetype-save">{{
        copy.save
      }}</UiButton>
      <UiButton variant="quiet" :disabled="busy" @click="emit('cancel')">{{
        copy.cancel
      }}</UiButton>
    </div>
  </form>
</template>
