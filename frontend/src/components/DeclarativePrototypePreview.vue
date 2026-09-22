<script setup lang="ts">
import { computed, nextTick, reactive, ref, useId, watch } from "vue";
import type {
  DeclarativePrototypePayload,
  PrototypeElementPayload,
  PrototypeViewport,
} from "../types/design";

const props = withDefaults(
  defineProps<{ prototype: DeclarativePrototypePayload; locale?: "en" | "it" }>(),
  { locale: "en" },
);
const labels = {
  en: {
    viewport: "Preview size",
    screens: "Mockup screens",
    reset: "Reset preview",
    noScreen: "This screen is unavailable.",
    required: "Complete the required fields to continue.",
    example: "Interactive design preview",
    sizes: { MOBILE: "Phone", TABLET: "Tablet", DESKTOP: "Desktop" },
  },
  it: {
    viewport: "Dimensioni anteprima",
    screens: "Schermate mockup",
    reset: "Riavvia anteprima",
    noScreen: "Questa schermata non è disponibile.",
    required: "Completa i campi obbligatori per continuare.",
    example: "Anteprima interattiva del design",
    sizes: { MOBILE: "Telefono", TABLET: "Tablet", DESKTOP: "Desktop" },
  },
};
const copy = computed(() => labels[props.locale]);
const titleId = `mockup-${useId()}`;
const currentScreenId = ref(props.prototype.entry_screen_id);
const viewport = ref<PrototypeViewport>(
  props.prototype.supported_viewports.includes("DESKTOP")
    ? "DESKTOP"
    : (props.prototype.supported_viewports[0] ?? "MOBILE"),
);
const values = reactive<Record<string, string>>({});
const validationError = ref(false);
const form = ref<HTMLFormElement | null>(null);
const screenHeading = ref<HTMLElement | null>(null);
const currentScreen = computed(
  () => props.prototype.screens.find((screen) => screen.id === currentScreenId.value) ?? null,
);
const viewportClass = computed(
  () => ({ MOBILE: "max-w-sm", TABLET: "max-w-xl", DESKTOP: "max-w-2xl" })[viewport.value],
);

function transitionFor(elementId: string) {
  return props.prototype.transitions.find(
    (transition) =>
      transition.source_screen_id === currentScreenId.value &&
      transition.trigger_element_id === elementId,
  );
}

async function showScreen(id: string): Promise<void> {
  currentScreenId.value = id;
  validationError.value = false;
  await nextTick();
  screenHeading.value?.focus();
}

function activate(element: PrototypeElementPayload): void {
  const transition = transitionFor(element.id);
  if (!transition) return;
  if (form.value && !form.value.reportValidity()) {
    validationError.value = true;
    return;
  }
  void showScreen(transition.target_screen_id);
}

function reset(): void {
  Object.keys(values).forEach((key) => delete values[key]);
  void showScreen(props.prototype.entry_screen_id);
}

watch(
  () => props.prototype,
  () => {
    currentScreenId.value = props.prototype.entry_screen_id;
    validationError.value = false;
    Object.keys(values).forEach((key) => delete values[key]);
  },
);

function fieldKey(element: PrototypeElementPayload): string {
  return element.field_name ?? element.id;
}
</script>

<template>
  <section class="grid min-w-0 gap-3" :aria-labelledby="titleId">
    <header class="flex flex-wrap items-center justify-between gap-3">
      <h3 :id="titleId" class="m-0 text-base font-semibold text-ink">
        {{ prototype.title }}
      </h3>
      <button
        type="button"
        class="rounded-md px-2 py-1 text-xs font-semibold text-ink-2 hover:bg-surface-3 focus-visible:outline-2 focus-visible:outline-action"
        @click="reset"
      >
        {{ copy.reset }}
      </button>
    </header>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <nav :aria-label="copy.screens" class="flex flex-wrap gap-1">
        <button
          v-for="(screen, index) in prototype.screens"
          :key="screen.id"
          type="button"
          class="rounded-control px-3 py-2 text-xs font-semibold focus-visible:outline-2 focus-visible:outline-action"
          :class="
            screen.id === currentScreenId
              ? 'bg-action-soft text-action'
              : 'text-ink-2 hover:bg-surface-3'
          "
          :aria-current="screen.id === currentScreenId ? 'step' : undefined"
          @click="showScreen(screen.id)"
        >
          {{ index + 1 }}. {{ screen.title }}
        </button>
      </nav>
      <div
        class="flex rounded-control border border-line p-1"
        role="group"
        :aria-label="copy.viewport"
      >
        <button
          v-for="option in prototype.supported_viewports"
          :key="option"
          type="button"
          class="rounded-md px-2 py-1 text-xs font-medium focus-visible:outline-2 focus-visible:outline-action"
          :class="viewport === option ? 'bg-ink text-white' : 'text-ink-2 hover:bg-surface-3'"
          :aria-pressed="viewport === option"
          :data-viewport="option"
          @click="viewport = option"
        >
          {{ copy.sizes[option] }}
        </button>
      </div>
    </div>
    <div class="min-w-0 rounded-panel border border-line bg-surface-3 p-3 sm:p-5">
      <article
        v-if="currentScreen !== null"
        :class="viewportClass"
        class="mx-auto overflow-hidden rounded-panel border border-line bg-white shadow-sm transition-[max-width]"
        :data-screen-id="currentScreen.id"
      >
        <div
          class="flex items-center gap-1.5 border-b border-line-soft bg-surface-2 px-4 py-2"
          aria-hidden="true"
        >
          <span v-for="dot in 3" :key="dot" class="h-1.5 w-1.5 rounded-full bg-button-line" />
          <span class="ml-2 text-[10px] tracking-wide text-ink-3">{{ copy.example }}</span>
        </div>
        <div class="p-5 sm:p-6">
          <h4
            ref="screenHeading"
            tabindex="-1"
            class="m-0 mb-5 text-xl font-bold tracking-tight text-ink outline-none"
          >
            {{ currentScreen.title }}
          </h4>
          <form
            ref="form"
            class="grid gap-4"
            :class="viewport !== 'MOBILE' ? 'sm:grid-cols-2' : ''"
            @submit.prevent
          >
            <template v-for="element in currentScreen.elements" :key="element.id">
              <h5
                v-if="element.kind === 'HEADING'"
                class="col-span-full m-0 text-lg font-semibold text-ink"
              >
                {{ element.content }}
              </h5>
              <p
                v-else-if="element.kind === 'TEXT'"
                class="col-span-full m-0 text-sm leading-6 text-ink-2"
              >
                {{ element.content }}
              </p>
              <ul
                v-else-if="element.kind === 'LIST'"
                class="col-span-full m-0 list-disc pl-5 text-sm text-ink-2"
              >
                <li>{{ element.content }}</li>
              </ul>
              <div
                v-else-if="element.kind === 'CARD'"
                class="rounded-panel border border-line bg-surface-2 p-4 text-sm text-ink-2"
              >
                {{ element.content }}
              </div>
              <p
                v-else-if="element.kind === 'STATUS'"
                class="col-span-full m-0 rounded-panel border p-4 text-base font-semibold"
                :class="
                  currentScreen.state === 'ERROR'
                    ? 'border-fail-line bg-fail-bg text-fail-dark'
                    : 'border-ok-line bg-ok-bg text-ok-dark'
                "
                role="status"
              >
                {{ element.content }}
              </p>
              <label
                v-else-if="element.kind === 'TEXT_INPUT'"
                class="grid gap-1.5 text-sm font-medium text-ink-2"
              >
                {{ element.accessible_name ?? element.content
                }}<span v-if="element.required" class="sr-only">*</span>
                <input
                  v-model="values[fieldKey(element)]"
                  type="text"
                  class="min-w-0 rounded-control border border-field px-3 py-2.5 font-normal focus:border-action focus:outline-2 focus:outline-action-soft-line"
                  :name="element.field_name ?? undefined"
                  :required="element.required"
                />
              </label>
              <label
                v-else-if="element.kind === 'SELECT'"
                class="grid gap-1.5 text-sm font-medium text-ink-2"
              >
                {{ element.accessible_name ?? element.content
                }}<span v-if="element.required" class="sr-only">*</span>
                <select
                  v-model="values[fieldKey(element)]"
                  class="min-w-0 rounded-control border border-field bg-white px-3 py-2.5 font-normal focus:border-action focus:outline-2 focus:outline-action-soft-line"
                  :name="element.field_name ?? undefined"
                  :required="element.required"
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
                class="col-span-full min-h-11 rounded-control bg-action px-4 py-2.5 text-sm font-semibold text-white hover:bg-action-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action disabled:cursor-not-allowed disabled:bg-surface-3"
                :aria-label="element.accessible_name ?? element.content"
                :disabled="!transitionFor(element.id)"
                :data-trigger-element-id="element.id"
                @click="activate(element)"
              >
                {{ element.content }}
              </button>
              <a
                v-else-if="element.kind === 'LINK'"
                href="#"
                class="col-span-full justify-self-start rounded text-sm font-semibold text-action underline focus-visible:outline-2 focus-visible:outline-action"
                :aria-label="element.accessible_name ?? element.content"
                :aria-disabled="!transitionFor(element.id)"
                @click.prevent="activate(element)"
                >{{ element.content }}</a
              >
            </template>
            <p v-if="validationError" class="col-span-full m-0 text-sm text-fail-dark" role="alert">
              {{ copy.required }}
            </p>
          </form>
        </div>
      </article>
      <p v-else class="m-0 rounded-control bg-white p-4 text-sm text-ink-2" role="alert">
        {{ copy.noScreen }}
      </p>
    </div>
  </section>
</template>
