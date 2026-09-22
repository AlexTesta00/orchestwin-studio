<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import UiButton from "@/components/UiButton.vue";
import UiCard from "@/components/UiCard.vue";
import UiClaimLabel from "@/components/UiClaimLabel.vue";
import { useAuthStore } from "@/stores/auth";

const twinKeys = ["brief", "critique", "proof"] as const;
const stepKeys = [
  "brief",
  "team",
  "twins",
  "requirements",
  "design",
  "architecture",
  "sources",
  "execution",
] as const;
const objectiveKeys = [
  "results",
  "minimal",
  "clear",
  "stepwise",
  "plain",
  "accessible",
  "honest",
] as const;
const userKeys = ["primary", "secondary"] as const;

const auth = useAuthStore();
const { t } = useI18n({ useScope: "global" });

const reducedMotion =
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const entryTarget = computed(() => (auth.isAuthenticated ? "/projects" : "/register"));

const entryClasses =
  "inline-flex min-h-11 items-center justify-center rounded-control bg-action px-6 py-3 text-[15px] font-semibold text-white transition-colors hover:bg-action-hover";

function revealTwins(): void {
  document
    .getElementById("twin")
    ?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}
</script>

<template>
  <div class="grid gap-20 py-10 sm:gap-24 sm:py-16">
    <section class="grid gap-6" aria-labelledby="home-title">
      <p class="m-0 font-mono text-xs tracking-wide text-ink-3 uppercase">
        {{ t("home.eyebrow") }}
      </p>
      <h1
        id="home-title"
        class="m-0 max-w-[22ch] text-[40px] leading-[1.06] font-semibold tracking-title sm:text-[58px]"
      >
        {{ t("home.title") }}
      </h1>
      <p class="m-0 max-w-[60ch] text-lg leading-relaxed text-ink-2 sm:text-xl">
        {{ t("home.lead") }}
      </p>
      <div class="flex flex-wrap gap-3">
        <RouterLink :to="entryTarget" :class="entryClasses" data-testid="home-enter">
          {{ t("home.enter") }}
        </RouterLink>
        <UiButton variant="secondary" data-testid="home-twins-link" @click="revealTwins">
          {{ t("home.twinsLink") }}
        </UiButton>
      </div>
    </section>

    <section class="grid gap-5 md:grid-cols-2" aria-labelledby="home-rule-one">
      <UiCard>
        <div class="grid gap-3">
          <p class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("home.rules.one.label") }}
          </p>
          <h2 id="home-rule-one" class="m-0 text-2xl leading-tight font-semibold tracking-block">
            {{ t("home.rules.one.title") }}
          </h2>
          <p class="m-0 leading-relaxed text-ink-2">{{ t("home.rules.one.text") }}</p>
        </div>
      </UiCard>
      <UiCard>
        <div class="grid gap-3">
          <p class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t("home.rules.two.label") }}
          </p>
          <h2 class="m-0 text-2xl leading-tight font-semibold tracking-block">
            {{ t("home.rules.two.title") }}
          </h2>
          <p class="m-0 leading-relaxed text-ink-2">{{ t("home.rules.two.text") }}</p>
          <div class="flex flex-wrap gap-2">
            <UiClaimLabel kind="hypothesis" />
            <UiClaimLabel kind="proof" />
          </div>
        </div>
      </UiCard>
    </section>

    <section id="twin" class="grid scroll-mt-24 gap-10" aria-labelledby="home-twins-title">
      <div class="grid gap-4">
        <p class="m-0 font-mono text-xs tracking-wide text-ink-3 uppercase">
          {{ t("home.twins.eyebrow") }}
        </p>
        <h2
          id="home-twins-title"
          class="m-0 max-w-[26ch] text-[32px] leading-[1.12] font-semibold tracking-title sm:text-[40px]"
        >
          {{ t("home.twins.title") }}
        </h2>
        <p class="m-0 max-w-[62ch] text-lg leading-relaxed text-ink-2">
          {{ t("home.twins.lead") }}
        </p>
      </div>
      <div class="grid gap-6 md:grid-cols-3">
        <figure
          v-for="key in twinKeys"
          :key="key"
          class="m-0 overflow-hidden rounded-card border border-line bg-surface shadow-card"
          data-testid="home-twin"
        >
          <div class="aspect-[3/2] bg-surface-2">
            <img
              v-if="reducedMotion"
              class="h-full w-full object-cover"
              :src="`/home/twin-${key}.webp`"
              :alt="t(`home.twins.items.${key}.alt`)"
            />
            <video
              v-else
              class="h-full w-full object-cover"
              :src="`/home/twin-${key}.mp4`"
              :poster="`/home/twin-${key}.webp`"
              :aria-label="t(`home.twins.items.${key}.alt`)"
              autoplay
              muted
              loop
              playsinline
            />
          </div>
          <figcaption class="grid gap-2 p-6">
            <p class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
              {{ t(`home.twins.items.${key}.label`) }}
            </p>
            <h3 class="m-0 text-[19px] font-semibold tracking-block">
              {{ t(`home.twins.items.${key}.title`) }}
            </h3>
            <p class="m-0 text-[15px] leading-relaxed text-ink-2">
              {{ t(`home.twins.items.${key}.text`) }}
            </p>
          </figcaption>
        </figure>
      </div>
    </section>

    <section class="grid gap-8" aria-labelledby="home-steps-title">
      <div class="grid gap-4">
        <p class="m-0 font-mono text-xs tracking-wide text-ink-3 uppercase">
          {{ t("home.steps.eyebrow") }}
        </p>
        <h2
          id="home-steps-title"
          class="m-0 text-[32px] leading-[1.12] font-semibold tracking-title sm:text-[40px]"
        >
          {{ t("home.steps.title") }}
        </h2>
      </div>
      <ol
        class="m-0 grid list-none gap-px overflow-hidden rounded-card border border-line bg-line p-0 sm:grid-cols-2 lg:grid-cols-4"
      >
        <li
          v-for="(key, index) in stepKeys"
          :key="key"
          class="grid content-start gap-2 bg-surface px-6 py-6"
          data-testid="home-step"
        >
          <span class="font-mono text-xs text-ink-3">{{ String(index + 1).padStart(2, "0") }}</span>
          <strong class="text-[16.5px] font-semibold tracking-block">
            {{ t(`home.steps.items.${key}.title`) }}
          </strong>
          <span class="text-[14.5px] leading-relaxed text-ink-2">
            {{ t(`home.steps.items.${key}.text`) }}
          </span>
        </li>
      </ol>
    </section>

    <section class="grid gap-8" aria-labelledby="home-objectives-title">
      <div class="grid gap-4">
        <p class="m-0 font-mono text-xs tracking-wide text-ink-3 uppercase">
          {{ t("home.objectives.eyebrow") }}
        </p>
        <h2
          id="home-objectives-title"
          class="m-0 text-[32px] leading-[1.12] font-semibold tracking-title sm:text-[40px]"
        >
          {{ t("home.objectives.title") }}
        </h2>
      </div>
      <ul class="m-0 grid list-none gap-5 p-0 sm:grid-cols-2 lg:grid-cols-3">
        <li
          v-for="key in objectiveKeys"
          :key="key"
          class="grid content-start gap-2 rounded-panel border border-line bg-surface px-6 py-5"
        >
          <h3 class="m-0 text-[17px] font-semibold tracking-block">
            {{ t(`home.objectives.items.${key}.title`) }}
          </h3>
          <p class="m-0 text-[15px] leading-relaxed text-ink-2">
            {{ t(`home.objectives.items.${key}.text`) }}
          </p>
        </li>
      </ul>
    </section>

    <section class="grid gap-5 md:grid-cols-2" aria-labelledby="home-user-primary">
      <UiCard v-for="key in userKeys" :key="key">
        <div class="grid gap-3">
          <p class="m-0 font-mono text-[11px] tracking-wide text-ink-3 uppercase">
            {{ t(`home.users.${key}.label`) }}
          </p>
          <h2
            :id="`home-user-${key}`"
            class="m-0 text-2xl leading-tight font-semibold tracking-block"
          >
            {{ t(`home.users.${key}.title`) }}
          </h2>
          <p class="m-0 leading-relaxed text-ink-2">{{ t(`home.users.${key}.text`) }}</p>
        </div>
      </UiCard>
    </section>

    <section aria-labelledby="home-closing-title">
      <UiCard tone="elevated">
        <div class="grid justify-items-center gap-4 py-4 text-center">
          <h2
            id="home-closing-title"
            class="m-0 max-w-[24ch] text-[28px] leading-[1.15] font-semibold tracking-title sm:text-[34px]"
          >
            {{ t("home.closing.title") }}
          </h2>
          <p class="m-0 max-w-[52ch] text-[17px] leading-relaxed text-ink-2">
            {{ t("home.closing.text") }}
          </p>
          <RouterLink :to="entryTarget" :class="entryClasses" data-testid="home-enter-closing">
            {{ t("home.enter") }}
          </RouterLink>
        </div>
      </UiCard>
    </section>

    <footer
      class="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-6 font-mono text-[12.5px] text-ink-3"
    >
      <span>{{ t("home.footer.thesis") }}</span>
      <span>{{ t("home.footer.stack") }}</span>
    </footer>
  </div>
</template>
