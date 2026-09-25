<script setup lang="ts">
import { computed } from "vue";

import type { PrototypeElementPayload, PrototypeScreenState } from "../types/design";
import type { LayoutZoneName } from "./prototypeLayout";

const props = withDefaults(
  defineProps<{
    element: PrototypeElementPayload;
    zone: LayoutZoneName;
    index: number;
    state: PrototypeScreenState;
    value?: string;
    active?: boolean;
  }>(),
  { value: "", active: false },
);

const emit = defineEmits<{
  "update:value": [value: string];
  activate: [element: PrototypeElementPayload];
}>();

const label = computed(() => props.element.accessible_name ?? props.element.content);
const isPerson = computed(() => props.index % 2 === 0);

function onInput(event: Event): void {
  emit("update:value", (event.target as HTMLInputElement | HTMLSelectElement).value);
}
</script>

<template>
  <h5 v-if="element.kind === 'HEADING'" class="vl-h2">{{ element.content }}</h5>
  <div
    v-else-if="element.kind === 'TEXT' && zone === 'thread'"
    class="vl-bubble"
    :class="isPerson ? 'vl-person' : 'vl-system'"
  >
    {{ element.content }}
  </div>
  <p v-else-if="element.kind === 'TEXT'" class="vl-text">{{ element.content }}</p>
  <ul v-else-if="element.kind === 'LIST'" class="vl-list">
    <li>{{ element.content }}</li>
  </ul>
  <div v-else-if="element.kind === 'CARD'" class="vl-card">{{ element.content }}</div>
  <p
    v-else-if="element.kind === 'STATUS'"
    class="vl-status"
    :class="state === 'ERROR' ? 'vl-status-error' : 'vl-status-ok'"
    role="status"
  >
    {{ element.content }}
  </p>
  <label v-else-if="element.kind === 'TEXT_INPUT'" class="vl-field">
    {{ label }}<span v-if="element.required" class="sr-only">*</span>
    <input
      type="text"
      class="vl-input"
      :name="element.field_name ?? undefined"
      :required="element.required"
      :value="value"
      @input="onInput"
    />
  </label>
  <label v-else-if="element.kind === 'SELECT'" class="vl-field">
    {{ label }}<span v-if="element.required" class="sr-only">*</span>
    <select
      class="vl-input"
      :name="element.field_name ?? undefined"
      :required="element.required"
      :value="value"
      @change="onInput"
    >
      <option disabled value="">—</option>
      <option v-for="option in element.options" :key="option" :value="option">
        {{ option }}
      </option>
    </select>
  </label>
  <button
    v-else-if="element.kind === 'BUTTON'"
    type="button"
    class="vl-button"
    :aria-label="label"
    :disabled="!active"
    :data-trigger-element-id="element.id"
    @click="emit('activate', element)"
  >
    {{ element.content }}
  </button>
  <a
    v-else
    href="#"
    class="vl-link"
    :aria-label="label"
    :aria-disabled="!active"
    @click.prevent="emit('activate', element)"
    >{{ element.content }}</a
  >
</template>
