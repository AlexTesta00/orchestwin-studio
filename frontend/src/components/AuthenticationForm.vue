<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { AuthenticationInput } from "@/api/contracts";
import UiButton from "./UiButton.vue";

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

function submit(): void {
  validationError.value = null;
  if (props.busy) return;
  if (props.mode === "register" && [...password.value].length < 15) {
    validationError.value = "password_too_short";
    return;
  }
  if ([...password.value].length > 1024) {
    validationError.value = "password_too_long";
    return;
  }
  emit("submit", {
    email: email.value,
    password: password.value,
  });
}
</script>

<template>
  <form class="grid gap-5" novalidate @submit.prevent="submit">
    <div
      v-if="visibleError"
      ref="errorSummary"
      class="rounded-panel border border-fail-line bg-fail-bg px-4 py-3 text-sm font-semibold text-fail-dark"
      role="alert"
      tabindex="-1"
    >
      {{ t(`auth.errors.${visibleError}`) }}
    </div>

    <div class="grid gap-2">
      <label class="text-sm font-semibold" for="authentication-email">
        {{ t("auth.email") }}
      </label>

      <input
        id="authentication-email"
        v-model="email"
        class="min-h-11 rounded-control border border-field bg-surface px-4 py-2.5 text-[15px] text-ink"
        name="email"
        type="email"
        autocomplete="email"
        required
      />
    </div>

    <div class="grid gap-2">
      <label class="text-sm font-semibold" for="authentication-password">
        {{ t("auth.password") }}
      </label>

      <input
        id="authentication-password"
        v-model="password"
        class="min-h-11 rounded-control border border-field bg-surface px-4 py-2.5 text-[15px] text-ink"
        name="password"
        type="password"
        :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
        :minlength="mode === 'register' ? 15 : 1"
        :aria-invalid="visibleError?.startsWith('password_') ? 'true' : undefined"
        :aria-describedby="mode === 'register' ? 'password-hint' : undefined"
        maxlength="1024"
        required
      />

      <p v-if="mode === 'register'" id="password-hint" class="m-0 text-sm leading-6 text-ink-3">
        {{ t("auth.passwordHint") }}
      </p>
    </div>

    <UiButton type="submit" full :disabled="busy">
      {{ busy ? t("auth.submitting") : t(`auth.${mode}.submit`) }}
    </UiButton>
  </form>
</template>
