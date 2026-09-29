<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { AuthenticationInput } from "@/api/contracts";
import UiButton from "./UiButton.vue";
import { useSurface } from "./UiSurface.vue";

const props = defineProps<{
  mode: "login" | "register";
  busy: boolean;
  error: string | null;
}>();

const emit = defineEmits<{
  submit: [credentials: AuthenticationInput];
}>();

const { t } = useI18n({
  useScope: "global",
});

const MINIMUM_PASSWORD_LENGTH = 8;
const MAXIMUM_PASSWORD_LENGTH = 1024;
const UPPERCASE_LETTER = /\p{Uppercase}/u;
const SPECIAL_CHARACTER = /[^\p{L}\p{N}\p{White_Space}]/u;

const palettes = {
  light: {
    label: "text-ink-2",
    field: "border-field bg-surface text-ink",
    hint: "text-ink-3",
    error: "border-fail-line bg-fail-bg text-fail-dark",
  },
  night: {
    label: "text-on-night-2",
    field: "border-on-night/18 bg-on-night/4 text-on-night",
    hint: "text-on-night-3",
    error: "border-fail-on-night/40 bg-fail-on-night/10 text-fail-on-night",
  },
};

const context = useSurface(() => undefined);
const palette = computed(() => palettes[context.value]);
const labelClasses = computed(() => [
  "font-mono text-[11px] tracking-label uppercase",
  palette.value.label,
]);
const fieldClasses = computed(() => [
  "h-[52px] w-full rounded-field border px-4 text-base",
  palette.value.field,
]);

const email = ref("");
const password = ref("");
const validationError = ref<string | null>(null);
const visibleError = computed(() => validationError.value ?? props.error);
const errorSummary = ref<HTMLDivElement | null>(null);

watch(visibleError, async (value) => {
  if (value === null) {
    return;
  }

  await nextTick();
  errorSummary.value?.focus();
});

function passwordError(): string | null {
  const length = [...password.value].length;
  const registering = props.mode === "register";
  if (registering && length < MINIMUM_PASSWORD_LENGTH) return "password_too_short";
  if (length > MAXIMUM_PASSWORD_LENGTH) return "password_too_long";
  if (registering && !UPPERCASE_LETTER.test(password.value)) return "password_missing_uppercase";
  if (registering && !SPECIAL_CHARACTER.test(password.value)) return "password_missing_special";
  return null;
}

function submit(): void {
  validationError.value = null;
  if (props.busy) return;
  validationError.value = passwordError();
  if (validationError.value !== null) return;
  emit("submit", {
    email: email.value,
    password: password.value,
  });
}
</script>

<template>
  <form class="flex flex-col gap-[18px]" novalidate @submit.prevent="submit">
    <div
      v-if="visibleError"
      ref="errorSummary"
      :class="['rounded-field border px-4 py-3 text-sm font-semibold', palette.error]"
      role="alert"
      tabindex="-1"
    >
      {{ t(`auth.errors.${visibleError}`) }}
    </div>

    <div class="flex flex-col gap-2">
      <label :class="labelClasses" for="authentication-email">
        {{ t("auth.email") }}
      </label>

      <input
        id="authentication-email"
        v-model="email"
        :class="fieldClasses"
        name="email"
        type="email"
        autocomplete="email"
        required
      />
    </div>

    <div class="flex flex-col gap-2">
      <label :class="labelClasses" for="authentication-password">
        {{ t("auth.password") }}
      </label>

      <input
        id="authentication-password"
        v-model="password"
        :class="fieldClasses"
        name="password"
        type="password"
        :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
        :minlength="mode === 'register' ? MINIMUM_PASSWORD_LENGTH : 1"
        :aria-invalid="visibleError?.startsWith('password_') ? 'true' : undefined"
        :aria-describedby="mode === 'register' ? 'password-hint' : undefined"
        :maxlength="MAXIMUM_PASSWORD_LENGTH"
        required
      />

      <p
        v-if="mode === 'register'"
        id="password-hint"
        :class="['m-0 text-[13px] leading-normal', palette.hint]"
      >
        {{ t("auth.passwordHint") }}
      </p>
    </div>

    <UiButton type="submit" size="lg" full class="mt-1" :disabled="busy">
      {{ busy ? t("auth.submitting") : t(`auth.${mode}.submit`) }}
    </UiButton>
  </form>
</template>
