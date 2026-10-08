<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { GuidanceMode } from "@/api/contracts";
import UiButton from "@/components/UiButton.vue";
import UiSurface from "@/components/UiSurface.vue";
import { useAuthStore } from "@/stores/auth";

const messages = {
  it: {
    eyebrow: "Prima di cominciare",
    title: "Come vuoi lavorare?",
    intro:
      "Scegli come lo Studio ti accompagna nei tuoi progetti. La scelta vale per questo account e dopo la conferma non si può cambiare.",
    legend: "Modalità di lavoro",
    guided: {
      name: "Guidata",
      summary: "Un passo alla volta, con le spiegazioni.",
      points: [
        "Il brief nasce da un dialogo, una domanda alla volta.",
        "Quando approvi un passo, lo Studio prepara da solo le proposte del passo dopo.",
        "Le sezioni si aprono in ordine; dopo il primo giro restano tutte aperte.",
      ],
      audience: "Per chi non ha esperienza di progettazione.",
    },
    expert: {
      name: "Esperta",
      summary: "Tutto aperto da subito, senza spiegazioni introduttive.",
      points: [
        "Entri in qualunque sezione quando vuoi.",
        "Ogni proposta del modello parte solo quando la chiedi tu.",
        "Puoi inserire direttamente prospettive, twin, definizione e prototipo.",
      ],
      audience: "Per chi progetta di mestiere.",
    },
    warning: "Dopo la conferma non potrai più cambiare modalità.",
    confirm: "Conferma la scelta",
    confirmGuided: "Conferma: modalità guidata",
    confirmExpert: "Conferma: modalità esperta",
    saving: "Salvo la scelta…",
    error: "La scelta non è stata salvata. Riprova.",
    logout: "Esci",
  },
  en: {
    eyebrow: "Before you start",
    title: "How do you want to work?",
    intro:
      "Choose how the Studio supports you in your projects. The choice applies to this account and cannot be changed after you confirm.",
    legend: "Working mode",
    guided: {
      name: "Guided",
      summary: "One step at a time, with explanations.",
      points: [
        "The brief comes from a dialogue, one question at a time.",
        "When you approve a step, the Studio prepares the proposals for the next one by itself.",
        "Sections open in order; after the first pass they all stay open.",
      ],
      audience: "For people with no design experience.",
    },
    expert: {
      name: "Expert",
      summary: "Everything open from the start, without introductory explanations.",
      points: [
        "You enter any section whenever you want.",
        "Every model proposal starts only when you ask for it.",
        "You can enter perspectives, twins, definition and prototype yourself.",
      ],
      audience: "For people who design for a living.",
    },
    warning: "After you confirm, you will not be able to change mode.",
    confirm: "Confirm the choice",
    confirmGuided: "Confirm: guided mode",
    confirmExpert: "Confirm: expert mode",
    saving: "Saving the choice…",
    error: "The choice was not saved. Try again.",
    logout: "Log out",
  },
} as const;

const CHOICES = [
  { mode: "GUIDED", key: "guided" },
  { mode: "EXPERT", key: "expert" },
] as const;

const { locale } = useI18n({
  useScope: "global",
});
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const copy = computed(() => messages[locale.value === "it" ? "it" : "en"]);
const selected = ref<GuidanceMode | null>(null);
const saving = ref(false);
const failed = ref(false);
const errorMessage = ref<HTMLElement | null>(null);

const options = computed(() => CHOICES.map(({ mode, key }) => ({ mode, key, ...copy.value[key] })));
const confirmLabel = computed(() => {
  if (saving.value) return copy.value.saving;
  if (selected.value === "GUIDED") return copy.value.confirmGuided;
  if (selected.value === "EXPERT") return copy.value.confirmExpert;
  return copy.value.confirm;
});

function redirectTarget(): string {
  const target = route.query.redirect;

  if (typeof target === "string" && target.startsWith("/") && !target.startsWith("//")) {
    return target;
  }

  return "/projects";
}

async function confirmChoice(): Promise<void> {
  const mode = selected.value;
  if (mode === null || saving.value) return;
  saving.value = true;
  failed.value = false;
  const outcome = await auth.chooseGuidanceMode(apiClient, mode);

  if (outcome === "failed") {
    saving.value = false;
    failed.value = true;
    await nextTick();
    errorMessage.value?.focus();
    return;
  }

  try {
    await router.replace(redirectTarget());
  } finally {
    saving.value = false;
  }
}

async function logout(): Promise<void> {
  await auth.logout(apiClient).catch(() => undefined);
  await router.replace("/login");
}
</script>

<template>
  <UiSurface
    as="section"
    tone="night"
    :padded="false"
    class="overflow-hidden"
    aria-labelledby="guidance-choice-title"
    data-testid="guidance-choice"
  >
    <div
      class="mx-auto flex max-w-[1040px] flex-col gap-10 px-[clamp(20px,5vw,64px)] py-[clamp(32px,5vw,64px)]"
    >
      <div class="flex max-w-[640px] flex-col gap-4">
        <p
          class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase motion-safe:animate-reveal"
        >
          {{ copy.eyebrow }}
        </p>
        <h1
          id="guidance-choice-title"
          class="m-0 font-display text-[clamp(30px,3.6vw,52px)] leading-[1.08] font-extralight tracking-display break-words uppercase motion-safe:animate-reveal motion-safe:[animation-delay:120ms]"
        >
          {{ copy.title }}
        </h1>
        <p
          class="m-0 border-l border-on-night/40 pl-4 text-[17px] leading-[1.55] text-on-night-2 motion-safe:animate-reveal motion-safe:[animation-delay:200ms]"
        >
          {{ copy.intro }}
        </p>
      </div>

      <fieldset
        class="m-0 min-w-0 border-0 p-0 motion-safe:animate-reveal motion-safe:[animation-delay:280ms]"
      >
        <legend class="mb-3 p-0 font-mono text-[11px] tracking-label text-on-night-2 uppercase">
          {{ copy.legend }}
        </legend>
        <div class="grid gap-4 md:grid-cols-2">
          <label
            v-for="option in options"
            :key="option.mode"
            class="relative flex cursor-pointer flex-col gap-4 rounded-tile border border-night-line bg-night-raised p-5 transition-colors duration-150 hover:border-night-line-strong has-checked:border-petrol-on-night has-checked:bg-petrol-on-night/8 has-checked:ring-1 has-checked:ring-petrol-on-night has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-petrol-on-night has-disabled:cursor-not-allowed sm:p-6"
            :data-testid="`guidance-option-${option.key}`"
          >
            <input
              v-model="selected"
              class="peer sr-only"
              type="radio"
              name="guidance-mode"
              :value="option.mode"
              :disabled="saving"
              :aria-labelledby="`guidance-${option.key}-name`"
              :aria-describedby="`guidance-${option.key}-details`"
            />
            <span
              class="pointer-events-none absolute top-5 right-5 size-6 rounded-full border-2 border-on-night-3 transition-colors duration-150 peer-checked:border-8 peer-checked:border-petrol-on-night sm:top-6 sm:right-6"
              aria-hidden="true"
            />
            <span
              :id="`guidance-${option.key}-name`"
              class="pr-10 text-2xl leading-tight font-semibold text-on-night"
            >
              {{ option.name }}
            </span>
            <span :id="`guidance-${option.key}-details`" class="flex grow flex-col gap-4">
              <span class="text-[17px] leading-[1.45] text-on-night">{{ option.summary }}</span>
              <span class="flex flex-col gap-2.5" role="list">
                <span
                  v-for="point in option.points"
                  :key="point"
                  class="flex gap-3 text-[15px] leading-normal text-on-night-2"
                  role="listitem"
                >
                  <span
                    class="mt-2 inline-block size-1.5 shrink-0 rounded-full bg-petrol-on-night-2"
                    aria-hidden="true"
                  />
                  <span>{{ point }}</span>
                </span>
              </span>
              <span class="mt-auto border-t border-night-line pt-4 text-sm text-on-night-3">
                {{ option.audience }}
              </span>
            </span>
          </label>
        </div>
      </fieldset>

      <div class="flex flex-col gap-4">
        <p id="guidance-choice-warning" class="m-0 text-sm font-semibold text-warn-on-night">
          {{ copy.warning }}
        </p>
        <p
          v-if="failed"
          ref="errorMessage"
          class="m-0 rounded-field border border-fail-on-night/40 bg-fail-on-night/10 px-4 py-3 text-sm font-semibold text-fail-on-night"
          role="alert"
          tabindex="-1"
          data-testid="guidance-choice-error"
        >
          {{ copy.error }}
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <UiButton
            size="lg"
            :disabled="selected === null || saving"
            aria-describedby="guidance-choice-warning"
            data-testid="guidance-confirm"
            @click="confirmChoice"
          >
            {{ confirmLabel }}
          </UiButton>
          <UiButton
            v-if="!auth.isLocal"
            variant="quiet"
            :disabled="saving"
            data-testid="guidance-choice-logout"
            @click="logout"
          >
            {{ copy.logout }}
          </UiButton>
        </div>
      </div>
    </div>
  </UiSurface>
</template>
