<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type {
  DeclarativePrototypePayload,
  PrototypeElementPayload,
  PrototypeViewport,
} from "../types/design";

type Locale = "en" | "it";

const props = withDefaults(
  defineProps<{
    prototype: DeclarativePrototypePayload;
    locale?: Locale;
  }>(),
  {
    locale: "en",
  },
);

const messages = {
  en: {
    viewport: "Preview viewport",
    screens: "Prototype screens",
    reset: "Return to entry screen",
    current: "Current screen",
    noScreen: "The selected prototype screen is unavailable.",
  },
  it: {
    viewport: "Viewport dell'anteprima",
    screens: "Schermate del prototipo",
    reset: "Torna alla schermata iniziale",
    current: "Schermata corrente",
    noScreen: "La schermata selezionata del prototipo non è disponibile.",
  },
} as const;

const copy = computed(() => messages[props.locale]);
const currentScreenId = ref(props.prototype.entry_screen_id);
const viewport = ref<PrototypeViewport>(props.prototype.supported_viewports[0] ?? "DESKTOP");

const currentScreen = computed(
  () => props.prototype.screens.find((screen) => screen.id === currentScreenId.value) ?? null,
);
const viewportClass = computed(() => {
  const classes: Record<PrototypeViewport, string> = {
    MOBILE: "max-w-sm",
    TABLET: "max-w-2xl",
    DESKTOP: "max-w-5xl",
  };

  return classes[viewport.value];
});

watch(
  () => props.prototype,
  (prototype) => {
    currentScreenId.value = prototype.entry_screen_id;
    viewport.value = prototype.supported_viewports[0] ?? "DESKTOP";
  },
);

function transitionFor(elementId: string) {
  return props.prototype.transitions.find(
    (transition) =>
      transition.source_screen_id === currentScreenId.value &&
      transition.trigger_element_id === elementId,
  );
}

function activate(element: PrototypeElementPayload): void {
  const transition = transitionFor(element.id);

  if (transition !== undefined) {
    currentScreenId.value = transition.target_screen_id;
  }
}

function isNavigable(elementId: string): boolean {
  return transitionFor(elementId) !== undefined;
}

function reset(): void {
  currentScreenId.value = props.prototype.entry_screen_id;
}
</script>

<template>
  <section class="grid gap-5" aria-labelledby="prototype-preview-title">
    <header class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="m-0 text-xs font-black tracking-widest text-indigo-700 uppercase">
          {{ prototype.code }}
        </p>
        <h3 id="prototype-preview-title" class="mt-1 text-xl font-black text-slate-950">
          {{ prototype.title }}
        </h3>
      </div>

      <button
        type="button"
        class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-bold text-slate-700 hover:bg-slate-50"
        @click="reset"
      >
        {{ copy.reset }}
      </button>
    </header>

    <fieldset class="flex flex-wrap gap-2">
      <legend class="mb-2 text-sm font-black text-slate-900">{{ copy.viewport }}</legend>
      <label
        v-for="option in prototype.supported_viewports"
        :key="option"
        class="cursor-pointer rounded-lg border px-3 py-2 text-sm font-bold"
        :class="
          viewport === option
            ? 'border-indigo-500 bg-indigo-50 text-indigo-800'
            : 'border-slate-300 text-slate-700 hover:bg-slate-50'
        "
      >
        <input v-model="viewport" class="sr-only" type="radio" :value="option" />
        {{ option }}
      </label>
    </fieldset>

    <nav :aria-label="copy.screens">
      <ol class="flex flex-wrap gap-2">
        <li v-for="screen in prototype.screens" :key="screen.id">
          <button
            type="button"
            class="rounded-lg border px-3 py-2 text-sm font-bold"
            :class="
              screen.id === currentScreenId
                ? 'border-indigo-500 bg-indigo-50 text-indigo-800'
                : 'border-slate-300 text-slate-700 hover:bg-slate-50'
            "
            @click="currentScreenId = screen.id"
          >
            {{ screen.code }} · {{ screen.title }}
          </button>
        </li>
      </ol>
    </nav>

    <div class="overflow-x-auto rounded-2xl bg-slate-100 p-4 sm:p-6">
      <article
        v-if="currentScreen !== null"
        :class="viewportClass"
        class="mx-auto grid min-h-80 content-start gap-5 rounded-2xl border border-slate-300 bg-white p-6 shadow-xl transition-[max-width]"
        :data-screen-id="currentScreen.id"
      >
        <header class="border-b border-slate-200 pb-4">
          <p class="m-0 text-xs font-black tracking-widest text-slate-500 uppercase">
            {{ copy.current }} · {{ currentScreen.code }} · {{ currentScreen.state }}
          </p>
          <h4 class="mt-2 text-2xl font-black text-slate-950">{{ currentScreen.title }}</h4>
        </header>

        <template v-for="element in currentScreen.elements" :key="element.id">
          <h5 v-if="element.kind === 'HEADING'" class="text-xl font-black text-slate-950">
            {{ element.content }}
          </h5>

          <p v-else-if="element.kind === 'TEXT'" class="m-0 leading-7 text-slate-700">
            {{ element.content }}
          </p>

          <ul v-else-if="element.kind === 'LIST'" class="list-disc space-y-1 pl-5 text-slate-700">
            <li>{{ element.content }}</li>
          </ul>

          <div
            v-else-if="element.kind === 'CARD'"
            class="rounded-xl border border-slate-200 bg-slate-50 p-4 text-slate-700"
          >
            {{ element.content }}
          </div>

          <p
            v-else-if="element.kind === 'STATUS'"
            class="m-0 rounded-xl border border-emerald-200 bg-emerald-50 p-4 font-bold text-emerald-900"
            role="status"
          >
            {{ element.content }}
          </p>

          <label
            v-else-if="element.kind === 'TEXT_INPUT'"
            class="grid gap-2 font-bold text-slate-900"
          >
            {{ element.accessible_name ?? element.content }}
            <input
              type="text"
              class="rounded-lg border border-slate-300 px-3 py-2 font-normal"
              :name="element.field_name ?? undefined"
              :required="element.required"
            />
          </label>

          <label v-else-if="element.kind === 'SELECT'" class="grid gap-2 font-bold text-slate-900">
            {{ element.accessible_name ?? element.content }}
            <select
              class="rounded-lg border border-slate-300 px-3 py-2 font-normal"
              :name="element.field_name ?? undefined"
              :required="element.required"
            >
              <option v-for="option in element.options" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
          </label>

          <button
            v-else-if="element.kind === 'BUTTON'"
            type="button"
            class="justify-self-start rounded-lg bg-indigo-700 px-4 py-2 font-black text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
            :aria-label="element.accessible_name ?? element.content"
            :disabled="!isNavigable(element.id)"
            :data-trigger-element-id="element.id"
            @click="activate(element)"
          >
            {{ element.content }}
          </button>

          <a
            v-else-if="element.kind === 'LINK'"
            href="#"
            class="justify-self-start font-black text-indigo-700 underline"
            :class="{ 'pointer-events-none text-slate-500': !isNavigable(element.id) }"
            :aria-label="element.accessible_name ?? element.content"
            :aria-disabled="!isNavigable(element.id)"
            @click.prevent="activate(element)"
          >
            {{ element.content }}
          </a>
        </template>
      </article>

      <p v-else class="m-0 rounded-xl bg-white p-4 text-slate-700" role="alert">
        {{ copy.noScreen }}
      </p>
    </div>
  </section>
</template>
