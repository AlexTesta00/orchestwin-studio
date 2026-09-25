<script setup lang="ts">
import { computed, nextTick, reactive, ref, useId, watch } from "vue";

import PrototypeElement from "./PrototypeElement.vue";
import type {
  DeclarativePrototypePayload,
  PrototypeElementPayload,
  PrototypeViewport,
  VisualLanguagePayload,
} from "../types/design";
import { layoutZones } from "./prototypeLayout";
import { shellClasses, tokenStyle, visualChoices, type VisualLocale } from "./visualLanguage";

const props = withDefaults(
  defineProps<{
    prototype: DeclarativePrototypePayload;
    visual?: VisualLanguagePayload | null;
    locale?: VisualLocale;
  }>(),
  { visual: null, locale: "en" },
);
const labels = {
  en: {
    viewport: "Preview size",
    screens: "Mockup screens",
    reset: "Reset preview",
    noScreen: "This screen is unavailable.",
    required: "Complete the required fields to continue.",
    example: "Interactive design preview",
    navigation: "Product navigation",
    steps: "Steps",
    sizes: { MOBILE: "Phone", TABLET: "Tablet", DESKTOP: "Desktop" },
  },
  it: {
    viewport: "Dimensioni anteprima",
    screens: "Schermate mockup",
    reset: "Riavvia anteprima",
    noScreen: "Questa schermata non è disponibile.",
    required: "Completa i campi obbligatori per continuare.",
    example: "Anteprima interattiva del design",
    navigation: "Navigazione del prodotto",
    steps: "Passi",
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
const choices = computed(() => visualChoices(props.visual));
const tokens = computed(() => tokenStyle(props.visual));
const shell = computed(() => shellClasses(choices.value));
const productName = computed(() => props.visual?.product_name ?? props.prototype.title);
const isPhone = computed(() => viewport.value === "MOBILE");
const zones = computed(() =>
  currentScreen.value === null
    ? []
    : layoutZones(choices.value.archetype, currentScreen.value.elements),
);
const columns = computed(() => zones.value.filter((zone) => zone.name === "column"));
const others = computed(() => zones.value.filter((zone) => zone.name !== "column"));
const showRail = computed(() => choices.value.navigation === "SIDE_RAIL" && !isPhone.value);
const showTabs = computed(() => choices.value.navigation === "SIDE_RAIL" && isPhone.value);
const showTopLinks = computed(
  () => choices.value.navigation === "TOP_BAR" || choices.value.navigation === "TABS",
);
const showStepper = computed(() => choices.value.archetype === "GUIDED_STEPS");
const split = computed(
  () =>
    !isPhone.value &&
    others.value.length === 2 &&
    (choices.value.archetype === "LIST_DETAIL" || choices.value.archetype === "SPLIT_SCREEN"),
);
const framed = computed(
  () => choices.value.archetype === "SINGLE_CARD" || choices.value.archetype === "GUIDED_STEPS",
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

function twoColumns(elements: readonly PrototypeElementPayload[]): boolean {
  return (
    !isPhone.value &&
    elements.filter((item) => item.kind === "TEXT_INPUT" || item.kind === "SELECT").length > 1
  );
}

function cells(content: string): string[] {
  return content.split(" · ").map((cell) => cell.trim());
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
        :class="[viewportClass, ...shell, { 'vl-phone': isPhone }]"
        class="vl mx-auto overflow-hidden rounded-panel border border-line shadow-sm transition-[max-width]"
        :style="tokens"
        :data-screen-id="currentScreen.id"
        :data-archetype="choices.archetype"
      >
        <div
          class="flex items-center gap-1.5 border-b border-line-soft bg-surface-2 px-4 py-2"
          aria-hidden="true"
        >
          <span v-for="dot in 3" :key="dot" class="h-1.5 w-1.5 rounded-full bg-button-line" />
          <span class="ml-2 text-[10px] tracking-wide text-ink-3">{{ copy.example }}</span>
        </div>
        <div class="vl-shell">
          <div class="vl-bar">
            <p class="vl-brand" data-testid="mockup-product-name">{{ productName }}</p>
            <div
              v-if="showTopLinks"
              class="vl-links"
              role="navigation"
              :aria-label="copy.navigation"
            >
              <button
                v-for="screen in prototype.screens"
                :key="screen.id"
                type="button"
                class="vl-navlink"
                :aria-current="screen.id === currentScreenId ? 'page' : undefined"
                @click="showScreen(screen.id)"
              >
                {{ screen.title }}
              </button>
            </div>
          </div>
          <div class="vl-layout" :class="{ 'vl-with-rail': showRail }">
            <div v-if="showRail" class="vl-rail" role="navigation" :aria-label="copy.navigation">
              <button
                v-for="screen in prototype.screens"
                :key="screen.id"
                type="button"
                class="vl-navlink"
                :aria-current="screen.id === currentScreenId ? 'page' : undefined"
                @click="showScreen(screen.id)"
              >
                {{ screen.title }}
              </button>
            </div>
            <div class="vl-main">
              <div v-if="showStepper" class="vl-stepper" role="navigation" :aria-label="copy.steps">
                <button
                  v-for="(screen, index) in prototype.screens"
                  :key="screen.id"
                  type="button"
                  class="vl-step"
                  :aria-current="screen.id === currentScreenId ? 'step' : undefined"
                  @click="showScreen(screen.id)"
                >
                  {{ index + 1 }}. {{ screen.title }}
                </button>
              </div>
              <h4 ref="screenHeading" tabindex="-1" class="vl-title outline-none">
                {{ currentScreen.title }}
              </h4>
              <form ref="form" class="vl-zones" :class="{ 'vl-frame': framed }" @submit.prevent>
                <div v-if="columns.length > 0" class="vl-columns">
                  <div v-for="(zone, column) in columns" :key="column" class="vl-column">
                    <PrototypeElement
                      v-for="(element, index) in zone.elements"
                      :key="element.id"
                      :element="element"
                      :zone="zone.name"
                      :index="index"
                      :state="currentScreen.state"
                      :value="values[fieldKey(element)] ?? ''"
                      :active="transitionFor(element.id) !== undefined"
                      @update:value="values[fieldKey(element)] = $event"
                      @activate="activate"
                    />
                  </div>
                </div>
                <div :class="split ? 'vl-split' : 'contents'">
                  <template v-for="zone in others" :key="zone.name">
                    <div v-if="zone.name === 'table'" class="vl-zone vl-zone-table">
                      <table class="vl-table">
                        <tbody>
                          <tr v-for="element in zone.elements" :key="element.id">
                            <td
                              v-for="(cell, cellIndex) in cells(element.content)"
                              :key="cellIndex"
                            >
                              {{ cell }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div
                      v-else
                      class="vl-zone"
                      :class="[
                        `vl-zone-${zone.name}`,
                        { 'vl-two-columns': zone.name === 'main' && twoColumns(zone.elements) },
                      ]"
                    >
                      <PrototypeElement
                        v-for="(element, index) in zone.elements"
                        :key="element.id"
                        :element="element"
                        :zone="zone.name"
                        :index="index"
                        :state="currentScreen.state"
                        :value="values[fieldKey(element)] ?? ''"
                        :active="transitionFor(element.id) !== undefined"
                        @update:value="values[fieldKey(element)] = $event"
                        @activate="activate"
                      />
                    </div>
                  </template>
                </div>
                <p v-if="validationError" class="vl-alert" role="alert">
                  {{ copy.required }}
                </p>
              </form>
            </div>
          </div>
          <div v-if="showTabs" class="vl-tabs" role="navigation" :aria-label="copy.navigation">
            <button
              v-for="screen in prototype.screens"
              :key="screen.id"
              type="button"
              class="vl-navlink"
              :aria-current="screen.id === currentScreenId ? 'page' : undefined"
              @click="showScreen(screen.id)"
            >
              {{ screen.title }}
            </button>
          </div>
        </div>
      </article>
      <p v-else class="m-0 rounded-control bg-white p-4 text-sm text-ink-2" role="alert">
        {{ copy.noScreen }}
      </p>
    </div>
  </section>
</template>

<style scoped>
.vl {
  background: var(--vl-color-background);
  color: var(--vl-color-text);
  font-family: var(--vl-font-body);
  font-size: var(--vl-size-body);
  line-height: var(--vl-line-height);
}
.vl-shell {
  min-height: 320px;
  display: grid;
  grid-template-rows: auto 1fr auto;
}
.vl-bg-TINTED .vl-shell {
  background: var(--vl-color-surface-alt);
}
.vl-bg-GRADIENT .vl-shell {
  background: linear-gradient(160deg, var(--vl-color-primary-soft), var(--vl-color-background) 60%);
}
.vl-bg-DOTS .vl-shell {
  background-image: radial-gradient(var(--vl-color-border) 1px, transparent 1px);
  background-size: 18px 18px;
}
.vl-bg-GRID .vl-shell {
  background-image:
    linear-gradient(var(--vl-color-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--vl-color-border) 1px, transparent 1px);
  background-size: 28px 28px;
}
.vl-bg-STRIPES .vl-shell {
  background-image: repeating-linear-gradient(
    135deg,
    var(--vl-color-surface-alt) 0 12px,
    transparent 12px 24px
  );
}
.vl-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--vl-gap);
  padding: var(--vl-space) calc(var(--vl-space) * 2);
  border-bottom: var(--vl-border-width) solid var(--vl-color-border);
  background: var(--vl-color-surface);
}
.vl-header-HERO_BAND .vl-bar {
  background: var(--vl-color-primary);
  color: var(--vl-color-on-primary);
  padding: calc(var(--vl-space) * 3) calc(var(--vl-space) * 2);
  border-bottom: 0;
}
.vl-header-MINIMAL .vl-bar {
  background: transparent;
  border-bottom: 0;
}
.vl-header-CENTERED_TITLE .vl-bar {
  justify-content: center;
  flex-direction: column;
  text-align: center;
}
.vl-brand {
  margin: 0;
  font-family: var(--vl-font-heading);
  font-weight: var(--vl-heading-weight);
  text-transform: var(--vl-heading-transform);
  font-variant: var(--vl-heading-variant);
  letter-spacing: var(--vl-heading-tracking);
  font-size: var(--vl-size-title);
}
.vl-links,
.vl-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: calc(var(--vl-space) / 2);
}
.vl-tabs {
  border-top: var(--vl-border-width) solid var(--vl-color-border);
  background: var(--vl-color-surface);
  padding: calc(var(--vl-space) / 2);
  justify-content: space-around;
}
.vl-navlink,
.vl-step {
  font: inherit;
  color: inherit;
  background: transparent;
  border: 0;
  cursor: pointer;
  padding: calc(var(--vl-space) / 2) var(--vl-space);
  border-radius: var(--vl-radius-control);
  font-weight: 600;
}
.vl-navlink[aria-current],
.vl-step[aria-current] {
  background: var(--vl-color-primary-soft);
  color: var(--vl-color-primary);
}
.vl-nav-TABS .vl-navlink {
  border-radius: 0;
  border-bottom: 2px solid transparent;
}
.vl-nav-TABS .vl-navlink[aria-current] {
  background: transparent;
  border-bottom-color: var(--vl-color-primary);
}
.vl-layout {
  display: grid;
  gap: var(--vl-gap);
  padding: calc(var(--vl-space) * 2);
  align-items: start;
}
.vl-with-rail {
  grid-template-columns: minmax(120px, 180px) 1fr;
}
.vl-rail {
  display: grid;
  gap: calc(var(--vl-space) / 2);
  align-content: start;
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
  border-radius: var(--vl-radius-panel);
  padding: var(--vl-space);
}
.vl-rail .vl-navlink {
  text-align: left;
}
.vl-main {
  min-width: 0;
}
.vl-title {
  margin: 0 0 var(--vl-gap);
  font-family: var(--vl-font-heading);
  font-weight: var(--vl-heading-weight);
  text-transform: var(--vl-heading-transform);
  font-variant: var(--vl-heading-variant);
  letter-spacing: var(--vl-heading-tracking);
  font-size: var(--vl-size-display);
  line-height: 1.15;
}
.vl-stepper {
  display: flex;
  flex-wrap: wrap;
  gap: calc(var(--vl-space) / 2);
  margin-bottom: var(--vl-gap);
}
.vl-step {
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
  color: var(--vl-color-text-muted);
}
.vl-zones {
  display: grid;
  gap: var(--vl-gap);
}
.vl-frame {
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
  border-radius: var(--vl-radius-panel);
  padding: calc(var(--vl-space) * 2);
  box-shadow: var(--vl-shadow);
}
.vl-shell-SINGLE_CARD .vl-main,
.vl-shell-GUIDED_STEPS .vl-main,
.vl-shell-CONVERSATIONAL .vl-main {
  max-width: 560px;
  margin: 0 auto;
  width: 100%;
}
.vl-shell-FOCUS_MODE .vl-main {
  max-width: 480px;
  margin: 0 auto;
  width: 100%;
  text-align: center;
}
.vl-shell-FOCUS_MODE .vl-zone {
  justify-items: center;
}
.vl-shell-SEARCH_FIRST .vl-zone-intro {
  text-align: center;
}
.vl-zone {
  display: grid;
  gap: var(--vl-gap);
}
.vl-two-columns {
  grid-template-columns: 1fr 1fr;
}
.vl-two-columns > :deep(.vl-h2),
.vl-two-columns > :deep(.vl-text),
.vl-two-columns > :deep(.vl-button),
.vl-two-columns > :deep(.vl-link),
.vl-two-columns > :deep(.vl-status),
.vl-two-columns > :deep(.vl-list) {
  grid-column: 1 / -1;
}
.vl-zone-tiles {
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
}
.vl-zone-gallery {
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}
.vl-zone-thread {
  gap: var(--vl-space);
}
.vl-zone-composer,
.vl-zone-search {
  display: flex;
  flex-wrap: wrap;
  gap: var(--vl-space);
  align-items: end;
}
.vl-zone-composer :deep(.vl-field),
.vl-zone-search :deep(.vl-field) {
  flex: 1 1 160px;
}
.vl-zone-search {
  max-width: 560px;
  margin: 0 auto;
  width: 100%;
}
.vl-zone-timeline {
  border-left: 2px solid var(--vl-color-primary);
  padding-left: var(--vl-gap);
}
.vl-split {
  display: grid;
  gap: var(--vl-gap);
  align-items: start;
}
.vl-shell-LIST_DETAIL .vl-split {
  grid-template-columns: 2fr 3fr;
}
.vl-shell-SPLIT_SCREEN .vl-split {
  grid-template-columns: 1fr 1fr;
}
.vl-columns {
  display: grid;
  gap: var(--vl-gap);
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  align-items: start;
}
.vl-column {
  display: grid;
  gap: var(--vl-space);
  align-content: start;
  background: var(--vl-color-surface-alt);
  border-radius: var(--vl-radius-panel);
  padding: var(--vl-space);
}
.vl-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
}
.vl-table td {
  padding: var(--vl-space);
  border-bottom: 1px solid var(--vl-color-border);
  text-align: left;
  vertical-align: top;
}
.vl-table tr:nth-child(even) td {
  background: var(--vl-color-surface-alt);
}
.vl-alert {
  margin: 0;
  color: var(--vl-color-danger);
  font-weight: 600;
}
:deep(.vl-h2) {
  margin: 0;
  font-family: var(--vl-font-heading);
  font-weight: var(--vl-heading-weight);
  text-transform: var(--vl-heading-transform);
  font-variant: var(--vl-heading-variant);
  letter-spacing: var(--vl-heading-tracking);
  font-size: var(--vl-size-title);
  line-height: 1.25;
}
:deep(.vl-text) {
  margin: 0;
}
:deep(.vl-list) {
  margin: 0;
  padding-left: 1.25em;
}
:deep(.vl-card) {
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
  border-radius: var(--vl-radius-panel);
  padding: calc(var(--vl-space) * 1.5);
  box-shadow: var(--vl-shadow);
}
:deep(.vl-bubble) {
  max-width: 78%;
  padding: var(--vl-space) calc(var(--vl-space) * 1.5);
  border-radius: var(--vl-radius-panel);
  background: var(--vl-color-surface);
  border: var(--vl-border-width) solid var(--vl-color-border);
}
:deep(.vl-person) {
  margin-left: auto;
  background: var(--vl-color-primary-soft);
}
:deep(.vl-status) {
  margin: 0;
  border-radius: var(--vl-radius-panel);
  padding: calc(var(--vl-space) * 1.5);
  font-weight: 600;
  border: max(1px, var(--vl-border-width)) solid;
}
:deep(.vl-status-ok) {
  background: var(--vl-color-success-soft);
  color: var(--vl-color-success);
  border-color: var(--vl-color-success);
}
:deep(.vl-status-error) {
  background: var(--vl-color-danger-soft);
  color: var(--vl-color-danger);
  border-color: var(--vl-color-danger);
}
:deep(.vl-field) {
  display: grid;
  gap: calc(var(--vl-space) / 2);
  font-weight: 600;
  color: var(--vl-color-text-muted);
  min-width: 0;
}
:deep(.vl-input) {
  min-height: var(--vl-control-height);
  padding: 0 var(--vl-space);
  font: inherit;
  font-weight: 400;
  color: var(--vl-color-text);
  background: var(--vl-color-surface);
  border: max(1px, var(--vl-border-width)) solid var(--vl-color-border);
  border-radius: var(--vl-radius-control);
  width: 100%;
  min-width: 0;
}
.vl-inputs-UNDERLINED :deep(.vl-input) {
  border-width: 0 0 2px;
  border-radius: 0;
  background: transparent;
  padding-left: 0;
}
.vl-inputs-FILLED :deep(.vl-input) {
  background: var(--vl-color-surface-alt);
  border-color: transparent;
}
:deep(.vl-button) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--vl-control-height);
  padding: 0 calc(var(--vl-space) * 2);
  border-radius: var(--vl-radius-control);
  font: inherit;
  font-weight: 700;
  cursor: pointer;
  border: max(1px, var(--vl-border-width)) solid transparent;
  background: var(--vl-color-primary);
  color: var(--vl-color-on-primary);
  justify-self: start;
}
.vl-buttons-OUTLINED :deep(.vl-button) {
  border-color: var(--vl-color-primary);
  color: var(--vl-color-primary);
  background: transparent;
}
.vl-buttons-SOFT :deep(.vl-button) {
  background: var(--vl-color-primary-soft);
  color: var(--vl-color-primary);
}
.vl-buttons-GHOST :deep(.vl-button) {
  background: transparent;
  color: var(--vl-color-primary);
  text-decoration: underline;
}
.vl-emphasis-BOLD :deep(.vl-button) {
  min-height: calc(var(--vl-control-height) * 1.15);
  font-size: 1.05em;
}
:deep(.vl-button:disabled) {
  opacity: 0.6;
  cursor: not-allowed;
}
:deep(.vl-link) {
  color: var(--vl-color-accent);
  font-weight: 600;
  justify-self: start;
  text-decoration: underline;
}
:deep(.vl-link[aria-disabled="true"]) {
  opacity: 0.6;
}
.vl-phone .vl-with-rail {
  grid-template-columns: 1fr;
}
.vl-phone .vl-split {
  grid-template-columns: 1fr;
}
</style>
