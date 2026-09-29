<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useI18n } from "vue-i18n";

import { apiClient } from "@/api/client";
import type { AuthenticationInput } from "@/api/contracts";
import AuthenticationForm from "@/components/AuthenticationForm.vue";
import UiSurface from "@/components/UiSurface.vue";
import { useAuthStore } from "@/stores/auth";

const picture = "/home/accesso.webp";

const messages = {
  it: {
    eyebrow: "Tu decidi a ogni passo",
    title: "Bentornato",
    imageAlt: "Un twin, robot da compagnia bianco con il viso a schermo, in uno studio scuro",
    switchLabel: "Accedi o registrati",
  },
  en: {
    eyebrow: "You decide at every step",
    title: "Welcome back",
    imageAlt: "A twin, a white companion robot with a screen for a face, in a dark studio",
    switchLabel: "Log in or register",
  },
} as const;

const { t, locale } = useI18n({
  useScope: "global",
});
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { errorDetail, status } = storeToRefs(auth);

const copy = computed(() => messages[locale.value === "it" ? "it" : "en"]);
const busy = computed(() => status.value === "loading");
const points = computed(() => [t("auth.points.one"), t("auth.points.two"), t("auth.points.three")]);
const imageShown = ref(false);

onMounted(() => {
  if (typeof window.requestAnimationFrame === "function") {
    window.requestAnimationFrame(() => {
      imageShown.value = true;
    });
    return;
  }
  imageShown.value = true;
});

function redirectTarget(): string {
  const target = route.query.redirect;

  if (typeof target === "string" && target.startsWith("/") && !target.startsWith("//")) {
    return target;
  }

  return "/projects";
}

async function login(credentials: AuthenticationInput): Promise<void> {
  const succeeded = await auth.login(apiClient, credentials);

  if (succeeded) {
    await router.replace(redirectTarget());
  }
}
</script>

<template>
  <UiSurface
    as="section"
    tone="night"
    :padded="false"
    class="flex min-h-[clamp(600px,82vh,760px)] flex-wrap overflow-hidden"
    aria-labelledby="login-title"
    data-testid="authentication-screen"
  >
    <div class="absolute inset-x-0 -top-[6%] -bottom-[6%] -z-2 overflow-hidden">
      <img
        :src="picture"
        :alt="copy.imageAlt"
        :class="[
          'block h-full w-full object-cover object-[78%_center] motion-safe:transition-[opacity,scale] motion-safe:duration-[1200ms,2400ms] motion-safe:ease-[ease,cubic-bezier(0.16,0.8,0.2,1)]',
          imageShown ? 'scale-100 opacity-100' : 'motion-safe:scale-110 motion-safe:opacity-0',
        ]"
        data-testid="authentication-image"
      />
    </div>
    <div
      class="absolute inset-0 -z-1 max-md:bg-night/75 md:bg-[linear-gradient(90deg,rgba(15,17,18,0.2)_0%,rgba(15,17,18,0.35)_45%,rgba(15,17,18,0.2)_100%)]"
      aria-hidden="true"
    />

    <div class="flex flex-[1_1_420px] flex-col justify-between gap-10 p-[clamp(32px,5vw,64px)]">
      <p
        class="m-0 font-mono text-[11px] tracking-label text-petrol-on-night-2 uppercase motion-safe:animate-reveal"
      >
        {{ copy.eyebrow }}
      </p>
      <div class="motion-safe:animate-reveal motion-safe:[animation-delay:120ms]">
        <h1
          id="login-title"
          class="m-0 mb-4 font-display text-[clamp(30px,3.6vw,52px)] leading-[1.08] font-extralight tracking-display uppercase"
        >
          {{ copy.title }}
        </h1>
        <p
          class="m-0 max-w-[380px] border-l border-on-night/40 pl-4 text-[17px] leading-[1.55] text-on-night-2"
        >
          {{ t("auth.login.description") }}
        </p>
      </div>
      <ul
        class="m-0 flex max-w-[380px] list-none flex-col gap-3.5 p-0 text-sm leading-normal text-on-night-2 motion-safe:animate-reveal motion-safe:[animation-delay:240ms]"
      >
        <li v-for="(point, index) in points" :key="point" class="flex gap-3">
          <span
            :class="[
              'mt-[5px] inline-block size-2.5 shrink-0 rounded-full',
              index < 2
                ? 'border-[1.5px] border-dashed border-violet-on-night'
                : 'bg-petrol-on-night-2',
            ]"
            aria-hidden="true"
          />
          <span>{{ point }}</span>
        </li>
      </ul>
    </div>

    <div class="flex flex-[0_1_460px] items-center p-[clamp(20px,3vw,40px)]">
      <div
        class="flex w-full flex-col gap-[18px] rounded-sheet border border-on-night/14 bg-night/72 p-6 backdrop-blur-[18px] motion-safe:animate-reveal motion-safe:[animation-delay:200ms] sm:p-8"
      >
        <nav class="flex gap-1 rounded-pill bg-on-night/6 p-1" :aria-label="copy.switchLabel">
          <RouterLink
            to="/login"
            class="inline-flex min-h-11 flex-1 items-center justify-center rounded-pill bg-on-night px-3 text-sm font-semibold text-ink"
            data-testid="authentication-tab-login"
          >
            {{ t("navigation.login") }}
          </RouterLink>
          <RouterLink
            to="/register"
            class="inline-flex min-h-11 flex-1 items-center justify-center rounded-pill px-3 text-sm font-semibold text-on-night transition-colors duration-150 hover:bg-night-hover"
            data-testid="authentication-tab-register"
          >
            {{ t("navigation.register") }}
          </RouterLink>
        </nav>

        <AuthenticationForm mode="login" :busy="busy" :error="errorDetail" @submit="login" />

        <p class="m-0 text-center text-sm text-on-night-3">
          {{ t("auth.login.noAccount") }}
          <RouterLink
            class="inline-flex min-h-11 items-center px-1 font-semibold text-on-night underline underline-offset-4 hover:text-petrol-on-night-2"
            to="/register"
          >
            {{ t("auth.login.registerLink") }}
          </RouterLink>
        </p>
      </div>
    </div>
  </UiSurface>
</template>
