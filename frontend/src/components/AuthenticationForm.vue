<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import type { AuthenticationInput } from "@/api/contracts";

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
const errorSummary = ref<HTMLDivElement | null>(null);

watch(
  () => props.error,
  async (value) => {
    if (value === null) {
      return;
    }

    await nextTick();
    errorSummary.value?.focus();
  },
);

function submit(): void {
  emit("submit", {
    email: email.value,
    password: password.value,
  });
}
</script>

<template>
  <form class="grid gap-5" novalidate @submit.prevent="submit">
    <div
      v-if="error"
      ref="errorSummary"
      class="rounded-xl border border-red-300 bg-red-50 p-4 text-sm font-semibold text-red-900"
      role="alert"
      tabindex="-1"
    >
      {{ t(`auth.errors.${error}`) }}
    </div>

    <div class="grid gap-2">
      <label class="text-sm font-bold text-slate-800" for="authentication-email">
        {{ t("auth.email") }}
      </label>

      <input
        id="authentication-email"
        v-model="email"
        class="min-h-12 rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-950 shadow-sm focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2 focus-visible:outline-none"
        name="email"
        type="email"
        autocomplete="email"
        required
      />
    </div>

    <div class="grid gap-2">
      <label class="text-sm font-bold text-slate-800" for="authentication-password">
        {{ t("auth.password") }}
      </label>

      <input
        id="authentication-password"
        v-model="password"
        class="min-h-12 rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-950 shadow-sm focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2 focus-visible:outline-none"
        name="password"
        type="password"
        :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
        :minlength="mode === 'register' ? 15 : 1"
        maxlength="1024"
        required
      />

      <p v-if="mode === 'register'" class="m-0 text-sm leading-6 text-slate-600">
        {{ t("auth.passwordHint") }}
      </p>
    </div>

    <button
      class="min-h-12 rounded-xl bg-slate-950 px-5 py-3 font-bold text-white shadow-sm transition-colors hover:bg-slate-800 focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      type="submit"
      :disabled="busy"
    >
      {{ busy ? t("auth.submitting") : t(`auth.${mode}.submit`) }}
    </button>
  </form>
</template>
