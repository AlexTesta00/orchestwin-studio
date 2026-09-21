<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { BrowserAction, BrowserExecutionChecks } from "@/api/executionLaunch";

const props = withDefaults(defineProps<{ locale?: "it" | "en"; disabled?: boolean }>(), {
  locale: "en",
  disabled: false,
});
const emit = defineEmits<{ change: [checks: BrowserExecutionChecks | null] }>();
const path = ref("/");
const actions = ref<BrowserAction[]>([
  { kind: "click", selector: "", value: null },
  { kind: "expect_text", selector: "", value: "" },
  { kind: "press", selector: "", value: "Enter" },
  { kind: "expect_text", selector: "", value: "" },
]);
const copy = computed(() =>
  props.locale === "it"
    ? {
        title: "Verifica il comportamento nel browser",
        intro:
          "Definisci un percorso reale: un clic e un’attivazione da tastiera, ciascuno seguito dal testo atteso. I selettori CSS devono riferirsi alla pagina generata.",
        route: "Percorso della pagina",
        action: "Azione",
        selector: "Selettore CSS",
        value: "Valore o testo atteso",
        add: "Aggiungi passaggio",
        remove: "Rimuovi",
        invalid: "Completa i passaggi e verifica il risultato dopo clic e tastiera.",
        kinds: {
          fill: "Compila campo",
          click: "Clic",
          press: "Premi tasto",
          expect_text: "Verifica testo",
          expect_contains: "Verifica che contenga",
          expect_not_text: "Verifica che sia cambiato",
        },
      }
    : {
        title: "Check browser behavior",
        intro:
          "Define a real path: a click and a keyboard activation, each followed by expected text. CSS selectors must refer to the generated page.",
        route: "Page path",
        action: "Action",
        selector: "CSS selector",
        value: "Value or expected text",
        add: "Add step",
        remove: "Remove",
        invalid: "Complete the steps and verify the result after click and keyboard activation.",
        kinds: {
          fill: "Fill field",
          click: "Click",
          press: "Press key",
          expect_text: "Check text",
          expect_contains: "Check contains",
          expect_not_text: "Check changed",
        },
      },
);
const assertion = (kind: string) =>
  ["expect_text", "expect_contains", "expect_not_text"].includes(kind);
const checks = computed<BrowserExecutionChecks | null>(() => {
  if (!path.value.startsWith("/") || path.value.startsWith("//") || !actions.value.length)
    return null;
  let pending: string | null = null;
  const checked = new Set<string>();
  for (const action of actions.value) {
    if (!action.selector.trim() || (assertion(action.kind) && !action.value?.trim())) return null;
    if (action.kind === "press" && !["Enter", "Space"].includes(action.value ?? "")) return null;
    if (action.kind === "click" || action.kind === "press") {
      if (pending) return null;
      pending = action.kind;
    } else if (assertion(action.kind) && pending) {
      checked.add(pending);
      pending = null;
    }
  }
  if (pending || checked.size !== 2) return null;
  const routeId = path.value === "/" ? "root" : "owner-check";
  return {
    declared_routes: path.value === "/" ? [] : [{ route_id: routeId, path: path.value }],
    browser_interactions: [
      {
        route_id: routeId,
        actions: actions.value.map((action) => ({
          ...action,
          value: action.kind === "click" ? null : (action.value ?? ""),
        })),
      },
    ],
  };
});
watch(checks, (value) => emit("change", value), { immediate: true });
</script>

<template>
  <fieldset class="space-y-3 rounded border p-4" :disabled="disabled">
    <legend class="font-bold">{{ copy.title }}</legend>
    <p class="text-sm">{{ copy.intro }}</p>
    <label class="grid gap-1"
      >{{ copy.route }}<input v-model="path" maxlength="240" class="rounded border p-2"
    /></label>
    <ol class="space-y-3">
      <li
        v-for="(action, index) in actions"
        :key="index"
        class="grid gap-2 rounded bg-slate-50 p-3 sm:grid-cols-3"
      >
        <label class="grid gap-1"
          >{{ index + 1 }} · {{ copy.action }}
          <select v-model="action.kind" class="rounded border p-2">
            <option v-for="(label, kind) in copy.kinds" :key="kind" :value="kind">
              {{ label }}
            </option>
          </select>
        </label>
        <label class="grid gap-1"
          >{{ copy.selector
          }}<input v-model="action.selector" maxlength="160" class="rounded border p-2"
        /></label>
        <label v-if="action.kind !== 'click'" class="grid gap-1"
          >{{ copy.value
          }}<input v-model="action.value" maxlength="1000" class="rounded border p-2"
        /></label>
        <button
          type="button"
          class="justify-self-start underline"
          @click="actions.splice(index, 1)"
        >
          {{ copy.remove }} {{ index + 1 }}
        </button>
      </li>
    </ol>
    <button
      type="button"
      class="rounded border p-2 disabled:opacity-50"
      :disabled="actions.length >= 8"
      @click="actions.push({ kind: 'fill', selector: '', value: '' })"
    >
      {{ copy.add }}
    </button>
    <p v-if="!checks" class="text-sm text-amber-900">{{ copy.invalid }}</p>
  </fieldset>
</template>
